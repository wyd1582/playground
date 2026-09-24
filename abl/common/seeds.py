"""One seed policy for the whole harness (CLAUDE.md rule 4)."""
from __future__ import annotations

import numpy as np

from .hashing import sha256_text

GLOBAL_SEED = 20260924


def derive_seed(*parts: object, base: int = GLOBAL_SEED) -> int:
    """Deterministic child seed from a base seed and any hashable labels."""
    digest = sha256_text("|".join([str(base), *map(str, parts)]))
    return int(digest[:8], 16)


def rng(*parts: object, base: int = GLOBAL_SEED) -> np.random.Generator:
    return np.random.default_rng(derive_seed(*parts, base=base))
