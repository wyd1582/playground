#!/usr/bin/env python3
"""低密度SKU可行性实验 — E1 密度曲线 / E2 掩码填补 / E3 经济学合成。

数据: BGLR wheat (CIMMYT 599 系 x 1279 DArT 标记, 0/1 编码),
表型 = 籽粒产量 ENV1 (已标准化)。
降级声明: 首选 Cleveland 猪数据 (G3 2012, 3534 x ~52843) 的托管源
(figshare / 期刊补充材料) 在本执行环境的网络出口策略下不可达, 且无
Task A 缓存可复用, 故按任务预案降级为 BGLR wheat。

用法: python3 experiments.py <wheat_X.npy> <wheat_Y.npy> <outdir>
输出: density_curve.csv, imputation_table.csv, cost_table.csv, results.json
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold

ALPHAS = np.logspace(-1, 6, 50)
SEEDS = [1, 2, 3]
N_FOLDS = 5
ENV = 0  # 籽粒产量 ENV1 (BGLR 惯例示例表型)
LD_PANEL_SIZE = 500  # E2 低密度档位
KNN_K = 20
MASK_SHARES = [0.3, 0.5, 0.7]
# 成本均为【假设占位值】(归一化), 真实价格留待客户数据:
COST_HD = 100.0
COST_LD = 30.0
SPEC_GRID = [200, 500, 1000, 2000, 5000]  # 任务书网格(为5万标记数据设计)
EXTRA_GRID = [50, 100, 300, 800]  # wheat 仅1279标记, 补充小密度点使曲线可读


def cv_pred_r(X, y, seed):
    """5折交叉验证的袋外预测相关 r; 每折内 RidgeCV(GCV) 自选 alpha。"""
    kf = KFold(N_FOLDS, shuffle=True, random_state=seed)
    yhat = np.empty_like(y)
    for tr, te in kf.split(X):
        model = RidgeCV(alphas=ALPHAS, fit_intercept=True).fit(X[tr], y[tr])
        yhat[te] = model.predict(X[te])
    return float(np.corrcoef(y, yhat)[0, 1])


def run_e1(X, y):
    n, p = X.shape
    grid = sorted(set(g for g in SPEC_GRID + EXTRA_GRID if g < p)) + [p]
    rows = []
    for m in grid:
        rs = []
        for seed in SEEDS:
            rng = np.random.default_rng(seed)
            cols = np.arange(p) if m == p else rng.choice(p, m, replace=False)
            rs.append(cv_pred_r(X[:, cols], y, seed))
        rows.append({
            "n_markers": m,
            "is_full": m == p,
            "in_spec_grid": (m in SPEC_GRID) or m == p,
            "r_mean": np.mean(rs),
            "r_std": np.std(rs, ddof=1),
            "r_per_seed": rs,
        })
    df = pd.DataFrame(rows)
    full_r = df.loc[df.is_full, "r_mean"].iloc[0]
    df["pct_of_full"] = df.r_mean / full_r * 100
    return df, full_r


def knn_impute(X, ld_idx, hd_idx, panel, nonpanel):
    """对 LD 个体: 在面板标记上找 k 个最近 HD 个体, 以其均值回填非面板标记。"""
    d2 = ((X[np.ix_(ld_idx, panel)][:, None, :]
           - X[np.ix_(hd_idx, panel)][None, :, :]) ** 2).sum(axis=2)
    nb = np.argpartition(d2, KNN_K, axis=1)[:, :KNN_K]
    X_hd_np = X[np.ix_(hd_idx, nonpanel)]
    return X_hd_np[nb].mean(axis=1)  # (n_ld, n_nonpanel) 剂量值∈[0,1]


def run_e2(X, y, full_r_per_seed):
    n, p = X.shape
    rows = []
    for share in MASK_SHARES:
        for seed in SEEDS:
            rng = np.random.default_rng(seed)
            panel = rng.choice(p, LD_PANEL_SIZE, replace=False)
            nonpanel = np.setdiff1d(np.arange(p), panel)
            rng2 = np.random.default_rng(1000 * seed + int(share * 100))
            ld_idx = rng2.choice(n, int(round(share * n)), replace=False)
            hd_idx = np.setdiff1d(np.arange(n), ld_idx)
            truth = X[np.ix_(ld_idx, nonpanel)]

            imputations = {
                "col_mean": np.broadcast_to(
                    X[np.ix_(hd_idx, nonpanel)].mean(axis=0), truth.shape),
                "knn_k20": knn_impute(X, ld_idx, hd_idx, panel, nonpanel),
            }
            for method, imp in imputations.items():
                X_imp = X.copy()
                X_imp[np.ix_(ld_idx, nonpanel)] = imp
                r_imp = cv_pred_r(X_imp, y, seed)
                r_full = full_r_per_seed[seed]
                rows.append({
                    "mask_share": share,
                    "seed": seed,
                    "method": method,
                    "geno_accuracy": float((np.where(imp > 0.5, 1.0, 0.0)
                                            == truth).mean()),
                    "geno_dosage_r": float(np.corrcoef(
                        imp.ravel(), truth.ravel())[0, 1]),
                    "pred_r": r_imp,
                    "pred_r_full_same_seed": r_full,
                    "pred_r_loss": r_full - r_imp,
                })
    df = pd.DataFrame(rows)
    agg = (df.groupby(["mask_share", "method"])
             .agg(geno_accuracy_mean=("geno_accuracy", "mean"),
                  geno_accuracy_std=("geno_accuracy", "std"),
                  geno_dosage_r_mean=("geno_dosage_r", "mean"),
                  pred_r_mean=("pred_r", "mean"),
                  pred_r_std=("pred_r", "std"),
                  pred_r_loss_mean=("pred_r_loss", "mean"))
             .reset_index())
    return df, agg


def run_e3(e1_df, e2_agg, full_r):
    r_ld500 = e1_df.loc[e1_df.n_markers == LD_PANEL_SIZE, "r_mean"].iloc[0]
    rows = [
        {"scheme": "全体高密度(全量1279标记)", "cost_per_ind": COST_HD, "r": full_r},
        {"scheme": f"全体低密度({LD_PANEL_SIZE}标记, 不填补)",
         "cost_per_ind": COST_LD, "r": r_ld500},
    ]
    for share in MASK_SHARES:
        for method, label in [("knn_k20", "KNN填补"), ("col_mean", "均值填补")]:
            sub = e2_agg[(e2_agg.mask_share == share)
                         & (e2_agg.method == method)]
            rows.append({
                "scheme": f"{int(share*100)}%个体低密度+{label}",
                "cost_per_ind": share * COST_LD + (1 - share) * COST_HD,
                "r": float(sub.pred_r_mean.iloc[0]),
            })
    df = pd.DataFrame(rows)
    df["pct_of_full_r"] = df.r / full_r * 100
    df["cost_saving_pct"] = (1 - df.cost_per_ind / COST_HD) * 100
    df["cost_per_unit_r"] = df.cost_per_ind / df.r
    df["cost_note"] = "成本为假设占位值(HD=100, LD=30, 归一化)"
    return df


def main():
    x_path, y_path, outdir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)
    X = np.load(x_path)
    Y = np.load(y_path)
    assert X.shape == (599, 1279), f"wheat 维度校验失败: {X.shape}"
    assert set(np.unique(X)) == {0.0, 1.0}, "wheat 基因型应为0/1编码"
    y = Y[:, ENV].copy()

    e1_df, full_r = run_e1(X, y)
    full_r_per_seed = dict(zip(
        SEEDS, e1_df.loc[e1_df.is_full, "r_per_seed"].iloc[0]))
    print("E1 done\n", e1_df.drop(columns="r_per_seed").to_string(index=False))

    e2_df, e2_agg = run_e2(X, y, full_r_per_seed)
    print("E2 done\n", e2_agg.to_string(index=False))
    # 自检: KNN 填补应显著优于均值填补
    for share in MASK_SHARES:
        a = e2_agg[(e2_agg.mask_share == share) & (e2_agg.method == "knn_k20")]
        b = e2_agg[(e2_agg.mask_share == share) & (e2_agg.method == "col_mean")]
        ok = a.geno_accuracy_mean.iloc[0] > b.geno_accuracy_mean.iloc[0]
        print(f"QA share={share}: KNN acc {a.geno_accuracy_mean.iloc[0]:.4f} "
              f"vs mean acc {b.geno_accuracy_mean.iloc[0]:.4f} -> "
              f"{'OK' if ok else '!!! KNN未优于均值, 需检查实现'}")

    e3_df = run_e3(e1_df, e2_agg, full_r)
    print("E3 done\n", e3_df.to_string(index=False))

    e1_out = e1_df.copy()
    e1_out["r_per_seed"] = e1_out.r_per_seed.apply(
        lambda v: ";".join(f"{x:.4f}" for x in v))
    e1_out.to_csv(outdir / "density_curve.csv", index=False)
    e2_detail = outdir / "imputation_table_per_seed.csv"
    e2_df.to_csv(e2_detail, index=False)
    e2_agg.to_csv(outdir / "imputation_table.csv", index=False)
    e3_df.to_csv(outdir / "cost_table.csv", index=False)

    sat95 = e1_df[e1_df.pct_of_full >= 95].n_markers.min()
    sat90 = e1_df[e1_df.pct_of_full >= 90].n_markers.min()
    results = {
        "dataset": "BGLR wheat (599 x 1279 DArT, trait=grain yield ENV1)",
        "downgrade": ("Cleveland pig 源不可达(网络策略), 无Task A缓存, "
                      "降级 BGLR wheat"),
        "spec_grid_note": ("任务网格{200,500,1000,2000,5000,全量}中 2000/5000 "
                           "超出wheat总标记数1279, 不适用; 另补充小密度点"
                           f"{EXTRA_GRID}"),
        "n": 599, "p": 1279, "seeds": SEEDS, "n_folds": N_FOLDS,
        "model": "RidgeCV (5-fold outer CV, GCV选alpha, alpha∈logspace(-1,6))",
        "full_r_mean": full_r,
        "saturation_95pct_markers": int(sat95),
        "saturation_90pct_markers": int(sat90),
        "ld_panel_size": LD_PANEL_SIZE, "knn_k": KNN_K,
        "cost_assumption": {"HD": COST_HD, "LD": COST_LD,
                            "note": "假设占位值, 真实价格留待客户数据"},
        "e1": json.loads(e1_out.to_json(orient="records")),
        "e2": json.loads(e2_agg.to_json(orient="records")),
        "e3": json.loads(e3_df.to_json(orient="records")),
    }
    (outdir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nSaved to {outdir}: density_curve.csv, imputation_table.csv, "
          f"imputation_table_per_seed.csv, cost_table.csv, results.json")


if __name__ == "__main__":
    main()
