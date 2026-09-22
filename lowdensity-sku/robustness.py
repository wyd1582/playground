#!/usr/bin/env python3
"""稳健性附录: 在 wheat 其余 3 个环境 (ENV2-4) 上复核主结论。

复核两点: (1) E1 关键密度点 (200/500/800/全量) 的精度保留率;
(2) E2 各占比下 KNN vs 均值填补的预测精度。
掩码/面板/填补由种子决定、与表型无关, 故基因型还原指标与 ENV1 相同,
此处只报预测精度。

用法: python3 robustness.py <wheat_X.npy> <wheat_Y.npy> <outdir>
输出: robustness_envs.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import experiments as ex

CORE_DENSITIES = [200, 500, 800]


def main():
    x_path, y_path, outdir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    X = np.load(x_path)
    Y = np.load(y_path)
    assert X.shape == (599, 1279)
    n, p = X.shape
    rows = []
    for env in range(Y.shape[1]):
        y = Y[:, env].copy()
        # E1 关键密度点
        full_rs = [ex.cv_pred_r(X, y, seed) for seed in ex.SEEDS]
        full_mean = float(np.mean(full_rs))
        rows.append({"env": env + 1, "item": "density_full", "method": "",
                     "r_mean": full_mean,
                     "r_std": float(np.std(full_rs, ddof=1)),
                     "pct_of_full_env": 100.0})
        for m in CORE_DENSITIES:
            rs = []
            for seed in ex.SEEDS:
                rng = np.random.default_rng(seed)
                cols = rng.choice(p, m, replace=False)
                rs.append(ex.cv_pred_r(X[:, cols], y, seed))
            rows.append({"env": env + 1, "item": f"density_{m}", "method": "",
                         "r_mean": float(np.mean(rs)),
                         "r_std": float(np.std(rs, ddof=1)),
                         "pct_of_full_env": float(np.mean(rs)) / full_mean * 100})
        # E2 填补 (基因型指标与环境无关, 只看预测精度)
        full_per_seed = dict(zip(ex.SEEDS, full_rs))
        _, agg = ex.run_e2(X, y, full_per_seed)
        for _, r in agg.iterrows():
            rows.append({"env": env + 1,
                         "item": f"impute_{int(r.mask_share*100)}pct",
                         "method": r.method,
                         "r_mean": float(r.pred_r_mean),
                         "r_std": float(r.pred_r_std),
                         "pct_of_full_env": float(r.pred_r_mean) / full_mean * 100})
        print(f"ENV{env+1} done: full r={full_mean:.3f}")
    df = pd.DataFrame(rows)
    df.to_csv(outdir / "robustness_envs.csv", index=False)
    # 摘要
    for item in ["density_500", "density_800"]:
        sub = df[df.item == item]
        print(item, "pct_of_full range:",
              f"{sub.pct_of_full_env.min():.1f}–{sub.pct_of_full_env.max():.1f}%")
    for share in [30, 50, 70]:
        knn = df[(df.item == f"impute_{share}pct") & (df.method == "knn_k20")]
        mean = df[(df.item == f"impute_{share}pct") & (df.method == "col_mean")]
        wins = int((knn.pct_of_full_env.values > mean.pct_of_full_env.values).sum())
        print(f"impute_{share}pct: KNN retained "
              f"{knn.pct_of_full_env.min():.1f}–{knn.pct_of_full_env.max():.1f}% "
              f"vs mean {mean.pct_of_full_env.min():.1f}–{mean.pct_of_full_env.max():.1f}%"
              f" | KNN wins {wins}/{len(knn)} envs")


if __name__ == "__main__":
    main()
