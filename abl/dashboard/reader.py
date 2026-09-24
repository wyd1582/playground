"""Read-only data layer for the Guardian & Learning dashboard (OPS.md D.1-D.3).

No streamlit in here. Exactly two sources:

* ``registry/events.jsonl`` — tailed incrementally (:func:`tail_events`, :func:`load_events`,
  :class:`EventFeed`); a partially written last line is left for the next tick.
* the SQLite registry — only through :func:`registry.db.connect_readonly` (URI ``mode=ro``).

Every :class:`RegistryReader` method returns a pandas DataFrame and never raises: a missing,
locked or half-migrated registry yields an empty frame with the expected columns, so the
caller simply skips that tick. Timestamps in the ledger are ISO-8601 UTC strings
(``YYYY-MM-DDTHH:MM:SSZ``), so window filters are plain string comparisons.
"""
from __future__ import annotations

import json
import re
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from common import paths
from common.hashing import sha256_file
from registry.db import connect_readonly

POLL_SECONDS = 5                       # OPS.md D.1: 5 s polling
BURN_WINDOW_HOURS = 6.0                # trailing window for burn-rate estimates
MAX_READ_BYTES = 16 << 20              # per-tick read cap when tailing events.jsonl
NEGATIVE_CONTROL_LIKE = "negative_control%"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
_HEX = re.compile(r"^[0-9a-fA-F]{8,128}$")


