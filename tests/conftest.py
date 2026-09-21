"""端到端夹具：在临时目录用默认种子完整复跑「模拟 + G0/G1/G2 三个批次」。

session 级只跑一次（约 15 秒），所有测试读取它的磁盘产物 ——
这同时证明了整条管线可从零确定性复现（与仓库中提交的 data/、artifacts/
使用同一默认种子与参数，产出应一致）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from refpop_agent.config import BATCH_SEQUENCE, PipelineConfig  # noqa: E402
from refpop_agent.graph import run_batch  # noqa: E402
from refpop_agent.simulate import SimConfig, simulate_all  # noqa: E402


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory):
    os.environ.setdefault("REFPOP_LLM", "mock")  # 测试不出网
    root = tmp_path_factory.mktemp("refpop_e2e")
    config = PipelineConfig(
        data_dir=root / "data",
        artifacts_dir=root / "artifacts",
        reports_dir=root / "reports",
    )
    sim = SimConfig()  # 默认种子（与仓库提交数据一致）
    simulate_all(sim, config.data_dir)
    states = {}
    for b in BATCH_SEQUENCE:
        states[b] = run_batch(config, b)
    return {"config": config, "states": states, "sim": sim}
