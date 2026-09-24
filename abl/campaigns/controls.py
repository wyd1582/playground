"""Negative controls and null calibration. Shuffling is always within contemporary group (birth_t)
so generation trends survive and only the individual signal is destroyed."""
from __future__ import annotations

import numpy as np

from engine import Evaluator
from genoframe import GenoFrame


def shuffled_frame(frame: GenoFrame, trait: str, seed: int) -> GenoFrame:
    sh = frame.public_view()
    rng = np.random.default_rng(seed)
    perm = sh.phenotypes.copy()
    bt = frame.animals.set_index("animal_id").birth_t
    m = perm.trait == trait
    for g in sorted(bt.unique()):
        idx = perm.index[m & perm.animal_id.map(bt).eq(g)]
        perm.loc[idx, "value"] = rng.permutation(perm.loc[idx, "value"].to_numpy())
    sh.phenotypes = perm
    sh.meta = dict(frame.meta, negative_control="shuffled_labels_within_birth_t", shuffle_seed=seed)
    return sh


def null_rho(frame_public: GenoFrame, priors: dict, trait: str, champion, champ_spec, splits, seeds=(11, 12, 13)) -> dict:
    """Empirical null of the LR rho and of the predictive r: champion on shuffled labels, several seeds."""
    rhos, preds, trues = [], [], []
    for s in seeds:
        ev = Evaluator(shuffled_frame(frame_public, trait, s), priors, trait, champion=champion)
        st = [ev.evaluate(champ_spec, sp) for sp in splits]
        n = np.array([x.n_test for x in st], dtype=float); w = n / n.sum()
        rhos.append(float(np.sum(w * [x.rho for x in st])))
        preds.append(float(np.sum(w * [x.extra["predictive_r"] for x in st])))
    return {"mean": float(np.mean(rhos)), "sd": float(np.std(rhos, ddof=1)) if len(rhos) > 1 else 0.0,
            "pred_mean": float(np.mean(preds)), "pred_sd": float(np.std(preds, ddof=1)) if len(preds) > 1 else 0.0,
            "seeds": list(seeds)}
