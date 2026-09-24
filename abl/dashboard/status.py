"""`make status` — one-screen text summary of the last 24h (same numbers as the dashboard, no UI).

    PYTHONPATH=. .venv/bin/python -m dashboard.status [--plain] [--hours 24] [--lang zh|en]

Reads only events.jsonl and the registry (read-only). Works with a missing or empty registry
(prints zeros). Uses ``rich`` when importable, plain print otherwise (or with ``--plain``).
"""
from __future__ import annotations

import argparse
import unicodedata
from datetime import timedelta
from typing import Any

from common import paths
from dashboard.alarms import compute_alarms
from dashboard.control import control_state
from dashboard.i18n import LANGS, t, using_lang
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


def _when(v: Any) -> str:
    return t("exhausted") if v == "exhausted" else str(v)


def _budget_line(b: dict) -> str:
    tu, tc = int(_num(b.get("tokens_used"))), int(_num(b.get("budget_tokens")))
    eu, ec = int(_num(b.get("evals_used"))), int(_num(b.get("budget_full_evals")))
    tp = f" ({tu / tc:.0%})" if tc else ""
    parts = [t("st_b_tokens", tu=f"{tu:,}", tc=f"{tc:,}", tp=tp), t("st_b_evals", eu=eu, ec=ec),
             t("st_b_burn", tph=f"{_num(b.get('tokens_per_hour')):,.0f}", eph=f"{_num(b.get('evals_per_hour')):.2f}")]
    if b.get("tokens_exhaust_at"):
        parts.append(t("st_b_tokens_out", at=_when(b["tokens_exhaust_at"])))
    if b.get("evals_exhaust_at"):
        parts.append(t("st_b_evals_out", at=_when(b["evals_exhaust_at"])))
    state = "" if b.get("active") else t("st_b_ended")
    return t("st_b_line", cid=b.get("campaign_id"), state=state, parts=" · ".join(parts))


def _alarms_title(s: dict) -> str:
    return t("st_sec_alarms", n=len(s["alarms"]))


def sections(s: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    c, tt, st, ctl = s["counts"], s["campaign_to_date"], s["stream"], s["control"]
    h = f"{s['window_hours']:g}"
    reg = s["registry"] + ("" if s["registry_present"] else t("st_reg_missing"))
    if s.get("registry_error"):
        reg += t("st_reg_skipped", err=s["registry_error"])
    ctl_text = {"PAUSED": t("ctl_paused"), "RUNNING": t("ctl_running"), "IDLE": t("ctl_idle")}[ctl["label"]]
    out = [
        (t("st_sec_control"), [(t("st_state"), ctl_text), (t("st_registry"), reg),
                               (t("st_last_event"), st["last_event"] or t("none_value"))]),
        (t("st_sec_learning", h=h), [
            (t("st_proposals"), f"{c['proposals']}"),
            (t("st_critic_verdicts"), t("st_critic_verdicts_val", p=c["critic_pass"], r=c["critic_return"],
                                        j=c["critic_reject"])),
            (t("st_gate_results"), t("st_gate_results_val", p=c["gate_pass"], f=c["gate_fail"])),
            (t("st_promotions"), t("st_promotions_val", p=c["promotions"], r=c["rejections"])),
            (t("st_full_evals"), f"{c['evaluations']}"),
        ]),
        (t("st_sec_cost", h=h), [
            (t("st_tokens"), t("st_tokens_val", n=f"{int(c['tokens']):,}", m=f"{int(tt['tokens']):,}")),
            (t("st_cost"), t("st_cost_val", a=f"{_num(c['cost_usd']):.4f}", b=f"{_num(tt['cost_usd']):.4f}")),
            (t("st_agent_calls"), f"{c['agent_calls']}"),
            (t("st_event_stream"), t("st_event_stream_val", n=st["events"], tok=f"{st['tokens']:,}",
                                     cost=f"{st['cost_usd']:.4f}")),
        ]),
        (t("st_sec_budget"), [(t("st_evals_vs_cap"), _budget_line(b)) for b in s["budget"]]
         or [(t("st_evals_vs_cap"), t("st_no_campaign"))]),
        (_alarms_title(s), [(t("st_red", kind=a["kind"]), a["message"]) for a in s["alarms"]]
         or [(t("none_value"), t("st_all_clear"))]),
    ]
    return out


def _width(text: str) -> int:
    """Terminal display width: East Asian wide/fullwidth characters take two columns."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(width - _width(text), 0)


def render_plain(s: dict) -> str:
    lines = [t("st_title", h=f"{s['window_hours']:g}", since=s["since"], now=s["now"])]
    for title, rows in sections(s):
        lines.append("")
        lines.append(title)
        width = max(_width(k) for k, _ in rows)
        lines.extend(f"  {_pad(k, width)}  {v}" for k, v in rows)
    return "\n".join(lines)


def render_rich(s: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print(t("st_title_rich", h=f"{s['window_hours']:g}", since=s["since"], now=s["now"]))
    alarms_title = _alarms_title(s)
    for title, rows in sections(s):
        red = title == alarms_title and bool(s["alarms"])
        table = Table(title=title, title_justify="left", show_header=False, expand=False,
                      title_style="bold red" if red else "bold", border_style="red" if red else "dim")
        table.add_column(style="red" if red else "cyan", no_wrap=True)
        table.add_column(overflow="fold")
        for k, v in rows:
            table.add_row(k, v)
        console.print(table)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=t("st_help"))
    ap.add_argument("--plain", action="store_true", help=t("st_help_plain"))
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--lang", choices=LANGS, default=None, help=t("cli_help_lang"))
    args = ap.parse_args(argv)
    with using_lang(args.lang):                       # --lang overrides ABL_LANG for this run only
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
