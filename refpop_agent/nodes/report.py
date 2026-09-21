"""报告节点 —— 汇总各节点磁盘产物，渲染单文件 HTML 报告（report_G{n}.html）。

诚实性设计：
- 本节点只读取其他节点已落盘的产物（qc_report.json / merge_summary.json /
  validation.json / mating_summary.json / candidates.csv / …），不重新计算任何
  指标 —— 报告里的每个数字都能在磁盘产物中找到并复算（tests/test_report.py 断言）。
- 页面顶部与页脚均明确标注"演示原型 · 模拟数据 · 遗传参数为假设值"。
- 中文摘要段由 llm.summarize 生成：默认 Mock 模板，可切真模型；无论哪种模式，
  报告都会标注来源与回退情况。
"""

from __future__ import annotations

import html as _html
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PipelineConfig, TRAIT_LABEL
from ..io_utils import now_iso, read_json, write_json
from ..llm import summarize
from .qc import REASON_LABELS

SEX_CN = {"M": "公", "F": "母"}


def esc(x) -> str:
    return _html.escape(str(x), quote=True)


def _category_of(code: str) -> str:
    if code == "LOW_CALL_RATE":
        return "低检出率"
    if code.startswith("DUP"):
        return "重复送检"
    if code.startswith("PHENO"):
        return "表型异常"
    return "系谱冲突"


def _load(path: Path):
    return read_json(path) if Path(path).exists() else None


def _load_csv(path: Path):
    return pd.read_csv(path, dtype={"id": str, "sire": str, "dam": str},
                       keep_default_na=False) if Path(path).exists() else None


# ------------------------------------------------------------------ SVG 图表


def _rounded_top_bar(x, y, w, h, r=3.0):
    """底边贴基线、仅顶端圆角的柱形 path（dataviz 规范：数据端圆角）。"""
    r = min(r, w / 2, max(h, 0.1))
    return (f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"L{x + w:.1f},{y + h:.1f} Z")


def _rounded_right_bar(x, y, w, h, r=3.0):
    r = min(r, h / 2, max(w, 0.1))
    return (f"M{x:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"L{x + w:.1f},{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} "
            f"L{x:.1f},{y + h:.1f} Z")


