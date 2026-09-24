from __future__ import annotations

from .base import AgentContext, load_prompt
from .schemas import GENETICIST


def propose(ctx: AgentContext, *, brief: dict, registry_summary: dict, catalog: dict, seed: int, probe: dict | None = None) -> dict:
    system = load_prompt("geneticist", species=brief["species"], trait=brief["trait"], selection_horizon=brief["horizon"])
    user = {"brief": brief, "registry_summary": registry_summary, "data_catalog": catalog,
            "grammar": catalog.get("grammar_summary", "see dsl/grammar.md")}
    if probe:
        user["probe"] = probe   # negative-control probe: a deliberately leaky hypothesis the Critic must catch
    return ctx.call(agent="geneticist", action="hypothesize", system=system, user_obj=user, schema=GENETICIST, seed=seed,
                    summary_fn=lambda p: f"Proposed [{p.get('mechanism_cluster')}]: {str(p.get('mechanism'))[:110]}")
