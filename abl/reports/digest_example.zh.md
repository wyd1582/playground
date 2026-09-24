# ABL 每日摘要 — 2026-09-24

_时间窗：最近 24 小时（2026-09-23T16:14:33Z → 2026-09-24T16:14:33Z）。所有数字来自台账（SQL，只读）；叙述要点：stub。_

## 学到了什么

- 最近 24 小时，循环产生了 196 个提案；评审者通过 242 个、退回 15 个、拒绝 32 个；61 个候选完成全量评估，0 个晋级。
- 探索最多的机制簇：'shrinkage'，25 个提案（占非对照提案的 15%），0 个晋级、16 个被拒绝。
- 目前最佳配对 ΔOOS 为 0.0144（CI 下限 0.0051），来自机制簇 'random_ops' 的 k_2b2d78c450。
- 限制最大的门是 research：最近 24 小时 183 次检查中有 111 次未通过。
- 框架可靠性：20 次负对照评审中评审者拒绝了 20 次，0 个负对照被错误晋级。

## 拒绝了什么、为什么

- 评审者因 temporal 泄漏退回或拒绝了 32 个候选 — 例如 k_0078ac50d6: The mechanism as stated requires phenotypes recorded after selection_date。
- 评审者因 plan 泄漏退回或拒绝了 9 个候选 — 例如 k_1eb2c42d06: Plan feasibility: too few markers for reliable coancestry。
- research 门未通过 111 次；例如 k_865ea1be07 的 z_deflated_threshold = -1.598，门槛为 1.1926。

## 报警

- **红色 `retry_limit`** — 5 个事件被标记为 retry_limit；最近一次：orchestrator/retry_limit（k_1eb2c42d06），时间 2026-09-24T12:07:14Z

## 成本

| 指标 | 最近 24 小时 | 台账累计 |
|---|---:|---:|
| Token | 954,359 | 954,359 |
| 费用（USD） | $0.0000 | $0.0000 |
| Agent 调用次数 | 874 | 874 |
| 全量评估（去重候选数） | 61 | 61 |
| 评估计算时间（秒） | 123.0 | 123.0 |

Token 去向（最近 24 小时）：geneticist 516,674 tokens / 242 次调用；critic 257,979 tokens / 289 次调用；builder 126,190 tokens / 141 次调用；analyst 53,516 tokens / 26 次调用；final_table 0 tokens / 1 次调用；orchestrator 0 tokens / 175 次调用

## 下一个实验（分析师）

```json
{
  "dsl": "champion() + snp_subset(strategy='prior_list', fraction=0.3, source='<prior>')",
  "mechanism": "Restricting the relationship to prior regions tests whether the prior alone carries the signal (a stricter version of prior weighting).",
  "rationale": "cluster 'prior_subset' is absent from the registry: highest expected information gain"
}
```

_来源：分析师于 2026-09-24T12:10:27Z 针对 k_c07af49992 的调用（`registry/prompts/6e7c71198308c66e167e21ace50873af0648ac97802c1f60eed1491f95f1fb59.out.txt`）。_
