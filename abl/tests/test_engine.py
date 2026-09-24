import numpy as np
import pandas as pd

from dsl import compile_program, parse, validate
from engine import Evaluator, freeze_champion
from engine.grm import weighted_grm
from engine.pedigree import a_matrix
from engine.plan import plan_metrics, selection_intensity
from genoframe import forward_splits
from sim import SimConfig, simulate

CFG = SimConfig(n_founders=200, n_per_gen=300, n_gens=5, n_chrom=3, markers_per_chrom=200, qtl_per_chrom=8)


def _setup():
    r = simulate(CFG)
    pub = r.frame.public_view()
    splits = forward_splits(pub, "t1", max_t=3)
    ev = Evaluator(pub, r.priors, "t1")
    champ = freeze_champion(ev, splits[-1], blend_w=0.05, covariates=["line", "farm", "birth_t"])
    return r, pub, splits, ev, champ


def test_grm_and_pedigree_basics():
    r = simulate(CFG)
    G = weighted_grm(r.frame.genotypes)
    assert abs(np.mean(np.diag(G)) - 1.0) < 0.25 and np.allclose(G, G.T)
    A, ids = a_matrix(r.frame.animals)
    assert A.shape[0] == len(ids) and np.allclose(np.diag(A)[:150], 1.0)
    off = A[np.triu_indices_from(A, 1)]
    assert off.max() > 0.4  # full-sibs / parent-offspring exist


def test_champion_has_real_accuracy_and_shuffled_labels_do_not():
    r, pub, splits, ev, champ = _setup()
    assert 0.05 < champ.h2 < 0.9
    spec = compile_program(validate(parse("champion()")))
    st = ev.evaluate(spec, splits[-1])
    tb = r.frame.true_bv[r.frame.true_bv.trait == "t1"].set_index("animal_id").tbv
    true_acc = np.corrcoef(st.u_partial.to_numpy(), tb.loc[st.u_partial.index].to_numpy())[0, 1]
    assert true_acc > 0.15, true_acc
    assert st.rho > 0.1 and st.coverage == 1.0 and 0.3 < st.dispersion < 2.0
    # deterministic replay
    st2 = ev.evaluate(spec, splits[-1])
    assert np.allclose(st.u_partial.to_numpy(), st2.u_partial.to_numpy())
    # shuffled labels within contemporary group (birth_t): the campaign's negative control
    sh = pub.public_view()
    rng = np.random.default_rng(1)
    perm = sh.phenotypes.copy()
    m = perm.trait == "t1"
    bt = pub.animals.set_index("animal_id").birth_t
    for g in sorted(bt.unique()):
        idx = perm.index[m & perm.animal_id.map(bt).eq(g)]
        perm.loc[idx, "value"] = rng.permutation(perm.loc[idx, "value"].to_numpy())
    sh.phenotypes = perm
    ev2 = Evaluator(sh, r.priors, "t1", champion=champ)
    st_sh = ev2.evaluate(spec, splits[-1])
    acc_sh = np.corrcoef(st_sh.u_partial.to_numpy(), tb.loc[st_sh.u_partial.index].to_numpy())[0, 1]
    # null predictions inherit K's structure, so the null sd is wider than 1/sqrt(n): compare to the real signal
    assert true_acc - acc_sh > 0.25 and abs(acc_sh) < 0.3, (true_acc, acc_sh)
    # the LR rho is NOT null-calibrated (shared shrinkage noise) but the predictive r is
    assert abs(st_sh.extra["predictive_r"]) < 0.15 and st.extra["predictive_r"] > 0.08


def test_operators_change_the_model_and_plan_metrics():
    r, pub, splits, ev, champ = _setup()
    base = ev.evaluate(compile_program(validate(parse("champion()"))), splits[-1])
    prior = ev.evaluate(compile_program(validate(parse("champion() + qtl_prior(source='sim_noisy_qtl_prior', weight=3.0)"),
                                                 known_priors=set(r.priors))), splits[-1])
    assert not np.allclose(base.u_partial.to_numpy(), prior.u_partial.to_numpy())
    K = ev.relationship(compile_program(validate(parse("champion()"))))
    pm = plan_metrics(base.u_partial, K, ev.ids, selected_fraction=0.1, accuracy=base.rho, sigma_a=0.6,
                      generation_interval_years=1.5)
    assert pm["n_selected"] >= 2 and pm["gain_per_year"] >= 0 and -0.2 < pm["delta_f"] < 0.5
    assert abs(selection_intensity(0.1) - 1.755) < 0.01
