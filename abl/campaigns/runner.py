"""Campaign runner: arms A–F of DESIGN.md P6 on one dataset.

A champion · B random-operator search · C one-shot LLM · D full ABL loop ·
E shuffled-label negative control (loop on shuffled data) · F random-SNP negative control.
Thresholds are read once at start and never edited; the holdout stays sealed until final_table.py.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import numpy as np

from agents import CampaignConfig, Orchestrator
from agents.base import AgentContext
from agents.stub_handlers import HANDLERS
from agents import builder as builder_agent, geneticist as geneticist_agent
from common import paths
from common.llm import get_llm
from common.seeds import derive_seed
from common.timeutil import utcnow_iso
from dsl import DSLError, compile_program, parse, random_program, validate
from engine import Evaluator, freeze_champion
from gates import GateRunner, load_thresholds
from genoframe import GenoFrame, forward_splits
from registry import Registry, append_event

from .controls import null_rho, shuffled_frame


@dataclass
class DatasetBundle:
    name: str                       # e.g. "sim" / "pig_cleveland"
    frame: GenoFrame                # development frame (holdout already split off), may carry true_bv
    priors: dict = field(default_factory=dict)
    trait: str = "t1"
    species: str = "sim_pig"
    customer_id: str = "public"
    champion_covariates: list[str] = field(default_factory=list)
    champion_blend_w: float = 0.0
    min_train_t: int | None = None
    owner: str = "public"
    sharing_tier: str = "public"


def _truth(frame: GenoFrame, trait: str):
    if frame.true_bv is None:
        return None
    return frame.true_bv[frame.true_bv.trait == trait].set_index("animal_id").tbv


def _stats_row(ev: Evaluator, spec, splits, truth):
    st = [ev.evaluate(spec, s) for s in splits]
    n = np.array([x.n_test for x in st], dtype=float); w = n / n.sum()
    row = {"lr_rho": float(np.sum(w * [x.rho for x in st])), "dispersion_b": float(np.sum(w * [x.dispersion for x in st])),
           "bias": float(np.sum(w * [x.bias for x in st])), "predictive_r": float(np.sum(w * [x.extra["predictive_r"] for x in st])),
           "n_test": int(n.sum()), "seconds": float(sum(x.seconds for x in st))}
    if truth is not None:
        row["true_accuracy"] = float(np.mean([np.corrcoef(x.u_partial.to_numpy(), truth.loc[x.u_partial.index].to_numpy())[0, 1] for x in st]))
    return row


class Campaign:
    def __init__(self, bundle: DatasetBundle, *, registry: Registry | None = None, seed: int = 0,
                 n_proposals: int = 100, budget_full_evals: int = 12, budget_tokens: int = 2_000_000,
                 llm=None, probe_every: int = 10):
        self.b = bundle
        self.reg = registry or Registry()
        self.seed = seed
        self.n_proposals = n_proposals
        self.budget_full_evals = budget_full_evals
        self.budget_tokens = budget_tokens
        self.llm = llm or get_llm(stub_handlers=HANDLERS)
        self.probe_every = probe_every
        self.th = load_thresholds()
        pub = bundle.frame.public_view()
        self.pub = pub
        self.truth = _truth(bundle.frame, bundle.trait)
        self.splits = forward_splits(pub, bundle.trait, min_train_t=bundle.min_train_t)
        if not self.splits:
            raise ValueError("no forward-in-time split available")
        self.ev = Evaluator(pub, bundle.priors, bundle.trait)
        self.champion = freeze_champion(self.ev, self.splits[-1], blend_w=bundle.champion_blend_w, covariates=bundle.champion_covariates)
        self.champ_spec = compile_program(validate(parse("champion()")))
        self.snapshot_id = self.reg.add_snapshot(customer_id=bundle.customer_id, genotype_source=pub.genotype_source,
                                                 genotype_build=pub.versions.get("genotype_build", "?"), pedigree_version=pub.versions.get("pedigree_snapshot", "?"),
                                                 phenotype_version=pub.versions.get("phenotype_snapshot", "?"), n_animals=pub.n_animals,
                                                 n_markers=pub.n_markers, cutoff_date=str(self.splits[-1].cutoff_t), owner=bundle.owner,
                                                 sharing_tier=bundle.sharing_tier, deidentified=1)
        self.null = null_rho(pub, bundle.priors, bundle.trait, self.champion, self.champ_spec, self.splits)
        self.catalog = {"priors": sorted(bundle.priors), "has_pedigree": bool(self.ev.has_pedigree), "species": bundle.species,
                        "trait": bundle.trait, "fields": ["animals.farm", "animals.line", "animals.sex", "animals.birth_t", "genotypes", "phenotypes.value"],
                        "n_animals": pub.n_animals, "n_markers": pub.n_markers, "cutoffs": [s.cutoff_t for s in self.splits],
                        "champion": self.champion.as_dict(), "null_rho": self.null, "dataset": bundle.name,
                        "calendar_source": pub.meta.get("calendar_source"), "map_source": pub.markers.map_source}
        self.results: dict = {"dataset": bundle.name, "started_at": utcnow_iso(), "champion": self.champion.as_dict(),
                              "null": self.null, "splits": [{"cutoff": s.cutoff_t, "n_train": len(s.train_ids), "n_test": len(s.test_ids), "purged": len(s.purged_ids)} for s in self.splits],
                              "arms": {}}

    # -- helpers -----------------------------------------------------------------------
    def _campaign_id(self, arm: str) -> str:
        return f"{self.b.name}_{arm}_s{self.seed}"

    def _new_registry_campaign(self, arm: str, n_prop: int, n_eval: int) -> str:
        cid = self._campaign_id(arm)
        self.reg.add_campaign(campaign_id=cid, customer_id=self.b.customer_id, species=self.b.species, trait_set=[self.b.trait],
                              horizon="next_generation", champion_id=self.champion.champion_id, budget_full_evals=n_eval,
                              budget_tokens=self.budget_tokens, owner=self.b.owner, sharing_tier=self.b.sharing_tier)
        return cid

    def _gates(self, cid: str, ev: Evaluator | None = None, truth=None) -> GateRunner:
        return GateRunner(registry=self.reg, evaluator=ev or self.ev, splits=self.splits, thresholds=self.th, campaign_id=cid,
                          snapshot_id=self.snapshot_id, known_priors=set(self.b.priors), truth=truth if truth is not None else self.truth,
                          null_rho=self.null, seed=self.seed)

    def _run_candidate(self, gates: GateRunner, cid: str, dsl_text: str, cluster: str, mechanism: str, agent_model: str) -> dict:
        """Register → (implicit PASS review) → implement → validity → full evaluation. Used by arms B, C, F."""
        pid = self.reg.add_proposal(campaign_id=cid, agent_model=agent_model, mechanism_text=mechanism, mechanism_cluster=cluster, direction="n/a",
                                    falsifiers=[], expected_gain={}, novelty_hash=dsl_text, source_refs=[], owner=self.b.owner, sharing_tier=self.b.sharing_tier)
        cand = self.reg.add_candidate(proposal_id=pid, dsl_text=dsl_text, dsl_hash=dsl_text, code_hash=dsl_text, data_decl_hash="")
        gates.apply_review(cand, "PASS", "hypothesis", f"{cluster}: no Critic in this arm")
        gates.mark_implemented(cand, "arm build")
        try:
            prog = validate(parse(dsl_text), known_priors=set(self.b.priors), has_pedigree=self.ev.has_pedigree)
            from dsl import data_declaration
            decl = data_declaration(prog)
        except DSLError:
            decl = []
        v = gates.run_validity(cand, dsl_text, decl)
        out = {"candidate_id": cand, "dsl": dsl_text, "state": v.state, "cluster": cluster}
        if v.passed and gates.n_full_evaluations < self.budget_full_evals:
            full = gates.run_full(cand, v.stats["spec"])
            out.update(state=full.state, delta_oos=full.stats["delta_oos"], ci_low=full.stats["delta_oos_ci_low"],
                       gate_pass=full.stats["gate_pass"], true_accuracy=full.stats.get("true_accuracy"))
        return out

    # -- arms --------------------------------------------------------------------------
    def arm_A_champion(self) -> dict:
        cid = self._new_registry_campaign("A", 0, 0)
        row = _stats_row(self.ev, self.champ_spec, self.splits, self.truth)
        for k, v in row.items():
            self.reg.add_control(campaign_id=cid, arm="champion", metric=k, value=v)
        self.reg.add_control(campaign_id=cid, arm="champion", metric="gain_per_year", value=None)
        self.reg.end_campaign(cid)
        self.results["arms"]["A_champion"] = row
        return row

    def arm_B_random_ops(self, n: int | None = None, max_evals: int | None = None) -> dict:
        n = n or self.n_proposals; max_evals = max_evals or self.budget_full_evals
        cid = self._new_registry_campaign("B", n, max_evals)
        gates = self._gates(cid)
        rng = np.random.default_rng(derive_seed("armB", self.seed))
        rows, seen = [], set()
        for i in range(n):
            prog = random_program(rng, sorted(self.b.priors), has_pedigree=self.ev.has_pedigree)
            text = prog.canonical()
            if text in seen:
                continue
            seen.add(text)
            if gates.n_full_evaluations >= max_evals:
                break
            rows.append(self._run_candidate(gates, cid, text, "random_ops", "random operator draw", "random_search"))
        summ = self._summarise(rows, cid)
        for k in ("promoted", "full_evaluations", "best_delta_oos"):
            self.reg.add_control(campaign_id=cid, arm="random_ops", metric=k, value=summ.get(k))
        self.reg.end_campaign(cid)
        self.results["arms"]["B_random_ops"] = summ
        return summ

    def arm_C_one_shot(self) -> dict:
        cid = self._new_registry_campaign("C", 1, 1)
        gates = self._gates(cid)
        ctx = AgentContext(self.llm, self.reg, cid)
        brief = {"species": self.b.species, "trait": self.b.trait, "horizon": "next_generation", "target": "next-generation adjusted phenotype"}
        hyp = geneticist_agent.propose(ctx, brief=brief, registry_summary={}, catalog=self.catalog, seed=derive_seed("armC", self.seed))
        bd = builder_agent.build(ctx, hypothesis=hyp, catalog=self.catalog, candidate_id="pending", seed=derive_seed("armC", self.seed))
        rows = []
        if bd.get("status") == "OK":
            rows.append(self._run_candidate(gates, cid, str(bd["dsl"]), str(hyp.get("mechanism_cluster", "one_shot")), str(hyp.get("mechanism", "")), self.llm.model))
        summ = self._summarise(rows, cid)
        summ["tokens"] = ctx.tokens_used
        self.reg.add_cost(campaign_id=cid, customer_id=self.b.customer_id, period="campaign", tokens=ctx.tokens_used, cash_cost=ctx.cost_usd)
        for k in ("promoted", "full_evaluations", "best_delta_oos"):
            self.reg.add_control(campaign_id=cid, arm="one_shot_llm", metric=k, value=summ.get(k))
        self.reg.end_campaign(cid)
        self.results["arms"]["C_one_shot_llm"] = summ
        return summ

    def arm_D_abl_loop(self, n: int | None = None, max_evals: int | None = None) -> dict:
        n = n or self.n_proposals; max_evals = max_evals or self.budget_full_evals
        cid = self._new_registry_campaign("D", n, max_evals)
        gates = self._gates(cid)
        cfg = CampaignConfig(campaign_id=cid, customer_id=self.b.customer_id, species=self.b.species, trait=self.b.trait, horizon="next_generation",
                             n_proposals=n, budget_full_evals=max_evals, budget_tokens=self.budget_tokens, seed=self.seed, probe_every=self.probe_every,
                             owner=self.b.owner, sharing_tier=self.b.sharing_tier)
        state = Orchestrator(cfg, self.reg, gates, self.catalog, llm=self.llm).run()
        summ = self._summarise(None, cid)
        summ.update({k: state.get(k) for k in ("proposals", "duplicates", "critic_rejects", "need_operator", "validity_rejects", "deferred_for_info_gain", "tokens", "cost_usd", "agent_calls", "paused")})
        for k in ("promoted", "full_evaluations", "best_delta_oos"):
            self.reg.add_control(campaign_id=cid, arm="abl_loop", metric=k, value=summ.get(k))
        self.results["arms"]["D_abl_loop"] = summ
        return summ

    def arm_E_shuffled_labels(self, n: int = 20, max_evals: int = 4) -> dict:
        cid = self._new_registry_campaign("E", n, max_evals)
        sh = shuffled_frame(self.pub, self.b.trait, derive_seed("armE", self.seed))
        ev = Evaluator(sh, self.b.priors, self.b.trait, champion=self.champion)
        gates = self._gates(cid, ev=ev, truth=self.truth)
        cfg = CampaignConfig(campaign_id=cid, customer_id=self.b.customer_id, species=self.b.species, trait=self.b.trait, horizon="next_generation",
                             n_proposals=n, budget_full_evals=max_evals, budget_tokens=self.budget_tokens, seed=self.seed + 1, probe_every=0,
                             owner=self.b.owner, sharing_tier=self.b.sharing_tier)
        Orchestrator(cfg, self.reg, gates, dict(self.catalog, negative_control="shuffled_labels"), llm=self.llm).run()
        summ = self._summarise(None, cid)
        summ["champion_on_shuffled"] = _stats_row(ev, self.champ_spec, self.splits, self.truth)
        summ["false_promotions"] = summ["promoted"]
        for k in ("promoted", "full_evaluations", "best_delta_oos"):
            self.reg.add_control(campaign_id=cid, arm="shuffled_labels", metric=k, value=summ.get(k))
        self.results["arms"]["E_shuffled_labels"] = summ
        return summ

    def arm_F_random_snp(self, n: int = 5, fraction: float = 0.3) -> dict:
        cid = self._new_registry_campaign("F", n, n)
        gates = self._gates(cid)
        rows = []
        for i in range(n):
            dsl = f"champion() + snp_subset(strategy='random', fraction={fraction}, seed={derive_seed('armF', self.seed, i) % 10**6})"
            rows.append(self._run_candidate(gates, cid, dsl, "negative_control_random_snp", "random SNP subset (negative control)", "control"))
        summ = self._summarise(rows, cid)
        summ["false_promotions"] = summ["promoted"]
        for k in ("promoted", "full_evaluations", "best_delta_oos"):
            self.reg.add_control(campaign_id=cid, arm="random_snp", metric=k, value=summ.get(k))
        self.reg.end_campaign(cid)
        self.results["arms"]["F_random_snp"] = summ
        return summ

    def _summarise(self, rows, cid: str) -> dict:
        ev = self.reg.df("SELECT e.candidate_id, e.delta_oos, e.delta_oos_ci_low, e.rho, e.dispersion, c.state, c.dsl_text, p.mechanism_cluster, e.compute_seconds "
                         "FROM evaluations e JOIN candidates c ON c.candidate_id=e.candidate_id JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=?", (cid,))
        cands = self.reg.df("SELECT c.state, p.mechanism_cluster FROM candidates c JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=?", (cid,))
        out = {"campaign_id": cid, "candidates": int(len(cands)), "validated_or_beyond": int((cands.state.isin(["validated", "evaluated", "promoted"])).sum()),
               "full_evaluations": int(len(ev)), "promoted": int((ev.state == "promoted").sum()),
               "best_delta_oos": float(ev.delta_oos.max()) if len(ev) else None, "mean_delta_oos": float(ev.delta_oos.mean()) if len(ev) else None,
               "best_ci_low": float(ev.delta_oos_ci_low.max()) if len(ev) else None,
               "clusters": cands.mechanism_cluster.value_counts().to_dict(), "compute_seconds": float(ev.compute_seconds.sum()) if len(ev) else 0.0,
               "evaluated": ev[["candidate_id", "dsl_text", "mechanism_cluster", "state", "delta_oos", "delta_oos_ci_low"]].to_dict("records") if len(ev) else []}
        if rows is not None:
            out["rows"] = rows
        return out

    def run_all(self, arms: str = "ABCDEF") -> dict:
        t0 = time.perf_counter()
        if "A" in arms: self.arm_A_champion()
        if "B" in arms: self.arm_B_random_ops()
        if "C" in arms: self.arm_C_one_shot()
        if "D" in arms: self.arm_D_abl_loop()
        if "E" in arms: self.arm_E_shuffled_labels()
        if "F" in arms: self.arm_F_random_snp()
        self.results["seconds"] = round(time.perf_counter() - t0, 1)
        self.results["ended_at"] = utcnow_iso()
        out = paths.reports_dir() / f"campaign_{self.b.name}_s{self.seed}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.results, indent=1, default=str))
        return self.results
