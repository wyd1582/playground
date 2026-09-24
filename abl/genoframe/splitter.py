"""Forward-in-time splitter with cross-generation purge (DESIGN.md §3.2 rules).

For cutoff ``T``:
* ``train_ids``  — animals whose phenotype had arrived by ``T`` (label_exit <= cutoff);
* ``test_ids``   — the selection candidates born at ``T + 1`` (scored at ``T + 1`` with data <= ``T``);
* ``purged_ids`` — parents and full-sibs of test animals removed from the training labels
  under ``purge_policy="contract"`` (the default written into the data contract). Purging
  makes the split conservative; champion and challenger always see the identical split, so
  paired ΔOOS stays fair.
* ``whole_t``    — the time at which test labels have arrived, used by the LR method
  (partial = data <= T, whole = data <= whole_t).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from common.hashing import sha256_json

from .frame import GenoFrame


@dataclass
class Split:
    cutoff_t: int
    whole_t: int
    train_ids: list[str]
    test_ids: list[str]
    purged_ids: list[str]
    purge_policy: str
    split_id: str = field(default="")

    def __post_init__(self):
        if not self.split_id:
            self.split_id = sha256_json({"cutoff": self.cutoff_t, "whole": self.whole_t,
                                         "train": self.train_ids, "test": self.test_ids,
                                         "purged": self.purged_ids, "policy": self.purge_policy})[:16]


def _full_sibs_and_parents(animals: pd.DataFrame, test_ids: set[str]) -> set[str]:
    a = animals.set_index("animal_id")
    t = a.loc[list(test_ids)]
    parents = set(t.sire.dropna()) | set(t.dam.dropna())
    pairs = set(zip(t.sire.fillna("?"), t.dam.fillna("?")))
    pairs.discard(("?", "?"))
    sibs = set()
    if pairs:
        cand = animals[~animals.animal_id.isin(test_ids)]
        key = list(zip(cand.sire.fillna("?"), cand.dam.fillna("?")))
        sibs = {aid for aid, k in zip(cand.animal_id, key) if k in pairs and "?" not in k}
    return parents | sibs


def forward_splits(frame: GenoFrame, trait: str, *, min_train_t: int | None = None,
                   purge_policy: str = "contract", label_lag: int = 0,
                   max_t: int | None = None) -> list[Split]:
    """One split per cutoff T in [first usable, last-1]. ``max_t`` excludes sealed generations."""
    if purge_policy not in ("contract", "temporal_only"):
        raise ValueError(purge_policy)
    a = frame.animals
    ph = frame.phenotypes[frame.phenotypes.trait == trait]
    ts = sorted(a.birth_t.unique().tolist())
    if max_t is not None:
        ts = [t for t in ts if t <= max_t]
    if min_train_t is None:
        min_train_t = ts[0]
    splits: list[Split] = []
    for i in range(len(ts) - 1):
        T, nxt = ts[i], ts[i + 1]
        if T < min_train_t:
            continue
        test_ids = a[a.birth_t == nxt].animal_id.tolist()
        test_ids = [x for x in test_ids if x in set(frame.geno_ids)]
        if not test_ids:
            continue
        train = ph[ph.available_at <= T]
        purged: set[str] = set()
        if purge_policy == "contract":
            purged = _full_sibs_and_parents(a, set(test_ids))
        train_ids = sorted(set(train.animal_id) - purged - set(test_ids))
        whole_t = int(ph[ph.animal_id.isin(test_ids)].available_at.max()) if (ph.animal_id.isin(test_ids)).any() else nxt + label_lag
        if len(train_ids) < 30:
            continue
        splits.append(Split(int(T), int(whole_t), train_ids, sorted(test_ids), sorted(purged), purge_policy))
    return splits


def assert_no_leak(frame: GenoFrame, split: Split, trait: str) -> None:
    """Machine check used by the validity gate and the Critic tools."""
    ph = frame.phenotypes[(frame.phenotypes.trait == trait) & frame.phenotypes.animal_id.isin(split.train_ids)]
    late = ph[ph.available_at > split.cutoff_t]
    if len(late):
        raise AssertionError(f"temporal leak: {len(late)} training labels available after cutoff {split.cutoff_t}")
    if set(split.train_ids) & set(split.test_ids):
        raise AssertionError("train/test overlap")
    if split.purge_policy == "contract":
        rel = _full_sibs_and_parents(frame.animals, set(split.test_ids))
        if rel & set(split.train_ids):
            raise AssertionError("relatedness leak: parents/full-sibs of test animals in training")
