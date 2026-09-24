from __future__ import annotations

from pathlib import Path

import yaml

from common import paths
from common.hashing import sha256_file


def load_thresholds(path: Path | None = None) -> dict:
    p = Path(path or paths.gates_thresholds_file())
    with open(p) as f:
        return yaml.safe_load(f)


def thresholds_hash(path: Path | None = None) -> str:
    return sha256_file(Path(path or paths.gates_thresholds_file()))
