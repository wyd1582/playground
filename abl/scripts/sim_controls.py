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
    a = res["arms"]
    A, B, E, F = a["A_champion"], a["B_random_ops"], a["E_shuffled_labels"], a["F_random_snp"]
    Es = E["champion_on_shuffled"]
    f = lambda v, d=3: (round(v, d) if isinstance(v, (int, float)) and v is not None else "")
    rows = [
        {"arm": "A frozen champion (ssGBLUP, uniform weights)", "true_accuracy": f(A.get("true_accuracy")), "lr_rho": f(A["lr_rho"]),
         "predictive_r": f(A["predictive_r"]), "dispersion_b": f(A["dispersion_b"], 2), "full_evaluations": "", "promoted": "", "best_delta_oos": ""},
        {"arm": "E champion on labels shuffled within generation", "true_accuracy": f(Es.get("true_accuracy")), "lr_rho": f(Es["lr_rho"]),
         "predictive_r": f(Es["predictive_r"]), "dispersion_b": f(Es["dispersion_b"], 2), "full_evaluations": "", "promoted": "", "best_delta_oos": ""},
        {"arm": "B random-operator search (same budget as the loop)", "true_accuracy": "", "lr_rho": "", "predictive_r": "", "dispersion_b": "",
         "full_evaluations": B["full_evaluations"], "promoted": B["promoted"], "best_delta_oos": f(B["best_delta_oos"], 4)},
        {"arm": "E ABL loop on shuffled labels (negative control)", "true_accuracy": "", "lr_rho": "", "predictive_r": "", "dispersion_b": "",
         "full_evaluations": E["full_evaluations"], "promoted": f"{E['false_promotions']} (false promotions)", "best_delta_oos": f(E["best_delta_oos"], 4)},
        {"arm": "F random 30 % SNP subsets (negative control)", "true_accuracy": "", "lr_rho": "", "predictive_r": "", "dispersion_b": "",
         "full_evaluations": F["full_evaluations"], "promoted": f"{F['false_promotions']} (false promotions)", "best_delta_oos": f(F["best_delta_oos"], 4)},
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
