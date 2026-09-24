"""Gate 4 — robustness: no single farm/year/line may explain the paired gain, and the gain must survive
dropping the largest sire family from training (refit, paired with the champion)."""
from __future__ import annotations

import numpy as np

from .stats import paired_bootstrap_delta


def _per_group_delta(cand_stats, champ_stats, evaluator, group_col: str) -> dict[str, tuple[float, int]]:
    out: dict[str, list] = {}
    for c, h in zip(cand_stats, champ_stats):
        y = c.extra["y_adj"]
        ids = [a for a in y.index if a in c.u_partial.index]
        groups = evaluator.cov.loc[ids, group_col].astype(str)
        gk = evaluator.group_key(ids)
        uc = c.u_partial.loc[ids]; uh = h.u_partial.loc[ids]
        uc = uc - uc.groupby(gk).transform("mean"); uh = uh - uh.groupby(gk).transform("mean")
        for g in groups.unique():
            m = (groups == g).to_numpy()
            if m.sum() < 8:
                continue
            a, b, t = uc.to_numpy()[m], uh.to_numpy()[m], y.loc[ids].to_numpy()[m]
            if a.std() == 0 or b.std() == 0 or t.std() == 0:
                continue
            d = float(np.corrcoef(a, t)[0, 1] - np.corrcoef(b, t)[0, 1])
            out.setdefault(g, []).append((d, int(m.sum())))
    return {g: (float(np.average([d for d, _ in v], weights=[n for _, n in v])), int(sum(n for _, n in v))) for g, v in out.items()}


def run(cand_stats, champ_stats, cand_spec, champ_spec, evaluator, splits, thresholds: dict, seed: int,
        total_delta: float) -> tuple[bool, list[dict]]:
    th = thresholds["robustness"]
    rows: list[dict] = []
    group_cols = [c for c in ("farm", "line", "birth_t") if c in evaluator.cov.columns and evaluator.cov[c].nunique() > 1]
    for col in group_cols:
        per = _per_group_delta(cand_stats, champ_stats, evaluator, col)
        if len(per) < int(th["min_groups"]):
            continue
        contrib = {g: d * n for g, (d, n) in per.items()}
        pos_total = sum(v for v in contrib.values() if v > 0)
        share = max((v / pos_total for v in contrib.values() if v > 0), default=0.0) if pos_total > 0 else 0.0
        # only meaningful when the total gain is positive; a null gain cannot be "explained" by one group
        passed = (total_delta <= 0) or share <= float(th["max_share_explained_by_single_group"])
        rows.append({"metric": f"max_share_{col}", "value": float(share),
                     "threshold": float(th["max_share_explained_by_single_group"]), "passed": bool(passed)})
    # drop-top-family: remove the largest sire family from the training labels of every split, refit both
    fam = evaluator.frame.animals.dropna(subset=["sire"])
    if len(fam):
        top_sire = fam.sire.value_counts().index[0]
        drop = set(fam[fam.sire == top_sire].animal_id) | {top_sire}
        pairs = []
        for s in splits:
            c = evaluator.evaluate(cand_spec, s, drop_ids=drop)
            h = evaluator.evaluate(champ_spec, s, drop_ids=drop)
            y = c.extra["y_adj"]
            ids = [a for a in y.index if a in c.u_partial.index]
            gk = evaluator.group_key(ids)
            uc = c.u_partial.loc[ids]; uh = h.u_partial.loc[ids]
            uc = (uc - uc.groupby(gk).transform("mean")).to_numpy(); uh = (uh - uh.groupby(gk).transform("mean")).to_numpy()
            pairs.append((uc, uh, y.loc[ids].to_numpy()))
        res = paired_bootstrap_delta(pairs, 100, float(thresholds["incremental"]["ci_level"]), seed + 7)
        rows.append({"metric": "delta_oos_drop_top_family", "value": res["delta"], "ci_low": res["ci_low"],
                     "ci_high": res["ci_high"], "threshold": float(th["drop_top_family_min_delta"]),
                     "passed": res["delta"] >= float(th["drop_top_family_min_delta"])})
    return all(r["passed"] for r in rows), rows
