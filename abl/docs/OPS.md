# ABL 开干手册 v0.2
## 回流数据模型 · Playground 启动 · 公开数据清单（猪以外） · 监护面板 Prompt

配套 v0.1《设计与 Prompt 包》使用。v0.1 回答"是什么、为什么"，本文回答"数据怎么留、明天怎么开、去哪找数据、怎么盯着 agent"。

---

## A. 数据回流与产出记录（为分析和商业化设计）

### A.1 设计原则

1. **每一行都带权属**：`owner`（客户 / NewCo / 公共）、`sharing_tier`（private / aggregated / public）、`deidentified`。数据权属协议不是一份 PDF，是这三个字段。
2. **决策与结果分表、用同一把钥匙连**：`recommendations`（我们建议了什么）→ `decisions`（人采纳了什么）→ `outcomes`（一个世代后发生了什么）。这三张表的连接就是第 5 层数据。
3. **只追加，不修改**：所有表 append-only；修正用新行 + `supersedes` 指针。可审计是信任产品的前提。
4. **成本随行记录**：token、算力秒、人工审核分钟都进表，否则算不出"每个有效发现的成本"。

### A.2 表结构（SQLite 起步，DuckDB 分析，字段可直接建表）

```
campaigns        campaign_id, customer_id, species, trait_set, horizon, champion_id,
                 budget_full_evals, budget_tokens, started_at, ended_at, owner, sharing_tier

proposals        proposal_id, campaign_id, agent_model, mechanism_text, mechanism_cluster,
                 direction, falsifiers, expected_gain, novelty_hash, source_refs[], tokens,
                 created_at, owner, sharing_tier

candidates       candidate_id, proposal_id, dsl_text, dsl_hash, code_hash, data_decl_hash,
                 state ∈ {registered, reviewed, implemented, validated, evaluated, promoted, rejected},
                 retry_count, supersedes, created_at, updated_at

critic_reviews   review_id, candidate_id, verdict ∈ {PASS, RETURN, REJECT}, leak_type[],
                 evidence[], tokens, created_at

gate_results     candidate_id, gate ∈ {validity, accuracy, incremental, plan, robustness, research},
                 metric, value, ci_low, ci_high, threshold, passed, cutoff_date, seed,
                 data_snapshot_id, evaluated_at

evaluations      evaluation_id, candidate_id, split_id, rho, bias, dispersion, delta_oos,
                 delta_oos_ci_low, n_train, n_test, compute_seconds, tokens, evaluated_at

data_snapshots   snapshot_id, customer_id, genotype_source ∈ {solid, liquid, seq}, genotype_build,
                 pedigree_version, phenotype_version, n_animals, n_markers, cutoff_date,
                 owner, sharing_tier, deidentified

recommendations  rec_id, customer_id, selection_date, candidate_id, snapshot_id, animal_id,
                 score, rank, pct_rank, recommended_action ∈ {keep, cull, mate_with:<id>},
                 issued_at, owner=customer

decisions        rec_id, adopted (bool), actual_action, decided_by_role, decided_at,
                 override_reason, owner=customer

outcomes         outcome_id, rec_id, animal_id, outcome_type ∈ {progeny_phenotype, debv,
                 survival, culled, litter, egg, fcr, ...}, value, observed_at, generation,
                 owner=customer

agent_events     ts, campaign_id, agent, action, input_hash, output_hash, tokens, latency_ms,
                 policy_flags[]  (holdout_touch, budget_exceeded, threshold_edit, retry_limit)

costs            campaign_id, customer_id, period, tokens, compute_seconds,
                 human_review_minutes, cash_cost

controls         campaign_id, arm ∈ {champion, random_ops, one_shot_llm, human_batch,
                 shuffled_labels, random_snp}, metric, value, evaluated_at
```

### A.3 分析视图（`make views` 一键生成）

