"""make demo — build a small, self-contained demo ledger for a public deployment.

Seals the simulated holdout, runs arms A–F on the simulation with small budgets, opens the
sealed holdout once for the final table, and writes a digest. Runs in a few minutes on a
laptop or inside `docker build`, so the deployed dashboard starts with data already in it.
The public pig data is left out by default (its genotype matrix needs ~2 GB of RAM to load);
set DEMO_PIG=1 to include it with 5,000 subsampled markers.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from campaigns.final_table import final_table
from campaigns.runner import Campaign
from campaigns.scorecard import write_scorecard
from registry import Registry
from scripts._common import pig_bundle, sim_bundle


def main() -> int:
    t0 = time.time()
    subprocess.check_call([sys.executable, "scripts/seal_holdout.py"])
    reg = Registry()
    b = sim_bundle()
    camp = Campaign(b, registry=reg, seed=0, n_proposals=int(os.environ.get("DEMO_PROPOSALS", 30)),
                    budget_full_evals=int(os.environ.get("DEMO_FULL_EVALS", 5)))
    camp.run_all("ABCDEF")
    final_table(reg, "sim", b.frame, b.priors, b.trait, camp.champion, [camp._campaign_id("D")])
    if os.environ.get("DEMO_PIG") == "1":
        pc = Campaign(pig_bundle(max_markers=5000), registry=reg, seed=0, n_proposals=20, budget_full_evals=3)
        pc.run_all("ADF")
    write_scorecard(reg, name="scorecard_demo")
    subprocess.call([sys.executable, "-m", "dashboard.digest"])
    print(f"demo ledger ready in {time.time() - t0:.0f}s → registry/abl.sqlite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
