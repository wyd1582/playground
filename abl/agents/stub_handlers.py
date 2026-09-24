"""Deterministic, offline stand-ins for the four LLM roles (StubLLM handlers).

They exist so the whole harness — dedup, budget, retries, gates, registry, dashboard — runs and is
tested without network access. They are intentionally simple: a hypothesis bank for the Geneticist,
a rule-based Critic, a template Analyst. With ``ABL_LLM=anthropic`` the real prompts P1–P5 are used.
"""
from __future__ import annotations

import json
import re

from dsl import DSLError, NeedOperator, parse, validate

LEAK_WORDS = ("progeny", "offspring phenotype", "after selection", "future phenotype", "post-selection",
              "next generation's phenotype", "next-generation phenotype", "later-recorded", "selection_date+1")

BANK: list[dict] = [
    dict(cluster="prior_weighting", plan="champion() + qtl_prior(source='{prior}', weight=2.0)",
         mechanism="Published QTL/eQTL neighbourhoods carry a disproportionate share of additive variance; up-weighting markers inside them sharpens the genomic relationship for the trait.",
         direction="Animals carrying favourable alleles in prior regions move up; animals whose similarity to top families rests on non-prior regions move down.",
         falsifiers=["paired ΔOOS ≤ 0 with CI covering 0", "dispersion b drifts below 1 (over-dispersion from concentrated weights)"],
         gain=dict(delta_oos=0.02, dispersion_b=0.98), refs=["FarmGTEx 2024 (PigGTEx)", "Animal QTLdb"]),
    dict(cluster="maf_weighting", plan="champion() + grm_weights(scheme='maf_inverse')",
         mechanism="Under a model where rarer alleles have larger per-allele effects, weighting markers by 1/(2pq) equalises their variance contribution (VanRaden method 2).",
         direction="Carriers of rare alleles shared with elite ancestors move up.", falsifiers=["ΔOOS ≤ 0", "no change in ranking of the top decile"],
         gain=dict(delta_oos=0.01, dispersion_b=1.0), refs=["VanRaden 2008"]),
    dict(cluster="maf_weighting", plan="champion() + grm_weights(scheme='maf_power', power=-0.5)",
         mechanism="A softer MAF power weight (α=-0.5) between VanRaden methods 1 and 2 trades noise from rare markers against their information.",
         direction="Same as 1/(2pq) weighting but attenuated.", falsifiers=["ΔOOS ≤ 0"], gain=dict(delta_oos=0.005, dispersion_b=1.0), refs=["Speed et al. 2012 (LDAK α)"]),
    dict(cluster="dominance", plan="champion() + dominance(w=0.2)",
         mechanism="Heterozygote advantage at hidden loci adds a dominance component to phenotypes; a dominance relationship term absorbs it so the additive ranking is cleaner.",
         direction="Highly heterozygous animals stop being over-ranked for additive merit.", falsifiers=["ΔOOS ≤ 0", "dominance variance estimate ~0"],
         gain=dict(delta_oos=0.01, dispersion_b=1.0), refs=["Vitezica et al. 2013"]),
    dict(cluster="pedigree_blend", plan="champion() + blend_pedigree(w=0.3)",
         mechanism="A sparse panel misses polygenic background that the numerator relationship still captures; stronger G–A blending (ssGBLUP-style) recovers it.",
         direction="Animals from well-recorded families with few genotyped relatives move toward pedigree expectation.",
         falsifiers=["ΔOOS ≤ 0", "accuracy gain confined to one line"], gain=dict(delta_oos=0.01, dispersion_b=1.02), refs=["Legarra et al. 2009 (H matrix)"]),
    dict(cluster="fixed_effects", plan="champion() + covariate(field='sex')",
         mechanism="Sex dimorphism in the trait inflates within-family residuals; fitting sex as a fixed effect removes a systematic component from the labels.",
         direction="Whichever sex is phenotypically favoured stops being over-ranked.", falsifiers=["ΔOOS ≤ 0", "sex effect estimate ≈ 0"],
         gain=dict(delta_oos=0.005, dispersion_b=1.0), refs=["standard contemporary-group modelling"]),
    dict(cluster="shrinkage", plan="champion() + lambda_scale(factor=0.5)",
         mechanism="REML on a purged forward split under-estimates h2 (Bulmer effect after selection); halving λ reduces over-shrinkage of young candidates.",
         direction="Young animals with strong genomic evidence move further from the mean.", falsifiers=["dispersion b < 1 (over-dispersion)", "ΔOOS ≤ 0"],
         gain=dict(delta_oos=0.005, dispersion_b=0.9), refs=["Legarra & Reverter 2018"]),
    dict(cluster="shrinkage", plan="champion() + lambda_scale(factor=2.0)",
         mechanism="Doubling λ regularises more strongly against noisy relatives in small purged training sets.",
         direction="Rankings compress toward family means.", falsifiers=["dispersion b > 1", "ΔOOS ≤ 0"],
         gain=dict(delta_oos=0.0, dispersion_b=1.1), refs=["ridge regression theory"]),
    dict(cluster="panel_reduction", plan="champion() + snp_subset(strategy='top_maf', fraction=0.5)",
         mechanism="Low-MAF markers add estimation noise to G; keeping only the most informative half loses little signal and reduces noise.",
         direction="Minimal reordering; better-calibrated dispersion.", falsifiers=["ΔOOS < 0"], gain=dict(delta_oos=0.0, dispersion_b=1.0), refs=["panel design literature"]),
    dict(cluster="prior_subset", plan="champion() + snp_subset(strategy='prior_list', fraction=0.3, source='{prior}')",
         mechanism="Restricting the relationship to prior regions tests whether the prior alone carries the signal (a stricter version of prior weighting).",
         direction="Ranking driven only by prior regions.", falsifiers=["ΔOOS < 0 (prior too sparse)"], gain=dict(delta_oos=-0.02, dispersion_b=0.9), refs=["Animal QTLdb"]),
    dict(cluster="region_weighting", plan="champion() + region_weight(chrom=1, weight=3.0)",
         mechanism="Chromosome 1 hosts the largest declared QTL cluster for this trait; a region weight concentrates relationship there.",
         direction="Animals sharing chromosome-1 haplotypes with elite sires move up.", falsifiers=["ΔOOS ≤ 0", "gain vanishes when chromosome is changed"],
         gain=dict(delta_oos=0.005, dispersion_b=0.97), refs=["Animal QTLdb chr summaries"]),
    dict(cluster="multi_trait", plan="champion() + multi_trait(traits=['t1', 't2'])",
         mechanism="A genetically correlated secondary trait recorded at the same time adds information on the target trait's breeding values.",
         direction="Animals with strong correlated-trait records move accordingly.", falsifiers=["ΔOOS ≤ 0 when the secondary trait is permuted"],
         gain=dict(delta_oos=0.02, dispersion_b=1.0), refs=["multi-trait BLUP (Henderson & Quaas 1976)"]),
    dict(cluster="gxe", plan="champion() + env_covariate(field='farm_climate')",
         mechanism="Genotype-by-environment interaction across farms means one ranking does not fit all sites; an environmental covariate lets the model re-rank per site.",
         direction="Farm-specific reordering.", falsifiers=["no farm-specific ΔOOS pattern"], gain=dict(delta_oos=0.01, dispersion_b=1.0), refs=["G2F multi-environment trials"]),
    dict(cluster="prior_weighting", plan="champion() + qtl_prior(source='{prior}', weight=2.0) + dominance(w=0.15)",
         mechanism="Prior-region weighting and a dominance term address different variance components and may stack.",
         direction="As for the two components.", falsifiers=["stacked ΔOOS not larger than either alone"], gain=dict(delta_oos=0.02, dispersion_b=0.98),
         refs=["FarmGTEx 2024", "Vitezica et al. 2013"]),
]

