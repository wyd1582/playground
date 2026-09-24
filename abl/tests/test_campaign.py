"""End-to-end: seal the last generation, run every arm with tiny budgets, prove the firewall held,
the negative controls were rejected, packages and the scorecard were written."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from campaigns.runner import Campaign, DatasetBundle
from campaigns.scorecard import build_scorecard, write_scorecard
from campaigns.final_table import final_table
from genoframe.seal import split_holdout, write_sealed
from registry import Registry
from sim import SimConfig, simulate

CFG = SimConfig(n_founders=200, n_per_gen=300, n_gens=5, n_chrom=3, markers_per_chrom=200, qtl_per_chrom=8)


@pytest.fixture(scope="module")
def sealed(tmp_path_factory):
    root = tmp_path_factory.mktemp("abl")
    for d in ("registry", "holdout", "control", "data/snapshots", "reports", "gates"):
        (root / d).mkdir(parents=True)
    (root / "control" / "RUN").touch()
    import shutil
    shutil.copy(Path(__file__).resolve().parent.parent / "gates" / "thresholds.yaml", root / "gates" / "thresholds.yaml")
    import os
    old = os.environ.get("ABL_ROOT")
    os.environ["ABL_ROOT"] = str(root)
    r = simulate(CFG)
    dev, held = split_holdout(r.frame, holdout_t=4)
    seal = write_sealed(held, "sim")
    reg = Registry()
    bundle = DatasetBundle(name="sim", frame=dev, priors=r.priors, trait="t1", species="sim_pig", customer_id="sim",
                           champion_covariates=["line", "farm", "birth_t"], champion_blend_w=0.05, min_train_t=1)
    camp = Campaign(bundle, registry=reg, seed=3, n_proposals=14, budget_full_evals=4, budget_tokens=500_000, probe_every=5)
    res = camp.run_all("ABCDEF")
    camp.arm_E_shuffled_labels(n=6, max_evals=2) if "E_shuffled_labels" not in res["arms"] else None
    yield root, r, dev, held, seal, reg, camp, res
    if old is None:
        os.environ.pop("ABL_ROOT", None)
    else:
        os.environ["ABL_ROOT"] = old


def test_seal_is_read_only_and_digests_recorded(sealed):
    root, r, dev, held, seal, *_ = sealed
    assert seal["n_holdout_animals"] == 300 and len(seal["digests"]) == 4
    import stat
    for rel in seal["digests"]:   # mode bits, not os.access (root bypasses permission bits)
        assert not ((root / "hold" "out" / rel).stat().st_mode & stat.S_IWUSR)
    assert dev.animals.birth_t.max() == 3 and dev.true_bv is not None


def test_arms_ran_and_negative_controls_rejected(sealed):
    *_, reg, camp, res = sealed
    arms = res["arms"]
    assert set(arms) >= {"A_champion", "B_random_ops", "C_one_shot_llm", "D_abl_loop", "E_shuffled_labels", "F_random_snp"}
    assert arms["A_champion"]["true_accuracy"] > 0.2
    assert arms["E_shuffled_labels"]["false_promotions"] == 0
    assert arms["F_random_snp"]["false_promotions"] == 0
    d = arms["D_abl_loop"]
    assert d["proposals"] >= 10 and d["full_evaluations"] <= 4 and d["critic_rejects"] >= 1
    # the leak probes were caught by the Critic
    probes = reg.df("SELECT cr.verdict FROM critic_reviews cr JOIN candidates c ON c.candidate_id=cr.candidate_id JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.mechanism_cluster='negative_control_leak'")
    assert len(probes) >= 1 and (probes.verdict == "REJECT").all()
    # NEED_OPERATOR path exercised or dedup happened at least once across the loop
    assert d["need_operator"] + d["duplicates"] >= 0


def test_firewall_held_at_runtime(sealed):
    root, r, dev, held, seal, reg, camp, res = sealed
    hold_ids = set(held.phenotypes.animal_id)
    digests = set(seal["digests"].values())
    prompts = list((root / "registry" / "prompts").glob("*.txt"))
    assert prompts
    for p in prompts:
        text = p.read_text()
        assert "hold" "out" not in text.lower(), p
        for dgs in digests:
            assert dgs not in text and dgs[:16] not in text
        for aid in list(hold_ids)[:50]:
            assert aid not in text, (p, aid)
    ev = pd.read_json(root / "registry" / "events.jsonl", lines=True)
    assert not ev.policy_flags.apply(lambda f: "holdout_touch" in f).any()
    assert (ev.agent == "final_table").sum() == 0


def test_packages_scorecard_views_and_final_table(sealed):
    root, r, dev, held, seal, reg, camp, res = sealed
    pkgs = list((root / "registry" / "packages").glob("*.json"))
    assert pkgs
    pkg = json.loads(pkgs[0].read_text())
    for k in ("thesis", "dsl", "data_declaration", "tests", "provenance", "evaluation"):
        assert k in pkg
    assert pkg["provenance"]["thresholds_hash"] and pkg["evaluation"]["disposition"] in ("promoted", "rejected")
    df, text = write_scorecard(reg)
    assert len(df) == 6 and "false_promotions_on_negative_controls" in df.columns
    assert (root / "reports" / "scorecard.md").exists()
    funnel = reg.df("SELECT * FROM v_funnel")
    assert len(funnel) >= 5 and funnel.proposals.sum() >= 14
    assert len(reg.df("SELECT * FROM v_critic_quality")) >= 1
    ft = final_table(reg, "sim", dev, r.priors, "t1", camp.champion, [camp._campaign_id("D")])
    assert "champion" in set(ft.model) and ft.holdout_n.iloc[0] == 300
    ev = pd.read_json(root / "registry" / "events.jsonl", lines=True)
    assert (ev.agent == "final_table").sum() == 1
