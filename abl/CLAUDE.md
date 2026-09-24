# ABL — Agentic Breeding-value Loop
Read docs/DESIGN.md (contract, roles, gates, prompts) and docs/OPS.md (registry schema,
dashboard, data sources) before any change. Non-negotiables:
1. Nothing under holdout/ is ever read by agent code; tests grep for it.
2. Only gates/ may change a candidate's state; agents return recommendations only.
3. Every agent call appends one line to registry/events.jsonl (schema in OPS.md A.2 / D.2).
4. Deterministic seeds everywhere; no threshold edits without a new commit + entry in registry.
5. Before each loop step, check control/RUN exists; if control/PAUSE exists, stop and write status.
Work in small commits. Run `pytest -q` before reporting done.

Layout follows DESIGN.md §P0: genoframe/ dsl/ engine/ gates/ registry/ agents/ campaigns/
holdout/ sim/, plus dataio/ (public-data loaders), dashboard/ (separate read-only process),
common/ (paths, hashing, seeds — importable by everyone including the dashboard).
Run everything from this directory with the project venv: `make test`, `make sim-controls`,
`make pig-public`, `make campaign`, `make scorecard`, `make watch`, `make status`, `make digest`.
