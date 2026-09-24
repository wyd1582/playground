# ABL 用户手册（中文）

Agentic Breeding-value Loop：一个"agents 提假设、确定性门槛决定谁存活"的基因组选择研究 harness。
本手册面向操作它的人（育种主管、数据科学家、一号位），回答"怎么装、怎么跑、怎么看、怎么改、出了问题怎么办"。
设计原理见 `docs/DESIGN.md`，数据模型与面板规范见 `docs/OPS.md`。English version: `docs/USER_MANUAL.md`.

---

## 1. 十分钟上手

```bash
git clone -b claude/affectionate-franklin-ttwudk https://github.com/wyd1582/playground
cd playground/abl
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
make test            # 63 项测试，约 6–8 分钟（含一个小规模端到端 campaign）
make seal-holdout    # 生成模拟数据，封存最后一代到 holdout/（只读）
make campaign        # 跑 DESIGN.md P6 的六个 arm：模拟 + 公开猪数据，约 15–20 分钟
make watch           # 浏览器打开 http://localhost:8501 看面板
```

系统要求：Python ≥ 3.9（3.10+ 更好），4 核 8 GB 内存足够；不需要 R、不需要联网（公开数据已随仓库附带）。
没有 Anthropic API key 时，agents 走内置的确定性 StubLLM，整条流水线照常运行；有 key 时自动切到 `claude-opus-5`。

## 2. 核心概念（读懂面板和报告所需的最少词汇）

| 词 | 含义 |
|---|---|
| 冠军 champion | 冻结的 ssGBLUP（均匀标记权重 + campaign 开始时 REML 估的 λ），一次 campaign 内永不变 |
| 挑战者 / 候选 candidate | 一条 DSL 表达式 `champion() + 算子(...)`，最多 4 个算子 |
| 提案 proposal | Geneticist 提出的一个假设（机制、方向、可证伪点、预期增益），可能产生 0 或多个候选 |
| 门 gate | 六道确定性检查：0 有效性、1 准确度（LR 法）、2 增量（配对 ΔOOS）、3 方案（ΔF、进展/年）、4 稳健性、5 研究（多重检验） |
| 晋级 promoted | 六道强制门全部通过。**没有任何 agent 能让候选晋级，只有 `gates/` 能。** |
| ΔOOS | 候选相对冠军的配对预测相关增量（同切分、同种子、同标签），用 bootstrap 给 90% 区间 |
| 负对照 | E：标签在同世代内打乱后跑整个内环；F：随机 30% SNP 子集。它们如果晋级，harness 就是坏的 |
| holdout | 最后一个世代，`make seal-holdout` 后只读，agent 代码永远读不到，campaign 结束后由 `final_table.py` 打开一次 |
| 台账 registry | `registry/abl.sqlite`：每个提案、评审、门结果、成本、状态变迁，只追加不修改 |
| BreedingPackage | 一个候选的完整交付物：机制 → DSL → 数据声明 → 测试 → 溯源 → 六道门数值，在 `registry/packages/<候选id>.md` |

## 3. 命令一览

| 命令 | 做什么 | 产出 |
|---|---|---|
| `make test` | 全部测试 | 终端 |
| `make seal-holdout` | 模拟 6 代 × 500 头，封存第 5 代 | `holdout/sim/`（只读）、`data/snapshots/sim_dev.pkl` |
| `make sim-controls` | 冠军 / 随机算子 / 打乱标签 / 随机 SNP，真育种值已知 | `reports/sim_controls.md`、`reports/scorecard.md` |
| `make pig-public` | 冠军 + 短内环跑 Cleveland 猪数据 | `reports/BreedingPackage_pig_cleveland.md` |
| `make campaign` | P6 完整实验：A–F 六个 arm，模拟 + 猪 | `reports/campaign_*.json`、`final_holdout_sim.md`、记分卡、猪 BreedingPackage |
| `make scorecard` | 从台账重算系统记分卡 | `reports/scorecard.md/.json` |
| `make views` | 重建并打印 OPS.md A.3 的九个分析视图 | 终端（DuckDB） |
| `make watch` | 监护面板（独立进程，只读） | 浏览器 |
| `make status` | 一屏文本：最近 24 小时 | 终端 |
| `make digest` | 每日摘要 | `registry/digest_YYYY-MM-DD.md` |
| `make clean-runtime` | 删除台账、事件流、快照、封存数据（**不可逆**） | — |

