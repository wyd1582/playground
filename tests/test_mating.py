"""选配节点测试：近交约束、携带者规则、公鸡配额 —— 单元 + 端到端复算。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from refpop_agent.config import PipelineConfig
from refpop_agent.io_utils import load_refpop, read_json
from refpop_agent.nodes.mating import genomic_kinship, greedy_mate
from refpop_agent.nodes.retrain import load_model


def test_greedy_mate_constraints_unit():
    """三类约束逐一生效：近交拦截、携带者×携带者禁配、公鸡配额。"""
    cand = pd.DataFrame({
        "idx": [0, 1, 2, 3],
        "id": ["M1", "M2", "F1", "F2"],
        "sex": ["M", "M", "F", "F"],
        "gebv": [10.0, 8.0, 9.0, 7.0],
    })
    kin = np.zeros((4, 4))
    kin[0, 2] = kin[2, 0] = 0.2          # M1×F1 预期后代 F 超标
    carriers = {"L1": np.array([True, False, False, True])}  # M1、F2 为携带者
    cfg = PipelineConfig(n_sires=2, n_dams=2, max_dams_per_sire=1,
                         max_progeny_inbreeding=0.0625)
    pairs, stats = greedy_mate(cand, kin, carriers, cfg)
    assert [(p["sire"], p["dam"]) for p in pairs] == [("M2", "F1")]
    assert stats["blocked_kinship_attempts"] == 1    # M1×F1 被近交拦下
    assert stats["blocked_carrier_attempts"] == 1    # M1×F2 被携带者规则拦下
    assert stats["unassigned_dams"] == ["F2"]        # M2 配额满，F2 无鸡可配


def test_pipeline_pairs_respect_all_rules(pipeline):
    """端到端：所有建议配对逐一复算 F 与携带者状态，约束必须全部满足。"""
    config: PipelineConfig = pipeline["config"]
    store = load_refpop(config.refpop_dir())
    markers = read_json(config.markers_path())
    lethal = {loc["name"]: int(loc["index"]) for loc in markers["lethal_loci"]}
    row_of = {v: k for k, v in enumerate(store.ids.tolist())}
    sex_of = dict(zip(store.ped["id"].tolist(), store.ped["sex"].tolist()))

    for batch in ("G0", "G1", "G2"):
        model = load_model(config.model_path(batch))
        pairs = pd.read_csv(config.run_dir(batch) / "mating_pairs.csv",
                            dtype={"sire": str, "dam": str})
        assert len(pairs) > 0
        summary = read_json(config.run_dir(batch) / "mating_summary.json")
        assert summary["n_pairs"] == len(pairs)
        sire_load = pairs["sire"].value_counts()
        assert int(sire_load.max()) <= config.max_dams_per_sire
        idx = np.array([[row_of[s], row_of[d]]
                        for s, d in zip(pairs["sire"], pairs["dam"])])
        used = np.unique(idx)
        sub_kin = genomic_kinship(store.geno[used], model["p"], model["sum2pq"])
        pos = {int(g): k for k, g in enumerate(used)}
        for (s, d), f_csv in zip(idx, pairs["expected_progeny_F"]):
            assert sex_of[store.ids[s]] == "M" and sex_of[store.ids[d]] == "F"
            f = float(sub_kin[pos[s], pos[d]])
            assert abs(f - f_csv) < 1e-3             # 报表中的 F 可复算
            assert f <= config.max_progeny_inbreeding + 1e-9
            for name, li in lethal.items():          # 携带者×携带者禁配
                assert not (store.geno[s, li] == 1 and store.geno[d, li] == 1), (
                    f"{batch} 配对 {store.ids[s]}×{store.ids[d]} 在 {name} 上双携带")
