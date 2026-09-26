# ABL — Agentic Breeding-value Loop

**The harness is the product, not the model.** ABL is a research harness for genomic selection in
which LLM agents *propose* ways to improve cross-sectional breeding-value rankings and a
deterministic core *decides* what survives. Nothing an agent says can change a candidate's state;
only machine-checkable gates can. The sales pitch is not "our AI beats BLUP" but "we built a judge
that any method must pass, and it has already rejected N good-looking false positives".

Built from `docs/DESIGN.md` (v0.1: contract, roles, gates, prompts) and `docs/OPS.md` (v0.2:
registry schema, dashboard, data sources). Both documents are the specification; this README is
the one-page argument and the operator's map.

## Why the harness, not the model

1. **A breeding value is an alpha signal.** One score per animal per selection date, ranked
   cross-sectionally, judged by what happens one generation later. Every trick from quantitative
   finance's "agents explore, harness decides" loop transfers, and so does every leak.
2. **Models come and go; the judge stays.** GBLUP/ssGBLUP is the frozen champion. Any LLM- or
   deep-learning-derived challenger only earns promotion through a *paired* ΔOOS against that
   champion on the same forward-in-time splits, same seeds, same labels — never on an absolute
   accuracy number.
3. **Leakage is the normal case, not the exception.** In breeding, the ways to cheat are temporal
   (a phenotype recorded after the selection date), relatedness (a test animal's parents or
   full-sibs in training) and structural (line/farm/year masquerading as genotype). ABL encodes all
   three as machine checks (`genoframe/splitter.py`, `gates/validity.py`) and as the Critic's brief.
4. **Negative controls are permanent residents.** Shuffled labels (within contemporary group) and
   random SNP subsets run in every campaign. A harness that promotes them is broken; a harness that
   rejects them earns the right to be believed when it promotes something real.
5. **The ledger is the asset.** Every proposal, review, gate result, cost and disposition is
   appended to the registry (`registry/schema.sql`, OPS.md A.2). On customer data the same tables
   become the decision→outcome record — the layer-5 data that public datasets can never supply.
6. **Honest statistics over pretty ones.** The LR-method ρ (Legarra & Reverter 2018) is reported
   but *is not null-calibrated*: on shuffled labels it stays high because partial and whole
   predictions share the same shrinkage noise. ABL therefore calibrates the accuracy gate against
   the campaign's own shuffled-label null and uses a within-contemporary-group predictive
   correlation for the incremental gate (see `reports/sim_controls.md`). Dispersion (b) and the
   plan's ΔF are judged *relative to the frozen champion* on the same selection — a gate the
   champion itself fails cannot rank challengers — while the absolute rules stay logged as
   diagnostics (`gates/thresholds.yaml`).
7. **A candidate is (DSL, data).** The semantic-hash dedup that blocks a second full evaluation
   is scoped to the data snapshot, so the same expression on the shuffled-label control or on
   another species is a new trial, and every run appends new campaigns to the ledger.

## What was built

| layer | directory | role |
|---|---|---|
| data contract | `genoframe/` | `GenoFrame` (key = animal_id × selection_date, `available_at` on every label), point-in-time snapshots, forward-in-time splitter with parent/full-sib purge, holdout sealing |
| restricted DSL | `dsl/` | `champion() + op(...)` grammar (`dsl/grammar.md`), AST validator with unit and causality checks, order-independent semantic hash, compiler, random search |
| deterministic core | `engine/` | weighted/dominance GRM, pedigree A, GBLUP with eigen-trick REML (frozen λ), plan simulator (ΔF, gain/yr, selection intensity), evaluator |
| gates | `gates/` | 0 validity · 1 accuracy (LR) · 2 incremental (paired bootstrap ΔOOS) · 3 plan · 4 robustness (group share + drop-top-family refit) · 5 research (expected-max deflation). `GateRunner` is the only writer of candidate state; `gates/thresholds.yaml` is hashed into every campaign |
| registry | `registry/` | SQLite ledger (OPS.md A.2 tables, append-only, `owner`/`sharing_tier` on every row), A.3 views, `events.jsonl` (OPS.md D.2) |
| agents | `agents/` | Orchestrator state machine (dedup, budget, retry limit, information-gain reserve, RUN/PAUSE), Geneticist/Builder/Critic/Analyst with prompts P1–P5 verbatim, structured JSON schemas, information firewall, deterministic offline stubs |
| campaigns | `campaigns/` | arms A–F of DESIGN.md P6, negative controls, BreedingPackage writer, system scorecard, the single sanctioned holdout read |
| simulation | `sim/` | pure-Python forward-in-time simulator with LD, hidden QTL, selection, lines, farms, years, dominance and known true BVs (AlphaSimR fallback) |
| public data | `dataio/` | OPS.md C.1 catalogue; loaders for the vendored Cleveland 2012 pig data and BGLR wheat (pseudo-generations from genomic family blocks, declared as such) |
| dashboard | `dashboard/` | Guardian & Learning dashboard (Streamlit), a separate read-only process; `make status`, `make digest`, alarms |

