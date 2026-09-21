# -*- coding: utf-8 -*-
"""苏州演示台（Task D）—— 把 Task A/B/C 的产物包成一个可点击的演示应用。

启动（一行）：
    streamlit run demo_station.py

约定：
  * 断网可跑：只读本地文件，不发任何网络请求（图表用 Streamlit 内置 Altair 资源）。
  * 上游产物缺失时给出友好提示，绝不崩溃（每个 Tab 外还有兜底异常捕获）。
  * 页面顶部固定声明栏：演示用公开/模拟数据，非客户数据。

上游产物的默认发现方式：从当前目录与本文件所在目录向下递归扫描（跳过 .git 等），
  Task A: results.json（含 results 记录表：dataset/model/protocol/trait/seed/r ...）
  Task B: refpop_agent/（含 cli.py）、data/DEFECTS.md、运行产物 report_G*.html
  Task C: cost_curves.png、imputation_table.csv、BRIEF.md（内含 markdown 表格）
也可在侧边栏指定额外的产物根目录（或设环境变量 DEMO_ARTIFACTS_DIR）。
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------- 启动方式守卫
# 直接 `python demo_station.py` 时给出提示而不是打印一堆 Streamlit 告警。
def _under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return True  # 判断不了就当作在 Streamlit 里，宁可继续渲染


if not _under_streamlit():
    print("请用一行命令启动演示台：\n\n    streamlit run demo_station.py\n")
    sys.exit(0)

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    import altair as alt
except Exception:  # altair 随 streamlit 一起安装，这里只是保险
    alt = None

st.set_page_config(page_title="苏州演示台 · 育种数字化", page_icon="🧬", layout="wide")

# ---------------------------------------------------------------- 顶部固定声明栏
_BANNER_TEXT = "演示用公开/模拟数据，非客户数据"
st.markdown(
    f"""
    <style>
      header[data-testid="stHeader"] {{ display: none; }}
      #MainMenu {{ visibility: hidden; }}
      div.block-container {{ padding-top: 4.2rem; }}
      .demo-banner {{
        position: fixed; top: 0; left: 0; right: 0; z-index: 999990;
        background: #92400e; color: #ffffff; text-align: center;
        padding: 0.45rem 1rem; font-size: 0.95rem; font-weight: 600;
        letter-spacing: 0.08em; box-shadow: 0 1px 4px rgba(0,0,0,0.35);
      }}
    </style>
    <div class="demo-banner">⚠️ {_BANNER_TEXT} ⚠️</div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- 产物发现
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".streamlit",
    ".ipynb_checkpoints", "site-packages", ".cache", ".tox",
}


def _search_roots():
    roots = []
    for cand in [Path.cwd(), Path(__file__).resolve().parent]:
        try:
            cand = cand.resolve()
        except Exception:
            continue
        if cand not in roots:
            roots.append(cand)
    extra = st.session_state.get("extra_root") or os.environ.get("DEMO_ARTIFACTS_DIR", "")
    if extra:
        p = Path(extra).expanduser()
        if p.is_dir():
            p = p.resolve()
            if p not in roots:
                roots.append(p)
    return roots


def discover_artifacts():
    """一次扫描把三个 Task 需要的文件都找齐。返回 {类别: [Path, ...]（按 mtime 新→旧）}。"""
    found = {
        "results_json": [], "summary_md": [], "taska_figs": [],
        "refpop_pkg": [], "defects_md": [], "reports_html": [],
        "cost_png": [], "imput_csv": [], "brief_md": [], "all_csv": [],
    }
    visited = 0
    for root in _search_roots():
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            visited += 1
            if visited > 4000:
                break
            dirnames[:] = [
                d for d in dirnames
                if d not in _SKIP_DIRS and not d.startswith(".")
                and len(Path(dirpath).parts) - base_depth < 6
            ]
            dp = Path(dirpath)
            for fn in filenames:
                low = fn.lower()
                p = dp / fn
                if low == "results.json":
                    found["results_json"].append(p)
                elif low == "summary.md":
                    found["summary_md"].append(p)
                elif low.startswith("fig") and low.endswith(".png"):
                    found["taska_figs"].append(p)
                elif low == "cli.py" and dp.name == "refpop_agent":
                    found["refpop_pkg"].append(dp)
                elif low == "defects.md":
                    found["defects_md"].append(p)
                elif re.match(r"report_g\d+.*\.html$", low):
                    found["reports_html"].append(p)
                elif low.endswith(".png") and "cost" in low and "curve" in low:
                    found["cost_png"].append(p)
                elif low.endswith(".csv") and "imput" in low:
                    found["imput_csv"].append(p)
                elif low.endswith(".md") and low.startswith("brief"):
                    found["brief_md"].append(p)
                if low.endswith(".csv") and len(found["all_csv"]) < 200:
                    found["all_csv"].append(p)
    for key, items in found.items():
        uniq = {}
        for p in items:
            try:
                uniq[str(p)] = p.stat().st_mtime
            except OSError:
                continue
        found[key] = [Path(s) for s, _ in sorted(uniq.items(), key=lambda kv: -kv[1])]
    return found


