"""One logged, firewalled LLM call per agent action."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.llm import LLM
from registry import Registry, append_event

from . import firewall

PROMPTS = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str, **fill: Any) -> str:
    text = (PROMPTS / f"{name}.md").read_text()
    for k, v in fill.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


class AgentContext:
    def __init__(self, llm: LLM, registry: Registry, campaign_id: str):
        self.llm = llm
        self.reg = registry
        self.campaign_id = campaign_id
        self.tokens_used = 0
        self.cost_usd = 0.0
        self.calls = 0

    def call(self, *, agent: str, action: str, system: str, user_obj: Any, schema: dict | None,
             candidate_id: str | None = None, seed: int = 0, summary_fn=None) -> dict:
        user = json.dumps(user_obj, ensure_ascii=False, indent=1, sort_keys=True, default=str)
        flags: list[str] = []
        try:
            firewall.enforce(system + "\n" + user)
        except firewall.FirewallError as e:
            flags.append("holdout_touch")
            append_event(agent=agent, action=action, campaign_id=self.campaign_id, candidate_id=candidate_id,
                         input_obj={"blocked": True, "reason": str(e)}, output_obj={}, summary=f"FIREWALL blocked {agent}.{action}: {e}",
                         policy_flags=flags, registry=self.reg)
            raise
        res = self.llm.complete(role=agent, system=system, user=user, schema=schema, seed=seed)
        parsed = res.parsed if res.parsed is not None else {"_raw": res.text, "_stop_reason": res.stop_reason}
        self.tokens_used += res.tokens
        self.cost_usd += res.cost_usd
        self.calls += 1
        summary = summary_fn(parsed) if summary_fn else f"{agent}.{action}"
        append_event(agent=agent, action=action, campaign_id=self.campaign_id, candidate_id=candidate_id,
                     input_obj=system + "\n" + user, output_obj=parsed, tokens=res.tokens, latency_ms=res.latency_ms,
                     summary=summary, policy_flags=flags, cost_usd=res.cost_usd, registry=self.reg)
        return parsed
