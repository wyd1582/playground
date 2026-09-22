"""LangGraph 编排测试：全流程状态完整、各节点产物齐备、门禁中止路径可用。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from refpop_agent.config import PipelineConfig, TRAIT
from refpop_agent.graph import build_graph, run_batch
from refpop_agent.io_utils import MISSING, read_json, save_batch


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


def test_halted_path_when_all_rejected(tmp_path, monkeypatch):
    """QC 全拦截 → 条件边直达 report：跳过合并/重训/选配，但报告必须照出。"""
    monkeypatch.setenv("REFPOP_LLM", "mock")
    config = PipelineConfig(data_dir=tmp_path / "data",
                            artifacts_dir=tmp_path / "artifacts",
                            reports_dir=tmp_path / "reports")
    ids = np.array(["X1", "X2", "X3"])
    geno = np.full((3, 600), MISSING, dtype=np.int8)   # 检出率 0 → 全部被拦
    pheno = pd.DataFrame({"id": ids, TRAIT: 2800.0,
                          "submitted_at": "2026-01-01T09:00:00"})
    ped = pd.DataFrame({"id": ids, "sire": "", "dam": "", "sex": "M",
                        "generation": 0})
    save_batch(config.batch_dir("G0"), ids, geno, pheno, ped,
               {"batch_id": "G0", "simulated": True, "arrival_date": "2026-01-01"})
    state = run_batch(config, "G0")
    assert state["halted"]
    assert state["qc"]["n_admitted"] == 0
    for skipped in ("merge", "retrain", "validation", "mating"):
        assert skipped not in state                    # 中止路径确实跳过了这些节点
    html = config.report_path("G0").read_text(encoding="utf-8")
    assert "None" not in html                          # 摘要/指标不得漏出 None
    summary = read_json(config.run_dir("G0") / "summary.json")
    assert "None" not in summary["llm"]["text"]
    assert "中止" in summary["llm"]["text"]
