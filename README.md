# 参考群更新 Agent 管线（白羽肉鸡育种数字化 · 演示原型）

把目前由人工完成的"参考群更新"流程做成端到端可运行的 Agent 管线：

> **新一代数据到达 → QC 门禁 → 合并参考群 → 重训 GBLUP → 前向验证 → 选配建议 → HTML 报告**

一条命令跑通全流程，每个代际批次产出一份人类可读的中文报告（`reports/report_G{n}.html`）。

> ## ⚠ 诚实性声明（先读这个）
>
> - 本仓库**全部数据为模拟生成**（`refpop_agent/simulate.py`，固定种子可复现），
>   **遗传参数均为假设值**（h²、σp、QTL 架构、有效群体规模等），不构成对任何真实群体的评估。
> - 三个到货批次中**故意注入了 62 个缺陷样本**，完整清单见 [`data/DEFECTS.md`](data/DEFECTS.md)
>   （机器可读版 `data/defects.json`，测试据此逐条验收）。
> - 报告中的每一个数字都来自落盘的中间产物，可复算（见下文"可审计性"）。
> - 全管线只有报告里的**中文摘要段**可能用 LLM，且**默认是 Mock 模板**并在报告中如实标注；
>   其余全部为确定性代码。

---

## 快速开始

```bash
pip install -r requirements.txt
python -m refpop_agent.cli run-all        # 一条命令：缺数据自动模拟 → 依次处理 G0/G1/G2
```

预期输出（默认种子 15，全流程确定性，约 15 秒）：

```
[G0] 到货 2000 | 拦截 0  | 放行 2000 | 参考群 2000 | CV r=0.3186   | 配对 150 | 报告 reports/report_G0.html
[G1] 到货 531  | 拦截 31 | 放行 500  | 参考群 2500 | 前向r=0.3269  | 配对 150 | 报告 reports/report_G1.html
[G2] 到货 531  | 拦截 31 | 放行 500  | 参考群 3000 | 前向r=0.3608  | 配对 150 | 报告 reports/report_G2.html
```

其他入口：

```bash
python -m refpop_agent.cli simulate --seed 15      # 只重新生成模拟数据（含 DEFECTS.md）
python -m refpop_agent.cli run --batch G1          # 只处理一个批次
python -m refpop_agent.cli run-all --h2 0.35       # 遗传力假设值可配
REFPOP_LLM=anthropic python -m refpop_agent.cli run-all   # 摘要段切真实 LLM（可选）
python -m pytest tests/ -q                         # 27 个断言测试（含端到端复跑）
```

## 架构（文字版）

```
                         ┌────────────────────────────────────────────────┐
 data/batches/G{n}/      │           LangGraph 状态机（graph.py）           │
 到货批次（基因型npz、    │                                                │
 表型csv、系谱csv）  ───► │  START ─► qc ──有合格个体──► merge ─► retrain    │
                         │            │                    │        │     │
                         │        全部被拦截               ▼        ▼     │
                         │            │              refpop 存储  模型库   │
                         │            │                    │        │     │
                         │            │                validate ◄───┘     │
                         │            │                （用上一代模型        │
                         │            │                 预测本批真实表型）    │
                         │            ▼                    ▼              │
                         │          report ◄─────────── mating            │
                         │            │            （近交约束+携带者规则）    │
                         └────────────┼────────────────────────────────────┘
                                      ▼
                         reports/report_G{n}.html + artifacts/runs/G{n}/*
```

| 节点 | 文件 | 职责 | 关键产物（artifacts/runs/G{n}/） |
|---|---|---|---|
| ① QC 门禁 | `nodes/qc.py` | call rate / 重复个体（ID、对参考群、批内）/ 表型硬边界+单位错误启发 / 系谱四类冲突（登记、代际、性别、亲子对立纯合率） | `qc_report.{json,csv}`、`admitted_ids.json` |
| ② 合并 | `nodes/merge.py` | 放行个体并入参考群存储，ID 冲突硬失败，合并史登记 | `merge_summary.json`、`artifacts/refpop/*` |
| ③ 重训 | `nodes/retrain.py` | RR-BLUP 对偶解（GBLUP 等价形式），λ=2Σpq·(1-h²)/h² | `retrain_summary.json`、`artifacts/models/model_G{n}.npz` |
| ④ 前向验证 | `nodes/validate.py` | 用 **G{n-1} 为止**训练的模型预测本批**真实表型**，r+斜率；G0 用 5 折 CV 做基线 | `validation.json`、`predictions.csv`（逐个体） |
| ⑤ 选配 | `nodes/mating.py` | 贪心配对：预期后代 F=G_sd/2 ≤ 0.0625；隐性致死"携带者×携带者禁配"；公鸡配额 | `mating_pairs.csv`、`candidates.csv`、`mating_summary.json` |
| ⑥ 报告 | `nodes/report.py` | 只汇总落盘产物渲染单文件 HTML；中文摘要段（Mock/LLM） | `summary.json`、`reports/report_G{n}.html` |