def _rel(p) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return str(p)


def read_text(p, limit=4_000_000) -> str:
    return Path(p).read_text(encoding="utf-8", errors="replace")[:limit]


def missing_box(what: str, expect: str, how: str):
    st.info(
        f"**尚未找到 {what}**（这是上游产物，不影响其他 Tab）。\n\n"
        f"- 期望文件：`{expect}`\n"
        f"- 怎么补齐：{how}\n"
        f"- 已扫描目录：{'、'.join('`' + str(r) + '`' for r in _search_roots())}"
        f"（可在左侧边栏追加产物根目录后点“重新扫描”）"
    )


# ================================================================ Tab1: Task A
_PROTO_ORDER = ["random", "group", "forward"]
_PROTO_ZH = {"random": "随机5折CV", "group": "留家系代理", "forward": "前向代理"}
_MODEL_ZH = {
    "L0_pedBLUP": "L0 系谱BLUP", "L1_GBLUP": "L1 GBLUP",
    "L2_GBM": "L2 GBM(梯度提升)", "L3_wRidge": "L3 加权岭",
}
_DS_ZH = {"wheat": "wheat（正式实验，599×1278）", "pig": "pig（补充分析，仅 t1 性状）"}


def load_task_a(art):
    """在候选 results.json 里找出符合 Task A 记录结构的那份，返回 (path, meta, DataFrame)。"""
    for p in art["results_json"]:
        try:
            obj = json.loads(read_text(p))
        except Exception:
            continue
        recs = obj.get("results") if isinstance(obj, dict) else obj
        if not isinstance(recs, list) or not recs:
            continue
        rows = []
        for r in recs:
            if not isinstance(r, dict):
                continue
            model, proto = r.get("model"), r.get("protocol")
            if model is None or proto is None:
                continue
            try:
                val = float(r.get("r"))
            except (TypeError, ValueError):
                continue
            rows.append({
                "dataset": str(r.get("dataset", "default")),
                "model": str(model), "protocol": str(proto),
                "trait": str(r.get("trait", "all")), "seed": r.get("seed", 0),
                "r": val,
                "top10": pd.to_numeric(pd.Series([r.get("top10")]), errors="coerce").iloc[0],
            })
        if len(rows) >= 4:
            meta = obj.get("meta", {}) if isinstance(obj, dict) else {}
            return p, meta, pd.DataFrame(rows)
    return None, None, None


def _model_sort_key(m: str):
    mm = re.match(r"L(\d+)", m)
    return (0, int(mm.group(1))) if mm else (1, m)


def _agg_a(df, metric="r"):
    g = df.groupby(["model", "protocol"], as_index=False).agg(
        val=(metric, "mean"), sd=(metric, "std"), n=(metric, "count"))
    g["sd"] = g["sd"].fillna(0.0)
    g["lo"], g["hi"] = g["val"] - g["sd"], g["val"] + g["sd"]
    return g


def _ladder_chart(sub, title, model_order, y_domain, metric_label):
    disp = sub.copy()
    disp["模型"] = disp["model"].map(lambda m: _MODEL_ZH.get(m, m))
    order = [_MODEL_ZH.get(m, m) for m in model_order]
    base = alt.Chart(disp)
    bars = base.mark_bar(size=34, color="#2a78d6", cornerRadiusTopLeft=4,
                         cornerRadiusTopRight=4).encode(
        x=alt.X("模型:N", sort=order, title=None,
                axis=alt.Axis(labelAngle=-30, labelOverlap=False, labelLimit=150,
                              labelFontSize=11)),
        y=alt.Y("val:Q", title=metric_label, scale=alt.Scale(domain=y_domain)),
        tooltip=[alt.Tooltip("模型:N"), alt.Tooltip("val:Q", format=".3f", title=metric_label),
                 alt.Tooltip("sd:Q", format=".3f", title="std"), alt.Tooltip("n:Q", title="单元数")],
    )
    err = base.mark_rule(strokeWidth=2, color="#52514e").encode(
        x=alt.X("模型:N", sort=order), y="lo:Q", y2="hi:Q")
    txt = base.mark_text(dy=-8, fontSize=11).encode(
        x=alt.X("模型:N", sort=order), y="hi:Q", text=alt.Text("val:Q", format=".3f"))
    return (bars + err + txt).properties(title=title, height=300)


def _fmt(v, nd=3):
    return ("{:." + str(nd) + "f}").format(v)


