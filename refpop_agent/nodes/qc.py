"""QC 门禁节点 —— 到货批次的个体级质量控制。确定性规则、可单测。

检查项（阈值见 config.PipelineConfig）：
1. 基因型检出率（call rate）
2. 重复个体：ID 与参考群冲突 / 与参考群基因型重复 / 批内基因型重复
   （批内重复按送检时间保留先送检样本，其余判为重复）
3. 表型：生理硬边界 + 单位错误启发（×1000 或 ÷1000 后落回正常范围
   → 疑似 kg↔g 类单位错误）+ 界内稳健 z 分数兜底
4. 系谱：亲本登记存在性 / 代际矛盾（亲本在本到货批次内）/ 亲本性别矛盾 /
   亲子对立纯合率（孟德尔一致性，仅当亲本已有基因型且可比位点足够）

一个个体可命中多条规则；任何一条命中即拦截，不进入参考群。
拦截明细落盘 artifacts/runs/<batch>/qc_report.{csv,json}（谁被拦、为什么）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PipelineConfig, TRAIT
from ..io_utils import (MISSING, BatchData, RefpopStore, load_batch,
                        load_refpop, write_json)

REASON_LABELS = {
    "LOW_CALL_RATE": "基因型检出率过低",
    "DUP_ID": "ID 与参考群已有个体冲突（重复送检）",
    "DUP_GENO_REF": "基因型与参考群个体高度一致（疑似重复/串样）",
    "DUP_GENO_BATCH": "基因型与本批次内个体高度一致（重复送检）",
    "PHENO_MISSING": "表型缺失",
    "PHENO_UNIT": "表型疑似单位错误",
    "PHENO_RANGE": "表型超出生理范围",
    "PHENO_OUTLIER": "表型稳健 z 分数异常",
    "PED_PARENT_UNKNOWN": "系谱冲突：亲本不在参考群登记",
    "PED_GENERATION": "系谱冲突：亲本属于本到货批次（代际矛盾）",
    "PED_SELF": "系谱冲突：个体被登记为自身亲本",
    "PED_SAME_PARENTS": "系谱冲突：父本与母本为同一个体",
    "PED_SEX": "系谱冲突：亲本性别与登记不符",
    "PED_MENDEL": "系谱冲突：亲子对立纯合率超标（孟德尔不一致）",
}

# 报告中"主要原因"的展示优先级
REASON_ORDER = [
    "DUP_ID", "DUP_GENO_REF", "DUP_GENO_BATCH", "LOW_CALL_RATE",
    "PHENO_MISSING", "PHENO_UNIT", "PHENO_RANGE", "PHENO_OUTLIER",
    "PED_SELF", "PED_SAME_PARENTS", "PED_GENERATION",
    "PED_PARENT_UNKNOWN", "PED_SEX", "PED_MENDEL",
]


def call_rates(geno: np.ndarray) -> np.ndarray:
    """每个体基因型检出率。"""
    return (geno != MISSING).mean(axis=1)


def genotype_concordance(a: np.ndarray, b: np.ndarray, min_overlap: int):
    """两组基因型两两一致率（重复样本扫描）。

    返回 (conc, overlap)：conc[i,j] = 共同检出位点上基因型完全一致的比例；
    共同检出位点数 < min_overlap 时记 -1（覆盖不足，不做判定）。
    用 0/1/2 三类 one-hot 矩阵乘实现，O(n·m·k) 由 BLAS 承担。
    """
    am = (a != MISSING).astype(np.float32)
    bm = (b != MISSING).astype(np.float32)
    overlap = am @ bm.T
    match = np.zeros_like(overlap)
    for g in (0, 1, 2):
        match += (a == g).astype(np.float32) @ (b == g).astype(np.float32).T
    conc = match / np.maximum(overlap, 1.0)
    conc[overlap < min_overlap] = -1.0
    return conc, overlap


def opposing_hom_rate(child: np.ndarray, parent: np.ndarray):
    """亲子对立纯合率：双方检出且一方 0、另一方 2 的位点比例。

    真亲子对（无基因分型错误时）应接近 0；错记亲本时通常达数个百分点。
    返回 (rate, n_informative)。
    """
    both = (child != MISSING) & (parent != MISSING)
    n = int(both.sum())
    if n == 0:
        return 0.0, 0
    oh = int(np.sum((((child == 0) & (parent == 2)) |
                     ((child == 2) & (parent == 0))) & both))
    return oh / n, n


def evaluate_batch(batch: BatchData, refpop: RefpopStore, cfg: PipelineConfig):
    """纯函数：对一个到货批次执行全部 QC 检查。

    返回 (decisions_df, admitted_ids, summary)。
    """
    n = batch.n
    reasons: list[list[str]] = [[] for _ in range(n)]
    details: list[list[str]] = [[] for _ in range(n)]

    def add(i: int, code: str, detail: str) -> None:
        if code not in reasons[i]:
            reasons[i].append(code)
        details[i].append(detail)

    ref_ids = set(refpop.ids.tolist())
    ref_idx = {v: k for k, v in enumerate(refpop.ids.tolist())}
    batch_idset = set(batch.ids.tolist())

    cr = call_rates(batch.geno)
    pheno = batch.pheno[TRAIT].to_numpy(dtype=float)
    sub_at = batch.pheno["submitted_at"].astype(str).tolist()

    # 1) call rate ---------------------------------------------------------
    for i in np.flatnonzero(cr < cfg.min_call_rate):
        add(int(i), "LOW_CALL_RATE",
            f"基因型检出率 {cr[i]:.3f} < 阈值 {cfg.min_call_rate:.2f}")

    # 2) ID 冲突 -----------------------------------------------------------
    for i, iid in enumerate(batch.ids):
        if iid in ref_ids:
            add(i, "DUP_ID", f"ID {iid} 已存在于参考群登记，疑似同一个体重复送检")

    # 3) 表型 --------------------------------------------------------------
    lo, hi = cfg.pheno_lo, cfg.pheno_hi
    inb = (pheno >= lo) & (pheno <= hi)
    med = float(np.median(pheno[inb])) if inb.any() else float("nan")
    mad = float(np.median(np.abs(pheno[inb] - med))) if inb.any() else float("nan")
    for i in range(n):
        v = pheno[i]
        if np.isnan(v):
            add(i, "PHENO_MISSING", "表型缺失")
            continue
        if v < lo or v > hi:
            if lo <= v * cfg.unit_factor <= hi:
                add(i, "PHENO_UNIT",
                    f"{TRAIT}={v:.10g} 超界 [{lo:g},{hi:g}]；×{cfg.unit_factor:g} 后 = "
                    f"{v * cfg.unit_factor:.10g} 落入正常范围，疑似 kg 误录为 g")
            elif lo <= v / cfg.unit_factor <= hi:
                add(i, "PHENO_UNIT",
                    f"{TRAIT}={v:.10g} 超界 [{lo:g},{hi:g}]；÷{cfg.unit_factor:g} 后 = "
                    f"{v / cfg.unit_factor:.10g} 落入正常范围，疑似千倍误录（单位换算错误）")
            else:
                add(i, "PHENO_RANGE", f"{TRAIT}={v:.10g} 超出生理范围 [{lo:g},{hi:g}]")
        elif mad > 0:
            z = 0.6745 * (v - med) / mad
            if abs(z) > cfg.robust_z_max:
                add(i, "PHENO_OUTLIER",
                    f"{TRAIT}={v:.10g} 稳健 z={z:.1f}，超过阈值 {cfg.robust_z_max:g}")

    # 4) 系谱 --------------------------------------------------------------
    reg_sex = dict(zip(refpop.ped["id"].tolist(), refpop.ped["sex"].tolist()))
    for i in range(n):
        row = batch.ped.iloc[i]
        sire, dam = str(row["sire"]), str(row["dam"])
        if sire and dam and sire == dam:
            add(i, "PED_SAME_PARENTS", f"父本与母本登记为同一个体 {sire}")
        for role, pid, want_sex in (("父本", sire, "M"), ("母本", dam, "F")):
            if not pid:
                continue  # 亲本未知（如奠基群）不检查
            if pid == batch.ids[i]:
                add(i, "PED_SELF", f"{role}登记为个体自身")
                continue
            # 注意顺序：亲本 ID 已在参考群登记时按登记个体处理（即使本批
            # 恰有同名 ID 冲突行，也不应连累引用该合法亲本的其他个体）；
            # 只有"不在参考群、仅出现在本批"的亲本才构成代际矛盾。
            if pid not in ref_ids:
                if pid in batch_idset:
                    add(i, "PED_GENERATION",
                        f"登记{role} {pid} 属于本到货批次，不可能是上代亲本（代际矛盾）")
                else:
                    add(i, "PED_PARENT_UNKNOWN",
                        f"登记{role} {pid} 不在参考群系谱登记中")
                continue
            psex = str(reg_sex.get(pid, ""))
            if psex and psex != want_sex:
                add(i, "PED_SEX",
                    f"登记{role} {pid} 在系谱中性别为 {psex}，与{role}角色矛盾")
                continue
            oh, ninf = opposing_hom_rate(batch.geno[i], refpop.geno[ref_idx[pid]])
            if ninf >= cfg.min_mendel_informative and oh > cfg.max_oh_rate:
                add(i, "PED_MENDEL",
                    f"与登记{role} {pid} 对立纯合率 {oh:.2%}（{ninf} 个可比位点）"
                    f"> 阈值 {cfg.max_oh_rate:.0%}")

    # 5) 基因型重复 --------------------------------------------------------
    if refpop.n > 0:
        conc, _ = genotype_concordance(batch.geno, refpop.geno, cfg.dup_min_overlap)
        best = conc.argmax(axis=1)
        for i in range(n):
            c = float(conc[i, best[i]])
            if c >= cfg.dup_concordance:
                add(i, "DUP_GENO_REF",
                    f"与参考群个体 {refpop.ids[best[i]]} 基因型一致率 {c:.4f} ≥ "
                    f"{cfg.dup_concordance}，疑似同一样本/串样")
    concb, _ = genotype_concordance(batch.geno, batch.geno, cfg.dup_min_overlap)
    ii, jj = np.where(np.triu(concb >= cfg.dup_concordance, k=1))
    for i, j in zip(ii.tolist(), jj.tolist()):
        # 保留先送检样本，后送检者判为重复（并列时按 ID 字典序）
        if (sub_at[i], batch.ids[i]) > (sub_at[j], batch.ids[j]):
            later, keep = i, j
        else:
            later, keep = j, i
        add(later, "DUP_GENO_BATCH",
            f"与本批次 {batch.ids[keep]} 基因型一致率 {float(concb[i, j]):.4f}，"
            f"保留先送检样本 {batch.ids[keep]}，本样本判为重复")

    # 汇总 ----------------------------------------------------------------
    rows = []
    for i in range(n):
        codes = sorted(reasons[i], key=REASON_ORDER.index)
        rows.append({
            "id": batch.ids[i],
            "decision": "拦截" if codes else "通过",
            "call_rate": round(float(cr[i]), 4),
            TRAIT: pheno[i],
            "sex": batch.ped.iloc[i]["sex"],
            "sire": batch.ped.iloc[i]["sire"],
            "dam": batch.ped.iloc[i]["dam"],
            "reasons": "|".join(codes),
            "detail": "；".join(details[i]),
        })
    decisions = pd.DataFrame(rows)
    admitted_ids = [batch.ids[i] for i in range(n) if not reasons[i]]

    reason_counts: dict[str, int] = {}
    for rs in reasons:
        for c in rs:
            reason_counts[c] = reason_counts.get(c, 0) + 1
    rejected = [
        {
            "id": rows[i]["id"],
            "reasons": sorted(reasons[i], key=REASON_ORDER.index),
            "detail": "；".join(details[i]),
            "call_rate": rows[i]["call_rate"],
            TRAIT: None if np.isnan(pheno[i]) else round(float(pheno[i]), 2),
        }
        for i in range(n) if reasons[i]
    ]
    summary = {
        "batch_id": batch.batch_id,
        "n_arrived": n,
        "n_admitted": len(admitted_ids),
        "n_rejected": len(rejected),
        "reason_counts": {k: reason_counts[k]
                          for k in sorted(reason_counts, key=REASON_ORDER.index)},
        "rejected": rejected,
        "thresholds": {
            "min_call_rate": cfg.min_call_rate,
            "dup_concordance": cfg.dup_concordance,
            "max_oh_rate": cfg.max_oh_rate,
            "pheno_bounds": [cfg.pheno_lo, cfg.pheno_hi],
        },
    }
    return decisions, admitted_ids, summary


def run(config: PipelineConfig, batch_id: str) -> dict:
    """I/O 包装：装载到货批次与参考群 → QC → 落盘拦截明细与放行名单。"""
    batch = load_batch(config.batch_dir(batch_id), batch_id)
    refpop = load_refpop(config.refpop_dir())
    decisions, admitted_ids, summary = evaluate_batch(batch, refpop, config)
    run_dir = config.run_dir(batch_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(run_dir / "qc_report.csv", index=False)
    write_json(run_dir / "qc_report.json", summary)
    write_json(run_dir / "admitted_ids.json", admitted_ids)
    return summary