PROBES: list[dict] = [
    dict(cluster="negative_control_leak", plan="champion() + covariate(field='progeny_mean')",
         mechanism="The mean phenotype of an animal's progeny is a direct estimate of its breeding value; include it as a covariate.",
         direction="Sires with good progeny move up.", falsifiers=["none"], gain=dict(delta_oos=0.3, dispersion_b=1.0), refs=["progeny testing"],
         leak_decl=[{"field": "animals.progeny_mean", "available_at": "after_selection", "note": "recorded one generation after selection_date"}]),
    dict(cluster="negative_control_leak", plan="champion() + lambda_scale(factor=0.8)",
         mechanism="Calibrate λ against the next generation's own phenotypes so the ranking matches later-recorded outcomes.",
         direction="Whoever performs well later moves up.", falsifiers=["none"], gain=dict(delta_oos=0.2, dispersion_b=1.0), refs=[],
         leak_decl=[{"field": "phenotypes.value", "available_at": "selection_date+1", "note": "next-generation labels used for calibration"}]),
]


def _ops(dsl: str) -> list[str]:
    try:
        return sorted(o.name for o in parse(dsl).ops if o.name != "champion")
    except DSLError:
        return []


def _fill(plan: str, catalog: dict) -> str:
    priors = catalog.get("priors", [])
    return plan.replace("{prior}", priors[0] if priors else "none")


def _vary(plan: str, k: int) -> str:
    """k-th numeric variant of a plan (what a real Geneticist does when the registry says 'tried')."""
    if k == 0:
        return plan
    def rep(m):
        v = float(m.group(0))
        return f"{v * (1 + 0.25 * k):.3g}" if "." in m.group(0) else m.group(0)
    return re.sub(r"(?<![\w'])\d+\.\d+(?![\w'])", rep, plan)


