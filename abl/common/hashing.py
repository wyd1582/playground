"""Deterministic hashing used for provenance, dedup and the holdout firewall."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace noise, floats rounded to 10 significant digits."""
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def sha256_array(a: np.ndarray) -> str:
    a = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(a.dtype).encode())
    h.update(str(a.shape).encode())
    h.update(a.tobytes())
    return h.hexdigest()


def short(h: str, n: int = 12) -> str:
    return h[:n]


def _normalise(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _normalise(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_normalise(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        if f != f:  # NaN
            return None
        return float(f"{f:.10g}")
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return _normalise(o.tolist())
    if isinstance(o, Path):
        return str(o)
    return o