def _interpret_a(agg_r, dataset):
    """按固定模板从聚合数字生成中文解读（非 LLM）。返回 (段落列表, 哨兵通过?, 哨兵明细)。"""
    piv = agg_r.pivot(index="model", columns="protocol", values="val")
    paras, sentinel_rows, sentinel_ok = [], [], True
    for m in piv.index:
        rnd = piv.at[m, "random"] if "random" in piv.columns else None
        grp = piv.at[m, "group"] if "group" in piv.columns else None
        if rnd is not None and grp is not None and pd.notna(rnd) and pd.notna(grp):
            ok = grp <= rnd + 0.01
            sentinel_ok &= ok
            sentinel_rows.append(
                f"{'✅' if ok else '❌'} {_MODEL_ZH.get(m, m)}：留家系 {_fmt(grp)} vs 随机CV {_fmt(rnd)}")

    def cell(m, p):
        try:
            v = piv.at[m, p]
            return float(v) if pd.notna(v) else None
        except (KeyError, ValueError):
            return None

    l0r, l1r = cell("L0_pedBLUP", "random"), cell("L1_GBLUP", "random")
    l0g, l1g = cell("L0_pedBLUP", "group"), cell("L1_GBLUP", "group")
    if l0r is not None and l1r is not None:
        s = (f"**标记 vs 系谱**：随机CV 下 GBLUP r={_fmt(l1r)} vs 系谱BLUP r={_fmt(l0r)}"
             f"（Δ={l1r - l0r:+.3f}）")
        if l0g is not None and l1g is not None:
            s += f"；换到留家系代理仍为 {_fmt(l1g)} vs {_fmt(l0g)}（Δ={l1g - l0g:+.3f}）"
        s += ("。在本数据与口径下，基因组标记相对系谱是真实增益。" if l1r > l0r
              else "。在本数据与口径下，未见标记相对系谱的增益。")
        paras.append(s)
    l2r, l2g, l2f = cell("L2_GBM", "random"), cell("L2_GBM", "group"), cell("L2_GBM", "forward")
    l1g2, l1f = cell("L1_GBLUP", "group"), cell("L1_GBLUP", "forward")
    if l1r is not None and l2r is not None:
        lead_rnd = l2r > l1r
        hard_pairs = [(l2g, l1g2, "留家系代理"), (l2f, l1f, "前向代理")]
        reversed_in = [name for a, b, name in hard_pairs
                       if a is not None and b is not None and a < b]
        if lead_rnd and reversed_in:
            paras.append(
                f"**非线性 ML vs GBLUP**：GBM 只在随机CV领先（{_fmt(l2r)} vs {_fmt(l1r)}），"
                f"换到{'与'.join(reversed_in)}即反转——它的“优势”与随机CV可利用的家系结构泄漏同消同长，"
                f"在本数据与口径下未稳健打败 GBLUP。")
        elif lead_rnd:
            paras.append(
                f"**非线性 ML vs GBLUP**：GBM 在各口径均不低于 GBLUP（随机CV {_fmt(l2r)} vs {_fmt(l1r)}），"
                f"在本数据上呈现稳健优势——建议核对口径设置后再下结论。")
        else:
            paras.append(
                f"**非线性 ML vs GBLUP**：GBM 连随机CV都未超过 GBLUP（{_fmt(l2r)} vs {_fmt(l1r)}），"
                f"在本数据与口径下无优势。")
    both = [m for m in piv.index if
            cell(m, "random") is not None and cell(m, "group") is not None]
    if both:
        gap_proto = sum(cell(m, "random") - cell(m, "group") for m in both) / len(both)
        rnd_vals = [cell(m, "random") for m in both]
        gap_model = max(rnd_vals) - min(rnd_vals)
        paras.append(
            f"**口径的影响有多大**：随机CV相对留家系代理平均虚高 Δr≈{gap_proto:+.3f}，"
            f"而随机CV下模型间最大差距仅 {_fmt(gap_model)}——先问“评估口径对不对”，再问“模型新不新”。")
    if "forward" in piv.columns:
        fwd = piv["forward"].dropna()
        if len(fwd):
            bm = fwd.idxmax()
            paras.append(
                f"**最难口径（前向代理）** 上表现最好的是 {_MODEL_ZH.get(bm, bm)}"
                f"（r={_fmt(fwd.max())}），这更接近“老代训练→新代预测”的真实使用姿势。")
    if dataset == "pig":
        paras.append(
            "**量级提醒**：pig 为补充分析（仅 t1 性状、无系谱，r≈0.05–0.09 属弱信号），"
            "只能佐证方向、不能当主结论——正式结论看 wheat。")
    return paras, sentinel_ok, sentinel_rows


