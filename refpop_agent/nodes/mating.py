"""选配建议节点 —— 近交约束 + 隐性致死携带者规则。确定性、可单测。

候选：本批次（当代）QC 通过个体，按重训后的 GEBV 排序取
top n_sires 公鸡 × top n_dams 母鸡。

约束：
1. 近交约束：预期后代近交系数 F = 双亲基因组亲缘系数 = G_sd / 2 ≤ 阈值
   （G 为 VanRaden 基因组关系矩阵，用当前模型的训练群频率中心化；
   全同胞 G_sd≈0.5 → F≈0.25 会被拒，表亲水平 F≈0.0625 为默认上限）。
2. 携带者规则：已知隐性致死位点（data/markers.json）上
   "携带者 × 携带者"禁配（后代 1/4 纯合致死）；携带者×正常允许但标注。
3. 每只公鸡最多配 max_dams_per_sire 只母鸡（笼位/配种能力约束的简化）。

算法：贪心 —— 母鸡按 GEBV 降序，依次分配满足全部约束的 GEBV 最高公鸡。
产物：mating_pairs.csv（全部配对）、candidates.csv（含携带者标注的候选清单，
报告 Top-20 由它复算）、mating_summary.json（被约束拒绝的统计）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PipelineConfig
from ..io_utils import load_refpop, read_json, write_json
from .retrain import center_genotypes, load_model, predict_gebv


def genomic_kinship(geno: np.ndarray, p: np.ndarray, sum2pq: float) -> np.ndarray:
    """基因组亲缘系数矩阵 K = G/2 = ZZ'/(2Σ2pq)···即预期后代近交系数。"""
    Z = center_genotypes(geno, p)
    return (Z @ Z.T) / sum2pq / 2.0


def greedy_mate(cand: pd.DataFrame, kin: np.ndarray, carrier_flags: dict[str, np.ndarray],
                cfg: PipelineConfig):
    """纯函数：贪心选配。

    cand: 候选表（含 idx 列 = kin/carrier 的行号，gebv、sex、id），
    kin: 候选×候选 亲缘系数矩阵（行列 = cand.idx 编号空间）。
    返回 (pairs list[dict], stats dict)。
    """
    males = cand[cand["sex"] == "M"].sort_values("gebv", ascending=False)
    females = cand[cand["sex"] == "F"].sort_values("gebv", ascending=False)
    sires = males.head(cfg.n_sires).reset_index(drop=True)
    dams = females.head(cfg.n_dams).reset_index(drop=True)

    lethal_names = sorted(carrier_flags.keys())
    load = {r["id"]: 0 for _, r in sires.iterrows()}
    pairs = []
    blocked_kinship = 0
    blocked_carrier = 0
    unassigned = []

    for _, drow in dams.iterrows():
        di = int(drow["idx"])
        chosen = None
        for _, srow in sires.iterrows():
            si = int(srow["idx"])
            if load[srow["id"]] >= cfg.max_dams_per_sire:
                continue
            f_prog = float(kin[si, di])
            if f_prog > cfg.max_progeny_inbreeding:
                blocked_kinship += 1
                continue
            clash = [nm for nm in lethal_names
                     if carrier_flags[nm][si] and carrier_flags[nm][di]]
            if clash:
                blocked_carrier += 1
                continue
            chosen = (srow, f_prog)
            break
        if chosen is None:
            unassigned.append(str(drow["id"]))
            continue
        srow, f_prog = chosen
        load[srow["id"]] += 1
        si = int(srow["idx"])
        notes = []
        for nm in lethal_names:
            if carrier_flags[nm][si]:
                notes.append(f"父本{nm}携带")
            if carrier_flags[nm][di]:
                notes.append(f"母本{nm}携带")
        pairs.append({
            "sire": srow["id"], "sire_gebv": round(float(srow["gebv"]), 2),
            "dam": drow["id"], "dam_gebv": round(float(drow["gebv"]), 2),
            "expected_progeny_gebv": round(float(srow["gebv"] + drow["gebv"]) / 2.0, 2),
            "expected_progeny_F": round(f_prog, 4),
            "carrier_note": "、".join(notes) if notes else "",
        })

    pairs.sort(key=lambda x: -x["expected_progeny_gebv"])
    for k, pr in enumerate(pairs, 1):
        pr["rank"] = k
    stats = {
        "n_sires_pool": int(len(sires)),
        "n_dams_pool": int(len(dams)),
        "n_pairs": len(pairs),
        "n_sires_used": int(sum(1 for v in load.values() if v > 0)),
        "blocked_kinship_attempts": blocked_kinship,
        "blocked_carrier_attempts": blocked_carrier,
        "unassigned_dams": unassigned,
    }
    return pairs, stats


