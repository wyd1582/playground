You are building "ABL" (Agentic Breeding-value Loop), a research harness for genomic
selection. Follow this contract exactly; ask no clarifying questions—make and log assumptions.

GOAL
An agentic inner loop (Geneticist → Builder → Critic → Evaluate → Analyst) explores
hypotheses for improving cross-sectional breeding-value scores; a deterministic core
decides what survives. Agents recommend; only machine-checkable gates change candidate state.

REPO LAYOUT
  genoframe/   data contract + point-in-time snapshots + forward-in-time splitter
  dsl/         restricted operator grammar, AST validator, unit checker, compiler
  engine/      GRM, GBLUP/ssGBLUP (frozen champion), plan simulator (ΔF, gain/yr, OCS)
  gates/       validity, accuracy(LR method: rho, bias, dispersion), incremental(paired),
               plan, robustness, research(multiple-testing)
  registry/    append-only trial ledger: proposal, code hash, data hash, cost, result, disposition
  agents/      orchestrator, geneticist, builder, critic, analyst (prompt files + tool schemas)
  campaigns/   champion–challenger runner; negative controls; scorecard
  holdout/     latest generation; READ-ONLY; never loaded by any agent process
  sim/         AlphaSimR wrapper (true breeding values known) for positive/negative controls

DATA CONTRACT (GenoFrame)
  key = (animal_id, selection_date); fields = score, in_universe, available_at,
  genotype_source in {solid, liquid, seq}; versioned genotype_build, pedigree_snapshot,
  phenotype_snapshot, calendar, code, universe.
  Rules: no silent forward fill; no duplicate keys; training rows require label_exit <=
  cutoff; purge parents/full-sibs of test animals from training; every split is
  forward-in-time across generations.

GATES (all must be deterministic and unit-tested)
  0 validity  1 accuracy(LR)  2 incremental(paired ΔOOS vs frozen champion, same cutoffs/seeds)
  3 plan(ΔF cap, gain/yr at equal genotyping cost)  4 robustness(farm/year/line, drop-top-family)
  5 research(trial count, DSR-style correction). Promotion requires all mandatory gates.

FIREWALL
  Nothing under holdout/ may appear in any prompt, memory file, retrieval index or reward.
  Implement as a filesystem permission + a test that greps agent inputs for holdout hashes.

DELIVERABLES
  1) `make sim-controls`: AlphaSimR campaign where true BVs are known; report true-vs-estimated
     accuracy for champion, a random-operator challenger, and a shuffled-label negative control.
  2) `make pig-public`: run on the Cleveland 2012 public pig dataset; produce one
     BreedingPackage (thesis, DSL, data declaration, tests, provenance, evaluation).
  3) `make scorecard`: valid candidates per 100 proposals, full evaluations per promotion,
     corrected mean/best ΔOOS, false promotions on negative controls, reproducibility rate.
  4) README explaining, in one page, why the harness (not the model) is the product.

STYLE
  Small deterministic modules with fixed seeds; log every agent call with token cost;
  prefer rejecting a candidate over rescuing it.
