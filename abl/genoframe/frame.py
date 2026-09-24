"""GenoFrame — the platform-neutral data contract.

Time is an integer ordinal ``t`` (a generation index for simulations, a calendar period for
real data). ``calendar`` maps ``t`` to a human label so the same rules apply to solid, liquid
and sequence genotypes alike.

Rules enforced by :meth:`GenoFrame.validate` (DESIGN.md §3.2):
* no duplicate keys — one row per (animal_id, trait) in ``phenotypes``;
* no silent forward fill — a missing phenotype is an absent row, never NaN;
* every phenotype carries ``available_at`` and it is never before the animal's birth;
* pedigree edges point at known animals, born strictly earlier, never at self.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from common.hashing import sha256_array, sha256_json

GENOTYPE_SOURCES = ("solid", "liquid", "seq", "sim")
ANIMAL_COLS = ["animal_id", "sire", "dam", "sex", "line", "farm", "birth_t"]
PHENO_COLS = ["animal_id", "trait", "value", "available_at"]


@dataclass
class Markers:
    marker_id: np.ndarray            # (m,) str
    chrom: np.ndarray                # (m,) int
    pos: np.ndarray                  # (m,) float — cM or bp; declared in ``map_source``
    map_source: str = "declared"     # "declared" (real map) | "index_blocks" (pseudo-map)

    def __len__(self) -> int:
        return int(len(self.marker_id))


@dataclass
class GenoFrame:
    animals: pd.DataFrame                    # ANIMAL_COLS (+ optional extras)
    phenotypes: pd.DataFrame                 # PHENO_COLS
    genotypes: np.ndarray                    # (n_genotyped, m) dosage 0/1/2 (float32 ok)
    geno_ids: np.ndarray                     # (n_genotyped,) animal_id in genotype row order
    markers: Markers
    calendar: dict[int, str]                 # t -> label
    genotype_source: str = "sim"
    versions: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    # simulation truth: NEVER exposed to agents; read only by gates/ for true-accuracy reporting
    true_bv: pd.DataFrame | None = None      # animal_id, trait, tbv

    # -- validation -------------------------------------------------------------------
    def validate(self) -> "GenoFrame":
        a, p = self.animals, self.phenotypes
        missing = [c for c in ANIMAL_COLS if c not in a.columns]
        if missing:
            raise ValueError(f"animals missing columns {missing}")
        missing = [c for c in PHENO_COLS if c not in p.columns]
        if missing:
            raise ValueError(f"phenotypes missing columns {missing}")
        if self.genotype_source not in GENOTYPE_SOURCES:
            raise ValueError(f"genotype_source must be one of {GENOTYPE_SOURCES}")
        if a.animal_id.duplicated().any():
            raise ValueError("duplicate animal_id")
        if p.duplicated(["animal_id", "trait"]).any():
            raise ValueError("duplicate (animal_id, trait) key in phenotypes")
        if p.value.isna().any():
            raise ValueError("NaN phenotype: missing values must be absent rows (no silent forward fill)")
        if p.available_at.isna().any():
            raise ValueError("every phenotype needs available_at")
        known = set(a.animal_id)
        unknown = set(p.animal_id) - known
        if unknown:
            raise ValueError(f"phenotypes for unknown animals: {sorted(unknown)[:5]}")
        birth = a.set_index("animal_id").birth_t
        early = p[p.available_at.values < birth.loc[p.animal_id].values]
        if len(early):
            raise ValueError(f"phenotype available before birth for {early.animal_id.iloc[0]}")
        for col in ("sire", "dam"):
            par = a[col].dropna()
            bad = set(par) - known
            if bad:
                raise ValueError(f"{col} references unknown animals: {sorted(bad)[:5]}")
            selfref = a[a[col] == a.animal_id]
            if len(selfref):
                raise ValueError(f"{col} == self for {selfref.animal_id.iloc[0]}")
            sub = a.dropna(subset=[col])
            if (birth.loc[sub[col]].values >= sub.birth_t.values).any():
                raise ValueError(f"{col} not born strictly before offspring")
        if self.genotypes.shape[0] != len(self.geno_ids):
            raise ValueError("genotype rows != geno_ids")
        if self.genotypes.shape[1] != len(self.markers):
            raise ValueError("genotype cols != markers")
        if set(self.geno_ids) - known:
            raise ValueError("genotyped animals not in animals table")
        if len(set(self.geno_ids)) != len(self.geno_ids):
            raise ValueError("duplicate geno_ids")
        return self

    # -- helpers ----------------------------------------------------------------------
    @property
    def traits(self) -> list[str]:
        return sorted(self.phenotypes.trait.unique().tolist())

    @property
    def n_animals(self) -> int:
        return int(len(self.animals))

    @property
    def n_markers(self) -> int:
        return int(self.genotypes.shape[1])

    def geno_index(self) -> dict[str, int]:
        return {aid: i for i, aid in enumerate(self.geno_ids)}

    def genotype_build_hash(self) -> str:
        return sha256_array(np.asarray(self.genotypes, dtype=np.float32))[:16]

    def pedigree_hash(self) -> str:
        return sha256_json(self.animals[ANIMAL_COLS].astype(str).values.tolist())[:16]

    def phenotype_hash(self) -> str:
        return sha256_json(self.phenotypes[PHENO_COLS].astype(str).values.tolist())[:16]

    def fill_versions(self, code_hash: str = "unversioned") -> "GenoFrame":
        self.versions = {
            "genotype_build": self.genotype_build_hash(),
            "pedigree_snapshot": self.pedigree_hash(),
            "phenotype_snapshot": self.phenotype_hash(),
            "calendar": sha256_json(self.calendar)[:16],
            "code": code_hash,
            "universe": sha256_json(sorted(self.geno_ids.tolist()))[:16],
        }
        return self

    def public_view(self) -> "GenoFrame":
        """Copy without simulation truth — this is what agent-facing code receives."""
        return GenoFrame(self.animals, self.phenotypes, self.genotypes, self.geno_ids, self.markers,
                         self.calendar, self.genotype_source, dict(self.versions), dict(self.meta), None)

    def subset_animals(self, keep: set[str]) -> "GenoFrame":
        a = self.animals[self.animals.animal_id.isin(keep)].copy()
        # parents outside the subset become unknown (edges are part of the point-in-time view)
        a.loc[~a.sire.isin(keep), "sire"] = None
        a.loc[~a.dam.isin(keep), "dam"] = None
        p = self.phenotypes[self.phenotypes.animal_id.isin(keep)].copy()
        m = np.isin(self.geno_ids, list(keep))
        tb = self.true_bv[self.true_bv.animal_id.isin(keep)].copy() if self.true_bv is not None else None
        return GenoFrame(a.reset_index(drop=True), p.reset_index(drop=True), self.genotypes[m], self.geno_ids[m],
                         self.markers, dict(self.calendar), self.genotype_source, dict(self.versions),
                         dict(self.meta), tb)
