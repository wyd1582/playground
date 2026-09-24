from __future__ import annotations

from .base import AgentContext, load_prompt
from .schemas import BUILDER


def build(ctx: AgentContext, *, hypothesis: dict, catalog: dict, candidate_id: str, seed: int, feedback: dict | None = None) -> dict:
    system = load_prompt("builder")
    user = {"hypothesis": hypothesis, "data_catalog": catalog, "grammar": catalog.get("grammar_summary")}
    if feedback:
        user["critic_feedback"] = feedback
    return ctx.call(agent="builder", action="implement", system=system, user_obj=user, schema=BUILDER, seed=seed,
                    candidate_id=candidate_id,
                    summary_fn=lambda p: (f"NEED_OPERATOR: {p.get('operator_spec')}" if p.get("status") == "NEED_OPERATOR"
                                          else f"Built {p.get('dsl')}"))
