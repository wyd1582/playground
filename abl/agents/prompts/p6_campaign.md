Run a controlled campaign to answer one question honestly: "Does any LLM- or deep-learning-
derived challenger add paired ΔOOS accuracy over frozen ssGBLUP on public pig data, and does the
harness correctly reject negative controls?"
Arms: (A) frozen ssGBLUP champion; (B) random-operator search, same budget; (C) one-shot LLM
proposal without loop; (D) full ABL inner loop, 100 proposals, ≤12 full evaluations;
(E) negative control: shuffled phenotypes; (F) negative control: random SNP subset.
Data: AlphaSimR simulation (true BVs known) and Cleveland 2012 public pig dataset.
Report: scorecard table; one BreedingPackage; one paragraph on what the harness rejected and why.
Do not tune thresholds after seeing results. Holdout generation stays sealed until the final table.
