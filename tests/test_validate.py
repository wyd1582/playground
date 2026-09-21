"""验证节点测试 —— 验收项：前向 r ∈ [0.3, 0.7] 且随参考群扩大非降；r 可复算。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from refpop_agent.config import PipelineConfig
from refpop_agent.io_utils import read_json
from refpop_agent.nodes.validate import pearson, regression_slope


def test_pearson_and_slope_unit():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert np.isclose(pearson(x, 2 * x + 1), 1.0)
    assert np.isclose(regression_slope(2 * x + 1, x), 2.0)
    assert np.isnan(pearson(x, np.ones(4)))         # 零方差保护


def test_forward_r_in_range_and_nondecreasing(pipeline):
    """核心验收：0.3 ≤ r ≤ 0.7；参考群 2000→2500 后 r 非降。"""
    config: PipelineConfig = pipeline["config"]
    history = read_json(config.history_path())
    assert [h["batch_id"] for h in history] == ["G0", "G1", "G2"]
    fwd = [h for h in history if h["mode"] == "forward"]
    assert len(fwd) == 2
    for h in fwd:
        assert 0.3 <= h["r"] <= 0.7, f"{h['batch_id']} 前向 r={h['r']} 超出合理区间"
        assert h["n_val"] == 500
    assert fwd[1]["r"] >= fwd[0]["r"], "前向 r 未随参考群扩大保持非降"
    assert fwd[0]["train_n"] == 2000 and fwd[1]["train_n"] == 2500
    cv = history[0]
    assert cv["mode"] == "cv" and 0.3 <= cv["r"] <= 0.7


def test_r_recomputable_from_predictions(pipeline):
    """报告中的 r 必须能从落盘的逐个体预测值复算（诚实性验收）。"""
    config: PipelineConfig = pipeline["config"]
    for batch, col in (("G0", "gebv_cv"), ("G1", "gebv_prev_model"),
                       ("G2", "gebv_prev_model")):
        val = read_json(config.run_dir(batch) / "validation.json")
        df = pd.read_csv(config.run_dir(batch) / "predictions.csv")
        r = pearson(df[col].to_numpy(), df["y_obs"].to_numpy())
        assert abs(round(r, 4) - val["r"]) <= 1e-4
        assert len(df) == val["n_val"]


def test_r_tbv_only_in_simulation(pipeline):
    """r(GEBV,TBV) 必须标注"仅模拟可得"（生产中不存在 TBV）。"""
    config: PipelineConfig = pipeline["config"]
    val = read_json(config.run_dir("G2") / "validation.json")
    assert "r_tbv_sim" in val and "仅模拟" in val["r_tbv_note"]