# --------------------------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO timestamp (``Z`` or offset, naive = UTC); ``None`` when unparsable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value or not isinstance(value, str):
        return None
    s = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def as_utc(value: Any = None) -> datetime:
    """``None`` -> now; datetime/ISO string -> aware UTC datetime."""
    if value is None:
        return utcnow()
    dt = parse_ts(value)
    if dt is None:
        raise ValueError(f"not a timestamp: {value!r}")
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    """Same format the registry writes (common.timeutil.utcnow_iso)."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def start_of_day(dt: datetime) -> datetime:
    d = dt.astimezone(timezone.utc)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


# --------------------------------------------------------------------------------------------
# events.jsonl
# --------------------------------------------------------------------------------------------
def _parse_line(raw: bytes | str) -> dict | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def tail_events(path: Path | str | None = None, since_offset: int = 0,
                max_bytes: int = MAX_READ_BYTES) -> tuple[list[dict], int]:
    """Read complete JSONL lines appended after byte ``since_offset``.

    Returns ``(events, new_offset)``. A trailing partial line (the writer is mid-append) is
    not consumed: ``new_offset`` stops after the last newline, so the next call re-reads it.
    Malformed complete lines are skipped. If the file shrank (truncated/rotated) reading
    restarts at 0; if it is missing, ``([], 0)``.
    """
    p = Path(path) if path is not None else paths.events_file()
    try:
        size = p.stat().st_size
    except OSError:
        return [], 0
    offset = int(since_offset or 0)
    if offset < 0 or offset > size:
        offset = 0
    if offset == size:
        return [], offset
    try:
        with open(p, "rb") as f:
            f.seek(offset)
            chunk = f.read(max_bytes)
            if b"\n" not in chunk and len(chunk) >= max_bytes:
                chunk += f.readline()          # a single line longer than the cap
    except OSError:
        return [], offset
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset                      # only a partial line so far
    complete = chunk[: end + 1]
    events = [e for e in (_parse_line(line) for line in complete.split(b"\n")) if e is not None]
    return events, offset + len(complete)


def load_events(path: Path | str | None = None, limit: int | None = None) -> list[dict]:
    """All parsable events (or the last ``limit``), oldest first. Missing file -> []."""
    p = Path(path) if path is not None else paths.events_file()
    out: deque[dict] = deque(maxlen=limit if limit and limit > 0 else None)
    try:
        with open(p, "rb") as f:
            for line in f:
                ev = _parse_line(line)
                if ev is not None:
                    out.append(ev)
    except OSError:
        return []
    return list(out)


def event_flags(event: dict) -> list[str]:
    """policy_flags as a list, tolerating a JSON-encoded string or a bare string."""
    flags = event.get("policy_flags") if isinstance(event, dict) else None
    if not flags:
        return []
    if isinstance(flags, str):
        try:
            parsed = json.loads(flags)
        except ValueError:
            parsed = [flags]
        flags = parsed if isinstance(parsed, list) else [parsed]
    if not isinstance(flags, (list, tuple, set)):
        return []
    return [str(f) for f in flags]


def events_since(events: Iterable[dict], since: datetime) -> list[dict]:
    out = []
    for ev in events:
        t = parse_ts(ev.get("ts")) if isinstance(ev, dict) else None
        if t is not None and t >= since:
            out.append(ev)
    return out


class EventFeed:
    """Shared incremental tail of events.jsonl (one per dashboard process).

    Keeps the most recent ``maxlen`` events for the narrative feed and, separately, every
    event that carried a policy flag (up to ``max_flagged``) so alarms never scroll away.
    """

    def __init__(self, path: Path | str | None = None, maxlen: int = 5000, max_flagged: int = 2000):
        self._path = Path(path) if path is not None else None
        self.offset = 0
        self.total = 0
        self.events: deque[dict] = deque(maxlen=maxlen)
        self.flagged: deque[dict] = deque(maxlen=max_flagged)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else paths.events_file()

    def poll(self) -> list[dict]:
        with self._lock:
            new, off = tail_events(self.path, self.offset)
            if off < self.offset:                      # file truncated / replaced
                self.events.clear()
                self.flagged.clear()
                self.total = 0
            self.offset = off
            self.events.extend(new)
            self.flagged.extend(e for e in new if event_flags(e))
            self.total += len(new)
            return new

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    def alarm_events(self) -> list[dict]:
        """Every flagged event still held plus the latest event (for the stall check)."""
        with self._lock:
            out = list(self.flagged)
            if self.events and not event_flags(self.events[-1]):
                out.append(self.events[-1])
            return out


# --------------------------------------------------------------------------------------------
# files next to the registry (data, not code)
# --------------------------------------------------------------------------------------------
def current_thresholds_hash() -> str:
    f = paths.gates_thresholds_file()
    try:
        return sha256_file(f) if f.exists() else "missing"
    except OSError:
        return "unreadable"


def load_package(candidate_id: str) -> dict | None:
    """registry/packages/<candidate_id>.json, or None (bad id, missing or unparsable file)."""
    if not isinstance(candidate_id, str) or not _SAFE_ID.match(candidate_id) or ".." in candidate_id:
        return None
    p = paths.registry_dir() / "packages" / f"{candidate_id}.json"
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def read_prompt_output(output_hash: str) -> Any:
    """registry/prompts/<output_hash>.out.txt parsed as JSON (raw text if not JSON; None if absent)."""
    if not isinstance(output_hash, str) or not _HEX.match(output_hash):
        return None
    p = paths.prompts_dir() / f"{output_hash}.out.txt"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


# --------------------------------------------------------------------------------------------
# SQLite registry (read-only)
# --------------------------------------------------------------------------------------------
FUNNEL_COLS = ["campaign_id", "proposals", "passed_critic", "implemented", "validated",
               "full_evaluated", "promoted", "rejected"]
FUNNEL_STAGES = ["proposals", "reviewed", "implemented", "validated", "evaluated", "promoted"]
DIVERSITY_COLS = ["campaign_id", "mechanism_cluster", "n", "share"]
MECH_COLS = ["mechanism_cluster", "proposals", "promoted", "rejected", "in_progress", "share"]
CRITIC_Q_COLS = ["campaign_id", "arm", "rejected", "returned", "passed", "reviews"]
BUDGET_COLS = ["campaign_id", "started_at", "ended_at", "active", "budget_tokens", "tokens_used",
               "tokens_pct", "budget_full_evals", "evals_used", "evals_pct", "evaluation_rows",
               "cost_usd", "tokens_window", "evals_window", "window_hours", "tokens_per_hour",
               "evals_per_hour", "tokens_exhaust_at", "evals_exhaust_at"]
GATE_COLS = ["gate", "metric", "value", "ci_low", "ci_high", "threshold", "passed", "cutoff_date",
             "seed", "data_snapshot_id", "evaluated_at"]
CAND_COLS = ["candidate_id", "proposal_id", "campaign_id", "mechanism_cluster", "state", "retry_count",
             "supersedes", "dsl_hash", "created_at", "updated_at", "mechanism_text"]
TRANS_COLS = ["transition_id", "candidate_id", "from_state", "to_state", "gate", "reason", "at"]
CAMPAIGN_COLS = ["campaign_id", "customer_id", "species", "trait_set", "horizon", "champion_id",
                 "budget_full_evals", "budget_tokens", "started_at", "ended_at", "active"]
THRESH_COLS = ["campaign_id", "start_hash", "recorded_at", "started_at", "ended_at", "active",
               "current_hash", "changed"]
NC_COLS = ["campaign_id", "candidate_id", "mechanism_cluster", "review_id", "verdict", "expected",
           "correct", "leak_type", "created_at"]
FP_COLS = ["campaign_id", "candidate_id", "mechanism_cluster", "state", "updated_at"]
REVIEW_COLS = ["review_id", "candidate_id", "campaign_id", "mechanism_cluster", "verdict", "leak_type",
               "evidence", "tokens", "created_at"]
GATE_SUM_COLS = ["gate", "n", "passed", "failed"]
GATE_FAIL_COLS = ["candidate_id", "mechanism_cluster", "gate", "metric", "value", "ci_low", "ci_high",
                  "threshold", "evaluated_at"]
PASS_RATE_COLS = ["campaign_id", "recent_n", "recent_pass", "base_n", "base_pass"]
WINDOW_COLS = ["proposals", "critic_pass", "critic_return", "critic_reject", "gate_pass", "gate_fail",
               "promotions", "rejections", "evaluations", "agent_calls", "tokens", "cost_usd",
               "compute_seconds"]
AGENT_COST_COLS = ["agent", "calls", "tokens", "cost_usd", "latency_ms"]
ANALYST_COLS = ["ts", "campaign_id", "candidate_id", "output_hash", "summary"]
EVAL_COLS = ["candidate_id", "mechanism_cluster", "split_id", "rho", "bias", "dispersion", "delta_oos",
             "delta_oos_ci_low", "compute_seconds", "evaluated_at"]
REJECT_REASON_COLS = ["gate", "reason", "n"]
GATE_EVENT_COLS = ["ts", "candidate_id", "gate", "passed", "to_state", "summary", "source"]
GATE_NAMES = ("validity", "accuracy", "incremental", "plan", "robustness", "research", "promotion", "evaluation")


def _empty(cols: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})


def _is_active(ended_at: Any) -> bool:
    return ended_at is None or (isinstance(ended_at, float) and ended_at != ended_at) or str(ended_at).strip() == ""


class RegistryReader:
    """Read-only view of the registry. Each query opens a ``mode=ro`` connection, runs, closes.

    ``keep_last=True`` (used by the live app) returns the last good frame for a query when the
    registry is momentarily locked, so a busy tick shows the previous snapshot instead of zeros.
    """

    def __init__(self, db_path: Path | str | None = None, *, keep_last: bool = False,
                 busy_timeout_ms: int = 200):
        self._db_path = Path(db_path) if db_path is not None else None
        self.keep_last = keep_last
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.last_error: str | None = None
        self._last: dict[Any, pd.DataFrame] = {}

    @property
    def db_path(self) -> Path:
        return self._db_path if self._db_path is not None else paths.registry_db()

    def available(self) -> bool:
        return self.db_path.exists()

    def query(self, sql: str, params: Any = (), columns: Iterable[str] = ()) -> pd.DataFrame:
        cols = list(columns)
        p = self.db_path
        if not p.exists():
            self.last_error = f"registry missing: {p}"
            return _empty(cols)
        key = (sql, json.dumps(params, default=str, sort_keys=True))
        con = None
        try:
            con = connect_readonly(p)
            con.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            df = pd.read_sql_query(sql, con, params=params)
        except Exception as exc:  # locked, malformed, schema not created yet ... skip the tick
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.keep_last and key in self._last:
                return self._last[key].copy()
            return _empty(cols)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
        self.last_error = None
        if self.keep_last:
            self._last[key] = df
        return df

    # -- campaign-level ---------------------------------------------------------------------
    def campaigns(self) -> pd.DataFrame:
        df = self.query(
            "SELECT campaign_id, customer_id, species, trait_set, horizon, champion_id, budget_full_evals, "
            "budget_tokens, started_at, ended_at FROM campaigns ORDER BY started_at DESC, campaign_id",
            columns=CAMPAIGN_COLS)
        df["active"] = [_is_active(v) for v in df["ended_at"]] if len(df) else pd.Series(dtype="bool")
        return df

    def funnel(self, campaign_id: str | None = None) -> pd.DataFrame:
        """Rows of view v_funnel (campaign-to-date)."""
        return self.query("SELECT * FROM v_funnel WHERE (:cid IS NULL OR campaign_id = :cid) ORDER BY campaign_id",
                          {"cid": campaign_id}, FUNNEL_COLS)

    def funnel_stages(self, campaign_id: str | None = None, since: str | None = None) -> pd.DataFrame:
        """proposals -> reviewed -> implemented -> validated -> evaluated -> promoted, counted from
        ``since`` (ISO) or over the whole ledger. "reviewed" = candidates with a Critic review or a
        transition into reviewed-or-later; later stages come from candidate_transitions."""
        sql = """
        WITH c AS (SELECT k.candidate_id FROM candidates k JOIN proposals p ON p.proposal_id = k.proposal_id
                   WHERE (:cid IS NULL OR p.campaign_id = :cid)),
             t AS (SELECT candidate_id, to_state FROM candidate_transitions
                   WHERE at >= :since AND candidate_id IN (SELECT candidate_id FROM c))
        SELECT
          (SELECT COUNT(*) FROM proposals WHERE (:cid IS NULL OR campaign_id = :cid) AND created_at >= :since) AS proposals,
          (SELECT COUNT(*) FROM (
              SELECT candidate_id FROM critic_reviews WHERE created_at >= :since AND candidate_id IN (SELECT candidate_id FROM c)
              UNION SELECT candidate_id FROM t WHERE to_state IN ('reviewed','implemented','validated','evaluated','promoted'))) AS reviewed,
          (SELECT COUNT(DISTINCT candidate_id) FROM t WHERE to_state IN ('implemented','validated','evaluated','promoted')) AS implemented,
          (SELECT COUNT(DISTINCT candidate_id) FROM t WHERE to_state IN ('validated','evaluated','promoted')) AS validated,
          (SELECT COUNT(DISTINCT candidate_id) FROM t WHERE to_state IN ('evaluated','promoted')) AS evaluated,
          (SELECT COUNT(DISTINCT candidate_id) FROM t WHERE to_state = 'promoted') AS promoted
        """
        df = self.query(sql, {"cid": campaign_id, "since": since or ""}, FUNNEL_STAGES)
        if df.empty:
            return pd.DataFrame({"stage": FUNNEL_STAGES, "count": [0] * len(FUNNEL_STAGES)})
        row = df.iloc[0]
        return pd.DataFrame({"stage": FUNNEL_STAGES, "count": [int(row[s] or 0) for s in FUNNEL_STAGES]})

    def funnel_compare(self, campaign_id: str | None = None, now: Any = None) -> pd.DataFrame:
        """Funnel for today (UTC day) next to campaign-to-date, plus conversion vs proposals."""
        n = as_utc(now)
        today = self.funnel_stages(campaign_id, iso(start_of_day(n)))
        ctd = self.funnel_stages(campaign_id, None)
        out = pd.DataFrame({"stage": FUNNEL_STAGES, "today": today["count"].astype(int).tolist(),
                            "campaign_to_date": ctd["count"].astype(int).tolist()})
        base = max(int(out["campaign_to_date"].iloc[0]), 0)
        out["pct_of_proposals"] = [round(100.0 * v / base, 1) if base else 0.0 for v in out["campaign_to_date"]]
        return out

    def diversity(self, campaign_id: str | None = None) -> pd.DataFrame:
        """Rows of view v_diversity."""
        return self.query("SELECT * FROM v_diversity WHERE (:cid IS NULL OR campaign_id = :cid) "
                          "ORDER BY campaign_id, n DESC", {"cid": campaign_id}, DIVERSITY_COLS)

    def mechanism_map(self, campaign_id: str | None = None) -> pd.DataFrame:
        """Per mechanism cluster: proposals and their disposition. A proposal counts as promoted if
        any of its candidates was promoted, rejected if none promoted, none open and one rejected."""
        sql = """
        WITH d AS (
          SELECT p.proposal_id, p.mechanism_cluster,
                 MAX(CASE WHEN c.state = 'promoted' THEN 1 ELSE 0 END) AS any_promoted,
                 MAX(CASE WHEN c.state = 'rejected' THEN 1 ELSE 0 END) AS any_rejected,
                 SUM(CASE WHEN c.candidate_id IS NOT NULL AND c.state NOT IN ('promoted','rejected') THEN 1 ELSE 0 END) AS open_cands
          FROM proposals p LEFT JOIN candidates c ON c.proposal_id = p.proposal_id
          WHERE (:cid IS NULL OR p.campaign_id = :cid)
          GROUP BY p.proposal_id, p.mechanism_cluster)
        SELECT mechanism_cluster, COUNT(*) AS proposals,
               SUM(any_promoted) AS promoted,
               SUM(CASE WHEN any_promoted = 0 AND open_cands = 0 AND any_rejected = 1 THEN 1 ELSE 0 END) AS rejected
        FROM d GROUP BY mechanism_cluster ORDER BY proposals DESC, mechanism_cluster
        """
        df = self.query(sql, {"cid": campaign_id}, MECH_COLS)
        if df.empty:
            return _empty(MECH_COLS)
        for c in ("proposals", "promoted", "rejected"):
            df[c] = df[c].fillna(0).astype(int)
        df["in_progress"] = (df["proposals"] - df["promoted"] - df["rejected"]).clip(lower=0)
        total = int(df["proposals"].sum())
        df["share"] = (df["proposals"] / total).round(3) if total else 0.0
        return df[MECH_COLS]

    def critic_quality(self) -> pd.DataFrame:
        """Rows of view v_critic_quality."""
        return self.query("SELECT * FROM v_critic_quality ORDER BY campaign_id, arm", columns=CRITIC_Q_COLS)

    def budget(self, campaign_id: str | None = None, now: Any = None) -> pd.DataFrame:
        """Per campaign: tokens (sum agent_events.tokens) and full evaluations (distinct evaluated
        candidates) used vs the caps in ``campaigns``, burn rate per hour over the trailing
        BURN_WINDOW_HOURS (or since start, if younger) and projected exhaustion time."""
        n = as_utc(now)
        win = iso(n - timedelta(hours=BURN_WINDOW_HOURS))
        sql = """
        WITH ev AS (
          SELECT p.campaign_id, e.candidate_id, MIN(e.evaluated_at) AS first_at, COUNT(*) AS rows_n
          FROM evaluations e JOIN candidates k ON k.candidate_id = e.candidate_id
          JOIN proposals p ON p.proposal_id = k.proposal_id
          GROUP BY p.campaign_id, e.candidate_id)
        SELECT c.campaign_id, c.started_at, c.ended_at, c.budget_tokens, c.budget_full_evals,
          (SELECT COALESCE(SUM(a.tokens), 0) FROM agent_events a WHERE a.campaign_id = c.campaign_id) AS tokens_used,
          (SELECT COALESCE(SUM(a.cost_usd), 0) FROM agent_events a WHERE a.campaign_id = c.campaign_id) AS cost_usd,
          (SELECT COALESCE(SUM(a.tokens), 0) FROM agent_events a WHERE a.campaign_id = c.campaign_id AND a.ts >= :win) AS tokens_window,
          (SELECT COUNT(*) FROM ev WHERE ev.campaign_id = c.campaign_id) AS evals_used,
          (SELECT COALESCE(SUM(rows_n), 0) FROM ev WHERE ev.campaign_id = c.campaign_id) AS evaluation_rows,
          (SELECT COUNT(*) FROM ev WHERE ev.campaign_id = c.campaign_id AND ev.first_at >= :win) AS evals_window
        FROM campaigns c WHERE (:cid IS NULL OR c.campaign_id = :cid)
        ORDER BY (c.ended_at IS NULL OR c.ended_at = '') DESC, c.started_at DESC
        """
        df = self.query(sql, {"cid": campaign_id, "win": win}, BUDGET_COLS)
        if df.empty:
            return _empty(BUDGET_COLS)
        rows = []
        for r in df.to_dict("records"):
            active = _is_active(r.get("ended_at"))
            started = parse_ts(r.get("started_at")) or n
            elapsed_h = max((n - started).total_seconds() / 3600.0, 0.0)
            hours = max(min(BURN_WINDOW_HOURS, elapsed_h), 0.1)
            tok_used, tok_cap = int(r["tokens_used"] or 0), int(r["budget_tokens"] or 0)
            ev_used, ev_cap = int(r["evals_used"] or 0), int(r["budget_full_evals"] or 0)
            # current burn: an ended campaign burns nothing, whatever it spent in its last hours
            tph = float(r["tokens_window"] or 0) / hours if active else 0.0
            eph = float(r["evals_window"] or 0) / hours if active else 0.0
            r.update(
                active=active, tokens_used=tok_used, evals_used=ev_used, window_hours=round(hours, 2),
                tokens_pct=round(tok_used / tok_cap, 4) if tok_cap else 0.0,
                evals_pct=round(ev_used / ev_cap, 4) if ev_cap else 0.0,
                tokens_per_hour=round(tph, 1), evals_per_hour=round(eph, 3),
                tokens_exhaust_at=_projection(tok_used, tok_cap, tph, n, active),
                evals_exhaust_at=_projection(ev_used, ev_cap, eph, n, active),
                cost_usd=round(float(r["cost_usd"] or 0.0), 6),
            )
            rows.append(r)
        return pd.DataFrame(rows, columns=BUDGET_COLS)

    # -- candidates -------------------------------------------------------------------------
    def candidates(self, campaign_id: str | None = None) -> pd.DataFrame:
        return self.query(
            "SELECT c.candidate_id, c.proposal_id, p.campaign_id, p.mechanism_cluster, c.state, c.retry_count, "
            "c.supersedes, c.dsl_hash, c.created_at, c.updated_at, p.mechanism_text "
            "FROM candidates c LEFT JOIN proposals p ON p.proposal_id = c.proposal_id "
            "WHERE (:cid IS NULL OR p.campaign_id = :cid) ORDER BY c.created_at DESC, c.candidate_id DESC",
            {"cid": campaign_id}, CAND_COLS)

    def gate_results_for(self, candidate_id: str) -> pd.DataFrame:
        return self.query(
            "SELECT gate, metric, value, ci_low, ci_high, threshold, passed, cutoff_date, seed, data_snapshot_id, "
            "evaluated_at FROM gate_results WHERE candidate_id = :cid ORDER BY gate_result_id",
            {"cid": candidate_id}, GATE_COLS)

    def transitions(self, candidate_id: str | None = None, since: str | None = None) -> pd.DataFrame:
        return self.query(
            "SELECT transition_id, candidate_id, from_state, to_state, gate, reason, at FROM candidate_transitions "
            "WHERE (:cid IS NULL OR candidate_id = :cid) AND at >= :since ORDER BY transition_id",
            {"cid": candidate_id, "since": since or ""}, TRANS_COLS)

    def critic_reviews(self, since: str | None = None, candidate_id: str | None = None) -> pd.DataFrame:
        return self.query(
            "SELECT r.review_id, r.candidate_id, p.campaign_id, p.mechanism_cluster, r.verdict, r.leak_type, "
            "r.evidence, r.tokens, r.created_at FROM critic_reviews r "
            "LEFT JOIN candidates c ON c.candidate_id = r.candidate_id "
            "LEFT JOIN proposals p ON p.proposal_id = c.proposal_id "
            "WHERE r.created_at >= :since AND (:cid IS NULL OR r.candidate_id = :cid) ORDER BY r.created_at DESC",
            {"since": since or "", "cid": candidate_id}, REVIEW_COLS)

    def evaluations(self, since: str | None = None) -> pd.DataFrame:
        return self.query(
            "SELECT e.candidate_id, p.mechanism_cluster, e.split_id, e.rho, e.bias, e.dispersion, e.delta_oos, "
            "e.delta_oos_ci_low, e.compute_seconds, e.evaluated_at FROM evaluations e "
            "LEFT JOIN candidates c ON c.candidate_id = e.candidate_id "
            "LEFT JOIN proposals p ON p.proposal_id = c.proposal_id "
            "WHERE e.evaluated_at >= :since ORDER BY e.evaluated_at DESC",
            {"since": since or ""}, EVAL_COLS)

    # -- gates ------------------------------------------------------------------------------
    def gate_summary(self, since: str | None = None) -> pd.DataFrame:
        return self.query(
            "SELECT gate, COUNT(*) AS n, SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS passed, "
            "SUM(CASE WHEN passed THEN 0 ELSE 1 END) AS failed FROM gate_results "
            "WHERE evaluated_at >= :since GROUP BY gate ORDER BY failed DESC, gate",
            {"since": since or ""}, GATE_SUM_COLS)

    def gate_failures(self, since: str | None = None, limit: int = 50) -> pd.DataFrame:
        return self.query(
            "SELECT g.candidate_id, p.mechanism_cluster, g.gate, g.metric, g.value, g.ci_low, g.ci_high, "
            "g.threshold, g.evaluated_at FROM gate_results g "
            "LEFT JOIN candidates c ON c.candidate_id = g.candidate_id "
            "LEFT JOIN proposals p ON p.proposal_id = c.proposal_id "
            "WHERE NOT g.passed AND g.evaluated_at >= :since ORDER BY g.evaluated_at DESC LIMIT :lim",
            {"since": since or "", "lim": int(limit)}, GATE_FAIL_COLS)

    def gate_pass_rates(self, since: str) -> pd.DataFrame:
        """Per campaign: gate rows (and passes) at/after ``since`` vs before it (the baseline)."""
        return self.query(
            "SELECT p.campaign_id, "
            "SUM(CASE WHEN g.evaluated_at >= :since THEN 1 ELSE 0 END) AS recent_n, "
            "SUM(CASE WHEN g.evaluated_at >= :since AND g.passed THEN 1 ELSE 0 END) AS recent_pass, "
            "SUM(CASE WHEN g.evaluated_at < :since THEN 1 ELSE 0 END) AS base_n, "
            "SUM(CASE WHEN g.evaluated_at < :since AND g.passed THEN 1 ELSE 0 END) AS base_pass "
            "FROM gate_results g JOIN candidates c ON c.candidate_id = g.candidate_id "
            "JOIN proposals p ON p.proposal_id = c.proposal_id GROUP BY p.campaign_id ORDER BY p.campaign_id",
            {"since": since or ""}, PASS_RATE_COLS)

    def rejection_reasons(self, since: str | None = None) -> pd.DataFrame:
        return self.query(
            "SELECT gate, reason, COUNT(DISTINCT candidate_id) AS n FROM candidate_transitions "
            "WHERE to_state = 'rejected' AND at >= :since GROUP BY gate, reason ORDER BY n DESC, gate",
            {"since": since or ""}, REJECT_REASON_COLS)

    def gate_events(self, since: str | None = None, limit: int = 200) -> pd.DataFrame:
        """Gate outcomes as feed items. Gates write to SQL, not events.jsonl, so the narrative feed
        merges these: one row per failed (candidate, gate, evaluation) and one per promotion or
        gate rejection transition. Newest first."""
        sql = """
        SELECT * FROM (
          SELECT g.evaluated_at AS ts, g.candidate_id, g.gate, 0 AS passed, NULL AS to_state,
                 group_concat(g.metric || ' ' ||
                     CASE WHEN g.value IS NULL THEN 'n/a' ELSE printf('%.4g', g.value) END || ' vs threshold ' ||
                     CASE WHEN g.threshold IS NULL THEN 'n/a' ELSE printf('%.4g', g.threshold) END, '; ') AS summary,
                 'registry:gate_results' AS source
          FROM gate_results g WHERE NOT g.passed AND g.evaluated_at >= :since
          GROUP BY g.candidate_id, g.gate, g.evaluated_at
          UNION ALL
          SELECT t.at, t.candidate_id, t.gate, CASE WHEN t.to_state = 'promoted' THEN 1 ELSE 0 END, t.to_state,
                 t.reason, 'registry:candidate_transitions'
          FROM candidate_transitions t
          WHERE t.to_state IN ('promoted', 'rejected') AND t.at >= :since
            AND t.gate IN ('validity','accuracy','incremental','plan','robustness','research','promotion','evaluation')
        ) ORDER BY ts DESC LIMIT :lim
        """
        return self.query(sql, {"since": since or "", "lim": int(limit)}, GATE_EVENT_COLS)

    # -- thresholds & reliability -----------------------------------------------------------
    def threshold_status(self) -> pd.DataFrame:
        """sha256 of gates/thresholds.yaml recorded at each campaign's start vs the file now."""
        df = self.query(
            "SELECT t.campaign_id, t.thresholds_hash AS start_hash, t.recorded_at, c.started_at, c.ended_at "
            "FROM threshold_versions t LEFT JOIN campaigns c ON c.campaign_id = t.campaign_id "
            "WHERE t.rowid = (SELECT t2.rowid FROM threshold_versions t2 WHERE t2.campaign_id = t.campaign_id "
            "                 ORDER BY t2.recorded_at, t2.rowid LIMIT 1) ORDER BY t.recorded_at",
            columns=THRESH_COLS)
        if df.empty:
            return _empty(THRESH_COLS)
        cur = current_thresholds_hash()
        df["active"] = [_is_active(v) for v in df["ended_at"]]
        df["current_hash"] = cur
        df["changed"] = [str(h) != cur for h in df["start_hash"]]
        return df[THRESH_COLS]

    def negative_control_reviews(self, campaign_id: str | None = None) -> pd.DataFrame:
        """Critic verdicts on negative-control candidates (expected: REJECT)."""
        return self.query(
            "SELECT p.campaign_id, c.candidate_id, p.mechanism_cluster, r.review_id, r.verdict, "
            "'REJECT' AS expected, CASE WHEN r.verdict = 'REJECT' THEN 1 ELSE 0 END AS correct, "
            "r.leak_type, r.created_at FROM critic_reviews r "
            "JOIN candidates c ON c.candidate_id = r.candidate_id JOIN proposals p ON p.proposal_id = c.proposal_id "
            "WHERE p.mechanism_cluster LIKE :nc AND (:cid IS NULL OR p.campaign_id = :cid) "
            "ORDER BY r.created_at DESC",
            {"nc": NEGATIVE_CONTROL_LIKE, "cid": campaign_id}, NC_COLS)

    def false_promotions(self, campaign_id: str | None = None) -> pd.DataFrame:
        """Negative-control candidates currently in state 'promoted' (should always be empty)."""
        return self.query(
            "SELECT p.campaign_id, c.candidate_id, p.mechanism_cluster, c.state, c.updated_at FROM candidates c "
            "JOIN proposals p ON p.proposal_id = c.proposal_id "
            "WHERE c.state = 'promoted' AND p.mechanism_cluster LIKE :nc AND (:cid IS NULL OR p.campaign_id = :cid) "
            "ORDER BY c.updated_at DESC",
            {"nc": NEGATIVE_CONTROL_LIKE, "cid": campaign_id}, FP_COLS)

    # -- windows & cost ---------------------------------------------------------------------
    def window_counts(self, since: str | None = None) -> pd.DataFrame:
        """One row of ledger counts at/after ``since`` (all campaigns)."""
        sql = """
        SELECT
          (SELECT COUNT(*) FROM proposals WHERE created_at >= :since) AS proposals,
          (SELECT COUNT(*) FROM critic_reviews WHERE created_at >= :since AND verdict = 'PASS') AS critic_pass,
          (SELECT COUNT(*) FROM critic_reviews WHERE created_at >= :since AND verdict = 'RETURN') AS critic_return,
          (SELECT COUNT(*) FROM critic_reviews WHERE created_at >= :since AND verdict = 'REJECT') AS critic_reject,
          (SELECT COUNT(*) FROM gate_results WHERE evaluated_at >= :since AND passed) AS gate_pass,
          (SELECT COUNT(*) FROM gate_results WHERE evaluated_at >= :since AND NOT passed) AS gate_fail,
          (SELECT COUNT(DISTINCT candidate_id) FROM candidate_transitions WHERE to_state = 'promoted' AND at >= :since) AS promotions,
          (SELECT COUNT(DISTINCT candidate_id) FROM candidate_transitions WHERE to_state = 'rejected' AND at >= :since) AS rejections,
          (SELECT COUNT(DISTINCT candidate_id) FROM evaluations WHERE evaluated_at >= :since) AS evaluations,
          (SELECT COUNT(*) FROM agent_events WHERE ts >= :since) AS agent_calls,
          (SELECT COALESCE(SUM(tokens), 0) FROM agent_events WHERE ts >= :since) AS tokens,
          (SELECT COALESCE(SUM(cost_usd), 0) FROM agent_events WHERE ts >= :since) AS cost_usd,
          (SELECT COALESCE(SUM(compute_seconds), 0) FROM evaluations WHERE evaluated_at >= :since) AS compute_seconds
        """
        return self.query(sql, {"since": since or ""}, WINDOW_COLS)

    def cost_by_agent(self, since: str | None = None) -> pd.DataFrame:
        return self.query(
            "SELECT agent, COUNT(*) AS calls, COALESCE(SUM(tokens), 0) AS tokens, "
            "COALESCE(SUM(cost_usd), 0) AS cost_usd, COALESCE(SUM(latency_ms), 0) AS latency_ms "
            "FROM agent_events WHERE ts >= :since GROUP BY agent ORDER BY tokens DESC, agent",
            {"since": since or ""}, AGENT_COST_COLS)

    def latest_analyst_event(self) -> pd.DataFrame:
        return self.query(
            "SELECT ts, campaign_id, candidate_id, output_hash, summary FROM agent_events "
            "WHERE agent = 'analyst' ORDER BY ts DESC, event_id DESC LIMIT 1", columns=ANALYST_COLS)