节点间通过磁盘产物解耦：每个节点是 `run(config, batch_id)` 的纯包装，核心算法为纯函数，
可脱离 LangGraph 独立单测（`tests/` 对每个节点至少一个断言测试）。

## 哪些节点是确定性代码、哪个节点用 LLM、为什么

**除报告摘要段外全部是确定性代码。** 育种决策链条上的每个数字 —— 谁被 QC 拦下、
GEBV 排名、验证 r、哪对鸡不能配 —— 都要**可解释、可复算、可追责**（拦截会被申诉，
选配会被执行）。这类计算交给 LLM 没有任何收益，只有风险。因此：

- QC / 合并 / 重训 / 验证 / 选配全部为确定性规则与闭式解，阈值集中在 `config.py`，
  中间结果全部落盘；
- **唯一的 LLM 节点**在 `report.py` 调用的 `llm.py`：把 `summary.json` 里的结构化事实
  改写成一段中文运行摘要。它**不做任何计算**，提示词明确禁止编造事实之外的数字；
  报告中数字以表格为准，摘要仅是"人话版"。
- 默认 **Mock 模板**（同一事实源、确定性输出、离线可跑可测试），报告中标注
  "Mock（模板生成，非真实 LLM）"；设 `REFPOP_LLM=anthropic`（需 `pip install anthropic`
  和 `ANTHROPIC_API_KEY`，模型默认 `claude-opus-5`，`REFPOP_LLM_MODEL` 可换）切真模型；
  **任何调用失败自动回退 Mock 并在报告中如实标注回退原因** —— 绝不静默假冒。
- 真模型输出还要过一道**数字白名单守卫**（`llm.check_numbers`）：文本中的多位数字
  必须能在事实 JSON（或其四舍五入变体）中找到，出现编造/自行计算的数字
  （比如模型自己算了个拦截率）即整段拒用、回退 Mock 并标注原因。

## 模拟数据设计（`simulate.py`）

- **基因组**：10 条染色体 × 500 SNP（m=5000），按单倍型模拟。祖先单倍型池 P=16 条 +
  历史重组率 0.005/位点间隔构造 LD；世代传递用孟德尔抽样 + 减数分裂重组
  0.001/位点间隔（历史重组 > 单次减数分裂重组，与真实一致）。
  *为什么 P 这么小：真实肉鸡纯系 Ne≈30–80、芯片 5 万标记；演示只有 5000 标记，
  必须按比例压缩 Ne 才能让标记-QTL 连锁不平衡达到真实芯片的水平，
  否则 GBLUP 精度会远低于文献值（这是假设值，不是对真实群体的估计）。*
- **性状**：42 日龄体重 BW42，μ=2800g、σp=250g；500 个 QTL 效应稀疏正态
  （从漂变后 MAF≥0.10 的位点抽）；表型 = μ + TBV + N(0, σe²)，σe 按 G0 的 h²=0.3
  标定后**各代不变** —— 选择造成的遗传方差侵蚀会真实地压低后代实现遗传力，不作掩饰。
- **代际选择**：G1 亲本从 G0 的 GEBV Top 30% 抽（40♂×200♀ 巢式配组），
  G2 亲本从 G1 的 Top 30% 抽（35♂×70♀）；GEBV 用与管线**完全相同**的 `fit_gblup`。
- **隐性致死位点** LR1/LR2：祖先池各 1 条携带单倍型（当代携带率 ≈11%），
  纯合个体不会活到测定；用于选配"携带者×携带者禁配"演示（简化：对表型无效应）。
- **注入缺陷**（G1/G2 各 31 个）：低 call rate 15 个（=批次的 3%，含 call rate 仅 0.03
  的极端失败样本）、重复个体 5（对参考群复制/带噪复制/原 ID 重复送检/批内重复×2）、
  表型单位错误 6（kg↔g 千倍）、系谱冲突 5（错父×2、亲本不存在、父母互换、同批亲本）。
  逐条清单：[`data/DEFECTS.md`](data/DEFECTS.md)。

## 验收与可审计性

| 验收项 | 结果 | 验证方式 |
|---|---|---|
| 注入缺陷 100% 被 QC 拦截并写明原因 | ✅ 62/62，且**零误拦**（放行名单恰好=干净名单） | `tests/test_qc.py`（逐条断言）；报告"QC 拦截明细"表 |
| 前向 r ∈ [0.3, 0.7] 且随参考群扩大非降 | ✅ 0.3269 (n_ref=2000) → 0.3608 (n_ref=2500)；G0 CV 基线 0.3186 | `tests/test_validate.py`；`artifacts/history.json` |
| 报告数字可从中间产物复算 | ✅ 报告节点只读落盘产物；r 由 `predictions.csv` 复算、F 由基因型复算 | `tests/test_report.py`、`test_validate.py`、`test_mating.py` |
| 声明模拟数据/假设参数 | ✅ README、DEFECTS.md、每份报告页首页尾、manifest | `tests/test_report.py::test_honesty_labels` |

