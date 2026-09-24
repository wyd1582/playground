# BreedingPackage k_11670e9a15 — REJECTED

Campaign `pig_cleveland_D_s0_r20260924T1159` · created 2026-09-24T12:05:17Z · agent model `stub`

## 1. Thesis
**Mechanism.** Low-MAF markers add estimation noise to G; keeping only the most informative half loses little signal and reduces noise.

**Direction.** Minimal reordering; better-calibrated dispersion.

**Falsifiers.**
- ΔOOS < 0

**Expected gain (prior).** {'delta_oos': 0.0, 'dispersion_b': 1.0} · cluster `panel_reduction` · refs: panel design literature

## 2. DSL
```
champion() + snp_subset(fraction=0.25, strategy='top_maf')
```
semantic hash `4552d07e99bffa99f6a7c71ce3d781b37ef66fb7b39a2b9d4ef1dee3a53b7426` · implements mechanism: "Low-MAF markers add estimation noise to G; keeping only the most informative hal" via snp_subset

## 3. Data declaration
| field | available_at | note |
|---|---|---|
| genotypes | birth | known at registration, <= selection_date |

snapshot `s_0893baf54b` · declaration hash `10ae05e332691a4b`

## 4. Tests (re-run by the validity gate)
| test | result | detail |
|---|---|---|
| grammar_units_causality | pass | champion() + snp_subset(fraction=0.25, strategy='top_maf') |
| data_declaration_matches_code | pass | 1 fields declared |
| semantic_hash_unique | pass | 4552d07e99bffa99 |
| splits_leak_free | pass | 3 forward-in-time splits |
| replay_determinism | pass | max|Δ|=0.00e+00 |
| edge_monomorphic_markers | pass | 0 monomorphic markers; weights finite |
| edge_missing_parents | pass | 3534 animals without sire handled as founders |

## 5. Provenance
- champion `champ_0dd98d219a` (ssGBLUP_uniform, h2=0.024, λ=41.36, blend=0.0)
- thresholds sha256 `03aced4eec69a7528e1e73bd15a9d25cfa919b151fa2aeae9efb5a605010a66e` · seed 0 · purge policy `contract`
- forward-in-time cutoffs [0, 1, 2] · split ids ['d934ac3d2615344d', 'd34c69ba9e8f513a', '84d70332d3d81548']

## 6. Evaluation
| gate | metric | value | 90% CI | threshold | result |
|---|---|---|---|---|---|
| validity | grammar_units_causality | 1 |  | 1 | pass |
| validity | data_declaration_matches_code | 1 |  | 1 | pass |
| validity | semantic_hash_unique | 1 |  | 1 | pass |
| validity | splits_leak_free | 1 |  | 1 | pass |
| validity | replay_determinism | 1 |  | 1 | pass |
| validity | edge_monomorphic_markers | 1 |  | 1 | pass |
| validity | edge_missing_parents | 1 |  | 1 | pass |
| accuracy | lr_rho | 0.5367 |  | 0.537 | pass |
| accuracy | lr_bias_sd | 0.04643 |  | 0.5 | pass |
| accuracy | lr_dispersion_b | 0.9384 | [+0.890, +0.987] | 1 | pass |
| accuracy | lr_dispersion_vs_champion | 0.06156 |  | 0.187 | pass |
| accuracy | lr_dispersion_ci_covers_one | 0 |  | 1 | pass |
| accuracy | coverage | 1 |  | 0.95 | pass |
| incremental | delta_oos | 0.009463 | [-0.010, +0.028] | 0 | FAIL |
| plan | delta_f | 0.003229 |  | 0.01 | pass |
| plan | delta_f_champion | -0.02414 |  | 0.01 | pass |
| plan | gain_per_year_ratio | 0.5812 |  | 1 | FAIL |
| plan | gain_per_year | 0.01627 |  | 0.028 | pass |
| robustness | max_share_birth_t | 0.838 |  | 0.7 | FAIL |
| research | n_trials | 8 |  |  | pass |
| research | z_deflated_threshold | 0.8478 |  | 1.46 | FAIL |
| research | deflated_p | 0.7295 |  | 0.1 | FAIL |

**Disposition.** Candidate k_11670e9a15 was rejected. Limiting gate: incremental — paired ΔOOS = +0.009 with 90% lower bound -0.010: the operator adds no information beyond the frozen champion.

**Diagnosis.** paired ΔOOS = +0.009 with 90% lower bound -0.010: the operator adds no information beyond the frozen champion

**Next experiment.** {"mechanism": "Published QTL/eQTL neighbourhoods carry a disproportionate share of additive variance; up-weighting markers inside them sharpens the genomic relationship for the trait.", "dsl": "champion() + qtl_prior(source='<prior>', weight=2.0)", "rationale": "cluster 'prior_weighting' is absent from the registry: highest expected information gain"}