def run(config: PipelineConfig, batch_id: str) -> dict:
    store = load_refpop(config.refpop_dir())
    model = load_model(config.model_path(batch_id))
    markers = read_json(config.markers_path())
    run_dir = config.run_dir(batch_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    mask = (store.pheno["batch"] == batch_id).to_numpy()
    ids_c = store.ids[mask]
    geno_c = store.geno[mask]
    ped_c = store.ped[mask].reset_index(drop=True)
    gebv_c = predict_gebv(model, geno_c)

    # 携带者判定（geno==1 为携带者；==2 理论上不应存活，防御性排除并记录）
    lethal = markers.get("lethal_loci", [])
    carrier_flags: dict[str, np.ndarray] = {}
    affected_ids: list[str] = []
    for loc in lethal:
        col = geno_c[:, int(loc["index"])]
        carrier_flags[loc["name"]] = (col == 1)
        affected_ids += [str(i) for i in ids_c[col == 2]]
    keep = ~np.isin(ids_c, affected_ids)

    order = np.argsort(-gebv_c)
    pct = np.empty(len(gebv_c))
    pct[order] = np.linspace(100, 100 / len(gebv_c), len(gebv_c))
    cand = pd.DataFrame({
        "idx": np.arange(len(ids_c)),
        "id": ids_c,
        "sex": ped_c["sex"].to_numpy(),
        "sire": ped_c["sire"].to_numpy(),
        "dam": ped_c["dam"].to_numpy(),
        "gebv": np.round(gebv_c, 3),
        "gebv_percentile": np.round(pct, 1),
    })
    for nm, flags in sorted(carrier_flags.items()):
        cand[f"carrier_{nm}"] = np.where(flags, "携带", "-")
    cand = cand[keep].sort_values("gebv", ascending=False).reset_index(drop=True)
    cand.to_csv(run_dir / "candidates.csv", index=False)

    kin = genomic_kinship(geno_c, model["p"], model["sum2pq"])
    pairs, stats = greedy_mate(cand, kin, carrier_flags, config)
    pairs_df = pd.DataFrame(pairs)
    if len(pairs_df):
        pairs_df = pairs_df[["rank", "sire", "sire_gebv", "dam", "dam_gebv",
                             "expected_progeny_gebv", "expected_progeny_F",
                             "carrier_note"]]
    pairs_df.to_csv(run_dir / "mating_pairs.csv", index=False)

    carrier_rates = {
        loc["name"]: {
            "index": int(loc["index"]),
            "n_carriers": int(carrier_flags[loc["name"]].sum()),
            "rate": round(float(carrier_flags[loc["name"]].mean()), 4),
        }
        for loc in lethal
    }
    summary = {
        "batch_id": batch_id,
        "n_candidates": int(len(cand)),
        "n_affected_excluded": len(affected_ids),
        **stats,
        "carrier_rates": carrier_rates,
        "rules": {
            "max_progeny_inbreeding": config.max_progeny_inbreeding,
            "max_dams_per_sire": config.max_dams_per_sire,
            "carrier_rule": "隐性致死位点 携带者×携带者 禁配；携带者×正常 允许并标注",
        },
    }
    write_json(run_dir / "mating_summary.json", summary)
    return summary
