"""Numerator relationship matrix A by the tabular method."""
from __future__ import annotations

import numpy as np
import pandas as pd


def a_matrix(animals: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Returns (A, ids) with ids in birth order. Unknown parents are treated as unrelated founders."""
    a = animals.sort_values(["birth_t", "animal_id"]).reset_index(drop=True)
    ids = a.animal_id.to_numpy()
    idx = {aid: i for i, aid in enumerate(ids)}
    n = len(ids)
    A = np.zeros((n, n))
    sire = [idx.get(s, -1) if isinstance(s, str) else -1 for s in a.sire]
    dam = [idx.get(d, -1) if isinstance(d, str) else -1 for d in a.dam]
    for i in range(n):
        s, d = sire[i], dam[i]
        if s >= 0 and d >= 0:
            A[i, i] = 1.0 + 0.5 * A[s, d]
        else:
            A[i, i] = 1.0
        for j in range(i):
            val = 0.0
            if s >= 0:
                val += 0.5 * A[j, s]
            if d >= 0:
                val += 0.5 * A[j, d]
            A[i, j] = A[j, i] = val
    return A, ids
