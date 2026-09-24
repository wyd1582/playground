# Agentic Breeding-Value Loop（ABL）
## 把"Agentic Alpha Loop"平移到拉索 NewCo：设计原理、目的、30 天实验与 Prompt 包

版本 v0.1 · 2026-09-24 · 供一号位自用；Prompt 可直接粘贴进 Claude Code / 任意 agent 框架

---

## 0. 一句话

**Alpha signal 的定义——"每个实体每个日期一个分数，横截面排名预测未来相对结果"——和育种值（GEBV / 选择指数）是同一个数学对象。** 陈奕语那套"agents 探索、确定性 harness 决定谁存活"的结构，可以逐模块平移到育种：把"股票"换成"候选个体"，把"未来收益"换成"子代表现 / 后验育种值"，把"回测"换成"跨世代前向验证"。平移之后得到的不是一个 demo，而是拉索 NewCo 的 L0 产品本身，以及第 5 层数据（决策→结果台账）的生产机器。

---

## 1. 类比映射表

| Alpha Loop（金融） | Breeding Loop（拉索） | 备注 |
|---|---|---|
| 股票 universe（当日可交易） | 当次选种的候选群体（在群、已基因分型、未淘汰） | `in_universe` 同义 |
| signal_date | selection_date（选种/配种决策日） | 一年 2-6 次而非每日 |
| 横截面分数 | GEBV / 选择指数 / 排名 | 一个数字 per 个体 per 决策日 |
| 未来相对收益 | 子代表型、后验 DEBV、实现遗传进展 | 标签延迟 = 一个世代（鸡 ~1 年，猪 ~1.5 年，牛 ~3 年） |
| IC / rank IC | 预测准确度（LR 法相关系数） | Legarra & Reverter 2018 的 LR 方法就是育种界的"paired OOS" |
| 因子 / 特征 | SNP 面板、基因区域先验、系谱、表型、环境协变量 | 芯片 = 数据生成设备 |
| 因子 library + frozen baseline | ssGBLUP / GBLUP + 现行选择指数 | 这就是"LLM vs BLUP"问题的裁判台 |
| PIT（point-in-time）数据 | 决策日之前已记录的系谱/表型快照 | 最常见泄漏：用了决策日之后才录入的子代/同胞记录 |
| 因子间相关性、pruning | 性状相关、指数权重、亲缘冗余 | PM mindset ↔ 育种主管 mindset |
| 组合层：成本、风险、回撤、容量 | 配种方案：近交率 ΔF、遗传进展/年、选择强度、分型成本 | 组合优化 ↔ 最优贡献选择（OCS） |
| Regime（牛熊、行业） | 场区、年份、品系、G×E | 稳健性门 |
| 交易日历、涨停板 | 生产日历、隔离期、圈舍容量 | tradability ↔ 可执行性 |
| 因子库、trial ledger | **决策→结果台账**（第 5 层数据） | 这是 NewCo 要拥有的资产 |
| Champion–challenger | 现行流程 vs 新流程的配对对照 | 用同一批候选、同一截止日 |
| Information firewall | 最新世代永不进入 prompt / 记忆 | 防止 LLM"看过答案" |
| Research-to-live parity | 影子运行：与圣农现行手工指数并行一轮 | 部署契约 |

---

## 2. 目的：这个东西为什么对拉索有用

1. **它就是 L0 产品**。圣农的参考群体更新 + 育种值计算现在是拉索手工且免费做的；ABL 把它变成可复制、可审计、可收费的产品，交付物是 `BreedingPackage`（机制 + 实现 + 数据声明 + 测试 + 溯源 + 评估），不是一份 Excel。
2. **它生产第 5 层数据**。permanent record = 每一次选种建议、被采纳与否、子代结果。这份台账是 NewCo 长期最稀缺的资产，也是跨客户模型的训练集。
3. **它把"LLM vs BLUP"从争论变成实验**。李总留下的开放问题、JD 上的"DeepSeek 微调"要求，都可以用同一句话回答："GBLUP 是冻结的 champion，任何 LLM/深度学习方法是 challenger，只有配对 ΔOOS 过门才晋级。" 这句话既保护公司不被 hype 带偏，也给了 AI 一个公平上场的机会。
4. **它落实平台中立**。`GenoFrame` 数据契约只认 `animal_id × selection_date × genotype_source`，固相、液相、测序数据都能进——第 4.2 节原则的工程实现。
5. **它 30 天可演示**。公开数据 + 模拟器（AlphaSimR）就能跑通并给出对照实验，正对着你 90 天计划的 Day 0-30。
6. **同一 harness 可复用到 L2/L3**。表观时钟（个体 × 采样日 × 生物年龄分数，排名预测生产寿命/存活）、靶点优先级（靶点 × 版本 × 分数，排名预测后续验证成功）都是"横截面分数预测前向结果"——harness 不变，只换 DSL 和门槛。

