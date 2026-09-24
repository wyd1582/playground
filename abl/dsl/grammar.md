# ABL DSL grammar (restricted operators)

A candidate is a Python-literal expression of the form

    champion() + op1(kw=literal, ...) + op2(...) ...

* Exactly one `champion()` and it must come first. Everything else *adds* one controlled
  variable on top of the frozen champion (DESIGN.md §3: "one controlled variable at a time"
  lives at the campaign level; inside a candidate at most `validity.max_operators` operators).
* Keyword arguments only, literal values only (str / int / float / bool / list of str).
* Each operator may appear at most once. Operators are commutative: the semantic hash sorts
  them, so `champion()+a()+b()` and `champion()+b()+a()` are the same candidate.

| operator | arguments | units / domain | status |
|---|---|---|---|
| `champion()` | — | — | required |
| `grm_weights(scheme=...)` | `scheme ∈ {uniform, maf_inverse, maf_power}`; `power` (float, only for maf_power, [-1, 1]) | dimensionless marker weights ≥ 0 | implemented |
| `region_weight(chrom=int, weight=float)` | `chrom ≥ 1`; `weight ∈ [0, 10]` (multiplier on that chromosome's markers) | dimensionless | implemented |
| `qtl_prior(source=str, weight=float)` | `source` must exist in the data catalog's prior list; `weight ∈ [0, 10]` = extra weight on prior markers | dimensionless | implemented |
| `covariate(field=str)` | `field ∈ {farm, line, sex, birth_t}` (all known at birth) | categorical fixed effect | implemented |
| `blend_pedigree(w=float)` | `w ∈ [0, 1]`: G ← (1-w)·G + w·A₂₂ | fraction | implemented (needs pedigree) |
| `dominance(w=float)` | `w ∈ (0, 1]`: adds w·D (dominance relationship) to the relationship | fraction | implemented |
| `snp_subset(strategy=str, fraction=float, seed=int)` | `strategy ∈ {random, top_maf, prior_list}`; `fraction ∈ (0, 1]` | fraction of panel | implemented |
| `lambda_scale(factor=float)` | `factor ∈ [0.2, 5]` multiplies the champion's λ = σe²/σa² | dimensionless | implemented |
| `multi_trait(traits=[str, ...])` | — | — | **reserved → NEED_OPERATOR** |
| `env_covariate(field=str)` | — | — | **reserved → NEED_OPERATOR** (G×E, needs environment table) |

Every field an operator touches is listed in `dsl/ast.py::FIELD_AVAILABILITY` with its
`available_at` semantics; the validity gate rejects any declaration whose field is not
knowable at `selection_date`.
