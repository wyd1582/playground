"""Turn a ModelSpec + Split into scores and LR-method statistics. Deterministic; no truth here."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from common.hashing import sha256_json
from dsl.compiler import ModelSpec
from genoframe import GenoFrame, Split

from . import grm
from .blup import design, gblup, reml_lambda
from .pedigree import a_matrix


@dataclass
class FitStats:
    u_partial: pd.Series          # test animals, data <= cutoff
    u_whole: pd.Series            # test animals, data <= whole_t (their own labels included)
    rho: float                    # cor(u_partial, u_whole)  — LR accuracy proxy
    bias: float                   # mean(u_whole − u_partial) / sd(u_whole)
    dispersion: float             # slope of u_whole on u_partial (b)
    dispersion_se: float
    coverage: float
    n_train: int
    n_test: int
    seconds: float
    extra: dict = field(default_factory=dict)


class Evaluator:
    def __init__(self, frame: GenoFrame, priors: dict[str, np.ndarray], trait: str, champion=None):
        if frame.true_bv is not None:
            raise ValueError("Evaluator must receive frame.public_view(); truth stays in gates/")
        self.frame = frame
        self.priors = priors
        self.trait = trait
        self.champion = champion
        self.ids = np.asarray(frame.geno_ids)
        self.X = frame.genotypes
        self.p = grm.allele_freq(self.X)
        self.cov = frame.animals.set_index("animal_id")
        self.has_pedigree = frame.animals.sire.notna().any()
        self._A: np.ndarray | None = None
        self._K_cache: dict[str, np.ndarray] = {}
        self._pheno = frame.phenotypes[frame.phenotypes.trait == trait].set_index("animal_id")

    # -- relationship -----------------------------------------------------------------
    def _A22(self) -> np.ndarray:
        if self._A is None:
            A, ids = a_matrix(self.frame.animals)
            pos = {a: i for i, a in enumerate(ids)}
            sel = np.array([pos[a] for a in self.ids])
            self._A = A[np.ix_(sel, sel)]
        return self._A

    def marker_weights(self, spec: ModelSpec) -> np.ndarray:
        m = self.X.shape[1]
        w = np.ones(m)
        mafv = np.minimum(self.p, 1 - self.p)
        for op in spec.marker_weight_ops:
            if op["name"] == "grm_weights":
                if op["scheme"] == "maf_inverse":
                    w *= 1.0 / np.maximum(2 * mafv * (1 - mafv), 1e-3)
                elif op["scheme"] == "maf_power":
                    w *= np.power(np.maximum(2 * mafv * (1 - mafv), 1e-3), float(op["power"]))
            elif op["name"] == "region_weight":
                w = np.where(self.frame.markers.chrom == int(op["chrom"]), w * float(op["weight"]), w)
            elif op["name"] == "qtl_prior":
                prior = np.asarray(self.priors[op["source"]], dtype=float)
                w *= 1.0 + float(op["weight"]) * (prior > 0)
        if spec.subset:
            s = spec.subset
            k = max(10, int(round(m * float(s["fraction"]))))
            if s["strategy"] == "random":
                rng = np.random.default_rng(int(s.get("seed", 0)))
                keep = rng.choice(m, size=k, replace=False)
            elif s["strategy"] == "top_maf":
                keep = np.argsort(-mafv, kind="stable")[:k]
            else:
                prior = np.asarray(self.priors[s["source"]], dtype=float)
                keep = np.flatnonzero(prior > 0)[:k]
            mask = np.zeros(m, dtype=bool); mask[keep] = True
            w = np.where(mask, w, 0.0)
        return w

    def relationship(self, spec: ModelSpec) -> np.ndarray:
        key = sha256_json({"w": spec.marker_weight_ops, "s": spec.subset, "b": spec.blend_w, "d": spec.dominance_w,
                           "cb": self.champion.blend_w if self.champion else 0.0})
        if key in self._K_cache:
            return self._K_cache[key]
        w = self.marker_weights(spec)
        K = grm.weighted_grm(self.X, w, self.p)
        bw = spec.blend_w if spec.blend_w > 0 else (self.champion.blend_w if self.champion else 0.0)
        if bw > 0 and self.has_pedigree:
            K = grm.blend(K, self._A22(), bw)
        if spec.dominance_w > 0:
            K = K + spec.dominance_w * grm.dominance_grm(self.X, self.p)
        K = grm.ridge(K, self.champion.ridge_eps if self.champion else 0.01)
        if len(self._K_cache) > 6:
            self._K_cache.clear()
        self._K_cache[key] = K
        return K

    def covariates(self, spec: ModelSpec) -> list[str]:
        base = list(self.champion.covariates) if self.champion else []
        return base + [c for c in spec.covariates if c not in base]

    def lam(self, spec: ModelSpec) -> float:
        base = self.champion.lam if self.champion else 1.0
        return base * spec.lambda_factor

    # -- fitting ------------------------------------------------------------------------
    def _labels(self, animal_ids: list[str], upto_t: int) -> pd.Series:
        ph = self._pheno.loc[self._pheno.index.intersection(animal_ids)]
        ph = ph[ph.available_at <= upto_t]
        return ph.value.astype(float)

    def reml_on_split(self, split: Split, spec: ModelSpec | None = None) -> dict[str, float]:
        from dsl import compile_program, parse, validate
        spec = spec or compile_program(validate(parse("champion()")))
        K = self.relationship(spec)
        y = self._labels(split.train_ids, split.cutoff_t)
        pos = {a: i for i, a in enumerate(self.ids)}
        p = np.array([pos[a] for a in y.index])
        X = design(self.cov, self.ids[p], self.covariates(spec))
        return reml_lambda(K[np.ix_(p, p)], y.to_numpy(), X)

    def fit(self, spec: ModelSpec, train_ids: list[str], upto_t: int, drop_ids: set[str] | None = None) -> pd.Series:
        K = self.relationship(spec)
        y = self._labels([a for a in train_ids if not (drop_ids and a in drop_ids)], upto_t)
        X = design(self.cov, self.ids, self.covariates(spec))
        return gblup(K, self.ids, y, X, self.lam(spec)).u

    def adjusted_labels(self, split: Split, group_cols: list[str] | None = None) -> pd.Series:
        """Test-generation phenotypes centred within contemporary groups (champion covariates).
        Model-free, leak-free, null-calibrated: with shuffled labels the correlation with any
        prediction is ~0, unlike the LR rho (see docs/OPS.md D.4 / reports)."""
        cols = group_cols if group_cols is not None else [c for c in (self.champion.covariates if self.champion else []) if c != "birth_t"]
        y = self._labels(split.test_ids, split.whole_t)
        if not len(y):
            return y
        if cols:
            g = self.cov.loc[y.index, cols].astype(str).agg("|".join, axis=1)
            y = y - y.groupby(g).transform("mean")
        else:
            y = y - y.mean()
        return y

    def group_key(self, ids) -> pd.Series:
        cols = [c for c in (self.champion.covariates if self.champion else []) if c != "birth_t"]
        if not cols:
            return pd.Series("all", index=list(ids))
        return self.cov.loc[list(ids), cols].astype(str).agg("|".join, axis=1)

    def predictive_r(self, u: pd.Series, y_adj: pd.Series) -> float:
        """Within-contemporary-group correlation between predictions and adjusted phenotypes."""
        if len(u) < 3:
            return 0.0
        g = self.group_key(u.index)
        uc = u - u.groupby(g).transform("mean")
        if uc.std() == 0 or y_adj.std() == 0:
            return 0.0
        return float(np.corrcoef(uc.to_numpy(), y_adj.loc[u.index].to_numpy())[0, 1])

    def evaluate(self, spec: ModelSpec, split: Split, drop_ids: set[str] | None = None) -> FitStats:
        t0 = time.perf_counter()
        u_p = self.fit(spec, split.train_ids, split.cutoff_t, drop_ids)
        u_w = self.fit(spec, split.train_ids + split.test_ids, split.whole_t, drop_ids)
        test = [a for a in split.test_ids if a in u_p.index]
        up, uw = u_p.loc[test], u_w.loc[test]
        stats = lr_stats(up.to_numpy(), uw.to_numpy())
        n_train = len(self._labels([a for a in split.train_ids if not (drop_ids and a in drop_ids)], split.cutoff_t))
        yadj = self.adjusted_labels(split)
        common = [a for a in test if a in yadj.index]
        pred = self.predictive_r(up.loc[common], yadj.loc[common])
        return FitStats(up, uw, stats["rho"], stats["bias"], stats["b"], stats["b_se"],
                        len(test) / max(1, len(split.test_ids)), n_train, len(test),
                        time.perf_counter() - t0, extra={"predictive_r": pred, "y_adj": yadj.loc[common]})


def lr_stats(u_partial: np.ndarray, u_whole: np.ndarray) -> dict[str, float]:
    """Legarra & Reverter (2018) LR statistics on validation animals."""
    n = len(u_partial)
    if n < 3 or np.std(u_partial) == 0 or np.std(u_whole) == 0:
        return {"rho": 0.0, "bias": 0.0, "b": 0.0, "b_se": float("inf")}
    rho = float(np.corrcoef(u_partial, u_whole)[0, 1])
    bias = float((u_whole - u_partial).mean() / u_whole.std())
    b = float(np.cov(u_whole, u_partial)[0, 1] / np.var(u_partial, ddof=1))
    resid = u_whole - (u_whole.mean() + b * (u_partial - u_partial.mean()))
    b_se = float(np.sqrt(np.sum(resid ** 2) / (n - 2) / np.sum((u_partial - u_partial.mean()) ** 2)))
    return {"rho": rho, "bias": bias, "b": b, "b_se": b_se}
