"""Dashboard tests (OPS.md D.3: "a fake events file must render without the agent stack").

The fake registry is built by executing registry/schema.sql + registry/views.sql with plain
sqlite3 — never through registry.Registry — under a throw-away ABL_ROOT. Streamlit is not
required: app.py is only parsed (plus an AppTest smoke run that is skipped if unavailable).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from dashboard import alarms as alarms_mod
from dashboard import control, digest, i18n, narrative, reader, status
from dashboard.alarms import ALARM_KINDS, Alarm, compute_alarms, notify
from dashboard.narrative import LEVELS, narrate
from dashboard.reader import EventFeed, RegistryReader, load_events, tail_events

PROJECT = Path(__file__).resolve().parents[2]
DASH = PROJECT / "dashboard"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
FORBIDDEN = {"agents", "engine", "gates", "campaigns", "dsl", "sim", "genoframe", "dataio"}
NEXT_EXPERIMENT = "Re-run k0005 with optimum-contribution selection capped at dF 0.01 and re-test the plan gate."


def ts(**delta) -> str:
    return (NOW - timedelta(**delta)).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _lang_reset(monkeypatch):
    """Every test starts on the default language (zh) with no override; nothing leaks out."""
    monkeypatch.delenv("ABL_LANG", raising=False)
    i18n.set_lang(None)
    yield
    i18n.set_lang(None)


@pytest.fixture()
def en():
    """Tests that assert the English wording."""
    i18n.set_lang("en")
    yield "en"


@pytest.fixture()
def root(tmp_path, monkeypatch):
    r = tmp_path / "abl"
    for d in ("registry/prompts", "registry/packages", "control", "gates"):
        (r / d).mkdir(parents=True)
    shutil.copy(PROJECT / "gates" / "thresholds.yaml", r / "gates" / "thresholds.yaml")
    (r / "control" / "RUN").touch()
    monkeypatch.setenv("ABL_ROOT", str(r))
    monkeypatch.setenv("ABL_LLM", "stub")
    return r


ANALYST_OUT = json.dumps({"diagnosis": "plan gate limited the result: dF above cap",
                          "next_experiment": NEXT_EXPERIMENT}, sort_keys=True)
ANALYST_HASH = hashlib.sha256(ANALYST_OUT.encode()).hexdigest()


def _events() -> list[dict]:
    """24 events, oldest first; the last one is 20 minutes old (events_stalled)."""
    base = dict(campaign_id="c01", input_hash="i" * 8, output_hash="o" * 8, latency_ms=900, cost_usd=0.01)
    spec = [
        ("orchestrator", "step", None, "allocating budget to under-explored clusters", []),
        ("geneticist", "propose", "k0010", "G×E covariate on farm temperature", []),
        ("builder", "implement", "k0008", "region-weighted GRM with explicit 5-year lookback", []),
        ("critic", "review", "k0002",
         "Returned to builder: lookback uses phenotype available_at > selection_date (field: litter_size)", []),
        ("critic", "review", "k0003", "Rejected: parents of test animals present in training with phenotypes", []),
        ("critic", "review", "k0011", "REJECT — signal explained by line structure (shuffled labels)", []),
        ("critic", "review", "k0012", "PASS: no leakage found", []),
        ("gate", "accuracy", "k0002", "accuracy FAILED: rho 0.031 < min_rho 0.05", []),
        ("gate", "validity", "k0001", "validity passed: 3 operators, replay identical", []),
        ("gate", "plan", "k0005", "plan FAILED: dF 0.013 > cap 0.01", []),
        ("gate", "promote", "k0001", "all mandatory gates passed", []),
        ("analyst", "diagnose", "k0005", "plan gate limited: dF too high", []),
        ("orchestrator", "retry_limit", "k0004", "Retry limit reached for k0004", ["retry_limit"]),
        ("geneticist", "propose", None, "tried to open holdout/gen5 phenotypes (blocked)", ["holdout_touch"]),
        ("geneticist", "hypothesize", "k0006", "Proposed [qtl_prior]: QTL-prior weights from public GWAS hits", []),
        ("critic", "review", "k0008", "PASS", []),
        ("builder", "implement", "k0007", "Built champion() + qtl_prior(prior=gwas)", []),
        ("orchestrator", "dedup", "k0006", "semantic hash already evaluated; skipping full evaluation", []),
        ("critic", "review_code", "k0004",
         "RETURN_TO_BUILDER (thesis_code): operator 2 does not implement the stated mechanism", []),
        ("gate", "incremental", "k0005", "incremental passed: dOOS CI low 0.002", []),
        ("analyst", "diagnose", "k0001", "promoted: all mandatory gates passed → next: champion() + dominance()", []),
        ("weird_agent", "", None, "", []),
        ("builder", "implement", "k0010", "NEED_OPERATOR: env_covariate(temp)", []),
        ("geneticist", "propose", "k0009", "dominance term for litter size", []),
    ]
    out = []
    n = len(spec)
    for i, (agent, action, cand, summary, flags) in enumerate(spec):
        ev = dict(base, ts=ts(minutes=20 + (n - 1 - i) * 5), agent=agent, action=action, candidate_id=cand,
                  summary=summary, policy_flags=flags, tokens=1000 + 10 * i)
        if agent == "analyst" and cand == "k0001":             # the LATEST analyst call carries the file
            ev["output_hash"] = ANALYST_HASH
        out.append(ev)
    out[7].update(gate="accuracy", passed=False)          # one gate event with explicit keys
    return out


def _build_registry(r: Path, events: list[dict]) -> Path:
    db = r / "registry" / "abl.sqlite"
    con = sqlite3.connect(db)
    con.executescript((PROJECT / "registry" / "schema.sql").read_text())
    con.executescript((PROJECT / "registry" / "views.sql").read_text())

    def ins(table: str, **row):
        con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    [json.dumps(v) if isinstance(v, (list, dict)) else v for v in row.values()])

    thash = hashlib.sha256((r / "gates" / "thresholds.yaml").read_bytes()).hexdigest()
    ins("campaigns", campaign_id="c01", customer_id="sim", species="pig", trait_set=["litter_size"], horizon="1gen",
        champion_id="ssgblup", budget_full_evals=12, budget_tokens=60000, started_at=ts(days=3), ended_at=None,
        owner="newco", sharing_tier="private")
    ins("campaigns", campaign_id="c00", customer_id="sim", species="pig", trait_set=["adg"], horizon="1gen",
        champion_id="ssgblup", budget_full_evals=1, budget_tokens=1000, started_at=ts(days=10),
        ended_at=ts(days=8), owner="newco", sharing_tier="private")
    ins("threshold_versions", campaign_id="c01", thresholds_hash=thash, recorded_at=ts(days=3))
    ins("threshold_versions", campaign_id="c00", thresholds_hash="0" * 64, recorded_at=ts(days=10))

    clusters = ["region_weighted_grm"] * 6 + ["qtl_prior"] * 3 + ["gxe_covariate"] + ["negative_control_shuffled"] * 2
    # final state and the state at which rejected candidates left the funnel
    fate = {1: "promoted", 2: ("rejected", "validated"), 3: ("rejected", "registered"), 4: "reviewed",
            5: "evaluated", 6: "registered", 7: "validated", 8: "implemented", 9: ("rejected", "reviewed"),
            10: "registered", 11: ("rejected", "registered"), 12: "promoted"}
    chain = ["registered", "reviewed", "implemented", "validated", "evaluated", "promoted"]
    GATE_OF = {"registered": "registry", "reviewed": "critic", "implemented": "builder", "validated": "validity",
               "evaluated": "evaluation", "promoted": "promotion"}                    # as gates/runner.py writes them
    for i, cl in enumerate(clusters, start=1):
        pid, cid = f"p{i:02d}", f"k{i:04d}"
        ins("proposals", proposal_id=pid, campaign_id="c01", agent_model="stub", mechanism_text=f"mechanism {i}",
            mechanism_cluster=cl, direction="up", falsifiers=["no forward gain"], expected_gain={"delta_oos": 0.01},
            novelty_hash=f"n{i}", source_refs=["ref1"], tokens=100, created_at=ts(days=2, hours=i))
        f = fate[i]
        final, stop = (f, f) if isinstance(f, str) else f
        states = chain[: chain.index(stop) + 1]
        ins("candidates", candidate_id=cid, proposal_id=pid, dsl_text=f"champion() + op{i}", dsl_hash=f"d{i}",
            code_hash=f"c{i}", data_decl_hash=f"dd{i}", state=final, retry_count=3 if i == 4 else 0,
            supersedes=None, created_at=ts(days=2, hours=i), updated_at=ts(hours=1))
        prev = None
        for j, s in enumerate(states):
            ins("candidate_transitions", candidate_id=cid, from_state=prev, to_state=s, gate=GATE_OF[s],
                reason=f"{s} ok", at=ts(days=2, minutes=-j))
            prev = s
        if final == "rejected":
            ins("candidate_transitions", candidate_id=cid, from_state=prev, to_state="rejected",
                gate="promotion" if i == 2 else "critic", reason="failed gates: accuracy" if i == 2 else "leakage",
                at=ts(hours=2))

    reviews = [("k0001", "PASS", [], ts(days=2)), ("k0002", "RETURN", ["temporal"], ts(hours=3)),
               ("k0002", "PASS", [], ts(hours=2)), ("k0003", "REJECT", ["relatedness"], ts(hours=2)),
               ("k0004", "RETURN", ["thesis_code"], ts(hours=1)), ("k0005", "PASS", [], ts(days=2)),
               ("k0007", "PASS", [], ts(days=2)), ("k0008", "PASS", [], ts(hours=1)),
               ("k0009", "PASS", [], ts(days=2)), ("k0011", "REJECT", ["structure"], ts(hours=2)),
               ("k0012", "PASS", [], ts(hours=2))]
    for n, (cid, verdict, leaks, at) in enumerate(reviews):
        ins("critic_reviews", review_id=f"r{n}", candidate_id=cid, verdict=verdict, leak_type=leaks,
            evidence=[{"file": "dsl", "line": 3, "field": "litter_size", "note": "available_at > selection_date"}],
            tokens=500, created_at=at)

    def gate(cid, g, metric, value, thr, passed, at):
        ins("gate_results", candidate_id=cid, gate=g, metric=metric, value=value, ci_low=None, ci_high=None,
            threshold=thr, passed=int(passed), cutoff_date="2025-01-01", seed=7, data_snapshot_id="s1",
            evaluated_at=at)

    for g in ("validity", "accuracy", "incremental", "plan", "robustness", "research"):   # k0001: 6 recent passes
        gate("k0001", g, "m", 0.5, 0.1, True, ts(hours=1))
    for g, ok in (("validity", True), ("accuracy", True), ("incremental", True), ("plan", False)):
        gate("k0005", g, "dF" if g == "plan" else "m", 0.013 if g == "plan" else 0.4, 0.01, ok, ts(hours=1))
    gate("k0002", "validity", "m", 1, 1, True, ts(hours=1))
    gate("k0002", "accuracy", "rho", 0.031, 0.05, False, ts(hours=1))
    gate("k0012", "validity", "m", 1, 1, True, ts(hours=1))
    for n in range(22):                                   # baseline two days ago: 2 passes of 22
        gate(f"k{3 + n % 7:04d}", "validity", "m", 0, 1, n < 2, ts(days=2))

    for cid, split, d, lo, at in (("k0001", "s1", 0.021, 0.004, ts(hours=1)), ("k0001", "s2", 0.019, 0.003, ts(hours=1)),
                                  ("k0005", "s1", -0.003, -0.01, ts(days=2)), ("k0012", "s1", 0.011, -0.002, ts(hours=1))):
        ins("evaluations", evaluation_id=f"e_{cid}_{split}", candidate_id=cid, split_id=split, rho=0.4, bias=0.01,
            dispersion=0.98, delta_oos=d, delta_oos_ci_low=lo, n_train=500, n_test=100, compute_seconds=12.5,
            tokens=0, evaluated_at=at)

    for ev in events:
        ins("agent_events", ts=ev["ts"], campaign_id=ev["campaign_id"], agent=ev["agent"], action=ev["action"] or "?",
            candidate_id=ev["candidate_id"], input_hash=ev["input_hash"], output_hash=ev["output_hash"],
            tokens=ev["tokens"], latency_ms=ev["latency_ms"], summary=ev["summary"], policy_flags=ev["policy_flags"],
            cost_usd=ev["cost_usd"])
    ins("agent_events", ts=ts(days=9), campaign_id="c00", agent="builder", action="implement", candidate_id=None,
        input_hash="x", output_hash="y", tokens=999999, latency_ms=1, summary="old ended campaign", policy_flags=[],
        cost_usd=1.0)   # the ended campaign blew its cap: must NOT alarm
    con.commit()
    con.close()
    return db


def _write_package(r: Path) -> None:
    pkg = {
        "thesis": {"mechanism": "Region-weighted GRM up-weights QTL windows", "direction": "animals carrying QTL move up",
                   "falsifiers": ["no forward-in-time gain"], "expected_gain": {"delta_oos": 0.01, "dispersion_b": 1.0},
                   "mechanism_cluster": "region_weighted_grm", "source_refs": ["ref1"]},
        "dsl": {"text": "grm_region_weighted(windows=qtl, w=2)", "semantic_hash": "abc123", "operators": ["grm_region_weighted"]},
        "data_declaration": {"fields": [{"name": "litter_size", "available_at": "farrowing_date"}],
                             "snapshot_id": "s1", "versions": {"pedigree": "v1"}, "hash": "dd1"},
        "tests": [{"name": "causality", "passed": True, "detail": "ok"}],
        "provenance": {"code_hash": "c1", "seed": 7},
        "evaluation": {"gates": [{"gate": "accuracy", "metric": "rho", "value": 0.4, "ci_low": 0.3, "ci_high": 0.5,
                                  "threshold": 0.05, "passed": True}],
                       "disposition": "promoted", "analyst_summary": "better ranking", "diagnosis": "none",
                       "next_experiment": "replicate on second line"},
    }
    (r / "registry" / "packages" / "k0001.json").write_text(json.dumps(pkg))


def _write_events(r: Path, events: list[dict]) -> Path:
    p = r / "registry" / "events.jsonl"
    lines = [json.dumps(e) for e in events]
    lines.insert(5, "{this is not json")                   # a corrupt line must be skipped
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.fixture()
def world(root):
    events = _events()
    _build_registry(root, events)
    _write_events(root, events)
    _write_package(root)
    (root / "registry" / "prompts" / f"{ANALYST_HASH}.out.txt").write_text(ANALYST_OUT)
    return root


# --------------------------------------------------------------------------------------------
# reader: events
# --------------------------------------------------------------------------------------------
def test_tail_events_incremental_and_partial_line(tmp_path):
    p = tmp_path / "events.jsonl"
    a, b, c = ({"ts": ts(minutes=i), "agent": "critic", "n": i} for i in range(3))
    partial = json.dumps(c)
    p.write_bytes((json.dumps(a) + "\n" + json.dumps(b) + "\n" + partial[:10]).encode())
    evs, off = tail_events(p, 0)
    assert [e["n"] for e in evs] == [0, 1]
    assert off == len((json.dumps(a) + "\n" + json.dumps(b) + "\n").encode())
    assert tail_events(p, off) == ([], off)                          # partial line: nothing consumed
    with open(p, "ab") as f:
        f.write((partial[10:] + "\n" + "garbage\n" + json.dumps({"n": 9}) + "\n").encode())
    evs2, off2 = tail_events(p, off)
    assert [e["n"] for e in evs2] == [2, 9]                           # garbage skipped
    assert off2 == p.stat().st_size
    assert tail_events(p, off2) == ([], off2)


def test_tail_events_truncation_and_missing(tmp_path):
    p = tmp_path / "events.jsonl"
    assert tail_events(p, 123) == ([], 0)
    p.write_text(json.dumps({"n": 1}) + "\n")
    evs, off = tail_events(p, 10_000)                                # offset past EOF -> restart
    assert [e["n"] for e in evs] == [1] and off == p.stat().st_size
    feed = EventFeed(p)
    feed.poll()
    assert feed.total == 1
    p.write_text("")                                                 # truncated
    feed.poll()
    p.write_text(json.dumps({"n": 3}) + "\n")
    feed.poll()
    assert [e["n"] for e in feed.snapshot()] == [3]


def test_load_events_and_feed(world):
    evs = load_events()
    assert len(evs) == 24                                            # corrupt line skipped
    assert [e["agent"] for e in load_events(limit=2)] == ["builder", "geneticist"]
    feed = EventFeed()
    new = feed.poll()
    assert len(new) == 24 and feed.poll() == []
    flagged = feed.alarm_events()
    assert {f for e in flagged for f in e.get("policy_flags", [])} == {"holdout_touch", "retry_limit"}
    assert flagged[-1]["agent"] == "geneticist"                      # the latest event is kept for stall checks


# --------------------------------------------------------------------------------------------
# reader: registry
# --------------------------------------------------------------------------------------------
READER_CALLS = [
    ("campaigns", ()), ("funnel", ()), ("funnel", ("c01",)), ("funnel_stages", ()), ("funnel_compare", ("c01",)),
    ("diversity", ()), ("mechanism_map", ()), ("critic_quality", ()), ("budget", ()), ("budget", ("c01",)),
    ("candidates", ()), ("gate_results_for", ("k0001",)), ("transitions", ()), ("transitions", ("k0002",)),
    ("critic_reviews", ()), ("evaluations", ()), ("gate_summary", ()), ("gate_failures", ()),
    ("gate_pass_rates", (ts(hours=24),)), ("rejection_reasons", ()), ("threshold_status", ()),
    ("negative_control_reviews", ()), ("false_promotions", ()), ("window_counts", (ts(hours=24),)),
    ("cost_by_agent", ()), ("latest_analyst_event", ()), ("gate_events", ()),
]


def test_every_reader_method_is_covered():
    public = {n for n in dir(RegistryReader) if not n.startswith("_") and callable(getattr(RegistryReader, n))}
    assert public - {"query", "available"} == {name for name, _ in READER_CALLS}


def test_registry_reader_returns_frames(world):
    rr = RegistryReader()
    for name, args in READER_CALLS:
        df = getattr(rr, name)(*args)
        assert isinstance(df, pd.DataFrame), name
        assert rr.last_error is None, (name, rr.last_error)


def test_registry_reader_values(world):
    rr = RegistryReader()
    f = rr.funnel("c01").iloc[0]
    assert (f.proposals, f.promoted, f.rejected) == (12, 2, 4)
    fc = rr.funnel_compare("c01", NOW).set_index("stage")
    assert fc.loc["proposals", "campaign_to_date"] == 12 and fc.loc["promoted", "campaign_to_date"] == 2
    assert (fc["today"] <= fc["campaign_to_date"]).all()
    mm = rr.mechanism_map("c01").set_index("mechanism_cluster")
    assert mm.loc["region_weighted_grm", "proposals"] == 6 and mm.loc["region_weighted_grm", "promoted"] == 1
    assert (mm["in_progress"] >= 0).all()
    b = rr.budget("c01", NOW).iloc[0]
    assert b.evals_used == 3 and b.evaluation_rows == 4 and b.budget_full_evals == 12
    assert b.tokens_used == sum(e["tokens"] for e in _events()) and b.tokens_per_hour > 0
    gr = rr.gate_results_for("k0002")
    assert list(gr.gate) == ["validity", "accuracy"] and gr.threshold.iloc[1] == 0.05
    assert list(rr.false_promotions().candidate_id) == ["k0012"]
    nc = rr.negative_control_reviews().set_index("candidate_id")
    assert nc.loc["k0011", "verdict"] == "REJECT" and nc.loc["k0012", "correct"] == 0
    th = rr.threshold_status().set_index("campaign_id")
    assert not th.loc["c01", "changed"] and th.loc["c00", "changed"] and not th.loc["c00", "active"]
    assert rr.latest_analyst_event().iloc[0].output_hash == ANALYST_HASH


def test_registry_reader_missing_db(root):
    rr = RegistryReader()
    assert not rr.available()
    for name, args in READER_CALLS:
        df = getattr(rr, name)(*args)
        assert isinstance(df, pd.DataFrame), name
        if name not in ("funnel_stages", "funnel_compare"):          # those return the stage list with zeros
            assert df.empty, name
    assert not (root / "registry" / "abl.sqlite").exists()           # read-only: nothing created


def test_registry_reader_locked_db(root):
    db = root / "registry" / "abl.sqlite"
    w = sqlite3.connect(db, isolation_level=None)
    w.executescript((PROJECT / "registry" / "schema.sql").read_text())
    w.executescript((PROJECT / "registry" / "views.sql").read_text())
    w.execute("PRAGMA journal_mode=DELETE")                          # rollback journal: writers block readers
    w.execute("INSERT INTO campaigns VALUES ('c01','sim','pig','[]','1g','ch',3,100,'2026-01-01T00:00:00Z',NULL,'newco','private')")
    rr = RegistryReader(keep_last=True, busy_timeout_ms=20)
    assert len(rr.campaigns()) == 1
    w.execute("BEGIN EXCLUSIVE")
    try:
        cold = RegistryReader(busy_timeout_ms=20)
        assert cold.campaigns().empty and "locked" in (cold.last_error or "")
        assert cold.budget().empty and cold.funnel().empty
        warm = rr.campaigns()                                         # keep_last: previous snapshot
        assert len(warm) == 1 and "locked" in (rr.last_error or "")
    finally:
        w.execute("ROLLBACK")
        w.close()


# --------------------------------------------------------------------------------------------
# alarms
# --------------------------------------------------------------------------------------------
def test_compute_alarms(world):
    events = load_events()
    kinds = {a.kind: a for a in compute_alarms(events, RegistryReader(), NOW)}
    assert set(kinds) <= set(ALARM_KINDS)
    for k in ("holdout_touch", "retry_limit", "events_stalled", "cluster_concentration", "suspicious_pass_rate"):
        assert k in kinds, k
    assert "threshold_changed" not in kinds and "budget_exceeded" not in kinds   # c00 ended: ignored
    assert all(a.severity == "red" and a.message and a.ts for a in kinds.values())
    assert "k0004" in kinds["retry_limit"].message
    assert "region_weighted_grm" in kinds["cluster_concentration"].message

    with open(world / "gates" / "thresholds.yaml", "a") as f:        # threshold edit mid-campaign
        f.write("\n# loosened by someone\n")
    kinds = {a.kind for a in compute_alarms(events, RegistryReader(), NOW)}
    assert "threshold_changed" in kinds

    (world / "control" / "PAUSE").touch()                            # paused: silence is expected
    assert "events_stalled" not in {a.kind for a in compute_alarms(events, RegistryReader(), NOW)}
    (world / "control" / "PAUSE").unlink()
    fresh = events + [{"ts": ts(minutes=1), "agent": "critic", "action": "review", "policy_flags": []}]
    assert "events_stalled" not in {a.kind for a in compute_alarms(fresh, RegistryReader(), NOW)}


def test_budget_alarm_from_sql(world, en):
    con = sqlite3.connect(world / "registry" / "abl.sqlite")
    con.execute("INSERT INTO agent_events (ts, campaign_id, agent, action, input_hash, output_hash, tokens) "
                "VALUES (?, 'c01', 'builder', 'implement', 'x', 'y', 100000)", (ts(minutes=2),))
    con.commit()
    con.close()
    a = {x.kind: x for x in compute_alarms([], RegistryReader(), NOW)}
    assert "budget_exceeded" in a and "c01" in a["budget_exceeded"].message and "c00" not in a["budget_exceeded"].message
    flagged = [{"ts": ts(minutes=1), "agent": "orchestrator", "action": "step", "policy_flags": ["budget_exceeded"]}]
    assert "flagged budget_exceeded" in {x.kind: x for x in compute_alarms(flagged, RegistryReader(), NOW)}[
        "budget_exceeded"].message


def test_no_alarms_on_empty_root(root):
    assert compute_alarms([], RegistryReader(), NOW) == []


def test_notify_throttles_and_logs(world, monkeypatch):
    calls = []
    monkeypatch.setattr(alarms_mod.subprocess, "run", lambda args, **kw: calls.append(args))
    state = world / "dashboard" / "state.json"
    al = [Alarm("holdout_touch", "1 event flagged", ts(minutes=1)), Alarm("events_stalled", "no event", ts(minutes=1))]
    assert set(notify(al, now=NOW, platform="darwin")) == {"holdout_touch", "events_stalled"}
    assert len(calls) == 2 and calls[0][0] == "osascript" and "display notification" in calls[0][2]
    assert notify(al, now=NOW + timedelta(minutes=5), platform="darwin") == []       # throttled
    assert len(calls) == 2
    assert notify(al, now=NOW + timedelta(minutes=11), platform="darwin") != []
    assert len(calls) == 4
    notify(al, now=NOW + timedelta(minutes=30), platform="linux")                  # never osascript off macOS
    assert len(calls) == 4
    log = (world / "registry" / "alarms.log").read_text().splitlines()
    assert len(log) == 6 and all("\tRED\t" in line for line in log)
    st = json.loads(state.read_text())
    assert set(st["notified"]) == {"holdout_touch", "events_stalled"}


# --------------------------------------------------------------------------------------------
# narrative
# --------------------------------------------------------------------------------------------
def test_narrate_every_event(world, en):
    evs = load_events()
    out = [narrate(e) for e in evs]
    assert all(isinstance(t, str) and t and lvl in LEVELS for t, lvl in out)
    by = {(e["agent"], e["action"], e.get("candidate_id")): r for e, r in zip(evs, out)}
    t, lvl = by[("critic", "review", "k0002")]
    assert t == ("Critic returned candidate k0002 to builder: lookback uses phenotype available_at > "
                 "selection_date (field: litter_size)") and lvl == "warn"
    assert by[("gate", "accuracy", "k0002")] == ("Gate accuracy FAILED for k0002: rho 0.031 < min_rho 0.05", "fail")
    assert by[("gate", "plan", "k0005")] == ("Gate plan FAILED for k0005: dF 0.013 > cap 0.01", "fail")
    assert by[("gate", "incremental", "k0005")][1] == "info"
    assert by[("critic", "review", "k0003")][1] == "fail"
    assert by[("critic", "review", "k0012")] == ("Critic passed candidate k0012: no leakage found", "info")
    assert by[("critic", "review", "k0008")] == ("Critic passed candidate k0008", "info")
    assert by[("critic", "review_code", "k0004")] == ("Critic returned candidate k0004 to builder (thesis_code): "
                                                      "operator 2 does not implement the stated mechanism", "warn")
    assert by[("geneticist", "hypothesize", "k0006")] == (
        "Geneticist proposed candidate k0006 [qtl_prior]: QTL-prior weights from public GWAS hits", "info")
    assert by[("builder", "implement", "k0007")] == ("Builder implemented candidate k0007: champion() + "
                                                     "qtl_prior(prior=gwas)", "info")
    assert by[("builder", "implement", "k0010")] == ("Builder needs a new DSL operator for candidate k0010: "
                                                     "env_covariate(temp)", "warn")
    assert by[("analyst", "diagnose", "k0001")][0] == ("Analyst diagnosed candidate k0001: promoted: all mandatory "
                                                       "gates passed → next: champion() + dominance()")
    assert by[("orchestrator", "retry_limit", "k0004")][1] == "fail"
    assert by[("gate", "validity", "k0001")][1] == "info"
    promote = [r for e, r in zip(evs, out) if e["action"] == "promote"]
    assert promote == [("Candidate k0001 PROMOTED: all mandatory gates passed", "promote")]
    holdout = [r for e, r in zip(evs, out) if "holdout_touch" in e["policy_flags"]]
    assert holdout[0][1] == "fail" and "holdout_touch" in holdout[0][0]
    assert narrate("nope") == ("Unreadable event (not a JSON object)", "warn")
    assert narrate({})[1] == "info"


def test_gate_outcomes_reach_the_feed(world, en):
    """Gates write SQL only (gates/runner.py); the feed synthesises their failures and promotions."""
    evs = reader.registry_gate_events(RegistryReader())
    assert evs and all(e["source"].startswith("registry:") and e["agent"] == "gate" for e in evs)
    lines = {narrate(e) for e in evs}
    assert ("Gate accuracy FAILED for k0002: rho 0.031 vs threshold 0.05", "fail") in lines
    assert ("Gate plan FAILED for k0005: dF 0.013 vs threshold 0.01", "fail") in lines
    assert ("Candidate k0001 PROMOTED: promoted ok", "promote") in lines
    assert ("Candidate k0002 REJECTED at promotion: failed gates: accuracy", "fail") in lines
    assert not any("leakage" in t for t, _ in lines)                 # critic transitions come via critic events
    assert reader.registry_gate_events(RegistryReader(), since=ts(minutes=1)) == []


# --------------------------------------------------------------------------------------------
# status / digest / control
# --------------------------------------------------------------------------------------------
def test_status_main(world, capsys, en):
    assert status.main(["--plain"]) == 0
    out = capsys.readouterr().out
    for s in ("Proposals", "Critic verdicts", "Gate results", "Promotions", "Tokens", "Evaluations vs cap",
              "RED holdout_touch", "RUNNING"):
        assert s in out, s
    assert "c01: tokens" in out and "full evals 3/12" in out
    assert status.main([]) == 0                                      # rich renderer
    assert "Alarms" in capsys.readouterr().out


def test_status_main_empty_root(tmp_path, monkeypatch, capsys, en):
    monkeypatch.setenv("ABL_ROOT", str(tmp_path / "empty"))
    assert status.main(["--plain"]) == 0
    out = capsys.readouterr().out
    assert "Proposals" in out and "PASS 0 · RETURN 0 · REJECT 0" in out and "IDLE" in out
    assert not (tmp_path / "empty").exists()                         # status writes nothing


def test_digest_main(world, capsys, en):
    assert digest.main([]) == 0
    p = world / "registry" / f"digest_{datetime.now(timezone.utc).date().isoformat()}.md"
    assert p.exists() and str(p) in capsys.readouterr().out
    md = p.read_text()
    sections = ["## What was learned", "## What was rejected and why", "## Alarms", "## Cost",
                "## Next experiment (Analyst)"]
    idx = [md.index(s) for s in sections]
    assert idx == sorted(idx)
    body = lambda a, b: [l for l in md[md.index(a):md.index(b)].splitlines() if l.startswith("- ")]  # noqa: E731
    assert len(body(sections[0], sections[1])) == 5
    assert len(body(sections[1], sections[2])) == 3
    assert "holdout_touch" in md and NEXT_EXPERIMENT in md and "stub" in md


def test_digest_guard_keeps_numbers(world, en):
    facts = digest.build_facts(NOW, RegistryReader(), load_events())
    det = digest.deterministic_bullets(facts)
    allowed = digest.numbers_in(json.dumps(facts, indent=1, sort_keys=True, ensure_ascii=False, default=str))
    assert all(digest.numbers_in(b) <= allowed for b in det["learned"] + det["rejected"])

    class FakeLLM:
        model = "fake"

        def complete(self, **kw):
            learned = ["The loop produced 999 proposals.", f"{facts['last_24h']['proposals']} proposals in 24h."]
            return type("R", (), {"parsed": {"learned": learned, "rejected": ["All good."]}, "model": "fake"})()

    bullets, note = digest.narrative_bullets(facts, FakeLLM())
    assert bullets["learned"][0] == det["learned"][0]                # 999 invented -> replaced
    assert bullets["learned"][1].startswith(str(facts["last_24h"]["proposals"]))
    assert bullets["rejected"][0] == "All good." and len(bullets["rejected"]) == 3
    assert "replaced" in note


def test_digest_empty_root(tmp_path, monkeypatch, en):
    monkeypatch.setenv("ABL_ROOT", str(tmp_path / "empty"))
    monkeypatch.setenv("ABL_LLM", "stub")
    assert digest.main([]) == 0
    md = next((tmp_path / "empty" / "registry").glob("digest_*.md")).read_text()
    assert "No Analyst call has been recorded yet." in md and "## What was learned" in md


def test_control_pause_resume(root):
    assert control.control_state() == {"run": True, "paused": False, "label": "RUNNING"}
    control.pause()
    assert (root / "control" / "PAUSE").exists() and control.control_state()["label"] == "PAUSED"
    control.resume()
    control.resume()
    assert not (root / "control" / "PAUSE").exists() and (root / "control" / "RUN").exists()


# --------------------------------------------------------------------------------------------
# isolation (OPS.md D.3 hard rules)
# --------------------------------------------------------------------------------------------
def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg = list(path.relative_to(PROJECT).with_suffix("").parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name, None
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[: len(pkg) - (node.level - 1)]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            yield node.lineno, mod, [a.name for a in node.names]
        elif isinstance(node, ast.Call):
            fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if fn in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                yield node.lineno, node.args[0].value, None


def _dashboard_files() -> list[Path]:
    files = sorted(DASH.rglob("*.py"))
    assert DASH / "app.py" in files and DASH / "reader.py" in files
    return files


def test_no_forbidden_imports():
    bad, uses_ro = [], False
    for f in _dashboard_files():
        for line, mod, names in _imports(f):
            top = mod.split(".")[0]
            if top in FORBIDDEN:
                bad.append(f"{f.relative_to(PROJECT)}:{line} imports {mod}")
            elif top == "registry":
                if mod == "registry.db" and names and set(names) <= {"connect_readonly"}:
                    uses_ro = True
                else:
                    bad.append(f"{f.relative_to(PROJECT)}:{line} imports {mod} {names or ''} "
                               f"(only `from registry.db import connect_readonly` is allowed)")
    assert not bad, "\n".join(bad)
    assert uses_ro


def test_streamlit_only_in_app():
    for f in _dashboard_files():
        if f.name == "app.py" or "tests" in f.relative_to(DASH).parts:   # tests only importorskip it
            continue
        assert not [m for _, m, _ in _imports(f) if m.split(".")[0] == "streamlit"], f


def test_app_parses():
    tree = ast.parse((DASH / "app.py").read_text(encoding="utf-8"))
    fragments = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and any("fragment" in ast.unparse(d) and "run_every" in ast.unparse(d) for d in n.decorator_list)]
    assert len(fragments) >= 6
    assert "time.sleep" not in (DASH / "app.py").read_text()


BLOCKER = r"""
import importlib.abc, sys
BLOCK = {"agents", "engine", "gates", "campaigns", "dsl", "sim", "genoframe", "dataio", "streamlit", "anthropic"}
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ImportError("blocked by test: " + name)
        return None
