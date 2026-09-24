"""`make status` — one-screen text summary of the last 24h (same numbers as the dashboard, no UI).

    PYTHONPATH=. .venv/bin/python -m dashboard.status [--plain] [--hours 24]

Reads only events.jsonl and the registry (read-only). Works with a missing or empty registry
(prints zeros). Uses ``rich`` when importable, plain print otherwise (or with ``--plain``).
"""
from __future__ import annotations

import argparse
from datetime import timedelta
from typing import Any

from common import paths
from dashboard.alarms import compute_alarms
from dashboard.control import control_state
from dashboard.reader import (RegistryReader, as_utc, events_since, iso, load_events, parse_ts,
                              window_row)

WINDOW = timedelta(hours=24)


def _num(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f else 0.0


def collect(now: Any = None, reader: RegistryReader | None = None, events: list[dict] | None = None,
            window: timedelta = WINDOW) -> dict:
    """All numbers the status screen shows, as plain Python values."""
    n = as_utc(now)
    since_dt = n - window
    since = iso(since_dt)
    reader = reader if reader is not None else RegistryReader()
    all_events = load_events() if events is None else [e for e in events if isinstance(e, dict)]
    recent = events_since(all_events, since_dt)
    counts = window_row(reader.window_counts(since))
    ctd = window_row(reader.window_counts(None))
    budget = reader.budget(now=n)
    alarms = compute_alarms(all_events, reader, n)
    last = max((t for t in (parse_ts(e.get("ts")) for e in all_events) if t is not None), default=None)
    return {
        "now": iso(n), "since": since, "window_hours": round(window.total_seconds() / 3600, 2),
        "registry": str(reader.db_path), "registry_present": reader.available(),
        "registry_error": reader.last_error if reader.available() else None,
        "events_file": str(paths.events_file()),
        "counts": counts, "campaign_to_date": ctd,
        "budget": [r for r in budget.to_dict("records") if r.get("active")] or budget.to_dict("records")[:1],
        "alarms": [a.to_dict() for a in alarms],
        "control": control_state(),
        "stream": {"events": len(recent), "tokens": int(sum(_num(e.get("tokens")) for e in recent)),
                   "cost_usd": round(sum(_num(e.get("cost_usd")) for e in recent), 4),
                   "last_event": iso(last) if last else None},
    }


def _budget_line(b: dict) -> str:
    tu, tc = int(_num(b.get("tokens_used"))), int(_num(b.get("budget_tokens")))
    eu, ec = int(_num(b.get("evals_used"))), int(_num(b.get("budget_full_evals")))
    tp = f" ({tu / tc:.0%})" if tc else ""
    parts = [f"tokens {tu:,}/{tc:,}{tp}", f"full evals {eu}/{ec}",
             f"burn {_num(b.get('tokens_per_hour')):,.0f} tok/h, {_num(b.get('evals_per_hour')):.2f} evals/h"]
    if b.get("tokens_exhaust_at"):
        parts.append(f"tokens out: {b['tokens_exhaust_at']}")
    if b.get("evals_exhaust_at"):
        parts.append(f"evals out: {b['evals_exhaust_at']}")
    state = "" if b.get("active") else " (ended)"
    return f"{b.get('campaign_id')}{state}: " + " · ".join(parts)


def sections(s: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    c, t, st, ctl = s["counts"], s["campaign_to_date"], s["stream"], s["control"]
    reg = s["registry"] + ("" if s["registry_present"] else "  (missing — showing zeros)")
    if s.get("registry_error"):
        reg += f"  (skipped: {s['registry_error']})"
    ctl_text = {"PAUSED": "PAUSED — control/PAUSE exists", "RUNNING": "RUNNING — control/RUN present, no PAUSE",
                "IDLE": "IDLE — control/RUN missing"}[ctl["label"]]
    out = [
        ("Control", [("State", ctl_text), ("Registry", reg),
                     ("Last event", st["last_event"] or "none")]),
        (f"Learning (last {s['window_hours']:g}h)", [
            ("Proposals", f"{c['proposals']}"),
            ("Critic verdicts", f"PASS {c['critic_pass']} · RETURN {c['critic_return']} · REJECT {c['critic_reject']}"),
            ("Gate results", f"passed {c['gate_pass']} · failed {c['gate_fail']}"),
            ("Promotions", f"{c['promotions']}  (rejections {c['rejections']})"),
            ("Full evaluations", f"{c['evaluations']}"),
        ]),
        (f"Cost (last {s['window_hours']:g}h)", [
            ("Tokens", f"{int(c['tokens']):,}  (ledger to date {int(t['tokens']):,})"),
            ("Cost", f"${_num(c['cost_usd']):.4f}  (ledger to date ${_num(t['cost_usd']):.4f})"),
            ("Agent calls", f"{c['agent_calls']}"),
            ("Event stream", f"{st['events']} events · {st['tokens']:,} tokens · ${st['cost_usd']:.4f}"),
        ]),
        ("Budget", [("Evaluations vs cap", _budget_line(b)) for b in s["budget"]]
         or [("Evaluations vs cap", "0 / 0 (no campaign in the registry)")]),
        (f"Alarms ({len(s['alarms'])})", [(f"RED {a['kind']}", a["message"]) for a in s["alarms"]]
         or [("none", "all clear")]),
    ]
    return out


def render_plain(s: dict) -> str:
    lines = [f"ABL status — last {s['window_hours']:g}h ({s['since']} → {s['now']})"]
    for title, rows in sections(s):
        lines.append("")
        lines.append(title)
        width = max(len(k) for k, _ in rows)
        lines.extend(f"  {k.ljust(width)}  {v}" for k, v in rows)
    return "\n".join(lines)


def render_rich(s: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print(f"[bold]ABL status[/bold] — last {s['window_hours']:g}h ({s['since']} → {s['now']})")
    for title, rows in sections(s):
        red = title.startswith("Alarms") and bool(s["alarms"])
        table = Table(title=title, title_justify="left", show_header=False, expand=False,
                      title_style="bold red" if red else "bold", border_style="red" if red else "dim")
        table.add_column(style="red" if red else "cyan", no_wrap=True)
        table.add_column(overflow="fold")
        for k, v in rows:
            table.add_row(k, v)
        console.print(table)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ABL one-screen status (read-only)")
    ap.add_argument("--plain", action="store_true", help="plain text even if rich is installed")
    ap.add_argument("--hours", type=float, default=24.0)
    args = ap.parse_args(argv)
    summary = collect(window=timedelta(hours=args.hours))
    if not args.plain:
        try:
            render_rich(summary)
            return 0
        except ImportError:
            pass
    print(render_plain(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
