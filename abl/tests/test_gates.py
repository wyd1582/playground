import numpy as np
import pytest

from dsl import compile_program, parse, validate
from engine import Evaluator, freeze_champion
from gates import GateRunner, load_thresholds
from gates.stats import expected_max_z, paired_bootstrap_delta
from genoframe import forward_splits
from registry import Registry
from sim import SimConfig, simulate

CFG = SimConfig(n_founders=200, n_per_gen=300, n_gens=5, n_chrom=3, markers_per_chrom=200, qtl_per_chrom=8)


@pytest.fixture()
def harness(abl_root):
    r = simulate(CFG)
    pub = r.frame.public_view()
    splits = forward_splits(pub, "t1", max_t=3)[1:]
    ev = Evaluator(pub, r.priors, "t1")
    freeze_champion(ev, splits[-1], blend_w=0.05, covariates=["line", "farm", "birth_t"])
    reg = Registry()
    reg.add_campaign(campaign_id="c1", customer_id="sim", species="sim_pig", trait_set=["t1"], horizon="1gen",
                     champion_id=ev.champion.champion_id, budget_full_evals=5, budget_tokens=10_000)
    truth = r.frame.true_bv[r.frame.true_bv.trait == "t1"].set_index("animal_id").tbv
    gr = GateRunner(registry=reg, evaluator=ev, splits=splits, thresholds=load_thresholds(), campaign_id="c1",
                    snapshot_id="snap", known_priors=set(r.priors), truth=truth, seed=1)
    return reg, gr


def _candidate(reg, dsl):
    pid = reg.add_proposal(campaign_id="c1", agent_model="stub", mechanism_text="m", mechanism_cluster="x", direction="d",
                           falsifiers=[], expected_gain={}, novelty_hash=dsl, source_refs=[])
    return reg.add_candidate(proposal_id=pid, dsl_text=dsl, dsl_hash="h", code_hash="c", data_decl_hash="d")


def test_stats_helpers():
    assert expected_max_z(1) == 0.0 and expected_max_z(10) > expected_max_z(2) > 0
    rng = np.random.default_rng(0)
    t = rng.normal(size=300); c = t + rng.normal(size=300); h = rng.normal(size=300)
    res = paired_bootstrap_delta([(c, h, t)], 200, 0.9, 0)
    assert res["delta"] > 0.5 and res["ci_low"] > 0.3


def test_state_machine_only_moves_through_gates(harness):
    reg, gr = harness
    cid = _candidate(reg, "champion() + covariate(field='sex')")
    assert gr.apply_review(cid, "PASS", "hypothesis", "ok") == "reviewed"
    assert gr.mark_implemented(cid, "built") == "implemented"
    assert gr.apply_review(cid, "RETURN", "code", "fix units") == "reviewed"
    gr.mark_implemented(cid, "rebuilt")
    v = gr.run_validity(cid, "champion() + covariate(field='sex')", [{"field": "animals.sex", "available_at": "birth"},
                                                                     {"field": "genotypes", "available_at": "birth"}])
    assert v.passed and v.state == "validated"
    with pytest.raises(ValueError):
        gr.run_full(_candidate(reg, "champion()"), gr.champ_spec)   # not validated
    full = gr.run_full(cid, v.stats["spec"])
    assert full.state in ("promoted", "rejected")
    gates_seen = {r["gate"] for r in full.gates}
    assert gates_seen == {"accuracy", "incremental", "plan", "robustness", "research"}
    hist = reg.df("SELECT to_state FROM candidate_transitions WHERE candidate_id=? ORDER BY transition_id", (cid,)).to_state.tolist()
    assert hist[:5] == ["registered", "reviewed", "implemented", "reviewed", "implemented"] and hist[-2] == "evaluated"
    assert reg.df("SELECT * FROM evaluations").shape[0] == 1


def test_validity_rejects_leaky_declaration_and_duplicates(harness):
    reg, gr = harness
    cid = _candidate(reg, "champion() + covariate(field='farm')")
    gr.apply_review(cid, "PASS", "hypothesis", "ok"); gr.mark_implemented(cid, "b")
    v = gr.run_validity(cid, "champion() + covariate(field='farm')",
                        [{"field": "animals.farm", "available_at": "after_selection"}, {"field": "genotypes", "available_at": "birth"}])
    assert not v.passed and v.state == "rejected"
    cid2 = _candidate(reg, "champion() + covariate(field='progeny_mean')")
    gr.apply_review(cid2, "PASS", "hypothesis", "ok"); gr.mark_implemented(cid2, "b")
    assert not gr.run_validity(cid2, "champion() + covariate(field='progeny_mean')", []).passed
    cid3 = _candidate(reg, "champion() + multi_trait(traits=['t1','t2'])")
    gr.apply_review(cid3, "PASS", "hypothesis", "ok"); gr.mark_implemented(cid3, "b")
    v3 = gr.run_validity(cid3, "champion() + multi_trait(traits=['t1','t2'])", [])
    assert not v3.passed and "NEED_OPERATOR" in v3.gates[0]["detail"]


def test_null_candidate_is_not_promoted_and_prior_can_be(harness):
    reg, gr = harness
    # random SNP subset (negative control F): must not be promoted
    dsl = "champion() + snp_subset(strategy='random', fraction=0.3, seed=3)"
    cid = _candidate(reg, dsl)
    gr.apply_review(cid, "PASS", "hypothesis", "ok"); gr.mark_implemented(cid, "b")
    v = gr.run_validity(cid, dsl, [{"field": "genotypes", "available_at": "birth"}])
    assert v.passed
    full = gr.run_full(cid, v.stats["spec"])
    assert full.state == "rejected"
    d = [r for r in full.gates if r["metric"] == "delta_oos"][0]
    assert d["ci_low"] <= 0.0
