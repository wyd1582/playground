"""One plain-language line per agent event (OPS.md D.3 "Live narrative feed").

``narrate(event) -> (text, level)`` with level in {"info", "warn", "fail", "promote"}:
Critic returns are "warn", Critic rejections, gate failures and serious policy flags are
"fail", promotions are "promote". Works on the D.2 event schema and tolerates extra keys
(``verdict``, ``gate``, ``passed``, ``to_state``, ``disposition``) or missing ones.
"""
from __future__ import annotations

import re
from typing import Any

from dashboard.reader import event_flags

LEVELS = ("info", "warn", "fail", "promote")
GATES = ("validity", "accuracy", "incremental", "plan", "robustness", "research")
GATE_AGENTS = {"gate", "gates", "evaluator", "evaluate", "evaluation", "harness", "engine"}
AGENT_NAMES = {"orchestrator": "Orchestrator", "geneticist": "Geneticist", "researcher": "Geneticist",
               "builder": "Builder", "critic": "Critic", "analyst": "Analyst", "registry": "Registry",
               "digest": "Digest", "final_table": "Final table"}
VERBS = {"propose": "proposed", "hypothesize": "proposed", "hypothesis": "proposed", "build": "implemented",
         "implement": "implemented", "diagnose": "diagnosed", "analyse": "analysed", "analyze": "analysed",
         "register": "registered", "plan": "planned", "allocate": "allocated budget for", "step": "stepped",
         "status": "reported status", "validate": "validated", "evaluate": "evaluated", "review": "reviewed",
         "dedup": "deduplicated", "stop": "stopped", "pause": "paused", "select": "selected",
         "defer": "deferred", "end": "ended the campaign", "budget": "hit the budget cap",
         "retry_limit": "hit the retry limit for", "reject": "rejected"}
LEADING_VERBS = ("proposed", "built", "implemented", "diagnosed")
SERIOUS_FLAGS = {"holdout_touch", "budget_exceeded", "threshold_edit", "retry_limit"}
FLAG_TEXT = {"holdout_touch": "tried to touch the sealed holdout",
             "budget_exceeded": "budget exceeded",
             "threshold_edit": "attempted a gate-threshold edit",
             "retry_limit": "retry limit exceeded",
             "holdout_final_read": "sanctioned final holdout read",
             "paused": "stopped: control/PAUSE present"}
MAX_SUMMARY = 280
# "Returned to builder: …", "RETURN_TO_BUILDER (temporal): …", "REJECT — …", "PASS (-): …"
_PREFIX = re.compile(r"^\s*(returned\s+to\s+builder|return(?:_to_builder)?|rejected|reject|passed|pass|"
                     r"approved|failed|fail|promoted)\b\s*(?:\(([^)]*)\))?\s*(?:[:\-—]\s*|$)", re.I)


def _clean(s: Any) -> str:
    text = " ".join(str(s or "").split())
    return text if len(text) <= MAX_SUMMARY else text[: MAX_SUMMARY - 1] + "…"


def _verdict(ev: dict, action: str, summary: str) -> str | None:
    v = ev.get("verdict")
    if isinstance(v, str) and v.strip():
        u = v.strip().upper()
        if u.startswith("RETURN"):
            return "RETURN"
        if u.startswith("REJECT"):
            return "REJECT"
        if u in ("PASS", "APPROVE", "APPROVED"):
            return "PASS"
    for key, val in (("return", "RETURN"), ("reject", "REJECT"), ("pass", "PASS"), ("approve", "PASS")):
        if key in action:
            return val
    m = re.match(r"\s*(returned?|rejected?|pass(?:ed)?|approved?)\b", summary, re.I)
    if m:
        w = m.group(1).lower()
        return "RETURN" if w.startswith("return") else "REJECT" if w.startswith("reject") else "PASS"
    m = re.search(r"\b(RETURN_TO_BUILDER|RETURN|REJECT|PASS)\b", summary)
    if m:
        return "RETURN" if m.group(1).startswith("RETURN") else m.group(1)
    return None


def _gate(ev: dict, action: str, summary: str) -> str | None:
    g = ev.get("gate")
    if isinstance(g, str) and g.strip():
        return g.strip()
    for text in (action, summary.lower()):
        for name in GATES:
            if re.search(rf"\b{name}\b", text):
                return name
    return None


def _passed(ev: dict, action: str, summary: str) -> bool | None:
    p = ev.get("passed")
    if isinstance(p, bool):
        return p
    if isinstance(p, (int, float)) and p in (0, 1):
        return bool(p)
    for key in ("result", "status", "outcome"):
        v = ev.get(key)
        if isinstance(v, str):
            if re.match(r"\s*fail", v, re.I):
                return False
            if re.match(r"\s*pass", v, re.I):
                return True
    if re.search(r"\bfail(?:ed|s|ure)?\b", summary, re.I) or "fail" in action:
        return False
    if re.search(r"\bpass(?:ed|es)?\b", summary, re.I) or "pass" in action:
        return True
    return None


