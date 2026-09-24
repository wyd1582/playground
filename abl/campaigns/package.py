"""BreedingPackage: thesis · DSL · data declaration · tests · provenance · evaluation (DESIGN.md §2.1)."""
from __future__ import annotations

import json
from pathlib import Path

from common import paths
from common.hashing import sha256_json
from common.timeutil import utcnow_iso


def packages_dir() -> Path:
    p = paths.registry_dir() / "packages"
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_package(*, registry, campaign_id: str, candidate_id: str, hypothesis: dict, build: dict, validity, full,
                  analysis: dict, champion, splits, seed: int, thresholds_hash: str | None) -> Path:
    gates = [{k: r.get(k) for k in ("gate", "metric", "value", "ci_low", "ci_high", "threshold", "passed", "detail")} for r in (validity.gates + full.gates)]
    decl = list(build.get("data_declaration", []))
    pkg = {
        "candidate_id": candidate_id, "campaign_id": campaign_id, "created_at": utcnow_iso(),
        "thesis": {k: hypothesis.get(k) for k in ("mechanism", "direction", "falsifiers", "expected_gain", "mechanism_cluster", "source_refs", "novelty_check")},
        "dsl": {"text": build.get("dsl"), "semantic_hash": getattr(validity.stats.get("spec"), "semantic_hash", None),
                "operators": getattr(validity.stats.get("spec"), "operators", []), "thesis_to_code": build.get("thesis_to_code")},
        "data_declaration": {"fields": decl, "snapshot_id": registry.one("SELECT data_snapshot_id FROM gate_results WHERE candidate_id=? LIMIT 1", (candidate_id,))[0],
                             "hash": sha256_json(decl)[:16]},
        "tests": [{"name": c["name"], "passed": c["passed"], "detail": c["detail"]} for c in validity.stats.get("checks", [])],
        "provenance": {"code_hash": getattr(validity.stats.get("spec"), "semantic_hash", None), "data_decl_hash": sha256_json(decl)[:16],
                       "thresholds_hash": thresholds_hash, "seed": seed, "champion_id": champion.champion_id, "champion": champion.as_dict(),
                       "split_ids": [s.split_id for s in splits], "cutoffs": [s.cutoff_t for s in splits], "purge_policy": splits[0].purge_policy if splits else None,
                       "agent_model": registry.one("SELECT agent_model FROM proposals p JOIN candidates c ON c.proposal_id=p.proposal_id WHERE c.candidate_id=?", (candidate_id,))[0]},
        "evaluation": {"gates": gates, "disposition": full.state,
                       "stats": {k: v for k, v in full.stats.items() if k != "spec"},
                       "analyst_summary": analysis.get("disposition_summary"), "diagnosis": analysis.get("diagnosis"),
                       "limiting_gate": analysis.get("limiting_gate"), "next_experiment": analysis.get("next_experiment"),
                       "evaluation_section": analysis.get("evaluation_section")},
    }
    out = packages_dir() / f"{candidate_id}.json"
    out.write_text(json.dumps(pkg, indent=1, ensure_ascii=False, default=str))
    (packages_dir() / f"{candidate_id}.md").write_text(render_markdown(pkg))
    return out


def render_markdown(pkg: dict) -> str:
    t, d, e, p = pkg["thesis"], pkg["dsl"], pkg["evaluation"], pkg["provenance"]
    lines = [f"# BreedingPackage {pkg['candidate_id']} — {e['disposition'].upper()}", "",
             f"Campaign `{pkg['campaign_id']}` · created {pkg['created_at']} · agent model `{p.get('agent_model')}`", "",
             "## 1. Thesis", f"**Mechanism.** {t.get('mechanism')}", "", f"**Direction.** {t.get('direction')}", "",
             "**Falsifiers.**"] + [f"- {f}" for f in (t.get("falsifiers") or [])] + [
             "", f"**Expected gain (prior).** {t.get('expected_gain')} · cluster `{t.get('mechanism_cluster')}` · refs: {', '.join(t.get('source_refs') or []) or '—'}", "",
             "## 2. DSL", "```", str(d.get("text")), "```", f"semantic hash `{d.get('semantic_hash')}` · {d.get('thesis_to_code')}", "",
             "## 3. Data declaration", "| field | available_at | note |", "|---|---|---|"] + [
             f"| {f.get('field')} | {f.get('available_at')} | {f.get('note')} |" for f in pkg["data_declaration"]["fields"]] + [
             f"\nsnapshot `{pkg['data_declaration']['snapshot_id']}` · declaration hash `{pkg['data_declaration']['hash']}`", "",
             "## 4. Tests (re-run by the validity gate)", "| test | result | detail |", "|---|---|---|"] + [
             f"| {x['name']} | {'pass' if x['passed'] else 'FAIL'} | {x['detail']} |" for x in pkg["tests"]] + [
             "", "## 5. Provenance",
             f"- champion `{p.get('champion_id')}` ({p.get('champion', {}).get('name')}, h2={p.get('champion', {}).get('h2'):.3f}, λ={p.get('champion', {}).get('lam'):.2f}, blend={p.get('champion', {}).get('blend_w')})",
             f"- thresholds sha256 `{p.get('thresholds_hash')}` · seed {p.get('seed')} · purge policy `{p.get('purge_policy')}`",
             f"- forward-in-time cutoffs {p.get('cutoffs')} · split ids {p.get('split_ids')}", "",
             "## 6. Evaluation", "| gate | metric | value | 90% CI | threshold | result |", "|---|---|---|---|---|---|"]
    for g in e["gates"]:
        v = g.get("value"); lo, hi = g.get("ci_low"), g.get("ci_high")
        ci = f"[{lo:+.3f}, {hi:+.3f}]" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else ""
        th = g.get("threshold"); th = f"{th:.3g}" if isinstance(th, (int, float)) else (th or "")
        vv = f"{v:.4g}" if isinstance(v, (int, float)) else str(v)
        lines.append(f"| {g['gate']} | {g['metric']} | {vv} | {ci} | {th} | {'pass' if g['passed'] else 'FAIL'} |")
    s = e.get("stats", {})
    lines += ["", f"**Disposition.** {e.get('analyst_summary')}", "", f"**Diagnosis.** {e.get('diagnosis')}", "",
              f"**Next experiment.** {json.dumps(e.get('next_experiment'), ensure_ascii=False)}", ""]
    if "true_accuracy" in s:
        lines.append(f"_Simulation diagnostic (never shown to agents): true accuracy candidate {s['true_accuracy']:.3f} vs champion {s['champion_true_accuracy']:.3f}._")
    return "\n".join(lines) + "\n"