`make campaign` 的参数（直接调脚本）：
```bash
.venv/bin/python scripts/run_campaign.py --datasets sim,pig --proposals 100 --full-evals 12 --arms ABCDEF --seed 0
.venv/bin/python scripts/run_campaign.py --datasets sim --arms AD --proposals 30 --full-evals 4    # 快速试跑
.venv/bin/python scripts/run_campaign.py --datasets pig --pig-max-markers 10000                   # 猪数据降采样提速
```
每次运行都会以新的 campaign id（带时间戳）追加进台账，不覆盖旧结果。

## 4. 环境变量与开关

| 变量 / 文件 | 作用 | 默认 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 有则 agents 用 `claude-opus-5`（结构化 JSON 输出、服务器端 refusal fallback） | 无 → StubLLM |
| `ABL_LLM=anthropic\|stub` | 强制后端 | 自动 |
| `ABL_LLM_FALLBACKS=0` | 关闭服务器端 fallback | 开 |
| `ABL_LANG=zh\|en` | 面板、`make status`、`make digest` 的语言（面板侧栏也可切换） | `zh` |
| `ABL_ROOT` | 把整个系统指向另一棵目录（测试用） | 项目目录 |
| `control/RUN` | 存在 = 允许运行 | 随仓库存在 |
| `control/PAUSE` | 存在 = Orchestrator 在下一步前停下并写 `registry/status_<campaign>.json` | 面板 PAUSE 按钮创建 |
| `gates/thresholds.yaml` | 六道门的阈值。**改它必须新 commit**；campaign 开始时记录其哈希，中途变化面板会红警 | — |

## 5. 面板怎么看（`make watch`）

左栏"学习"：
- **叙事流**：一行一个事件，人话。开关"只看 Critic 退回、门失败、晋级和策略标记"可过滤噪音；点开可看原始 JSON。
- **机制簇图**：agents 反复提同一类机制说明语料或先验偏了，该换检索源（OPS.md D.4）。
- **漏斗**：提案 → 已评审 → 已实现 → 通过有效性 → 全量评估 → 晋级，今日 vs 累计。
- **解释候选**：选一个候选 id，看它的 BreedingPackage 六个 tab 和每道门的数值/阈值/通过与否。有包的候选排在前面。

右栏"监护"：
- **策略报警**（任一为红即需要看）：`holdout_touch`（agent 输入里出现封存数据）、`threshold_changed`（阈值文件哈希变了）、`retry_limit`、`budget_exceeded`（真正超支，按计划用完不算）、`cluster_concentration`（单簇 > 40%）、`suspicious_pass_rate`（通过率 > 基线 3 倍）、`events_stalled`（15 分钟无事件）。
- **预算**：token 与全量评估的用量 / 上限、燃烧率、预计耗尽时间。
- **PAUSE / RESUME**：创建 / 删除 `control/PAUSE`。不走网络、不走信号，最笨最稳。
- **Agent 可靠性**：Critic 对泄漏探针的拒绝率（应为 100%）、误晋级数（应为 0）。

每天的用法：早上 `make status`，白天面板开着有红才看，晚上 `make digest` 两分钟读完，每周 `make scorecard` 贴进技术 note。

## 6. 读报告

- `reports/sim_controls.md`：harness 可信度的一张表。看三个数：冠军真准确度（应明显 > 0）、打乱标签后的真准确度（应 ≈ 0）、负对照误晋级数（必须 0）。注意 LR ρ 在打乱标签上仍然很高，这是 LR 法本身的性质，所以门 1 用经验空分布校准、门 2 用组内预测相关。
- `reports/scorecard.md`：DESIGN.md §3.4 的系统记分卡，一行一个 campaign。`false_promotions_on_negative_controls` 和 `critic_reject_rate_on_leak_probes` 是信任指标；`full_evals_per_promotion` 和 `compute_seconds` 是成本指标。
- `reports/final_holdout_sim.md`：封存世代上的最终表，campaign 结束后只打开一次；事件流里会有一条 `holdout_final_read`。
- `reports/BreedingPackage_*.md`：给育种主管看的候选交付物。第 6 节的表里每道门一行，FAIL 的那行就是"为什么没晋级"。
- `registry/digest_YYYY-MM-DD.md`：数字来自 SQL，叙事句子来自 LLM（或 stub），LLM 不能改数字。

