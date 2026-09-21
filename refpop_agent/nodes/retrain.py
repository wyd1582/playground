"""GBLUP 重训节点 —— ridge 等价形式（RR-BLUP 对偶解）。确定性、可单测。

模型：y = 1μ + Zu + e，u ~ N(0, σu²·I_m)，e ~ N(0, σe²·I_n)
其中 Z 为按训练群等位基因频率中心化的基因型（缺失填补为均值 2p_j）。

σu² = σa² / (2Σ p_j q_j)
λ   = σe² / σu² = 2Σ p_j q_j · (1 - h²) / h²

解（对偶 / 核形式，n < m 时更省）：
û = Z'(ZZ' + λI_n)⁻¹ (y - ȳ)      —— 与原式 (Z'Z + λI_m)⁻¹ Z'(y - ȳ) 恒等
GEBV_new = Z_new û

与 GBLUP 的等价性：取 G = ZZ'/(2Σpq)（VanRaden 法一），则上式给出的 GEBV
与用 G 矩阵的 GBLUP 完全相同 —— 这就是任务规格里“GBLUP 用 ridge 等价形式”。

h² 为假设值（默认 0.3，可配）；生产中应由 REML 估计，见 README 生产化清单。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PipelineConfig, TRAIT
from ..io_utils import MISSING, load_refpop, now_iso, write_json


def allele_freq(geno: np.ndarray) -> np.ndarray:
    """按列（标记）计算等位基因频率，忽略缺失；截断避免除零。"""
    mask = geno != MISSING
    called = mask.sum(axis=0)
    alt = np.where(mask, geno, 0).sum(axis=0, dtype=np.int64)
    p = alt / (2.0 * np.maximum(called, 1))
    return np.clip(p, 1e-3, 1.0 - 1e-3)


def center_genotypes(geno: np.ndarray, p: np.ndarray) -> np.ndarray:
    """中心化基因型：Z = geno - 2p；缺失填补为均值（即 Z=0）。"""
    return np.where(geno == MISSING, 0.0, geno.astype(np.float64) - 2.0 * p)


def fit_gblup(geno: np.ndarray, y, h2: float, ids=None) -> dict:
    """训练 RR-BLUP（GBLUP 等价）。返回内存模型 dict。"""
    y = np.asarray(y, dtype=np.float64)
    n, m = geno.shape
    if n != len(y):
        raise ValueError(f"基因型 {n} 行与表型 {len(y)} 条不一致")
    if n < 10:
        raise ValueError("训练个体数过少（<10），拒绝训练")
    p = allele_freq(geno)
    Z = center_genotypes(geno, p)
    sum2pq = float(2.0 * np.sum(p * (1.0 - p)))
    lam = sum2pq * (1.0 - h2) / h2
    K = Z @ Z.T
    mu = float(y.mean())
    alpha = np.linalg.solve(K + lam * np.eye(n), y - mu)
    u = Z.T @ alpha
    gebv_train = K @ alpha  # = Z @ u
    return {
        "u": u, "p": p, "mu": mu, "lam": lam, "sum2pq": sum2pq,
        "h2": float(h2), "n_train": n, "m": m,
        "gebv_train": gebv_train,
        "train_ids": None if ids is None else np.asarray(ids, dtype=str),
    }


def predict_gebv(model: dict, geno: np.ndarray) -> np.ndarray:
    """用训练群频率中心化后预测 GEBV（相对训练群均值的偏差，单位同表型）。"""
    return center_genotypes(geno, model["p"]) @ model["u"]


def save_model(path_npz: Path, path_json: Path, model: dict, extra_meta: dict | None = None) -> None:
    path_npz = Path(path_npz)
    path_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path_npz,
        u=model["u"], p=model["p"],
        mu=model["mu"], lam=model["lam"], sum2pq=model["sum2pq"],
        h2=model["h2"], n_train=model["n_train"], m=model["m"],
    )
    meta = {k: model[k] for k in ("mu", "lam", "sum2pq", "h2", "n_train", "m")}
    meta.update(extra_meta or {})
    write_json(path_json, meta)


def load_model(path_npz: Path) -> dict:
    z = np.load(Path(path_npz), allow_pickle=False)
    return {
        "u": z["u"], "p": z["p"],
        "mu": float(z["mu"]), "lam": float(z["lam"]), "sum2pq": float(z["sum2pq"]),
        "h2": float(z["h2"]), "n_train": int(z["n_train"]), "m": int(z["m"]),
    }


def run(config: PipelineConfig, batch_id: str) -> dict:
    """在“合并后的全量参考群”上重训模型，落盘模型与全群 GEBV。"""
    store = load_refpop(config.refpop_dir())
    y = store.pheno[TRAIT].to_numpy(dtype=float)
    model = fit_gblup(store.geno, y, config.h2, ids=store.ids)
    save_model(
        config.model_path(batch_id), config.model_meta_path(batch_id), model,
        extra_meta={
            "batch_id": batch_id,
            "trained_at": now_iso(),
            "train_batches": {str(k): int(v)
                              for k, v in sorted(store.pheno["batch"].value_counts().items())},
        },
    )
    run_dir = config.run_dir(batch_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    gebv_df = pd.DataFrame({
        "id": store.ids,
        "batch": store.pheno["batch"].to_numpy(),
        "generation": store.pheno["generation"].to_numpy(),
        "sex": store.ped["sex"].to_numpy(),
        "gebv": np.round(model["gebv_train"], 3),
    })
    gebv_df.to_csv(run_dir / "gebv_refpop.csv", index=False)
    summary = {
        "batch_id": batch_id,
        "n_train": model["n_train"],
        "m_markers": model["m"],
        "h2_assumed": model["h2"],
        "lambda": round(model["lam"], 2),
        "sum2pq": round(model["sum2pq"], 2),
        "mu": round(model["mu"], 2),
        "gebv_sd": round(float(np.std(model["gebv_train"])), 2),
        "model_path": str(config.model_path(batch_id)),
    }
    write_json(run_dir / "retrain_summary.json", summary)
    return summary
