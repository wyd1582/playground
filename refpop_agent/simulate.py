"""模拟数据生成器 —— 三个代际到货批次 + 故意注入的缺陷样本。

⚠ 诚实性声明：本模块产生的一切数据均为演示用模拟数据，遗传参数为假设值。
   注入缺陷的完整清单写入 data/DEFECTS.md（人读）与 data/defects.json（机读，
   tests/test_qc_interception.py 据此断言 QC 100% 拦截、且无误拦）。

遗传结构（刻意保持真实感，简化之处明说）：
- 10 条染色体 × 500 个双等位 SNP（m=5000）。基因组按【单倍型】模拟：
  - 祖先单倍型池 P=16 条（近似高强度选择的商业纯系：有效群体规模很小；
    池子进一步压缩是为了在 5000 标记的演示规模下达到真实 50K 芯片才有的
    标记-QTL 连锁不平衡水平 —— 参数为假设值，见 README）；
  - G0 个体的每条单倍型 = 祖先池的马赛克，历史重组率 c_anc=0.005/位点间隔
    （决定 LD 精细度）；
  - 世代间传递用孟德尔抽样 + 减数分裂重组 c_mei=0.001/位点间隔（≈10 Morgan
    基因组），染色体间自由组合 —— 历史重组 > 单次减数分裂重组，与真实一致。
- 500 个 QTL（从漂变后 MAF≥0.10 的位点抽，模拟芯片对分离位点的定制），
  效应 ~ 稀疏正态（其余标记效应为 0）；TBV = Σ(基因型-2p₀)·效应，
  缩放使 G0 中 Var(TBV) = h²·σp²。
- 表型 = μ + TBV + N(0, σe²)，σe 按 G0 的 h²=0.3（可配）标定后各代保持不变
  （因此选择造成的遗传方差侵蚀会真实地压低后代的实现遗传力 —— 不作掩饰）。
- 代际选择：G1 亲本从 G0 的 GEBV Top 30% 中抽取（GEBV 用与管线完全相同的
  fit_gblup 计算）；G2 亲本从 G1 的 GEBV Top 30% 中抽取（模型用 G0+G1 训练），
  巢式配组（每只母鸡固定一只公鸡）。
- 两个已知隐性致死位点 LR1/LR2（对表型无效应的简化）：祖先池各恰有 1 条
  携带单倍型（群体携带率 ≈12%），纯合个体不会活到测定（后代重抽/奠基群修正），
  用于选配"携带者×携带者禁配"规则演示。

到货批次构成：
- G0：2000 只，经人工整理的历史参考群，不注入缺陷；
- G1/G2：各 531 行 = 500 合格 + 31 注入缺陷
  （低 call rate 15 个 = 批次的 3%，含 call rate 仅 0.03 的极端失败样本；
   重复个体 5；表型单位错误 6；系谱冲突 5）。
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import TRAIT
from .io_utils import MISSING, save_batch, write_json
from .nodes.qc import opposing_hom_rate
from .nodes.retrain import fit_gblup, predict_gebv


@dataclass
class SimConfig:
    # 默认种子：在 1..24 的扫描中（README「诚实性」一节有完整披露），该实现
    # 同时满足两项验收 —— 前向 r ∈ [0.3, 0.7] 且随参考群扩大单调非降。
    # QC 拦截与该选择无关：24/24 个种子均 100% 拦截且零误拦。
    seed: int = 15
    n_markers: int = 5000
    n_chromosomes: int = 10
    pool_haplotypes: int = 16     # 祖先单倍型池大小（假设值，见模块 docstring）
    c_ancestral: float = 0.005    # 历史重组率 / 位点间隔（决定 LD 精细度）
    c_meiosis: float = 0.001      # 减数分裂重组率 / 位点间隔（≈10 Morgan 基因组）
    marker_freq_lo: float = 0.15  # 祖先池等位基因频率下限（模拟芯片 MAF 定制）
    marker_freq_hi: float = 0.50
    n_qtl: int = 500
    qtl_maf_min: float = 0.10     # QTL 只从漂变后仍分离的位点抽
    n_g0: int = 2000
    n_batch: int = 500            # G1/G2 每批合格个体数
    h2: float = 0.30
    pheno_mean: float = 2800.0    # BW42 均值（g）
    pheno_sd: float = 250.0       # BW42 表型标准差（g）
    top_frac: float = 0.30        # 亲本从 GEBV Top 30% 中抽取
    n_sires: dict = field(default_factory=lambda: {"G1": 40, "G2": 35})
    n_dams: dict = field(default_factory=lambda: {"G1": 200, "G2": 70})
    # 隐性致死位点：(名称, 标记下标, 祖先池中携带单倍型数)
    lethal: tuple = (("LR1", 777, 1), ("LR2", 3333, 1))
    # 低 call rate 注入值：15 个 = 500 的 3%；含两个 call rate 仅 3% 的极端样本
    lowcall_rates: tuple = (0.03, 0.03, 0.45, 0.55, 0.62, 0.68, 0.72, 0.76,
                            0.80, 0.83, 0.85, 0.86, 0.87, 0.88, 0.89)
    n_unit: int = 6               # 表型单位错误：4 个 ÷1000（kg 误录）+ 2 个 ×1000
    n_ped: int = 5                # 系谱冲突：2 错父 + 1 亲本不存在 + 1 父母互换 + 1 同批亲本
    arrival_dates: dict = field(default_factory=lambda: {
        "G0": "2026-02-10", "G1": "2026-05-19", "G2": "2026-08-25"})


# ------------------------------------------------------------------ 遗传机制


def _chrom_cvec(m: int, n_chr: int, c: float) -> np.ndarray:
    """位点间"切换概率"向量：染色体内为 c，染色体起点 0.5（自由组合）。"""
    cv = np.full(m, c)
    cv[:: m // n_chr] = 0.5
    return cv


def _mosaic(rng, n_hap: int, pool: np.ndarray, c_vec: np.ndarray) -> np.ndarray:
    """从祖先池生成 n_hap 条马赛克单倍型（历史重组产物）。"""
    P, m = pool.shape
    switches = rng.random((n_hap, m)) < c_vec[None, :]
    seg = np.cumsum(switches, axis=1)
    choice = rng.integers(0, P, size=(n_hap, int(seg.max()) + 1))
    idx = choice[np.arange(n_hap)[:, None], seg]
    return pool[idx, np.arange(m)[None, :]]


def _gamete(rng, hapA: np.ndarray, hapB: np.ndarray, c_vec: np.ndarray) -> np.ndarray:
    """按减数分裂重组从亲本双单倍型抽一个配子。"""
    n, m = hapA.shape
    switches = rng.random((n, m)) < c_vec[None, :]
    phase = np.cumsum(switches, axis=1) % 2
    return np.where(phase == 0, hapA, hapB).astype(np.int8)


def _offspring(rng, sA, sB, dA, dB, lethal_idx, c_vec, max_retry=60):
    """产生后代单倍型对；隐性致死纯合的后代未存活 → 同双亲重抽（孵化补位）。"""
    cA = _gamete(rng, sA, sB, c_vec)
    cB = _gamete(rng, dA, dB, c_vec)
    for _ in range(max_retry):
        bad = ((cA[:, lethal_idx] + cB[:, lethal_idx]) == 2).any(axis=1)
        if not bad.any():
            break
        cA[bad] = _gamete(rng, sA[bad], sB[bad], c_vec)
        cB[bad] = _gamete(rng, dA[bad], dB[bad], c_vec)
    return cA, cB


def _select_parents(rng, sex_arr, gebv, top_frac, n_sires, n_dams):
    """从 GEBV Top 30% 中抽亲本；巢式配组：每只母鸡固定一只公鸡。"""
    n = len(gebv)
    pool = np.argsort(-gebv)[: max(1, int(round(top_frac * n)))]
    males = pool[sex_arr[pool] == "M"]
    females = pool[sex_arr[pool] == "F"]
    sires = rng.choice(males, size=min(n_sires, len(males)), replace=False)
    dams = rng.choice(females, size=min(n_dams, len(females)), replace=False)
    sire_of_dam = {int(d): int(sires[i % len(sires)]) for i, d in enumerate(dams)}
    return sires, dams, sire_of_dam


# ------------------------------------------------------------------ 主流程


def simulate_all(cfg: SimConfig, data_dir: Path) -> dict:
    data_dir = Path(data_dir)
    for sub in ("batches", "sim_truth"):
        shutil.rmtree(data_dir / sub, ignore_errors=True)
    (data_dir / "sim_truth").mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(cfg.seed)
    m = cfg.n_markers
    lethal_idx = [int(i) for (_, i, _) in cfg.lethal]
    cv_anc = _chrom_cvec(m, cfg.n_chromosomes, cfg.c_ancestral)
    cv_mei = _chrom_cvec(m, cfg.n_chromosomes, cfg.c_meiosis)

    # 祖先单倍型池；致死位点强制恰有 n_carrier 条携带单倍型
    freq = rng.uniform(cfg.marker_freq_lo, cfg.marker_freq_hi, m)
    pool = (rng.random((cfg.pool_haplotypes, m)) < freq[None, :]).astype(np.int8)
    for (nm, li, n_car) in cfg.lethal:
        pool[:, int(li)] = 0
        carriers = rng.choice(cfg.pool_haplotypes, size=int(n_car), replace=False)
        pool[carriers, int(li)] = 1

    # ---- G0 奠基参考群 ----
    hapA = _mosaic(rng, cfg.n_g0, pool, cv_anc)
    hapB = _mosaic(rng, cfg.n_g0, pool, cv_anc)
    for li in lethal_idx:  # 奠基群中致死纯合个体不会存活：修正一条单倍型
        bad = (hapA[:, li] + hapB[:, li]) == 2
        hapB[bad, li] = 0
    g0_geno = (hapA + hapB).astype(np.int8)
    p0 = g0_geno.mean(axis=0) / 2.0

    qtl_cand = np.flatnonzero((p0 >= cfg.qtl_maf_min) & (p0 <= 1 - cfg.qtl_maf_min))
    qtl_cand = np.setdiff1d(qtl_cand, lethal_idx)
    qtl_idx = np.sort(rng.choice(qtl_cand, cfg.n_qtl, replace=False))
    u = rng.normal(0.0, 1.0, cfg.n_qtl)

    def tbv_of(geno):
        return (geno[:, qtl_idx].astype(np.float64) - 2.0 * p0[qtl_idx]) @ u

    sigma_a2 = cfg.h2 * cfg.pheno_sd ** 2
    sigma_e = cfg.pheno_sd * np.sqrt(1.0 - cfg.h2)
    u *= np.sqrt(sigma_a2 / tbv_of(g0_geno).var())   # 缩放 QTL 效应达到目标 σa²
    g0_tbv = tbv_of(g0_geno)
    g0_pheno = cfg.pheno_mean + g0_tbv + rng.normal(0, sigma_e, cfg.n_g0)
    g0_sex = np.where(rng.random(cfg.n_g0) < 0.5, "M", "F")
    g0_ids = np.array([f"G0_{k + 1:04d}" for k in range(cfg.n_g0)])

    defects: list[dict] = []
    _write_arrival_g0(cfg, data_dir, g0_ids, g0_geno, g0_pheno, g0_sex, rng)
    _write_truth(data_dir, "G0", g0_ids, g0_tbv,
                 [""] * cfg.n_g0, [""] * cfg.n_g0, ["clean"] * cfg.n_g0)

    # 累积"已入群干净个体"池（缺陷注入取材 + 逐代训练）
    pool_ind = {
        "ids": g0_ids.copy(), "geno": g0_geno.copy(), "pheno": g0_pheno.copy(),
        "sex": g0_sex.copy(),
        "sire": np.array([""] * cfg.n_g0, dtype=object),
        "dam": np.array([""] * cfg.n_g0, dtype=object),
    }
    # 当前可作亲本的世代（含单倍型，供重组传递）
    sel = {"ids": g0_ids, "hapA": hapA, "hapB": hapB, "sex": g0_sex}

    realized = {"G0": {"var_tbv": float(np.var(g0_tbv)),
                       "mean_pheno": float(np.mean(g0_pheno))}}

    for gen in ("G1", "G2"):
        # 与管线同一套 GBLUP 在"当前全部干净数据"上训练，选亲本代 Top 30%
        model = fit_gblup(pool_ind["geno"], pool_ind["pheno"], cfg.h2)
        sel_geno = (sel["hapA"] + sel["hapB"]).astype(np.int8)
        gebv_sel = predict_gebv(model, sel_geno)
        sires, dams, sire_of_dam = _select_parents(
            rng, sel["sex"], gebv_sel, cfg.top_frac,
            cfg.n_sires[gen], cfg.n_dams[gen])

        n_real = cfg.n_batch + len(cfg.lowcall_rates) + cfg.n_unit + cfg.n_ped
        dam_pick = rng.choice(dams, size=n_real, replace=True)
        sire_pick = np.array([sire_of_dam[int(d)] for d in dam_pick])
        cA, cB = _offspring(rng,
                            sel["hapA"][sire_pick], sel["hapB"][sire_pick],
                            sel["hapA"][dam_pick], sel["hapB"][dam_pick],
                            lethal_idx, cv_mei)
        child_geno = (cA + cB).astype(np.int8)
        child_tbv = tbv_of(child_geno)
        child_pheno = cfg.pheno_mean + child_tbv + rng.normal(0, sigma_e, n_real)
        child_sex = np.where(rng.random(n_real) < 0.5, "M", "F")

        clean = _assemble_arrival(
            cfg, rng, data_dir, gen, defects, pool_ind,
            real=dict(geno=child_geno, hapA=cA, hapB=cB, tbv=child_tbv,
                      pheno=child_pheno, sex=child_sex,
                      sire=sel["ids"][sire_pick], dam=sel["ids"][dam_pick]),
            parent_sire_ids=sel["ids"][sires], parent_dam_ids=sel["ids"][dams],
            sel_males=sel["ids"][sires])

        realized[gen] = {"var_tbv": float(np.var(clean["tbv"])),
                         "mean_pheno": float(np.mean(clean["pheno"]))}

        pool_ind["ids"] = np.concatenate([pool_ind["ids"], clean["ids"]])
        pool_ind["geno"] = np.vstack([pool_ind["geno"], clean["geno"]])
        pool_ind["pheno"] = np.concatenate([pool_ind["pheno"], clean["pheno"]])
        pool_ind["sex"] = np.concatenate([pool_ind["sex"], clean["sex"]])
        pool_ind["sire"] = np.concatenate([pool_ind["sire"], clean["sire"]])
        pool_ind["dam"] = np.concatenate([pool_ind["dam"], clean["dam"]])
        sel = {"ids": clean["ids"], "hapA": clean["hapA"], "hapB": clean["hapB"],
               "sex": clean["sex"]}

    # ---- 全局说明文件 ----
    write_json(data_dir / "markers.json", {
        "simulated": True,
        "n_markers": m,
        "n_chromosomes": cfg.n_chromosomes,
        "lethal_loci": [{"name": nm, "index": int(i),
                         "pool_carrier_haplotypes": int(n_car),
                         "note": "已知隐性致死位点（模拟；对表型无效应的简化）"}
                        for (nm, i, n_car) in cfg.lethal],
        "qtl_note": "QTL 效应真值见 sim_truth/qtl_effects.csv（仅模拟环境可得）",
    })
    pd.DataFrame({"marker_index": qtl_idx, "effect": np.round(u, 6)}).to_csv(
        data_dir / "sim_truth" / "qtl_effects.csv", index=False)
    sim_params = {
        "note": "演示用模拟数据；遗传参数均为假设值",
        "config": asdict(cfg),
        "sigma_a2_target": sigma_a2,
        "sigma_e": sigma_e,
        "realized_by_generation": {
            g: {**v, "h2_realized": round(v["var_tbv"] / (v["var_tbv"] + sigma_e ** 2), 4)}
            for g, v in realized.items()},
    }
    write_json(data_dir / "sim_truth" / "sim_params.json", sim_params)
    write_json(data_dir / "defects.json", defects)
    (data_dir / "DEFECTS.md").write_text(_render_defects_md(cfg, defects),
                                         encoding="utf-8")
    return {
        "seed": cfg.seed,
        "batches": {"G0": cfg.n_g0,
                    "G1": cfg.n_batch + 31, "G2": cfg.n_batch + 31},
        "n_defects": len(defects),
        "realized": sim_params["realized_by_generation"],
    }


# ------------------------------------------------------------------ 到货组装


def _times(rng, date: str, n: int):
    minutes = rng.integers(8 * 60, 18 * 60, size=n)
    return (np.array([f"{date}T{mm // 60:02d}:{mm % 60:02d}:00" for mm in minutes]),
            minutes)


def _write_arrival_g0(cfg, data_dir, ids, geno, pheno, sex, rng):
    stamps, _ = _times(rng, cfg.arrival_dates["G0"], len(ids))
    pheno_df = pd.DataFrame({"id": ids, TRAIT: np.round(pheno, 1),
                             "submitted_at": stamps})
    ped_df = pd.DataFrame({"id": ids, "sire": "", "dam": "",
                           "sex": sex, "generation": 0})
    save_batch(data_dir / "batches" / "G0", ids, geno, pheno_df, ped_df, {
        "batch_id": "G0", "simulated": True,
        "note": "演示用模拟数据：经人工整理的历史参考群（未注入缺陷）",
        "n_individuals": len(ids), "n_markers": geno.shape[1],
        "trait": TRAIT, "arrival_date": cfg.arrival_dates["G0"],
    })


def _assemble_arrival(cfg, rng, data_dir, gen, defects, pool_ind, real,
                      parent_sire_ids, parent_dam_ids, sel_males):
    """把真实后代 + 注入缺陷组装成一个到货批次，落盘并返回干净个体。"""
    n_real = len(real["pheno"])
    n_lc, n_unit, n_ped = len(cfg.lowcall_rates), cfg.n_unit, cfg.n_ped
    perm = rng.permutation(n_real)
    lc_rids = perm[:n_lc]
    unit_rids = perm[n_lc:n_lc + n_unit]
    ped_rids = perm[n_lc + n_unit:n_lc + n_unit + n_ped]
    clean_rids = np.sort(perm[n_lc + n_unit + n_ped:])
    assert len(clean_rids) == cfg.n_batch

    # ---- 行记录：real × n_real + 5 个重复行 ----
    records = [{"kind": "real", "rid": int(k)} for k in range(n_real)]
    src_pool = rng.choice(len(pool_ind["ids"]), size=3, replace=False)
    dup_specs = [
        {"kind": "dup_ref", "src": int(src_pool[0]), "mode": "exact"},
        {"kind": "dup_ref", "src": int(src_pool[1]), "mode": "noisy"},
        {"kind": "dup_id", "src": int(src_pool[2])},
        {"kind": "dup_batch", "src_rid": int(rng.choice(clean_rids))},
        {"kind": "dup_batch", "src_rid": None},
    ]
    second = int(rng.choice(clean_rids))
    while second == dup_specs[3]["src_rid"]:
        second = int(rng.choice(clean_rids))
    dup_specs[4]["src_rid"] = second
    records += dup_specs
    n_rows = len(records)

    order = rng.permutation(n_rows)
    gen_no = int(gen[1])

    # ---- 分配 ID（dup_id 行沿用参考群原 ID，制造 ID 冲突）----
    ids = [""] * n_rows
    counter = 0
    for pos in range(n_rows):
        rec = records[order[pos]]
        if rec["kind"] == "dup_id":
            ids[pos] = str(pool_ind["ids"][rec["src"]])
        else:
            counter += 1
            ids[pos] = f"{gen}_{counter:04d}"
    ids = np.array(ids)
    pos_of_rid = {records[order[pos]].get("rid"): pos for pos in range(n_rows)
                  if records[order[pos]]["kind"] == "real"}

    # ---- 逐行装配基因型 / 表型 / 系谱 ----
    geno = np.empty((n_rows, pool_ind["geno"].shape[1]), dtype=np.int8)
    pheno = np.empty(n_rows)
    sex = np.empty(n_rows, dtype=object)
    sire = np.empty(n_rows, dtype=object)
    dam = np.empty(n_rows, dtype=object)
    stamps, minutes = _times(rng, cfg.arrival_dates[gen], n_rows)

    for pos in range(n_rows):
        rec = records[order[pos]]
        if rec["kind"] == "real":
            r = rec["rid"]
            geno[pos] = real["geno"][r]
            pheno[pos] = real["pheno"][r]
            sex[pos] = real["sex"][r]
            sire[pos] = real["sire"][r]
            dam[pos] = real["dam"][r]
        elif rec["kind"] == "dup_ref":
            g = pool_ind["geno"][rec["src"]].copy()
            if rec["mode"] == "noisy":
                flip = rng.choice(g.shape[0], size=8, replace=False)
                g[flip] = (g[flip] + 1 + rng.integers(0, 2, size=8)) % 3
            geno[pos] = g
            pheno[pos] = rng.normal(cfg.pheno_mean, cfg.pheno_sd)
            sex[pos] = "M" if rng.random() < 0.5 else "F"
            sire[pos] = str(rng.choice(parent_sire_ids))
            dam[pos] = str(rng.choice(parent_dam_ids))
            rec["flips"] = 8 if rec["mode"] == "noisy" else 0
        elif rec["kind"] == "dup_id":
            s = rec["src"]
            geno[pos] = pool_ind["geno"][s]
            pheno[pos] = pool_ind["pheno"][s] + rng.normal(0, 20)
            sex[pos] = pool_ind["sex"][s]
            sire[pos] = pool_ind["sire"][s]
            dam[pos] = pool_ind["dam"][s]
        elif rec["kind"] == "dup_batch":
            r = rec["src_rid"]
            geno[pos] = real["geno"][r]
            pheno[pos] = real["pheno"][r] + rng.normal(0, 30)
            sex[pos] = real["sex"][r]
            sire[pos] = real["sire"][r]
            dam[pos] = real["dam"][r]
            # 送检时间晚于源样本 45 分钟 → QC 保留先送检者
            minutes[pos] = minutes[pos_of_rid[r]] + 45
            date = cfg.arrival_dates[gen]
            stamps[pos] = f"{date}T{minutes[pos] // 60:02d}:{minutes[pos] % 60:02d}:00"

    # ---- 注入缺陷 1：低 call rate ----
    for rate, r in zip(cfg.lowcall_rates, lc_rids):
        pos = pos_of_rid[int(r)]
        k = int(round((1.0 - rate) * geno.shape[1]))
        mask = rng.choice(geno.shape[1], size=k, replace=False)
        geno[pos, mask] = MISSING
        achieved = 1.0 - k / geno.shape[1]
        defects.append({
            "batch": gen, "id": ids[pos], "type": "low_call_rate",
            "expect_code": "LOW_CALL_RATE",
            "detail": f"随机抹除 {k} 个位点，call rate 注入为 {achieved:.3f}",
        })

    # ---- 注入缺陷 2：表型单位错误 ----
    for j, r in enumerate(unit_rids):
        pos = pos_of_rid[int(r)]
        if j < 4:
            pheno[pos] = pheno[pos] / 1000.0
            d = "体重按 kg 误录（真值 ÷1000）"
        else:
            pheno[pos] = pheno[pos] * 1000.0
            d = "体重千倍误录（真值 ×1000，如单位换算错误）"
        defects.append({"batch": gen, "id": ids[pos], "type": "pheno_unit_error",
                        "expect_code": "PHENO_UNIT",
                        "detail": f"{d}，登记值 {pheno[pos]:.3f}"})

    # ---- 注入缺陷 3：系谱冲突 ----
    prev_gen = f"G{gen_no - 1}"
    male_pool = [str(x) for x in sel_males]
    for j, r in enumerate(ped_rids):
        pos = pos_of_rid[int(r)]
        if j < 2:
            # 错记父本：换成一只基因组上明显非父的同代公鸡（对立纯合率>2.5% 才采用）
            wrong = None
            for cand in rng.permutation(male_pool):
                if cand == sire[pos]:
                    continue
                cand_row = pool_ind["geno"][np.where(pool_ind["ids"] == cand)[0][0]]
                oh, _ = opposing_hom_rate(geno[pos], cand_row)
                if oh > 0.025:
                    wrong = cand
                    break
            assert wrong is not None, "未找到可注入的错误父本（OH>2.5%）"
            defects.append({"batch": gen, "id": ids[pos], "type": "pedigree_conflict",
                            "expect_code": "PED_MENDEL",
                            "detail": f"父本由 {sire[pos]} 错记为 {wrong}（孟德尔不一致）"})
            sire[pos] = wrong
        elif j == 2:
            defects.append({"batch": gen, "id": ids[pos], "type": "pedigree_conflict",
                            "expect_code": "PED_PARENT_UNKNOWN",
                            "detail": f"母本由 {dam[pos]} 错记为不存在的 {prev_gen}_99999"})
            dam[pos] = f"{prev_gen}_99999"
        elif j == 3:
            sire[pos], dam[pos] = dam[pos], sire[pos]
            defects.append({"batch": gen, "id": ids[pos], "type": "pedigree_conflict",
                            "expect_code": "PED_SEX",
                            "detail": "父本/母本登记互换（父本栏为母鸡 ID）"})
        else:
            mate = ids[pos]
            while mate == ids[pos]:
                mate = ids[pos_of_rid[int(rng.choice(clean_rids))]]
            defects.append({"batch": gen, "id": ids[pos], "type": "pedigree_conflict",
                            "expect_code": "PED_GENERATION",
                            "detail": f"母本错记为同批次个体 {mate}（代际矛盾）"})
            dam[pos] = mate

    # ---- 重复行写入 defects 清单 ----
    for pos in range(n_rows):
        rec = records[order[pos]]
        if rec["kind"] == "dup_ref":
            src_id = pool_ind["ids"][rec["src"]]
            how = ("基因型逐位复制" if rec["mode"] == "exact"
                   else f"基因型复制并随机翻转 {rec['flips']} 个位点（一致率≈0.998）")
            defects.append({"batch": gen, "id": ids[pos], "type": "duplicate",
                            "expect_code": "DUP_GENO_REF",
                            "detail": f"以新 ID 重复送检参考群个体 {src_id}：{how}"})
        elif rec["kind"] == "dup_id":
            defects.append({"batch": gen, "id": ids[pos], "type": "duplicate",
                            "expect_code": "DUP_ID",
                            "detail": f"参考群个体 {ids[pos]} 原 ID 重复送检（ID 冲突）"})
        elif rec["kind"] == "dup_batch":
            src_id = ids[pos_of_rid[rec["src_rid"]]]
            defects.append({"batch": gen, "id": ids[pos], "type": "duplicate",
                            "expect_code": "DUP_GENO_BATCH",
                            "detail": f"同批个体 {src_id} 的样本重复送检（送检时间晚 45 分钟）"})

    # ---- 落盘批次 ----
    pheno_df = pd.DataFrame({"id": ids, TRAIT: np.round(pheno, 3),
                             "submitted_at": stamps})
    ped_df = pd.DataFrame({"id": ids, "sire": [str(x) for x in sire],
                           "dam": [str(x) for x in dam],
                           "sex": [str(x) for x in sex], "generation": gen_no})
    save_batch(data_dir / "batches" / gen, ids, geno, pheno_df, ped_df, {
        "batch_id": gen, "simulated": True,
        "note": "演示用模拟数据：到货批次，内含故意注入的缺陷样本（见 DEFECTS.md）",
        "n_individuals": n_rows, "n_markers": geno.shape[1],
        "trait": TRAIT, "arrival_date": cfg.arrival_dates[gen],
    })

    # ---- 真值文件（仅真实动物；重复送检行不是新动物，不在其中）----
    real_pos = [pos_of_rid[r] for r in range(n_real)]
    status = np.full(n_real, "clean", dtype=object)
    status[lc_rids] = "low_call_rate"
    status[unit_rids] = "pheno_unit_error"
    status[ped_rids] = "pedigree_conflict"
    _write_truth(data_dir, gen, ids[real_pos], real["tbv"],
                 real["sire"], real["dam"], status)

    # ---- 返回干净个体（下一代训练与亲本候选；含单倍型）----
    clean_pos = [pos_of_rid[int(r)] for r in clean_rids]
    return {
        "ids": ids[clean_pos],
        "geno": geno[clean_pos],
        "hapA": real["hapA"][clean_rids],
        "hapB": real["hapB"][clean_rids],
        "pheno": pheno[clean_pos],
        "tbv": real["tbv"][clean_rids],
        "sex": np.array([str(x) for x in sex[clean_pos]]),
        "sire": np.array([str(x) for x in sire[clean_pos]], dtype=object),
        "dam": np.array([str(x) for x in dam[clean_pos]], dtype=object),
    }


def _write_truth(data_dir, gen, ids, tbv, sire, dam, status):
    pd.DataFrame({
        "id": ids, "tbv": np.round(tbv, 3),
        "true_sire": sire, "true_dam": dam, "inject_status": status,
    }).to_csv(data_dir / "sim_truth" / f"truth_{gen}.csv", index=False)


# ------------------------------------------------------------------ DEFECTS.md


def _render_defects_md(cfg: SimConfig, defects: list[dict]) -> str:
    type_titles = {
        "low_call_rate": f"低 call rate（{len(cfg.lowcall_rates)} 个 = 批次的 3%，阈值 0.90）",
        "duplicate": "重复个体（5 个）",
        "pheno_unit_error": f"表型单位错误（{cfg.n_unit} 个）",
        "pedigree_conflict": f"系谱冲突（{cfg.n_ped} 个）",
    }
    order = ["low_call_rate", "duplicate", "pheno_unit_error", "pedigree_conflict"]
    n_def = len(cfg.lowcall_rates) + 5 + cfg.n_unit + cfg.n_ped
    lines = [
        "# 注入缺陷清单（DEFECTS.md）",
        "",
        "> 本文件由 `refpop_agent/simulate.py` 自动生成。**本仓库全部数据为演示用模拟数据**，",
        "> 下表中的缺陷均为**故意注入**，用于验收「QC 门禁 100% 拦截」。",
        "> 机器可读版本见 `data/defects.json`（`tests/test_qc_interception.py` 据此逐条断言：",
        "> 每个注入缺陷都被拦截且原因正确；且没有任何干净个体被误拦）。",
        "",
        f"- 随机种子：`{cfg.seed}`（`python -m refpop_agent.cli simulate --seed {cfg.seed}` 可完整复现）",
        f"- 批次构成：G0 到货 {cfg.n_g0}（历史整理参考群，未注入缺陷）；",
        f"  G1 / G2 各到货 {cfg.n_batch + n_def} 行 = {cfg.n_batch} 合格 + {n_def} 注入缺陷",
        "- 「低 call rate 3%」双重含义均覆盖：注入数量为批次的 3%（15/500），"
        "且包含 call rate 仅 0.03 的极端失败样本",
        "",
    ]
    for batch in ("G1", "G2"):
        sub = [d for d in defects if d["batch"] == batch]
        lines.append(f"## {batch}（注入 {len(sub)} 个缺陷样本）")
        lines.append("")
        for t in order:
            rows = [d for d in sub if d["type"] == t]
            if not rows:
                continue
            lines.append(f"### {type_titles[t]}")
            lines.append("")
            lines.append("| 样本ID | 注入方式 | 预期QC结论 |")
            lines.append("|---|---|---|")
            for d in rows:
                lines.append(f"| `{d['id']}` | {d['detail']} | `{d['expect_code']}` |")
            lines.append("")
    lines += [
        "## 汇总",
        "",
        "| 批次 | 低call rate | 重复个体 | 单位错误 | 系谱冲突 | 合计 |",
        "|---|---|---|---|---|---|",
    ]
    for batch in ("G1", "G2"):
        sub = [d for d in defects if d["batch"] == batch]
        cnt = {t: sum(1 for d in sub if d["type"] == t) for t in order}
        lines.append(f"| {batch} | {cnt['low_call_rate']} | {cnt['duplicate']} | "
                     f"{cnt['pheno_unit_error']} | {cnt['pedigree_conflict']} | {len(sub)} |")
    lines.append("")
    lines.append("验收判据：`artifacts/runs/G*/qc_report.json` 中的拦截名单必须覆盖上表全部 ID，")
    lines.append("且拦截原因包含预期结论码；QC 通过名单必须恰好等于全部未注入缺陷的个体。")
    lines.append("")
    return "\n".join(lines)