---

## 3. 架构

```
                    ┌──────────────────────────────────────────────┐
                    │  SYSTEM LOOP（外环）：champion–challenger        │
                    │  一次只改一个受控变量；配对 campaign；防火墙       │
                    └──────────────────────────────────────────────┘
                                          │
   REGISTERED INPUTS          AGENTIC CANDIDATE LOOP（内环）          DETERMINISTIC CORE
   ─────────────────          ───────────────────────────            ──────────────────
   Research brief             Orchestrator  状态/预算/角色隔离        PIT snapshot   系谱+表型截止视图
   （物种·性状·选择周期·目标）  Geneticist    机制 + 可证伪点           DSL compiler   AST + 单位 + 因果检查
   Data catalog               Builder       DSL/代码 + 测试           GRM/BLUP engine 沙箱，固定随机种子
   （芯片/系谱/表型/环境）      Critic        泄漏·结构·机制-代码匹配    Forward-in-time  跨世代验证 + LR 法
   Frozen baseline            Analyst       诊断 + 下一个实验         Registry       trial ledger（永久）
   （ssGBLUP + 现行指数）                                              
   Constraints                          ↓ 只有机器可检查的门改变候选状态
   （ΔF 上限·分型预算·世代间隔）
   Budget & memory            OUTPUT：BreedingPackage
                                      → FINAL HOLDOUT：最新一个世代，开发期不可见
```

**核心原则（一字不改地从 alpha loop 继承）**：agents 推荐，只有确定性门槛能改变候选状态；每一个提案、拒绝、重试、成本、结果永久记录；很多假设，很少全量评估；holdout 永不进入 prompt。

### 3.1 五个角色的育种版定义

| 角色 | 输入 | 输出 | 育种特有职责 |
|---|---|---|---|
| Orchestrator | brief、预算、registry | 任务分派、状态机 | 控制"全量 BLUP 评估"次数（最贵的一步）；语义哈希去重 |
| Geneticist（=Researcher） | 文献、QTL/基因注释、registry 历史 | 假设：机制、方向、性状、可证伪点 | 必须写出"如果这个先验是假的，数据会长什么样" |
| Builder | 假设 | DSL 表达式 / 代码 + 单元测试 | 只能用受限算子（GRM 加权、区域先验、协变量、多性状） |
| Critic | 假设 + 代码 + 数据声明 | 通过/退回 + 理由 | 三类泄漏：时间（决策日后记录）、亲缘（训练/测试近亲）、结构（品系混淆）；机制-代码匹配 |
| Analyst | 评估结果 | 诊断 + 下一个实验 | 偏差、离散度、G×E、近交代价 |

### 3.2 数据契约 GenoFrame

```
key:      animal_id × selection_date
fields:   score | in_universe | available_at | genotype_source ∈ {solid, liquid, seq}
versions: genotype_build | pedigree_snapshot | phenotype_snapshot | calendar | code | universe
timeline: T-∞…T-1 历史记录（仅 available_at ≤ T）
          T          候选群体 + 分数
          T+1        配种/留种执行（可执行性检查：圈舍、隔离、健康）
          T+G        子代表型 / 后验 EBV 到达（标签出口）
rules:    无静默前向填充；无重复键；训练集按"标签出口 ≤ 截止日"过滤；
          跨世代 purge（测试个体的父母/全同胞记录不得进入训练）
```

### 3.3 六道门（育种版）

| # | 门 | 指标 | 说明 |
|---|---|---|---|
| 0 | Validity | 因果截止、确定性、测试通过 | 未过不进评估 |
| 1 | Accuracy | LR 法：相关 ρ、偏差 μ、离散度 b；覆盖率 | 离散度 b 显著 ≠ 1 视为失败（过度/不足离散） |
| 2 | Incremental | 配对 ΔOOS = M(F∪B) − M(F)，同截止日、同种子、同标签 | 对 frozen ssGBLUP 的增量，不看绝对值 |
| 3 | Plan（=Portfolio） | 等成本下的遗传进展/年、ΔF、选择强度、分型成本 | 用 OCS 规则统一 |
| 4 | Robustness | 场区/年份/品系分组、去掉 top 家系的扰动 | 无单一场区解释结果 |
| 5 | Research | 试验计数、多重检验校正（DSR 类） | 小样本（数千头）下尤其重要 |

