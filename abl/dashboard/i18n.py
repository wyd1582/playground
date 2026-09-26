"""Chinese / English strings for the dashboard, ``make status``, ``make digest``, the narrative feed
and the alarm messages.

    from dashboard.i18n import t
    t("st_proposals")                      # -> "提案" (zh, the default) or "Proposals" (en)
    t("narr_promoted", cand="k0001")       # str.format placeholders

Language resolution (``current_lang``): an explicit ``set_lang(...)`` override, else the
``ABL_LANG`` environment variable when it is one of ``LANGS``, else ``DEFAULT_LANG`` (zh).
Ids (k_..., p_..., campaign ids), DSL text, metric and gate names and verdict tokens are never
translated. Dependency-free on purpose: stdlib ``os`` only.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

LANGS = ("zh", "en")
DEFAULT_LANG = "zh"
_LABELS = {"zh": "中文", "en": "English"}
_override: str | None = None


def set_lang(lang: str | None) -> None:
    """Set (or, with None, clear) the process-wide language override."""
    global _override
    if lang is not None and lang not in LANGS:
        raise ValueError(f"unsupported language {lang!r}; expected one of {LANGS}")
    _override = lang


@contextmanager
def using_lang(lang: str | None) -> Iterator[None]:
    """Temporarily set the override (None leaves the current resolution untouched)."""
    global _override
    prev = _override
    if lang is not None:
        set_lang(lang)
    try:
        yield
    finally:
        _override = prev


def current_lang() -> str:
    if _override is not None:
        return _override
    env = os.environ.get("ABL_LANG", "").strip().lower()
    return env if env in LANGS else DEFAULT_LANG


def lang_label(lang: str) -> str:
    return _LABELS[lang]


def t(key: str, **fmt) -> str:
    """STRINGS[key][current language], ``str.format``-ed with ``fmt``.

    A missing key raises KeyError; a missing placeholder raises KeyError/IndexError from
    ``str.format`` — nothing is swallowed.
    """
    return STRINGS[key][current_lang()].format(**fmt)


STRINGS: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- shared
    "sep_list": {"zh": "；", "en": "; "},
    "none_value": {"zh": "无", "en": "none"},
    "exhausted": {"zh": "已耗尽", "en": "exhausted"},
    "ctl_paused": {"zh": "PAUSED（已暂停）— control/PAUSE 存在",
                   "en": "PAUSED — control/PAUSE exists"},
    "ctl_running": {"zh": "RUNNING（运行中）— control/RUN 存在，无 PAUSE",
                    "en": "RUNNING — control/RUN present, no PAUSE"},
    "ctl_idle": {"zh": "IDLE（空闲）— control/RUN 缺失", "en": "IDLE — control/RUN missing"},

    # ---------------------------------------------------------------- agent roles (narrative)
    "agent_orchestrator": {"zh": "编排器", "en": "Orchestrator"},
    "agent_geneticist": {"zh": "遗传学家", "en": "Geneticist"},
    "agent_builder": {"zh": "构建者", "en": "Builder"},
    "agent_critic": {"zh": "评审者", "en": "Critic"},
    "agent_analyst": {"zh": "分析师", "en": "Analyst"},
    "agent_registry": {"zh": "台账", "en": "Registry"},
    "agent_digest": {"zh": "摘要", "en": "Digest"},
    "agent_final_table": {"zh": "最终表", "en": "Final table"},
    "agent_unknown": {"zh": "未知 agent", "en": "Unknown agent"},

    # ---------------------------------------------------------------- verbs (narrative)
    "verb_proposed": {"zh": "提出了", "en": "proposed"},
    "verb_implemented": {"zh": "实现了", "en": "implemented"},
    "verb_diagnosed": {"zh": "诊断了", "en": "diagnosed"},
    "verb_analysed": {"zh": "分析了", "en": "analysed"},
    "verb_registered": {"zh": "登记了", "en": "registered"},
    "verb_planned": {"zh": "规划了", "en": "planned"},
    "verb_allocated": {"zh": "分配了预算", "en": "allocated budget for"},
    "verb_stepped": {"zh": "执行了一步", "en": "stepped"},
    "verb_reported_status": {"zh": "报告了状态", "en": "reported status"},
    "verb_validated": {"zh": "验证了", "en": "validated"},
    "verb_evaluated": {"zh": "评估了", "en": "evaluated"},
    "verb_reviewed": {"zh": "审查了", "en": "reviewed"},
    "verb_deduplicated": {"zh": "去重了", "en": "deduplicated"},
    "verb_stopped": {"zh": "停止了", "en": "stopped"},
    "verb_paused": {"zh": "暂停了", "en": "paused"},
    "verb_selected": {"zh": "选择了", "en": "selected"},
    "verb_deferred": {"zh": "推迟了", "en": "deferred"},
    "verb_ended": {"zh": "结束了 campaign", "en": "ended the campaign"},
    "verb_budget_cap": {"zh": "触及预算上限", "en": "hit the budget cap"},
    "verb_retry_limit": {"zh": "判定已达重试上限的", "en": "hit the retry limit for"},
    "verb_rejected": {"zh": "拒绝了", "en": "rejected"},
    "verb_acted": {"zh": "执行了操作", "en": "acted on"},
    "verb_unknown": {"zh": "执行了「{action}」", "en": "{action}"},

    # ---------------------------------------------------------------- policy flags (narrative)
    "flag_holdout_touch": {"zh": "试图触碰封存的 holdout", "en": "tried to touch the sealed holdout"},
    "flag_budget_exceeded": {"zh": "预算超限", "en": "budget exceeded"},
    "flag_threshold_edit": {"zh": "试图修改门槛", "en": "attempted a gate-threshold edit"},
    "flag_retry_limit": {"zh": "重试超限", "en": "retry limit exceeded"},
    "flag_holdout_final_read": {"zh": "经批准的最终 holdout 读取", "en": "sanctioned final holdout read"},
    "flag_paused": {"zh": "已停止：control/PAUSE 存在", "en": "stopped: control/PAUSE present"},

    # ---------------------------------------------------------------- narrative sentences
    "narr_unreadable": {"zh": "无法解析的事件（不是 JSON 对象）", "en": "Unreadable event (not a JSON object)"},
    "narr_reason": {"zh": "{text}：{reason}", "en": "{text}: {reason}"},
    "narr_target_cand": {"zh": "候选 {cand}", "en": "candidate {cand}"},
    "narr_target_the": {"zh": "该候选", "en": "the candidate"},
    "narr_gate_target": {"zh": "候选 {cand}", "en": "{cand}"},
    "narr_leak_tag": {"zh": "（{leak}）", "en": " ({leak})"},
    "narr_critic_return": {"zh": "评审者将{target} 退回构建者{tag}", "en": "Critic returned {target} to builder{tag}"},
    "narr_critic_reject": {"zh": "评审者拒绝了{target}{tag}", "en": "Critic rejected {target}{tag}"},
    "narr_critic_pass": {"zh": "评审者通过了{target}", "en": "Critic passed {target}"},
    "narr_critic_review": {"zh": "评审者审查了{target}", "en": "Critic reviewed {target}"},
    "narr_promoted": {"zh": "候选 {cand} 已晋级（PROMOTED）", "en": "Candidate {cand} PROMOTED"},
    "narr_rejected": {"zh": "候选 {cand} 在晋级环节被拒绝（REJECTED）", "en": "Candidate {cand} REJECTED at promotion"},
    "narr_gate_rejected": {"zh": "{gate} 门拒绝了{target}", "en": "Gate {gate} rejected {target}"},
    "narr_gate_failed": {"zh": "{target} 未通过 {gate} 门（FAILED）", "en": "Gate {gate} FAILED for {target}"},
    "narr_gate_passed": {"zh": "{target} 通过了 {gate} 门", "en": "Gate {gate} passed for {target}"},
    "narr_gate_ran": {"zh": "{gate} 门已对{target} 运行", "en": "Gate {gate} ran on {target}"},
    "narr_vs_threshold": {"zh": " 对比门槛 ", "en": " vs threshold "},
    "narr_need_operator": {"zh": "构建者需要新的 DSL 算子{target}", "en": "Builder needs a new DSL operator{target}"},
    "narr_need_operator_target": {"zh": "（候选 {cand}）", "en": " for candidate {cand}"},
    "narr_generic": {"zh": "{who}{verb}", "en": "{who} {verb}"},
    "narr_generic_cand": {"zh": "{who}{verb}候选 {cand}", "en": "{who} {verb} candidate {cand}"},
    "narr_generic_hypothesis": {"zh": "{who}{verb}一个假设", "en": "{who} {verb} a hypothesis"},
    "narr_cluster_tag": {"zh": "{text} [{cluster}]", "en": "{text} [{cluster}]"},
    "narr_policy": {"zh": " [策略标记：{items}]", "en": " [policy: {items}]"},
    "narr_policy_item": {"zh": "{flag} — {text}", "en": "{flag} — {text}"},

    # ---------------------------------------------------------------- alarms
    "alarm_label_sealed_holdout": {"zh": "封存的 holdout", "en": "sealed holdout"},
    "alarm_describe": {"zh": "{who}/{act}{on}，时间 {ts}", "en": "{who}/{act}{on} at {ts}"},
    "alarm_describe_on": {"zh": "（{cand}）", "en": " on {cand}"},
    "alarm_flagged_label": {"zh": "{n} 个事件被标记为 {flag}（{label}）；最近一次：{latest}",
                            "en": "{n} event(s) flagged {flag} ({label}); latest {latest}"},
    "alarm_flagged": {"zh": "{n} 个事件被标记为 {flag}；最近一次：{latest}",
                      "en": "{n} event(s) flagged {flag}; latest {latest}"},
    "alarm_threshold_edit_flags": {"zh": "{n} 个 threshold_edit 标记；最近一次：{latest}",
                                   "en": "{n} threshold_edit flag(s); latest {latest}"},
    "alarm_threshold_hash": {"zh": "campaign {cid}：gates/thresholds.yaml 的 sha256 开始时为 {start}，现在为 {now}",
                             "en": "campaign {cid}: gates/thresholds.yaml sha256 {start} at start, now {now}"},
    "alarm_retry_over": {"zh": "{n} 个候选重试超过 {limit} 次：{ids}",
                         "en": "{n} candidate(s) retried more than {limit}x: {ids}"},
    "alarm_budget_tokens": {"zh": "campaign {cid}：token 用量 {used} > 上限 {cap}",
                            "en": "campaign {cid}: tokens {used} > cap {cap}"},
    "alarm_budget_evals": {"zh": "campaign {cid}：全量评估 {used} > 上限 {cap}",
                           "en": "campaign {cid}: full evaluations {used} > cap {cap}"},
    "alarm_cluster": {"zh": "campaign {cid}：机制簇 '{cluster}' 占 {total} 个提案的 {share}（> {limit}）",
                      "en": "campaign {cid}: cluster '{cluster}' holds {share} of {total} proposals (> {limit})"},
    "alarm_pass_rate": {"zh": "campaign {cid}：过去 24 小时门通过率 {recent}（{rp}/{rn}），基线 {bp}/{bn}（> {factor} 倍）",
                        "en": "campaign {cid}: gate pass-rate {recent} over the last 24h ({rp}/{rn}) "
                              "vs baseline {bp}/{bn} (> {factor}x)"},
    "alarm_stalled": {"zh": "已 {mins} 分钟没有 agent 事件（最后一次 {last}），而 control/RUN 存在且 control/PAUSE 不存在",
                      "en": "no agent event for {mins} min (last at {last}) while control/RUN exists and "
                            "control/PAUSE does not"},
    "alarm_notify_title": {"zh": "ABL 报警：{kind}", "en": "ABL alarm: {kind}"},

    # ---------------------------------------------------------------- make status
    "st_title": {"zh": "ABL 状态 — 最近 {h} 小时（{since} → {now}）", "en": "ABL status — last {h}h ({since} → {now})"},
    "st_title_rich": {"zh": "[bold]ABL 状态[/bold] — 最近 {h} 小时（{since} → {now}）",
                      "en": "[bold]ABL status[/bold] — last {h}h ({since} → {now})"},
    "st_sec_control": {"zh": "控制", "en": "Control"},
    "st_state": {"zh": "状态", "en": "State"},
    "st_registry": {"zh": "台账", "en": "Registry"},
    "st_reg_missing": {"zh": "（缺失 — 显示为零）", "en": "  (missing — showing zeros)"},
    "st_reg_skipped": {"zh": "（本次读取跳过：{err}）", "en": "  (skipped: {err})"},
    "st_last_event": {"zh": "最近事件", "en": "Last event"},
    "st_sec_learning": {"zh": "学习（最近 {h} 小时）", "en": "Learning (last {h}h)"},
    "st_proposals": {"zh": "提案", "en": "Proposals"},
    "st_critic_verdicts": {"zh": "评审者结论", "en": "Critic verdicts"},
    "st_critic_verdicts_val": {"zh": "通过 {p} · 退回 {r} · 拒绝 {j}", "en": "PASS {p} · RETURN {r} · REJECT {j}"},
    "st_gate_results": {"zh": "门结果", "en": "Gate results"},
    "st_gate_results_val": {"zh": "通过 {p} · 未通过 {f}", "en": "passed {p} · failed {f}"},
    "st_promotions": {"zh": "晋级", "en": "Promotions"},
    "st_promotions_val": {"zh": "{p}（拒绝 {r}）", "en": "{p}  (rejections {r})"},
    "st_full_evals": {"zh": "全量评估", "en": "Full evaluations"},
    "st_sec_cost": {"zh": "成本（最近 {h} 小时）", "en": "Cost (last {h}h)"},
    "st_tokens": {"zh": "Token", "en": "Tokens"},
    "st_tokens_val": {"zh": "{n}（台账累计 {m}）", "en": "{n}  (ledger to date {m})"},
    "st_cost": {"zh": "费用", "en": "Cost"},
    "st_cost_val": {"zh": "${a}（台账累计 ${b}）", "en": "${a}  (ledger to date ${b})"},
    "st_agent_calls": {"zh": "Agent 调用次数", "en": "Agent calls"},
    "st_event_stream": {"zh": "事件流", "en": "Event stream"},
    "st_event_stream_val": {"zh": "{n} 个事件 · {tok} tokens · ${cost}", "en": "{n} events · {tok} tokens · ${cost}"},
    "st_sec_budget": {"zh": "预算", "en": "Budget"},
    "st_evals_vs_cap": {"zh": "用量 vs 上限", "en": "Evaluations vs cap"},
    "st_no_campaign": {"zh": "0 / 0（台账中没有 campaign）", "en": "0 / 0 (no campaign in the registry)"},
    "st_sec_alarms": {"zh": "报警（{n}）", "en": "Alarms ({n})"},
    "st_red": {"zh": "红色报警 {kind}", "en": "RED {kind}"},
    "st_all_clear": {"zh": "一切正常", "en": "all clear"},
    "st_b_tokens": {"zh": "token {tu}/{tc}{tp}", "en": "tokens {tu}/{tc}{tp}"},
    "st_b_evals": {"zh": "全量评估 {eu}/{ec}", "en": "full evals {eu}/{ec}"},
    "st_b_burn": {"zh": "燃烧率 {tph} token/小时，{eph} 次评估/小时", "en": "burn {tph} tok/h, {eph} evals/h"},
    "st_b_tokens_out": {"zh": "token 耗尽于：{at}", "en": "tokens out: {at}"},
    "st_b_evals_out": {"zh": "评估额度耗尽于：{at}", "en": "evals out: {at}"},
    "st_b_ended": {"zh": "（已结束）", "en": " (ended)"},
    "st_b_line": {"zh": "{cid}{state}：{parts}", "en": "{cid}{state}: {parts}"},
    "st_help": {"zh": "ABL 一屏状态摘要（只读）", "en": "ABL one-screen status (read-only)"},
    "st_help_plain": {"zh": "即使安装了 rich 也输出纯文本", "en": "plain text even if rich is installed"},
    "cli_help_lang": {"zh": "输出语言（覆盖 ABL_LANG）", "en": "output language (overrides ABL_LANG)"},

    # ---------------------------------------------------------------- make digest
    "dg_llm_lang": {"zh": "Write every bullet in Simplified Chinese (简体中文). Keep ids, gate names, metric names "
                          "and DSL text exactly as they appear in the facts.",
                    "en": "Write every bullet in English."},
    "dg_title": {"zh": "# ABL 每日摘要 — {date}", "en": "# ABL daily digest — {date}"},
    "dg_window": {"zh": "_时间窗：最近 {h} 小时（{since} → {until}）。所有数字来自台账（SQL，只读）；叙述要点：{backend}。_",
                  "en": "_Window: last {h} h ({since} → {until}). Numbers come from the registry (SQL, read-only); "
                        "narrative bullets: {backend}._"},
    "dg_h_learned": {"zh": "## 学到了什么", "en": "## What was learned"},
    "dg_h_rejected": {"zh": "## 拒绝了什么、为什么", "en": "## What was rejected and why"},
    "dg_h_alarms": {"zh": "## 报警", "en": "## Alarms"},
    "dg_alarm_line": {"zh": "- **红色 `{kind}`** — {msg}", "en": "- **RED `{kind}`** — {msg}"},
    "dg_no_alarms": {"zh": "- 无。所有策略检查均正常。", "en": "- None. All policy checks are clear."},
    "dg_h_cost": {"zh": "## 成本", "en": "## Cost"},
    "dg_cost_header": {"zh": "| 指标 | 最近 {h} 小时 | 台账累计 |", "en": "| Metric | Last {h} h | Ledger to date |"},
    "dg_cost_tokens": {"zh": "Token", "en": "Tokens"},
    "dg_cost_usd": {"zh": "费用（USD）", "en": "Cost (USD)"},
    "dg_cost_calls": {"zh": "Agent 调用次数", "en": "Agent calls"},
    "dg_cost_evals": {"zh": "全量评估（去重候选数）", "en": "Full evaluations (distinct candidates)"},
    "dg_cost_compute": {"zh": "评估计算时间（秒）", "en": "Evaluation compute (s)"},
    "dg_budget_header": {"zh": "| Campaign | Token 用量 / 上限 | 全量评估用量 / 上限 | 燃烧率（token/小时） | Token 耗尽时间 |",
                         "en": "| Campaign | Tokens used / cap | Full evals used / cap | Burn (tokens/h) | Tokens run out |"},
    "dg_where_tokens": {"zh": "Token 去向（最近 {h} 小时）：", "en": "Where the tokens went (last {h} h): "},
    "dg_agent_cost_one": {"zh": "{agent} {tokens} tokens / {calls} 次调用", "en": "{agent} {tokens} tokens / {calls} call"},
    "dg_agent_cost_many": {"zh": "{agent} {tokens} tokens / {calls} 次调用", "en": "{agent} {tokens} tokens / {calls} calls"},
    "dg_h_next": {"zh": "## 下一个实验（分析师）", "en": "## Next experiment (Analyst)"},
    "dg_next_source": {"zh": "_来源：分析师于 {ts} 针对 {cand} 的调用（`{src}`）。_",
                       "en": "_Source: Analyst call at {ts} on {cand} (`{src}`)._"},
    "dg_na": {"zh": "无", "en": "n/a"},
    "dg_next_missing": {"zh": "最近一次分析师调用（{ts}）没有记录 `next_experiment`（`{src}`）。",
                        "en": "The latest Analyst call ({ts}) recorded no `next_experiment` (`{src}`)."},
    "dg_no_analyst": {"zh": "尚未记录任何分析师调用。", "en": "No Analyst call has been recorded yet."},
    "dg_backend_det": {"zh": "确定性文本（LLM 不可用：{exc}）", "en": "deterministic (LLM unavailable: {exc})"},
    "dg_backend_replaced": {"zh": "{model}；{n} 条要点被替换为确定性文本（数字不在 SQL 事实中）",
                            "en": "{model}; {n} bullet(s) replaced by deterministic text (numbers not in SQL facts)"},
    "dg_wrote": {"zh": "已写入 {path}", "en": "wrote {path}"},
    "dg_help": {"zh": "写出 registry/digest_YYYY-MM-DD.md（台账只读）",
                "en": "Write registry/digest_YYYY-MM-DD.md (read-only on the ledger)"},
    "dg_help_print": {"zh": "同时打印摘要", "en": "also print the digest"},
    # deterministic bullets — learned
    "dg_b_summary": {"zh": "最近 {h} 小时，循环产生了 {proposals} 个提案；评审者通过 {passed} 个、退回 {returned} 个、"
                           "拒绝 {rejected} 个；{evals} 个候选完成全量评估，{promoted} 个晋级。",
                     "en": "In the last {h}h the loop produced {proposals} proposals; the Critic passed {passed}, "
                           "returned {returned} and rejected {rejected}; {evals} candidates got a full evaluation "
                           "and {promoted} were promoted."},
    "dg_b_cluster": {"zh": "探索最多的机制簇：'{cluster}'，{proposals} 个提案（占非对照提案的 {share}%），"
                           "{promoted} 个晋级、{rejected} 个被拒绝。",
                     "en": "Most explored mechanism cluster: '{cluster}' with {proposals} proposals ({share}% of "
                           "non-control proposals), {promoted} promoted and {rejected} rejected."},
    "dg_b_no_proposals": {"zh": "台账中还没有提案，暂无机制簇分布可供学习。",
                          "en": "No proposals are in the ledger yet, so there is no mechanism map to learn from."},
    "dg_b_best": {"zh": "目前最佳配对 ΔOOS 为 {delta}{ci}，来自机制簇 '{cluster}' 的 {cand}。",
                  "en": "Best paired ΔOOS so far is {delta}{ci} for {cand} in cluster '{cluster}'."},
    "dg_b_best_ci": {"zh": "（CI 下限 {lo}）", "en": " (CI low {lo})"},
    "dg_b_no_eval": {"zh": "尚未记录任何全量评估，因此还没有准确度方面的证据。",
                     "en": "No full evaluation has been recorded yet, so there is no accuracy evidence either way."},
    "dg_b_limiting_gate": {"zh": "限制最大的门是 {gate}：最近 {h} 小时 {n} 次检查中有 {failed} 次未通过。",
                           "en": "The most limiting gate was {gate}: {failed} of {n} checks failed in the last {h}h."},
    "dg_b_no_gate_fail": {"zh": "最近 {h} 小时没有门检查未通过。", "en": "No gate check failed in the last {h}h."},
    "dg_b_no_gate_results": {"zh": "最近 {h} 小时没有记录门结果。", "en": "No gate results were recorded in the last {h}h."},
    "dg_b_reliability": {"zh": "框架可靠性：{reviews} 次负对照评审中评审者拒绝了 {rejected} 次，"
                               "{fp} 个负对照被错误晋级。",
                         "en": "Harness reliability: the Critic rejected {rejected} of {reviews} negative-control "
                               "reviews, and {fp} negative control(s) were falsely promoted."},
    "dg_b_nc_untested": {"zh": "尚无负对照候选接受评审，评审者的可靠性尚未检验。",
                         "en": "No negative-control candidates have been reviewed yet, so Critic reliability is untested."},
    # deterministic bullets — rejected
    "dg_r_leak": {"zh": "评审者因 {leak} 泄漏退回或拒绝了 {n} 个候选{eg}。",
                  "en": "The Critic returned or rejected {n} candidate(s) for {leak} leakage{eg}."},
    "dg_r_leak_eg": {"zh": " — 例如 {example}", "en": " — e.g. {example}"},
    "dg_r_gate_fail": {"zh": "{gate} 门未通过 {n} 次；例如 {cand} 的 {metric} = {value}，门槛为 {threshold}。",
                       "en": "Gate {gate} failed {n} time(s); e.g. {cand} had {metric} = {value} against "
                             "threshold {threshold}."},
    "dg_r_moved": {"zh": "{n} 个候选被 {gate} 移入 rejected：{reason}。",
                   "en": "{n} candidate(s) were moved to rejected by {gate}: {reason}."},
    "dg_r_fill_1": {"zh": "最近 {h} 小时没有其他被拒绝的内容。", "en": "Nothing else was rejected in the last {h}h."},
    "dg_r_fill_2": {"zh": "没有更多拒绝需要报告。", "en": "No further rejections to report."},
    "dg_r_fill_3": {"zh": "拒绝记录中没有其他内容。", "en": "The rejection log is otherwise empty."},
    "dg_r_nothing": {"zh": "最近 {h} 小时没有任何内容被拒绝。", "en": "Nothing was rejected in the last {h}h."},

    # ---------------------------------------------------------------- Streamlit page
    "app_lang_label": {"zh": "语言 / Language", "en": "语言 / Language"},
    "app_page_title": {"zh": "ABL 监护与学习", "en": "ABL Guardian & Learning"},
    "app_title": {"zh": "ABL — 监护与学习", "en": "ABL — Guardian & Learning"},
    "app_learning": {"zh": "学习", "en": "Learning"},
    "app_guardian": {"zh": "监护", "en": "Guardian"},
    "app_campaign": {"zh": "Campaign", "en": "Campaign"},
    "app_all_campaigns": {"zh": "（全部 campaign）", "en": "(all campaigns)"},
    "app_abl_root": {"zh": "ABL_ROOT `{root}`", "en": "ABL_ROOT `{root}`"},
    "app_registry_path": {"zh": "台账 `{path}`", "en": "registry `{path}`"},
    "app_registry_missing": {"zh": "（缺失）", "en": " (missing)"},
    "app_last_read_skipped": {"zh": "上次台账读取已跳过：{err}", "en": "last registry read skipped: {err}"},
    "app_readonly_note": {"zh": "只读 · 每 5 秒轮询 · 仅写入 dashboard/state.json、registry/alarms.log 和 control/PAUSE",
                          "en": "Read-only · polls every 5 s · writes only dashboard/state.json, registry/alarms.log "
                                "and control/PAUSE"},
    # feed
    "app_feed_title": {"zh": "实时叙述流", "en": "Live narrative feed"},
    "app_feed_only": {"zh": "只看评审者退回、门未通过、晋级和策略标记",
                      "en": "Only Critic returns, gate failures, promotions and policy flags"},
    "app_feed_empty": {"zh": "`{path}` 中还没有事件。", "en": "No events yet in `{path}`."},
    "app_feed_caption": {"zh": "从 events.jsonl 读取 {total} 个事件 + 台账中最近 {gates} 个门结果 · 最新在前 · 显示 {shown} 条",
                         "en": "{total} events read from events.jsonl + {gates} recent gate outcomes from the "
                               "registry · newest first · showing {shown}"},
    # mechanism map
    "app_mech_title": {"zh": "机制簇分布", "en": "Mechanism map"},
    "app_no_proposals": {"zh": "台账中还没有提案。", "en": "No proposals in the registry yet."},
    "app_series_promoted": {"zh": "晋级", "en": "promoted"},
    "app_series_rejected": {"zh": "拒绝", "en": "rejected"},
    "app_series_in_progress": {"zh": "进行中", "en": "in progress"},
    "app_axis_proposals": {"zh": "提案数", "en": "proposals"},
    "app_axis_cluster": {"zh": "机制簇", "en": "mechanism cluster"},
    "app_table_view": {"zh": "表格视图", "en": "Table view"},
    "app_col_share": {"zh": "占比", "en": "share"},
    # funnel
    "app_funnel_title": {"zh": "漏斗 — 今日 vs campaign 累计", "en": "Funnel — today vs campaign-to-date"},
    "app_col_stage": {"zh": "阶段", "en": "stage"},
    "app_col_today": {"zh": "今日（UTC）", "en": "today (UTC)"},
    "app_col_ctd": {"zh": "campaign 累计", "en": "campaign-to-date"},
    "app_col_pct": {"zh": "占提案 %", "en": "% of proposals"},
    "stage_proposals": {"zh": "提案", "en": "proposals"},
    "stage_reviewed": {"zh": "已评审", "en": "reviewed"},
    "stage_implemented": {"zh": "已实现", "en": "implemented"},
    "stage_validated": {"zh": "已验证", "en": "validated"},
    "stage_evaluated": {"zh": "已评估", "en": "evaluated"},
    "stage_promoted": {"zh": "已晋级", "en": "promoted"},
    # explain
    "app_explain_title": {"zh": "解释这个候选", "en": "Explain this candidate"},
    "app_no_candidates": {"zh": "台账中还没有候选。", "en": "No candidates in the registry yet."},
    "app_candidate_select": {"zh": "候选（candidate_id）", "en": "candidate_id"},
    "app_cand_caption": {"zh": "状态 **{state}** · 重试 {retries} 次 · 提案 `{pid}` · campaign `{cid}`",
                         "en": "state **{state}** · retries {retries} · proposal `{pid}` · campaign `{cid}`"},
    "app_no_package": {"zh": "registry/packages/{cid}.json 中还没有 BreedingPackage。",
                       "en": "No BreedingPackage at registry/packages/{cid}.json yet."},
    "app_gate_results_title": {"zh": "**门结果（台账，含门槛）**", "en": "**Gate results (registry, with thresholds)**"},
    "app_no_gate_results": {"zh": "未记录门结果。", "en": "No gate results recorded."},
    "app_reviews_history": {"zh": "评审者评审与状态历史", "en": "Critic reviews and state history"},
    "app_tab_thesis": {"zh": "论点", "en": "Thesis"},
    "app_tab_dsl": {"zh": "DSL", "en": "DSL"},
    "app_tab_data": {"zh": "数据声明", "en": "Data declaration"},
    "app_tab_tests": {"zh": "测试", "en": "Tests"},
    "app_tab_provenance": {"zh": "溯源", "en": "Provenance"},
    "app_tab_evaluation": {"zh": "评估", "en": "Evaluation"},
    "app_pkg_mechanism": {"zh": "**机制** — {v}", "en": "**Mechanism** — {v}"},
    "app_pkg_direction": {"zh": "**方向** — {v}", "en": "**Direction** — {v}"},
    "app_pkg_cluster": {"zh": "**机制簇** — `{v}`", "en": "**Cluster** — `{v}`"},
    "app_pkg_falsifiers": {"zh": "**证伪条件**", "en": "**Falsifiers**"},
    "app_pkg_expected_gain": {"zh": "**预期增益**", "en": "**Expected gain**"},
    "app_pkg_sources": {"zh": "来源：{refs}", "en": "Sources: {refs}"},
    "app_pkg_dsl_caption": {"zh": "语义哈希 `{h}` · 算子：{ops}", "en": "semantic hash `{h}` · operators: {ops}"},
    "app_pkg_snapshot": {"zh": "快照 `{snap}` · 哈希 `{h}`", "en": "snapshot `{snap}` · hash `{h}`"},
    "app_pkg_no_tests": {"zh": "未记录测试。", "en": "No tests recorded."},
    "app_pkg_disposition": {"zh": "**处置** — {v}", "en": "**Disposition** — {v}"},
    "app_pkg_analyst_summary": {"zh": "分析师总结", "en": "Analyst summary"},
    "app_pkg_diagnosis": {"zh": "诊断", "en": "Diagnosis"},
    "app_pkg_next_experiment": {"zh": "下一个实验", "en": "Next experiment"},
    # budget
    "app_budget_title": {"zh": "预算", "en": "Budget"},
    "app_no_campaign": {"zh": "台账中还没有 campaign。", "en": "No campaign in the registry yet."},
    "app_ended": {"zh": " · 已结束", "en": " · ended"},
    "app_tokens_cap": {"zh": "Token 用量 / 上限", "en": "Tokens used / cap"},
    "app_evals_cap": {"zh": "全量评估 / 上限", "en": "Full evaluations / cap"},
    "app_burn_caption": {"zh": "最近 {h} 小时燃烧率：{tph} token/小时 · {eph} 次评估/小时 · token 耗尽于：{tout} · "
                               "评估额度耗尽于：{eout} · 花费 ${cost}",
                         "en": "Burn over the last {h} h: {tph} tokens/h · {eph} evals/h · tokens run out: {tout} · "
                               "evals run out: {eout} · spend ${cost}"},
    # alarms
    "app_alarms_title": {"zh": "策略报警", "en": "Policy alarms"},
    "app_no_alarms": {"zh": "没有策略报警。", "en": "No policy alarms."},
    "app_threshold_hash": {"zh": "门槛文件哈希（campaign 开始时 vs 现在）",
                           "en": "Threshold file hash (campaign start vs now)"},
    # controls
    "app_controls_title": {"zh": "控制", "en": "Controls"},
    "app_demo_banner": {"zh": "演示模式：只读的演示台账（模拟数据 + 公开猪数据），控制按钮已隐藏。",
                        "en": "Demo mode: a read-only demo ledger (simulation + public pig data); controls are hidden."},
    "app_demo_controls": {"zh": "演示部署中不提供暂停 / 恢复。在自己的机器上运行 `make watch` 可使用控制功能。",
                          "en": "PAUSE / RESUME are not available in the demo deployment. Run `make watch` locally to use them."},
    "app_login_title": {"zh": "ABL — 请输入访问密码", "en": "ABL — enter the access password"},
    "app_login_password": {"zh": "访问密码", "en": "Access password"},
    "app_login_button": {"zh": "进入", "en": "Enter"},
    "app_login_wrong": {"zh": "密码不正确。", "en": "Wrong password."},
    "app_paused": {"zh": "已暂停（PAUSED）— control/PAUSE 存在；编排器会在下一步之前停止。",
                   "en": "PAUSED — control/PAUSE exists; the Orchestrator stops before its next step."},
    "app_running": {"zh": "运行中（RUNNING）— control/RUN 存在，无 PAUSE。", "en": "RUNNING — control/RUN present, no PAUSE."},
    "app_idle": {"zh": "空闲（IDLE）— control/RUN 缺失。", "en": "IDLE — control/RUN is missing."},
    "app_btn_pause": {"zh": "暂停 PAUSE", "en": "PAUSE"},
    "app_btn_resume": {"zh": "恢复 RESUME", "en": "RESUME"},
    # reliability
    "app_reliability_title": {"zh": "Agent 可靠性", "en": "Agent reliability"},
    "app_nc_rejected": {"zh": "被评审者拒绝的负对照", "en": "Negative controls rejected by Critic"},
    "app_false_promotions": {"zh": "错误晋级", "en": "False promotions"},
    "app_nc_promoted": {"zh": "负对照候选被晋级：{ids}", "en": "Negative-control candidate(s) promoted: {ids}"},
    "app_nc_not_rejected": {"zh": "评审者有 {n} 次负对照评审没有给出 REJECT。",
                            "en": "The Critic did not REJECT {n} negative-control review(s)."},
    "app_critic_quality": {"zh": "按对照臂统计的评审者质量（v_critic_quality）",
                           "en": "Critic quality by arm (v_critic_quality)"},
}
