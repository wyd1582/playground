from __future__ import annotations

from .base import AgentContext, load_prompt
from .schemas import CRITIC

VERDICT_MAP = {"PASS": "PASS", "RETURN_TO_BUILDER": "RETURN", "REJECT": "REJECT"}


def review(ctx: AgentContext, *, hypothesis: dict, build: dict | None, stage: str, catalog: dict,
           candidate_id: str, seed: int) -> dict:
    system = load_prompt("critic")
    user = {"stage": stage, "hypothesis": hypothesis, "build": build, "data_catalog": catalog,
            "constraints": catalog.get("constraints", {})}
    out = ctx.call(agent="critic", action=f"review_{stage}", system=system, user_obj=user, schema=CRITIC, seed=seed,
                   candidate_id=candidate_id,
                   summary_fn=lambda p: f"{p.get('verdict')} ({', '.join(p.get('leak_type', []) or ['-'])}): {str(p.get('rationale'))[:120]}")
    out["verdict_short"] = VERDICT_MAP.get(out.get("verdict"), "REJECT")
    return out