| 视图 | 回答的问题 | 用途 |
|---|---|---|
| `v_funnel` | 100 个提案 → 多少通过 Critic → 多少全量评估 → 多少晋级 | 系统记分卡 |
| `v_cost_per_promotion` | 每个晋级候选花了多少 token/算力/人工 | 预算与定价 |
| `v_adoption` | 建议被采纳的比例、按客户/性状/排名分位 | 客户信任度、产品化程度 |
| `v_realized` | 采纳 vs 未采纳个体的子代结果差（同截止日配对） | 可归因价值（谨慎：非随机，只做描述） |
| `v_drift` | 准确度、偏差、离散度随时间变化 | 部署契约 kill rules |
| `v_diversity` | 机制簇分布、单簇占比 | 防止同质化 |
| `v_critic_quality` | Critic 在负对照上的拒绝率 / 在正对照上的误杀率 | agent 可靠性 |
| `v_marker_value` | 哪些标记/区域在增量门上反复贡献 | **回馈母公司芯片设计** |
| `v_customer_scorecard` | 每客户：遗传进展/年 vs 成本 | 续约与定价 |

### A.4 商业化分析（从同一份台账里长出来的六个产品）

| 产品 | 数据来源 | sharing_tier | 谁付钱 |
|---|---|---|---|
| 客户价值报告（年度 ROI） | `v_customer_scorecard` | private | 客户续费依据 |
| 跨客户基准（脱敏分位数） | `outcomes` 聚合 | aggregated | 客户、行业协会 |
| 芯片内容迭代建议 | `v_marker_value` | NewCo 内部 → 母公司 | 母公司（关联交易的价值锚） |
| 机制先验库 | `proposals` + `gate_results` 跨客户 | NewCo IP | 新客户冷启动加速 |
| 可复现审计凭证 | `candidates` 哈希 + `evaluations` | private | 保险/融资尽调/客户审计 |
| 定价实验 | `recommendations` × `decisions` × `costs` | internal | 捆绑 vs 按建议计费 |

**权属边界**：`recommendations/decisions/outcomes` 的原始行归客户；聚合到 `aggregated` 层后的统计归 NewCo；`proposals/candidates/gate_results` 归 NewCo。这三句话就是数据协议的骨架。

---

## B. 真的开干：Playground 启动与 md 文件的用法

### B.1 独立环境（macOS，`~/Desktop/playground/abl`）

```bash
# 一次性
mkdir -p ~/Desktop/playground/abl && cd ~/Desktop/playground/abl
git init
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip numpy pandas scipy scikit-learn duckdb pyarrow pyyaml pytest rich streamlit
# 可选：R + AlphaSimR（真实育种值已知的模拟器）；没有 R 就让 Claude 写一个 Python 简化模拟器
# brew install r && Rscript -e 'install.packages("AlphaSimR", repos="https://cloud.r-project.org")'
mkdir -p docs data/raw data/snapshots registry holdout control dashboard
cp ~/Downloads/AgenticBreedingLoop_拉索NewCo_设计与Prompt包.md docs/DESIGN.md
cp ~/Downloads/ABL_开干手册_v0.2.md docs/OPS.md
chmod -R a-w holdout        # 防火墙第一层：文件系统只读
touch control/RUN            # 存在 = 允许运行；删掉或改名 PAUSE = 暂停
```

`CLAUDE.md`（放仓库根目录，Claude Code 每次都会读）：

```
# ABL — Agentic Breeding-value Loop
Read docs/DESIGN.md (contract, roles, gates, prompts) and docs/OPS.md (registry schema,
dashboard, data sources) before any change. Non-negotiables:
1. Nothing under holdout/ is ever read by agent code; tests grep for it.
2. Only gates/ may change a candidate's state; agents return recommendations only.
3. Every agent call appends one line to registry/events.jsonl (schema in OPS.md A.2).
4. Deterministic seeds everywhere; no threshold edits without a new commit + entry in registry.
5. Before each loop step, check control/RUN exists; if control/PAUSE exists, stop and write status.
Work in small commits. Run `pytest -q` before reporting done.
```

隔离：单独 venv、单独 git、`.env` 只放这个项目的 key、Claude Code 不加 `--add-dir`；它看不到你别的目录。

### B.2 五个阶段、五条 prompt（每阶段一条，做完 commit 再下一条）

