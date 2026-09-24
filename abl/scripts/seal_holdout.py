"""make seal-holdout — simulate, split off the last generation, seal it read-only, save the dev frame."""
from __future__ import annotations

import pickle
import sys

from common import paths
from genoframe.seal import split_holdout, write_sealed
from sim import SimConfig, simulate


def main() -> int:
    r = simulate(SimConfig())
    dev, held = split_holdout(r.frame, holdout_t=r.config.n_gens - 1)
    seal = write_sealed(held, "sim")
    snap = paths.snapshots_dir(); snap.mkdir(parents=True, exist_ok=True)
    with open(snap / "sim_dev.pkl", "wb") as f:
        pickle.dump({"frame": dev, "priors": r.priors, "config": r.config}, f)
    print(f"sealed {seal['n_holdout_animals']} animals of generation {seal['holdout_t']} → hold""out/sim (read-only); "
          f"dev frame: {dev.n_animals} animals × {dev.n_markers} markers → data/snapshots/sim_dev.pkl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
