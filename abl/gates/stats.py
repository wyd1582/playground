"""Shared statistics for the gates: paired bootstrap, expected-maximum deflation."""
from __future__ import annotations

import numpy as np
from scipy.stats import norm

EULER_GAMMA = 0.5772156649


def paired_bootstrap_delta(pairs: list[tuple[np.ndarray, np.ndarray, np.ndarray]], reps: int, level: float,
                           seed: int, corr=None) -> dict[str, float]:
    """pairs = [(cand_pred, champ_pred, target), ...] one per split. Statistic = n-weighted mean over
    splits of cor(cand, target) − cor(champ, target); animals resampled within split."""
    corr = corr or (lambda a, b: float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 0.0)
    rng = np.random.default_rng(seed)
    n_tot = sum(len(t) for _, _, t in pairs)

    def stat(idx_list):
        val = 0.0
        for (c, h, t), idx in zip(pairs, idx_list):
            val += len(t) / n_tot * (corr(c[idx], t[idx]) - corr(h[idx], t[idx]))
        return val

    point = stat([np.arange(len(t)) for _, _, t in pairs])
    boots = np.empty(reps)
    for r in range(reps):
        boots[r] = stat([rng.integers(0, len(t), size=len(t)) for _, _, t in pairs])
    a = (1 - level) / 2
    return {"delta": float(point), "ci_low": float(np.quantile(boots, a)), "ci_high": float(np.quantile(boots, 1 - a)),
            "se": float(boots.std(ddof=1)), "n": int(n_tot)}


def expected_max_z(n_trials: int) -> float:
    """E[max of N standard normals] (Bailey & López de Prado 2014 approximation)."""
    n = max(int(n_trials), 1)
    if n == 1:
        return 0.0
    return float((1 - EULER_GAMMA) * norm.ppf(1 - 1.0 / n) + EULER_GAMMA * norm.ppf(1 - 1.0 / (n * np.e)))


def deflated_p(z: float, n_trials: int) -> float:
    """p-value of z against the expected maximum of n_trials null trials."""
    return float(1 - norm.cdf(z - expected_max_z(n_trials)))