def geneticist(system: str, user: str, schema, seed: int) -> dict:
    u = json.loads(user)
    catalog = u.get("data_catalog", {})
    summary = u.get("registry_summary", {})
    if u.get("probe"):
        p = PROBES[seed % len(PROBES)]
        return dict(mechanism=p["mechanism"], direction=p["direction"], operator_plan=_fill(p["plan"], catalog),
                    falsifiers=p["falsifiers"], expected_gain=p["gain"], novelty_check="probe", source_refs=p["refs"],
                    mechanism_cluster=p["cluster"], _leak_decl=p["leak_decl"])
    counts = summary.get("mechanism_clusters", {}) or {}
    tried = set(summary.get("recent_dsl", []) or [])
    has_ped = catalog.get("has_pedigree", True)
    bank = [b for b in BANK if not (b["cluster"] == "pedigree_blend" and not has_ped)]
    order = sorted(range(len(bank)), key=lambda i: (counts.get(bank[i]["cluster"], 0), (i + seed) % len(bank)))
    for k in range(0, 6):
        for i in order:
            b = bank[i]
            plan = _vary(_fill(b["plan"], catalog), k)
            try:
                canon = validate(parse(plan), known_priors=set(catalog.get("priors", [])), has_pedigree=has_ped).canonical()
            except NeedOperator:
                canon = plan
            except DSLError:
                continue
            if canon in tried:
                continue
            return dict(mechanism=b["mechanism"], direction=b["direction"], operator_plan=plan, falsifiers=b["falsifiers"],
                        expected_gain=b["gain"], source_refs=b["refs"], mechanism_cluster=b["cluster"],
                        novelty_check=f"nearest registry cluster '{b['cluster']}' seen {counts.get(b['cluster'], 0)}x; variant {k}")
    b = bank[seed % len(bank)]
    return dict(mechanism=b["mechanism"], direction=b["direction"], operator_plan=_fill(b["plan"], catalog), falsifiers=b["falsifiers"],
                expected_gain=b["gain"], source_refs=b["refs"], mechanism_cluster=b["cluster"], novelty_check="bank exhausted; repeat")


def builder(system: str, user: str, schema, seed: int) -> dict:
    u = json.loads(user)
    h = u["hypothesis"]
    plan = h["operator_plan"]
    catalog = u.get("data_catalog", {})
    try:
        prog = validate(parse(plan), known_priors=set(catalog.get("priors", [])), has_pedigree=catalog.get("has_pedigree", True))
    except NeedOperator as e:
        return dict(status="NEED_OPERATOR", dsl=plan, data_declaration=[], tests=[], thesis_to_code="",
                    operator_spec=f"minimal spec: {e}; needs a second phenotype/environment table joined on animal_id with its own available_at")
    except DSLError as e:
        return dict(status="NEED_OPERATOR", dsl=plan, data_declaration=[], tests=[], thesis_to_code="", operator_spec=f"grammar violation: {e}")
    from dsl import data_declaration
    decl = data_declaration(prog)
    if h.get("_leak_decl"):
        decl = decl + h["_leak_decl"]
    tests = [dict(name="schema", description="GenoFrame.validate() on the declared fields"),
             dict(name="causality", description="no declared field with available_at > selection_date"),
             dict(name="replay_determinism", description="two evaluations with the same seed agree to 1e-9"),
             dict(name="edge_cases", description="singleton contemporary group, missing sire/dam, monomorphic SNPs")]
    return dict(status="OK", dsl=prog.canonical(), data_declaration=decl, tests=tests,
                thesis_to_code=f"implements mechanism: \"{h['mechanism'][:80]}\" via {', '.join(_ops(plan)) or 'champion only'}",
                operator_spec="")


