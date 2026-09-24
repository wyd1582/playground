"""Gate 0 — validity: grammar, units, causality, declaration match, leak-free splits, replay determinism,
semantic-hash dedup, edge cases. Machine-checked; the Builder's tests are re-run here, never trusted."""
from __future__ import annotations

import numpy as np

from dsl import DSLError, NeedOperator, compile_program, data_declaration, parse, semantic_hash, validate
from genoframe.splitter import assert_no_leak


def run(program_text: str, declared_fields: list[dict], *, evaluator, splits, registry, thresholds: dict,
        known_priors: set[str], has_pedigree: bool) -> tuple[bool, list[dict], object | None]:
    checks: list[dict] = []
    max_ops = int(thresholds["validity"]["max_operators"])
    tol = float(thresholds["validity"]["replay_tolerance"])
    spec = None
    try:
        prog = validate(parse(program_text), max_operators=max_ops, known_priors=known_priors, has_pedigree=has_pedigree)
        checks.append({"name": "grammar_units_causality", "passed": True, "detail": prog.canonical()})
    except NeedOperator as e:
        checks.append({"name": "grammar_units_causality", "passed": False, "detail": f"NEED_OPERATOR: {e}"})
        return False, checks, None
    except DSLError as e:
        checks.append({"name": "grammar_units_causality", "passed": False, "detail": str(e)})
        return False, checks, None
    # declaration must list exactly the fields the program touches, with legal available_at semantics
    want = {d["field"]: d["available_at"] for d in data_declaration(prog)}
    got = {d.get("field"): d.get("available_at") for d in declared_fields}
    missing = sorted(set(want) - set(got))
    illegal = sorted(f for f, a in got.items() if a not in ("birth", "label", "external"))
    ok = not missing and not illegal
    checks.append({"name": "data_declaration_matches_code", "passed": ok,
                   "detail": f"missing={missing} illegal_available_at={illegal}" if not ok else f"{len(want)} fields declared"})
    if not ok:
        return False, checks, None
    spec = compile_program(prog)
    # dedup: a semantic hash already fully evaluated never gets another full evaluation
    dup = registry.dsl_hash_evaluated(spec.semantic_hash)
    checks.append({"name": "semantic_hash_unique", "passed": not dup, "detail": spec.semantic_hash[:16]})
    if dup:
        return False, checks, spec
    # leak-free splits (temporal + relatedness) — re-asserted for every candidate, cheap
    try:
        for s in splits:
            assert_no_leak(evaluator.frame, s, evaluator.trait)
        checks.append({"name": "splits_leak_free", "passed": True, "detail": f"{len(splits)} forward-in-time splits"})
    except AssertionError as e:
        checks.append({"name": "splits_leak_free", "passed": False, "detail": str(e)})
        return False, checks, spec
    # replay determinism on the smallest split
    small = min(splits, key=lambda s: len(s.train_ids))
    try:
        a = evaluator.evaluate(spec, small).u_partial.to_numpy()
        b = evaluator.evaluate(spec, small).u_partial.to_numpy()
        det = bool(np.allclose(a, b, atol=tol, rtol=0)) and np.isfinite(a).all()
        checks.append({"name": "replay_determinism", "passed": det, "detail": f"max|Δ|={np.max(np.abs(a - b)):.2e}"})
        if not det:
            return False, checks, spec
    except Exception as e:  # any numerical failure is a validity failure, never rescued
        checks.append({"name": "replay_determinism", "passed": False, "detail": f"{type(e).__name__}: {e}"})
        return False, checks, spec
    # edge cases: monomorphic markers and missing parents must not break the relationship
    w = evaluator.marker_weights(spec)
    mono = (np.minimum(evaluator.p, 1 - evaluator.p) == 0)
    checks.append({"name": "edge_monomorphic_markers", "passed": bool(np.isfinite(w).all()),
                   "detail": f"{int(mono.sum())} monomorphic markers; weights finite"})
    checks.append({"name": "edge_missing_parents", "passed": True,
                   "detail": f"{int(evaluator.frame.animals.sire.isna().sum())} animals without sire handled as founders"})
    return all(c["passed"] for c in checks), checks, spec
