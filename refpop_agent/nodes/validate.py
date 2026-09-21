"""验证节点 —— 前向验证。确定性、可单测。

前向验证定义（与任务规格一致）：用【上一代为止】训练的模型（model_G{n-1}）
预测本批次个体的【真实观测表型】，r = Pearson(GEBV, y)。
G0 没有上一代，用固定种子的 5 折交叉验证给出基线 r（口径不同，报告中明确标注）。

同时（仅模拟环境可得）对比 GEBV 与真实育种值 TBV 的相关 r_tbv —— 生产中
不存在 TBV 文件，此指标会自动缺省；报告中明确标注"仅模拟可得"。

逐个体预测值落盘 predictions.csv，报告中的 r 可由它复算（测试有断言）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import BATCH_SEQUENCE, PipelineConfig, TRAIT, prev_batch
from ..io_utils import load_refpop, now_iso, read_json, read_table, write_json
from .retrain import fit_gblup, load_model, predict_gebv

CV_SEED = 4711   # 交叉验证分折种子（与数据模拟种子无关，固定保证可复现）
CV_FOLDS = 5


def pearson(a, b) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def regression_slope(y, x) -> float:
    """b = cov(y,x)/var(x)：GEBV 无偏时约为 1（校准诊断）。

    注意 cov 与 var 必须用同一自由度（这里都用 ddof=1），否则斜率会被放大 n/(n-1)。
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    vx = np.var(x, ddof=1)
    return float(np.cov(y, x)[0, 1] / vx) if vx > 0 else float("nan")


def _truth_map(config: PipelineConfig, batch_id: str) -> dict[str, float]:
    path = config.truth_path(batch_id)
    if not path.exists():
        return {}
    df = read_table(path, str_cols=("id",))
    return dict(zip(df["id"].tolist(), df["tbv"].astype(float).tolist()))


def run(config: PipelineConfig, batch_id: str) -> dict:
    store = load_refpop(config.refpop_dir())
    run_dir = config.run_dir(batch_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    mask = (store.pheno["batch"] == batch_id).to_numpy()
    ids_b = store.ids[mask]
    geno_b = store.geno[mask]
    y_b = store.pheno.loc[mask, TRAIT].to_numpy(dtype=float)
    truth = _truth_map(config, batch_id)

    prev = prev_batch(batch_id)
    if prev is None:
        # ---- G0：5 折交叉验证基线（此时参考群 = 本批全部个体）----
        rng = np.random.default_rng(CV_SEED)
        order = rng.permutation(store.n)
        folds = np.array_split(order, CV_FOLDS)
        pred = np.full(store.n, np.nan)
        fold_of = np.full(store.n, -1)
        per_fold_r = []
        y_all = store.pheno[TRAIT].to_numpy(dtype=float)
        for f, test_idx in enumerate(folds):
            train_idx = np.setdiff1d(order, test_idx)
            model = fit_gblup(store.geno[train_idx], y_all[train_idx], config.h2)
            pred[test_idx] = predict_gebv(model, store.geno[test_idx])
            fold_of[test_idx] = f
            per_fold_r.append(round(pearson(pred[test_idx], y_all[test_idx]), 4))
        r = pearson(pred, y_all)
        slope = regression_slope(y_all, pred)
        tbv = np.array([truth.get(i, np.nan) for i in store.ids])
        r_tbv = pearson(pred[~np.isnan(tbv)], tbv[~np.isnan(tbv)]) if truth else None
        pd.DataFrame({
            "id": store.ids, "fold": fold_of,
            "y_obs": y_all, "gebv_cv": np.round(pred, 3),
            "tbv_sim": np.round(tbv, 3),
        }).to_csv(run_dir / "predictions.csv", index=False)
        result = {
            "batch_id": batch_id,
            "mode": "cv",
            "mode_label": f"{CV_FOLDS} 折交叉验证（G0 基线，口径与前向验证不同）",
            "r": round(r, 4),
            "per_fold_r": per_fold_r,
            "slope": round(slope, 3),
            "n_val": int(store.n),
            "train_model": None,
        }
    else:
        # ---- 前向验证：上一代模型 → 本批真实表型 ----
        model_prev = load_model(config.model_path(prev))
        gebv = predict_gebv(model_prev, geno_b)
        r = pearson(gebv, y_b)
        slope = regression_slope(y_b, gebv)
        tbv = np.array([truth.get(i, np.nan) for i in ids_b])
        has_tbv = ~np.isnan(tbv)
        r_tbv = pearson(gebv[has_tbv], tbv[has_tbv]) if truth else None
        pd.DataFrame({
            "id": ids_b,
            "y_obs": y_b,
            "gebv_prev_model": np.round(gebv, 3),
            "tbv_sim": np.round(tbv, 3),
        }).to_csv(run_dir / "predictions.csv", index=False)
        result = {
            "batch_id": batch_id,
            "mode": "forward",
            "mode_label": f"前向验证：用 {prev} 为止训练的模型预测本批真实表型",
            "r": round(r, 4),
            "slope": round(slope, 3),
            "n_val": int(len(y_b)),
            "train_model": {"batch": prev, "n_train": model_prev["n_train"]},
        }

    if r_tbv is not None:
        result["r_tbv_sim"] = round(r_tbv, 4)
        result["r_tbv_note"] = "GEBV 与真实育种值 TBV 的相关 —— 仅模拟环境可得，生产中无此指标"

    write_json(run_dir / "validation.json", result)

    # ---- 更新跨代 r 历史（报告画趋势 + 与上一代对比用）----
    hp = config.history_path()
    history = read_json(hp) if hp.exists() else []
    history = [h for h in history if h.get("batch_id") != batch_id]  # 重跑覆盖
    history.append({
        "batch_id": batch_id,
        "mode": result["mode"],
        "r": result["r"],
        "r_tbv_sim": result.get("r_tbv_sim"),
        "n_val": result["n_val"],
        "refpop_n_after": int(store.n),
        "train_n": (result["train_model"] or {}).get("n_train"),
        "at": now_iso(),
    })
    history.sort(key=lambda h: BATCH_SEQUENCE.index(h["batch_id"]))
    write_json(hp, history)
    return result
