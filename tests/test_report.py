"""报告节点测试：数字与磁盘产物一致、拦截明细齐全、Mock 与模拟数据如实标注。"""

from __future__ import annotations

import re

from refpop_agent.config import PipelineConfig
from refpop_agent.io_utils import read_json


def _metric(html: str, metric_id: str) -> str:
    m = re.search(rf'id="{metric_id}">([^<]+)<', html)
    assert m, f"报告缺少指标 {metric_id}"
    return m.group(1)


def test_reports_exist_and_numbers_match_artifacts(pipeline):
    config: PipelineConfig = pipeline["config"]
    for batch in ("G0", "G1", "G2"):
        html = config.report_path(batch).read_text(encoding="utf-8")
        qc = read_json(config.run_dir(batch) / "qc_report.json")
        merge = read_json(config.run_dir(batch) / "merge_summary.json")
        val = read_json(config.run_dir(batch) / "validation.json")
        assert _metric(html, "metric-arrived") == str(qc["n_arrived"])
        assert _metric(html, "metric-rejected") == str(qc["n_rejected"])
        assert _metric(html, "metric-admitted") == str(qc["n_admitted"])
        assert _metric(html, "metric-refpop-after") == str(merge["n_after"])
        assert _metric(html, "metric-r") == f"{val['r']:.3f}"


def test_all_rejected_ids_listed_in_report(pipeline):
    """拦截明细"谁被拦、为什么"：每个被拦个体的 ID 必须出现在报告里。"""
    config: PipelineConfig = pipeline["config"]
    for batch in ("G1", "G2"):
        html = config.report_path(batch).read_text(encoding="utf-8")
        qc = read_json(config.run_dir(batch) / "qc_report.json")
        assert len(qc["rejected"]) == 31
        for r in qc["rejected"]:
            assert r["id"] in html, f"{batch} 报告缺少被拦个体 {r['id']}"
            assert r["reasons"][0] in html


def test_honesty_labels(pipeline):
    """诚实性：模拟数据横幅 + Mock 摘要标注必须出现在报告与 summary.json 中。"""
    config: PipelineConfig = pipeline["config"]
    for batch in ("G0", "G1", "G2"):
        html = config.report_path(batch).read_text(encoding="utf-8")
        assert "演示原型" in html and "模拟生成" in html
        assert "Mock" in html                       # 默认摘要为 Mock，且如实标注
        assert "假设值" in html                     # h² 假设值标注
        summary = read_json(config.run_dir(batch) / "summary.json")
        assert summary["llm"]["mode"] == "mock"
        assert summary["llm"]["text"]               # 摘要非空


def test_summary_json_consistent(pipeline):
    config: PipelineConfig = pipeline["config"]
    for batch in ("G1", "G2"):
        summary = read_json(config.run_dir(batch) / "summary.json")
        qc = read_json(config.run_dir(batch) / "qc_report.json")
        assert summary["qc"]["n_arrived"] == qc["n_arrived"] == 531
        assert summary["qc"]["n_rejected"] == qc["n_rejected"] == 31
        cat = summary["facts"]["qc_category_counts"]
        assert sum(cat.values()) == 31              # 按主因分类计数守恒
