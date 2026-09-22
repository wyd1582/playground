"""LLM 摘要模块测试：默认 Mock 确定性；真模型失败/编造数字必须如实回退并标注。"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from refpop_agent.llm import check_numbers, summarize


def _stub_anthropic(reply_text: str, stop_reason: str = "end_turn"):
    """离线桩：模拟 anthropic SDK 的最小接口（测试不出网）。"""
    mod = types.ModuleType("anthropic")

    class _Messages:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(
                stop_reason=stop_reason,
                content=[SimpleNamespace(type="text", text=reply_text)])

    class Anthropic:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    mod.Anthropic = Anthropic
    return mod

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


def test_number_guard_unit():
    """数字白名单：事实内数字（含四舍五入变体）放行，事实外数字判违规。"""
    assert check_numbers("到货 531，拦截 31，r=0.3269（约 0.33），Δ+0.0083", FACTS) == []
    assert check_numbers("拦截率高达 5.8%", FACTS) == ["5.8"]      # 自行计算的比例
    assert check_numbers("第2点：情况正常", FACTS) == []            # 单个数字豁免


def test_anthropic_faithful_output_accepted(monkeypatch):
    monkeypatch.setenv("REFPOP_LLM", "anthropic")
    monkeypatch.setitem(sys.modules, "anthropic",
                        _stub_anthropic("本批 531 个个体，拦截 31 个，前向验证 r = 0.3269。"))
    out = summarize(FACTS)
    assert out["mode"] == "anthropic"
    assert "白名单" in out["note"]


def test_anthropic_fabricated_number_rejected(monkeypatch):
    """LLM 输出含事实之外的数字（编造/自行计算）→ 必须拒用并回退 Mock。"""
    monkeypatch.setenv("REFPOP_LLM", "anthropic")
    monkeypatch.setitem(sys.modules, "anthropic",
                        _stub_anthropic("拦截率 97.5%，前向 r = 0.3269，效果极佳。"))
    out = summarize(FACTS)
    assert out["mode"] == "mock"
    assert "数字" in out["note"] and "回退" in out["note"]


def test_anthropic_refusal_falls_back(monkeypatch):
    monkeypatch.setenv("REFPOP_LLM", "anthropic")
    monkeypatch.setitem(sys.modules, "anthropic",
                        _stub_anthropic("", stop_reason="refusal"))
    out = summarize(FACTS)
    assert out["mode"] == "mock"
    assert "回退" in out["note"]
