"""QC 节点测试 —— 含核心验收：注入缺陷 100% 拦截且零误拦。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from refpop_agent.config import PipelineConfig, TRAIT
from refpop_agent.io_utils import MISSING, BatchData, RefpopStore, read_json
from refpop_agent.nodes.qc import (call_rates, evaluate_batch,
                                   genotype_concordance, opposing_hom_rate)

# ---------------------------------------------------------------- 单元测试


def test_call_rates():
    g = np.array([[0, 1, 2, MISSING], [MISSING, MISSING, 1, 2]], dtype=np.int8)
    assert np.allclose(call_rates(g), [0.75, 0.5])


def test_opposing_hom_rate():
    child = np.array([0, 2, 1, 0, MISSING], dtype=np.int8)
    parent = np.array([2, 0, 1, 0, 2], dtype=np.int8)
    rate, n = opposing_hom_rate(child, parent)
    assert n == 4                    # 最后一位子代缺失，不可比
    assert rate == 0.5               # 前两位对立纯合
    same, _ = opposing_hom_rate(parent, parent)
    assert same == 0.0


def test_genotype_concordance_duplicate_and_overlap_guard():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 3, size=(1, 1000)).astype(np.int8)
    b = a.copy()
    b[0, :5] = (b[0, :5] + 1) % 3          # 翻转 5 个位点 → 一致率 0.995
    c = rng.integers(0, 3, size=(1, 1000)).astype(np.int8)
    conc, _ = genotype_concordance(a, np.vstack([b, c]), min_overlap=200)
    assert conc[0, 0] == 0.995
    assert conc[0, 1] < 0.9
    # 覆盖不足时不判定（返回 -1 哨兵）
    a2 = a.copy(); a2[0, 100:] = MISSING   # 仅 100 个位点可比
    conc2, _ = genotype_concordance(a2, b, min_overlap=200)
    assert conc2[0, 0] == -1.0


def _mini_batch():
    """4 个体小批次：A 干净 / B 低检出率 / C 单位错误 / D 是 A 的批内重复。"""
    rng = np.random.default_rng(7)
    m = 1000
    base = rng.integers(0, 3, size=(4, m)).astype(np.int8)
    base[3] = base[0]                              # D 复制 A 的基因型
    base[1, : m // 2] = MISSING                    # B call rate 0.5
    ids = np.array(["A", "B", "C", "D"])
    pheno = pd.DataFrame({
        "id": ids,
        TRAIT: [2800.0, 2790.0, 2.81, 2820.0],     # C 疑似 kg 误录
        "submitted_at": ["2026-01-01T09:00:00", "2026-01-01T09:05:00",
                         "2026-01-01T09:10:00", "2026-01-01T10:00:00"],  # D 晚于 A
    })
    ped = pd.DataFrame({"id": ids, "sire": "", "dam": "", "sex": "M",
                        "generation": 0})
    return BatchData("T0", ids, base, pheno, ped, {})


def test_evaluate_batch_rules_and_keep_earliest():
    cfg = PipelineConfig(dup_min_overlap=200, min_mendel_informative=50)
    decisions, admitted, summary = evaluate_batch(_mini_batch(),
                                                  RefpopStore.empty(), cfg)
    d = decisions.set_index("id")
    assert admitted == ["A"]                       # 干净个体保留，且只有它
    assert "LOW_CALL_RATE" in d.loc["B", "reasons"]
    assert "PHENO_UNIT" in d.loc["C", "reasons"] and "kg" in d.loc["C", "detail"]
    assert "DUP_GENO_BATCH" in d.loc["D", "reasons"]   # 晚送检的 D 被判重复
    assert d.loc["A", "decision"] == "通过"
    assert summary["n_rejected"] == 3


def test_pedigree_checks_unit():
    """系谱四类冲突：亲本不存在 / 同批亲本 / 性别矛盾 / 孟德尔不一致。"""
    rng = np.random.default_rng(11)
    m = 1000
    ref_geno = rng.integers(0, 3, size=(2, m)).astype(np.int8)
    refpop = RefpopStore(
        ids=np.array(["S1", "D1"]),
        geno=ref_geno,
        pheno=pd.DataFrame({"id": ["S1", "D1"], TRAIT: [2800.0, 2700.0],
                            "generation": 0, "batch": "G0"}),
        ped=pd.DataFrame({"id": ["S1", "D1"], "sire": "", "dam": "",
                          "sex": ["M", "F"], "generation": 0}),
    )
    # 个体 X：真实双亲 S1×D1（按孟德尔抽样）→ 应通过
    ok_child = (rng.binomial(1, ref_geno[0] / 2.0)
                + rng.binomial(1, ref_geno[1] / 2.0)).astype(np.int8)
    # 个体 Y：基因型与双亲无关 → 孟德尔不一致
    stranger = rng.integers(0, 3, size=m).astype(np.int8)
    ids = np.array(["X", "Y", "Z", "W", "V"])
    geno = np.vstack([ok_child, stranger, ok_child, ok_child, ok_child])
    pheno = pd.DataFrame({"id": ids, TRAIT: 2800.0,
                          "submitted_at": "2026-01-01T09:00:00"})
    ped = pd.DataFrame({
        "id": ids,
        "sire": ["S1", "S1", "S1", "D1", "NOPE"],   # W 父本填了母鸡 D1；V 父本不存在
        "dam": ["D1", "D1", "V", "D1", "D1"],       # Z 母本是同批个体 V
        "sex": "M", "generation": 1,
    })
    cfg = PipelineConfig(dup_min_overlap=2000,      # 关掉重复扫描干扰
                         min_mendel_informative=50)
    decisions, admitted, _ = evaluate_batch(
        BatchData("T1", ids, geno, pheno, ped, {}), refpop, cfg)
    d = decisions.set_index("id")
    assert "X" in admitted                          # 真亲子对通过
    assert "PED_MENDEL" in d.loc["Y", "reasons"]
    assert "PED_GENERATION" in d.loc["Z", "reasons"]
    assert "PED_SEX" in d.loc["W", "reasons"]
    assert "PED_PARENT_UNKNOWN" in d.loc["V", "reasons"]


# ------------------------------------------------- 核心验收（端到端）


def test_all_injected_defects_intercepted(pipeline):
    """DEFECTS.md 注入的缺陷必须 100% 被 QC 拦截，且拦截原因包含预期结论码。"""
    config = pipeline["config"]
    defects = read_json(config.data_dir / "defects.json")
    assert len(defects) == 62                       # 31 × 2 个批次
    for batch in ("G1", "G2"):
        rep = read_json(config.run_dir(batch) / "qc_report.json")
        rejected = {r["id"]: r["reasons"] for r in rep["rejected"]}
        for d in [x for x in defects if x["batch"] == batch]:
            assert d["id"] in rejected, f"{batch} 注入缺陷 {d['id']} 未被拦截"
            assert d["expect_code"] in rejected[d["id"]], (
                f"{batch} {d['id']} 拦截原因 {rejected[d['id']]} "
                f"未包含预期 {d['expect_code']}")


def test_no_false_positives(pipeline):
    """反向验收：未注入缺陷的个体一个都不能误拦（放行名单恰好=干净名单）。"""
    config = pipeline["config"]
    defects = read_json(config.data_dir / "defects.json")
    for batch in ("G0", "G1", "G2"):
        rep = read_json(config.run_dir(batch) / "qc_report.json")
        admitted = set(read_json(config.run_dir(batch) / "admitted_ids.json"))
        import numpy as np  # noqa: F811
        z = np.load(config.batch_dir(batch) / "genotypes.npz")
        arrived = set(z["ids"].astype(str).tolist())
        defect_ids = {d["id"] for d in defects if d["batch"] == batch}
        assert admitted == arrived - defect_ids
        assert rep["n_admitted"] == len(admitted)