| 阶段 | 给 Claude Code 的一句话 | 完成标志 |
|---|---|---|
| 0 骨架 | "Implement DESIGN.md §P0 repo layout with empty modules, the registry schema from OPS.md A.2 (SQLite + DuckDB views), and the holdout firewall test. No models yet." | `pytest` 通过；`make views` 出表 |
| 1 模拟 + 门 | "Add sim/ (AlphaSimR wrapper or Python fallback with known true BVs), GenoFrame, forward-in-time splitter, and gates 0–2 (validity, LR accuracy, paired incremental). Run `make sim-controls`." | 真 BV 与估计 BV 的相关有数；负对照被拒 |
| 2 公开数据 | "Add loaders for the datasets in OPS.md C.1 marked ★ (start with Cleveland pig). Fit the frozen ssGBLUP champion. Run `make pig-public`." | 一个 BreedingPackage 生成 |
| 3 内环 + 外环 | "Implement agents/ with prompts P1–P5, the orchestrator state machine, semantic-hash dedup, budget control, then run the campaign in P6." | 记分卡出表 |
| 4 面板 | "Build dashboard/ per OPS.md D (read-only, separate process). Run it with `make watch`." | 浏览器里看到事件流 |

### B.3 你每天怎么用

- 早：`make status`（一屏：昨天提案数/晋级数/花费/警报）。
- 白天：面板开在一个浏览器 tab，不看也行；有红色警报才看。
- 晚：`make digest` 生成 `registry/digest_YYYY-MM-DD.md`，两分钟读完。
- 周：`make scorecard`，把表贴进你的技术 note（发表权）。

---

## C. 公开数据：清单、猪以外能发现什么、还有什么数据

### C.1 清单（★ = 先用）

| 来源 | 类型 | 物种 | 内容 | ABL 用途 | 可得性 |
|---|---|---|---|---|---|
| ★ G2P Datasets（Genetics 2026） | 基因型+表型 | 60+ 物种、100+ 数据集 | 公开发表数据集的元数据 + 下载脚本，部分在 Kaggle | **跨物种方法基准**；一次接 20+ 数据集 | 开放 |
| ★ Cleveland 2012 PIC 猪数据（G3） | 基因型+表型+EBV | 猪 | 3,534 头、高密度 SNP、5 性状、系谱 | L1 champion 与内环主战场 | 开放 |
| ★ BGLR 包 `wheat` / `mice` | 基因型+表型 | 小麦、小鼠 | 599 系小麦 4 环境；1,814 只小鼠 | 跨物种 sanity | 开放（R 包自带） |
| ★ CropGS-Hub（NAR 2024） | 基因型+表型 | 主要作物 | 面向基因组预测整理的作物资源 | 作物线（拉索已有麦/油菜/番茄芯片） | 开放 |
| G2F Genomes to Fields | 基因型+表型+环境 | 玉米 | 多年多环境杂交种试验 | **G×E 算子**的测试场（对应圣农多场区） | 开放 |
| FarmGTEx：PigGTEx / CattleGTEx / ChickenGTEx | 分子 QTL | 猪、牛、鸡 | ChickenGTEx：7,015 份 RNA-seq、28 组织、2,869 个体 WGS、100+ 品种 | **生物先验算子**（eQTL 加权 SNP）；芯片内容设计 | 开放 |
| Animal QTLdb | QTL/关联 | 畜禽 | 文献 QTL 汇总 | Geneticist 的检索库、区域先验 | 开放 |
| Horvath 泛哺乳动物甲基化数据（GEO） | 甲基化+年龄 | 数百种哺乳动物 | 跨物种 CpG 阵列数据、年龄标签 | **L2 表观时钟**：探针筛选、跨物种迁移 | 开放 |
| CDCB / Interbull | 公开公牛评估 | 奶牛 | 公牛 PTA/EBV（无原始表型） | 牛线标签替代品 | 开放（汇总） |
| Sheep HapMap / NSIP | 基因型 / EBV | 羊 | 全球羊群基因型；美国羊 EBV | 扩物种 | 开放 |
| CNCB-NGDC（GSA、GVM） | 序列 | 中国地方品种 | 猪、鸡等 WGS | 中国品种低密度面板设计、遗传资源叙事 | 开放（部分需申请） |
| 全国种猪遗传评估中心 | 汇总排名 | 猪 | 国家核心育种场公猪排名/指数 | 中国市场校准、竞品对照 | 公开汇总 |
| 鸡基因型-表型配对 | — | 鸡 | 极少；零星论文小样本（如台湾土鸡 GS 论文） | 只能靠模拟 + 客户数据 | 稀缺 |
| 水产 | — | 鲑、罗非鱼零星；中国对虾几乎无 | 论文附带 | 稀缺 | 稀缺 |

