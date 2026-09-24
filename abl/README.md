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
   correlation for the incremental gate (see `reports/sim_controls.md`).

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

## Run it

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
`final_holdout_sim.json` and the per-dataset `campaign_*.json`. The section below is refreshed
from those files.

_Results section pending: the first full run (`make sim-controls`, `make pig-public`, `make campaign`) is in progress; numbers land here with the reports._