## 7. 写自己的候选 / 扩展算子

DSL 语法见 `dsl/grammar.md`。手工评估一条表达式：
```python
from dsl import parse, validate, compile_program
from engine import Evaluator, freeze_champion
from genoframe import forward_splits
from scripts._common import sim_bundle

b = sim_bundle()
pub = b.frame.public_view()
splits = forward_splits(pub, "t1", min_train_t=1)
ev = Evaluator(pub, b.priors, "t1")
freeze_champion(ev, splits[-1], blend_w=0.05, covariates=["line", "farm", "birth_t"])
spec = compile_program(validate(parse("champion() + dominance(w=0.2)"), known_priors=set(b.priors)))
for s in splits:
    st = ev.evaluate(spec, s)
    print(s.cutoff_t, round(st.rho, 3), round(st.extra["predictive_r"], 3), round(st.dispersion, 2))
```
加新算子的步骤：(1) `dsl/ast.py` 的 `OPERATORS` 里登记参数、单位、触碰的字段；(2) `dsl/compiler.py` 把它编进 `ModelSpec`；(3) `engine/evaluate.py` 实现；(4) `dsl/grammar.md` 写文档；(5) `tests/test_dsl.py` 加用例。`multi_trait` 和 `env_covariate` 目前是保留字，Builder 会返回 NEED_OPERATOR。

接新数据集：照 `dataio/loaders.py::load_pig_cleveland` 写一个返回 `GenoFrame` 的函数，`validate()` 会检查契约（无静默前填、每个标签有 `available_at`、系谱合法）。没有真实时间轴时用 `pseudo_generations` 生成家系块，并在 `meta["calendar_source"]` 里如实标注。

## 8. 接客户数据（影子运行）

1. 客户数据装成 `GenoFrame`，`genotype_source` 填 `solid/liquid/seq`，`owner="customer"`。
2. `make seal-holdout` 的逻辑换成"封存最近一个选种周期"。
3. 跑一次 campaign，只记录不干预；`recommendations` 表由 `campaigns/` 写入，`decisions` 和 `outcomes` 等客户回填。
4. 权属三句话（OPS.md A.4）：`recommendations/decisions/outcomes` 原始行归客户；聚合后统计归 NewCo；`proposals/candidates/gate_results` 归 NewCo。这三个字段（`owner`、`sharing_tier`、`deidentified`）每行都有。

## 9. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `make test` 报 `unsupported operand type(s) for \|` | Python < 3.10 且用了旧版本代码 | `git pull`（已修）或升级到 3.10+ |
| `make watch` 页面空白 | 台账还没生成 | 先 `make campaign` 或 `make sim-controls` |
| 面板红警 `retry_limit` | Builder 修不好 Critic 退回的问题（stub 下常见） | 属预期；真 LLM 下若频繁出现，看该候选的 `critic_reviews` |
| 面板红警 `threshold_changed` | campaign 中途改了 `gates/thresholds.yaml` | 该 campaign 结果作废，重跑 |
| `git pull` 很慢 | 历史里有一个 33 MB 数据文件，且 git 协议对网络抖动敏感 | `git clone --depth 1`，或给 git 配代理 |
| `holdout_touch` 红警 | 某个 agent 输入里出现了封存数据的摘要或路径 | 立刻 PAUSE，查 `registry/prompts/<input_hash>.in.txt` |
| 想清零重来 | — | `make clean-runtime`（不可逆），再 `make seal-holdout` |

## 10. 不可协商的五条（CLAUDE.md）

1. `holdout/` 下的东西 agent 代码永远不读；测试会 grep。
2. 只有 `gates/` 能改候选状态；agents 只给建议。
3. 每次 agent 调用都往 `registry/events.jsonl` 追加一行。
4. 到处用确定性种子；改阈值必须新 commit 并进台账。
5. 每步之前检查 `control/RUN`；有 `control/PAUSE` 就停下写状态。
