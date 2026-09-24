"""`make digest` — writes registry/digest_YYYY-MM-DD.md, a two-minute read (OPS.md D.1/D.3).

Sections: 5 bullets on what was learned, 3 on what was rejected and why, alarms, cost, and the
single next experiment the Analyst proposed. Every number comes from SQL (read-only registry).
Only the narrative bullets go through ``common.llm.get_llm`` (role ``digest``): offline that is
the deterministic StubLLM handler below; with Anthropic credentials it is the real model. Any
LLM bullet quoting a number that is not in the SQL facts is replaced by the deterministic
bullet, so the LLM can reword but never change a number.

    PYTHONPATH=. .venv/bin/python -m dashboard.digest [--print]
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from common import paths
from common.llm import get_llm
from common.seeds import derive_seed
from dashboard.alarms import compute_alarms
from dashboard.narrative import strip_verdict
from dashboard.reader import (RegistryReader, as_utc, events_since, iso, load_events, parse_ts,
                              read_prompt_output, window_row)

WINDOW = timedelta(hours=24)
N_LEARNED, N_REJECTED = 5, 3
SYSTEM = (
    "You write the narrative bullets of a daily digest for ABL, a genomic-selection research harness. "
    "Use ONLY the JSON facts you are given. Copy every number exactly as it appears in the facts: never "
    "compute, round, convert or invent a number. Plain language for a breeding manager, one sentence each. "
    f"Return JSON: learned = exactly {N_LEARNED} bullets on what was learned, rejected = exactly {N_REJECTED} "
    "bullets on what the harness rejected and why."
)
SCHEMA = {
    "type": "object",
    "properties": {"learned": {"type": "array", "items": {"type": "string"}},
                   "rejected": {"type": "array", "items": {"type": "string"}}},
    "required": ["learned", "rejected"],
    "additionalProperties": False,
}
_NUM = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def _r(v: Any, nd: int = 4) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else round(f, nd)


def _i(v: Any) -> int:
    f = _r(v, 0)
    return int(f) if f is not None else 0


def _json_list(v: Any) -> list:
    if isinstance(v, list):
        return v
    try:
        out = json.loads(v) if isinstance(v, str) else []
    except ValueError:
        return [v] if v else []
    return out if isinstance(out, list) else [out]


# --------------------------------------------------------------------------------------------
# facts (all numbers from SQL)
# --------------------------------------------------------------------------------------------
def _critic_facts(reader: RegistryReader, since: str, recent_events: list[dict]) -> dict:
    rv = reader.critic_reviews(since)
    bad = rv[rv["verdict"].isin(["RETURN", "REJECT"])] if not rv.empty else rv
    leaks: dict[str, int] = {}
    example: dict[str, str] = {}
    summaries = {str(e.get("candidate_id")): str(e.get("summary") or "") for e in recent_events
                 if str(e.get("agent") or "").lower() == "critic" and e.get("candidate_id")}
    for r in bad.to_dict("records") if not bad.empty else []:
        for lt in _json_list(r.get("leak_type")) or ["unspecified"]:
            lt = str(lt)
            leaks[lt] = leaks.get(lt, 0) + 1
            if lt not in example:
                note = strip_verdict(summaries.get(str(r.get("candidate_id")), ""))
                if not note:
                    ev = _json_list(r.get("evidence"))
                    note = str(ev[0].get("note", "")) if ev and isinstance(ev[0], dict) else ""
                example[lt] = f"{r.get('candidate_id')}: {note}".strip(": ")
    top = sorted(leaks.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"returned_or_rejected": int(len(bad)),
            "leak_types": [{"leak_type": k, "n": v, "example": example.get(k, "")} for k, v in top[:5]]}


def _gate_failure_facts(reader: RegistryReader, since: str) -> list[dict]:
    gf = reader.gate_failures(since, limit=500)
    if gf.empty:
        return []
    out = []
    for gate, g in gf.groupby("gate"):
        ex = g.iloc[0]
        out.append({"gate": str(gate), "n": int(len(g)), "example_candidate": str(ex["candidate_id"]),
                    "metric": str(ex["metric"]), "value": _r(ex["value"]), "threshold": _r(ex["threshold"])})
    return sorted(out, key=lambda d: (-d["n"], d["gate"]))


def build_facts(now: Any = None, reader: RegistryReader | None = None, events: list[dict] | None = None,
                window: timedelta = WINDOW) -> dict:
    n = as_utc(now)
    since = iso(n - window)
    reader = reader if reader is not None else RegistryReader()
    all_events = load_events() if events is None else [e for e in events if isinstance(e, dict)]
    recent = events_since(all_events, n - window)
    c = window_row(reader.window_counts(since))
    ctd = window_row(reader.window_counts(None))

    mm = reader.mechanism_map()
    if not mm.empty:          # negative-control arms are harness probes, not what the agents chose to explore
        mm = mm[~mm["mechanism_cluster"].astype(str).str.startswith("negative_control")]
    total = int(mm["proposals"].sum()) if not mm.empty else 0
    clusters = [{"cluster": str(r["mechanism_cluster"]), "proposals": _i(r["proposals"]),
                 "promoted": _i(r["promoted"]), "rejected": _i(r["rejected"]),
                 "share_pct": _i(round(100.0 * _i(r["proposals"]) / total)) if total else 0}
                for r in mm.head(5).to_dict("records")] if total else []

    ev = reader.evaluations(None)
    best = None
    if not ev.empty:
        d = pd.to_numeric(ev["delta_oos"], errors="coerce")
        if d.notna().any():
            r = ev.loc[d.idxmax()]
            best = {"candidate_id": str(r["candidate_id"]), "cluster": str(r["mechanism_cluster"]),
                    "delta_oos": _r(r["delta_oos"]), "delta_oos_ci_low": _r(r["delta_oos_ci_low"]),
                    "rho": _r(r["rho"])}

    gs = reader.gate_summary(since)
    gates = [{"gate": str(r["gate"]), "n": _i(r["n"]), "passed": _i(r["passed"]), "failed": _i(r["failed"])}
             for r in gs.to_dict("records")] if not gs.empty else []

    nc = reader.negative_control_reviews()
    fp = reader.false_promotions()
    reasons = reader.rejection_reasons(since)
    budget = reader.budget(now=n)
    by_agent = reader.cost_by_agent(since)

    return {
        "date": n.date().isoformat(), "since": since, "until": iso(n),
        "window_hours": round(window.total_seconds() / 3600, 2),
        "last_24h": c, "ledger_to_date": ctd,
        "mechanism_clusters": clusters,
        "best_evaluation": best,
        "gates_last_24h": gates,
        "gate_failures_last_24h": _gate_failure_facts(reader, since),
        "critic_last_24h": _critic_facts(reader, since, recent),
        "rejection_reasons_last_24h": [{"gate": str(r["gate"]), "reason": str(r["reason"]), "n": _i(r["n"])}
                                       for r in reasons.head(5).to_dict("records")] if not reasons.empty else [],
        "negative_controls": {"reviews": int(len(nc)), "rejected": int(pd.to_numeric(nc["correct"]).sum()) if len(nc) else 0,
                              "false_promotions": int(len(fp)),
                              "false_promotion_ids": [str(x) for x in fp["candidate_id"]] if len(fp) else []},
        "budget": [{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()
                    if k in ("campaign_id", "active", "budget_tokens", "tokens_used", "budget_full_evals",
                             "evals_used", "cost_usd", "tokens_per_hour", "evals_per_hour",
                             "tokens_exhaust_at", "evals_exhaust_at")}
                   for r in budget.to_dict("records")],
        "cost_by_agent_last_24h": [{"agent": str(r["agent"]), "calls": _i(r["calls"]), "tokens": _i(r["tokens"]),
                                    "cost_usd": _r(r["cost_usd"], 6)} for r in by_agent.to_dict("records")]
        if not by_agent.empty else [],
        "event_stream_last_24h": {"events": len(recent)},
    }


# --------------------------------------------------------------------------------------------
# deterministic bullets (the StubLLM "digest" handler) and the number guard
# --------------------------------------------------------------------------------------------
def deterministic_bullets(f: dict) -> dict[str, list[str]]:
    c, h = f["last_24h"], f["window_hours"]
    h = int(h) if float(h).is_integer() else h
    learned = [
        f"In the last {h}h the loop produced {c['proposals']} proposals; the Critic passed {c['critic_pass']}, "
        f"returned {c['critic_return']} and rejected {c['critic_reject']}; {c['evaluations']} candidates got a full "
        f"evaluation and {c['promotions']} were promoted.",
    ]
    cl = f["mechanism_clusters"]
    if cl:
        t = cl[0]
        learned.append(f"Most explored mechanism cluster: '{t['cluster']}' with {t['proposals']} proposals "
                       f"({t['share_pct']}% of non-control proposals), {t['promoted']} promoted and {t['rejected']} rejected.")
    else:
        learned.append("No proposals are in the ledger yet, so there is no mechanism map to learn from.")
    b = f["best_evaluation"]
    if b:
        ci = f" (CI low {b['delta_oos_ci_low']})" if b.get("delta_oos_ci_low") is not None else ""
        learned.append(f"Best paired ΔOOS so far is {b['delta_oos']}{ci} for {b['candidate_id']} "
                       f"in cluster '{b['cluster']}'.")
    else:
        learned.append("No full evaluation has been recorded yet, so there is no accuracy evidence either way.")
    g = [x for x in f["gates_last_24h"] if x["failed"] > 0]
    if g:
        t = g[0]
        learned.append(f"The most limiting gate was {t['gate']}: {t['failed']} of {t['n']} checks failed in the last {h}h.")
    elif f["gates_last_24h"]:
        learned.append(f"No gate check failed in the last {h}h.")
    else:
        learned.append(f"No gate results were recorded in the last {h}h.")
    nc = f["negative_controls"]
    if nc["reviews"] or nc["false_promotions"]:
        learned.append(f"Harness reliability: the Critic rejected {nc['rejected']} of {nc['reviews']} negative-control "
                       f"reviews, and {nc['false_promotions']} negative control(s) were falsely promoted.")
    else:
        learned.append("No negative-control candidates have been reviewed yet, so Critic reliability is untested.")

    rejected: list[str] = []
    for lt in f["critic_last_24h"]["leak_types"][:2]:
        ex = f" — e.g. {lt['example'].rstrip('. ')}" if lt.get("example") else ""
        rejected.append(f"The Critic returned or rejected {lt['n']} candidate(s) for {lt['leak_type']} leakage{ex}.")
    for gf in f["gate_failures_last_24h"]:
        if len(rejected) >= N_REJECTED:
            break
        rejected.append(f"Gate {gf['gate']} failed {gf['n']} time(s); e.g. {gf['example_candidate']} had "
                        f"{gf['metric']} = {gf['value']} against threshold {gf['threshold']}.")
    for rr in f["rejection_reasons_last_24h"]:
        if len(rejected) >= N_REJECTED:
            break
        rejected.append(f"{rr['n']} candidate(s) were moved to rejected by {rr['gate']}: {rr['reason'].rstrip('. ')}.")
    fillers = [f"Nothing else was rejected in the last {h}h.",
               "No further rejections to report.",
               "The rejection log is otherwise empty."]
    while len(rejected) < N_REJECTED:
        rejected.append(fillers[len(rejected) % len(fillers)] if rejected else f"Nothing was rejected in the last {h}h.")
    return {"learned": learned[:N_LEARNED], "rejected": rejected[:N_REJECTED]}


def stub_digest_handler(system: str, user: str, schema: dict | None, seed: int) -> dict:
    """StubLLM handler for role "digest": bullets built from the facts JSON in the prompt."""
    start = user.find("{")
    facts = json.loads(user[start:]) if start >= 0 else {}
    return deterministic_bullets(facts)


def numbers_in(text: str) -> set[float]:
    return {round(float(x), 6) for x in _NUM.findall(_THOUSANDS.sub("", text))}


def guard_bullets(proposed: Any, fallback: list[str], allowed: set[float], n: int) -> tuple[list[str], int]:
    """Keep an LLM bullet only if every number in it appears in the SQL facts."""
    items = proposed if isinstance(proposed, list) else []
    out, replaced = [], 0
    for i in range(n):
        cand = items[i] if i < len(items) else None
        if isinstance(cand, str) and cand.strip() and numbers_in(cand) <= allowed:
            out.append(" ".join(cand.split()))
        else:
            out.append(fallback[i])
            replaced += 1
    return out, replaced


def narrative_bullets(facts: dict, llm: Any = None) -> tuple[dict[str, list[str]], str]:
    det = deterministic_bullets(facts)
    facts_json = json.dumps(facts, indent=1, sort_keys=True, ensure_ascii=False, default=str)
    allowed = numbers_in(facts_json)
    try:
        llm = llm if llm is not None else get_llm(stub_handlers={"digest": stub_digest_handler})
        res = llm.complete(role="digest", system=SYSTEM, user="FACTS (JSON):\n" + facts_json, schema=SCHEMA,
                           seed=derive_seed("digest", facts.get("date")))
        parsed = res.parsed if isinstance(res.parsed, dict) else {}
        model = getattr(res, "model", "?")
    except Exception as exc:  # network / credentials / refusal: the deterministic text is always there
        return det, f"deterministic (LLM unavailable: {type(exc).__name__})"
    learned, r1 = guard_bullets(parsed.get("learned"), det["learned"], allowed, N_LEARNED)
    rejected, r2 = guard_bullets(parsed.get("rejected"), det["rejected"], allowed, N_REJECTED)
    note = f"{model}" + (f"; {r1 + r2} bullet(s) replaced by deterministic text (numbers not in SQL facts)"
                         if r1 + r2 else "")
    return {"learned": learned, "rejected": rejected}, note


# --------------------------------------------------------------------------------------------
# next experiment (Analyst)
# --------------------------------------------------------------------------------------------
def _extract_next(out: Any) -> Any:
    if isinstance(out, dict):
        if out.get("next_experiment"):
            return out["next_experiment"]
        ev = out.get("evaluation")
        if isinstance(ev, dict) and ev.get("next_experiment"):
            return ev["next_experiment"]
    return None


def next_experiment(reader: RegistryReader, events: list[dict] | None = None) -> dict | None:
    """Latest agent_events row with agent='analyst' -> registry/prompts/<output_hash>.out.txt ->
    ``next_experiment``. Falls back to the latest analyst line in events.jsonl if the ledger has none."""
    rows = reader.latest_analyst_event().to_dict("records")
    if not rows and events:
        an = [e for e in events if str(e.get("agent") or "").lower() == "analyst" and e.get("output_hash")]
        if an:
            rows = [max(an, key=lambda e: parse_ts(e.get("ts")) or parse_ts("1970-01-01T00:00:00Z"))]
    if not rows:
        return None
    r = rows[0]
    h = str(r.get("output_hash") or "")
    return {"ts": r.get("ts"), "campaign_id": r.get("campaign_id"), "candidate_id": r.get("candidate_id"),
            "source": f"registry/prompts/{h}.out.txt", "next_experiment": _extract_next(read_prompt_output(h))}


# --------------------------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------------------------
def _fmt_int(v: Any) -> str:
    return f"{_i(v):,}"


def render_markdown(facts: dict, bullets: dict, alarms: list, nxt: dict | None, backend: str) -> str:
    c, t = facts["last_24h"], facts["ledger_to_date"]
    h = facts["window_hours"]
    h = int(h) if float(h).is_integer() else h
    L = [f"# ABL daily digest — {facts['date']}", "",
         f"_Window: last {h} h ({facts['since']} → {facts['until']}). Numbers come from the registry (SQL, "
         f"read-only); narrative bullets: {backend}._", "",
         "## What was learned", ""]
    L += [f"- {b}" for b in bullets["learned"]]
    L += ["", "## What was rejected and why", ""]
    L += [f"- {b}" for b in bullets["rejected"]]
    L += ["", "## Alarms", ""]
    L += [f"- **RED `{a.kind}`** — {a.message}" for a in alarms] or ["- None. All policy checks are clear."]
    L += ["", "## Cost", "",
          f"| Metric | Last {h} h | Ledger to date |", "|---|---:|---:|",
          f"| Tokens | {_fmt_int(c['tokens'])} | {_fmt_int(t['tokens'])} |",
          f"| Cost (USD) | ${float(c['cost_usd']):.4f} | ${float(t['cost_usd']):.4f} |",
          f"| Agent calls | {_fmt_int(c['agent_calls'])} | {_fmt_int(t['agent_calls'])} |",
          f"| Full evaluations (distinct candidates) | {_fmt_int(c['evaluations'])} | {_fmt_int(t['evaluations'])} |",
          f"| Evaluation compute (s) | {float(c['compute_seconds']):,.1f} | {float(t['compute_seconds']):,.1f} |", ""]
    active = [b for b in facts["budget"] if b.get("active")]
    if active:
        L += ["| Campaign | Tokens used / cap | Full evals used / cap | Burn (tokens/h) | Tokens run out |",
              "|---|---:|---:|---:|---|"]
        for b in active:
            L.append(f"| {b['campaign_id']} | {_fmt_int(b['tokens_used'])} / {_fmt_int(b['budget_tokens'])} | "
                     f"{_i(b['evals_used'])} / {_i(b['budget_full_evals'])} | {float(b['tokens_per_hour'] or 0):,.0f} | "
                     f"{b.get('tokens_exhaust_at') or '—'} |")
        L.append("")
    if facts["cost_by_agent_last_24h"]:
        L += [f"Where the tokens went (last {h} h): " + "; ".join(
            f"{a['agent']} {a['tokens']:,} tokens / {a['calls']} call{'' if a['calls'] == 1 else 's'}"
            for a in facts["cost_by_agent_last_24h"]), ""]
    L += ["## Next experiment (Analyst)", ""]
    if nxt and nxt.get("next_experiment"):
        ne = nxt["next_experiment"]
        if isinstance(ne, str):
            L.append("> " + " ".join(ne.split()))
        else:
            L += ["```json", json.dumps(ne, indent=2, ensure_ascii=False, sort_keys=True), "```"]
        L += ["", f"_Source: Analyst call at {nxt.get('ts')} on {nxt.get('candidate_id') or 'n/a'} "
                  f"(`{nxt.get('source')}`)._"]
    elif nxt:
        L.append(f"The latest Analyst call ({nxt.get('ts')}) recorded no `next_experiment` "
                 f"(`{nxt.get('source')}`).")
    else:
        L.append("No Analyst call has been recorded yet.")
    return "\n".join(L) + "\n"


def digest_path(date: str) -> Path:
    return paths.registry_dir() / f"digest_{date}.md"


def write_digest(now: Any = None, reader: RegistryReader | None = None, events: list[dict] | None = None,
                 llm: Any = None) -> Path:
    n = as_utc(now)
    reader = reader if reader is not None else RegistryReader()
    all_events = load_events() if events is None else events
    facts = build_facts(n, reader, all_events)
    bullets, backend = narrative_bullets(facts, llm)
    alarms = compute_alarms(all_events, reader, n)
    nxt = next_experiment(reader, all_events)
    out = digest_path(facts["date"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(facts, bullets, alarms, nxt, backend), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write registry/digest_YYYY-MM-DD.md (read-only on the ledger)")
    ap.add_argument("--print", action="store_true", dest="show", help="also print the digest")
    args = ap.parse_args(argv)
    p = write_digest()
    print(f"wrote {p}")
    if args.show:
        print(p.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