## Deploy

`docs/DEPLOY.zh.md` (step by step, Chinese) · `docs/DEPLOY.md` (summary). Dashboard on Render via
`render.yaml` + `Dockerfile` (demo mode, password-gated); landing site and manuals on Vercel via
`vercel.json` + `scripts/build_site.py`; CI in `.github/workflows/ci.yml` (Python 3.9 and 3.11).

## Run it

Operator's manual: `docs/USER_MANUAL.md` (English) · `docs/USER_MANUAL.zh.md`（中文）. The dashboard,
`make status` and `make digest` speak Chinese by default; switch with the sidebar or `ABL_LANG=en`.


```bash
cd abl
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
make test            # pytest -q (unit + end-to-end on a small simulation)
make seal-holdout    # simulate, seal the last generation read-only under holdout/
make sim-controls    # champion vs random ops vs shuffled labels vs random SNP, true BVs known
make pig-public      # frozen champion + short loop on the Cleveland 2012 pig data → one BreedingPackage
make campaign        # DESIGN.md P6: arms A–F on sim and pig, 100 proposals, ≤12 full evaluations
make scorecard       # DESIGN.md §3.4 system scorecard from the registry
make views           # OPS.md A.3 analysis views
make watch           # dashboard (separate process); make status / make digest for text
```

Without Anthropic credentials the agents run on deterministic stubs (`common/llm.py`), so every
target above works offline; with `ANTHROPIC_API_KEY` (or `ant auth login`) the real prompts run on
`claude-opus-5` with JSON-schema outputs. Set `ABL_LLM=stub|anthropic` to force either.

## Non-negotiables (enforced by tests)

- `holdout/` is never read by agent code: filesystem read-only + path guard + prompt scanner +
  a test that greps every prompt an agent ever saw for holdout digests and animal ids.
- Only `gates/` changes candidate state (`registry.Registry.transition` checks its caller).
- Every agent call appends one line to `registry/events.jsonl`.
- Seeds everywhere; a candidate must replay bit-for-bit before it is evaluated.
- `control/RUN` must exist and `control/PAUSE` must not, checked before every loop step.

## Results

See `reports/` — `sim_controls.md`, `scorecard.md`, `BreedingPackage_pig_cleveland.md`,
`final_holdout_sim.md`, `digest_example.md`, `status_example.txt` and the per-dataset `campaign_*.json`.
The section below is rendered from those files by `scripts/readme_results.py`.

### Results of the first full run (`make campaign`, deterministic stub agents, seed 0)

**Simulation** (775–1779 training animals per split, 3 forward-in-time splits, generation 5 sealed). Champion frozen at h2 = 0.247.

| arm | what it measures | result |
|---|---|---|
| A champion | true accuracy cor(GEBV, TBV) on the next generation | **0.508** (LR ρ 0.770, dispersion b 1.12, predictive r 0.242) |
| E shuffled labels | champion on labels shuffled within generation | true accuracy +0.018; LR ρ still 0.53 ± 0.04 (not null-calibrated); predictive r -0.012 ± 0.015 |
| E shuffled labels (loop) | false promotions by the full ABL loop on shuffled data | **0** of 4 full evaluations |
| F random SNP subset | false promotions of 30 % random panels | **0** of 5 |
| B random operators | promotions / full evaluations, best ΔOOS | 0 / 12, best ΔOOS +0.0144 (best CI low +0.0051) |
| C one-shot LLM | one proposal, no loop | 0 promoted of 0 evaluated |
| D ABL loop | 100 hypotheses → 80 candidate rows (retries supersede) → 9 full evaluations | **0 promoted**, best ΔOOS +0.0066 (CI low +0.0030); Critic rejected 14, duplicates skipped 29, NEED_OPERATOR 2, validity rejects 1 |

Full evaluations in the ABL loop (sim):

