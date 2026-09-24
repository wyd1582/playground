"""Public-data loaders → GenoFrame.

The vendored Cleveland pig file has genotypes and one phenotype but no pedigree, map or dates.
ABL's forward-in-time contract needs a time axis, so ``pseudo_generations`` derives ordered
family blocks from the genomic relationship (k-means on the top principal components of G) and
declares ``calendar_source = "synthetic_family_blocks"``. This is the honest equivalent of the
leave-family-out protocol; it is written into every data declaration and BreedingPackage.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from common import paths
from common.hashing import sha256_array
from genoframe import GenoFrame, Markers

from .catalog import VENDORED


def pseudo_generations(X: np.ndarray, k: int = 4, seed: int = 0, n_pcs: int = 10) -> np.ndarray:
    """Ordered family blocks 0..k-1 from the GRM's leading PCs (deterministic k-means)."""
    from sklearn.cluster import KMeans

    Xc = np.asarray(X, dtype=np.float64)
    p = Xc.mean(0) / 2
    Z = Xc - 2 * p
    G = Z @ Z.T / (2 * np.sum(p * (1 - p)))
    vals, vecs = np.linalg.eigh(G)
    pcs = vecs[:, ::-1][:, :n_pcs] * np.sqrt(np.maximum(vals[::-1][:n_pcs], 0))
    lab = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(pcs)
    order = pd.Series(lab).value_counts().index.tolist()          # largest block first = "oldest"
    remap = {old: new for new, old in enumerate(order)}
    return np.array([remap[v] for v in lab], dtype=int)


def _index_block_markers(m: int, block: int = 1000) -> Markers:
    chrom = (np.arange(m) // block) + 1
    pos = (np.arange(m) % block).astype(float)
    return Markers(np.array([f"snp{i:06d}" for i in range(m)]), chrom.astype(int), pos, map_source="index_blocks")


def load_pig_cleveland(path: Path | None = None, *, maf_min: float = 0.01, max_markers: int | None = None,
                       n_blocks: int = 4, seed: int = 0) -> GenoFrame:
    import rdata

    p = paths.assert_not_holdout(path or VENDORED / "pig_cleveland_curated.rdata")
    conv = rdata.conversion.convert(rdata.parser.parse_file(str(p)))
    X = np.asarray(conv["geno"].values, dtype=np.float32)
    ids = np.array([f"pig{int(float(i)):05d}" for i in conv["pheno"]["id"].to_numpy()])
    y = conv["pheno"]["pheno"].to_numpy(dtype=float)
    freq = X.mean(0) / 2
    keep = np.flatnonzero(np.minimum(freq, 1 - freq) >= maf_min)
    if max_markers and len(keep) > max_markers:
        rng = np.random.default_rng(seed)
        keep = np.sort(rng.choice(keep, size=max_markers, replace=False))
    X = np.ascontiguousarray(X[:, keep])
    blocks = pseudo_generations(X[:, :: max(1, X.shape[1] // 8000)], k=n_blocks, seed=seed)
    animals = pd.DataFrame({"animal_id": ids, "sire": None, "dam": None, "sex": "U", "line": "PIC", "farm": "unknown", "birth_t": blocks})
    ok = np.isfinite(y)
    phen = pd.DataFrame({"animal_id": ids[ok], "trait": "t1", "value": y[ok], "available_at": blocks[ok]})
    frame = GenoFrame(animals=animals, phenotypes=phen, genotypes=X, geno_ids=ids, markers=_index_block_markers(X.shape[1]),
                      calendar={i: f"family_block_{i}" for i in range(n_blocks)}, genotype_source="solid",
                      meta={"species": "pig", "source": "Cleveland et al. 2012 (G3) via QuantGen/G2P-Datasets@a7bf58a", "sha256_prefix": "9968d60791971d9b",
                            "calendar_source": "synthetic_family_blocks", "map_source": "index_blocks", "pedigree": "none",
                            "maf_min": maf_min, "n_markers_after_qc": int(X.shape[1]), "trait_note": "t1 only (weak-signal trait; GBLUP random-CV r≈0.06 in Task A)"})
    return frame.validate().fill_versions(code_hash="dataio.load_pig_cleveland")


def load_wheat_bglr(path: Path | None = None, trait: str = "env1", n_blocks: int = 4, seed: int = 0) -> GenoFrame:
    import rdata

    p = paths.assert_not_holdout(path or VENDORED / "wheat.RData")
    conv = rdata.conversion.convert(rdata.parser.parse_file(str(p)))
    X = np.asarray(conv["wheat.X"], dtype=np.float32)
    Y = np.asarray(conv["wheat.Y"], dtype=float)
    ids = np.array([f"wheat{i:04d}" for i in range(X.shape[0])])
    blocks = pseudo_generations(X, k=n_blocks, seed=seed)
    animals = pd.DataFrame({"animal_id": ids, "sire": None, "dam": None, "sex": "U", "line": "CIMMYT", "farm": "unknown", "birth_t": blocks})
    rows = []
    for j in range(Y.shape[1]):
        rows.append(pd.DataFrame({"animal_id": ids, "trait": f"env{j+1}", "value": Y[:, j], "available_at": blocks}))
    phen = pd.concat(rows).reset_index(drop=True)
    frame = GenoFrame(animals=animals, phenotypes=phen, genotypes=X, geno_ids=ids, markers=_index_block_markers(X.shape[1], block=200),
                      calendar={i: f"family_block_{i}" for i in range(n_blocks)}, genotype_source="solid",
                      meta={"species": "wheat", "source": "BGLR wheat (gdlc/BGLR-R@de839cf)", "sha256_prefix": "8710523389007dd8",
                            "calendar_source": "synthetic_family_blocks", "map_source": "index_blocks", "pedigree": "none (A matrix only)"})
    return frame.validate().fill_versions(code_hash="dataio.load_wheat_bglr")
