"""One plain-language line per agent event (OPS.md D.3 "Live narrative feed").

``narrate(event) -> (text, level)`` with level in {"info", "warn", "fail", "promote"}:
Critic returns are "warn", Critic rejections, gate failures and serious policy flags are
"fail", promotions are "promote". Works on the D.2 event schema and tolerates extra keys
(``verdict``, ``gate``, ``passed``, ``to_state``, ``disposition``) or missing ones.
"""
from __future__ import annotations

import re
from typing import Any

from dashboard.i18n import t
from dashboard.reader import event_flags

LEVELS = ("info", "warn", "fail", "promote")
GATES = ("validity", "accuracy", "incremental", "plan", "robustness", "research")
GATE_AGENTS = {"gate", "gates", "evaluator", "evaluate", "evaluation", "harness", "engine"}
# role -> i18n key (ids, DSL text, metric and gate names stay untranslated)
AGENT_KEYS = {"orchestrator": "agent_orchestrator", "geneticist": "agent_geneticist",
              "researcher": "agent_geneticist", "builder": "agent_builder", "critic": "agent_critic",
              "analyst": "agent_analyst", "registry": "agent_registry", "digest": "agent_digest",
              "final_table": "agent_final_table"}
# action -> i18n key of the past-tense verb
VERB_KEYS = {"propose": "verb_proposed", "hypothesize": "verb_proposed", "hypothesis": "verb_proposed",
             "build": "verb_implemented", "implement": "verb_implemented", "diagnose": "verb_diagnosed",
             "analyse": "verb_analysed", "analyze": "verb_analysed", "register": "verb_registered",
             "plan": "verb_planned", "allocate": "verb_allocated", "step": "verb_stepped",
             "status": "verb_reported_status", "validate": "verb_validated", "evaluate": "verb_evaluated",
             "review": "verb_reviewed", "dedup": "verb_deduplicated", "stop": "verb_stopped",
             "pause": "verb_paused", "select": "verb_selected", "defer": "verb_deferred", "end": "verb_ended",
             "budget": "verb_budget_cap", "retry_limit": "verb_retry_limit", "reject": "verb_rejected"}
LEADING_VERBS = ("proposed", "built", "implemented", "diagnosed")
SERIOUS_FLAGS = {"holdout_touch", "budget_exceeded", "threshold_edit", "retry_limit"}
# policy flag -> i18n key of its explanation (unknown flags are shown as-is)
FLAG_KEYS = {"holdout_touch": "flag_holdout_touch", "budget_exceeded": "flag_budget_exceeded",
             "threshold_edit": "flag_threshold_edit", "retry_limit": "flag_retry_limit",
             "holdout_final_read": "flag_holdout_final_read", "paused": "flag_paused"}
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
    return t("narr_reason", text=text, reason=reason) if reason else text


def _generic(text: str, summary: str) -> str:
    """Non-critic agents: drop a leading verb the line already says; lift "[cluster]:" next to it."""
    rest = summary.strip()
    m = re.match(rf"^({'|'.join(LEADING_VERBS)})\b\s*", rest, re.I)
    if m:
        rest = rest[m.end():]
    b = re.match(r"^\[([^\]]+)\]\s*:?\s*(.*)$", rest)
    if b:
        text, rest = t("narr_cluster_tag", text=text, cluster=b.group(1)), b.group(2)
    return t("narr_reason", text=text, reason=rest) if rest else text


def _who(agent: str) -> str:
    key = AGENT_KEYS.get(agent.lower())
    if key:
        return t(key)
    return agent[:1].upper() + agent[1:] if agent else t("agent_unknown")


def narrate(event: Any) -> tuple[str, str]:
    """Plain-language line for one event (in the current i18n language) and its highlight level.

    The level is a language-independent identifier."""
    if not isinstance(event, dict):
        return t("narr_unreadable"), "warn"
    agent = str(event.get("agent") or "").strip()
    a = agent.lower()
    action = str(event.get("action") or "").strip().lower()
    cand = event.get("candidate_id")
    cand = str(cand) if cand not in (None, "") else None
    summary = _clean(event.get("summary"))
    who = _who(agent)
    is_gate = a in GATE_AGENTS or "gate" in event or action.startswith("gate")
    to_state = _to_state(event, action)
    level = "info"

    if a == "critic":
        target = t("narr_target_cand", cand=cand) if cand else t("narr_target_the")
        verdict = _verdict(event, action, summary)
        leak = _leak_group(summary)
        tag = t("narr_leak_tag", leak=leak) if leak else ""
        if verdict == "RETURN":
            text, level = _append_reason(t("narr_critic_return", target=target, tag=tag), summary), "warn"
        elif verdict == "REJECT":
            text, level = _append_reason(t("narr_critic_reject", target=target, tag=tag), summary), "fail"
        elif verdict == "PASS":
            text = _append_reason(t("narr_critic_pass", target=target), summary)
        else:
            text = _append_reason(t("narr_critic_review", target=target), summary)
    elif to_state == "promoted" and (is_gate or a in ("registry", "orchestrator")):
        text, level = _append_reason(t("narr_promoted", cand=cand or "?"), summary), "promote"
    elif is_gate:
        g = _gate(event, action, summary) or "?"
        passed = _passed(event, action, summary)
        summary = re.sub(rf"^\s*{re.escape(g)}(?:\s+gate)?\s+(?:failed|passed|fail|pass)\s*[:\-—]\s*", "",
                         summary, flags=re.I)
        if str(event.get("source") or "") == "registry:gate_results":     # "<metric> <v> vs threshold <thr>"
            summary = summary.replace(" vs threshold ", t("narr_vs_threshold"))
        target = t("narr_gate_target", cand=cand) if cand else t("narr_target_the")
        if to_state == "rejected" and g == "promotion":
            text, level = _append_reason(t("narr_rejected", cand=cand or "?"), summary, False), "fail"
        elif to_state == "rejected":
            text, level = _append_reason(t("narr_gate_rejected", gate=g, target=target), summary, False), "fail"
        elif passed is False:
            text, level = _append_reason(t("narr_gate_failed", gate=g, target=target), summary), "fail"
        elif passed is True:
            text = _append_reason(t("narr_gate_passed", gate=g, target=target), summary)
        else:
            text = _append_reason(t("narr_gate_ran", gate=g, target=target), summary)
    elif a == "builder" and summary.upper().startswith("NEED_OPERATOR"):
        target = t("narr_need_operator_target", cand=cand) if cand else ""
        spec = summary[len("NEED_OPERATOR"):].lstrip(" :")
        text, level = _append_reason(t("narr_need_operator", target=target), spec, False), "warn"
    else:
        vkey = VERB_KEYS.get(action)
        if vkey:
            verb = t(vkey)
        elif action:
            verb = t("verb_unknown", action=action.replace("_", " "))
        else:
            verb = t("verb_acted")
        if cand:
            head = t("narr_generic_cand", who=who, verb=verb, cand=cand)
        elif a in ("geneticist", "researcher") and vkey == "verb_proposed":
            head = t("narr_generic_hypothesis", who=who, verb=verb)
        else:
            head = t("narr_generic", who=who, verb=verb)
        text = _generic(head, summary)

    flags = event_flags(event)
    if flags:
        items = t("sep_list").join(t("narr_policy_item", flag=f, text=t(FLAG_KEYS[f]) if f in FLAG_KEYS else f)
                                   for f in flags)
        text += t("narr_policy", items=items)
        if SERIOUS_FLAGS.intersection(flags):
            level = "fail"
        elif level == "info":
            level = "warn"
    return text, level
