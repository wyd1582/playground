"""Append-only trial ledger (OPS.md A.2). Only gates/ may write candidate state transitions."""
from .db import Registry, connect_readonly  # noqa: F401
from .events import append_event  # noqa: F401
