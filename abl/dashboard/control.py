"""The one operator switch (OPS.md D.1): control/PAUSE. The dashboard never touches control/RUN."""
from __future__ import annotations

from common import paths
from dashboard.reader import iso, utcnow


def pause_file():
    return paths.control_dir() / "PAUSE"


def control_state() -> dict:
    ctl = paths.control_dir()
    run, paused = (ctl / "RUN").exists(), pause_file().exists()
    if paused:
        label = "PAUSED"
    elif run:
        label = "RUNNING"
    else:
        label = "IDLE"
    return {"run": run, "paused": paused, "label": label}


def pause(by: str = "dashboard") -> None:
    """Create control/PAUSE; the Orchestrator stops before its next step."""
    p = pause_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(f"paused by {by} at {iso(utcnow())}\n", encoding="utf-8")


def resume() -> None:
    """Delete control/PAUSE (no-op when absent)."""
    pause_file().unlink(missing_ok=True)