def _to_state(ev: dict, action: str) -> str | None:
    for key in ("to_state", "disposition", "state"):
        v = ev.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    if action in ("promote", "promoted", "promotion"):
        return "promoted"
    if action in ("reject", "rejected"):
        return "rejected"
    return None


def strip_verdict(summary: str) -> str:
    """Drop a leading "Returned to builder:" / "REJECT —" / "PASS:" style prefix."""
    return _PREFIX.sub("", " ".join(str(summary or "").split())).strip()


def _leak_group(summary: str) -> str | None:
    m = _PREFIX.match(summary)
    g = (m.group(2) or "").strip() if m else ""
    return g if g and g != "-" else None


def _append_reason(text: str, summary: str, strip: bool = True) -> str:
    reason = strip_verdict(summary) if strip else summary.strip()
    return f"{text}: {reason}" if reason else text


def _generic(text: str, summary: str) -> str:
    """Non-critic agents: drop a leading verb the line already says; lift "[cluster]:" next to it."""
    rest = summary.strip()
    m = re.match(rf"^({'|'.join(LEADING_VERBS)})\b\s*", rest, re.I)
    if m:
        rest = rest[m.end():]
    b = re.match(r"^\[([^\]]+)\]\s*:?\s*(.*)$", rest)
    if b:
        text, rest = f"{text} [{b.group(1)}]", b.group(2)
    return f"{text}: {rest}" if rest else text


def narrate(event: Any) -> tuple[str, str]:
    """Plain-language line for one event and its highlight level."""
    if not isinstance(event, dict):
        return "Unreadable event (not a JSON object)", "warn"
    agent = str(event.get("agent") or "").strip()
    a = agent.lower()
    action = str(event.get("action") or "").strip().lower()
    cand = event.get("candidate_id")
    cand = str(cand) if cand not in (None, "") else None
    summary = _clean(event.get("summary"))
    who = AGENT_NAMES.get(a, agent[:1].upper() + agent[1:] if agent else "Unknown agent")
    is_gate = a in GATE_AGENTS or "gate" in event or action.startswith("gate")
    to_state = _to_state(event, action)
    level = "info"

    if a == "critic":
        target = f"candidate {cand}" if cand else "the candidate"
        verdict = _verdict(event, action, summary)
        leak = _leak_group(summary)
        tag = f" ({leak})" if leak else ""
        if verdict == "RETURN":
            text, level = _append_reason(f"Critic returned {target} to builder{tag}", summary), "warn"
        elif verdict == "REJECT":
            text, level = _append_reason(f"Critic rejected {target}{tag}", summary), "fail"
        elif verdict == "PASS":
            text = _append_reason(f"Critic passed {target}", summary)
        else:
            text = _append_reason(f"Critic reviewed {target}", summary)
    elif to_state == "promoted" and (is_gate or a in ("registry", "orchestrator")):
        text, level = _append_reason(f"Candidate {cand or '?'} PROMOTED", summary), "promote"
    elif is_gate:
        g = _gate(event, action, summary) or "?"
        passed = _passed(event, action, summary)
        summary = re.sub(rf"^\s*{re.escape(g)}(?:\s+gate)?\s+(?:failed|passed|fail|pass)\s*[:\-—]\s*", "",
                         summary, flags=re.I)
        if to_state == "rejected" and g == "promotion":
            text, level = _append_reason(f"Candidate {cand or '?'} REJECTED at promotion", summary, False), "fail"
        elif to_state == "rejected":
            text, level = _append_reason(f"Gate {g} rejected {cand or 'the candidate'}", summary, False), "fail"
        elif passed is False:
            text, level = _append_reason(f"Gate {g} FAILED for {cand or 'the candidate'}", summary), "fail"
        elif passed is True:
            text = _append_reason(f"Gate {g} passed for {cand or 'the candidate'}", summary)
        else:
            text = _append_reason(f"Gate {g} ran on {cand or 'the candidate'}", summary)
    elif a == "builder" and summary.upper().startswith("NEED_OPERATOR"):
        target = f" for candidate {cand}" if cand else ""
        spec = summary[len("NEED_OPERATOR"):].lstrip(" :")
        text, level = _append_reason(f"Builder needs a new DSL operator{target}", spec, False), "warn"
    else:
        verb = VERBS.get(action, action.replace("_", " ") if action else "acted on")
        if cand:
            obj = f" candidate {cand}"
        elif a in ("geneticist", "researcher") and verb == "proposed":
            obj = " a hypothesis"
        else:
            obj = ""
        text = _generic(f"{who} {verb}{obj}", summary)

    flags = event_flags(event)
    if flags:
        text += " [policy: " + "; ".join(f"{f} — {FLAG_TEXT.get(f, f)}" for f in flags) + "]"
        if SERIOUS_FLAGS.intersection(flags):
            level = "fail"
        elif level == "info":
            level = "warn"
    return text, level
