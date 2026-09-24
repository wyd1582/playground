# Final sealed-holdout table (sim)

Opened once, after the campaign, by campaigns/final_table.py (event flag holdout_final_read). Test set = the sealed generation; training = everything the campaign was allowed to see.

| model | dsl | holdout_n | lr_rho | dispersion_b | predictive_r | delta_predictive_r_vs_champion | true_accuracy |
|---|---|---|---|---|---|---|---|
| champion | champion() | 500 | 0.8778 | 1.146 | 0.3247 | 0 | 0.647 |
