from __future__ import annotations

from .base import AgentContext, load_prompt
from .schemas import ANALYST


def diagnose(ctx: AgentContext, *, hypothesis: dict, dsl: str, gate_rows: list[dict], stats: dict, state: str,
             registry_summary: dict, candidate_id: str, seed: int) -> dict:
    system = load_prompt("analyst")
    user = {"candidate_id": candidate_id, "dsl": dsl, "hypothesis": hypothesis, "disposition": state,
            "gate_results": gate_rows, "stats": {k: v for k, v in stats.items() if k not in ("spec",)},
            "registry_summary": registry_summary}
    return ctx.call(agent="analyst", action="diagnose", system=system, user_obj=user, schema=ANALYST, seed=seed,
                    candidate_id=candidate_id,
                    summary_fn=lambda p: f"{state}: {str(p.get('diagnosis'))[:110]} → next: {str(p.get('next_experiment', {}).get('dsl'))[:60]}")
