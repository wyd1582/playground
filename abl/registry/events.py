"""The agent side's single obligation (OPS.md D.1/D.2): append one JSON line per agent call.

Also persists the exact prompt/input text to registry/prompts/<input_hash>.txt so the
holdout firewall test can grep everything an agent ever saw.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common import paths
from common.hashing import canonical_json, sha256_text
from common.timeutil import utcnow_iso

POLICY_FLAGS = {"holdout_touch", "budget_exceeded", "threshold_edit", "retry_limit", "holdout_final_read", "paused"}


def append_event(*, agent: str, action: str, campaign_id: str | None, candidate_id: str | None = None,
                 input_obj: Any = None, output_obj: Any = None, tokens: int = 0, latency_ms: int = 0,
                 summary: str = "", policy_flags: list[str] | None = None, cost_usd: float = 0.0,
                 registry: Any = None, events_path: Path | None = None) -> dict[str, Any]:
    flags = list(policy_flags or [])
    bad = set(flags) - POLICY_FLAGS
    if bad:
        raise ValueError(f"unknown policy flags {bad}")
    in_text = input_obj if isinstance(input_obj, str) else canonical_json(input_obj)
    out_text = output_obj if isinstance(output_obj, str) else canonical_json(output_obj)
    in_hash, out_hash = sha256_text(in_text), sha256_text(out_text)
    event = {
        "ts": utcnow_iso(), "campaign_id": campaign_id, "agent": agent, "action": action,
        "candidate_id": candidate_id, "input_hash": in_hash, "output_hash": out_hash,
        "tokens": int(tokens), "latency_ms": int(latency_ms), "summary": summary,
        "policy_flags": flags, "cost_usd": float(cost_usd),
    }
    ep = Path(events_path or paths.events_file())
    ep.parent.mkdir(parents=True, exist_ok=True)
    with open(ep, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    pd = paths.prompts_dir()
    pd.mkdir(parents=True, exist_ok=True)
    (pd / f"{in_hash}.in.txt").write_text(in_text, encoding="utf-8")
    (pd / f"{out_hash}.out.txt").write_text(out_text, encoding="utf-8")
    if registry is not None:
        registry.add_agent_event(event)
    return event
