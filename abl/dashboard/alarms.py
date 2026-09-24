"""Policy alarms for the Guardian panel (OPS.md D.1/D.3) and their notifications.

``compute_alarms`` is pure: it reads the event list it is given plus the registry through a
:class:`~dashboard.reader.RegistryReader` and returns one :class:`Alarm` per firing kind.
``notify`` is the only writer here: registry/alarms.log, dashboard/state.json and — on macOS
only — ``osascript`` desktop notifications, at most once per 10 minutes per alarm kind.

``python -m dashboard.alarms`` runs the same checks headless every 5 s (``--once`` for a single
pass), so notifications keep flowing when no browser tab has the Streamlit page open.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from common import paths
from dashboard.reader import POLL_SECONDS, EventFeed, RegistryReader, as_utc, event_flags, iso, parse_ts

ALARM_KINDS = ("holdout_touch", "threshold_changed", "retry_limit", "budget_exceeded",
               "cluster_concentration", "suspicious_pass_rate", "events_stalled")
RETRY_LIMIT = 2                          # DESIGN.md P1: retry limit 2 per hypothesis
FLAG_WINDOW = timedelta(hours=24)        # retry_limit / budget_exceeded / threshold_edit flags stay red 24h
CLUSTER_MAX_SHARE = 0.40
CLUSTER_MIN_PROPOSALS = 10
PASS_RATE_FACTOR = 3.0
PASS_RATE_WINDOW = timedelta(hours=24)
PASS_RATE_MIN_RECENT = 10                # gate rows needed in the last 24h ...
PASS_RATE_MIN_BASELINE = 20              # ... and before it, before the ratio means anything
STALL_AFTER = timedelta(minutes=15)
NOTIFY_EVERY = timedelta(minutes=10)


@dataclass(frozen=True)
class Alarm:
    kind: str
    message: str
    ts: str
    severity: str = "red"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def state_file() -> Path:
    return paths.root() / "dashboard" / "state.json"


def alarms_log_file() -> Path:
    return paths.registry_dir() / "alarms.log"


# --------------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------------
def _flagged(events: list[dict], flag: str, now: datetime, window: timedelta | None) -> list[dict]:
    out = []
    for ev in events:
        if flag not in event_flags(ev):
            continue
        if window is not None:
            t = parse_ts(ev.get("ts"))
            if t is not None and t < now - window:
                continue
        out.append(ev)
    return out


def _latest(evs: list[dict]) -> dict:
    return max(evs, key=lambda e: str(e.get("ts") or ""))


def _describe(ev: dict) -> str:
    who = ev.get("agent") or "?"
    act = ev.get("action") or "?"
    cand = ev.get("candidate_id")
    return f"{who}/{act}" + (f" on {cand}" if cand else "") + f" at {ev.get('ts') or '?'}"


def _active_campaigns(reader: RegistryReader) -> set[str] | None:
    """Active campaign ids, or None when the registry lists no campaigns (unknown)."""
    df = reader.campaigns()
    if df.empty:
        return None
    return {str(c) for c, a in zip(df["campaign_id"], df["active"]) if bool(a)}


def _is_tracked(campaign_id: Any, active: set[str] | None) -> bool:
    return active is None or str(campaign_id) in active


def _check_flag(events, flag, kind, now, window, label) -> Alarm | None:
    hits = _flagged(events, flag, now, window)
    if not hits:
        return None
    last = _latest(hits)
    return Alarm(kind, f"{len(hits)} event(s) flagged {flag} ({label}); latest {_describe(last)}",
                 str(last.get("ts") or iso(now)))


def _check_threshold(events, reader, now) -> Alarm | None:
    parts, ts = [], iso(now)
    df = reader.threshold_status()
    for r in df.to_dict("records"):
        if bool(r.get("active")) and bool(r.get("changed")):
            parts.append(f"campaign {r['campaign_id']}: gates/thresholds.yaml sha256 {str(r['start_hash'])[:12]} "
                         f"at start, now {str(r['current_hash'])[:12]}")
    edits = _flagged(events, "threshold_edit", now, FLAG_WINDOW)
    if edits:
        last = _latest(edits)
        parts.append(f"{len(edits)} threshold_edit flag(s); latest {_describe(last)}")
        ts = str(last.get("ts") or ts)
    return Alarm("threshold_changed", "; ".join(parts), ts) if parts else None


def _check_retry(events, reader, now, active) -> Alarm | None:
    parts, ts = [], iso(now)
    hits = _flagged(events, "retry_limit", now, FLAG_WINDOW)
    if hits:
        last = _latest(hits)
        parts.append(f"{len(hits)} event(s) flagged retry_limit; latest {_describe(last)}")
        ts = str(last.get("ts") or ts)
    cands = reader.candidates()
    if not cands.empty:
        over = [r for r in cands.to_dict("records")
                if _is_tracked(r.get("campaign_id"), active) and int(r.get("retry_count") or 0) > RETRY_LIMIT]
        if over:
            ids = ", ".join(f"{r['candidate_id']} ({int(r['retry_count'])})" for r in over[:5])
            parts.append(f"{len(over)} candidate(s) retried more than {RETRY_LIMIT}x: {ids}")
    return Alarm("retry_limit", "; ".join(parts), ts) if parts else None


def _check_budget(events, reader, now) -> Alarm | None:
    parts, ts = [], iso(now)
    hits = _flagged(events, "budget_exceeded", now, FLAG_WINDOW)
    if hits:
        last = _latest(hits)
        parts.append(f"{len(hits)} event(s) flagged budget_exceeded; latest {_describe(last)}")
        ts = str(last.get("ts") or ts)
    b = reader.budget(now=now)
    for r in b.to_dict("records"):
        if not bool(r.get("active")):
            continue
        tu, tc = int(r.get("tokens_used") or 0), int(r.get("budget_tokens") or 0)
        eu, ec = int(r.get("evals_used") or 0), int(r.get("budget_full_evals") or 0)
        if tc and tu > tc:
            parts.append(f"campaign {r['campaign_id']}: tokens {tu:,} > cap {tc:,}")
        if ec and eu > ec:
            parts.append(f"campaign {r['campaign_id']}: full evaluations {eu} > cap {ec}")
    return Alarm("budget_exceeded", "; ".join(parts), ts) if parts else None


def _check_clusters(reader, now, active) -> Alarm | None:
    """Single mechanism cluster > 40% of a campaign's proposals (negative-control arms excluded)."""
    df = reader.diversity()
    if df.empty:
        return None
    parts = []
    for cid, g in df.groupby("campaign_id"):
        if not _is_tracked(cid, active):
            continue
        g = g[~g["mechanism_cluster"].astype(str).str.startswith("negative_control")]
        total = int(g["n"].sum()) if len(g) else 0
        if total < CLUSTER_MIN_PROPOSALS:
            continue
        top = g.sort_values("n", ascending=False).iloc[0]
        share = int(top["n"]) / total
        if share > CLUSTER_MAX_SHARE:
            parts.append(f"campaign {cid}: cluster '{top['mechanism_cluster']}' holds {share:.0%} of "
                         f"{total} proposals (> {CLUSTER_MAX_SHARE:.0%})")
    return Alarm("cluster_concentration", "; ".join(parts), iso(now)) if parts else None


