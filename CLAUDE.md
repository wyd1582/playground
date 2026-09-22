# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

白羽肉鸡育种"参考群更新"Agent 管线的演示原型（LangGraph 编排）：
新一代到货 → QC 门禁 → 合并参考群 → 重训 GBLUP → 前向验证 → 选配建议 → HTML 报告。
**全部数据为模拟生成、遗传参数为假设值** —— 这是产品的诚实性承诺，多处文案和测试都锁定它，不要移除相关声明。
面向中文用户：报告、README、DEFECTS.md、代码注释均为中文，保持这一约定。

## 常用命令

```bash
pip install -r requirements.txt
python -m refpop_agent.cli run-all              # 一条命令全流程（缺数据自动模拟；总是先清空 artifacts/ 重跑）
python -m refpop_agent.cli run --batch G1       # 单批次（要求前序批次的产物已存在）
python -m refpop_agent.cli simulate --seed 15   # 只重新生成 data/（含 DEFECTS.md、defects.json）
python -m pytest tests/ -q                      # 全部测试（32 个）
python -m pytest tests/test_qc.py -q            # 单文件
python -m pytest "tests/test_qc.py::test_all_injected_defects_intercepted" -q
```

测试里的 `pipeline` 夹具（tests/conftest.py）是 session 级的：在临时目录用默认种子完整复跑
模拟 + G0/G1/G2（约 15–20 秒，仅一次），大多数测试断言它落盘的产物。

## 架构要点（跨文件才能看懂的部分）

- **节点间只靠磁盘产物通信。** `graph.py` 的 LangGraph 节点是薄包装，每个节点是
  `refpop_agent/nodes/<x>.py` 的 `run(config, batch_id)`：读上游落盘产物 → 算 → 写
  `artifacts/runs/G{n}/…`。状态对象只带轻量摘要。核心算法都是纯函数
  （如 `qc.evaluate_batch`、`mating.greedy_mate`、`retrain.fit_gblup`），可脱离编排直接单测。
- **条件边只有一条**：QC 后无合格个体 → 直接跳 report（state 带 `halted`），
  中止路径也必须出报告且摘要不得出现 None（有测试）。
- **前向验证的语义**：验证批次 G{n} 用的是 **model_G{n-1}**（上一轮 retrain 落盘在
  `artifacts/models/`），不是本轮模型；G0 没有上一代，用固定种子 5 折 CV 做基线。
  跨代 r 序列追加在 `artifacts/history.json`，报告的趋势图和"与上一代对比"都读它。
- **模拟器复用管线的模型代码**：`simulate.py` 直接 import `nodes/retrain.fit_gblup` 来做
  代际 GEBV 选择（保证与管线口径一致），并 import `nodes/qc.opposing_hom_rate` 校准
  "错父"注入强度。改 retrain/qc 的接口时注意这两处反向依赖。
- **路径全部经 `PipelineConfig` 派生**（config.py），任何节点都不要硬编码路径；
  测试靠这一点把整条管线重定向到临时目录。
- **LLM 只出现在一个地方**：`llm.py` 被 report 节点调用，把 `summary.json` 的事实写成
  中文摘要段。默认 Mock（确定性模板）；`REFPOP_LLM=anthropic` 切真模型，任何失败
  （含 `check_numbers` 数字白名单不通过——输出含事实之外的数字）都回退 Mock 并在
  报告标注原因。**不要让 LLM 参与任何计算或新增第二个 LLM 节点** —— 这是产品立场。

## 确定性与"重新生成"契约（改代码前必读）

- 全管线在固定种子下逐字节确定（默认种子 15，选择依据披露在 README"诚实性"一节）。
- `data/`、`artifacts/`、`reports/` 是**提交进仓库的生成物**。凡是改动会影响输出的代码
  （simulate、任何节点、报告模板、Mock 模板措辞），必须 `python -m refpop_agent.cli run-all`
  重新生成并把变化后的生成物一并提交，否则仓库内容与代码不一致（测试在临时目录复跑
  同种子，能过测试但仓库里是旧产物）。
- 验收红线（tests 已锁定，改动需同时维护）：
  - `data/defects.json` 里 62 个注入缺陷 100% 被 QC 拦截且原因码匹配，放行名单恰好等于
    干净名单（零误拦）；
  - 前向 r ∈ [0.3, 0.7] 且 G2 ≥ G1；
  - 报告中的数字可由 `predictions.csv`（复算 r）、基因型（复算配对 F）等产物复算；
  - 报告含"演示原型/模拟生成/假设值/Mock"等诚实性标注。
- 改 QC 阈值或注入方式后，跑一下多种子稳健性再定（历史上做过 1–24 种子扫描：
  QC 应与种子无关地全拦截；r 的区间/趋势才允许挑种子并在 README 披露）。

## 领域约定

- 基因型编码 0/1/2，缺失 `-1`（`io_utils.MISSING`）；ID 均为字符串（读 CSV 时
  用 `io_utils.read_table` 保持 dtype 与空串，不要让 pandas 把 "" 变 NaN）。
- GBLUP 用 RR-BLUP 对偶解（`retrain.py` docstring 有推导），λ=2Σpq·(1-h²)/h²，
  h² 是**假设值**（`--h2` 可配），文案里保持"生产应 REML 估计"的说法。
- 选配约束：预期后代 F = 基因组亲缘 G_sd/2 ≤ 0.0625；隐性致死位点（data/markers.json）
  "携带者×携带者"禁配；每公鸡配额 `max_dams_per_sire`。
- 报告是单文件 HTML（无外部依赖、明暗双主题、可发布为 claude.ai artifact），
  图表为手写内联 SVG，配色 token 在 `report.py` 的 `_CSS` 里成套定义 —— 改色要同时改
  亮/暗两组并保持与 dataviz 校验一致。