def registry_gate_events(reader: RegistryReader, since: str | None = None, limit: int = 200) -> list[dict]:
    """``RegistryReader.gate_events`` as event dicts that :func:`dashboard.narrative.narrate` understands."""
    out = []
    for r in reader.gate_events(since, limit).to_dict("records"):
        to_state = r.get("to_state") if isinstance(r.get("to_state"), str) else None
        out.append({"ts": r.get("ts"), "agent": "gate", "action": str(r.get("gate")), "gate": str(r.get("gate")),
                    "candidate_id": r.get("candidate_id"), "passed": bool(int(r.get("passed") or 0)),
                    "to_state": to_state, "summary": str(r.get("summary") or ""), "policy_flags": [],
                    "source": r.get("source")})
    return out


def _projection(used: float, cap: float, per_hour: float, now: datetime, active: bool) -> str:
    """ISO time the cap is reached at the current burn rate; '' when not projectable."""
    if not cap:
        return ""
    if used >= cap:
        return "exhausted"
    if not active or per_hour <= 0:
        return ""
    hours_left = (cap - used) / per_hour
    if hours_left > 24 * 365:
        return ""
    return iso(now + timedelta(hours=hours_left))


def window_row(df: pd.DataFrame, columns: Iterable[str] = WINDOW_COLS) -> dict[str, float]:
    """First row of a counts frame as a dict of numbers; zeros for an empty frame."""
    cols = list(columns)
    if df is None or df.empty:
        return {c: 0 for c in cols}
    row = df.iloc[0]
    out: dict[str, float] = {}
    for c in cols:
        v = row.get(c, 0)
        try:
            v = float(v) if v is not None and v == v else 0.0
        except (TypeError, ValueError):
            v = 0.0
        out[c] = int(v) if float(v).is_integer() and c != "cost_usd" else round(v, 6)
    return out
