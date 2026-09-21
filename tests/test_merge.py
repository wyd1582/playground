"""合并节点测试：规模账目、ID 冲突防护、存储一致性。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from refpop_agent.config import PipelineConfig, TRAIT
from refpop_agent.io_utils import BatchData, RefpopStore, load_refpop, read_json
from refpop_agent.nodes.merge import merge_into_refpop


def _tiny_batch(ids, m=20, batch_id="B1"):
    rng = np.random.default_rng(1)
    n = len(ids)
    return BatchData(
        batch_id, np.array(ids),
        rng.integers(0, 3, size=(n, m)).astype(np.int8),
        pd.DataFrame({"id": ids, TRAIT: 2800.0,
                      "submitted_at": "2026-01-01T09:00:00"}),
        pd.DataFrame({"id": ids, "sire": "", "dam": "", "sex": "M",
                      "generation": 1}),
        {},
    )


def test_merge_counts_and_conflict_guard():
    store, s1 = merge_into_refpop(RefpopStore.empty(), _tiny_batch(["a", "b"]), "B1")
    assert (s1["n_before"], s1["n_added"], s1["n_after"]) == (0, 2, 2)
    store2, s2 = merge_into_refpop(store, _tiny_batch(["c"]), "B2")
    assert s2["n_after"] == 3 and store2.n == 3
    assert store2.pheno["batch"].tolist() == ["B1", "B1", "B2"]
    with pytest.raises(ValueError):                # 重复 ID 必须硬失败
        merge_into_refpop(store2, _tiny_batch(["b"]), "B3")


def test_pipeline_refpop_growth(pipeline):
    config: PipelineConfig = pipeline["config"]
    expect = {"G0": (0, 2000, 2000), "G1": (2000, 500, 2500), "G2": (2500, 500, 3000)}
    for batch, (before, added, after) in expect.items():
        s = read_json(config.run_dir(batch) / "merge_summary.json")
        assert (s["n_before"], s["n_added"], s["n_after"]) == (before, added, after)
    store = load_refpop(config.refpop_dir())
    assert store.n == 3000
    assert len(set(store.ids.tolist())) == 3000     # 无重复 ID
    registry = read_json(config.refpop_dir() / "registry.json")
    assert [r["batch_id"] for r in registry] == ["G0", "G1", "G2"]
