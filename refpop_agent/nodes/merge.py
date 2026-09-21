"""合并节点 —— 将 QC 通过的个体并入参考群存储。确定性、可单测。

幂等防护：任何 ID 冲突直接报错（正常情况下 QC 已拦截 DUP_ID，
走到这里说明流程被跳步或重复执行，宁可失败也不静默污染参考群）。
合并历史追加写入 artifacts/refpop/registry.json。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PipelineConfig, TRAIT
from ..io_utils import (BatchData, RefpopStore, load_batch, load_refpop,
                        now_iso, read_json, save_refpop, write_json)


def merge_into_refpop(store: RefpopStore, admitted: BatchData, batch_id: str):
    """纯函数：合并放行个体。返回 (new_store, summary)。"""
    overlap = set(store.ids.tolist()) & set(admitted.ids.tolist())
    if overlap:
        raise ValueError(
            f"合并冲突：{len(overlap)} 个 ID 已在参考群中（例如 {sorted(overlap)[:3]}）。"
            "QC 应已拦截，请检查流程是否重复执行。")
    if store.n == 0:
        new_geno = admitted.geno.copy()
    else:
        if store.geno.shape[1] != admitted.geno.shape[1]:
            raise ValueError("标记数与参考群不一致，无法合并")
        new_geno = np.vstack([store.geno, admitted.geno])
    add_pheno = pd.DataFrame({
        "id": admitted.ids,
        TRAIT: admitted.pheno[TRAIT].to_numpy(),
        "generation": admitted.ped["generation"].to_numpy(),
        "batch": batch_id,
    })
    new_pheno = pd.concat([store.pheno, add_pheno], ignore_index=True)
    new_ped = pd.concat([store.ped, admitted.ped], ignore_index=True)
    new_ids = np.concatenate([store.ids, admitted.ids]) if store.n else admitted.ids.copy()
    new_store = RefpopStore(new_ids, new_geno, new_pheno, new_ped)
    summary = {
        "batch_id": batch_id,
        "n_before": store.n,
        "n_added": admitted.n,
        "n_after": new_store.n,
        "by_batch_after": {str(k): int(v)
                           for k, v in sorted(new_pheno["batch"].value_counts().items())},
    }
    return new_store, summary


def run(config: PipelineConfig, batch_id: str) -> dict:
    batch = load_batch(config.batch_dir(batch_id), batch_id)
    admitted_ids = read_json(config.run_dir(batch_id) / "admitted_ids.json")
    admitted = batch.subset(admitted_ids)
    store = load_refpop(config.refpop_dir())
    new_store, summary = merge_into_refpop(store, admitted, batch_id)
    save_refpop(config.refpop_dir(), new_store)

    registry_path = config.refpop_dir() / "registry.json"
    registry = read_json(registry_path) if registry_path.exists() else []
    registry.append({**summary, "merged_at": now_iso()})
    write_json(registry_path, registry)

    write_json(config.run_dir(batch_id) / "merge_summary.json", summary)
    return summary
