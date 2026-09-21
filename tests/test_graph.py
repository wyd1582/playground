"""LangGraph 编排测试：全流程状态完整、各节点产物齐备。"""

from __future__ import annotations

from refpop_agent.config import PipelineConfig
from refpop_agent.graph import build_graph


def test_graph_compiles():
    app = build_graph(PipelineConfig())
    nodes = set(app.get_graph().nodes)
    assert {"qc", "merge", "retrain", "validate", "mating", "report"} <= nodes


def test_pipeline_states_complete(pipeline):
    config: PipelineConfig = pipeline["config"]
    for batch, state in pipeline["states"].items():
        assert "halted" not in state, f"{batch} 意外中止：{state.get('halted')}"
        for key in ("qc", "merge", "retrain", "validation", "mating", "report"):
            assert key in state, f"{batch} 缺少节点输出 {key}"
        assert config.report_path(batch).exists()
        assert state["report"]["llm_mode"] == "mock"
