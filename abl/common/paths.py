"""Canonical project paths.

Everything resolves relative to ``ABL_ROOT`` (default: the directory containing this
package) so tests can point the whole system at a temporary tree by setting the
environment variable before importing anything else.
"""
from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    return Path(os.environ.get("ABL_ROOT", Path(__file__).resolve().parent.parent)).resolve()


def registry_dir() -> Path:
    return root() / "registry"


def registry_db() -> Path:
    return registry_dir() / "abl.sqlite"


def events_file() -> Path:
    return registry_dir() / "events.jsonl"


def prompts_dir() -> Path:
    return registry_dir() / "prompts"


def holdout_dir() -> Path:
    return root() / "holdout"


def holdout_seal_file() -> Path:
    """Digest-only record of what was sealed. Lives OUTSIDE holdout/ so the firewall test
    can grep agent inputs for these digests without any agent code touching holdout/."""
    return registry_dir() / "holdout_seal.json"


def control_dir() -> Path:
    return root() / "control"


def data_dir() -> Path:
    return root() / "data"


def snapshots_dir() -> Path:
    return data_dir() / "snapshots"


def reports_dir() -> Path:
    return root() / "reports"


def gates_thresholds_file() -> Path:
    return root() / "gates" / "thresholds.yaml"


def assert_not_holdout(path: os.PathLike | str) -> Path:
    """Firewall layer 2: raise if ``path`` resolves anywhere under holdout/.

    Every data loader in genoframe/ and dataio/ calls this before opening a file.
    """
    p = Path(path).resolve()
    h = holdout_dir().resolve()
    if p == h or h in p.parents:
        raise PermissionError(f"firewall: refusing to read sealed path {p}")
    return p


def run_allowed() -> tuple[bool, str]:
    """OPS.md B.1 rule 5: control/RUN must exist and control/PAUSE must not."""
    c = control_dir()
    if (c / "PAUSE").exists():
        return False, "control/PAUSE exists"
    if not (c / "RUN").exists():
        return False, "control/RUN missing"
    return True, "ok"
