"""SQLite registry — append-only trial ledger.

Design rules (OPS.md A.1):
* every row carries ``owner`` / ``sharing_tier`` where the schema defines them;
* nothing is ever UPDATEd or DELETEd except the ``candidates.state`` projection, which is
  rewritten only by :meth:`Registry.transition` and only when the caller lives in ``gates/``;
* corrections are new rows with a ``supersedes`` pointer.
"""
from __future__ import annotations

import inspect
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from common import paths
from common.hashing import sha256_file
from common.timeutil import utcnow_iso

_HERE = Path(__file__).resolve().parent
_SCHEMA = _HERE / "schema.sql"
_VIEWS = _HERE / "views.sql"

TABLES = {
    "campaigns", "proposals", "candidates", "candidate_transitions", "critic_reviews",
    "gate_results", "evaluations", "data_snapshots", "recommendations", "decisions",
    "outcomes", "agent_events", "costs", "controls", "threshold_versions",
}
STATES = ("registered", "reviewed", "implemented", "validated", "evaluated", "promoted", "rejected")
# legal forward moves; `rejected` is reachable from any non-terminal state
_ALLOWED = {
    None: {"registered"},
    "registered": {"reviewed", "rejected"},
    "reviewed": {"implemented", "rejected", "reviewed"},   # RETURN_TO_BUILDER re-reviews
    "implemented": {"validated", "rejected", "reviewed"},
    "validated": {"evaluated", "rejected"},
    "evaluated": {"promoted", "rejected"},
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _j(v: Any) -> Any:
    """JSON-encode lists/dicts for TEXT columns; pass scalars through."""
    if isinstance(v, (list, dict, tuple)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return v


def connect_readonly(path: Path | None = None) -> sqlite3.Connection:
    """Read-only connection for the dashboard (OPS.md D.3)."""
    p = Path(path or paths.registry_db())
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=0.5)
    con.row_factory = sqlite3.Row
    return con


class Registry:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or paths.registry_db())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_SCHEMA.read_text())
        self.create_views()

    # -- infrastructure ---------------------------------------------------------------
    def create_views(self) -> None:
        self.con.executescript(_VIEWS.read_text())
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def insert(self, table: str, row: dict[str, Any]) -> int:
        if table not in TABLES:
            raise ValueError(f"unknown table {table}")
        cols = list(row)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        cur = self.con.execute(sql, [_j(row[c]) for c in cols])
        self.con.commit()
        return int(cur.lastrowid)

    def df(self, sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, self.con, params=list(params))

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.con.execute(sql, list(params)).fetchone()

    # -- campaigns ----------------------------------------------------------------------
    def add_campaign(self, *, campaign_id: str, customer_id: str, species: str, trait_set: list[str],
                     horizon: str, champion_id: str, budget_full_evals: int, budget_tokens: int,
                     owner: str = "newco", sharing_tier: str = "private") -> str:
        self.insert("campaigns", dict(
            campaign_id=campaign_id, customer_id=customer_id, species=species, trait_set=trait_set,
            horizon=horizon, champion_id=champion_id, budget_full_evals=budget_full_evals,
            budget_tokens=budget_tokens, started_at=utcnow_iso(), ended_at=None, owner=owner,
            sharing_tier=sharing_tier))
        self.record_thresholds(campaign_id)
        return campaign_id

    def end_campaign(self, campaign_id: str) -> None:
        # the single sanctioned UPDATE besides the state projection: closing a campaign
        self.con.execute("UPDATE campaigns SET ended_at=? WHERE campaign_id=? AND ended_at IS NULL",
                         (utcnow_iso(), campaign_id))
        self.con.commit()

    def record_thresholds(self, campaign_id: str) -> str:
        f = paths.gates_thresholds_file()
        h = sha256_file(f) if f.exists() else "missing"
        self.insert("threshold_versions", dict(campaign_id=campaign_id, thresholds_hash=h, recorded_at=utcnow_iso()))
        return h

    def thresholds_hash_at_start(self, campaign_id: str) -> str | None:
        r = self.one("SELECT thresholds_hash FROM threshold_versions WHERE campaign_id=? ORDER BY recorded_at LIMIT 1", (campaign_id,))
        return r[0] if r else None

    # -- proposals / candidates ---------------------------------------------------------
    def add_proposal(self, *, campaign_id: str, agent_model: str, mechanism_text: str, mechanism_cluster: str,
                     direction: str, falsifiers: list[str], expected_gain: dict, novelty_hash: str,
                     source_refs: list[str], tokens: int = 0, owner: str = "newco",
                     sharing_tier: str = "private") -> str:
        pid = new_id("p")
        self.insert("proposals", dict(
            proposal_id=pid, campaign_id=campaign_id, agent_model=agent_model, mechanism_text=mechanism_text,
            mechanism_cluster=mechanism_cluster, direction=direction, falsifiers=falsifiers,
            expected_gain=expected_gain, novelty_hash=novelty_hash, source_refs=source_refs, tokens=tokens,
            created_at=utcnow_iso(), owner=owner, sharing_tier=sharing_tier))
        return pid

    def novelty_hash_exists(self, novelty_hash: str, campaign_id: str | None = None) -> bool:
        if campaign_id:
            r = self.one("SELECT 1 FROM proposals WHERE novelty_hash=? AND campaign_id=?", (novelty_hash, campaign_id))
        else:
            r = self.one("SELECT 1 FROM proposals WHERE novelty_hash=?", (novelty_hash,))
        return r is not None

    def dsl_hash_evaluated(self, dsl_hash: str, snapshot_id: str | None = None) -> bool:
        """Orchestrator rule: never run a full evaluation for a semantic hash already in the registry.
        A candidate is (DSL, data): the same expression on another data snapshot (another dataset, or
        the shuffled-label control) is a new trial, so the check is scoped to ``snapshot_id``."""
        if snapshot_id is None:
            r = self.one("SELECT 1 FROM candidates c JOIN evaluations e ON e.candidate_id=c.candidate_id WHERE c.dsl_hash=?",
                         (dsl_hash,))
        else:
            r = self.one("SELECT 1 FROM candidates c JOIN evaluations e ON e.candidate_id=c.candidate_id "
                         "JOIN gate_results g ON g.candidate_id=c.candidate_id AND g.gate='incremental' "
                         "WHERE c.dsl_hash=? AND g.data_snapshot_id=?", (dsl_hash, snapshot_id))
        return r is not None

    def add_candidate(self, *, proposal_id: str, dsl_text: str, dsl_hash: str, code_hash: str,
                      data_decl_hash: str, supersedes: str | None = None, retry_count: int = 0) -> str:
        cid = new_id("k")
        now = utcnow_iso()
        self.insert("candidates", dict(
            candidate_id=cid, proposal_id=proposal_id, dsl_text=dsl_text, dsl_hash=dsl_hash, code_hash=code_hash,
            data_decl_hash=data_decl_hash, state="registered", retry_count=retry_count, supersedes=supersedes,
            created_at=now, updated_at=now))
        self.insert("candidate_transitions", dict(candidate_id=cid, from_state=None, to_state="registered",
                                                  gate="registry", reason="candidate registered", at=now))
        return cid

    def candidate_state(self, candidate_id: str) -> str:
        r = self.one("SELECT state FROM candidates WHERE candidate_id=?", (candidate_id,))
        if r is None:
            raise KeyError(candidate_id)
        return r[0]

    def transition(self, candidate_id: str, to_state: str, *, gate: str, reason: str) -> None:
        """The ONLY way a candidate's state changes. Callers must live under gates/ (CLAUDE.md rule 2)."""
        caller = Path(inspect.stack()[1].filename).resolve()
        gates_dir = (_HERE.parent / "gates").resolve()   # the source tree, not ABL_ROOT
        if gates_dir not in caller.parents and _HERE not in caller.parents:
            raise PermissionError(f"state transitions are reserved for gates/; called from {caller}")
        if to_state not in STATES:
            raise ValueError(to_state)
        cur = self.candidate_state(candidate_id)
        if to_state not in _ALLOWED.get(cur, set()):
            raise ValueError(f"illegal transition {cur} -> {to_state} for {candidate_id}")
        now = utcnow_iso()
        self.insert("candidate_transitions", dict(candidate_id=candidate_id, from_state=cur, to_state=to_state,
                                                  gate=gate, reason=reason, at=now))
        self.con.execute("UPDATE candidates SET state=?, updated_at=? WHERE candidate_id=?", (to_state, now, candidate_id))
        self.con.commit()

    def bump_retry(self, candidate_id: str) -> int:
        self.con.execute("UPDATE candidates SET retry_count=retry_count+1, updated_at=? WHERE candidate_id=?",
                         (utcnow_iso(), candidate_id))
        self.con.commit()
        return int(self.one("SELECT retry_count FROM candidates WHERE candidate_id=?", (candidate_id,))[0])

    # -- reviews / gates / evaluations ---------------------------------------------------
    def add_review(self, *, candidate_id: str, verdict: str, leak_type: list[str], evidence: list[dict],
                   tokens: int = 0) -> str:
        rid = new_id("r")
        self.insert("critic_reviews", dict(review_id=rid, candidate_id=candidate_id, verdict=verdict,
                                           leak_type=leak_type, evidence=evidence, tokens=tokens,
                                           created_at=utcnow_iso()))
        return rid

    def add_gate_result(self, *, candidate_id: str, gate: str, metric: str, value: float | None,
                        passed: bool, threshold: float | None = None, ci_low: float | None = None,
                        ci_high: float | None = None, cutoff_date: str | None = None, seed: int | None = None,
                        data_snapshot_id: str | None = None) -> None:
        self.insert("gate_results", dict(candidate_id=candidate_id, gate=gate, metric=metric, value=value,
                                         ci_low=ci_low, ci_high=ci_high, threshold=threshold, passed=int(passed),
                                         cutoff_date=cutoff_date, seed=seed, data_snapshot_id=data_snapshot_id,
                                         evaluated_at=utcnow_iso()))

    def add_evaluation(self, *, candidate_id: str, split_id: str, rho: float, bias: float, dispersion: float,
                       delta_oos: float | None, delta_oos_ci_low: float | None, n_train: int, n_test: int,
                       compute_seconds: float, tokens: int = 0) -> str:
        eid = new_id("e")
        self.insert("evaluations", dict(evaluation_id=eid, candidate_id=candidate_id, split_id=split_id, rho=rho,
                                        bias=bias, dispersion=dispersion, delta_oos=delta_oos,
                                        delta_oos_ci_low=delta_oos_ci_low, n_train=n_train, n_test=n_test,
                                        compute_seconds=compute_seconds, tokens=tokens, evaluated_at=utcnow_iso()))
        return eid

    def add_snapshot(self, **row: Any) -> str:
        row.setdefault("snapshot_id", new_id("s"))
        self.insert("data_snapshots", row)
        return row["snapshot_id"]

    def add_control(self, *, campaign_id: str, arm: str, metric: str, value: float | None) -> None:
        self.insert("controls", dict(campaign_id=campaign_id, arm=arm, metric=metric, value=value,
                                     evaluated_at=utcnow_iso()))

    def add_cost(self, *, campaign_id: str, customer_id: str, period: str, tokens: int = 0,
                 compute_seconds: float = 0.0, human_review_minutes: float = 0.0, cash_cost: float = 0.0) -> None:
        self.insert("costs", dict(campaign_id=campaign_id, customer_id=customer_id, period=period, tokens=tokens,
                                  compute_seconds=compute_seconds, human_review_minutes=human_review_minutes,
                                  cash_cost=cash_cost))

    def add_agent_event(self, row: dict[str, Any]) -> None:
        keep = {"ts", "campaign_id", "agent", "action", "candidate_id", "input_hash", "output_hash", "tokens",
                "latency_ms", "summary", "policy_flags", "cost_usd"}
        self.insert("agent_events", {k: v for k, v in row.items() if k in keep})

    # -- summaries for the orchestrator (last N trials) ---------------------------------
    def summary(self, campaign_id: str, last_n: int = 200) -> dict[str, Any]:
        props = self.df(
            "SELECT proposal_id, mechanism_cluster, mechanism_text, novelty_hash, created_at FROM proposals "
            "WHERE campaign_id=? ORDER BY created_at DESC LIMIT ?", (campaign_id, last_n))
        cands = self.df(
            "SELECT c.candidate_id, c.proposal_id, c.dsl_text, c.dsl_hash, c.state, p.mechanism_cluster "
            "FROM candidates c JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=? "
            "ORDER BY c.created_at DESC LIMIT ?", (campaign_id, last_n))
        clusters = props["mechanism_cluster"].value_counts().to_dict() if len(props) else {}
        rejected = cands[cands.state == "rejected"][["mechanism_cluster", "dsl_text"]].to_dict("records")
        promoted = cands[cands.state == "promoted"][["mechanism_cluster", "dsl_text"]].to_dict("records")
        rejected = rejected[:60]
        evals = self.df(
            "SELECT e.candidate_id, e.delta_oos, e.delta_oos_ci_low, e.rho FROM evaluations e "
            "JOIN candidates c ON c.candidate_id=e.candidate_id JOIN proposals p ON p.proposal_id=c.proposal_id "
            "WHERE p.campaign_id=?", (campaign_id,))
        return {
            "n_proposals": int(len(props)),
            "mechanism_clusters": clusters,
            "rejected": rejected,
            "promoted": promoted[:20],
            "full_evaluations": int(len(evals)),
            "best_delta_oos": float(evals.delta_oos.max()) if len(evals) else None,
            "recent_dsl": cands["dsl_text"].tolist(),
        }
