# ABL User Manual (English)

Agentic Breeding-value Loop: a genomic-selection research harness in which agents *propose*
hypotheses and a deterministic core *decides* what survives. This manual is for the people who
operate it (breeding manager, data scientist, founder) and answers: how to install, run, read,
change, and recover. Design rationale: `docs/DESIGN.md`; data model and dashboard spec:
`docs/OPS.md`. 中文版：`docs/USER_MANUAL.zh.md`.

---

## 1. Ten-minute start

```bash
git clone -b claude/affectionate-franklin-ttwudk https://github.com/wyd1582/playground
cd playground/abl
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
make test            # 63 tests, ~6–8 min (includes a small end-to-end campaign)
make seal-holdout    # simulate, seal the last generation under holdout/ (read-only)
make campaign        # DESIGN.md P6: six arms on simulation + public pig data, ~15–20 min
make watch           # dashboard at http://localhost:8501
```

Requirements: Python ≥ 3.9 (3.10+ preferred), 4 cores / 8 GB is plenty; no R, no network
(the public datasets ship with the repository). Without an Anthropic API key the agents run on
the built-in deterministic StubLLM and the whole pipeline still runs; with a key they switch
to `claude-opus-5` automatically.

## 2. Core vocabulary (the minimum needed to read the dashboard and reports)

| term | meaning |
|---|---|
| champion | frozen ssGBLUP (uniform marker weights, λ from REML at campaign start); never changes within a campaign |
| challenger / candidate | one DSL expression `champion() + operator(...)`, at most 4 operators |
| proposal | one Geneticist hypothesis (mechanism, direction, falsifiers, expected gain); yields 0..n candidates |
| gate | six deterministic checks: 0 validity, 1 accuracy (LR method), 2 incremental (paired ΔOOS), 3 plan (ΔF, gain/yr), 4 robustness, 5 research (multiple testing) |
| promoted | all mandatory gates passed. **No agent can promote a candidate; only `gates/` can.** |
| ΔOOS | paired gain in predictive correlation over the champion (same splits, seeds, labels), with a 90 % bootstrap interval |
| negative controls | E: the whole inner loop on labels shuffled within generation; F: random 30 % SNP subsets. If either is promoted the harness is broken |
| holdout | the last generation; read-only after `make seal-holdout`; never read by agent code; opened once after the campaign by `final_table.py` |
| registry | `registry/abl.sqlite`: every proposal, review, gate result, cost and state transition, append-only |
| BreedingPackage | the full deliverable for one candidate: thesis → DSL → data declaration → tests → provenance → all gate values, at `registry/packages/<candidate_id>.md` |

## 3. Commands

| command | what it does | output |
|---|---|---|
| `make test` | full test suite | terminal |
| `make seal-holdout` | simulate 6 generations × 500 animals, seal generation 5 | `holdout/sim/` (read-only), `data/snapshots/sim_dev.pkl` |
| `make sim-controls` | champion / random operators / shuffled labels / random SNP, true BVs known | `reports/sim_controls.md`, `reports/scorecard.md` |
| `make pig-public` | champion + short loop on the Cleveland pig data | `reports/BreedingPackage_pig_cleveland.md` |
| `make campaign` | the P6 experiment: arms A–F on sim + pig | `reports/campaign_*.json`, `final_holdout_sim.md`, scorecard, pig BreedingPackage |
| `make scorecard` | recompute the system scorecard from the registry | `reports/scorecard.md/.json` |
| `make views` | rebuild and print the nine OPS.md A.3 views | terminal (DuckDB) |
| `make watch` | Guardian & Learning dashboard (separate read-only process) | browser |
| `make status` | one-screen text summary of the last 24 h | terminal |
| `make digest` | daily digest | `registry/digest_YYYY-MM-DD.md` |
| `make clean-runtime` | delete ledger, event stream, snapshots, sealed data (**irreversible**) | — |

`make campaign` options (call the script directly):
```bash
.venv/bin/python scripts/run_campaign.py --datasets sim,pig --proposals 100 --full-evals 12 --arms ABCDEF --seed 0
.venv/bin/python scripts/run_campaign.py --datasets sim --arms AD --proposals 30 --full-evals 4    # quick trial
.venv/bin/python scripts/run_campaign.py --datasets pig --pig-max-markers 10000                   # subsample pig markers
```
Every run appends new campaigns (time-stamped ids) to the ledger; nothing is overwritten.

## 4. Environment variables and switches

| variable / file | effect | default |
|---|---|---|
| `ANTHROPIC_API_KEY` | agents use `claude-opus-5` (JSON-schema outputs, server-side refusal fallbacks) | unset → StubLLM |
| `ABL_LLM=anthropic\|stub` | force a backend | auto |
| `ABL_LLM_FALLBACKS=0` | disable server-side fallbacks | on |
| `ABL_LANG=zh\|en` | language of the dashboard, `make status`, `make digest` (the dashboard sidebar can switch too) | `zh` |
| `ABL_ROOT` | point the whole system at another tree (tests) | project dir |
| `control/RUN` | must exist for the loop to run | tracked in git |
| `control/PAUSE` | if present the Orchestrator stops before its next step and writes `registry/status_<campaign>.json` | created by the dashboard PAUSE button |
| `gates/thresholds.yaml` | gate thresholds. **Changing it requires a new commit**; its hash is recorded at campaign start and the dashboard alarms if it changes mid-campaign | — |

## 5. Reading the dashboard (`make watch`)

