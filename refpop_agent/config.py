"""管线全局配置：路径、遗传参数、QC 阈值、选配约束。

所有阈值集中在此，便于评审以及生产化时按场内标准调整
（生产化应改为配置文件 + 阈值变更审批流，见 README 生产化清单）。
注意：本项目为演示原型，数据为模拟生成，遗传参数为假设值。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TRAIT = "bw42_g"                      # 表型列名：42日龄体重（克）
TRAIT_LABEL = "42日龄体重 BW42（g）"
BATCH_SEQUENCE = ("G0", "G1", "G2")   # 代际批次处理顺序


def prev_batch(batch_id: str) -> str | None:
    """返回上一代批次号；G0 没有上一代（返回 None）。"""
    i = BATCH_SEQUENCE.index(batch_id)
    return None if i == 0 else BATCH_SEQUENCE[i - 1]


@dataclass
class PipelineConfig:
    """管线运行配置。默认路径相对当前工作目录（CLI 可覆盖）。"""

    # --- 路径 ---
    data_dir: Path = Path("data")
    artifacts_dir: Path = Path("artifacts")
    reports_dir: Path = Path("reports")

    # --- 遗传参数（假设值；生产中应由 REML 估计，见 README）---
    h2: float = 0.30                  # 遗传力，CLI --h2 可配

    # --- QC 门禁阈值 ---
    min_call_rate: float = 0.90       # 个体基因型检出率下限
    dup_concordance: float = 0.995    # 基因型一致率 ≥ 此值判为重复样本
    dup_min_overlap: int = 500        # 重复判定所需最少共同检出位点数
    max_oh_rate: float = 0.01         # 亲子对立纯合率上限（孟德尔一致性）
    min_mendel_informative: int = 200 # 孟德尔校验所需最少可比位点数
    pheno_lo: float = 800.0           # BW42 生理硬下界（g）
    pheno_hi: float = 6000.0          # BW42 生理硬上界（g）
    unit_factor: float = 1000.0       # 单位错误检测因子（kg↔g 千倍关系）
    robust_z_max: float = 6.0         # 界内表型的稳健 z 分数兜底阈值（MAD）

    # --- 选配约束 ---
    max_progeny_inbreeding: float = 0.0625  # 预期后代近交系数上限（≈表亲水平）
    n_sires: int = 30                 # 参与选配的候选公鸡数（GEBV top）
    n_dams: int = 150                 # 参与选配的候选母鸡数
    max_dams_per_sire: int = 8        # 每只公鸡最多分配母鸡数
    pairs_in_report: int = 40         # HTML 报告中展示的配对数（完整表在 CSV）
    top_list_size: int = 20           # GEBV Top-N 清单长度

    # ---------- 派生路径 ----------
    def batch_dir(self, batch_id: str) -> Path:
        return Path(self.data_dir) / "batches" / batch_id

    def refpop_dir(self) -> Path:
        return Path(self.artifacts_dir) / "refpop"

    def models_dir(self) -> Path:
        return Path(self.artifacts_dir) / "models"

    def model_path(self, batch_id: str) -> Path:
        return self.models_dir() / f"model_{batch_id}.npz"

    def model_meta_path(self, batch_id: str) -> Path:
        return self.models_dir() / f"model_{batch_id}.json"

    def run_dir(self, batch_id: str) -> Path:
        return Path(self.artifacts_dir) / "runs" / batch_id

    def history_path(self) -> Path:
        return Path(self.artifacts_dir) / "history.json"

    def report_path(self, batch_id: str) -> Path:
        return Path(self.reports_dir) / f"report_{batch_id}.html"

    def markers_path(self) -> Path:
        return Path(self.data_dir) / "markers.json"

    def truth_path(self, batch_id: str) -> Path:
        """仿真真值（TBV）文件 —— 仅模拟环境存在，生产中没有。"""
        return Path(self.data_dir) / "sim_truth" / f"truth_{batch_id}.csv"
