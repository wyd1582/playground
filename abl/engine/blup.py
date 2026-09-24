"""GBLUP with a general relationship K: y_p = Xβ + u_p + e,  u ~ N(0, K σa²).

Prediction for every animal in K (phenotyped or not):
    u_all = K[:, p] (K[p, p] + λ I)⁻¹ (y − X β̂),  β̂ by GLS,  λ = σe²/σa².
λ is frozen at campaign start by REML on the champion (eigen trick), so every candidate is
compared at the same shrinkage unless it explicitly uses ``lambda_scale``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import linalg
from scipy.optimize import minimize_scalar


@dataclass
class FitResult:
    u: pd.Series            # indexed by animal_id, all animals in K
    beta: np.ndarray
    lam: float
    n_train: int


def design(cov: pd.DataFrame | None, ids: np.ndarray, columns: list[str]) -> np.ndarray:
    """Intercept + one-hot (drop first) for each categorical covariate."""
    n = len(ids)
    X = [np.ones((n, 1))]
    if cov is not None and columns:
        c = cov.loc[ids, columns]
        for col in columns:
            d = pd.get_dummies(c[col].astype(str), drop_first=True, dtype=float)
            if d.shape[1]:
                X.append(d.to_numpy())
    return np.hstack(X)


def reml_lambda(K_pp: np.ndarray, y: np.ndarray, X: np.ndarray) -> dict[str, float]:
    """Profile REML over λ using the eigen decomposition of K_pp (rrBLUP mixed.solve style)."""
    n, p = X.shape
    d, U = linalg.eigh(K_pp)
    d = np.maximum(d, 1e-8)
    ys, Xs = U.T @ y, U.T @ X

    def neg_reml(loglam: float) -> float:
        lam = np.exp(loglam)
        v = d + lam
        Xv = Xs / v[:, None]
        XtVX = Xs.T @ Xv
        beta = np.linalg.solve(XtVX, Xv.T @ ys)
        r = ys - Xs @ beta
        sa = float(r @ (r / v)) / (n - p)
        ll = -0.5 * ((n - p) * np.log(sa) + np.sum(np.log(v)) + np.linalg.slogdet(XtVX)[1] + (n - p))
        return -ll

    res = minimize_scalar(neg_reml, bounds=(-6.0, 6.0), method="bounded", options={"xatol": 1e-4})
    lam = float(np.exp(res.x))
    v = d + lam
    Xv = Xs / v[:, None]
    beta = np.linalg.solve(Xs.T @ Xv, Xv.T @ ys)
    r = ys - Xs @ beta
    sa = float(r @ (r / v)) / (n - p)
    return {"lam": lam, "h2": 1.0 / (1.0 + lam), "sigma_a2": sa, "sigma_e2": sa * lam, "reml": -res.fun}


def gblup(K: np.ndarray, ids: np.ndarray, y: pd.Series, X_all: np.ndarray, lam: float) -> FitResult:
    """K over ``ids``; ``y`` indexed by animal_id for the phenotyped subset; ``X_all`` rows align with ids."""
    pos = {a: i for i, a in enumerate(ids)}
    p = np.array([pos[a] for a in y.index if a in pos], dtype=int)
    yv = y.loc[ids[p]].to_numpy(dtype=np.float64)
    Xp = X_all[p]
    V = K[np.ix_(p, p)] + lam * np.eye(len(p))
    c, low = linalg.cho_factor(V, lower=True, check_finite=False)
    Vinv_y = linalg.cho_solve((c, low), yv, check_finite=False)
    Vinv_X = linalg.cho_solve((c, low), Xp, check_finite=False)
    XtVX = Xp.T @ Vinv_X
    beta = np.linalg.lstsq(XtVX, Xp.T @ Vinv_y, rcond=None)[0]
    resid = yv - Xp @ beta
    alpha = linalg.cho_solve((c, low), resid, check_finite=False)
    u = K[:, p] @ alpha
    return FitResult(pd.Series(u, index=ids, name="u"), beta, float(lam), int(len(p)))
