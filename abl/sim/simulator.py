"""Pure-Python forward-in-time breeding simulator (AlphaSimR fallback, OPS.md B.1).

Founders are mosaics of a small pool of ancestral haplotypes (so markers carry LD), QTL are
hidden loci *not* on the marker panel, and each generation is bred from parents selected on
their own phenotype within line. Everything is seeded; the same config yields byte-identical
data. True breeding values are stored on the returned GenoFrame's ``true_bv`` and never
leave gates/.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from common.hashing import sha256_json
from common.seeds import GLOBAL_SEED
from genoframe import GenoFrame, Markers


@dataclass
class SimConfig:
    n_founders: int = 400
    n_per_gen: int = 500
    n_gens: int = 6                  # generations 0..n_gens-1; the last one is the sealed holdout
    n_chrom: int = 5
    markers_per_chrom: int = 400
    qtl_per_chrom: int = 20
    n_ancestral_haplotypes: int = 40
    mosaic_segment_mean: int = 40    # markers per ancestral segment in founders (controls LD)
    n_lines: int = 2
    n_farms: int = 3
    traits: tuple[str, ...] = ("t1", "t2")
    h2: tuple[float, ...] = (0.35, 0.25)
    genetic_corr: float = 0.3        # share of QTL shared between traits
    dominance_var: float = 0.05      # fraction of phenotypic variance from dominance (hidden from TBV)
    farm_var: float = 0.10
    line_var: float = 0.05
    year_var: float = 0.03
    sel_frac_male: float = 0.10
    sel_frac_female: float = 0.40
    prior_true_share: float = 0.5    # share of true QTL neighbourhoods in the "literature" prior
    seed: int = GLOBAL_SEED

    def config_hash(self) -> str:
        return sha256_json(asdict(self))[:12]


@dataclass
class SimResult:
    frame: GenoFrame
    priors: dict[str, np.ndarray] = field(default_factory=dict)   # name -> marker weights (m,)
    config: SimConfig = field(default_factory=SimConfig)


def _founder_haplotypes(rng, n_hap, n_loci, cfg: SimConfig):
    freqs = rng.beta(0.6, 0.6, size=n_loci).clip(0.02, 0.98)
    anc = (rng.random((cfg.n_ancestral_haplotypes, n_loci)) < freqs).astype(np.int8)
    hap = np.empty((n_hap, n_loci), dtype=np.int8)
    for h in range(n_hap):
        pos = 0
        while pos < n_loci:
            seg = max(1, int(rng.exponential(cfg.mosaic_segment_mean)))
            src = rng.integers(cfg.n_ancestral_haplotypes)
            hap[h, pos:pos + seg] = anc[src, pos:pos + seg]
            pos += seg
    return hap


def _meiosis(rng, hap_a, hap_b, chrom_bounds):
    """One gamete: per chromosome Poisson(1) crossovers on a 1-Morgan map, random start strand."""
    out = np.empty_like(hap_a)
    for lo, hi in chrom_bounds:
        n = hi - lo
        k = rng.poisson(1.0)
        cuts = np.sort(rng.integers(1, n, size=k)) if k > 0 and n > 1 else np.array([], dtype=int)
        strand = rng.integers(2)
        seg_start = 0
        for c in list(cuts) + [n]:
            src = hap_a if strand == 0 else hap_b
            out[lo + seg_start: lo + c] = src[lo + seg_start: lo + c]
            strand ^= 1
            seg_start = c
    return out


def simulate(cfg: SimConfig | None = None) -> SimResult:
    cfg = cfg or SimConfig()
    rng = np.random.default_rng(cfg.seed)
    per_chrom = cfg.markers_per_chrom + cfg.qtl_per_chrom
    n_loci = cfg.n_chrom * per_chrom
    chrom_bounds = [(c * per_chrom, (c + 1) * per_chrom) for c in range(cfg.n_chrom)]
    chrom_of = np.repeat(np.arange(1, cfg.n_chrom + 1), per_chrom)
    pos_of = np.concatenate([np.linspace(0, 100, per_chrom, endpoint=False) for _ in range(cfg.n_chrom)])
    # hidden QTL positions: qtl_per_chrom loci per chromosome
    qtl_mask = np.zeros(n_loci, dtype=bool)
    for lo, hi in chrom_bounds:
        qtl_mask[rng.choice(np.arange(lo, hi), size=cfg.qtl_per_chrom, replace=False)] = True
    qtl_idx = np.flatnonzero(qtl_mask)
    marker_idx = np.flatnonzero(~qtl_mask)

    # QTL effects per trait, shared subset for genetic correlation
    n_q = len(qtl_idx)
    shared = rng.random(n_q) < cfg.genetic_corr
    add_eff = np.zeros((len(cfg.traits), n_q))
    dom_eff = np.zeros((len(cfg.traits), n_q))
    base = rng.normal(size=n_q)
    for ti in range(len(cfg.traits)):
        own = rng.normal(size=n_q)
        add_eff[ti] = np.where(shared, base, own)
        dom_eff[ti] = rng.normal(size=n_q) * 0.5

    # founders
    haps = _founder_haplotypes(rng, 2 * cfg.n_founders, n_loci, cfg)
    hapA, hapB = haps[0::2], haps[1::2]

    animals, phen_rows, tbv_rows = [], [], []
    geno_rows, geno_ids = [], []
    line_eff = rng.normal(scale=np.sqrt(cfg.line_var), size=cfg.n_lines)
    farm_eff = rng.normal(scale=np.sqrt(cfg.farm_var), size=cfg.n_farms)
    year_eff = rng.normal(scale=np.sqrt(cfg.year_var), size=cfg.n_gens)

    # scale additive effects so Var(TBV) = h2 in founders (phenotypic variance ~ 1)
    X0 = (hapA + hapB).astype(float)
    p0 = X0.mean(0) / 2
    scale = []
    for ti, h2 in enumerate(cfg.h2):
        tb = (X0[:, qtl_idx] - 2 * p0[qtl_idx]) @ add_eff[ti]
        scale.append(np.sqrt(h2) / tb.std())
        add_eff[ti] *= scale[-1]
        dom_eff[ti] *= scale[-1] * np.sqrt(cfg.dominance_var / max(h2, 1e-9)) * 2
    counter = 0

    def register(gen, hA, hB, sire, dam, line, farm):
        nonlocal counter
        counter += 1
        aid = f"a{counter:06d}"
        x = (hA + hB).astype(float)
        sex = "M" if rng.random() < 0.5 else "F"
        animals.append(dict(animal_id=aid, sire=sire, dam=dam, sex=sex, line=f"L{line+1}",
                            farm=f"F{farm+1}", birth_t=gen))
        geno_rows.append((hA + hB)[marker_idx].astype(np.int8))
        geno_ids.append(aid)
        het = ((hA[qtl_idx] != hB[qtl_idx])).astype(float)
        ys = {}
        for ti, tr in enumerate(cfg.traits):
            tbv = float((x[qtl_idx] - 2 * p0[qtl_idx]) @ add_eff[ti])
            dom = float(het @ dom_eff[ti]) - float(np.mean(dom_eff[ti]) * len(qtl_idx) * 0.5)
            e = rng.normal(scale=np.sqrt(max(1e-6, 1 - cfg.h2[ti] - cfg.dominance_var)))
            y = 10.0 + line_eff[line] + farm_eff[farm] + year_eff[gen] + tbv + dom + e
            tbv_rows.append(dict(animal_id=aid, trait=tr, tbv=tbv))
            phen_rows.append(dict(animal_id=aid, trait=tr, value=float(y), available_at=gen))
            ys[tr] = y
        return aid, ys

    # generation 0
    gen_pool = []   # list of (aid, hA, hB, sex, line, y_sel)
    for i in range(cfg.n_founders):
        line = i % cfg.n_lines
        farm = int(rng.integers(cfg.n_farms))
        aid, ys = register(0, hapA[i], hapB[i], None, None, line, farm)
        gen_pool.append((aid, hapA[i], hapB[i], animals[-1]["sex"], line, ys[cfg.traits[0]]))

    for gen in range(1, cfg.n_gens):
        new_pool = []
        per_line = cfg.n_per_gen // cfg.n_lines
        for line in range(cfg.n_lines):
            males = [p for p in gen_pool if p[4] == line and p[3] == "M"]
            females = [p for p in gen_pool if p[4] == line and p[3] == "F"]
            males.sort(key=lambda p: -p[5]); females.sort(key=lambda p: -p[5])
            sires = males[:max(2, int(len(males) * cfg.sel_frac_male))]
            dams = females[:max(4, int(len(females) * cfg.sel_frac_female))]
            for k in range(per_line):
                s = sires[k % len(sires)]
                d = dams[int(rng.integers(len(dams)))]
                gA = _meiosis(rng, s[1], s[2], chrom_bounds)
                gB = _meiosis(rng, d[1], d[2], chrom_bounds)
                farm = int(rng.integers(cfg.n_farms))
                aid, ys = register(gen, gA, gB, s[0], d[0], line, farm)
                new_pool.append((aid, gA, gB, animals[-1]["sex"], line, ys[cfg.traits[0]]))
        gen_pool = new_pool

    G = np.vstack(geno_rows)
    markers = Markers(marker_id=np.array([f"m{i:05d}" for i in range(len(marker_idx))]),
                      chrom=chrom_of[marker_idx].astype(int), pos=pos_of[marker_idx].astype(float),
                      map_source="declared")
    frame = GenoFrame(
        animals=pd.DataFrame(animals), phenotypes=pd.DataFrame(phen_rows), genotypes=G,
        geno_ids=np.array(geno_ids), markers=markers, calendar={g: f"gen{g}" for g in range(cfg.n_gens)},
        genotype_source="sim",
        meta={"species": "sim_pig", "source": "sim/simulator.py", "config_hash": cfg.config_hash(),
              "calendar_source": "generation_index", "map_source": "declared", "pedigree": "complete"},
        true_bv=pd.DataFrame(tbv_rows),
    ).validate().fill_versions(code_hash="sim:" + cfg.config_hash())

    # "literature" priors over the *marker* panel: markers within ±2 positions of a QTL get weight 1
    m = len(marker_idx)
    near_qtl = np.zeros(m, dtype=bool)
    mpos = marker_idx
    for q in qtl_idx:
        near = np.flatnonzero(np.abs(mpos - q) <= 2)
        near_qtl[near] = True
    prng = np.random.default_rng(cfg.seed + 1)
    noisy = np.zeros(m)
    truth_keep = np.flatnonzero(near_qtl)
    noisy[prng.choice(truth_keep, size=int(len(truth_keep) * cfg.prior_true_share), replace=False)] = 1.0
    noisy[prng.choice(np.flatnonzero(~near_qtl), size=len(truth_keep) - int(len(truth_keep) * cfg.prior_true_share), replace=False)] = 1.0
    random_prior = np.zeros(m); random_prior[prng.choice(m, size=int(noisy.sum()), replace=False)] = 1.0
    priors = {"sim_noisy_qtl_prior": noisy, "random_prior": random_prior}
    return SimResult(frame=frame, priors=priors, config=cfg)