Cleveland 论文里有一句话值得记住：商业数据有经济价值，所以畜禽领域有意义规模的公共数据集一直很少。**这句话就是 NewCo 的商业理由**——数据托管层之所以有价值，正因为公开数据填不上第 3-5 层。

### C.2 猪以外，公开数据里真能挖出的五样东西（按商业价值排）

| # | 实验 | 数据 | 预期产出 | 对拉索的价值 |
|---|---|---|---|---|
| 1 | **芯片内容设计**：eQTL/QTL 加权 SNP 是否在增量门上稳定贡献 | FarmGTEx + QTLdb + G2P 中的猪/鸡/牛数据集 | 一份"哪些区域值得上芯片"的证据表 | 直接回馈母公司下一代芯片；关联交易的价值锚 |
| 2 | **跨物种甲基化探针筛选**：复现泛哺乳动物时钟，筛出猪/牛/犬保守 CpG | Horvath GEO 数据 | 国产跨物种甲基化芯片的候选探针清单 | L2 立项的技术起点；院士共研的敲门砖 |
| 3 | **G×E 算子**：环境协变量能否提升多环境预测 | G2F 玉米 | 多场区模型模板 | 圣农多场区、未来牛线 |
| 4 | **方法基准图**：20+ 数据集上"什么时候有东西能赢 GBLUP" | G2P Datasets | 一张"按遗传力/样本量/性状类型分的 ΔOOS 期望图" | 给客户报价时的先验；技术 note 第一篇；诚实的招牌 |
| 5 | **中国地方品种低密度面板** | CNCB WGS | 面板设计方法 + 遗传资源叙事 | 种业振兴项目、引导基金 |

诚实预期：1、2 大概率有正结果（先验和保守 CpG 是真实生物学）；3 取决于环境数据质量；4 大概率是"很少赢"——这正是你要的结果，它让 harness 而不是模型成为产品；5 是政策线产物。**公开数据挖不出第 5 层（决策→结果），这一层只有客户能给。**

### C.3 除了公开数据，还有什么数据

| 类别 | 例子 | 怎么拿 | 备注 |
|---|---|---|---|
| 模拟数据 | AlphaSimR、自写模拟器 | 自己生成 | 真值已知，是正负对照的唯一来源 |
| 分子先验 | FarmGTEx、QTLdb、Ensembl | 开放 | 不是训练集，是算子的先验 |
| 公开汇总/EBV | CDCB、Interbull、种猪评估中心 | 开放 | 无原始表型，可作标签替代 |
| 母公司检测流水 | 拉索数百万样本的基因型 | 章程里的接口权 | 有基因型无表型：可做群体结构、填充参考面板、面板设计 |
| 客户数据换服务 | 温氏、圣农、牧场 | 影子运行 + 数据协议 | **唯一能给第 3-5 层的来源** |
| 院所合作方 | 黄路生团队、农科院牧医所、北京农林科学院 | 共研模式（拉索已有先例） | 历史表型池、论文数据 |
| 政府测定数据 | 种猪性能测定站、国家核心育种场 | 项目/协作 | 政策线入口 |
| 生产系统数据 | ERP、饲喂、称重、摄像 | 客户部署时接入 | 未来的表型自动化（phenomics） |
| 文献 | 综述、研报、专利 | 语料库 | Geneticist 的检索对象 |

---

## D. 监护面板（Guardian & Learning Dashboard）

### D.1 设计要求（不干扰、可监控、可学习）

- **物理隔离**：agent 只做一件事——往 `registry/events.jsonl` 追加一行；面板是**另一个进程**，只读文件，不 import agent 代码，不持锁，5 秒轮询。agent 挂了面板还在，面板挂了 agent 不受影响。
- **两块屏**：左"学习"——每个 agent 刚才做了什么（人话叙述）、提了什么机制、Critic 为什么退回、门的结果；右"监护"——预算燃烧率、holdout 触碰尝试、阈值文件哈希是否变化、重试超限、单簇占比过高、异常高通过率。
- **一个开关**：`control/PAUSE` 文件。面板上一个按钮 = 创建这个文件；Orchestrator 每步之前检查。不通过网络、不通过进程信号，最笨最稳。
- **每日摘要**：一页 markdown，2 分钟读完。

