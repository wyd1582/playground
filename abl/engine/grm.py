"""Genomic relationship matrices (VanRaden 2008 method 1, weighted; Vitezica 2013 dominance)."""
from __future__ import annotations

import numpy as np


def allele_freq(X: np.ndarray) -> np.ndarray:
    return np.asarray(X, dtype=np.float64).mean(axis=0) / 2.0


def maf(X: np.ndarray) -> np.ndarray:
    p = allele_freq(X)
    return np.minimum(p, 1 - p)


def weighted_grm(X: np.ndarray, weights: np.ndarray | None = None, p: np.ndarray | None = None,
                 chunk: int = 4096) -> np.ndarray:
    """G = Z W Z' / (2 Σ_j w_j p_j q_j), Z = X − 2p. Weights are normalised to mean 1 so that
    uniform weights reproduce the classic VanRaden G exactly."""
    n, m = X.shape
    p = allele_freq(X) if p is None else np.asarray(p, dtype=np.float64)
    w = np.ones(m) if weights is None else np.asarray(weights, dtype=np.float64)
    if (w < 0).any():
        raise ValueError("marker weights must be non-negative")
    if w.sum() <= 0:
        raise ValueError("all marker weights are zero")
    w = w * (m / w.sum())
    denom = 2.0 * float(np.sum(w * p * (1 - p)))
    G = np.zeros((n, n), dtype=np.float64)
    for s in range(0, m, chunk):
        e = min(m, s + chunk)
        Z = np.asarray(X[:, s:e], dtype=np.float64) - 2.0 * p[s:e]
        G += (Z * w[s:e]) @ Z.T
    return G / denom


def dominance_grm(X: np.ndarray, p: np.ndarray | None = None, chunk: int = 4096) -> np.ndarray:
    n, m = X.shape
    p = allele_freq(X) if p is None else np.asarray(p, dtype=np.float64)
    q = 1 - p
    denom = float(np.sum((2 * p * q) ** 2))
    D = np.zeros((n, n), dtype=np.float64)
    for s in range(0, m, chunk):
        e = min(m, s + chunk)
        Xc = np.asarray(X[:, s:e], dtype=np.float64)
        pc, qc = p[s:e], q[s:e]
        W = np.where(Xc == 0, -2 * pc * pc, np.where(Xc == 1, 2 * pc * qc, -2 * qc * qc))
        D += W @ W.T
    return D / denom


def blend(G: np.ndarray, A: np.ndarray, w: float) -> np.ndarray:
    return (1.0 - w) * G + w * A


def ridge(G: np.ndarray, eps: float = 0.01) -> np.ndarray:
    return G + eps * np.eye(G.shape[0])