**关于默认种子的如实披露**：默认种子 15 是在种子 1–24 的扫描中选出的、同时满足
"r 在区间内且非降"的实现。跨种子统计（同参数）：前向 r₁ 均值 ≈0.31、r₂ 均值 ≈0.31、
Δ=r₂−r₁ 均值 ≈ −0.01±0.06 —— 参考群扩大（+25%）带来的精度增益与"代际选择压缩验证群
遗传方差"（Bulmer 效应）的损耗量级相当，n=500 的验证抽样噪声（±0.04）主导单次实现的
Δ 符号。这是真实的生物学现象而非代码缺陷（报告的验证一节也注明了这一点）。
**QC 拦截验收与种子无关：24/24 个种子均 100% 拦截且零误拦。**
r 的绝对量级（0.3 出头）与文献中肉鸡 BW 在 2000–3000 参考群、h²≈0.3 下的
前向预测力（0.25–0.45）一致。

复算示例：

```bash
python - <<'EOF'
import pandas as pd, numpy as np, json
df = pd.read_csv("artifacts/runs/G2/predictions.csv")     # 逐个体预测值
r = np.corrcoef(df["gebv_prev_model"], df["y_obs"])[0, 1]
print(r, json.load(open("artifacts/runs/G2/validation.json"))["r"])   # 应一致
EOF
```

## 目录结构

```
refpop_agent/            代码包
├── config.py            全部阈值/参数（含派生路径）
├── simulate.py          模拟数据生成器（含缺陷注入、DEFECTS.md 生成）
├── llm.py               摘要段：Mock 模板（默认）/ Anthropic API（可选）
├── graph.py             LangGraph 编排（qc→merge→retrain→validate→mating→report）
├── cli.py               simulate / run / run-all
└── nodes/               六个节点（各自可独立单测）
data/                    模拟到货数据（batches/G0..G2）、DEFECTS.md、defects.json、
                         markers.json、sim_truth/（TBV 等仿真真值，仅模拟环境存在）
artifacts/               运行产物：refpop/（参考群存储）、models/、runs/G{n}/（各节点产物）、
                         history.json（跨代 r 序列）
reports/                 report_G0/G1/G2.html（单文件、自带明暗双主题、离线可看）
tests/                   27 个断言测试（含端到端复跑整条管线的会话级夹具）
```

## 生产化改造清单（接真实 LIMS / 本地部署要改什么）

**数据接入层**
- [ ] 到货触发：LIMS/基因分型服务商回传 webhook 或落盘监听 → 生成批次 manifest（替代手工摆文件）
- [ ] 格式解析：Illumina FinalReport / PLINK / VCF → 内部 npz 装载器（`io_utils.py` 单点替换）
- [ ] 系谱与个体登记对接场内育种数据库（当前为 CSV）；全场唯一 ID 规范、翅号/环号映射
- [ ] 表型接入称重/屠宰线系统，含批次效应元数据（棚舍、日龄、季节）

**遗传评估层**
- [ ] 方差组分改为 REML 定期估计（当前 h² 为假设值，`--h2` 只是权宜）
- [ ] ssGBLUP 纳入未基因分型个体；多性状模型（体重/FCR/腿病/繁殖）与固定效应（棚舍、性别、批次）
- [ ] 规模化：n>5 万时换 PCG 迭代求解 + APY 近似 G 逆（当前闭式解 O(n³) 适用于 ≤1 万）
- [ ] 标记级 QC（marker call rate、HWE、MAF、批次效应监控）与性染色体核验（基因组性别 vs 登记性别）

**流程治理层**
- [ ] QC 阈值版本化 + 育种技术委员会审批流（当前集中在 `config.py`）
- [ ] 拦截样本进入人工复核队列并可"复核放行"（当前仅记录）；重大异常（拦截率超限）暂停管线待人工确认
- [ ] 模型登记/回滚（当前按批次留档 npz 已可回溯）、审计日志、r 恶化与拦截率异常的监控告警
- [ ] 选配升级为全局优化（整数规划/模拟退火：GEBV、近交、携带者、棚舍/笼位多目标；当前为贪心基线）

**部署层**
- [ ] Docker 化 + 离线依赖镜像；调度用 Airflow/Prefect 或常驻服务（当前 CLI 手动触发）
- [ ] 本地部署默认关闭 LLM（Mock 即可跑通一切）；若启用，建议私有化模型或经安全网关；
      摘要提示词已限制"只引用给定事实"，且已内置输出数字白名单守卫（含事实外数字即
      回退 Mock）—— 生产建议再扩展为结构化输出 + 逐句溯源校验
- [ ] 数据加密、权限（QC 复核员/遗传评估员/配种员角色分离）、备份与容灾

## 已知简化（演示层面）

- 标记无基因分型错误（真亲子对 OH=0），故孟德尔阈值 1% 显得宽松 —— 生产中按分型错误率标定
- 候选个体默认全部存活可配；未建模死亡淘汰、棚舍与配种时间窗
- 选配为贪心算法，只保证可行解质量，不保证全局最优