def _check_pass_rate(reader, now, active) -> Alarm | None:
    """Gate pass-rate in the last 24h > 3x the campaign's earlier (Laplace-smoothed) pass-rate."""
    df = reader.gate_pass_rates(iso(now - PASS_RATE_WINDOW))
    parts = []
    for r in df.to_dict("records"):
        if not _is_tracked(r.get("campaign_id"), active):
            continue
        rn, rp = int(r.get("recent_n") or 0), int(r.get("recent_pass") or 0)
        bn, bp = int(r.get("base_n") or 0), int(r.get("base_pass") or 0)
        if rn < PASS_RATE_MIN_RECENT or bn < PASS_RATE_MIN_BASELINE:
            continue
        recent, base = rp / rn, (bp + 1) / (bn + 2)
        if recent > PASS_RATE_FACTOR * base:
            parts.append(f"campaign {r['campaign_id']}: gate pass-rate {recent:.0%} over the last 24h "
                         f"({rp}/{rn}) vs baseline {bp}/{bn} (> {PASS_RATE_FACTOR:g}x)")
    return Alarm("suspicious_pass_rate", "; ".join(parts), iso(now)) if parts else None


def _check_stalled(events, now, active) -> Alarm | None:
    ctl = paths.control_dir()
    if not (ctl / "RUN").exists() or (ctl / "PAUSE").exists():
        return None
    if active is not None and not active:
        return None                    # every campaign in the ledger has ended: nothing should run
    times = [t for t in (parse_ts(e.get("ts")) for e in events) if t is not None]
    last = max(times) if times else None
    if last is None:
        f = paths.events_file()
        try:
            last = datetime.fromtimestamp(f.stat().st_mtime, tz=now.tzinfo)
        except OSError:
            return None                # nothing has ever been written: not stalled, just not started
    if now - last <= STALL_AFTER:
        return None
    mins = int((now - last).total_seconds() // 60)
    return Alarm("events_stalled", f"no agent event for {mins} min (last at {iso(last)}) while control/RUN "
                                   f"exists and control/PAUSE does not", iso(now))


def compute_alarms(events: Iterable[dict] | None, registry_reader: RegistryReader | None = None,
                   now: Any = None) -> list[Alarm]:
    """Every red alarm currently firing, in ALARM_KINDS order. Never raises."""
    n = as_utc(now)
    reader = registry_reader if registry_reader is not None else RegistryReader()
    evs = [e for e in (events or []) if isinstance(e, dict)]
    try:
        active = _active_campaigns(reader)
    except Exception:
        active = None
    checks = [
        lambda: _check_flag(evs, "holdout_touch", "holdout_touch", n, None, "sealed holdout"),
        lambda: _check_threshold(evs, reader, n),
        lambda: _check_retry(evs, reader, n, active),
        lambda: _check_budget(evs, reader, n),
        lambda: _check_clusters(reader, n, active),
        lambda: _check_pass_rate(reader, n, active),
        lambda: _check_stalled(evs, n, active),
    ]
    out: list[Alarm] = []
    for check in checks:
        try:
            a = check()
        except Exception as exc:  # one broken check must not hide the others
            print(f"[alarms] check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if a is not None:
            out.append(a)
    return out


# --------------------------------------------------------------------------------------------
# notifications
# --------------------------------------------------------------------------------------------
def _load_state(p: Path) -> dict:
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(p: Path, state: dict) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        print(f"[alarms] cannot write {p}: {exc}", file=sys.stderr)


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _mac_notify(alarm: Alarm) -> None:
    body = alarm.message if len(alarm.message) <= 220 else alarm.message[:217] + "..."
    script = (f"display notification {_applescript_str(body)} with title "
              f"{_applescript_str('ABL alarm: ' + alarm.kind)}")
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[alarms] osascript failed: {exc}", file=sys.stderr)


def _since(ts: Any, now: datetime) -> timedelta:
    t = parse_ts(ts)
    return now - t if t is not None else timedelta.max


def notify(alarms: Iterable[Alarm], state_path: Path | str | None = None, *, now: Any = None,
           platform: str | None = None) -> list[str]:
    """Log red alarms to registry/alarms.log and, on macOS, raise a desktop notification.

    Throttle (persisted in dashboard/state.json): per kind, a desktop notification at most once
    per 10 minutes; a log line when the alarm's message changes or 10 minutes have passed.
    Returns the kinds whose notification was due this call.
    """
    n = as_utc(now)
    plat = platform if platform is not None else sys.platform
    sp = Path(state_path) if state_path is not None else state_file()
    state = _load_state(sp)
    notified: dict = state.setdefault("notified", {})
    logged: dict = state.setdefault("logged", {})
    lines, due, changed = [], [], False
    for a in alarms:
        if a.severity != "red":
            continue
        last = logged.get(a.kind) if isinstance(logged.get(a.kind), dict) else {}
        if last.get("message") != a.message or _since(last.get("ts"), n) >= NOTIFY_EVERY:
            lines.append(f"{iso(n)}\t{a.severity.upper()}\t{a.kind}\t{a.message}\n")
            logged[a.kind] = {"ts": iso(n), "message": a.message}
            changed = True
        if _since(notified.get(a.kind), n) >= NOTIFY_EVERY:
            if plat == "darwin":
                _mac_notify(a)
            notified[a.kind] = iso(n)
            due.append(a.kind)
            changed = True
    if lines:
        log = alarms_log_file()
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.writelines(lines)
        except OSError as exc:
            print(f"[alarms] cannot append {log}: {exc}", file=sys.stderr)
    if changed:
        _save_state(sp, state)
    return due


# --------------------------------------------------------------------------------------------
# headless watcher
# --------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ABL alarm watcher (read-only; logs + notifies red alarms)")
    ap.add_argument("--once", action="store_true", help="run one pass and exit")
    ap.add_argument("--interval", type=float, default=POLL_SECONDS)
    args = ap.parse_args(argv)
    reader = RegistryReader(keep_last=True)
    feed = EventFeed()
    while True:
        feed.poll()                                   # incremental tail, not a full re-read
        alarms = compute_alarms(feed.alarm_events(), reader)
        due = set(notify(alarms))
        for a in alarms:
            if args.once or a.kind in due:
                print(f"{a.ts}  RED  {a.kind}: {a.message}", flush=True)
        if args.once:
            return 0
        time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