def _svg_r_trend(history: list[dict]) -> str:
    """跨代验证 r 趋势：实心点=前向验证，空心点=G0 交叉验证基线（口径不同）。"""
    if not history:
        return ""
    W, H, L, R, T, B = 560, 236, 48, 18, 16, 40
    pw, ph = W - L - R, H - T - B
    rs = [h["r"] for h in history]
    ymax = max(0.6, float(np.ceil((max(rs) + 0.07) * 10) / 10))
    xs = [L + pw * (i + 0.5) / len(history) for i in range(len(history))]

    def ypix(v):
        return T + ph * (1 - v / ymax)

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="验证 r 趋势" '
             'style="width:100%;max-width:620px;height:auto">']
    tick = 0.0
    while tick <= ymax + 1e-9:
        y = ypix(tick)
        parts.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{L - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="ax">{tick:.1f}</text>')
        tick = round(tick + 0.2, 10)
    parts.append(f'<line x1="{L}" y1="{ypix(0):.1f}" x2="{W - R}" y2="{ypix(0):.1f}" class="axis"/>')

    fwd = [(x, h) for x, h in zip(xs, history) if h["mode"] == "forward"]
    if len(fwd) >= 2:
        pts = " ".join(f"{x:.1f},{ypix(h['r']):.1f}" for x, h in fwd)
        parts.append(f'<polyline points="{pts}" class="trend"/>')
    for x, h in zip(xs, history):
        y = ypix(h["r"])
        cls = "pt" if h["mode"] == "forward" else "pt-cv"
        mode_cn = "前向验证" if h["mode"] == "forward" else "5折交叉验证基线"
        tip = (f"{h['batch_id']} · {mode_cn} · r={h['r']:.3f} · 验证 n={h['n_val']}"
               + (f" · 训练 n={h['train_n']}" if h.get("train_n") else ""))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" class="{cls}"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="14" fill="transparent" '
                     f'data-tip="{esc(tip)}"/>')
        parts.append(f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" class="lbl">{h["r"]:.3f}</text>')
        parts.append(f'<text x="{x:.1f}" y="{H - 22}" text-anchor="middle" class="ax">{esc(h["batch_id"])}</text>')
        parts.append(f'<text x="{x:.1f}" y="{H - 8}" text-anchor="middle" class="ax">参考群 {h["refpop_n_after"]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_hist(a: np.ndarray, b: np.ndarray) -> str:
    """GEBV 分布：本批次 vs 参考群全体（按占比 % 归一，两组可比）。"""
    if a is None or b is None or len(a) == 0 or len(b) == 0:
        return ""
    lo = float(min(a.min(), b.min()))
    hi = float(max(a.max(), b.max()))
    edges = np.linspace(lo, hi, 15)
    pa = np.histogram(a, bins=edges)[0] / len(a) * 100.0
    pb = np.histogram(b, bins=edges)[0] / len(b) * 100.0
    W, H, L, R, T, B = 560, 226, 44, 14, 12, 34
    pw, ph = W - L - R, H - T - B
    ymax = max(1.0, float(np.ceil(max(pa.max(), pb.max()) / 5) * 5))
    slot = pw / 14
    bw = (slot - 6) / 2  # 组内两根柱，柱间与组间均留 2px 以上空隙

    def ypix(v):
        return T + ph * (1 - v / ymax)

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="GEBV 分布对比" '
             'style="width:100%;max-width:620px;height:auto">']
    for tick in np.arange(0, ymax + 1e-9, max(5, ymax // 3 // 5 * 5 or 5)):
        y = ypix(tick)
        parts.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{L - 6}" y="{y + 3.5:.1f}" text-anchor="end" class="ax">{tick:.0f}%</text>')
    for i in range(14):
        x0 = L + i * slot + 1
        rng = f"[{edges[i]:.0f}, {edges[i + 1]:.0f}) g"
        for j, (p, cls, nm) in enumerate(((pa[i], "b1", "本批次"), (pb[i], "b2", "参考群全体"))):
            h = ph * p / ymax
            if h <= 0.1:
                continue
            x = x0 + j * (bw + 2)
            parts.append(f'<path d="{_rounded_top_bar(x, ypix(p), bw, h)}" class="bar {cls}" '
                         f'data-tip="{esc(f"{nm} · GEBV {rng} · {p:.1f}%")}"/>')
    parts.append(f'<line x1="{L}" y1="{ypix(0):.1f}" x2="{W - R}" y2="{ypix(0):.1f}" class="axis"/>')
    for v in (edges[0], edges[7], edges[14]):
        x = L + pw * (v - lo) / (hi - lo)
        parts.append(f'<text x="{x:.1f}" y="{H - 8}" text-anchor="middle" class="ax">{v:.0f}</text>')
    parts.append(f'<text x="{W - R}" y="{H - 8}" text-anchor="end" class="ax">GEBV（g）</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_qc_bar(reason_counts: dict) -> str:
    """QC 拦截原因分布（个体数；一个个体可命中多条原因）。"""
    if not reason_counts:
        return ""
    items = sorted(reason_counts.items(), key=lambda kv: -kv[1])
    W, L, R, bh, gap = 560, 250, 40, 16, 9
    H = len(items) * (bh + gap) + 12
    vmax = max(v for _, v in items)
    pw = W - L - R
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="QC 拦截原因分布" '
             'style="width:100%;max-width:620px;height:auto">']
    for k, (code, v) in enumerate(items):
        y = 6 + k * (bh + gap)
        w = max(3.0, pw * v / vmax)
        label = REASON_LABELS.get(code, code)
        parts.append(f'<text x="{L - 8}" y="{y + bh - 4}" text-anchor="end" class="lbl">{esc(label)}</text>')
        parts.append(f'<path d="{_rounded_right_bar(L, y, w, bh)}" class="bar b1" '
                     f'data-tip="{esc(f"{code} · {v} 个个体")}"/>')
        parts.append(f'<text x="{L + w + 6:.1f}" y="{y + bh - 4}" class="lbl">{v}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------ HTML 渲染

_CSS = """
:root{
  --bg:#f9f9f7; --surface:#fcfcfb; --surface-2:#f0efec;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --series-1:#2a78d6; --series-2:#eb6834;
  --good:#0ca30c; --good-text:#006300; --warn:#fab219; --crit:#d03b3b;
  --accent:#2a78d6;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0d0d0d; --surface:#1a1a19; --surface-2:#262624;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --series-1:#3987e5; --series-2:#d95926;
    --good-text:#0ca30c; --accent:#3987e5;
  }
}
:root[data-theme="dark"]{
  --bg:#0d0d0d; --surface:#1a1a19; --surface-2:#262624;
  --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --series-1:#3987e5; --series-2:#d95926;
  --good-text:#0ca30c; --accent:#3987e5;
}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.7 system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;}
.wrap{max-width:1040px;margin-inline:auto;padding-inline:16px;padding-block:28px 56px;}
header .eyebrow{font-size:12.5px;letter-spacing:.14em;color:var(--muted);text-transform:uppercase;}
h1{font-size:clamp(24px,4vw,32px);line-height:1.25;margin:.25em 0 .2em;text-wrap:balance;}
h2{font-size:19px;margin:0 0 4px;}
.hmeta{color:var(--ink-2);font-size:13.5px;}
.simnote{display:inline-flex;gap:7px;align-items:center;margin-top:12px;padding:5px 12px;
  border:1px solid var(--border);border-radius:999px;background:var(--surface);
  color:var(--ink-2);font-size:12.5px;}
.simnote .dot{width:8px;height:8px;border-radius:50%;background:var(--warn);}
section{margin-top:34px;}
.sechead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:12px;}
.sechead .sub{color:var(--muted);font-size:13px;}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:18px 20px;}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px;}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 15px;}
.tile .k{font-size:12.5px;color:var(--muted);}
.tile .v{font-size:25px;font-weight:650;line-height:1.25;margin-top:2px;}
.tile .s{font-size:12.5px;color:var(--ink-2);margin-top:2px;}
.tile .s.up{color:var(--good-text);}
.tile .s.down{color:var(--crit);}
.scroll{overflow-x:auto;}
table{width:100%;border-collapse:collapse;font-size:13.5px;}
th{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
  text-align:left;font-weight:600;padding:7px 10px;border-bottom:1px solid var(--axis);white-space:nowrap;}
td{padding:7px 10px;border-bottom:1px solid var(--grid);vertical-align:top;}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;}
tr:hover td{background:var(--surface-2);}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
  background:var(--surface-2);border-radius:5px;padding:1px 6px;white-space:nowrap;}
.badge{display:inline-block;font-size:11.5px;border:1px solid var(--border);
  border-radius:999px;padding:1px 9px;color:var(--ink-2);background:var(--surface-2);}
.chip{display:inline-flex;gap:6px;align-items:center;font-size:12.5px;color:var(--ink-2);}
.chip .sw{width:10px;height:10px;border-radius:3px;}
.chip .sw.s1{background:var(--series-1);} .chip .sw.s2{background:var(--series-2);}
.status{display:inline-flex;gap:6px;align-items:center;font-size:12.5px;font-weight:600;}
.status .dot{width:8px;height:8px;border-radius:50%;}
.status.reject{color:var(--crit);} .status.reject .dot{background:var(--crit);}
.status.pass{color:var(--good-text);} .status.pass .dot{background:var(--good);}
.llm{border-left:3px solid var(--accent);}
.llm p{margin:8px 0 0;color:var(--ink);}
.llm .src{font-size:12.5px;color:var(--muted);}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;align-items:start;}
.note{font-size:12.5px;color:var(--muted);margin-top:6px;}
.legend{display:flex;gap:16px;margin-bottom:6px;}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--grid);
  color:var(--muted);font-size:12.5px;}
svg .grid{stroke:var(--grid);stroke-width:1;}
svg .axis{stroke:var(--axis);stroke-width:1.2;}
svg .ax{font-size:11px;fill:var(--muted);}
svg .lbl{font-size:11.5px;fill:var(--ink-2);font-variant-numeric:tabular-nums;}
svg .trend{fill:none;stroke:var(--series-1);stroke-width:2;}
svg .pt{fill:var(--series-1);}
svg .pt-cv{fill:var(--surface);stroke:var(--series-1);stroke-width:2;}
svg .bar{transition:opacity .12s;} svg .bar:hover{opacity:.8;}
svg .b1{fill:var(--series-1);} svg .b2{fill:var(--series-2);}
.tip{position:fixed;background:var(--ink);color:var(--bg);font-size:12.5px;
  padding:5px 10px;border-radius:7px;pointer-events:none;z-index:20;max-width:320px;}
@media (prefers-reduced-motion: reduce){ svg .bar{transition:none;} }
"""

_TIP_JS = """
<div class="tip" id="tip" hidden></div>
<script>
(function(){
  var tip=document.getElementById('tip');
  document.querySelectorAll('[data-tip]').forEach(function(el){
    el.addEventListener('mousemove',function(e){
      tip.textContent=el.getAttribute('data-tip');tip.hidden=false;
      var x=Math.min(e.clientX+14,window.innerWidth-330), y=e.clientY+14;
      tip.style.left=x+'px';tip.style.top=y+'px';});
    el.addEventListener('mouseleave',function(){tip.hidden=true;});
  });
})();
</script>
"""


def _tile(label, value, sub="", sub_cls="", metric_id=""):
    idattr = f' id="{metric_id}"' if metric_id else ""
    subline = f'<div class="s {sub_cls}">{sub}</div>' if sub else ""
    return (f'<div class="tile"><div class="k">{esc(label)}</div>'
            f'<div class="v"><span{idattr}>{value}</span></div>{subline}</div>')


def _reject_rows(qc: dict) -> str:
    rows = []
    for r in qc.get("rejected", []):
        codes = "".join(
            f'<span class="code" title="{esc(REASON_LABELS.get(c, c))}">{esc(c)}</span> '
            for c in r["reasons"])
        cat = _category_of(r["reasons"][0]) if r["reasons"] else ""
        rows.append(
            f'<tr><td><span class="code">{esc(r["id"])}</span></td>'
            f'<td>{esc(cat)}</td><td>{codes}</td>'
            f'<td style="color:var(--ink-2)">{esc(r["detail"])}</td></tr>')
    return "".join(rows)


def build_facts(batch_id, qc, merge, retrain, validation, mating, history, config):
    """供 LLM/Mock 摘要使用的结构化事实（只取已落盘数字）。"""
    cat_counts: dict[str, int] = {}
    for r in qc.get("rejected", []):
        cat = _category_of(r["reasons"][0]) if r["reasons"] else "其他"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    prev_r = delta = None
    if validation and history:
        idx = [i for i, h in enumerate(history) if h["batch_id"] == batch_id]
        if idx and idx[0] > 0:
            prev_r = history[idx[0] - 1]["r"]
            delta = round(validation["r"] - prev_r, 4)
    return {
        "batch_id": batch_id,
        "n_arrived": qc["n_arrived"], "n_admitted": qc["n_admitted"],
        "n_rejected": qc["n_rejected"], "qc_category_counts": cat_counts,
        "n_before": merge["n_before"] if merge else None,
        "n_after": merge["n_after"] if merge else None,
        "h2": retrain["h2_assumed"] if retrain else config.h2,
        "val_mode": validation["mode"] if validation else None,
        "r": validation["r"] if validation else None,
        "n_val": validation["n_val"] if validation else None,
        "prev_r": prev_r, "delta_r": delta if delta is not None else 0.0,
        "n_pairs": mating["n_pairs"] if mating else None,
        "blocked_kinship": mating["blocked_kinship_attempts"] if mating else None,
        "blocked_carrier": mating["blocked_carrier_attempts"] if mating else None,
        "max_F": config.max_progeny_inbreeding,
    }


def run(config: PipelineConfig, batch_id: str) -> dict:
    run_dir = config.run_dir(batch_id)
    qc = read_json(run_dir / "qc_report.json")
    merge = _load(run_dir / "merge_summary.json")
    retrain = _load(run_dir / "retrain_summary.json")
    validation = _load(run_dir / "validation.json")
    mating = _load(run_dir / "mating_summary.json")
    history = _load(config.history_path()) or []
    candidates = _load_csv(run_dir / "candidates.csv")
    pairs = _load_csv(run_dir / "mating_pairs.csv")
    gebv_all = _load_csv(run_dir / "gebv_refpop.csv")
    sim_params = _load(Path(config.data_dir) / "sim_truth" / "sim_params.json")
    manifest = _load(config.batch_dir(batch_id) / "manifest.json") or {}

    facts = build_facts(batch_id, qc, merge, retrain, validation, mating, history, config)
    llm = summarize(facts)

    generated_at = now_iso()
    write_json(run_dir / "summary.json", {
        "batch_id": batch_id, "generated_at": generated_at,
        "qc": {k: qc[k] for k in ("n_arrived", "n_admitted", "n_rejected", "reason_counts")},
        "merge": merge, "retrain": retrain, "validation": validation,
        "mating": mating, "facts": facts,
        "llm": {"mode": llm["mode"], "model": llm["model"], "note": llm["note"],
                "text": llm["text"]},
    })

    html_text = _render(config, batch_id, qc, merge, retrain, validation, mating,
                        history, candidates, pairs, gebv_all, llm, sim_params,
                        manifest, generated_at)
    out = config.report_path(batch_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")
    return {"report_path": str(out), "llm_mode": llm["mode"]}


def _render(config, batch_id, qc, merge, retrain, validation, mating, history,
            candidates, pairs, gebv_all, llm, sim_params, manifest, generated_at) -> str:
    seed = (sim_params or {}).get("config", {}).get("seed", "—")
    h = []
    h.append('<meta charset="utf-8">')
    h.append(f'<title>参考群更新 · {esc(batch_id)}</title>')
    h.append(f"<style>{_CSS}</style>")
    h.append('<div class="wrap">')

    # ---------- 头部 ----------
    h.append('<header>')
    h.append('<div class="eyebrow">白羽肉鸡育种数字化 · 参考群更新管线</div>')
    h.append(f'<h1>{esc(batch_id)} 批次运行报告</h1>')
    h.append(f'<div class="hmeta">到货日期 {esc(manifest.get("arrival_date", "—"))} · '
             f'报告生成 {esc(generated_at)} · 性状：{esc(TRAIT_LABEL)}</div>')
    h.append(f'<div class="simnote"><span class="dot"></span>'
             f'演示原型 —— 全部数据为模拟生成（种子 {esc(seed)}），遗传参数为假设值，'
             f'注入缺陷清单见 data/DEFECTS.md</div>')
    h.append('</header>')

    # ---------- LLM 摘要 ----------
    mode_badge = ("Mock（模板生成，非真实 LLM）" if llm["mode"] == "mock"
                  else f"LLM 起草 · {llm['model']}")
    h.append('<section id="sec-llm"><div class="card llm">')
    h.append(f'<div class="src">运行摘要 · <span class="badge">{esc(mode_badge)}</span>'
             f' · {esc(llm["note"])}</div>')
    h.append(f'<p id="llm-text">{esc(llm["text"])}</p>')
    h.append('</div></section>')

    # ---------- 关键指标 ----------
    h.append('<section><div class="tiles">')
    h.append(_tile("到货个体", qc["n_arrived"], metric_id="metric-arrived"))
    h.append(_tile("QC 拦截", qc["n_rejected"],
                   sub=f'拦截率 {qc["n_rejected"] / max(qc["n_arrived"], 1):.1%}',
                   metric_id="metric-rejected"))
    h.append(_tile("放行合格", qc["n_admitted"], metric_id="metric-admitted"))
    if merge:
        h.append(_tile("合并后参考群", merge["n_after"],
                       sub=f'较更新前 +{merge["n_added"]}', sub_cls="up",
                       metric_id="metric-refpop-after"))
    if validation:
        mode_cn = "前向验证 r" if validation["mode"] == "forward" else "交叉验证 r（基线）"
        prev = [x for x in history if x["batch_id"] != batch_id]
        sub, cls = "", ""
        if validation["mode"] == "forward" and prev:
            d = validation["r"] - prev[-1]["r"]
            sub, cls = f'较上一轮 {d:+.3f}', ("up" if d >= 0 else "down")
        h.append(_tile(mode_cn, f'{validation["r"]:.3f}', sub=sub, sub_cls=cls,
                       metric_id="metric-r"))
    if mating:
        h.append(_tile("选配建议", mating["n_pairs"],
                       sub=f'候选 {mating["n_candidates"]} 只', metric_id="metric-pairs"))
    h.append('</div></section>')

    # ---------- QC ----------
    h.append('<section id="sec-qc">')
    h.append('<div class="sechead"><h2>① QC 门禁 —— 拦截明细</h2>'
             f'<span class="sub">谁被拦、为什么 · 阈值见 qc_report.json</span></div>')
    if qc["n_rejected"] == 0:
        h.append('<div class="card"><span class="status pass"><span class="dot"></span>'
                 '本批全部个体通过 QC，无拦截</span>'
                 '<div class="note">该批为经人工整理的历史参考群（模拟设定），未注入缺陷。</div></div>')
    else:
        h.append('<div class="grid2">')
        h.append(f'<div class="card"><div class="note" style="margin:0 0 8px">'
                 f'按原因统计（一个个体可命中多条原因）</div>{_svg_qc_bar(qc["reason_counts"])}</div>')
        h.append('<div class="card"><div class="note" style="margin:0 0 8px">拦截判定均为确定性规则；'
                 '被拦个体不进入参考群，进入人工复核队列（演示中仅记录）。'
                 '完整逐个体决策表见 qc_report.csv。</div>'
                 f'<div class="note">到货 {qc["n_arrived"]} · '
                 f'<span class="status reject"><span class="dot"></span>拦截 {qc["n_rejected"]}</span> · '
                 f'<span class="status pass"><span class="dot"></span>放行 {qc["n_admitted"]}</span>'
                 '</div></div>')
        h.append('</div>')
        h.append('<div class="scroll" style="margin-top:14px"><table id="qc-reject-table">')
        h.append('<tr><th>样本 ID</th><th>缺陷类别</th><th>命中规则</th><th>拦截说明</th></tr>')
        h.append(_reject_rows(qc))
        h.append('</table></div>')
    h.append('</section>')

    # ---------- 合并 ----------
    h.append('<section id="sec-merge">')
    h.append('<div class="sechead"><h2>② 参考群合并</h2>'
             '<span class="sub">merge_summary.json</span></div>')
    if merge:
        comp = " · ".join(f"{k}: {v}" for k, v in merge["by_batch_after"].items())
        h.append('<div class="tiles">')
        h.append(_tile("更新前", merge["n_before"], metric_id="metric-n-before"))
        h.append(_tile("本批并入", f'+{merge["n_added"]}', metric_id="metric-n-added"))
        h.append(_tile("更新后", merge["n_after"]))
        h.append('</div>')
        h.append(f'<div class="note">合并后构成：{esc(comp)}（个体数按来源批次）</div>')
    else:
        h.append('<div class="card">未执行（QC 后无合格个体，流程在门禁处中止）。</div>')
    h.append('</section>')

    # ---------- 重训 + 验证 ----------
    h.append('<section id="sec-model">')
    h.append('<div class="sechead"><h2>③ GBLUP 重训与前向验证</h2>'
             '<span class="sub">retrain_summary.json · validation.json · predictions.csv</span></div>')
    if retrain and validation:
        h.append('<div class="grid2">')
        # 左：趋势图
        h.append('<div class="card">')
        h.append('<div class="note" style="margin:0 0 6px">验证 r 跨代趋势 —— 实心点为前向验证'
                 '（上一代模型 → 本批真实表型），空心点为 G0 交叉验证基线（口径不同，仅作参照）</div>')
        h.append(_svg_r_trend(history))
        h.append('</div>')
        # 右：模型与验证明细
        h.append('<div class="card"><div class="scroll"><table>')
        h.append('<tr><th>项</th><th>值</th></tr>')
        rows = [
            ("训练个体数", retrain["n_train"]),
            ("标记数", retrain["m_markers"]),
            ("遗传力 h²", f'{retrain["h2_assumed"]}　<span class="badge">假设值（生产应 REML 估计）</span>'),
            ("岭参数 λ = 2Σpq·(1-h²)/h²", retrain["lambda"]),
            ("验证口径", esc(validation["mode_label"])),
            ("验证 r", f'<b>{validation["r"]:.4f}</b>（n={validation["n_val"]}）'),
            ("回归斜率 b(y,GEBV)", f'{validation["slope"]}（≈1 为无偏）'),
        ]
        if validation.get("r_tbv_sim") is not None:
            rows.append(("r(GEBV, 真实TBV)",
                         f'{validation["r_tbv_sim"]:.4f}　<span class="badge">仅模拟环境可得</span>'))
        for k, v in rows:
            h.append(f'<tr><td style="color:var(--ink-2)">{k}</td><td>{v}</td></tr>')
        h.append('</table></div></div>')
        h.append('</div>')
        # 历史表
        h.append('<div class="scroll" style="margin-top:14px"><table id="history-table">')
        h.append('<tr><th>批次</th><th>口径</th><th class="num">验证 r</th>'
                 '<th class="num">验证 n</th><th class="num">训练 n</th>'
                 '<th class="num">参考群规模</th><th class="num">Δr（较上一行）</th></tr>')
        for i, x in enumerate(history):
            d = "—" if i == 0 else f'{x["r"] - history[i - 1]["r"]:+.4f}'
            mode_cn = "前向" if x["mode"] == "forward" else "5折CV"
            h.append(f'<tr><td>{esc(x["batch_id"])}</td><td>{mode_cn}</td>'
                     f'<td class="num"><b>{x["r"]:.4f}</b></td>'
                     f'<td class="num">{x["n_val"]}</td>'
                     f'<td class="num">{x.get("train_n") or "—"}</td>'
                     f'<td class="num">{x["refpop_n_after"]}</td><td class="num">{d}</td></tr>')
        h.append('</table></div>')
        h.append('<div class="note">前向验证 r 的合理区间为 0.3～0.7，且应随参考群扩大呈非降趋势'
                 '（Δr 混合了参考群扩大(+)与代际选择降低验证群方差(−)两种效应）。'
                 '每个 r 均可由 predictions.csv 逐个体复算。</div>')
    else:
        h.append('<div class="card">未执行。</div>')
    h.append('</section>')

    # ---------- GEBV Top-20 ----------
    h.append('<section id="sec-top">')
    h.append(f'<div class="sechead"><h2>④ 本批次 GEBV Top-{config.top_list_size} 清单</h2>'
             '<span class="sub">candidates.csv（重训后模型对当代合格个体的排名）</span></div>')
    if candidates is not None and len(candidates) and gebv_all is not None:
        carrier_cols = [c for c in candidates.columns if c.startswith("carrier_")]
        h.append('<div class="grid2">')
        h.append('<div class="card">')
        h.append('<div class="legend"><span class="chip"><span class="sw s1"></span>本批次（当代候选）</span>'
                 '<span class="chip"><span class="sw s2"></span>参考群全体</span></div>')
        a = candidates["gebv"].to_numpy(dtype=float)
        b = gebv_all["gebv"].to_numpy(dtype=float)
        h.append(_svg_hist(a, b))
        h.append('<div class="note">按占比归一（两组个体数不同）。当代候选分布整体右移即为代际遗传进展。</div>')
        h.append('</div>')
        top = candidates.head(config.top_list_size)
        h.append('<div class="card" style="padding:8px 6px"><div class="scroll"><table id="top20-table">')
        cc = "".join(f"<th>{esc(c.replace('carrier_', ''))}</th>" for c in carrier_cols)
        h.append(f'<tr><th class="num">#</th><th>个体</th><th>性别</th>'
                 f'<th class="num">GEBV(g)</th><th class="num">百分位</th>{cc}<th>父</th><th>母</th></tr>')
        for k, (_, r) in enumerate(top.iterrows(), 1):
            cvals = "".join(f'<td>{"⚠ 携带" if r[c] == "携带" else "—"}</td>' for c in carrier_cols)
            h.append(f'<tr><td class="num">{k}</td><td><span class="code">{esc(r["id"])}</span></td>'
                     f'<td>{SEX_CN.get(str(r["sex"]), r["sex"])}</td>'
                     f'<td class="num"><b>{float(r["gebv"]):+.1f}</b></td>'
                     f'<td class="num">{float(r["gebv_percentile"]):.1f}%</td>{cvals}'
                     f'<td><span class="code">{esc(r["sire"]) or "—"}</span></td>'
                     f'<td><span class="code">{esc(r["dam"]) or "—"}</span></td></tr>')
        h.append('</table></div></div>')
        h.append('</div>')
    else:
        h.append('<div class="card">未执行。</div>')
    h.append('</section>')

    # ---------- 选配 ----------
    h.append('<section id="sec-mating">')
    h.append('<div class="sechead"><h2>⑤ 选配建议 —— 近交约束 + 携带者规则</h2>'
             '<span class="sub">mating_pairs.csv · mating_summary.json</span></div>')
    if mating and pairs is not None:
        h.append('<div class="tiles">')
        h.append(_tile("建议配对", mating["n_pairs"]))
        h.append(_tile("启用公鸡", f'{mating["n_sires_used"]}/{mating["n_sires_pool"]}'))
        h.append(_tile("近交拦截(次)", mating["blocked_kinship_attempts"],
                       sub=f'预期后代 F ≤ {mating["rules"]["max_progeny_inbreeding"]}'))
        h.append(_tile("携带者拦截(次)", mating["blocked_carrier_attempts"],
                       sub="携带者×携带者禁配"))
        h.append(_tile("未能配对母鸡", len(mating["unassigned_dams"])))
        h.append('</div>')
        cr = " · ".join(f'{k}: {v["n_carriers"]} 只（{v["rate"]:.1%}）'
                        for k, v in mating["carrier_rates"].items())
        h.append(f'<div class="note">当代携带者频率 —— {esc(cr)}（隐性致死位点，见 data/markers.json）；'
                 f'规则：{esc(mating["rules"]["carrier_rule"])}；'
                 f'每只公鸡至多配 {mating["rules"]["max_dams_per_sire"]} 只母鸡。</div>')
        show = pairs.head(config.pairs_in_report)
        h.append('<div class="scroll" style="margin-top:12px"><table id="pairs-table">')
        h.append('<tr><th class="num">#</th><th>父本</th><th class="num">父GEBV</th>'
                 '<th>母本</th><th class="num">母GEBV</th><th class="num">后代期望GEBV</th>'
                 '<th class="num">预期后代F</th><th>携带者标注</th></tr>')
        for _, r in show.iterrows():
            h.append(f'<tr><td class="num">{int(r["rank"])}</td>'
                     f'<td><span class="code">{esc(r["sire"])}</span></td>'
                     f'<td class="num">{float(r["sire_gebv"]):+.1f}</td>'
                     f'<td><span class="code">{esc(r["dam"])}</span></td>'
                     f'<td class="num">{float(r["dam_gebv"]):+.1f}</td>'
                     f'<td class="num"><b>{float(r["expected_progeny_gebv"]):+.1f}</b></td>'
                     f'<td class="num">{float(r["expected_progeny_F"]):.4f}</td>'
                     f'<td>{esc(r["carrier_note"]) or "—"}</td></tr>')
        h.append('</table></div>')
        if len(pairs) > len(show):
            h.append(f'<div class="note">仅展示前 {len(show)} 组（按后代期望 GEBV 排序），'
                     f'完整 {len(pairs)} 组见 mating_pairs.csv。</div>')
    else:
        h.append('<div class="card">未执行。</div>')
    h.append('</section>')

    # ---------- 页脚：复算指引 ----------
    h.append('<footer>')
    h.append('<b>数字可复算</b> —— 本报告不做任何计算，仅汇总以下磁盘产物；'
             '逐条核对路径（相对仓库根目录）：')
    art = f"artifacts/runs/{batch_id}"
    h.append('<ul style="margin:6px 0 0;padding-left:18px">')
    for label, p in [
        ("QC 拦截明细", f"{art}/qc_report.json 与 qc_report.csv"),
        ("参考群规模", f"{art}/merge_summary.json 与 artifacts/refpop/registry.json"),
        ("模型参数", f"artifacts/models/model_{batch_id}.json"),
        ("验证 r（逐个体预测值）", f"{art}/validation.json 与 predictions.csv"),
        ("GEBV 排名/Top-20", f"{art}/candidates.csv 与 gebv_refpop.csv"),
        ("选配建议", f"{art}/mating_pairs.csv 与 mating_summary.json"),
        ("本页全部数字的汇总", f"{art}/summary.json"),
    ]:
        h.append(f'<li>{esc(label)}：<span class="code">{esc(p)}</span></li>')
    h.append('</ul>')
    h.append(f'<div style="margin-top:10px">复现：<span class="code">python -m refpop_agent.cli run-all'
             f'</span>（数据种子 {esc(seed)}，全流程确定性）。'
             '再次声明：演示用模拟数据，遗传参数为假设值，不构成任何真实群体的评估结论。</div>')
    h.append('</footer>')
    h.append('</div>')
    h.append(_TIP_JS)
    return "\n".join(h)
