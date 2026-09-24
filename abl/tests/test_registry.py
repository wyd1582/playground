import sqlite3

import pytest

from registry import Registry, append_event, connect_readonly


def _campaign(reg):
    return reg.add_campaign(campaign_id="c_test", customer_id="sim", species="pig", trait_set=["t1"],
                            horizon="1gen", champion_id="champ", budget_full_evals=3, budget_tokens=1000)


def test_schema_and_views_exist(abl_root):
    reg = Registry()
    names = {r[0] for r in reg.con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    for t in ["campaigns", "proposals", "candidates", "critic_reviews", "gate_results", "evaluations",
              "data_snapshots", "recommendations", "decisions", "outcomes", "agent_events", "costs", "controls"]:
        assert t in names
    for v in ["v_funnel", "v_cost_per_promotion", "v_adoption", "v_realized", "v_drift", "v_diversity",
              "v_critic_quality", "v_marker_value", "v_customer_scorecard"]:
        assert v in names


def test_append_only_state_machine(abl_root):
    reg = Registry()
    cid_campaign = _campaign(reg)
    pid = reg.add_proposal(campaign_id=cid_campaign, agent_model="stub", mechanism_text="m", mechanism_cluster="x",
                           direction="up", falsifiers=["f"], expected_gain={"delta_oos": 0.01}, novelty_hash="h1",
                           source_refs=[])
    cid = reg.add_candidate(proposal_id=pid, dsl_text="champion()", dsl_hash="d", code_hash="c", data_decl_hash="dd")
    assert reg.candidate_state(cid) == "registered"
    with pytest.raises(PermissionError):
        reg.transition(cid, "reviewed", gate="critic", reason="test may not change state")
    assert reg.candidate_state(cid) == "registered"
    hist = reg.df("SELECT * FROM candidate_transitions WHERE candidate_id=?", (cid,))
    assert list(hist.to_state) == ["registered"]
    assert reg.novelty_hash_exists("h1", cid_campaign) and not reg.novelty_hash_exists("nope")


def test_events_jsonl_and_readonly(abl_root):
    reg = Registry()
    _campaign(reg)
    ev = append_event(agent="critic", action="review", campaign_id="c_test", candidate_id="k1",
                      input_obj={"a": 1}, output_obj={"verdict": "PASS"}, tokens=10, latency_ms=5,
                      summary="ok", registry=reg)
    lines = (abl_root / "registry" / "events.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1 and '"agent": "critic"' in lines[0]
    assert (abl_root / "registry" / "prompts" / f"{ev['input_hash']}.in.txt").exists()
    ro = connect_readonly()
    assert ro.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO costs(campaign_id, customer_id, period) VALUES ('c','c','p')")
    with pytest.raises(ValueError):
        append_event(agent="x", action="y", campaign_id=None, policy_flags=["not_a_flag"])


def test_threshold_hash_recorded(abl_root):
    reg = Registry()
    _campaign(reg)
    h = reg.thresholds_hash_at_start("c_test")
    assert h and len(h) == 64
