"""Random-operator search (control arm B): sample grammar-valid programs uniformly."""
from __future__ import annotations

import numpy as np

from .ast import Program, parse, validate


def random_program(rng: np.random.Generator, priors: list[str], has_pedigree: bool = True,
                   max_ops: int = 2) -> Program:
    pool = ["grm_weights", "region_weight", "covariate", "dominance", "snp_subset", "lambda_scale"]
    if priors:
        pool.append("qtl_prior")
    if has_pedigree:
        pool.append("blend_pedigree")
    k = int(rng.integers(1, max_ops + 1))
    names = rng.choice(pool, size=k, replace=False)
    parts = ["champion()"]
    for n in names:
        if n == "grm_weights":
            s = rng.choice(["maf_inverse", "maf_power"])
            parts.append(f"grm_weights(scheme='{s}'" + (f", power={float(rng.uniform(-1, 1)):.2f})" if s == "maf_power" else ")"))
        elif n == "region_weight":
            parts.append(f"region_weight(chrom={int(rng.integers(1, 6))}, weight={float(rng.uniform(0, 5)):.2f})")
        elif n == "qtl_prior":
            parts.append(f"qtl_prior(source='{rng.choice(priors)}', weight={float(rng.uniform(0, 5)):.2f})")
        elif n == "covariate":
            parts.append(f"covariate(field='{rng.choice(['farm', 'line', 'sex'])}')")
        elif n == "dominance":
            parts.append(f"dominance(w={float(rng.uniform(0.05, 0.5)):.2f})")
        elif n == "snp_subset":
            parts.append(f"snp_subset(strategy='{rng.choice(['random', 'top_maf'])}', fraction={float(rng.uniform(0.2, 0.9)):.2f}, seed={int(rng.integers(0, 10**6))})")
        elif n == "lambda_scale":
            parts.append(f"lambda_scale(factor={float(rng.uniform(0.3, 3)):.2f})")
        elif n == "blend_pedigree":
            parts.append(f"blend_pedigree(w={float(rng.uniform(0.05, 0.5)):.2f})")
    return validate(parse(" + ".join(parts)), known_priors=set(priors), has_pedigree=has_pedigree)
