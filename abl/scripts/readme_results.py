"""Render the README 'Results' block from reports/*.json (numbers only ever come from the run outputs)."""
from __future__ import annotations

import json
import sys

import pandas as pd

from common import paths
from common.mdtable import md_table


def _load(name: str):
    p = paths.reports_dir() / name
    return json.loads(p.read_text()) if p.exists() else None


def render() -> str:
    sim, pig, sc, fh = _load("campaign_sim.json"), _load("campaign_pig_cleveland.json"), _load("scorecard.json"), _load("final_holdout_sim.json")
    out = ["### Results of the first full run (`make campaign`, deterministic stub agents, seed 0)", ""]
    if sim:
        a = sim["arms"]
        n = sim["null"]
        out += [f"**Simulation** ({sim['splits'][0]['n_train']}–{sim['splits'][-1]['n_train']} training animals per split, "
                f"{len(sim['splits'])} forward-in-time splits, generation 5 sealed). Champion frozen at h2 = {sim['champion']['h2']:.3f}.", "",
                "| arm | what it measures | result |", "|---|---|---|",
                f"| A champion | true accuracy cor(GEBV, TBV) on the next generation | **{a['A_champion']['true_accuracy']:.3f}** (LR ρ {a['A_champion']['lr_rho']:.3f}, dispersion b {a['A_champion']['dispersion_b']:.2f}, predictive r {a['A_champion']['predictive_r']:.3f}) |",
                f"| E shuffled labels | champion on labels shuffled within generation | true accuracy {a['E_shuffled_labels']['champion_on_shuffled']['true_accuracy']:+.3f}; LR ρ still {n['mean']:.2f} ± {n['sd']:.2f} (not null-calibrated); predictive r {n['pred_mean']:+.3f} ± {n['pred_sd']:.3f} |",
                f"| E shuffled labels (loop) | false promotions by the full ABL loop on shuffled data | **{a['E_shuffled_labels']['false_promotions']}** of {a['E_shuffled_labels']['full_evaluations']} full evaluations |",
                f"| F random SNP subset | false promotions of 30 % random panels | **{a['F_random_snp']['false_promotions']}** of {a['F_random_snp']['full_evaluations']} |",
                f"| B random operators | promotions / full evaluations, best ΔOOS | {a['B_random_ops']['promoted']} / {a['B_random_ops']['full_evaluations']}, best ΔOOS {a['B_random_ops']['best_delta_oos']:+.4f} (best CI low {a['B_random_ops']['best_ci_low']:+.4f}) |",
                f"| C one-shot LLM | one proposal, no loop | {a['C_one_shot_llm']['promoted']} promoted of {a['C_one_shot_llm']['full_evaluations']} evaluated |",
                f"| D ABL loop | {a['D_abl_loop']['proposals']} proposals → {a['D_abl_loop']['candidates']} candidates → {a['D_abl_loop']['full_evaluations']} full evaluations | **{a['D_abl_loop']['promoted']} promoted**, best ΔOOS {a['D_abl_loop']['best_delta_oos']:+.4f} (CI low {a['D_abl_loop']['best_ci_low']:+.4f}); Critic rejected {a['D_abl_loop']['critic_rejects']}, duplicates skipped {a['D_abl_loop']['duplicates']}, NEED_OPERATOR {a['D_abl_loop']['need_operator']}, validity rejects {a['D_abl_loop']['validity_rejects']} |", ""]
        ev = a["D_abl_loop"].get("evaluated", [])
        if ev:
            df = pd.DataFrame(ev)[["dsl_text", "mechanism_cluster", "state", "delta_oos", "delta_oos_ci_low"]]
            out += ["Full evaluations in the ABL loop (sim):", "", md_table(df), ""]
    if fh:
        out += ["**Sealed holdout (sim), opened once after the campaign:**", "", md_table(pd.DataFrame(fh)[[c for c in ("model", "dsl", "holdout_n", "true_accuracy", "predictive_r", "lr_rho", "delta_predictive_r_vs_champion") if c in fh[0]]]), ""]
    if pig:
        a = pig["arms"]
        out += [f"**Cleveland 2012 public pig data** ({pig['splits'][0]['n_train']}–{pig['splits'][-1]['n_train']} training animals per split over {len(pig['splits'])} genomic family blocks, trait t1, no pedigree/map/dates). "
                f"Champion frozen at h2 = {pig['champion']['h2']:.3f}.", "",
                f"- A champion: predictive r {a['A_champion']['predictive_r']:.3f}, LR ρ {a['A_champion']['lr_rho']:.3f}, dispersion b {a['A_champion']['dispersion_b']:.2f}; shuffled-label null predictive r {pig['null']['pred_mean']:+.3f} ± {pig['null']['pred_sd']:.3f}.",
                f"- D ABL loop: {a['D_abl_loop']['proposals']} proposals, {a['D_abl_loop']['full_evaluations']} full evaluations, **{a['D_abl_loop']['promoted']} promoted**; best ΔOOS {a['D_abl_loop']['best_delta_oos']:+.4f} (CI low {a['D_abl_loop']['best_ci_low']:+.4f}).",
                f"- E shuffled labels: {a['E_shuffled_labels']['false_promotions']} false promotions; F random SNP: {a['F_random_snp']['false_promotions']} false promotions; B random operators: {a['B_random_ops']['promoted']} promoted of {a['B_random_ops']['full_evaluations']}.", ""]
    if sc:
        df = pd.DataFrame(sc)[["dataset", "arm", "proposals", "valid_per_100_proposals", "full_evaluations", "promoted", "best_delta_oos", "best_delta_oos_ci_low",
                               "false_promotions_on_negative_controls", "critic_reject_rate_on_leak_probes", "mechanism_clusters", "reproducible_from_hash", "tokens", "compute_seconds"]]
        out += ["**System scorecard** (`reports/scorecard.md`, DESIGN.md §3.4):", "", md_table(df), ""]
    out += ["**What the harness rejected and why.** Every full evaluation above that ended `rejected` failed at least one mandatory gate; the limiting gate and the "
            "Analyst's diagnosis are in `registry/packages/<candidate_id>.md` and the best pig package is copied to "
            "`reports/BreedingPackage_pig_cleveland.md`. The leak probes (negative_control_leak) were rejected by the Critic before any code was written.",
            "", "_Agents in this run were the deterministic stubs (no API credentials in the build environment); rerun `make campaign` with `ANTHROPIC_API_KEY` set to use `claude-opus-5` with the same prompts, gates and ledger._"]
    return "\n".join(out)


if __name__ == "__main__":
    print(render())
    sys.exit(0)