### D.2 事件 schema（agent 端唯一义务）

```json
{"ts":"2026-09-25T09:12:03Z","campaign_id":"c01","agent":"critic","action":"review",
 "candidate_id":"k0042","input_hash":"…","output_hash":"…","tokens":1830,"latency_ms":4210,
 "summary":"Returned to builder: lookback uses phenotype available_at > selection_date (field: litter_size)",
 "policy_flags":[],"cost_usd":0.011}
```

### D.3 Prompt（给 Claude Code，独立运行于 dashboard/）

```
Build a read-only "Guardian & Learning" dashboard for ABL in dashboard/ as a SEPARATE process.
Hard rules: it must never import from agents/, engine/ or gates/; it only tails
registry/events.jsonl and reads the SQLite registry with a read-only connection; it must not
write anything except dashboard/state.json and, on operator action, the file control/PAUSE.
Polling interval 5s; CPU under 3%; if the registry is locked, skip the tick, never block.

Views (Streamlit, single page, two columns):
LEFT "Learning":
  - Live narrative feed: one plain-language line per event (who, did what, to which candidate,
    why); Critic returns and gate failures highlighted; click to expand raw event.
  - Mechanism map: clusters of proposals (bar or treemap) with promoted/rejected counts.
  - Funnel today vs campaign-to-date: proposals → reviewed → implemented → validated →
    evaluated → promoted.
  - "Explain this candidate": select a candidate_id, render its BreedingPackage sections and
    all gate results with thresholds.
RIGHT "Guardian":
  - Budget: tokens and full evaluations used vs cap, burn rate, projected exhaustion time.
  - Policy alarms (red if any): holdout_touch, threshold file hash changed since campaign start,
    retry_limit exceeded, budget_exceeded, single mechanism cluster > 40% of proposals,
    gate pass-rate > 3x campaign baseline (suspicious), events stalled > 15 min.
  - Controls: PAUSE / RESUME buttons that create/delete control/PAUSE; show current state.
  - Agent reliability: Critic verdicts on negative-control candidates (should be REJECT),
    false-promotion count.
Also implement:
  - `make watch`  → runs the dashboard.
  - `make status` → prints a one-screen text summary of the last 24h (same numbers, no UI).
  - `make digest` → writes registry/digest_YYYY-MM-DD.md: 5 bullets on what was learned,
    3 bullets on what was rejected and why, alarms, cost, and the single next experiment
    the Analyst proposed. Use the LLM only for the narrative bullets; numbers come from SQL.
Notifications: on any red alarm, append to registry/alarms.log and, on macOS, call
`osascript -e 'display notification ...'` at most once per 10 minutes per alarm type.
Tests: a fake events file must render without the agent stack installed.
```

### D.4 你从面板上要学的三件事（不是看热闹）

1. **Critic 在拒什么**——它拒的理由就是这个领域的泄漏教科书，一周后你会比大多数生信工程师更懂时间边界。
2. **机制簇在哪里聚**——agents 反复提同一类东西，说明语料或先验偏了，该换检索源。
3. **钱花在哪一步**——全量评估是瓶颈（陈奕语的原型也是这个结论：每个有效读数的时间是 12 倍），这决定 NewCo 的算力预算和产品定价。

---

## E. 一页时间线

| 周 | 你做 | agent 做 | 产出 |
|---|---|---|---|
| 1 | 启动环境、阶段 0-1 | 骨架、模拟、门 | `make sim-controls` 表 |
| 2 | 阶段 2、接 G2P 的 5 个数据集 | champion 基线 | 第一个 BreedingPackage |
| 3 | 阶段 3、开面板 | 内环 100 提案 | 记分卡、digest |
| 4 | 跑 C.2 的实验 1、2 | 外环 1 次 | 芯片内容证据表 v0、甲基化探针清单 v0、技术 note 草稿 |
| 去苏州 | 带：记分卡 + 两份 v0 + "harness 拒绝了什么" | — | — |