**晋级条件**：全部强制门通过；配对下界过阈；近交代价可接受；无单一场区解释。一个漂亮的相关系数不能绕过失败的门。

### 3.4 系统记分卡（评价系统，不评价最好的一次回测）

每 100 个提案的有效候选数 · 每个晋级候选消耗的全量 BLUP 评估数 · 校正后的平均/最佳 ΔOOS · 负对照（打乱标签、随机 SNP 集）上的假晋级数 · 机制多样性 · 从哈希复现的比例 · 每个合格候选的育种主管审核时间。
**对照臂**：随机算子搜索 · 一次性 LLM · 育种主管手工批次 · 上一版 loop。

### 3.5 部署契约（研究到实盘的平行）

FREEZE（代码/数据/校准）→ REPLAY（历史选种日重放，分数与当时手工指数逐头比对）→ SHADOW（与圣农现行流程并行一个选种周期，只记录不干预）→ DECISION（育种主管审批 + kill rules：准确度跌破阈、ΔF 超限、数据延迟超期即回滚）。

---

## 4. 30 天实验计划（公开数据，零客户数据）

| 天 | 做什么 | 数据 |
|---|---|---|
| 1-5 | 搭 GenoFrame + registry + forward-in-time 验证器 + LR 法门 | AlphaSimR 模拟（真实育种值已知 → 可算"真 IC"，做正/负对照） |
| 6-12 | frozen champion：GBLUP/ssGBLUP + 简单指数 | Cleveland et al. 2012 公共猪数据集（约 3.5 千头、60K SNP、5 性状）；BGLR 包 `wheat`/`mice` 作跨物种 sanity |
| 13-20 | 内环跑通：Geneticist 提 20 个假设 → Builder → Critic → 少量全量评估 | 同上；负对照：打乱表型、随机 SNP 子集 |
| 21-27 | 外环一次：challenger = 深度学习/LLM-衍生特征 vs champion，配对 ΔOOS | 同上 |
| 28-30 | 写 BreedingPackage 示例 + 记分卡 + 一页结论："在公开猪数据上，X 通过/未通过增量门" | — |

**演示口径**：不要说"我们的 AI 比 BLUP 准"，说"我们建了一个能公平裁判任何方法的 harness，并且它已经拒绝了 N 个看起来很好的假阳性"。这句话比任何准确度数字更能建立信任——也正是拉索团队说的"信任、速度、scale"里的"信任"。

---

## 5. Prompt 包

> 约定：`{{...}}` 为占位符。角色 prompt 用英文（模型表现更稳），注释用中文。所有 prompt 假设存在 `registry/`、`genoframe/`、`dsl/` 三个目录与一个只读的 `holdout/`（agents 无权限）。

### P0 · 总建造 Prompt（给 Claude Code，一次性）

