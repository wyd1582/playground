"""System scorecard (DESIGN.md §3.4): evaluate the system, not the best single backtest."""
from __future__ import annotations

import json
import re

import pandas as pd

from common import paths
from registry import Registry


def build_scorecard(reg: Registry) -> pd.DataFrame:
    camps = reg.df("SELECT campaign_id, species, budget_full_evals, started_at, ended_at FROM campaigns")
    rows = []
    for cid in camps.campaign_id:
        props = reg.df("SELECT proposal_id, mechanism_cluster FROM proposals WHERE campaign_id=?", (cid,))
        cands = reg.df("SELECT c.candidate_id, c.state, c.dsl_hash, p.mechanism_cluster FROM candidates c JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=?", (cid,))
        ev = reg.df("SELECT e.*, p.mechanism_cluster FROM evaluations e JOIN candidates c ON c.candidate_id=e.candidate_id JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=?", (cid,))
        neg = cands[cands.mechanism_cluster.str.startswith("negative_control")]
        crit = reg.df("SELECT cr.verdict, p.mechanism_cluster FROM critic_reviews cr JOIN candidates c ON c.candidate_id=cr.candidate_id JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=?", (cid,))
        negcrit = crit[crit.mechanism_cluster.str.startswith("negative_control")]
        cost = reg.df("SELECT COALESCE(SUM(tokens),0) t, COALESCE(SUM(compute_seconds),0) s, COALESCE(SUM(cash_cost),0) c FROM costs WHERE campaign_id=?", (cid,)).iloc[0]
        n_prop = max(1, len(props))
        valid = int(cands.state.isin(["validated", "evaluated", "promoted"]).sum())
        promoted = int((cands.state == "promoted").sum())
        m = re.search(r"^(.*)_([A-F])_s\d+", cid)
        arm = m.group(2) if m else "?"
        dataset = m.group(1) if m else cid
        rows.append({
            "campaign_id": cid, "dataset": dataset, "arm": arm, "proposals": len(props),
            "valid_per_100_proposals": round(100 * valid / n_prop, 1),
            "full_evaluations": len(ev), "promoted": promoted,
            "full_evals_per_promotion": (round(len(ev) / promoted, 2) if promoted else None),
            "mean_delta_oos": (round(float(ev.delta_oos.mean()), 4) if len(ev) else None),
            "best_delta_oos": (round(float(ev.delta_oos.max()), 4) if len(ev) else None),
            "best_delta_oos_ci_low": (round(float(ev.delta_oos_ci_low.max()), 4) if len(ev) else None),
            "false_promotions_on_negative_controls": int((neg.state == "promoted").sum()) if len(neg) else (promoted if arm == "E" else 0),
            "critic_reject_rate_on_leak_probes": (round(float((negcrit.verdict == "REJECT").mean()), 2) if len(negcrit) else None),
            "mechanism_clusters": int(props.mechanism_cluster.nunique()),
            "max_cluster_share": (round(float(props.mechanism_cluster.value_counts(normalize=True).max()), 2) if len(props) else None),
            "reproducible_from_hash": (round(float(reg.df("SELECT AVG(passed) v FROM gate_results g JOIN candidates c ON c.candidate_id=g.candidate_id JOIN proposals p ON p.proposal_id=c.proposal_id WHERE p.campaign_id=? AND g.metric='replay_determinism'", (cid,)).iloc[0].v or 0), 2) if len(cands) else None),
            "tokens": int(cost.t), "compute_seconds": round(float(cost.s) + (float(ev.compute_seconds.sum()) if len(ev) else 0.0), 1),
            "cash_cost_usd": round(float(cost.c), 4),
        })
    return pd.DataFrame(rows)


def write_scorecard(reg: Registry, name: str = "scorecard") -> tuple[pd.DataFrame, str]:
    df = build_scorecard(reg)
    out = paths.reports_dir(); out.mkdir(parents=True, exist_ok=True)
    md = ["# ABL system scorecard", "", f"{len(df)} campaigns in the registry. Arms: A champion · B random ops · C one-shot LLM · D ABL loop · E shuffled labels · F random SNP.", ""]
    if len(df):
        cols = list(df.columns)
        md.append("| " + " | ".join(cols) + " |")
        md.append("|" + "---|" * len(cols))
        for _, r in df.iterrows():
            md.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.values) + " |")
    text = "\n".join(md) + "\n"
    (out / f"{name}.md").write_text(text)
    (out / f"{name}.json").write_text(json.dumps(df.to_dict("records"), indent=1, default=str))
    return df, text
