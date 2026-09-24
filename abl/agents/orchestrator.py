"""Orchestrator (DESIGN.md P1): state, budget, role separation, semantic-hash dedup, retry limit.
It never reads holdout/, never edits thresholds, and never changes candidate state itself —
every transition goes through gates.GateRunner."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

from common import paths
from common.llm import LLM, get_llm
from common.seeds import derive_seed
from common.timeutil import utcnow_iso
from dsl import DSLError, NeedOperator, parse, semantic_hash, validate
from registry import Registry, append_event

from . import analyst, builder, critic, geneticist
from .base import AgentContext
from .stub_handlers import HANDLERS


@dataclass
class CampaignConfig:
    campaign_id: str
    customer_id: str
    species: str
    trait: str
    horizon: str
    n_proposals: int
    budget_full_evals: int
    budget_tokens: int
    seed: int = 0
    retry_limit: int = 2
    probe_every: int = 10            # every k-th proposal is a leaky negative-control probe for the Critic
    constraints: dict = field(default_factory=lambda: {"delta_f_cap": 0.01, "genotyping_budget": "equal", "generation_interval": 1.5})
    owner: str = "newco"
    sharing_tier: str = "private"
    info_gain_reserve: float = 0.3   # below this share of remaining full evals, only unseen clusters get evaluated


class Orchestrator:
    def __init__(self, cfg: CampaignConfig, registry: Registry, gates, catalog: dict, llm: LLM | None = None):
        self.cfg = cfg
        self.reg = registry
        self.gates = gates
        self.catalog = dict(catalog)
        self.catalog.setdefault("grammar_summary", "champion() + one to four of: grm_weights, region_weight, qtl_prior, covariate, blend_pedigree, dominance, snp_subset, lambda_scale (see dsl/grammar.md); multi_trait/env_covariate are reserved")
        self.catalog["constraints"] = cfg.constraints
        self.llm = llm or get_llm(stub_handlers=HANDLERS)
        self.ctx = AgentContext(self.llm, registry, cfg.campaign_id)
        self.state: dict = {"campaign_id": cfg.campaign_id, "proposals": 0, "duplicates": 0, "critic_rejects": 0,
                            "need_operator": 0, "validity_rejects": 0, "full_evaluations": 0, "promoted": 0,
                            "deferred_for_info_gain": 0, "paused": False, "budget_exhausted": False, "log": []}
        self.evaluated_clusters: dict[str, int] = {}

    # -- controls ---------------------------------------------------------------------
    def _check_control(self) -> bool:
        ok, why = paths.run_allowed()
        if not ok:
            self.state["paused"] = True
            append_event(agent="orchestrator", action="pause", campaign_id=self.cfg.campaign_id, input_obj=why, output_obj=self.state,
                         summary=f"Loop stopped: {why}", policy_flags=["paused"], registry=self.reg)
            self._write_status(why)
        return ok

    def _write_status(self, why: str) -> None:
        p = paths.registry_dir() / f"status_{self.cfg.campaign_id}.json"
        p.write_text(json.dumps({"ts": utcnow_iso(), "reason": why, "state": self.state}, indent=1, default=str))

    def _budget_ok(self, need_full_eval: bool) -> bool:
        if self.ctx.tokens_used > self.cfg.budget_tokens:
            self._flag_budget("tokens", overrun=True)
            return False
        if need_full_eval and self.gates.n_full_evaluations >= self.cfg.budget_full_evals:
            self._flag_budget("full_evaluations", overrun=self.gates.n_full_evaluations > self.cfg.budget_full_evals)
            return False
        return True

    def _flag_budget(self, what: str, overrun: bool = False) -> None:
        """Reaching the planned budget is normal and logged without a policy flag; only a genuine
        overrun (tokens above cap, or more full evaluations than allowed) raises budget_exceeded."""
        if not self.state["budget_exhausted"]:
            self.state["budget_exhausted"] = True
            append_event(agent="orchestrator", action="budget", campaign_id=self.cfg.campaign_id, input_obj=what,
                         output_obj={"tokens": self.ctx.tokens_used, "full_evals": self.gates.n_full_evaluations, "overrun": overrun},
                         summary=(f"Budget OVERRUN: {what}" if overrun else f"Budget reached as planned: {what}"),
                         policy_flags=["budget_exceeded"] if overrun else [], registry=self.reg)

    def _log(self, msg: str) -> None:
        self.state["log"].append(msg)

    # -- the loop --------------------------------------------------------------------
    def run(self) -> dict:
        t0 = time.perf_counter()
        for i in range(self.cfg.n_proposals):
            if not self._check_control():
                break
            if not self._budget_ok(need_full_eval=False):
                break
            self.step(i)
        self.state["seconds"] = round(time.perf_counter() - t0, 1)
        self.state["tokens"] = self.ctx.tokens_used
        self.state["cost_usd"] = round(self.ctx.cost_usd, 4)
        self.state["agent_calls"] = self.ctx.calls
        self.reg.add_cost(campaign_id=self.cfg.campaign_id, customer_id=self.cfg.customer_id, period="campaign",
                          tokens=self.ctx.tokens_used, cash_cost=self.ctx.cost_usd,
                          compute_seconds=float(self.reg.one("SELECT COALESCE(SUM(compute_seconds),0) FROM evaluations e JOIN candidates c ON c.candidate_id=e.candidate_id JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=?", (self.cfg.campaign_id,))[0]))
        self.reg.end_campaign(self.cfg.campaign_id)
        append_event(agent="orchestrator", action="end", campaign_id=self.cfg.campaign_id, input_obj=asdict(self.cfg),
                     output_obj={k: v for k, v in self.state.items() if k != "log"}, summary="Campaign ended", registry=self.reg)
        return {k: v for k, v in self.state.items() if k != "log"}

    def step(self, i: int) -> None:
        cid_camp = self.cfg.campaign_id
        seed = derive_seed(cid_camp, i, base=self.cfg.seed)
        summary = self.reg.summary(cid_camp)
        brief = {"species": self.cfg.species, "trait": self.cfg.trait, "horizon": self.cfg.horizon,
                 "target": "next-generation adjusted phenotype (proxy for DEBV)", "constraints": self.cfg.constraints}
        probe = {"kind": "negative_control_leak"} if (self.cfg.probe_every and (i + 1) % self.cfg.probe_every == 0) else None
        # HYPOTHESIZE
        hyp = geneticist.propose(self.ctx, brief=brief, registry_summary=summary, catalog=self.catalog, seed=seed, probe=probe)
        self.state["proposals"] += 1
        plan = str(hyp.get("operator_plan", ""))
        try:
            prog = validate(parse(plan), known_priors=set(self.catalog.get("priors", [])), has_pedigree=self.catalog.get("has_pedigree", True))
            novelty = semantic_hash(prog)
        except NeedOperator:
            novelty = "reserved:" + plan
        except DSLError as e:
            novelty = "invalid:" + plan
            self._log(f"#{i} invalid plan: {e}")
        if not probe and self.reg.novelty_hash_exists(novelty, cid_camp):
            self.state["duplicates"] += 1
            append_event(agent="orchestrator", action="dedup", campaign_id=cid_camp, input_obj=plan, output_obj=novelty,
                         summary=f"Duplicate hypothesis skipped (semantic hash exists): {plan[:80]}", registry=self.reg)
            return
        pid = self.reg.add_proposal(campaign_id=cid_camp, agent_model=self.llm.model, mechanism_text=str(hyp.get("mechanism", "")),
                                    mechanism_cluster=str(hyp.get("mechanism_cluster", "unknown")), direction=str(hyp.get("direction", "")),
                                    falsifiers=list(hyp.get("falsifiers", [])), expected_gain=dict(hyp.get("expected_gain", {})),
                                    novelty_hash=novelty, source_refs=list(hyp.get("source_refs", [])), owner=self.cfg.owner,
                                    sharing_tier=self.cfg.sharing_tier)
        cand = self.reg.add_candidate(proposal_id=pid, dsl_text=plan, dsl_hash=novelty, code_hash="", data_decl_hash="")
        # REVIEW (Critic, before any code)
        rv = critic.review(self.ctx, hypothesis=hyp, build=None, stage="hypothesis", catalog=self.catalog, candidate_id=cand, seed=seed)
        self.reg.add_review(candidate_id=cand, verdict=rv["verdict_short"], leak_type=list(rv.get("leak_type", [])),
                            evidence=list(rv.get("evidence", [])))
        st = self.gates.apply_review(cand, rv["verdict_short"], "hypothesis", str(rv.get("rationale", "")))
        if st == "rejected":
            self.state["critic_rejects"] += 1
            return
        # IMPLEMENT → REVIEW(code) with retry limit
        feedback = None
        for attempt in range(self.cfg.retry_limit + 1):
            bd = builder.build(self.ctx, hypothesis=hyp, catalog=self.catalog, candidate_id=cand, seed=seed + attempt, feedback=feedback)
            if bd.get("status") != "OK":
                self.state["need_operator"] += 1
                self.gates.reject(cand, "builder", f"NEED_OPERATOR: {str(bd.get('operator_spec'))[:200]}")
                return
            dsl_text = str(bd.get("dsl", ""))
            try:
                canon = validate(parse(dsl_text), known_priors=set(self.catalog.get("priors", [])), has_pedigree=self.catalog.get("has_pedigree", True)).canonical()
            except DSLError:
                canon = dsl_text
            if canon != plan:
                new = self.reg.add_candidate(proposal_id=pid, dsl_text=canon, dsl_hash=novelty, code_hash=canon, data_decl_hash="", supersedes=cand,
                                             retry_count=attempt)
                self.gates.reject(cand, "registry", f"superseded by {new} after build")
                self.gates.apply_review(new, "PASS", "hypothesis", f"inherited hypothesis review from {cand}")
                cand = new
            self.gates.mark_implemented(cand, f"build attempt {attempt}: {bd.get('thesis_to_code', '')[:120]}")
            rv = critic.review(self.ctx, hypothesis=hyp, build=bd, stage="code", catalog=self.catalog, candidate_id=cand, seed=seed + attempt)
            self.reg.add_review(candidate_id=cand, verdict=rv["verdict_short"], leak_type=list(rv.get("leak_type", [])),
                                evidence=list(rv.get("evidence", [])))
            st = self.gates.apply_review(cand, rv["verdict_short"], "code", str(rv.get("rationale", "")))
            if st == "rejected":
                self.state["critic_rejects"] += 1
                return
            if st == "implemented":
                break
            feedback = {"verdict": rv.get("verdict"), "evidence": rv.get("evidence"), "rationale": rv.get("rationale")}
            if self.reg.bump_retry(cand) > self.cfg.retry_limit:
                append_event(agent="orchestrator", action="retry_limit", campaign_id=cid_camp, candidate_id=cand, input_obj=feedback, output_obj={},
                             summary=f"Retry limit reached for {cand}", policy_flags=["retry_limit"], registry=self.reg)
                self.gates.reject(cand, "orchestrator", "retry limit exceeded after Critic RETURN")
                return
        else:
            self.gates.reject(cand, "orchestrator", "retry limit exceeded")
            return
        # VALIDATE (cheap screens)
        v = self.gates.run_validity(cand, dsl_text, list(bd.get("data_declaration", [])))
        if not v.passed:
            self.state["validity_rejects"] += 1
            return
        # EVALUATE (expensive; budget + information gain)
        cluster = str(hyp.get("mechanism_cluster", "unknown"))
        remaining = self.cfg.budget_full_evals - self.gates.n_full_evaluations
        if remaining <= 0:
            self._flag_budget("full_evaluations", overrun=remaining < 0)
            append_event(agent="orchestrator", action="defer", campaign_id=cid_camp, candidate_id=cand, input_obj=cluster, output_obj={},
                         summary=f"{cand} validated but no full-evaluation budget left", registry=self.reg)
            return
        if remaining / max(1, self.cfg.budget_full_evals) < self.cfg.info_gain_reserve and self.evaluated_clusters.get(cluster, 0) >= 1:
            self.state["deferred_for_info_gain"] += 1
            append_event(agent="orchestrator", action="defer", campaign_id=cid_camp, candidate_id=cand, input_obj=cluster, output_obj={},
                         summary=f"{cand} deferred: cluster '{cluster}' already evaluated and budget is in the reserve zone", registry=self.reg)
            return
        full = self.gates.run_full(cand, v.stats["spec"])
        self.state["full_evaluations"] += 1
        self.evaluated_clusters[cluster] = self.evaluated_clusters.get(cluster, 0) + 1
        if full.state == "promoted":
            self.state["promoted"] += 1
        # DIAGNOSE
        an = analyst.diagnose(self.ctx, hypothesis=hyp, dsl=dsl_text, gate_rows=full.gates, stats=full.stats, state=full.state,
                              registry_summary=self.reg.summary(cid_camp), candidate_id=cand, seed=seed)
        from campaigns.package import write_package
        write_package(registry=self.reg, campaign_id=cid_camp, candidate_id=cand, hypothesis=hyp, build=bd, validity=v, full=full,
                      analysis=an, champion=self.gates.ev.champion, splits=self.gates.splits, seed=self.gates.seed,
                      thresholds_hash=self.reg.thresholds_hash_at_start(cid_camp))