```
You are building "ABL" (Agentic Breeding-value Loop), a research harness for genomic
selection. Follow this contract exactly; ask no clarifying questions—make and log assumptions.

GOAL
An agentic inner loop (Geneticist → Builder → Critic → Evaluate → Analyst) explores
hypotheses for improving cross-sectional breeding-value scores; a deterministic core
decides what survives. Agents recommend; only machine-checkable gates change candidate state.

REPO LAYOUT
  genoframe/   data contract + point-in-time snapshots + forward-in-time splitter
  dsl/         restricted operator grammar, AST validator, unit checker, compiler
  engine/      GRM, GBLUP/ssGBLUP (frozen champion), plan simulator (ΔF, gain/yr, OCS)
  gates/       validity, accuracy(LR method: rho, bias, dispersion), incremental(paired),
               plan, robustness, research(multiple-testing)
  registry/    append-only trial ledger: proposal, code hash, data hash, cost, result, disposition
  agents/      orchestrator, geneticist, builder, critic, analyst (prompt files + tool schemas)
  campaigns/   champion–challenger runner; negative controls; scorecard
  holdout/     latest generation; READ-ONLY; never loaded by any agent process
  sim/         AlphaSimR wrapper (true breeding values known) for positive/negative controls

DATA CONTRACT (GenoFrame)
  key = (animal_id, selection_date); fields = score, in_universe, available_at,
  genotype_source in {solid, liquid, seq}; versioned genotype_build, pedigree_snapshot,
  phenotype_snapshot, calendar, code, universe.
  Rules: no silent forward fill; no duplicate keys; training rows require label_exit <=
  cutoff; purge parents/full-sibs of test animals from training; every split is
  forward-in-time across generations.

GATES (all must be deterministic and unit-tested)
  0 validity  1 accuracy(LR)  2 incremental(paired ΔOOS vs frozen champion, same cutoffs/seeds)
  3 plan(ΔF cap, gain/yr at equal genotyping cost)  4 robustness(farm/year/line, drop-top-family)
  5 research(trial count, DSR-style correction). Promotion requires all mandatory gates.

FIREWALL
  Nothing under holdout/ may appear in any prompt, memory file, retrieval index or reward.
  Implement as a filesystem permission + a test that greps agent inputs for holdout hashes.

DELIVERABLES
  1) `make sim-controls`: AlphaSimR campaign where true BVs are known; report true-vs-estimated
     accuracy for champion, a random-operator challenger, and a shuffled-label negative control.
  2) `make pig-public`: run on the Cleveland 2012 public pig dataset; produce one
     BreedingPackage (thesis, DSL, data declaration, tests, provenance, evaluation).
  3) `make scorecard`: valid candidates per 100 proposals, full evaluations per promotion,
     corrected mean/best ΔOOS, false promotions on negative controls, reproducibility rate.
  4) README explaining, in one page, why the harness (not the model) is the product.

STYLE
  Small deterministic modules with fixed seeds; log every agent call with token cost;
  prefer rejecting a candidate over rescuing it.
```

### P1 · Orchestrator（系统 prompt）

```
You are the Orchestrator of ABL. You own state, budget and role separation.
Inputs: research brief {{species, trait(s), selection_horizon, target=progeny phenotype or DEBV}},
data catalog, frozen champion id, constraints {{ΔF_cap, genotyping_budget, generation_interval}},
budget {{max_full_evaluations, max_tokens}}, registry summary (last 200 trials).
Loop: REGISTER → HYPOTHESIZE(Geneticist) → REVIEW(Critic, before any code) → IMPLEMENT(Builder)
→ VALIDATE(cheap screens: AST, units, causality, semantic-hash dedup) → EVALUATE(full, only if
screens pass and budget allows) → DIAGNOSE(Analyst) → next.
Rules: never call full evaluation for a candidate whose semantic hash exists in registry;
retry limit 2 per hypothesis; allocate remaining budget by expected information gain
(prefer mechanisms not yet represented in the registry); write every transition to registry.
You never read holdout/. You never modify gate thresholds. Output a JSON state object only.
```

### P2 · Geneticist（= Researcher）

```
You are the Geneticist. Propose ONE hypothesis for improving cross-sectional breeding-value
ranking for {{species}} / {{trait}} at horizon {{selection_horizon}}.
Required fields (JSON):
  mechanism: biological or statistical reason the ranking should improve (1-3 sentences)
  direction: which animals should move up/down and why
  operator_plan: which restricted DSL operators you intend (e.g., region-weighted GRM,
    QTL-prior weights, multi-trait, environmental covariate, non-additive term)
  falsifiers: what the forward-in-time result would look like if the mechanism is false
  expected_gain: honest prior on paired ΔOOS (accuracy) and on dispersion b
  novelty_check: nearest registry entries and why this differs
Constraints: cite sources from the corpus with ids; do not propose anything that requires
phenotypes recorded after selection_date; do not propose anything already in registry
with disposition REJECTED unless you state what changed. Prefer mechanisms absent from the
registry's mechanism clusters.
```

### P3 · Builder

```
You are the Builder. Convert the approved hypothesis into ABL DSL and tests.
Allowed: operators in dsl/grammar.md only; explicit units; explicit lookbacks; explicit
missing-data policy; deterministic seeds.
Produce: (1) DSL expression or reviewed code, (2) data declaration listing every field with
available_at semantics, (3) unit tests: schema, causality (no field with available_at >
selection_date), replay determinism, edge cases (singletons, missing sire/dam, monomorphic SNPs),
(4) a one-line "thesis-to-code match" statement quoting the hypothesis field it implements.
If the hypothesis cannot be implemented within the grammar, return NEED_OPERATOR with the
minimal operator spec instead of writing free-form code.
```

### P4 · Critic

