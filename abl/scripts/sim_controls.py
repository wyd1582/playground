"""make sim-controls — simulated campaign with known true BVs: champion, random-operator challenger,
shuffled-label negative control, random-SNP negative control (DESIGN.md P0 deliverable 1)."""
from __future__ import annotations

import json
import sys

import pandas as pd

from campaigns.runner import Campaign
from campaigns.scorecard import write_scorecard
from common import paths
from common.mdtable import md_table
from registry import Registry
from scripts._common import sim_bundle


def write_sim_controls_report(res: dict) -> str:
    rows = [
        {"arm": "A champion (frozen ssGBLUP)", **{k: v for k, v in res["arms"]["A_champion"].items() if k in ("true_accuracy", "lr_rho", "predictive_r", "dispersion_b")}},
        {"arm": "B random-operator search", "full_evaluations": res["arms"]["B_random_ops"]["full_evaluations"], "promoted": res["arms"]["B_random_ops"]["promoted"],
         "best_delta_oos": res["arms"]["B_random_ops"]["best_delta_oos"]},
        {"arm": "E shuffled labels (loop)", "false_promotions": res["arms"]["E_shuffled_labels"]["false_promotions"],
         **{f"champion_on_shuffled_{k}": v for k, v in res["arms"]["E_shuffled_labels"]["champion_on_shuffled"].items() if k in ("true_accuracy", "lr_rho", "predictive_r")}},
        {"arm": "F random SNP subset", "false_promotions": res["arms"]["F_random_snp"]["false_promotions"], "full_evaluations": res["arms"]["F_random_snp"]["full_evaluations"]},
    ]
    df = pd.DataFrame(rows)
    out = paths.reports_dir(); out.mkdir(exist_ok=True)
    md = ["# sim-controls — true vs estimated accuracy (simulated pig, last generation sealed)", "",
          f"Run `{res.get('run_tag')}` seed {res.get('seed')} · champion frozen: `{json.dumps(res['champion'])}`", "",
          f"Null (champion on labels shuffled within birth_t, {len(res['null']['seeds'])} seeds): LR rho {res['null']['mean']:.3f} ± {res['null']['sd']:.3f}; "
          f"predictive r {res['null']['pred_mean']:.3f} ± {res['null']['pred_sd']:.3f}. The LR rho of a null model is far from zero — "
          "it is not null-calibrated — which is why gate 1 uses this empirical null and gate 2 uses the predictive correlation.", "",
          "Forward-in-time splits (train labels ≤ cutoff, test = next generation, parents/full-sibs purged): " + json.dumps(res['splits']), "",
          md_table(df), ""]
    text = "\n".join(md)
    (out / "sim_controls.md").write_text(text)
    return text


def main() -> int:
    b = sim_bundle()
    camp = Campaign(b, registry=Registry(), seed=0, n_proposals=40, budget_full_evals=8)
    res = camp.run_all("ABEF")
    print(write_sim_controls_report(res))
    write_scorecard(camp.reg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
