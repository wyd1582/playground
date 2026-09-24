"""Holdout sealing: split off the latest generation, write it under holdout/, chmod a-w,
and record digests (never contents) in registry/holdout_seal.json."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import numpy as np
import pandas as pd

from common import paths
from common.hashing import sha256_file
from common.timeutil import utcnow_iso

from .frame import GenoFrame


def split_holdout(frame: GenoFrame, holdout_t: int) -> tuple[GenoFrame, GenoFrame]:
    dev_ids = set(frame.animals[frame.animals.birth_t < holdout_t].animal_id)
    hold_ids = set(frame.animals[frame.animals.birth_t >= holdout_t].animal_id)
    dev = frame.subset_animals(dev_ids)
    dev.meta = dict(frame.meta, holdout_t=holdout_t, sealed=True)
    held = frame.subset_animals(hold_ids | dev_ids)   # holdout keeps ancestry for its own evaluation
    held.phenotypes = held.phenotypes[held.phenotypes.animal_id.isin(hold_ids)].reset_index(drop=True)
    held.meta = dict(frame.meta, holdout_t=holdout_t, role="holdout")
    return dev, held


def write_sealed(held: GenoFrame, name: str, holdout_dir: Path | None = None) -> dict:
    hd = Path(holdout_dir or paths.holdout_dir())
    hd.mkdir(parents=True, exist_ok=True)
    # unseal for re-writing if a previous run left it read-only
    for p in hd.rglob("*"):
        try:
            os.chmod(p, p.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass
    os.chmod(hd, hd.stat().st_mode | stat.S_IWUSR)
    base = hd / name
    base.mkdir(exist_ok=True)
    held.animals.to_parquet(base / "animals.parquet", index=False)
    held.phenotypes.to_parquet(base / "phenotypes.parquet", index=False)
    if held.true_bv is not None:
        held.true_bv.to_parquet(base / "true_bv.parquet", index=False)
    np.savez_compressed(base / "genotypes.npz", genotypes=held.genotypes.astype(np.int8), geno_ids=held.geno_ids)
    files = sorted(p for p in base.rglob("*") if p.is_file())
    digests = {str(p.relative_to(hd)): sha256_file(p) for p in files}
    hold_ids = held.phenotypes.animal_id.unique().tolist()
    seal = {"name": name, "sealed_at": utcnow_iso(), "holdout_t": held.meta.get("holdout_t"),
            "n_holdout_animals": len(hold_ids), "digests": digests}
    sf = paths.holdout_seal_file()
    sf.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(sf.read_text()) if sf.exists() else {}
    existing[name] = seal
    sf.write_text(json.dumps(existing, indent=2))
    for p in files:
        os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    os.chmod(base, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return seal


def read_sealed_for_final_table(name: str, holdout_dir: Path | None = None) -> GenoFrame:
    """Only campaigns/final_table.py calls this, once, and logs a holdout_final_read event."""
    hd = Path(holdout_dir or paths.holdout_dir()) / name
    animals = pd.read_parquet(hd / "animals.parquet")
    phen = pd.read_parquet(hd / "phenotypes.parquet")
    tb = pd.read_parquet(hd / "true_bv.parquet") if (hd / "true_bv.parquet").exists() else None
    z = np.load(hd / "genotypes.npz", allow_pickle=False)
    from .frame import Markers
    m = z["genotypes"].shape[1]
    markers = Markers(np.array([f"m{i:05d}" for i in range(m)]), np.ones(m, dtype=int), np.arange(m, dtype=float), "index_blocks")
    return GenoFrame(animals, phen, z["genotypes"], z["geno_ids"].astype(str), markers, {}, "sim", {}, {"role": "holdout"}, tb)