def render_tab1(art):
    st.subheader("LLM/ML vs BLUP —— 实验阶梯（Task A）")
    path, meta, df = load_task_a(art)
    if df is None:
        missing_box(
            "Task A 的 results.json", "results.json（内含 results 记录表）",
            "跑完 Task A（猪数据实验）后把 `genomic-selection-pig/` 目录放进本目录，"
            "或合并 Task A 的分支。")
        return
    st.caption(f"数据源：`{_rel(path)}`（阶梯图由 results.json 现场重算，非贴图）")

    datasets = sorted(df["dataset"].unique(), key=lambda d: (d != "wheat", d))
    c1, c2, c3 = st.columns([2, 2, 1])
    ds = c1.radio("数据集", datasets, format_func=lambda d: _DS_ZH.get(d, d), horizontal=True)
    sub_all = df[df["dataset"] == ds]
    traits = sorted(sub_all["trait"].unique())
    trait_sel = c2.selectbox("性状", ["全部（平均）"] + traits) if len(traits) > 1 else "全部（平均）"
    metric_opts = ["r"] + (["top10"] if sub_all["top10"].notna().any() else [])
    metric = c3.selectbox("指标", metric_opts,
                          format_func=lambda m: {"r": "预测精度 r", "top10": "Top-10% 命中率"}[m])
    sub = sub_all if trait_sel == "全部（平均）" else sub_all[sub_all["trait"] == trait_sel]
    if metric == "top10":
        sub = sub[sub["top10"].notna()]
    agg = _agg_a(sub, metric)
    model_order = sorted(agg["model"].unique(), key=_model_sort_key)
    metric_label = "预测精度 r" if metric == "r" else "Top-10% 命中率"

    protos = [p for p in _PROTO_ORDER if p in set(agg["protocol"])] or sorted(set(agg["protocol"]))
    pad = 0.05
    y_domain = [min(0.0, float(agg["lo"].min())) - pad, float(agg["hi"].max()) + pad]
    if alt is None:
        st.dataframe(agg, width="stretch")
    else:
        cols = st.columns(len(protos))
        for col, proto in zip(cols, protos):
            with col:
                st.altair_chart(
                    _ladder_chart(agg[agg["protocol"] == proto],
                                  _PROTO_ZH.get(proto, proto), model_order, y_domain, metric_label),
                    width="stretch")
        st.caption("误差线为 ±1 std（跨性状×随机种子单元）；三个分面共用同一 y 轴，方便看“口径虚高”。")

    st.markdown("#### 自动解读（固定模板填充，非 LLM 生成）")
    agg_r = _agg_a(sub if metric == "r" else
                   (sub_all if trait_sel == "全部（平均）" else sub_all[sub_all["trait"] == trait_sel]), "r")
    paras, sentinel_ok, sentinel_rows = _interpret_a(agg_r, ds)
    if sentinel_rows:
        if sentinel_ok:
            st.success("**泄漏哨兵通过**：各模型留家系代理 r 均未高于随机CV——评估口径无泄漏迹象。\n\n"
                       + "\n".join("- " + s for s in sentinel_rows))
        else:
            st.error("**泄漏哨兵未通过**：存在“留家系 r 高于随机CV”的单元。按验收清单，此时 Task A 的"
                     "全部数字需复核/作废，以下解读仅供排查参考。\n\n"
                     + "\n".join("- " + s for s in sentinel_rows))
    for s in paras:
        st.markdown("- " + s)
    st.caption("解读为模板+results.json 数字自动填充；数据为公开数据集，任何数字不外推到生产群体。"
               "阶梯未含 L4（纯 LLM 直接建模基因型）——Task A 的论证是当前证据不支持，"
               "LLM 更合理的切入是为 L3 提供功能先验权重（详见 SUMMARY）。")

    with st.expander("Task A 原始产物（SUMMARY.md / 原图 / meta）"):
        if art["summary_md"]:
            st.markdown(read_text(art["summary_md"][0], 60_000))
        for fig in art["taska_figs"][:2]:
            st.image(str(fig), caption=_rel(fig), width="stretch")
        if meta:
            st.json(meta, expanded=False)


# ================================================================ Tab2: Task B
_NODES = [("qc", "QC 门禁"), ("merge", "合并参考群"), ("retrain", "重训 GBLUP"),
          ("validate", "前向验证"), ("mating", "选配建议"), ("report", "输出报告")]
