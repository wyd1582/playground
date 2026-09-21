#!/usr/bin/env python3
"""渲染 cost_curves.png — 4面板: E1密度曲线 / E2基因型还原 / E2精度损失 / E3成本效益。

用法: python3 make_figure.py <resultsdir>
调色板: dataviz 参考调色板 (slot1 蓝 #2a78d6, slot2 橙 #eb6834), 已通过
adjacent-pair CVD/对比度校验 (validate_palette.js, light surface #fcfcfb)。
中文字体: WenQuanYi Zen Hei (容器内唯一可用的矢量CJK字体, 经 addfont 注册)。
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
import numpy as np
import pandas as pd
from matplotlib.patches import PathPatch, Patch
from matplotlib.path import Path as MplPath

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, SEC, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
DEEMPH = "#c3c2b7"
DPI = 200
R_PX = 4 * DPI / 96  # 4px 圆角数据端 (设计像素换算到输出 dpi)

fm.fontManager.addfont("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["WenQuanYi Zen Hei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "text.color": SEC, "axes.labelcolor": SEC,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.edgecolor": BASELINE,
})


def style_axis(ax, ygrid=True, xgrid=False):
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.8)
    if ygrid:
        ax.grid(axis="y", color=GRID, linewidth=0.7, zorder=0)
    if xgrid:
        ax.grid(axis="x", color=GRID, linewidth=0.7, zorder=0)
        ax.spines["bottom"].set_visible(False)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=8.5)
    ax.set_facecolor(SURFACE)


def rounded_bar(ax, x0, y0, w, h, color, horizontal=False):
    """条形: 数据端 4px 圆角、基线端方角。在 display 坐标构建 (需先 draw)。"""
    t = ax.transData
    if horizontal:
        (X0, Y0), (X1, Y1) = t.transform((y0, x0)), t.transform((y0 + h, x0 + w))
    else:
        (X0, Y0), (X1, Y1) = t.transform((x0, y0)), t.transform((x0 + w, y0 + h))
    r = min(R_PX, abs(X1 - X0) / 2, abs(Y1 - Y0) / 2)
    if horizontal:  # 数据端在右
        verts = [(X0, Y0), (X1 - r, Y0), (X1, Y0), (X1, Y0 + r), (X1, Y1 - r),
                 (X1, Y1), (X1 - r, Y1), (X0, Y1), (X0, Y0)]
    else:  # 数据端在上
        verts = [(X0, Y0), (X0, Y1 - r), (X0, Y1), (X0 + r, Y1), (X1 - r, Y1),
                 (X1, Y1), (X1, Y1 - r), (X1, Y0), (X0, Y0)]
    codes = [MplPath.MOVETO, MplPath.LINETO, MplPath.CURVE3, MplPath.CURVE3,
             MplPath.LINETO, MplPath.CURVE3, MplPath.CURVE3, MplPath.LINETO,
             MplPath.CLOSEPOLY]
    patch = PathPatch(MplPath(verts, codes), facecolor=color, edgecolor="none",
                      transform=mtransforms.IdentityTransform(), zorder=3)
    patch.set_clip_box(ax.bbox)
    ax.add_patch(patch)


def main():
    outdir = Path(sys.argv[1])
    e1 = pd.read_csv(outdir / "density_curve.csv")
    e2 = pd.read_csv(outdir / "imputation_table.csv")
    e2s = pd.read_csv(outdir / "imputation_table_per_seed.csv")
    e3 = pd.read_csv(outdir / "cost_table.csv")
    res = json.loads((outdir / "results.json").read_text())
    full_r = res["full_r_mean"]
    loss = (e2s.groupby(["mask_share", "method"]).pred_r_loss
            .agg(["mean", "std"]).reset_index())

    fig, axes = plt.subplots(2, 2, figsize=(12.6, 8.6), dpi=DPI)
    fig.patch.set_facecolor(SURFACE)
    (axA, axB), (axC, axD) = axes
    fig.subplots_adjust(left=0.075, right=0.965, top=0.865, bottom=0.135,
                        hspace=0.55, wspace=0.30)

    # ---------- Panel A: E1 密度-精度曲线 ----------
    style_axis(axA)
    axA.set_xscale("log")
    x, ym, ys = e1.n_markers.values, e1.r_mean.values, e1.r_std.values
    axA.axhline(full_r, color=BASELINE, lw=1, zorder=1)
    axA.axhline(0.95 * full_r, color=GRID, lw=1, zorder=1)
    axA.fill_between(x, ym - ys, ym + ys, color=BLUE, alpha=0.10, lw=0, zorder=2)
    axA.plot(x, ym, color=BLUE, lw=2, solid_joinstyle="round",
             solid_capstyle="round", zorder=4,
             marker="o", ms=6, mfc=BLUE, mec=SURFACE, mew=1.4)
    axA.set_xticks([50, 100, 200, 500, 800, 1279])
    axA.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    axA.set_xlim(44, 1500)
    axA.set_ylim(0.18, 0.60)
    axA.set_xlabel("标记数（对数轴；全量=1279）", fontsize=9)
    axA.set_ylabel("预测精度 r（5折袋外）", fontsize=9)
    axA.text(46, full_r + 0.012, f"全量精度 r = {full_r:.3f}", fontsize=8,
             color=SEC)
    axA.text(1450, 0.95 * full_r - 0.030, "95% 全量线", fontsize=8,
             color=MUTED, ha="right")
    r800 = float(e1.loc[e1.n_markers == 800, "r_mean"].iloc[0])
    p800 = float(e1.loc[e1.n_markers == 800, "pct_of_full"].iloc[0])
    r500 = float(e1.loc[e1.n_markers == 500, "r_mean"].iloc[0])
    p500 = float(e1.loc[e1.n_markers == 500, "pct_of_full"].iloc[0])
    axA.annotate(f"饱和点：800标记 ≈ 全量{p800:.0f}%",
                 xy=(800, r800 + 0.004), xytext=(255, 0.555), fontsize=8.5,
                 color=INK,
                 arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8,
                                 shrinkB=6))
    axA.annotate(f"500标记 = 全量{p500:.0f}%", xy=(500, r500 - 0.006),
                 xytext=(500, 0.335), fontsize=8.5, color=SEC, ha="center",
                 arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8,
                                 shrinkB=6))
    axA.set_title("E1 · 标记密度—精度曲线（±1 SD，3种子）",
                  fontsize=10.5, color=INK, loc="left", pad=10)

    # ---------- Panel B/C 公共: 分组条形 ----------
    shares = [0.3, 0.5, 0.7]
    xs = np.arange(3.0)
    bw, off = 0.15, 0.085  # 条宽≈23css px, 组内 2px+ 表面留白
    legend_handles = [Patch(facecolor=BLUE, label="KNN填补 (k=20)"),
                      Patch(facecolor=ORANGE, label="列均值填补")]

    def grouped_axis(ax, ylabel):
        style_axis(ax)
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{int(s*100)}%" for s in shares])
        ax.set_xlim(-0.55, 2.55)
        ax.set_xlabel("低密度(500标记)个体占比", fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.legend(handles=legend_handles, frameon=False, fontsize=8, ncol=2,
                  loc="lower right", bbox_to_anchor=(1.0, 0.998),
                  handlelength=1.1, handleheight=1.1, borderaxespad=0,
                  columnspacing=1.2)

    def draw_grouped(ax, mean_of, std_of):
        bars = []
        for i, s in enumerate(shares):
            for dx, method, color in [(-off, "knn_k20", BLUE),
                                      (+off, "col_mean", ORANGE)]:
                m, sd = mean_of(s, method), std_of(s, method)
                bars.append((xs[i] + dx - bw / 2, m, color))
                ax.errorbar(xs[i] + dx, m, yerr=sd, fmt="none", ecolor=MUTED,
                            elinewidth=1, capsize=2.5, capthick=1, zorder=5)
        return bars

    grouped_axis(axB, "基因型还原准确率")
    axB.set_ylim(0, 1.0)
    axB.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    barsB = draw_grouped(
        axB,
        lambda s, m: float(e2[(e2.mask_share == s) & (e2.method == m)]
                           .geno_accuracy_mean.iloc[0]),
        lambda s, m: float(e2[(e2.mask_share == s) & (e2.method == m)]
                           .geno_accuracy_std.iloc[0]))
    axB.set_title("E2 · 掩码标记的基因型还原准确率", fontsize=10.5, color=INK,
                  loc="left", pad=10)

    grouped_axis(axC, "精度损失 Δr（相对全量；越低越好）")
    axC.set_ylim(0, 0.075)
    ld_loss = full_r - float(e3.loc[e3.scheme.str.contains("不填补"), "r"].iloc[0])
    axC.axhline(ld_loss, color=BASELINE, lw=1, zorder=1)
    axC.text(-0.50, 0.0695,
             f"灰色参考线：全员500标记、不填补的损失 Δr = {ld_loss:.3f}",
             fontsize=8, color=MUTED, va="top")
    barsC = draw_grouped(
        axC,
        lambda s, m: float(loss[(loss.mask_share == s) & (loss.method == m)]
                           ["mean"].iloc[0]),
        lambda s, m: float(loss[(loss.mask_share == s) & (loss.method == m)]
                           ["std"].iloc[0]))
    axC.set_title("E2 · 填补数据训练的精度损失 Δr", fontsize=10.5, color=INK,
                  loc="left", pad=10)

    # ---------- Panel D: E3 成本效益 ----------
    style_axis(axD, ygrid=False, xgrid=True)
    d = e3[~e3.scheme.str.contains("均值")].copy()  # 均值填补方案见表格
    d = d.sort_values("cost_per_unit_r", ascending=False).reset_index(drop=True)
    names = [s.replace("全体高密度(全量1279标记)", "全体高密度（1279标记）")
              .replace("全体低密度(500标记, 不填补)", "全体低密度500（不填补）")
             for s in d.scheme]
    best = int(d.cost_per_unit_r.idxmin())
    ybar = np.arange(len(d), dtype=float)
    axD.set_yticks(ybar)
    axD.set_yticklabels(names, fontsize=8.5)
    axD.set_xlim(0, 262)
    axD.set_xticks([0, 50, 100, 150, 200, 250])
    axD.set_ylim(-0.55, len(d) - 0.45)
    axD.set_xlabel("每单位预测精度的成本 = 成本 ÷ r（越低越好）", fontsize=9)
    axD.set_title("E3 · 成本效益（成本为假设占位值：HD=100，LD=30）",
                  fontsize=10.5, color=INK, loc="left", pad=10)
    barsD = [(float(ybar[i]) - 0.15, float(d.cost_per_unit_r[i]),
              BLUE if i == best else DEEMPH) for i in range(len(d))]
    for i in range(len(d)):
        v, r_, s_ = (float(d.cost_per_unit_r[i]), float(d.r[i]),
                     float(d.cost_saving_pct[i]))
        tail = "基准" if s_ == 0 else f"省{s_:.0f}%"
        axD.text(v + 4, ybar[i], f"{v:.0f}（r={r_:.2f}，{tail}）",
                 va="center", fontsize=8, color=INK if i == best else SEC)

    # ---------- 圆角条形绘制 (需先锁定坐标变换) ----------
    fig.canvas.draw()
    for x0, v, c in barsB:
        rounded_bar(axB, x0, 0, bw, v, c)
    for x0, v, c in barsC:
        rounded_bar(axC, x0, 0, bw, v, c)
    for y0, v, c in barsD:
        rounded_bar(axD, y0, 0, 0.30, v, c, horizontal=True)

    fig.suptitle("低密度SKU可行性 · 标记密度—精度曲线与「低密度+填补」经济学",
                 fontsize=13.5, color=INK, x=0.075, ha="left", y=0.975)
    fig.text(0.075, 0.925,
             "数据：BGLR wheat（599系 × 1279 DArT标记，表型=籽粒产量ENV1）"
             "｜模型：RidgeCV 5折交叉验证 × 3随机种子",
             fontsize=9, color=SEC)
    fig.text(0.075, 0.030,
             "注：Cleveland猪数据托管源在本执行环境不可达，按预案降级为 BGLR wheat；"
             "任务网格中2000/5000超出总标记数1279故不适用，补充50/100/300/800密度点。\n"
             "所有成本数字均为假设占位值（高密度=100、低密度=30，归一化），"
             "真实价格留待客户数据；结论仅描述本数据，不构成跨物种/跨群体外推承诺。",
             fontsize=7.8, color=MUTED, va="bottom")
    fig.savefig(outdir / "cost_curves.png", dpi=DPI, facecolor=SURFACE)
    print("saved", outdir / "cost_curves.png")


if __name__ == "__main__":
    main()
