"""GateRunner — executes the gates and performs every candidate state transition."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from dsl import compile_program, parse, validate
from registry import Registry

from . import accuracy, incremental, plan, research, robustness, validity


@dataclass
class GateVerdict:
    candidate_id: str
    state: str
    passed: bool
    gates: list[dict] = field(default_factory=list)        # rows: gate, metric, value, ci_low, ci_high, threshold, passed
    stats: dict = field(default_factory=dict)
    seconds: float = 0.0


class GateRunner:
    def __init__(self, *, registry: Registry, evaluator, splits, thresholds: dict, campaign_id: str,
                 snapshot_id: str, known_priors: set[str], truth: pd.Series | None = None,
                 null_rho: dict | None = None, seed: int = 0):
        self.reg = registry
        self.ev = evaluator
        self.splits = list(splits)
        self.th = thresholds
        self.campaign_id = campaign_id
        self.snapshot_id = snapshot_id
        self.known_priors = set(known_priors)
        self.truth = truth
        self.null_rho = null_rho
        self.seed = seed
        self.champ_spec = compile_program(validate(parse("champion()")))
        self._champ_stats = None
        self.n_full_evaluations = 0

    # -- state transitions on behalf of agent recommendations ---------------------------
    def apply_review(self, candidate_id: str, verdict: str, stage: str, reason: str) -> str:
        cur = self.reg.candidate_state(candidate_id)
        if verdict == "REJECT":
            self.reg.transition(candidate_id, "rejected", gate="critic", reason=f"{stage}: {reason}")
        elif verdict == "PASS" and stage == "hypothesis" and cur == "registered":
            self.reg.transition(candidate_id, "reviewed", gate="critic", reason=f"{stage}: {reason}")
        elif verdict == "RETURN" and stage == "code" and cur == "implemented":
            self.reg.transition(candidate_id, "reviewed", gate="critic", reason=f"{stage}: returned to builder: {reason}")
        return self.reg.candidate_state(candidate_id)

    def mark_implemented(self, candidate_id: str, reason: str) -> str:
        self.reg.transition(candidate_id, "implemented", gate="builder", reason=reason)
        return "implemented"

    def reject(self, candidate_id: str, gate: str, reason: str) -> str:
        if self.reg.candidate_state(candidate_id) not in ("promoted", "rejected"):
            self.reg.transition(candidate_id, "rejected", gate=gate, reason=reason)
        return "rejected"

    # -- gate 0 -------------------------------------------------------------------------
    def run_validity(self, candidate_id: str, program_text: str, declared_fields: list[dict]) -> GateVerdict:
        t0 = time.perf_counter()
        ok, checks, spec = validity.run(program_text, declared_fields, evaluator=self.ev, splits=self.splits,
                                        registry=self.reg, thresholds=self.th, known_priors=self.known_priors,
                                        has_pedigree=self.ev.has_pedigree, snapshot_id=self.snapshot_id)
        rows = []
        for c in checks:
            self.reg.add_gate_result(candidate_id=candidate_id, gate="validity", metric=c["name"], value=1.0 if c["passed"] else 0.0,
                                     passed=c["passed"], threshold=1.0, seed=self.seed, data_snapshot_id=self.snapshot_id)
            rows.append({"gate": "validity", "metric": c["name"], "value": 1.0 if c["passed"] else 0.0,
                         "threshold": 1.0, "passed": c["passed"], "detail": c["detail"]})
        if ok:
            self.reg.transition(candidate_id, "validated", gate="validity", reason="all validity checks passed")
        else:
            failed = [c["name"] + ": " + c["detail"] for c in checks if not c["passed"]]
            self.reg.transition(candidate_id, "rejected", gate="validity", reason="; ".join(failed)[:500])
        return GateVerdict(candidate_id, self.reg.candidate_state(candidate_id), ok, rows, {"spec": spec, "checks": checks},
                           time.perf_counter() - t0)

    # -- gates 1-5 (the expensive step) -------------------------------------------------
    def champion_stats(self) -> list:
        if self._champ_stats is None:
            self._champ_stats = [self.ev.evaluate(self.champ_spec, s) for s in self.splits]
        return self._champ_stats

    def evaluate_spec(self, spec) -> list:
        return [self.ev.evaluate(spec, s) for s in self.splits]

    def run_full(self, candidate_id: str, spec) -> GateVerdict:
        t0 = time.perf_counter()
        if self.reg.candidate_state(candidate_id) != "validated":
            raise ValueError("full evaluation requires state=validated")
        champ = self.champion_stats()
        cand = self.evaluate_spec(spec)
        self.n_full_evaluations += 1
        rows: list[dict] = []

        def record(gate: str, rs: list[dict]):
            for r in rs:
                self.reg.add_gate_result(candidate_id=candidate_id, gate=gate, metric=r["metric"], value=r.get("value"),
                                         passed=bool(r["passed"]), threshold=r.get("threshold"), ci_low=r.get("ci_low"),
                                         ci_high=r.get("ci_high"), cutoff_date=",".join(str(s.cutoff_t) for s in self.splits),
                                         seed=self.seed, data_snapshot_id=self.snapshot_id)
                rows.append(dict(r, gate=gate))

        ok1, r1 = accuracy.run(cand, self.th, self.null_rho, champ); record("accuracy", r1)
        ok2, r2, inc = incremental.run(cand, champ, self.ev, self.th, self.seed, self.truth); record("incremental", r2)
        ok3, r3, pl = plan.run(cand, champ, spec, self.champ_spec, self.ev, self.th); record("plan", r3)
        ok4, r4 = robustness.run(cand, champ, spec, self.champ_spec, self.ev, self.splits, self.th, self.seed, inc["delta"]); record("robustness", r4)
        n_trials = int(self.reg.one("SELECT COUNT(*) FROM evaluations e JOIN candidates c ON c.candidate_id=e.candidate_id "
                                    "JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=?", (self.campaign_id,))[0]) + 1
        ok5, r5 = research.run(inc["delta"], inc["se"], n_trials, self.th); record("research", r5)
        n = np.array([c.n_test for c in cand], dtype=float); w = n / n.sum()
        self.reg.add_evaluation(candidate_id=candidate_id, split_id="+".join(s.split_id[:8] for s in self.splits),
                                rho=float(np.sum(w * [c.rho for c in cand])), bias=float(np.sum(w * [c.bias for c in cand])),
                                dispersion=float(np.sum(w * [c.dispersion for c in cand])), delta_oos=inc["delta"],
                                delta_oos_ci_low=inc["ci_low"], n_train=int(np.mean([c.n_train for c in cand])),
                                n_test=int(n.sum()), compute_seconds=float(sum(c.seconds for c in cand)))
        self.reg.transition(candidate_id, "evaluated", gate="evaluation", reason=f"full evaluation #{n_trials}")
        results = {"validity": True, "accuracy": ok1, "incremental": ok2, "plan": ok3, "robustness": ok4, "research": ok5}
        mandatory = self.th["promotion"]["mandatory_gates"]
        promote = all(results[g] for g in mandatory)
        if promote:
            self.reg.transition(candidate_id, "promoted", gate="promotion", reason="all mandatory gates passed")
        else:
            failed = [g for g in mandatory if not results[g]]
            self.reg.transition(candidate_id, "rejected", gate="promotion", reason="failed gates: " + ", ".join(failed))
        stats = {"gate_pass": results, "delta_oos": inc["delta"], "delta_oos_ci_low": inc["ci_low"], "se": inc["se"],
                 "rho": float(np.sum(w * [c.rho for c in cand])), "dispersion": float(np.sum(w * [c.dispersion for c in cand])),
                 "bias": float(np.sum(w * [c.bias for c in cand])), "predictive_r": float(np.sum(w * [c.extra["predictive_r"] for c in cand])),
                 "champion_predictive_r": float(np.sum(w * [c.extra["predictive_r"] for c in champ])),
                 "plan": pl, "n_trials": n_trials, "n_test": int(n.sum())}
        if self.truth is not None:
            stats["true_accuracy"] = float(np.mean([np.corrcoef(c.u_partial.to_numpy(), self.truth.loc[c.u_partial.index].to_numpy())[0, 1] for c in cand]))
            stats["champion_true_accuracy"] = float(np.mean([np.corrcoef(c.u_partial.to_numpy(), self.truth.loc[c.u_partial.index].to_numpy())[0, 1] for c in champ]))
        return GateVerdict(candidate_id, self.reg.candidate_state(candidate_id), promote, rows, stats, time.perf_counter() - t0)
