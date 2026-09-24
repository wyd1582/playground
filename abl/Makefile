# ABL — every target runs from this directory with the project venv.
PY ?= .venv/bin/python
export PYTHONPATH := .

.PHONY: help test views seal-holdout sim-controls pig-public campaign scorecard watch status digest clean-runtime

help:
	@echo "make test          run the full test suite (pytest -q)"
	@echo "make views         (re)create registry views and print them (DuckDB)"
	@echo "make sim-controls  simulated campaign with known true BVs: champion / random ops / shuffled labels"
	@echo "make pig-public    frozen champion on the Cleveland 2012 public pig data -> one BreedingPackage"
	@echo "make campaign      full arms A-F campaign (DESIGN.md P6) on sim + pig"
	@echo "make scorecard     system scorecard from the registry (DESIGN.md 3.4)"
	@echo "make watch         Guardian & Learning dashboard (separate read-only process)"
	@echo "make status        one-screen text summary of the last 24h"
	@echo "make digest        write registry/digest_YYYY-MM-DD.md"

test:
	$(PY) -m pytest -q

views:
	$(PY) scripts/make_views.py

seal-holdout:
	$(PY) scripts/seal_holdout.py

sim-controls:
	$(PY) scripts/sim_controls.py

pig-public:
	$(PY) scripts/pig_public.py

campaign:
	$(PY) scripts/run_campaign.py

scorecard:
	$(PY) scripts/scorecard.py

watch:
	.venv/bin/streamlit run dashboard/app.py --server.headless true

status:
	$(PY) -m dashboard.status

digest:
	$(PY) -m dashboard.digest

clean-runtime:
	rm -f registry/*.sqlite registry/events.jsonl registry/alarms.log registry/holdout_seal.json registry/digest_*.md
	rm -rf registry/prompts data/snapshots/* dashboard/state.json
	chmod -R u+w holdout 2>/dev/null || true; find holdout -mindepth 1 ! -name README.md -delete
