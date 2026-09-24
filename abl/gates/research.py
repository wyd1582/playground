"""Gate 5 — research hygiene: the trial count is the number of full evaluations in this campaign; the
candidate's z = Δ/se must clear the expected maximum of that many null trials (deflated p < alpha)."""
from __future__ import annotations

from .stats import deflated_p, expected_max_z


def run(delta: float, se: float, n_trials: int, thresholds: dict) -> tuple[bool, list[dict]]:
    th = thresholds["research"]
    z = delta / se if se > 0 else 0.0
    p = deflated_p(z, n_trials)
    rows = [{"metric": "n_trials", "value": float(n_trials), "threshold": None, "passed": True, "diagnostic": True},
            {"metric": "z_deflated_threshold", "value": z, "threshold": expected_max_z(n_trials), "passed": z >= expected_max_z(n_trials)},
            {"metric": "deflated_p", "value": p, "threshold": float(th["alpha"]), "passed": p < float(th["alpha"])}]
    return all(r["passed"] for r in rows if not r.get("diagnostic")), rows
