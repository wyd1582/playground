"""make pig-public — frozen champion on the Cleveland 2012 public pig data; one BreedingPackage
(DESIGN.md P0 deliverable 2) from a short ABL loop."""
from __future__ import annotations

import argparse
import shutil
import sys

from campaigns.runner import Campaign
from campaigns.scorecard import write_scorecard
from common import paths
from registry import Registry
from scripts._common import pig_bundle


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposals", type=int, default=30)
    ap.add_argument("--full-evals", type=int, default=6)
    ap.add_argument("--max-markers", type=int, default=None)
    a = ap.parse_args()
    b = pig_bundle(a.max_markers)
    camp = Campaign(b, registry=Registry(), seed=0, n_proposals=a.proposals, budget_full_evals=a.full_evals)
    res = camp.run_all("ADF")
    print(res["arms"]["A_champion"])
    pkgs = sorted((paths.registry_dir() / "packages").glob("*.md"), key=lambda p: p.stat().st_mtime)
    out = paths.reports_dir(); out.mkdir(exist_ok=True)
    evaluated = res["arms"]["D_abl_loop"].get("evaluated", [])
    if pkgs and evaluated:
        best = max(evaluated, key=lambda r: (r["state"] == "promoted", r["delta_oos"] or -9))
        src = paths.registry_dir() / "packages" / f"{best['candidate_id']}.md"
        shutil.copy(src, out / "BreedingPackage_pig_cleveland.md")
        print(f"BreedingPackage → reports/BreedingPackage_pig_cleveland.md ({best['candidate_id']}, {best['state']})")
    write_scorecard(camp.reg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
