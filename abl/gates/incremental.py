"""Gate 2 — paired ΔOOS = M(F ∪ B) − M(F) vs the frozen champion: same splits, same seeds, same labels.
M = within-contemporary-group predictive correlation with adjusted test-generation phenotypes
(null-calibrated). On simulated data Δ true accuracy is logged alongside as a diagnostic."""
from __future__ import annotations

import numpy as np

from .stats import paired_bootstrap_delta


def run(cand_stats: list, champ_stats: list, evaluator, thresholds: dict, seed: int, truth=None) -> tuple[bool, list[dict], dict]:
    th = thresholds["incremental"]
    pairs = []
    for c, h in zip(cand_stats, champ_stats):
        y = c.extra["y_adj"]
        ids = [a for a in y.index if a in c.u_partial.index and a in h.u_partial.index]
        g = evaluator.group_key(ids)
        uc = c.u_partial.loc[ids]; uh = h.u_partial.loc[ids]
        uc = (uc - uc.groupby(g).transform("mean")).to_numpy()
        uh = (uh - uh.groupby(g).transform("mean")).to_numpy()
        pairs.append((uc, uh, y.loc[ids].to_numpy()))
    res = paired_bootstrap_delta(pairs, int(th["bootstrap_reps"]), float(th["ci_level"]), seed)
    rows = [{"metric": "delta_oos", "value": res["delta"], "ci_low": res["ci_low"], "ci_high": res["ci_high"],
             "threshold": float(th["min_delta_oos_ci_low"]), "passed": res["ci_low"] > float(th["min_delta_oos_ci_low"])}]
    if truth is not None:
        tp = []
        for c, h in zip(cand_stats, champ_stats):
            ids = [a for a in c.u_partial.index if a in truth.index]
            tp.append((c.u_partial.loc[ids].to_numpy(), h.u_partial.loc[ids].to_numpy(), truth.loc[ids].to_numpy()))
        tr = paired_bootstrap_delta(tp, int(th["bootstrap_reps"]) // 2, float(th["ci_level"]), seed + 1)
        rows.append({"metric": "delta_true_acc", "value": tr["delta"], "ci_low": tr["ci_low"], "ci_high": tr["ci_high"],
                     "threshold": None, "passed": True, "diagnostic": True})
    return rows[0]["passed"], rows, res