_NODE_KEYS = {
    "qc": ["qc", "质控", "门禁"], "merge": ["merge", "合并"],
    "retrain": ["retrain", "重训", "train"], "validate": ["validat", "验证"],
    "mating": ["mating", "选配", "近交"], "report": ["report", "报告"],
}
_QC_LINE = re.compile(
    r"(拦截|剔除|排除|淘汰|冲突|重复|缺陷|不合格|reject|fail|remov|exclud|duplicat|call\s*_?rate|conflict|flag|drop)",
    re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _detect_node(line: str, current: int) -> int:
    low = line.lower()
    for i, (key, _) in enumerate(_NODES):
        if i > current and any(k in low for k in _NODE_KEYS[key]):
            return i
    return current


def _node_line(current: int, running: bool, ok=None) -> str:
    parts = []
    for i, (_, label) in enumerate(_NODES):
        if running:
            icon = "✅" if i < current else ("🔄" if i == current else "⚪")
        elif ok:
            icon = "✅"
        else:
            icon = "✅" if i < current else ("❌" if i == current else "⚪")
        parts.append(f"{icon} {label}")
    return "　→　".join(parts)


def _probe_cli(pkg_dir: Path) -> str:
    key = f"bhelp::{pkg_dir}"
    if key not in st.session_state:
        try:
            out = subprocess.run(
                [sys.executable, "-m", "refpop_agent.cli", "--help"],
                cwd=str(pkg_dir.parent), capture_output=True, text=True, timeout=30,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            st.session_state[key] = (out.stdout or "") + (out.stderr or "")
        except Exception as e:
            st.session_state[key] = f"(探测 CLI 用法失败：{e})"
    return st.session_state[key]


def _default_cmd(help_text: str) -> str:
    for flag in ["--generation", "--batch", "--gen"]:
        if flag in help_text:
            return f"{{python}} -m refpop_agent.cli {flag} {{gen}}"
    return "{python} -m refpop_agent.cli {gen}"


def _embed_report(path: Path):
    st.markdown(f"**内嵌报告**：`{_rel(path)}`")
    embedded = False
    if hasattr(st, "iframe"):
        try:
            st.iframe(Path(path).resolve(), height=820)
            embedded = True
        except Exception:
            embedded = False
    if not embedded:
        try:
            components.html(read_text(path), height=820, scrolling=True)
        except Exception as e:
            st.warning(f"内嵌渲染失败（{e}），可下载后用浏览器打开。")
    try:
        st.download_button("下载该报告 HTML", data=read_text(path),
                           file_name=Path(path).name, mime="text/html",
                           key=f"dl::{path}::{Path(path).stat().st_mtime}")
    except Exception:
        pass


def _run_pipeline(cmd: str, workdir: Path, gen: str):
    st.markdown("##### 节点进度")
    prog_ph, log_ph = st.empty(), st.empty()
    current, lines, timed_out = -1, [], False
    t0 = time.time()
    prog_ph.markdown(_node_line(-1, running=True))
    try:
        proc = subprocess.Popen(
            shlex.split(cmd), cwd=str(workdir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    except Exception as e:
        st.error(f"命令无法启动：`{cmd}`\n\n{e}\n\n请在上方修改命令后重试。")
        return
    while True:
        line = proc.stdout.readline()
        if line == "" and proc.poll() is not None:
            break
        if line:
            line = _ANSI.sub("", line.rstrip("\n"))
            lines.append(line)
            current = _detect_node(line, current)
            prog_ph.markdown(_node_line(current, running=True))
            log_ph.code("\n".join(lines[-22:]) or "…", language=None)
        if time.time() - t0 > 1500:
            proc.kill()
            timed_out = True
            break
    rc = proc.wait()
    st.session_state["b_last"] = {
        "gen": gen, "cmd": cmd, "rc": rc, "timed_out": timed_out,
        "t0": t0, "sec": time.time() - t0, "lines": lines[-800:], "current": current,
    }
    prog_ph.empty()
    log_ph.empty()


def _render_b_result(art):
    res = st.session_state.get("b_last")
    if not res:
        return
    ok = (res["rc"] == 0) and not res["timed_out"]
    st.markdown(_node_line(res["current"], running=False, ok=ok))
    if ok:
        st.success(f"代际批次 **{res['gen']}** 运行完成（耗时 {res['sec']:.0f} 秒，退出码 0）。")
    elif res["timed_out"]:
        st.error("运行超时（>25 分钟）已终止——请检查命令或直接在终端排查后重试。")
    else:
        st.error(f"运行失败（退出码 {res['rc']}）。日志最后几行：")
        st.code("\n".join(res["lines"][-12:]) or "(无输出)", language=None)
    qc_lines = [l for l in res["lines"] if _QC_LINE.search(l)]
    if qc_lines:
        st.markdown("##### QC 拦截明细（来自管线日志）")
        st.code("\n".join(qc_lines[:80]), language=None)
    fresh_qc = [p for p in discover_artifacts()["all_csv"]
                if "qc" in p.name.lower() and p.stat().st_mtime >= res["t0"] - 1]
    if fresh_qc:
        try:
            st.markdown(f"##### QC 结构化产物：`{_rel(fresh_qc[0])}`")
            st.dataframe(pd.read_csv(fresh_qc[0]), width="stretch")
        except Exception:
            pass
    if ok:
        reports = [p for p in discover_artifacts()["reports_html"] if res["gen"].lower() in p.name.lower()]
        reports = reports or discover_artifacts()["reports_html"]
        if reports:
            _embed_report(reports[0])
        else:
            st.warning("管线跑完了，但没找到 report_G*.html——请确认 Task B 的报告输出路径。")


def render_tab2(art):
    st.subheader("参考群更新 Agent —— 跑一个代际批次（Task B）")
    pkgs = art["refpop_pkg"]
    if not pkgs:
        missing_box(
            "Task B 的管线代码 refpop_agent/", "refpop_agent/cli.py（及 data/ 模拟批次）",
            "跑完 Task B 后把 `refpop_agent/` 与 `data/` 放进本目录，或合并 Task B 的分支。")
    else:
        pkg = pkgs[0]
        st.caption(f"管线包：`{_rel(pkg)}`（新一代数据到达 → QC门禁 → 合并参考群 → 重训GBLUP → 验证 → 选配建议 → 报告）")
        help_text = _probe_cli(pkg)
        c1, c2 = st.columns([1, 3])
        gen = c1.selectbox("代际批次", ["G1", "G2"])
        tmpl = c2.text_input("运行命令（可改；{python}/{gen} 会被替换）",
                             value=_default_cmd(help_text))
        cmd = tmpl.replace("{python}", shlex.quote(sys.executable)).replace("{gen}", gen)
        st.caption(f"实际执行：`{cmd}`　·　工作目录：`{_rel(pkg.parent)}`")
        with st.expander("CLI 用法探测（--help 原文）"):
            st.code(help_text or "(无输出)", language=None)
        if st.button(f"▶ 运行代际批次 {gen}", type="primary"):
            _run_pipeline(cmd, pkg.parent, gen)
        _render_b_result(art)
        if art["defects_md"]:
            with st.expander("对照：DEFECTS.md 注入缺陷清单（验收=QC 100% 拦截）"):
                st.markdown(read_text(art["defects_md"][0], 40_000))

    others = art["reports_html"]
    if others:
        st.markdown("---")
        st.markdown("##### 直接查看已有报告（不运行管线）")
        sel = st.selectbox("选择报告", others, format_func=_rel, key="b_browse")
        if st.button("查看该报告"):
            st.session_state["b_view"] = str(sel)
        if st.session_state.get("b_view"):
            p = Path(st.session_state["b_view"])
            if p.exists():
                _embed_report(p)
    elif pkgs:
        st.caption("提示：还没有任何 report_G*.html——点上面的按钮跑一个代际批次即可生成。")


# ================================================================ Tab3: Task C
_NUM = re.compile(r"[-+]?\d+(?:[,_]\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _to_num(cell):
    if isinstance(cell, (int, float)):
        return float(cell)
    m = _NUM.search(str(cell).replace("，", ","))
    return float(m.group().replace(",", "").replace("_", "")) if m else None


def _mean_std(cell):
    s = str(cell)
    if "±" in s:
        a, b = s.split("±", 1)
        return _to_num(a), _to_num(b)
    return _to_num(s), None


def parse_md_tables(text: str):
    tables, lines, i = [], text.splitlines(), 0
    sep = re.compile(r"^\s*\|?\s*:?-{2,}.*\|")
    while i < len(lines) - 1:
        if "|" in lines[i] and sep.match(lines[i + 1]):
            header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                cells = (cells + [""] * len(header))[:len(header)]
                rows.append(cells)
                j += 1
            if rows:
                tables.append(pd.DataFrame(rows, columns=header))
            i = j
        else:
            i += 1
    return tables


_DENS_HINT = re.compile(r"densit|marker|snp|标记|密度|位点", re.I)
_R_HINT = re.compile(r"(^|_|\b)(r|acc|accuracy|精度|pearson|corr)", re.I)
_FULL_HINT = re.compile(r"全量|full|all", re.I)


def sniff_density_curve(df: pd.DataFrame):
    """从任意 DataFrame 里找 (密度列, r列)，返回标准化曲线 DataFrame 或 None。"""
    cols = list(df.columns)
    best = None
    for dc in cols:
        vals = [(_to_num(v), _FULL_HINT.search(str(v)) is not None) for v in df[dc]]
        nums = [v for v, _ in vals if v is not None]
        fulls = sum(1 for v, f in vals if f)
        if len(nums) + fulls < 3 or len(nums) < 2:
            continue
        if not all(v >= 1 and abs(v - round(v)) < 1e-6 for v in nums):
            continue
        if max(nums) < 150 or len(set(nums)) < 2:
            continue
        for rc in cols:
            if rc == dc:
                continue
            ms = [_mean_std(v) for v in df[rc]]
            rs = [m for m, _ in ms if m is not None]
            if len(rs) < max(2, int(0.6 * len(df))):
                continue
            if not all(-1.05 <= v <= 1.05 for v in rs):
                continue
            score = (2 if _DENS_HINT.search(str(dc)) else 0) + (2 if _R_HINT.search(str(rc)) else 0) + len(rs) / 10
            if best is None or score > best[0]:
                best = (score, dc, rc)
    if best is None:
        return None
    _, dc, rc = best
    rows = []
    for _, row in df.iterrows():
        d = _to_num(row[dc])
        mean, sd = _mean_std(row[rc])
        if mean is None:
            continue
        label = str(row[dc]).strip()
        if d is None and not _FULL_HINT.search(label):
            continue
        rows.append({"density_label": label, "density_num": d, "r_mean": mean, "r_std": sd})
    if len(rows) < 3:
        return None
    out = pd.DataFrame(rows)
    out = out.groupby(["density_label"], as_index=False).agg(
        density_num=("density_num", "mean"), r_mean=("r_mean", "mean"), r_std=("r_std", "mean"))
    return out.sort_values("density_num", na_position="last").reset_index(drop=True)


def load_density_curve(art):
    """依次尝试：名字像密度曲线的 csv → 任意 csv 嗅探 → BRIEF.md 里的 markdown 表。"""
    named = [p for p in art["all_csv"] if re.search(r"densit|curve|e1", p.name, re.I)]
    near = set()
    for anchor in art["cost_png"][:1] + art["brief_md"][:1]:
        near.add(anchor.parent)
    nearby = [p for p in art["all_csv"] if p.parent in near]
    for p in named + nearby:
        try:
            got = sniff_density_curve(pd.read_csv(p))
        except Exception:
            continue
        if got is not None:
            return got, f"csv：`{_rel(p)}`"
    for p in art["brief_md"][:2]:
        for t in parse_md_tables(read_text(p)):
            got = sniff_density_curve(t)
            if got is not None:
                return got, f"BRIEF 表格：`{_rel(p)}`"
    return None, None


def render_tab3(art):
    st.subheader("芯片 SKU 经济学 —— 密度曲线 / 填补 / 成本（Task C）")
    have_any = bool(art["cost_png"] or art["brief_md"] or art["imput_csv"])
    if not have_any:
        missing_box(
            "Task C 的产物", "cost_curves.png、imputation_table.csv、BRIEF.md",
            "跑完 Task C（芯片降本双曲线）后把三件产物放进本目录，或合并 Task C 的分支。")
        return
    if art["cost_png"]:
        st.image(str(art["cost_png"][0]),
                 caption=f"两条曲线：标记密度-精度 & 掩码-填补精度（{_rel(art['cost_png'][0])}）",
                 width="stretch")
    else:
        missing_box("Task C 的曲线图", "cost_curves.png", "确认 Task C 的图输出路径后重新扫描。")

    curve, src = load_density_curve(art)
    st.markdown("#### 目标精度 → 最低标记密度建议")
    if curve is None:
        st.info("**尚未找到密度-精度曲线的数值数据**（支持任意含“密度列+r列”的 csv，"
                "或 BRIEF.md 内的 markdown 表格）。曲线数据落地后此处滑块自动生效。")
    else:
        st.caption(f"曲线数据源：{src}（推荐只在实测密度档内取最小满足档，不做插值/外推）")
        finite = curve.dropna(subset=["density_num"]).sort_values("density_num")
        full_row = curve.iloc[curve["density_num"].fillna(float("inf")).argmax()]
        full_r = float(full_row["r_mean"])
        lo = float(curve["r_mean"].min())
        hi = float(curve["r_mean"].max())
        if hi - lo < 0.02:
            st.dataframe(curve, width="stretch")
            st.warning("曲线上各密度档精度几乎无差别，滑块建议意义不大——直接看上表。")
        else:
            lo_r, hi_r = round(lo, 2), round(hi, 2)
            if lo_r >= hi_r:
                lo_r, hi_r = round(lo - 0.01, 2), round(hi + 0.01, 2)
            default = min(max(round(0.95 * hi, 2), lo_r), hi_r)
            target = st.slider("目标预测精度 r", min_value=lo_r, max_value=hi_r,
                               value=default, step=0.01)
            meet = finite[finite["r_mean"] >= target]
            if len(meet):
                rec = meet.iloc[0]
                pct = 100.0 * rec["r_mean"] / full_r if full_r else float("nan")
                st.success(
                    f"**建议最低标记密度：{rec['density_label']}**（实测 r={_fmt(rec['r_mean'])}，"
                    f"≈全量精度的 {pct:.0f}%）。在本数据上，这是满足目标 r≥{target:.2f} 的最小实测档。")
            elif full_r >= target:
                st.warning(f"各低密度档均不足，需 **{full_row['density_label']}**（r={_fmt(full_r)}）。")
            else:
                st.warning(f"目标 r≥{target:.2f} 在本数据上不可达——最高档 "
                           f"{full_row['density_label']} 也仅 r={_fmt(full_r)}。请降低目标。")
            if alt is not None and len(finite) >= 2:
                cd = finite.copy()
                cd["density_num"] = cd["density_num"].astype(float)
                line = alt.Chart(cd).mark_line(
                    point=alt.OverlayMarkDef(size=70, color="#2a78d6"),
                    color="#2a78d6", strokeWidth=2).encode(
                    x=alt.X("density_num:Q", scale=alt.Scale(type="log"),
                            title="标记密度（个，log 刻度）"),
                    y=alt.Y("r_mean:Q", title="预测精度 r",
                            scale=alt.Scale(domain=[min(0, lo) - 0.05, hi + 0.05])),
                    tooltip=[alt.Tooltip("density_label:N", title="密度档"),
                             alt.Tooltip("r_mean:Q", format=".3f")])
                rule = alt.Chart(pd.DataFrame({"y": [target]})).mark_rule(
                    strokeDash=[6, 4], color="#52514e", strokeWidth=1.5).encode(y="y:Q")
                st.altair_chart((line + rule).properties(height=280), width="stretch")

    st.markdown("#### 成本与填补明细")
    shown_tables = 0
    for p in art["brief_md"][:1]:
        for t in parse_md_tables(read_text(p)):
            names = " ".join(map(str, t.columns))
            is_cost = re.search(r"成本|cost|价格|price|sku|每单位", names, re.I)
            st.dataframe(t, width="stretch")
            st.caption(("成本对比表（成本为假设占位值，真实价格待客户数据）—— " if is_cost else "BRIEF 表格 —— ")
                       + f"来自 `{_rel(p)}`")
            shown_tables += 1
    if art["imput_csv"]:
        try:
            st.dataframe(pd.read_csv(art["imput_csv"][0]), width="stretch")
            st.caption(f"E2 填补实验结果 —— `{_rel(art['imput_csv'][0])}`")
            shown_tables += 1
        except Exception as e:
            st.warning(f"imputation_table.csv 读取失败：{e}")
    if not shown_tables:
        missing_box("Task C 的表格", "imputation_table.csv / BRIEF.md 内表格",
                    "确认 Task C 产物路径后重新扫描。")
    if art["brief_md"]:
        with st.expander("《低密度SKU可行性简报》BRIEF.md 全文"):
            st.markdown(read_text(art["brief_md"][0], 80_000))
    st.caption("所有成本数字均为假设占位（如高密=100、低密=30 的归一化假设）；"
               "结论句式限定为“在本数据上”，不做外推承诺。")


# ================================================================ 页面组装
def _sidebar(art):
    with st.sidebar:
        st.markdown("### 🧬 苏州演示台")
        st.caption(_BANNER_TEXT + "。启动：`streamlit run demo_station.py`（断网可跑）")
        st.markdown("#### 产物自检")
        def row(okay, label, path=None):
            mark = "✅" if okay else "✗"
            tail = f"　`{_rel(path)}`" if (okay and path is not None) else ""
            st.markdown(f"- {mark} {label}{tail}")
        a_path, _, a_df = load_task_a(art)
        row(a_df is not None, "Task A results.json", a_path)
        row(bool(art["refpop_pkg"]), "Task B refpop_agent/",
            art["refpop_pkg"][0] if art["refpop_pkg"] else None)
        row(bool(art["reports_html"]), f"Task B 报告 ×{len(art['reports_html'])}",
            art["reports_html"][0] if art["reports_html"] else None)
        row(bool(art["cost_png"]), "Task C cost_curves.png",
            art["cost_png"][0] if art["cost_png"] else None)
        row(bool(art["imput_csv"]), "Task C imputation_table.csv",
            art["imput_csv"][0] if art["imput_csv"] else None)
        row(bool(art["brief_md"]), "Task C BRIEF.md",
            art["brief_md"][0] if art["brief_md"] else None)
        if st.button("🔄 重新扫描产物"):
            st.rerun()
        with st.expander("追加产物根目录"):
            st.text_input("目录路径（也可设环境变量 DEMO_ARTIFACTS_DIR）", key="extra_root")
            extra = st.session_state.get("extra_root")
            if extra and not Path(extra).expanduser().is_dir():
                st.warning("该路径不存在或不是目录，已忽略。")


def _safe(render_fn, art):
    try:
        render_fn(art)
    except Exception:
        st.error("该 Tab 渲染时出现异常（已捕获，不影响其他 Tab）。多半是上游产物格式与预期不同，"
                 "可把下面的堆栈发给工程侧。")
        with st.expander("异常堆栈"):
            st.code(traceback.format_exc(), language=None)


def main():
    art = discover_artifacts()
    _sidebar(art)
    st.title("育种数字化 · 三件套演示")
    tab1, tab2, tab3 = st.tabs(["① LLM vs BLUP", "② 参考群更新 Agent", "③ 芯片 SKU 经济学"])
    with tab1:
        _safe(render_tab1, art)
    with tab2:
        _safe(render_tab2, art)
    with tab3:
        _safe(render_tab3, art)


main()
