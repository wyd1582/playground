# sim-controls — true vs estimated accuracy (simulated pig, last generation sealed)

Run `20260924T1152` seed 0 · champion frozen: `{"name": "ssGBLUP_uniform", "blend_w": 0.05, "covariates": ["line", "farm", "birth_t"], "lam": 3.056498524737475, "h2": 0.2465180238330586, "ridge_eps": 0.01, "trait": "t1", "frozen_on_split": "7b5e7fd42f6d2eb3", "champion_id": "champ_1b872c8829"}`

Null (champion on labels shuffled within birth_t, 3 seeds): LR rho 0.528 ± 0.035; predictive r -0.012 ± 0.015. The LR rho of a null model is far from zero — it is not null-calibrated — which is why gate 1 uses this empirical null and gate 2 uses the predictive correlation.

Forward-in-time splits (train labels ≤ cutoff, test = next generation, parents/full-sibs purged): [{"cutoff": 1, "n_train": 775, "n_test": 500, "purged": 125}, {"cutoff": 2, "n_train": 1279, "n_test": 500, "purged": 121}, {"cutoff": 3, "n_train": 1779, "n_test": 500, "purged": 121}]

| arm | true_accuracy | lr_rho | predictive_r | dispersion_b | full_evaluations | promoted | best_delta_oos |
|---|---|---|---|---|---|---|---|
| A frozen champion (ssGBLUP, uniform weights) | 0.508 | 0.77 | 0.242 | 1.12 |  |  |  |
| E champion on labels shuffled within generation | 0.018 | 0.585 | 0.029 | 0.7 |  |  |  |
| B random-operator search (same budget as the loop) |  |  |  |  | 12 | 0 | 0.0144 |
| E ABL loop on shuffled labels (negative control) |  |  |  |  | 4 | 0 (false promotions) | -0.0001 |
| F random 30 % SNP subsets (negative control) |  |  |  |  | 5 | 0 (false promotions) | -0.0405 |
