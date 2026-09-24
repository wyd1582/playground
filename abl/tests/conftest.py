"""Every test runs against a throw-away ABL_ROOT so the real registry/holdout are untouched."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def abl_root(tmp_path, monkeypatch):
    root = tmp_path / "abl"
    for d in ("registry", "holdout", "control", "data/snapshots", "reports", "gates"):
        (root / d).mkdir(parents=True)
    (root / "control" / "RUN").touch()
    shutil.copy(PROJECT / "gates" / "thresholds.yaml", root / "gates" / "thresholds.yaml")
    monkeypatch.setenv("ABL_ROOT", str(root))
    yield root
