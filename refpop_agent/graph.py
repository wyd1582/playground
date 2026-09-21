"""LangGraph 编排 —— 参考群更新管线。

拓扑（与业务流程一一对应）：

    START → qc ──(有合格个体)──→ merge → retrain → validate → mating → report → END
              └─(全部被拦截)──────────────────────────────────────────→ report

节点函数本身只是薄包装：真正的逻辑在 refpop_agent/nodes/*.py 中，
以 run(config, batch_id) 形式读写磁盘产物 —— 这保证了：
1) 每个节点可以脱离 LangGraph 独立单测；
2) 任何一步的输出都持久化、可审计、可复算；
3) 状态对象只携带轻量摘要，不携带大矩阵。
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .config import PipelineConfig
from .nodes import mating, merge, qc, report, retrain, validate


class PipelineState(TypedDict, total=False):
    batch_id: str
    qc: dict
    merge: dict
    retrain: dict
    validation: dict
    mating: dict
    report: dict
    halted: str   # 非空 = 流程在 QC 门禁处中止的原因


def build_graph(config: PipelineConfig):
    """按给定配置构建并编译管线图。"""

    def qc_node(state: PipelineState) -> dict:
        s = qc.run(config, state["batch_id"])
        out: dict = {"qc": s}
        if s["n_admitted"] == 0:
            out["halted"] = "QC 门禁后无合格个体，跳过合并/重训/验证/选配，仅生成报告"
        return out

    def merge_node(state: PipelineState) -> dict:
        return {"merge": merge.run(config, state["batch_id"])}

    def retrain_node(state: PipelineState) -> dict:
        return {"retrain": retrain.run(config, state["batch_id"])}

    def validate_node(state: PipelineState) -> dict:
        return {"validation": validate.run(config, state["batch_id"])}

    def mating_node(state: PipelineState) -> dict:
        return {"mating": mating.run(config, state["batch_id"])}

    def report_node(state: PipelineState) -> dict:
        return {"report": report.run(config, state["batch_id"])}

    g = StateGraph(PipelineState)
    g.add_node("qc", qc_node)
    g.add_node("merge", merge_node)
    g.add_node("retrain", retrain_node)
    g.add_node("validate", validate_node)
    g.add_node("mating", mating_node)
    g.add_node("report", report_node)

    g.add_edge(START, "qc")
    g.add_conditional_edges(
        "qc",
        lambda s: "report" if s.get("halted") else "merge",
        {"merge": "merge", "report": "report"},
    )
    g.add_edge("merge", "retrain")
    g.add_edge("retrain", "validate")
    g.add_edge("validate", "mating")
    g.add_edge("mating", "report")
    g.add_edge("report", END)
    return g.compile()


def run_batch(config: PipelineConfig, batch_id: str) -> dict:
    """处理一个到货批次，返回最终管线状态（各节点摘要）。"""
    app = build_graph(config)
    return app.invoke({"batch_id": batch_id})
