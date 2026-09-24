"""Plan simulator (gate 3): ΔF, gain/yr and selection intensity for a ranking (DESIGN.md §3.3)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


def selection_intensity(fraction: float) -> float:
    fraction = min(max(fraction, 1e-6), 1 - 1e-6)
    x = norm.ppf(1 - fraction)
    return float(norm.pdf(x) / fraction)


def plan_metrics(scores: pd.Series, K: np.ndarray, ids: np.ndarray, *, selected_fraction: float,
                 accuracy: float, sigma_a: float, generation_interval_years: float) -> dict[str, float]:
    """Select the top fraction of candidates by score; report the plan's inbreeding and gain."""
    pos = {a: i for i, a in enumerate(ids)}
    cand = [a for a in scores.index if a in pos]
    k = max(2, int(round(len(cand) * selected_fraction)))
    top = scores.loc[cand].sort_values(ascending=False).index[:k]
    sel = np.array([pos[a] for a in top])
    allc = np.array([pos[a] for a in cand])
    f_now = float(np.mean(np.diag(K)[allc]) - 1.0)
    sub = K[np.ix_(sel, sel)]
    off = sub[~np.eye(len(sel), dtype=bool)]
    f_next = float(0.5 * off.mean())                       # expected inbreeding of progeny = mean coancestry of parents
    delta_f = (f_next - f_now) / max(1e-9, 1.0 - f_now)
    i = selection_intensity(selected_fraction)
    gain = i * max(accuracy, 0.0) * sigma_a / generation_interval_years
    return {"delta_f": float(delta_f), "gain_per_year": float(gain), "n_selected": int(k),
            "selection_intensity": float(i), "genotyping_cost_units": float(len(cand))}
