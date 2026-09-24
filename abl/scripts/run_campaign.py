"""make campaign — DESIGN.md P6: arms A–F on the simulation (true BVs known) and on the public pig data."""
from __future__ import annotations

import argparse
import json
import sys

from campaigns.final_table import final_table
from campaigns.runner import Campaign
from campaigns.scorecard import write_scorecard
from registry import Registry
from scripts._common import pig_bundle, sim_bundle


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="sim,pig", help="comma list of sim,pig")
    ap.add_argument("--proposals", type=int, default=100)
    ap.add_argument("--full-evals", type=int, default=12)
    ap.add_argument("--arms", default="ABCDEF")
    ap.add_argument("--pig-max-markers", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    reg = Registry()
    for ds in a.datasets.split(","):
        b = sim_bundle() if ds == "sim" else pig_bundle(a.pig_max_markers)
        camp = Campaign(b, registry=reg, seed=a.seed, n_proposals=a.proposals, budget_full_evals=a.full_evals)
        res = camp.run_all(a.arms)
        print(json.dumps({k: v for k, v in res["arms"].items()}, indent=1, default=str)[:4000])
        if ds == "sim" and "D" in a.arms:
            ft = final_table(reg, "sim", b.frame, b.priors, b.trait, camp.champion, [camp._campaign_id("D")])
            print("\nFinal sealed-holdout table (sim):\n", ft.to_string(index=False))
    df, text = write_scorecard(reg)
    print("\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