| dsl_text | mechanism_cluster | state | delta_oos | delta_oos_ci_low |
|---|---|---|---|---|
| champion() + dominance(w=0.15) + qtl_prior(source='random_prior', weight=2.0) | prior_weighting | rejected | -0.01847 | -0.03122 |
| champion() + snp_subset(fraction=0.3, source='random_prior', strategy='prior_list') | prior_subset | rejected | -0.103 | -0.1361 |
| champion() + lambda_scale(factor=2.0) | shrinkage | rejected | -0.0015 | -0.007963 |
| champion() + dominance(w=0.2) | dominance | rejected | -0.0008926 | -0.01039 |
| champion() + blend_pedigree(w=0.3) | pedigree_blend | rejected | 0.003187 | -0.001664 |
| champion() + covariate(field='sex') | fixed_effects | rejected | 0.001285 | 1.721e-05 |
| champion() + snp_subset(fraction=0.5, strategy='top_maf') | panel_reduction | rejected | -0.007773 | -0.01693 |
| champion() + region_weight(chrom=1, weight=3.0) | region_weighting | rejected | -0.01354 | -0.02638 |
| champion() + grm_weights(power=-0.5, scheme='maf_power') | maf_weighting | rejected | 0.0066 | 0.003047 |

**Sealed holdout (sim), opened once after the campaign:**

| model | dsl | holdout_n | true_accuracy | predictive_r | lr_rho | delta_predictive_r_vs_champion |
|---|---|---|---|---|---|---|
| champion | champion() | 500 | 0.647 | 0.3247 | 0.8778 | 0 |

**Cleveland 2012 public pig data** (835–2479 training animals per split over 3 genomic family blocks, trait t1, no pedigree/map/dates). Champion frozen at h2 = 0.024.

- A champion: predictive r -0.003, LR ρ 0.450, dispersion b 0.86; shuffled-label null predictive r -0.005 ± 0.037.
- D ABL loop: 100 proposals, 9 full evaluations, **0 promoted**; best ΔOOS +0.0095 (CI low +0.0000).
- E shuffled labels: 0 false promotions; F random SNP: 0 false promotions; B random operators: 0 promoted of 12.
- Reading: on this weak trait the frozen champion itself has no forward predictive ability across family blocks (REML h2 ≈ 0.02), which matches the leave-family-out result of the earlier ladder experiment in `../genomic-selection-pig/`; the honest outcome is that nothing is promoted, and the harness says so.

**System scorecard** (`reports/scorecard.md`, DESIGN.md §3.4):

| dataset | arm | proposals | valid_per_100_proposals | full_evaluations | promoted | best_delta_oos | best_delta_oos_ci_low | false_promotions_on_negative_controls | critic_reject_rate_on_leak_probes | mechanism_clusters | reproducible_from_hash | tokens | compute_seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sim | A | 0 | 0 | 0 | 0 |  |  | 0 |  | 0 |  | 0 | 0 |
| sim | B | 12 | 100 | 12 | 0 | 0.0144 | 0.0051 | 0 |  | 1 | 1 | 0 | 20.7 |
| sim | C | 0 | 0 | 0 | 0 |  |  | 0 |  | 0 |  | 1330 | 0 |
| sim | D | 71 | 71.8 | 9 | 0 | 0.0066 | 0.003 | 0 | 1 | 12 | 1 | 454634 | 32 |
| sim | E | 20 | 80 | 4 | 0 | -0.0001 | -0.0005 | 0 |  | 11 | 1 | 84161 | 12.5 |
| sim | F | 5 | 100 | 5 | 0 | -0.0405 | -0.0663 | 0 |  | 1 | 1 | 0 | 8.3 |
| pig_cleveland | A | 0 | 0 | 0 | 0 |  |  | 0 |  | 0 |  | 0 | 0 |
| pig_cleveland | B | 12 | 100 | 12 | 0 | 0.01 | -0.0001 | 0 |  | 1 | 1 | 0 | 28.2 |
| pig_cleveland | C | 1 | 100 | 1 | 0 | -0 | -0.0016 | 0 |  | 1 | 1 | 1454 | 2 |
| pig_cleveland | D | 50 | 56 | 9 | 0 | 0.0095 | 0 | 0 | 1 | 11 | 1 | 332367 | 40.4 |
| pig_cleveland | E | 20 | 80 | 4 | 0 | 0.0055 | 0.0002 | 0 |  | 8 | 1 | 80413 | 20.1 |
| pig_cleveland | F | 5 | 100 | 5 | 0 | 0.0141 | 0.0064 | 0 |  | 1 | 1 | 0 | 11.3 |

**What the harness rejected and why.** Every full evaluation above that ended `rejected` failed at least one mandatory gate; the limiting gate and the Analyst's diagnosis are in `registry/packages/<candidate_id>.md` and the best pig package is copied to `reports/BreedingPackage_pig_cleveland.md`. The leak probes (negative_control_leak) were rejected by the Critic before any code was written.

_Agents in this run were the deterministic stubs (no API credentials in the build environment); rerun `make campaign` with `ANTHROPIC_API_KEY` set to use `claude-opus-5` with the same prompts, gates and ledger._

