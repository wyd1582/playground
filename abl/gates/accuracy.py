"""Gate 1 — LR-method accuracy (Legarra & Reverter 2018): rho, bias, dispersion b, coverage.
rho's pass line is the larger of the yaml minimum and the campaign's shuffled-label null + 1 sd."""
from __future__ import annotations

import numpy as np


def run(stats_by_split: list, thresholds: dict, null_rho: dict | None) -> tuple[bool, list[dict]]:
    th = thresholds["accuracy"]
    rows: list[dict] = []
    n = np.array([s.n_test for s in stats_by_split], dtype=float)
    w = n / n.sum()
    rho = float(np.sum(w * np.array([s.rho for s in stats_by_split])))
    bias = float(np.sum(w * np.array([s.bias for s in stats_by_split])))
    b = float(np.sum(w * np.array([s.dispersion for s in stats_by_split])))
    b_se = float(np.sqrt(np.sum((w * np.array([s.dispersion_se for s in stats_by_split])) ** 2)))
    cov = float(np.min([s.coverage for s in stats_by_split]))
    rho_line = float(th["min_rho"])
    if null_rho:
        rho_line = max(rho_line, float(null_rho["mean"]) + float(null_rho["sd"]))
    rows.append({"metric": "lr_rho", "value": rho, "threshold": rho_line, "passed": rho >= rho_line})
    rows.append({"metric": "lr_bias_sd", "value": bias, "threshold": float(th["max_abs_bias_sd"]),
                 "passed": abs(bias) <= float(th["max_abs_bias_sd"])})
    lo, hi = b - 1.645 * b_se, b + 1.645 * b_se
    covers = (lo <= 1.0 <= hi) or not th["dispersion_ci_must_cover_one"]
    rows.append({"metric": "lr_dispersion_b", "value": b, "ci_low": lo, "ci_high": hi, "threshold": 1.0, "passed": covers})
    rows.append({"metric": "coverage", "value": cov, "threshold": float(th["min_coverage"]), "passed": cov >= float(th["min_coverage"])})
    return all(r["passed"] for r in rows), rows
