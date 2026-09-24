"""The one sanctioned read of holdout/: after a campaign, re-score the promoted candidates and the
champion on the sealed generation. Logged with policy flag holdout_final_read. Never called by agents."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import paths
from dsl import compile_program, parse, validate
from engine import Evaluator
from genoframe import GenoFrame, Split
from genoframe.seal import read_sealed_for_final_table
from registry import Registry, append_event


def final_table(reg: Registry, bundle_name: str, dev_frame: GenoFrame, priors: dict, trait: str, champion, campaign_ids: list[str]) -> pd.DataFrame:
    held = read_sealed_for_final_table(bundle_name)
    append_event(agent="final_table", action="holdout_final_read", campaign_id=None, input_obj=bundle_name, output_obj={"n": int(held.phenotypes.animal_id.nunique())},
                 summary="Sealed holdout opened once for the final table", policy_flags=["holdout_final_read"], registry=reg)
    # assemble a frame = development animals + holdout generation, then one split whose test set is the holdout
    full = GenoFrame(pd.concat([dev_frame.animals, held.animals[~held.animals.animal_id.isin(dev_frame.animals.animal_id)]]).reset_index(drop=True),
                     pd.concat([dev_frame.phenotypes, held.phenotypes]).reset_index(drop=True),
                     np.vstack([dev_frame.genotypes, held.genotypes[~np.isin(held.geno_ids, dev_frame.geno_ids)]]),
                     np.concatenate([dev_frame.geno_ids, held.geno_ids[~np.isin(held.geno_ids, dev_frame.geno_ids)]]),
                     dev_frame.markers, dict(dev_frame.calendar), dev_frame.genotype_source, dict(dev_frame.versions), dict(dev_frame.meta),
                     pd.concat([dev_frame.true_bv, held.true_bv]).reset_index(drop=True) if dev_frame.true_bv is not None and held.true_bv is not None else None)
    hold_ids = sorted(set(held.phenotypes.animal_id) & set(full.geno_ids))
    cutoff = int(dev_frame.animals.birth_t.max())
    train_ph = dev_frame.phenotypes[(dev_frame.phenotypes.trait == trait) & (dev_frame.phenotypes.available_at <= cutoff)]
    from genoframe.splitter import _full_sibs_and_parents
    purged = _full_sibs_and_parents(full.animals, set(hold_ids))
    train_ids = sorted(set(train_ph.animal_id) - purged)
    split = Split(cutoff, int(held.phenotypes.available_at.max()), train_ids, hold_ids, sorted(purged), "contract")
    ev = Evaluator(full.public_view(), priors, trait, champion=champion)
    truth = full.true_bv[full.true_bv.trait == trait].set_index("animal_id").tbv if full.true_bv is not None else None
    rows = []
    specs = [("champion", "champion()")]
    for cid in campaign_ids:
        df = reg.df("SELECT c.candidate_id, c.dsl_text FROM candidates c JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=? AND c.state='promoted'", (cid,))
        specs += [(r.candidate_id, r.dsl_text) for r in df.itertuples()]
    champ_st = None
    for name, text in specs:
        spec = compile_program(validate(parse(text), known_priors=set(priors), has_pedigree=ev.has_pedigree))
        st = ev.evaluate(spec, split)
        if name == "champion":
            champ_st = st
        row = {"model": name, "dsl": text, "holdout_n": st.n_test, "lr_rho": st.rho, "dispersion_b": st.dispersion, "predictive_r": st.extra["predictive_r"],
               "delta_predictive_r_vs_champion": st.extra["predictive_r"] - champ_st.extra["predictive_r"]}
        if truth is not None:
            row["true_accuracy"] = float(np.corrcoef(st.u_partial.to_numpy(), truth.loc[st.u_partial.index].to_numpy())[0, 1])
        rows.append(row)
    df = pd.DataFrame(rows)
    out = paths.reports_dir() / f"final_holdout_{bundle_name}.json"
    out.write_text(json.dumps(df.to_dict("records"), indent=1, default=str))
    return df
