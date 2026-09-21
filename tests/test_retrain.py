"""重训节点测试：ridge 对偶解与原始解恒等（GBLUP 等价形式的数学正确性）。"""

from __future__ import annotations

import numpy as np

from refpop_agent.config import PipelineConfig
from refpop_agent.io_utils import read_json
from refpop_agent.nodes.retrain import (allele_freq, center_genotypes,
                                        fit_gblup, load_model, predict_gebv)


def test_ridge_dual_equals_primal():
    """û = Z'(ZZ'+λI)⁻¹yc 必须等于 (Z'Z+λI)⁻¹Z'yc（推导正确性）。"""
    rng = np.random.default_rng(3)
    n, m, h2 = 12, 7, 0.3
    geno = rng.integers(0, 3, size=(n, m)).astype(np.int8)
    y = rng.normal(3000, 100, n)
    model = fit_gblup(geno, y, h2)
    p = allele_freq(geno)
    Z = center_genotypes(geno, p)
    yc = y - y.mean()
    u_primal = np.linalg.solve(Z.T @ Z + model["lam"] * np.eye(m), Z.T @ yc)
    assert np.allclose(model["u"], u_primal, atol=1e-8)
    assert np.allclose(predict_gebv(model, geno), Z @ u_primal, atol=1e-8)


def test_missing_imputed_to_mean():
    """缺失基因型填补为 2p（中心化后为 0），不影响其他位点。"""
    geno = np.array([[0, 1, 2], [2, 1, 0], [1, -1, 1]], dtype=np.int8)
    p = allele_freq(geno)
    Z = center_genotypes(geno, p)
    assert Z[2, 1] == 0.0
    assert np.allclose(Z[0], geno[0] - 2 * p)


def test_lambda_formula():
    rng = np.random.default_rng(4)
    geno = rng.integers(0, 3, size=(20, 10)).astype(np.int8)
    y = rng.normal(0, 1, 20)
    h2 = 0.25
    model = fit_gblup(geno, y, h2)
    assert np.isclose(model["lam"], model["sum2pq"] * (1 - h2) / h2)


def test_pipeline_models_saved(pipeline):
    config: PipelineConfig = pipeline["config"]
    for batch, n_train in (("G0", 2000), ("G1", 2500), ("G2", 3000)):
        meta = read_json(config.model_meta_path(batch))
        assert meta["n_train"] == n_train and meta["m"] == 5000
        model = load_model(config.model_path(batch))
        assert model["u"].shape == (5000,)
        s = read_json(config.run_dir(batch) / "retrain_summary.json")
        assert s["n_train"] == n_train
        assert s["h2_assumed"] == config.h2
