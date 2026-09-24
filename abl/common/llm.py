"""LLM backend shared by agents/ and dashboard/digest.py.

* ``AnthropicLLM`` — the official SDK (``claude-opus-5``, adaptive thinking, JSON-schema
  structured output, server-side refusal fallbacks). Used when credentials resolve.
* ``StubLLM`` — deterministic, offline. Role handlers are plain functions registered by the
  caller, so the entire loop, the tests and the dashboard run without network access and the
  registry still records every call with a token estimate.

Select with ``ABL_LLM=anthropic|stub``; default is anthropic when credentials are available.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

DEFAULT_MODEL = "claude-opus-5"
# USD per million tokens (input, output) — kept next to the model id so cost rows stay honest
PRICES = {"claude-opus-5": (5.0, 25.0), "stub": (0.0, 0.0)}

Handler = Callable[[str, str, dict | None, int], dict]   # (system, user, schema, seed) -> parsed dict


@dataclass
class LLMResult:
    text: str
    parsed: dict | None
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int
    cost_usd: float
    stop_reason: str = "end_turn"

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLM(Protocol):
    model: str

    def complete(self, *, role: str, system: str, user: str, schema: dict | None = None, seed: int = 0) -> LLMResult: ...


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _cost(model: str, tin: int, tout: int) -> float:
    pi, po = PRICES.get(model, (0.0, 0.0))
    return round((tin * pi + tout * po) / 1e6, 6)


@dataclass
class StubLLM:
    handlers: dict[str, Handler] = field(default_factory=dict)
    model: str = "stub"

    def register(self, role: str, fn: Handler) -> None:
        self.handlers[role] = fn

    def complete(self, *, role: str, system: str, user: str, schema: dict | None = None, seed: int = 0) -> LLMResult:
        if role not in self.handlers:
            raise KeyError(f"StubLLM has no handler for role {role!r}")
        t0 = time.perf_counter()
        parsed = self.handlers[role](system, user, schema, seed)
        text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
        tin, tout = estimate_tokens(system + user), estimate_tokens(text)
        return LLMResult(text, parsed, tin, tout, self.model, int((time.perf_counter() - t0) * 1000), 0.0)


class AnthropicLLM:
    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 16000, use_fallbacks: bool | None = None):
        import anthropic  # imported lazily so the stub path has no SDK dependency

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.use_fallbacks = (os.environ.get("ABL_LLM_FALLBACKS", "1") != "0") if use_fallbacks is None else use_fallbacks

    def complete(self, *, role: str, system: str, user: str, schema: dict | None = None, seed: int = 0) -> LLMResult:
        kwargs: dict[str, Any] = dict(model=self.model, max_tokens=self.max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}])
        if schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        t0 = time.perf_counter()
        resp = self._create(kwargs)
        latency = int((time.perf_counter() - t0) * 1000)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        parsed = None
        if schema is not None and resp.stop_reason != "refusal":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        tin, tout = int(resp.usage.input_tokens), int(resp.usage.output_tokens)
        return LLMResult(text, parsed, tin, tout, getattr(resp, "model", self.model), latency,
                         _cost(self.model, tin, tout), stop_reason=str(resp.stop_reason))

    def _create(self, kwargs: dict[str, Any]):
        a = self._anthropic
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            except a.BadRequestError:
                # proxies / older deployments may reject the fallbacks field: degrade to a plain call
                pass
        return self.client.messages.create(**kwargs)


def credentials_available() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    prof = os.path.expanduser("~/.config/anthropic")
    return os.path.isdir(prof) and any(os.scandir(prof))


def get_llm(stub_handlers: dict[str, Handler] | None = None, prefer: str | None = None) -> LLM:
    choice = (prefer or os.environ.get("ABL_LLM") or ("anthropic" if credentials_available() else "stub")).lower()
    if choice == "anthropic":
        try:
            return AnthropicLLM()
        except Exception as exc:  # missing SDK or credentials -> deterministic stub
            if prefer == "anthropic":
                raise
            print(f"[llm] anthropic backend unavailable ({exc}); using stub")
    return StubLLM(dict(stub_handlers or {}))
