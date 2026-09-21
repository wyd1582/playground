"""CLI —— 一条命令跑通全流程。

用法：
  python -m refpop_agent.cli run-all              # 无数据则先模拟，再依次处理 G0/G1/G2
  python -m refpop_agent.cli simulate --seed 20260921
  python -m refpop_agent.cli run --batch G1
可配项：--h2 遗传力（默认 0.3）、--llm mock|anthropic（报告摘要模式）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

from .config import BATCH_SEQUENCE, PipelineConfig


def _pipeline_config(args) -> PipelineConfig:
    return PipelineConfig(
        data_dir=Path(args.data_dir),
        artifacts_dir=Path(args.artifacts_dir),
        reports_dir=Path(args.reports_dir),
        h2=args.h2,
    )


def _reset_artifacts(config: PipelineConfig) -> None:
    """只清理管线自己的产物路径（避免误删无关目录）。"""
    for sub in ("refpop", "models", "runs"):
        shutil.rmtree(Path(config.artifacts_dir) / sub, ignore_errors=True)
    hp = config.history_path()
    if hp.exists():
        hp.unlink()
    for b in BATCH_SEQUENCE:
        rp = config.report_path(b)
        if rp.exists():
            rp.unlink()


def _run_one(config: PipelineConfig, batch_id: str) -> dict:
    from .graph import run_batch  # 延迟导入：simulate 子命令无需 langgraph

    t0 = time.time()
    state = run_batch(config, batch_id)
    dt = time.time() - t0
    qc = state["qc"]
    line = (f"[{batch_id}] 到货 {qc['n_arrived']} | 拦截 {qc['n_rejected']} | "
            f"放行 {qc['n_admitted']}")
    if state.get("halted"):
        line += f" | 中止：{state['halted']}"
    else:
        v = state["validation"]
        tag = "前向r" if v["mode"] == "forward" else "CV r"
        line += (f" | 参考群 {state['merge']['n_after']} | {tag}={v['r']:.4f}"
                 f" | 配对 {state['mating']['n_pairs']}")
    line += f" | 报告 {state['report']['report_path']} | {dt:.1f}s"
    print(line, flush=True)
    return state


def cmd_simulate(args) -> None:
    from .simulate import SimConfig, simulate_all

    cfg = SimConfig(seed=args.seed, h2=args.h2)
    summary = simulate_all(cfg, Path(args.data_dir))
    print(f"模拟数据已生成于 {args.data_dir}/（种子 {summary['seed']}，"
          f"注入缺陷 {summary['n_defects']} 个，清单见 {args.data_dir}/DEFECTS.md）",
          flush=True)


def cmd_run(args) -> None:
    if args.llm:
        os.environ["REFPOP_LLM"] = args.llm
    _run_one(_pipeline_config(args), args.batch)


def cmd_run_all(args) -> None:
    if args.llm:
        os.environ["REFPOP_LLM"] = args.llm
    config = _pipeline_config(args)
    if not (Path(args.data_dir) / "batches" / "G0" / "genotypes.npz").exists():
        print("未发现模拟数据，先生成……", flush=True)
        cmd_simulate(args)
    _reset_artifacts(config)  # 幂等：每次 run-all 从空参考群开始，全流程确定性
    for b in BATCH_SEQUENCE:
        _run_one(config, b)
    print(f"完成。3 份报告位于 {args.reports_dir}/report_G*.html；"
          f"中间产物位于 {args.artifacts_dir}/。", flush=True)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="refpop",
        description="参考群更新 Agent 管线（演示原型；数据为模拟生成）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--data-dir", default="data")
        sp.add_argument("--artifacts-dir", default="artifacts")
        sp.add_argument("--reports-dir", default="reports")
        sp.add_argument("--h2", type=float, default=0.30, help="遗传力假设值（默认 0.3）")
        sp.add_argument("--seed", type=int, default=15,
                        help="模拟数据种子（默认 15，选择依据见 README 诚实性声明）")
        sp.add_argument("--llm", choices=["mock", "anthropic"], default=None,
                        help="报告摘要模式（默认沿用环境变量 REFPOP_LLM，未设则 mock）")

    sp = sub.add_parser("simulate", help="生成三个代际到货批次的模拟数据（含注入缺陷）")
    common(sp)
    sp.set_defaults(fn=cmd_simulate)

    sp = sub.add_parser("run", help="处理单个到货批次")
    common(sp)
    sp.add_argument("--batch", required=True, choices=list(BATCH_SEQUENCE))
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("run-all", help="一条命令跑通全流程（缺数据自动模拟 + G0/G1/G2）")
    common(sp)
    sp.set_defaults(fn=cmd_run_all)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
