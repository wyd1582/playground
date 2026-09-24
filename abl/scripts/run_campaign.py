"""make campaign — DESIGN.md P6: arms A–F on the simulation (true BVs known) and on the public pig data."""
from __future__ import annotations

import argparse
import json
import shutil
import sys

from campaigns.final_table import final_table
from campaigns.runner import Campaign
from campaigns.scorecard import write_scorecard
from common import paths
from common.mdtable import md_table
from registry import Registry
from scripts._common import pig_bundle, sim_bundle
from scripts.sim_controls import write_sim_controls_report


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
        print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("rows", "evaluated")} for k, v in res["arms"].items()}, indent=1, default=str))
        if ds == "sim" and all(x in a.arms for x in "ABEF"):
            print(write_sim_controls_report(res))
        if ds == "sim" and "D" in a.arms:
            ft = final_table(reg, "sim", b.frame, b.priors, b.trait, camp.champion, [camp._campaign_id("D")])
            (paths.reports_dir() / "final_holdout_sim.md").write_text(
                "# Final sealed-holdout table (sim)\n\nOpened once, after the campaign, by campaigns/final_table.py (event flag holdout_final_read). "
                "Test set = the sealed generation; training = everything the campaign was allowed to see.\n\n" + md_table(ft) + "\n")
            print("\nFinal sealed-holdout table (sim):\n", ft.to_string(index=False))
        if ds == "pig" and "D" in a.arms:
            evaluated = res["arms"]["D_abl_loop"].get("evaluated", [])
            if evaluated:
                best = max(evaluated, key=lambda r: (r["state"] == "promoted", r["delta_oos"] if r["delta_oos"] is not None else -9))
                src = paths.registry_dir() / "packages" / f"{best['candidate_id']}.md"
                if src.exists():
                    shutil.copy(src, paths.reports_dir() / "BreedingPackage_pig_cleveland.md")
                    print(f"BreedingPackage → reports/BreedingPackage_pig_cleveland.md ({best['candidate_id']}, {best['state']})")
    df, text = write_scorecard(reg)
    print("\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
