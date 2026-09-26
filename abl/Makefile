# ABL — every target runs from this directory with the project venv.
PY ?= .venv/bin/python
export PYTHONPATH := .

.PHONY: help test views seal-holdout sim-controls pig-public campaign scorecard watch status digest clean-runtime demo site docker docker-run

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
	@echo "make demo          small self-contained demo ledger (what the deployed dashboard shows)"
	@echo "make site          build the static landing site for Vercel into site/dist/"
	@echo "make docker        build the deployment image locally; make docker-run to open it on :8501"

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
	.venv/bin/streamlit run dashboard/app.py --server.headless true --server.port $${PORT:-8501}

status:
	$(PY) -m dashboard.status

digest:
	$(PY) -m dashboard.digest

clean-runtime:
	rm -f registry/*.sqlite registry/*.sqlite-* registry/status_*.json registry/events.jsonl registry/alarms.log registry/holdout_seal.json registry/digest_*.md
	rm -rf registry/prompts registry/packages data/snapshots/* dashboard/state.json
	chmod -R u+w holdout 2>/dev/null || true; find holdout -mindepth 1 ! -name README.md -delete

demo:
	$(PY) scripts/build_demo.py

site:
	python3 scripts/build_site.py

docker:
	docker build -t abl .

docker-run:
	docker run --rm -p 8501:8501 -e ABL_DASHBOARD_PASSWORD=$${ABL_DASHBOARD_PASSWORD:-demo} abl