```
You are the Critic. Your job is to prove the candidate does NOT work. Review hypothesis,
DSL/code and data declaration. Check, in order:
  1 Temporal leakage: any field, pedigree edge or phenotype whose available_at > selection_date.
  2 Relatedness leakage: test animals' parents or full-sibs present in training with phenotypes.
  3 Structure confound: signal explained by line/farm/year rather than genotype.
  4 Thesis–code mismatch: operators that do not implement the stated mechanism.
  5 Dispersion risk: transformations likely to inflate estimated BVs (b < 1) or shrink them.
  6 Plan feasibility: would acting on this ranking violate ΔF_cap or genotyping budget?
Return PASS / RETURN_TO_BUILDER / REJECT with a numbered list of concrete evidence
(file, line, field). You may not approve on the basis of a good accuracy number; accuracy is
not your gate. Never suggest how to "fix" a leak that changes the hypothesis silently—send it back.
```

### P5 · Analyst

```
You are the Analyst. Given gate outputs for a candidate (LR rho/bias/dispersion, paired ΔOOS
with confidence bounds, plan metrics, robustness by farm/year/line, negative-control results),
write: (1) disposition summary in plain language for a breeding manager, (2) diagnosis:
which gate limited the result and the most likely biological/statistical reason,
(3) the single next experiment with the highest expected information gain, (4) an updated
BreedingPackage evaluation section. Never recommend promotion if any mandatory gate failed.
Record the mechanism cluster this candidate belongs to for diversity accounting.
```

### P6 · 实验 Prompt（30 天演示，给 Claude Code）

```
Run a controlled campaign to answer one question honestly: "Does any LLM- or deep-learning-
derived challenger add paired ΔOOS accuracy over frozen ssGBLUP on public pig data, and does the
harness correctly reject negative controls?"
Arms: (A) frozen ssGBLUP champion; (B) random-operator search, same budget; (C) one-shot LLM
proposal without loop; (D) full ABL inner loop, 100 proposals, ≤12 full evaluations;
(E) negative control: shuffled phenotypes; (F) negative control: random SNP subset.
Data: AlphaSimR simulation (true BVs known) and Cleveland 2012 public pig dataset.
Report: scorecard table; one BreedingPackage; one paragraph on what the harness rejected and why.
Do not tune thresholds after seeing results. Holdout generation stays sealed until the final table.
```

### P7 · 给圣农/李总的演示脚本（给自己用的写作 prompt）

```
用育种主管听得懂的话，把上面的 campaign 结果写成一页：
1) 我们不是在推销一个模型，是在交付一个"任何方法都要过的裁判"；
2) 它在公开数据上拒绝了哪些看起来很好的假阳性；
3) 接入圣农数据后第一步是影子运行一个选种周期，不改变现行决策；
4) 每一次建议和结果都会进入台账——这份台账归谁，是我们要在协议里写清的第一件事。
不用任何"AI 超越 BLUP"的措辞。
```

---

## 6. 从陈奕语的辅导反馈里直接复用的三条

辅导里你给他的三点批评，正好是 ABL 要提前满足的：
1. **数据要有**：所以第 4 节第一天就用模拟器 + 公开猪数据，不等客户数据。
2. **回到具体的 signal 与数据**：所以 BreedingPackage 必须写出机制、方向、可证伪点，而不是"AI 找到了一个模式"。
3. **improvement 要落到实处**：所以外环一次只改一个受控变量，负对照永久保留，部署契约写明人在哪里介入、出错怎么回滚。

以及你问他的那个问题——"agentic 到底体现在哪儿"——在 ABL 里的答案是：**角色之间的信息传递是自动的，但改变候选状态的权力不在任何 agent 手里，在门里。** 这句话也是给李总解释"为什么我们不会被 DeepSeek 微调的故事带偏"的答案。

---

## 7. 复用到 L2 / L3（harness 不变，只换 DSL 和门）

| 层 | 实体 × 日期 | 分数 | 前向结果 | 特有门 |
|---|---|---|---|---|
| L1 育种 | 个体 × 选种日 | GEBV/指数 | 子代表型 / DEBV | LR 法、ΔF |
| L2 表观时钟 | 个体 × 采样日 | 生物年龄残差 | 生产寿命、存活、干预后变化 | 跨物种一致性、批次效应 |
| L3 靶点 | 靶点 × 证据版本 | 优先级分数 | 后续验证/临床成功 | 时间边界（Virtual Biotech 式）、文献泄漏 |

同一 registry 跨三层累积，就是"跨物种生命数据的读出与托管层"的工程形态。