def critic(system: str, user: str, schema, seed: int) -> dict:
    u = json.loads(user)
    h, b, stage = u["hypothesis"], u.get("build"), u["stage"]
    text = " ".join(str(h.get(k, "")) for k in ("mechanism", "direction", "operator_plan")).lower()
    ev, leaks = [], []
    for w in LEAK_WORDS:
        if w in text:
            leaks.append("temporal"); ev.append(dict(file="hypothesis", line="mechanism", field=w, note="uses information recorded after selection_date"))
            break
    if stage == "code" and b:
        for i, d in enumerate(b.get("data_declaration", [])):
            if d.get("available_at") not in ("birth", "label", "external") or "progeny" in d.get("field", ""):
                leaks.append("temporal"); ev.append(dict(file="data_declaration", line=str(i), field=d.get("field", "?"),
                                                         note=f"available_at={d.get('available_at')} is after selection_date"))
        if leaks:
            return dict(verdict="REJECT", leak_type=sorted(set(leaks)), evidence=ev, rationale="Temporal leakage: a declared field is only knowable after the selection date.")
        want, got = _ops(h.get("operator_plan", "")), _ops(b.get("dsl", ""))
        if want != got:
            return dict(verdict="RETURN_TO_BUILDER", leak_type=["thesis_code"], evidence=[dict(file="dsl", line="1", field="operators", note=f"hypothesis plans {want}, code implements {got}")],
                        rationale="Thesis–code mismatch: the operators do not implement the stated mechanism.")
        for o in parse(b["dsl"]).ops:
            if o.name == "lambda_scale" and not (0.34 <= float(o.get("factor")) <= 3.0):
                return dict(verdict="RETURN_TO_BUILDER", leak_type=["dispersion"], evidence=[dict(file="dsl", line="1", field="lambda_scale.factor", note=f"factor={o.get('factor')} likely inflates/deflates EBV dispersion (b≠1)")],
                            rationale="Dispersion risk: extreme λ scaling.")
            if o.name == "snp_subset" and float(o.get("fraction")) < 0.15:
                return dict(verdict="RETURN_TO_BUILDER", leak_type=["plan"], evidence=[dict(file="dsl", line="1", field="snp_subset.fraction", note="panel too sparse to support ΔF control")],
                            rationale="Plan feasibility: too few markers for reliable coancestry.")
            if o.name == "blend_pedigree" and not u.get("data_catalog", {}).get("has_pedigree", True):
                return dict(verdict="REJECT", leak_type=["structure"], evidence=[dict(file="dsl", line="1", field="blend_pedigree", note="dataset declares no pedigree")],
                            rationale="Structure: no pedigree available; blending would fit line/farm structure instead.")
        return dict(verdict="PASS", leak_type=[], evidence=[], rationale="No temporal, relatedness or structural leak found; operators implement the stated mechanism; dispersion risk acceptable.")
    if leaks:
        return dict(verdict="REJECT", leak_type=["temporal"], evidence=ev, rationale="The mechanism as stated requires phenotypes recorded after selection_date.")
    return dict(verdict="PASS", leak_type=[], evidence=[], rationale="Hypothesis is falsifiable and uses only information available at selection_date.")


def analyst(system: str, user: str, schema, seed: int) -> dict:
    u = json.loads(user)
    rows, stats, state = u.get("gate_results", []), u.get("stats", {}), u.get("disposition")
    order = ["validity", "accuracy", "incremental", "plan", "robustness", "research"]
    failed = [g for g in order if any(r["gate"] == g and not r["passed"] and not r.get("diagnostic") for r in rows)]
    limiting = failed[0] if failed else "none"
    d = stats.get("delta_oos"); lo = stats.get("delta_oos_ci_low")
    reasons = {
        "accuracy": "the LR statistics did not clear the null-calibrated line (rho below the shuffled-label null + 1 sd, or dispersion CI excluding 1)",
        "incremental": f"paired ΔOOS = {d:+.3f} with 90% lower bound {lo:+.3f}: the operator adds no information beyond the frozen champion" if d is not None else "no incremental gain",
        "plan": "at equal genotyping cost the ranking would breach the ΔF cap or deliver less gain/yr than the champion",
        "robustness": "the gain is carried by a single farm/line/year or vanishes when the largest sire family is dropped",
        "research": "after deflating for the number of trials in this campaign the gain is consistent with the expected maximum of null trials",
        "none": f"all mandatory gates passed; paired ΔOOS = {d:+.3f} (lower bound {lo:+.3f})" if d is not None else "all gates passed",
    }
    summary = (f"Candidate {u.get('candidate_id')} was {state}. " + (f"Limiting gate: {limiting} — " if limiting != "none" else "") + reasons[limiting] + ".")
    clusters = (u.get("registry_summary", {}) or {}).get("mechanism_clusters", {}) or {}
    untried = [b for b in BANK if b["cluster"] not in clusters and b["cluster"] not in ("multi_trait", "gxe")]
    nxt = untried[seed % len(untried)] if untried else BANK[seed % len(BANK)]
    return dict(disposition_summary=summary, diagnosis=reasons[limiting], limiting_gate=limiting,
                next_experiment=dict(mechanism=nxt["mechanism"], dsl=nxt["plan"].replace("{prior}", "<prior>"),
                                     rationale=f"cluster '{nxt['cluster']}' is absent from the registry: highest expected information gain"),
                evaluation_section="\n".join(f"- {r['gate']}/{r['metric']}: {r.get('value')!s:.8} (threshold {r.get('threshold')}) → {'pass' if r['passed'] else 'FAIL'}" for r in rows),
                mechanism_cluster=u.get("hypothesis", {}).get("mechanism_cluster", "unknown"))


HANDLERS = {"geneticist": geneticist, "builder": builder, "critic": critic, "analyst": analyst}
