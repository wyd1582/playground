import numpy as np
import pandas as pd
import pytest

from genoframe import GenoFrame, Markers, forward_splits, pit_snapshot
from genoframe.splitter import assert_no_leak
from sim import SimConfig, simulate

SMALL = SimConfig(n_founders=80, n_per_gen=100, n_gens=4, n_chrom=2, markers_per_chrom=60, qtl_per_chrom=5)


def test_simulator_deterministic_and_valid():
    a, b = simulate(SMALL), simulate(SMALL)
    assert np.array_equal(a.frame.genotypes, b.frame.genotypes)
    assert a.frame.versions == b.frame.versions
    assert a.frame.true_bv is not None and a.frame.public_view().true_bv is None
    assert a.frame.n_markers == 120 and a.frame.animals.birth_t.max() == 3


def test_validation_catches_contract_violations():
    f = simulate(SMALL).frame
    bad = f.phenotypes.copy(); bad.loc[0, "value"] = np.nan
    with pytest.raises(ValueError, match="forward fill"):
        GenoFrame(f.animals, bad, f.genotypes, f.geno_ids, f.markers, f.calendar, "sim").validate()
    bad = pd.concat([f.phenotypes, f.phenotypes.head(1)])
    with pytest.raises(ValueError, match="duplicate"):
        GenoFrame(f.animals, bad, f.genotypes, f.geno_ids, f.markers, f.calendar, "sim").validate()
    bad = f.phenotypes.copy(); bad.loc[0, "available_at"] = -5
    with pytest.raises(ValueError, match="before birth"):
        GenoFrame(f.animals, bad, f.genotypes, f.geno_ids, f.markers, f.calendar, "sim").validate()
    with pytest.raises(ValueError, match="genotype_source"):
        GenoFrame(f.animals, f.phenotypes, f.genotypes, f.geno_ids, f.markers, f.calendar, "excel").validate()


def test_pit_snapshot_hides_the_future():
    f = simulate(SMALL).frame
    s = pit_snapshot(f, 1)
    assert s.frame.animals.birth_t.max() == 1
    assert s.frame.phenotypes.available_at.max() <= 1
    assert s.frame.animals.sire.dropna().isin(s.frame.animals.animal_id).all()


def test_forward_splits_purge_and_no_leak():
    f = simulate(SMALL).frame
    splits = forward_splits(f, "t1", max_t=2)          # gen 3 is the holdout here
    assert [s.cutoff_t for s in splits] == [0, 1]
    for s in splits:
        assert_no_leak(f, s, "t1")
        test_born = f.animals.set_index("animal_id").loc[s.test_ids].birth_t
        assert (test_born == s.cutoff_t + 1).all()
        # parents of the test generation were purged from training labels
        parents = set(f.animals.set_index("animal_id").loc[s.test_ids].sire.dropna())
        assert not (parents & set(s.train_ids)) and parents <= set(s.purged_ids)
    loose = forward_splits(f, "t1", max_t=2, purge_policy="temporal_only")
    assert len(loose[1].train_ids) > len(splits[1].train_ids)
    with pytest.raises(AssertionError):
        bad = splits[1]; bad.train_ids = bad.train_ids + [bad.purged_ids[0]]
        assert_no_leak(f, bad, "t1")
