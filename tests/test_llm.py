"""LLM 摘要模块测试：默认 Mock 确定性；真模型失败必须如实回退并标注。"""

from __future__ import annotations

import sys

from refpop_agent.llm import summarize

FACTS = {
    "batch_id": "G1", "n_arrived": 531, "n_admitted": 500, "n_rejected": 31,
    "qc_category_counts": {"低检出率": 15, "重复送检": 5, "表型异常": 6, "系谱冲突": 5},
    "n_before": 2000, "n_after": 2500, "h2": 0.3,
    "val_mode": "forward", "r": 0.3269, "n_val": 500,
    "prev_r": 0.3186, "delta_r": 0.0083,
    "n_pairs": 150, "blocked_kinship": 12, "blocked_carrier": 3, "max_F": 0.0625,
}


def test_mock_is_default_and_deterministic(monkeypatch):
    monkeypatch.delenv("REFPOP_LLM", raising=False)
    out1 = summarize(FACTS)
    out2 = summarize(FACTS)
    assert out1["mode"] == "mock"
    assert out1["text"] == out2["text"]              # 模板确定性
    for token in ("531", "31", "500", "2500", "0.3269", "150"):
        assert token in out1["text"]                 # 摘要只引用事实中的数字


def test_anthropic_failure_falls_back_to_mock(monkeypatch):
    """真模型不可用时必须回退 Mock，并在 note 中如实标注 —— 不得静默假冒。"""
    monkeypatch.setenv("REFPOP_LLM", "anthropic")
    monkeypatch.setitem(sys.modules, "anthropic", None)   # 强制 import 失败
    out = summarize(FACTS)
    assert out["mode"] == "mock"
    assert "回退" in out["note"]