Left, "Learning":
- **Narrative feed**: one plain-language line per event. The toggle "only Critic returns, gate failures, promotions and policy flags" filters noise; expand a row for the raw JSON.
- **Mechanism map**: agents repeatedly proposing the same cluster means the corpus or the priors are skewed; change the retrieval source (OPS.md D.4).
- **Funnel**: proposals → reviewed → implemented → validated → fully evaluated → promoted, today vs campaign-to-date.
- **Explain this candidate**: pick a candidate id to see its BreedingPackage tabs and every gate value / threshold / result. Candidates with a package are listed first.

Right, "Guardian":
- **Policy alarms** (any red one needs a look): `holdout_touch` (sealed data appeared in an agent input), `threshold_changed`, `retry_limit`, `budget_exceeded` (a genuine overrun, not a budget used up as planned), `cluster_concentration` (one cluster > 40 %), `suspicious_pass_rate` (> 3× baseline), `events_stalled` (no event for 15 min).
- **Budget**: tokens and full evaluations used / cap, burn rate, projected exhaustion.
- **PAUSE / RESUME**: create / delete `control/PAUSE`. No network, no signals; the dumbest and most robust switch.
- **Agent reliability**: Critic rejection rate on leak probes (should be 100 %), false promotions (should be 0).

Daily routine: `make status` in the morning; keep the dashboard open and look only when something is red; `make digest` in the evening (two minutes); `make scorecard` weekly into your technical note.

## 6. Reading the reports

- `reports/sim_controls.md`: the harness's credibility in one table. Three numbers matter: champion true accuracy (clearly > 0), true accuracy on shuffled labels (≈ 0), false promotions on negative controls (must be 0). Note that the LR ρ stays high on shuffled labels; that is a property of the LR method, which is why gate 1 is calibrated on the empirical null and gate 2 uses the within-group predictive correlation.
- `reports/scorecard.md`: the DESIGN.md §3.4 system scorecard, one row per campaign. `false_promotions_on_negative_controls` and `critic_reject_rate_on_leak_probes` are trust metrics; `full_evals_per_promotion` and `compute_seconds` are cost metrics.
- `reports/final_holdout_sim.md`: the sealed-generation table, opened exactly once after the campaign; the event stream carries one `holdout_final_read` line.
- `reports/BreedingPackage_*.md`: the deliverable a breeding manager reads. Section 6 has one row per gate; the FAIL rows are "why it was not promoted".
- `registry/digest_YYYY-MM-DD.md`: numbers from SQL, narrative sentences from the LLM (or stub); the LLM cannot change a number.

## 7. Writing your own candidate / extending the grammar

Grammar: `dsl/grammar.md`. Evaluate one expression by hand:
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
Adding an operator: (1) register arguments, units and touched fields in `OPERATORS` in `dsl/ast.py`; (2) compile it into `ModelSpec` in `dsl/compiler.py`; (3) implement it in `engine/evaluate.py`; (4) document it in `dsl/grammar.md`; (5) add cases to `tests/test_dsl.py`. `multi_trait` and `env_covariate` are reserved today; the Builder returns NEED_OPERATOR for them.

Adding a dataset: write a function returning a `GenoFrame` like `dataio/loaders.py::load_pig_cleveland`; `validate()` enforces the contract (no silent forward fill, `available_at` on every label, legal pedigree). Without a real time axis use `pseudo_generations` for family blocks and say so in `meta["calendar_source"]`.

## 8. Customer data (shadow run)

1. Load the customer data as a `GenoFrame` with `genotype_source` in `solid/liquid/seq` and `owner="customer"`.
2. Replace the `make seal-holdout` logic with "seal the most recent selection cycle".
3. Run one campaign, record only, never intervene; `campaigns/` writes `recommendations`, the customer fills `decisions` and `outcomes`.
4. Ownership in three sentences (OPS.md A.4): raw `recommendations/decisions/outcomes` rows belong to the customer; aggregated statistics belong to NewCo; `proposals/candidates/gate_results` belong to NewCo. The three columns `owner`, `sharing_tier`, `deidentified` exist on every row.

## 9. Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `make test` fails with `unsupported operand type(s) for \|` | Python < 3.10 on an old checkout | `git pull` (fixed) or upgrade to 3.10+ |
| `make watch` shows an empty page | no ledger yet | run `make campaign` or `make sim-controls` first |
| red `retry_limit` alarm | the Builder could not fix what the Critic returned (common with the stub) | expected; with a real LLM inspect that candidate's `critic_reviews` if frequent |
| red `threshold_changed` alarm | `gates/thresholds.yaml` edited mid-campaign | that campaign is void; rerun |
| `git pull` very slow | one 33 MB data file in history and git's protocol is sensitive to flaky networks | `git clone --depth 1`, or give git a proxy |
| red `holdout_touch` alarm | a sealed digest or path appeared in an agent input | PAUSE immediately; inspect `registry/prompts/<input_hash>.in.txt` |
| start over | — | `make clean-runtime` (irreversible), then `make seal-holdout` |

## 10. The five non-negotiables (CLAUDE.md)

1. Nothing under `holdout/` is ever read by agent code; tests grep for it.
2. Only `gates/` may change a candidate's state; agents return recommendations only.
3. Every agent call appends one line to `registry/events.jsonl`.
4. Deterministic seeds everywhere; threshold edits need a new commit and a registry entry.
5. Check `control/RUN` before each step; if `control/PAUSE` exists, stop and write status.