sys.meta_path.insert(0, Blocker())
from dashboard import alarms, control, digest, narrative, reader, status
from dashboard.reader import load_events, RegistryReader
assert status.main(["--plain"]) == 0
assert digest.main([]) == 0
kinds = sorted(a.kind for a in alarms.compute_alarms(load_events(), RegistryReader()))
print("KINDS", kinds)
assert [narrative.narrate(e) for e in load_events()]
"""


def test_renders_without_agent_stack_or_streamlit(world):
    env = dict(os.environ, ABL_ROOT=str(world), ABL_LLM="stub", PYTHONPATH=str(PROJECT))
    r = subprocess.run([sys.executable, "-c", BLOCKER], cwd=str(PROJECT), env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    assert "KINDS" in r.stdout and "holdout_touch" in r.stdout


def test_app_smoke_with_streamlit_apptest(world):
    pytest.importorskip("streamlit")
    testing = pytest.importorskip("streamlit.testing.v1")
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()
    at = testing.AppTest.from_file(str(DASH / "app.py"), default_timeout=60)
    at.run()                                                         # default language: zh
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["abl_lang"] == "zh"
    text = " ".join(e.value for e in at.error)
    assert "holdout_touch" in text
    assert any("监护" in h.value for h in at.header)
    assert any(_CJK.search(e.value) for e in at.error)                # alarm messages are in Chinese
    at.button(key="btn_pause").click().run()
    assert (world / "control" / "PAUSE").exists()
    at.button(key="btn_resume").click().run()
    assert not (world / "control" / "PAUSE").exists()

    st.cache_data.clear()
    st.cache_resource.clear()
    at = testing.AppTest.from_file(str(DASH / "app.py"), default_timeout=60)
    at.session_state["abl_lang"] = "en"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Guardian" in h.value for h in at.header)
    assert not any(_CJK.search(h.value) for h in list(at.header) + list(at.subheader))
    assert "holdout_touch" in " ".join(e.value for e in at.error)


# --------------------------------------------------------------------------------------------
# i18n (中文 / English)
# --------------------------------------------------------------------------------------------
_CJK = __import__("re").compile(r"[㐀-鿿豈-﫿　-〿＀-￯]")


def _t_keys(path: Path) -> set[str]:
    """Every string literal inside the first argument of a call to ``t(...)`` in ``path``."""
    keys = set()

    def collect(n):                  # "key" or  "a" if cond else "b"
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            keys.add(n.value)
        elif isinstance(n, ast.IfExp):
            collect(n.body)
            collect(n.orelse)

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t" and node.args:
            collect(node.args[0])
    return keys


def test_i18n_every_used_key_exists_in_both_languages():
    used: dict[str, set[str]] = {}
    for f in _dashboard_files():
        if "tests" in f.relative_to(DASH).parts:
            continue
        for k in _t_keys(f):
            used.setdefault(k, set()).add(f.name)
    for name in ("app.py", "status.py", "digest.py", "narrative.py", "alarms.py"):
        assert any(name in files for files in used.values()), f"{name} uses no t() keys"
    # keys chosen at runtime from lookup tables
    for table in (narrative.AGENT_KEYS, narrative.VERB_KEYS, narrative.FLAG_KEYS):
        for k in table.values():
            used.setdefault(k, set()).add("narrative.py")
    missing = sorted(k for k in used if k not in i18n.STRINGS)
    assert not missing, missing
    for k, v in i18n.STRINGS.items():
        assert set(v) == set(i18n.LANGS), k
        assert all(isinstance(v[lang], str) and v[lang].strip() for lang in i18n.LANGS), k
    unused = sorted(set(i18n.STRINGS) - set(used))
    assert not unused, unused                                        # no dead strings either


def test_i18n_placeholders_match_between_languages():
    import string
    for k, v in i18n.STRINGS.items():
        fields = {lang: {f for _, f, _, _ in string.Formatter().parse(v[lang]) if f} for lang in i18n.LANGS}
        assert fields["zh"] == fields["en"], (k, fields)


def test_i18n_resolution(monkeypatch):
    assert i18n.DEFAULT_LANG == "zh" and i18n.current_lang() == "zh"
    monkeypatch.setenv("ABL_LANG", "en")
    assert i18n.current_lang() == "en" and i18n.t("st_proposals") == "Proposals"
    monkeypatch.setenv("ABL_LANG", "fr")                             # invalid -> default
    assert i18n.current_lang() == "zh" and i18n.t("st_proposals") == "提案"
    monkeypatch.setenv("ABL_LANG", "en")
    i18n.set_lang("zh")                                              # explicit override beats the env
    assert i18n.current_lang() == "zh"
    with i18n.using_lang("en"):
        assert i18n.current_lang() == "en"
    assert i18n.current_lang() == "zh"
    i18n.set_lang(None)
    assert i18n.current_lang() == "en"
    with pytest.raises(ValueError):
        i18n.set_lang("de")
    assert i18n.lang_label("zh") == "中文" and i18n.lang_label("en") == "English"


def test_i18n_t_is_strict():
    with pytest.raises(KeyError):
        i18n.t("no_such_key")
    with pytest.raises(KeyError):
        i18n.t("narr_promoted")                                      # placeholder {cand} not given
    assert i18n.t("narr_promoted", cand="k0001") == "候选 k0001 已晋级（PROMOTED）"


def test_narrate_both_languages(world):
    evs = load_events() + reader.registry_gate_events(RegistryReader()) + ["nope", {}]
    out = {}
    for lang in i18n.LANGS:
        i18n.set_lang(lang)
        out[lang] = [narrate(e) for e in evs]
    for (zt, zl), (et, el), ev in zip(out["zh"], out["en"], evs):
        assert zt and et and zl == el and zl in LEVELS, ev
        assert not _CJK.search(et), et
    assert sum(bool(_CJK.search(zt)) for zt, _ in out["zh"]) == len(evs)
    i18n.set_lang("zh")
    by = {(e["agent"], e["action"], e.get("candidate_id")): narrate(e) for e in load_events()}
    assert by[("critic", "review", "k0002")] == (
        "评审者将候选 k0002 退回构建者：lookback uses phenotype available_at > selection_date (field: litter_size)", "warn")
    assert by[("gate", "accuracy", "k0002")] == ("候选 k0002 未通过 accuracy 门（FAILED）：rho 0.031 < min_rho 0.05", "fail")
    assert by[("geneticist", "hypothesize", "k0006")][0].startswith("遗传学家提出了候选 k0006 [qtl_prior]")


def test_alarms_both_languages(world):
    events = load_events()
    msgs = {}
    for lang in i18n.LANGS:
        i18n.set_lang(lang)
        msgs[lang] = {a.kind: a.message for a in compute_alarms(events, RegistryReader(), NOW)}
    assert set(msgs["zh"]) == set(msgs["en"]) and msgs["zh"]
    for kind in msgs["zh"]:
        assert _CJK.search(msgs["zh"][kind]) and not _CJK.search(msgs["en"][kind]), kind
    assert "k0004" in msgs["zh"]["retry_limit"] and "region_weighted_grm" in msgs["zh"]["cluster_concentration"]


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_status_lang_flag(world, capsys, lang):
    assert status.main(["--plain", "--lang", lang]) == 0
    out = capsys.readouterr().out
    assert bool(_CJK.search(out)) == (lang == "zh")
    assert "holdout_touch" in out and "c01" in out
    assert i18n.current_lang() == "zh"                               # --lang does not leak past the run
    assert status.main(["--lang", lang]) == 0                        # rich renderer
    assert bool(_CJK.search(capsys.readouterr().out)) == (lang == "zh")


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_digest_lang_flag(world, capsys, lang):
    assert digest.main(["--lang", lang]) == 0
    capsys.readouterr()
    p = world / "registry" / f"digest_{datetime.now(timezone.utc).date().isoformat()}.md"
    md = p.read_text(encoding="utf-8")
    assert bool(_CJK.search(md)) == (lang == "zh")
    heads = [l for l in md.splitlines() if l.startswith("## ")]
    assert len(heads) == 5
    body = md.split("\n## ")
    assert len([l for l in body[1].splitlines() if l.startswith("- ")]) == 5
    assert len([l for l in body[2].splitlines() if l.startswith("- ")]) == 3
    assert "holdout_touch" in md and NEXT_EXPERIMENT in md


def test_digest_zh_bullets_keep_numbers(world):
    i18n.set_lang("zh")
    facts = digest.build_facts(NOW, RegistryReader(), load_events())
    det = digest.deterministic_bullets(facts)
    allowed = digest.numbers_in(json.dumps(facts, indent=1, sort_keys=True, ensure_ascii=False, default=str))
    assert all(_CJK.search(b) for b in det["learned"] + det["rejected"])
    assert all(digest.numbers_in(b) <= allowed for b in det["learned"] + det["rejected"])
    seen = {}

    class FakeLLM:
        def complete(self, **kw):
            seen.update(kw)
            return type("R", (), {"parsed": {"learned": ["共 999 个提案。"], "rejected": []}, "model": "fake"})()

    bullets, note = digest.narrative_bullets(facts, FakeLLM())
    assert "Simplified Chinese" in seen["system"] and bullets["learned"][0] == det["learned"][0]
    assert "fake" in note and _CJK.search(note)
    i18n.set_lang("en")
    digest.narrative_bullets(facts, FakeLLM())
    assert "Write every bullet in English." in seen["system"]


def test_app_avoids_streamlit_apis_newer_than_1_37():
    """Python 3.9 users get Streamlit ≤1.40: no segmented_control kwargs, no width=, no bar_chart sort=.
    The app must route those through its version-adaptive helpers instead of calling them directly."""
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))   # ignore comments
    assert "st.segmented_control(" not in code
    assert 'width="stretch"' not in code.replace('{"width": "stretch"}', "")
    assert "st.bar_chart(chart" not in code          # goes through _bar_chart
