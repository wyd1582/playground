"""批次数据与参考群存储的读写工具。

设计原则：所有中间产物落盘（npz / csv / json），保证报告中的每个数字
都能从磁盘上的产物复算（诚实性验收项之一）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import TRAIT

MISSING = -1  # int8 基因型缺失哨兵值

PED_COLS = ["id", "sire", "dam", "sex", "generation"]
PHENO_COLS = ["id", TRAIT, "submitted_at"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(o):
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, default=_jsonable),
        encoding="utf-8",
    )


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_table(path: Path, str_cols=("id",)) -> pd.DataFrame:
    """读 CSV；ID 类列强制为字符串，空串保留为 ""（不转 NaN）。"""
    return pd.read_csv(path, dtype={c: str for c in str_cols}, keep_default_na=False)


# ---------------------------------------------------------------- 到货批次


@dataclass
class BatchData:
    """一个到货批次（行序对齐：ids / geno / pheno / ped 顺序一致）。"""

    batch_id: str
    ids: np.ndarray          # <U 字符串数组
    geno: np.ndarray         # int8 (n, m)，缺失 = MISSING
    pheno: pd.DataFrame      # PHENO_COLS
    ped: pd.DataFrame        # PED_COLS
    manifest: dict

    @property
    def n(self) -> int:
        return len(self.ids)

    def subset(self, keep_ids) -> "BatchData":
        keep = set(keep_ids)
        mask = np.array([i in keep for i in self.ids], dtype=bool)
        return BatchData(
            batch_id=self.batch_id,
            ids=self.ids[mask],
            geno=self.geno[mask],
            pheno=self.pheno[mask].reset_index(drop=True),
            ped=self.ped[mask].reset_index(drop=True),
            manifest=self.manifest,
        )


def save_batch(batch_dir: Path, ids, geno, pheno: pd.DataFrame,
               ped: pd.DataFrame, manifest: dict) -> None:
    d = Path(batch_dir)
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / "genotypes.npz",
                        ids=np.asarray(ids, dtype=str),
                        geno=np.asarray(geno, dtype=np.int8))
    pheno.to_csv(d / "phenotypes.csv", index=False)
    ped.to_csv(d / "pedigree.csv", index=False)
    write_json(d / "manifest.json", manifest)


def load_batch(batch_dir: Path, batch_id: str) -> BatchData:
    d = Path(batch_dir)
    z = np.load(d / "genotypes.npz", allow_pickle=False)
    ids = z["ids"].astype(str)
    geno = z["geno"]
    if len(set(ids.tolist())) != len(ids):
        # 到货文件内部 ID 重复属于数据交付事故，直接拒绝整批（生产化清单里有更细的处理）
        raise ValueError(f"批次 {batch_id} 到货文件内部存在重复 ID，无法装载")
    pheno = read_table(d / "phenotypes.csv", str_cols=("id", "submitted_at"))
    ped = read_table(d / "pedigree.csv", str_cols=("id", "sire", "dam", "sex"))
    # 与基因型行序对齐
    pheno = pheno.set_index("id").loc[list(ids)].reset_index()
    ped = ped.set_index("id").loc[list(ids)].reset_index()
    manifest = read_json(d / "manifest.json")
    return BatchData(batch_id, ids, geno, pheno, ped, manifest)


# ---------------------------------------------------------------- 参考群存储


@dataclass
class RefpopStore:
    """累积参考群（基因型 + 表型 + 系谱登记），行序对齐。"""

    ids: np.ndarray
    geno: np.ndarray
    pheno: pd.DataFrame      # id, TRAIT, generation, batch
    ped: pd.DataFrame        # PED_COLS

    @property
    def n(self) -> int:
        return len(self.ids)

    @classmethod
    def empty(cls) -> "RefpopStore":
        return cls(
            ids=np.array([], dtype=str),
            geno=np.zeros((0, 0), dtype=np.int8),
            pheno=pd.DataFrame(columns=["id", TRAIT, "generation", "batch"]),
            ped=pd.DataFrame(columns=PED_COLS),
        )


def load_refpop(refpop_dir: Path) -> RefpopStore:
    d = Path(refpop_dir)
    if not (d / "genotypes.npz").exists():
        return RefpopStore.empty()
    z = np.load(d / "genotypes.npz", allow_pickle=False)
    ids = z["ids"].astype(str)
    geno = z["geno"]
    pheno = read_table(d / "phenotypes.csv", str_cols=("id", "batch"))
    ped = read_table(d / "pedigree.csv", str_cols=("id", "sire", "dam", "sex"))
    pheno = pheno.set_index("id").loc[list(ids)].reset_index()
    ped = ped.set_index("id").loc[list(ids)].reset_index()
    return RefpopStore(ids, geno, pheno, ped)


def save_refpop(refpop_dir: Path, store: RefpopStore) -> None:
    d = Path(refpop_dir)
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / "genotypes.npz",
                        ids=np.asarray(store.ids, dtype=str),
                        geno=np.asarray(store.geno, dtype=np.int8))
    store.pheno.to_csv(d / "phenotypes.csv", index=False)
    store.ped.to_csv(d / "pedigree.csv", index=False)
