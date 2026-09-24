"""Gate 3 — plan: at equal genotyping cost the candidate's ranking must not breach the ΔF cap and must
deliver at least the champion's gain/yr (OCS-style rule, DESIGN.md §3.3)."""
from __future__ import annotations

import numpy as np

from engine.plan import plan_metrics


def run(cand_stats, champ_stats, cand_spec, champ_spec, evaluator, thresholds: dict) -> tuple[bool, list[dict], dict]:
    th = thresholds["plan"]
    sigma_a = float(np.sqrt(max(evaluator.champion.h2, 1e-6)))
    Kc = evaluator.relationship(cand_spec)
    Kh = evaluator.relationship(champ_spec)
    out = {"cand": [], "champ": []}
    for c, h in zip(cand_stats, champ_stats):
        out["cand"].append(plan_metrics(c.u_partial, Kc, evaluator.ids, selected_fraction=float(th["selected_fraction"]),
                                        accuracy=max(c.extra["predictive_r"], 0.0) / sigma_a, sigma_a=sigma_a,
                                        generation_interval_years=float(th["generation_interval_years"])))
        out["champ"].append(plan_metrics(h.u_partial, Kh, evaluator.ids, selected_fraction=float(th["selected_fraction"]),
                                         accuracy=max(h.extra["predictive_r"], 0.0) / sigma_a, sigma_a=sigma_a,
                                         generation_interval_years=float(th["generation_interval_years"])))
    df = float(np.mean([m["delta_f"] for m in out["cand"]]))
    gc = float(np.mean([m["gain_per_year"] for m in out["cand"]]))
    gh = float(np.mean([m["gain_per_year"] for m in out["champ"]]))
    ratio = gc / gh if gh > 0 else (1.0 if gc >= gh else 0.0)
    rows = [{"metric": "delta_f", "value": df, "threshold": float(th["delta_f_cap"]), "passed": df <= float(th["delta_f_cap"])},
            {"metric": "gain_per_year_ratio", "value": ratio, "threshold": float(th["min_gain_ratio"]),
             "passed": ratio >= float(th["min_gain_ratio"])},
            {"metric": "gain_per_year", "value": gc, "threshold": gh, "passed": True, "diagnostic": True}]
    return all(r["passed"] for r in rows if not r.get("diagnostic")), rows, {"cand_gain": gc, "champ_gain": gh, "delta_f": df}
