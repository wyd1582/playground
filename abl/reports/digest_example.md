# ABL daily digest — 2026-09-24

_Window: last 24 h (2026-09-23T16:16:47Z → 2026-09-24T16:16:47Z). Numbers come from the registry (SQL, read-only); narrative bullets: stub._

## What was learned

- In the last 24h the loop produced 196 proposals; the Critic passed 242, returned 15 and rejected 32; 61 candidates got a full evaluation and 0 were promoted.
- Most explored mechanism cluster: 'shrinkage' with 25 proposals (15% of non-control proposals), 0 promoted and 16 rejected.
- Best paired ΔOOS so far is 0.0144 (CI low 0.0051) for k_2b2d78c450 in cluster 'random_ops'.
- The most limiting gate was research: 111 of 183 checks failed in the last 24h.
- Harness reliability: the Critic rejected 20 of 20 negative-control reviews, and 0 negative control(s) were falsely promoted.

## What was rejected and why

- The Critic returned or rejected 32 candidate(s) for temporal leakage — e.g. k_0078ac50d6: The mechanism as stated requires phenotypes recorded after selection_date.
- The Critic returned or rejected 9 candidate(s) for plan leakage — e.g. k_1eb2c42d06: Plan feasibility: too few markers for reliable coancestry.
- Gate research failed 111 time(s); e.g. k_865ea1be07 had z_deflated_threshold = -1.598 against threshold 1.1926.

## Alarms

- **RED `retry_limit`** — 5 event(s) flagged retry_limit; latest orchestrator/retry_limit on k_1eb2c42d06 at 2026-09-24T12:07:14Z

## Cost

| Metric | Last 24 h | Ledger to date |
|---|---:|---:|
| Tokens | 954,359 | 954,359 |
| Cost (USD) | $0.0000 | $0.0000 |
| Agent calls | 874 | 874 |
| Full evaluations (distinct candidates) | 61 | 61 |
| Evaluation compute (s) | 123.0 | 123.0 |

Where the tokens went (last 24 h): geneticist 516,674 tokens / 242 calls; critic 257,979 tokens / 289 calls; builder 126,190 tokens / 141 calls; analyst 53,516 tokens / 26 calls; final_table 0 tokens / 1 call; orchestrator 0 tokens / 175 calls

## Next experiment (Analyst)

```json
{
  "dsl": "champion() + snp_subset(strategy='prior_list', fraction=0.3, source='<prior>')",
  "mechanism": "Restricting the relationship to prior regions tests whether the prior alone carries the signal (a stricter version of prior weighting).",
  "rationale": "cluster 'prior_subset' is absent from the registry: highest expected information gain"
}
```

_Source: Analyst call at 2026-09-24T12:10:27Z on k_c07af49992 (`registry/prompts/6e7c71198308c66e167e21ace50873af0648ac97802c1f60eed1491f95f1fb59.out.txt`)._
