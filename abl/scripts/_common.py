from __future__ import annotations

import pickle

from campaigns.runner import DatasetBundle
from common import paths


def sim_bundle() -> DatasetBundle:
    p = paths.snapshots_dir() / "sim_dev.pkl"
    if not p.exists():
        import subprocess, sys
        subprocess.check_call([sys.executable, "scripts/seal_holdout.py"])
    with open(p, "rb") as f:
        d = pickle.load(f)
    return DatasetBundle(name="sim", frame=d["frame"], priors=d["priors"], trait="t1", species="sim_pig", customer_id="sim",
                         champion_covariates=["line", "farm", "birth_t"], champion_blend_w=0.05, min_train_t=1, owner="public", sharing_tier="public")


def pig_bundle(max_markers: int | None = None) -> DatasetBundle:
    from dataio import load_pig_cleveland
    frame = load_pig_cleveland(max_markers=max_markers)
    return DatasetBundle(name="pig_cleveland", frame=frame, priors={}, trait="t1", species="pig", customer_id="public_pic",
                         champion_covariates=[], champion_blend_w=0.0, min_train_t=None, owner="public", sharing_tier="public")
