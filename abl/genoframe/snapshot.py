"""Point-in-time snapshots: what was knowable at cutoff ``t``."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from common.hashing import sha256_json

from .frame import GenoFrame


@dataclass
class Snapshot:
    frame: GenoFrame            # animals born <= t, phenotypes available <= t, edges among them
    cutoff_t: int
    snapshot_id: str

    @property
    def phenotypes(self) -> pd.DataFrame:
        return self.frame.phenotypes


def pit_snapshot(frame: GenoFrame, cutoff_t: int, include_unphenotyped_born_leq: bool = True) -> Snapshot:
    """Everything with available_at <= cutoff. Animals born after the cutoff do not exist yet."""
    keep = set(frame.animals[frame.animals.birth_t <= cutoff_t].animal_id)
    sub = frame.subset_animals(keep)
    sub.phenotypes = sub.phenotypes[sub.phenotypes.available_at <= cutoff_t].reset_index(drop=True)
    sid = sha256_json({"cutoff": cutoff_t, "versions": frame.versions, "n": len(keep),
                       "ph": sub.phenotype_hash()})[:16]
    return Snapshot(sub, cutoff_t, sid)
