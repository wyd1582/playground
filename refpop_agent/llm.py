"""LLM 摘要模块 —— 整条管线中唯一可能调用 LLM 的地方。

诚实性设计原则：
- LLM 只做一件事：把确定性节点落盘的结构化事实（facts JSON）改写成一段中文
  运行摘要。它不做任何计算；报告中所有数字以表格与磁盘产物为准。
- 默认 Mock：模板确定性生成，离线可跑、可单测；报告中明确标注"Mock（模板生成）"。
- 切换真模型：设置环境变量 REFPOP_LLM=anthropic（需 `pip install anthropic`
  并配置 ANTHROPIC_API_KEY）。任何调用失败都自动回退 Mock，并在报告中如实
  标注回退原因 —— 绝不静默假装是模型输出。

环境变量：
  REFPOP_LLM        mock（默认）| anthropic
  REFPOP_LLM_MODEL  默认 claude-opus-5
"""

from __future__ import annotations

import json
import os

DEFAULT_MODEL = "claude-opus-5"

_SYSTEM_PROMPT = (
    "你是育种数据分析助手。仅依据用户提供的 JSON 事实，撰写一段 120～220 字的"
    "中文运行摘要，面向育种场技术负责人。要求：只引用 JSON 中出现的数字，"
    "禁止编造任何数字、比例或结论；不做任何计算或推断；语气专业、克制；"
    "输出纯文本一个自然段，不使用 markdown。"
)


def summarize(facts: dict) -> dict:
    """把结构化事实改写为中文摘要段。

    返回 {"text", "mode": "mock"|"anthropic", "model", "note"}。
    """
    mode = os.environ.get("REFPOP_LLM", "mock").strip().lower()
    if mode == "anthropic":
        try:
            return _anthropic_summary(facts)
        except Exception as exc:  # 任何失败都回退 Mock，并如实标注
            return {
                "text": _mock_summary(facts),
                "mode": "mock",
                "model": None,
                "note": f"真实 LLM 调用失败，已回退 Mock 模板：{type(exc).__name__}: {exc}",
            }
    return {"text": _mock_summary(facts), "mode": "mock", "model": None,
            "note": "默认 Mock 模式（REFPOP_LLM=anthropic 可切换真模型）"}


def _anthropic_summary(facts: dict) -> dict:
    import anthropic  # 可选依赖，仅真模型模式需要

    model = os.environ.get("REFPOP_LLM_MODEL", DEFAULT_MODEL)
    client = anthropic.Anthropic(timeout=60.0, max_retries=1)
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "请依据以下事实撰写摘要：\n" + json.dumps(facts, ensure_ascii=False),
        }],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("模型拒绝了本次请求（stop_reason=refusal）")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("模型未返回文本内容")
    return {"text": text, "mode": "anthropic", "model": model,
            "note": "摘要由 LLM 起草；所有数字以下方表格与磁盘产物为准"}


def _mock_summary(facts: dict) -> str:
    """确定性模板摘要：与真模型同一事实来源，便于离线演示与测试。"""
    f = facts
    cat = f.get("qc_category_counts", {})
    cat_txt = "、".join(f"{k} {v} 例" for k, v in cat.items()) if cat else "无"
    parts = [
        f"本批次（{f['batch_id']}）到货 {f['n_arrived']} 个个体，"
        f"QC 门禁拦截 {f['n_rejected']} 个、放行 {f['n_admitted']} 个"
    ]
    if f.get("n_rejected"):
        parts.append(f"（拦截构成：{cat_txt}）")
    parts.append(
        f"。合并后参考群规模由 {f['n_before']} 增至 {f['n_after']}，"
        f"并已在全量参考群上重训 GBLUP（假设 h²={f['h2']}）。"
    )
    if f.get("val_mode") == "forward":
        seg = (f"用上一代模型做前向验证，对本批真实表型的预测相关 r = {f['r']}"
               f"（验证个体 {f['n_val']} 只）")
        if f.get("prev_r") is not None:
            seg += f"，上一轮为 {f['prev_r']}，变化 {f['delta_r']:+.4f}"
        parts.append(seg + "。")
    elif f.get("val_mode") == "cv":
        parts.append(
            f"本批为初始参考群，采用 5 折交叉验证给出基线 r = {f['r']}"
            f"（口径与前向验证不同，仅作参照）。")
    if f.get("n_pairs") is not None:
        parts.append(
            f"选配建议在近交约束（预期后代 F ≤ {f['max_F']}）与隐性致死携带者规则下"
            f"生成 {f['n_pairs']} 组配对；配对搜索中 {f['blocked_kinship']} 次尝试因近交"
            f"超标被跳过、{f['blocked_carrier']} 次因携带者×携带者禁配被跳过。")
    parts.append("建议人工复核全部拦截样本后归档，并按 GEBV Top-20 清单复核留种候选。")
    return "".join(parts)
