"""Deterministic gates — the only code allowed to change a candidate's state (CLAUDE.md rule 2)."""
from .runner import GateRunner, GateVerdict  # noqa: F401
from .thresholds import load_thresholds, thresholds_hash  # noqa: F401
