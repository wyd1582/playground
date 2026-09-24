import numpy as np
import pytest

from dsl import DSLError, NeedOperator, compile_program, parse, random_program, semantic_hash, validate


def test_parse_validate_hash_commutative():
    a = validate(parse("champion() + covariate(field='farm') + dominance(w=0.3)"))
    b = validate(parse("champion() + dominance(w=0.30000000001) + covariate(field='farm')"))
    assert semantic_hash(a) == semantic_hash(b)
    assert a.canonical() == b.canonical()
    assert a.fields == ["animals.farm", "genotypes"]
    spec = compile_program(a)
    assert spec.covariates == ["farm"] and spec.dominance_w == 0.3 and not spec.is_champion
    assert compile_program(validate(parse("champion()"))).is_champion


@pytest.mark.parametrize("text", [
    "covariate(field='farm')",                       # no champion
    "champion() + champion()",
    "champion() + covariate('farm')",                # positional
    "champion() + covariate(field='progeny_mean')",  # field not knowable at selection date
    "champion() + dominance(w=1.5)",                 # unit/domain
    "champion() + lambda_scale(factor=0.01)",
    "champion() + unknown_op(x=1)",
    "champion() + covariate(field='farm') + covariate(field='line')",  # duplicate op
    "champion() + qtl_prior(source='nope', weight=1.0)",
    "champion() + grm_weights(scheme='maf_power')",  # missing power
    "champion() + blend_pedigree(w=0.1)",            # has_pedigree=False below
])
def test_rejects(text):
    with pytest.raises(DSLError):
        validate(parse(text), known_priors={"sim_noisy_qtl_prior"}, has_pedigree=False)


def test_reserved_returns_need_operator():
    with pytest.raises(NeedOperator):
        validate(parse("champion() + multi_trait(traits=['t1','t2'])"))


def test_max_operators():
    with pytest.raises(DSLError):
        validate(parse("champion() + covariate(field='farm') + dominance(w=0.2) + lambda_scale(factor=2) "
                       "+ grm_weights(scheme='maf_inverse') + region_weight(chrom=1, weight=2)"), max_operators=4)


def test_random_program_is_valid():
    rng = np.random.default_rng(0)
    for _ in range(50):
        p = random_program(rng, ["sim_noisy_qtl_prior"], has_pedigree=True)
        assert p.ops[0].name == "champion" and 1 <= len(p.ops) - 1 <= 2
