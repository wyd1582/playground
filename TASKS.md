# 跨会话任务交接（Task A → B/C/D 共享中枢）

> 本仓库是四个并行 Claude Code 会话的共享空间。**Task A（LLM/ML vs BLUP 实验阶梯）已完成**，
> 产物在 `genomic-selection-pig/`。本文档写给 Task B/C/D 的会话：数据在哪、怎么读、有哪些坑。

## Task A 产物一览（全部在 master）

| 文件 | 用途 |
|---|---|
| `genomic-selection-pig/results.json` | 171 个实验格子（dataset×model×protocol×trait×seed）+ meta + 检查 → **Task D Tab1 直接读这个** |
| `genomic-selection-pig/figs/fig1_ladder.png`, `fig2_inflation.png` | 阶梯对比图（三口径分面）、虚高差距图 |
| `genomic-selection-pig/SUMMARY.md` | 一页结论（首行有数据降级声明） |
| `genomic-selection-pig/data/pig_cleveland_curated.rdata` | **真实猪基因型 3,534×52,843 + t1 表型**（35MB，已入库）→ **Task C 复用这个** |
| `genomic-selection-pig/data/wheat.RData` | BGLR wheat 599×1,279（X/Y/A/sets）→ Task C 的降级备选 |
| `genomic-selection-pig/gs_pig_ladder.ipynb` | 已执行 notebook（方法细节都在里面） |
| `genomic-selection-pig/gs_ladder_report.pdf` | 3 页 conference 短文 |

## ⚠ 网络策略（所有会话通用的坑）

出站 HTTPS 只放行 **GitHub + PyPI**。PMC/OUP/figshare/dryad/zenodo/wayback 全部被代理 403。
**不要再尝试从期刊下载 Cleveland 数据**——Task A 已确认完整版（5性状+系谱）在本环境不可得，
可得的只有上面这份 curated 版（仅 t1 性状、无系谱）。数据来源与校验：
- pig: `QuantGen/G2P-Datasets @ a7bf58a` `Datasets/00070_PigDataPICG3/curated_geno_pheno_map.rdata`，sha256 前16位 `9968d60791971d9b`
- wheat: `gdlc/BGLR-R @ de839cf` `data/wheat.RData`，sha256 前16位 `8710523389007dd8`

## Task C：数据读取代码（直接可用）

**坑：`pyreadr` 解析这份 rdata 会报错**（不支持其矩阵对象），必须用纯 Python 的 `rdata` 包：

```python
# pip install rdata numpy pandas scikit-learn
import rdata, numpy as np

# --- pig（优先）：X (3534, 52843) float32, y 含 NaN（t1 有效 2804 条） ---
conv = rdata.conversion.convert(rdata.parser.parse_file(
    'genomic-selection-pig/data/pig_cleveland_curated.rdata'))
X = np.asarray(conv['geno'], dtype=np.float32)      # 值为 0/1/2 + 少量分数剂量(0.13%, 镜像方预填补)
y = conv['pheno']['pheno'].values.astype(float)      # t1, NaN=缺失
assert X.shape == (3534, 52843)
mask = np.isfinite(y); X, y = X[mask], y[mask]       # n=2804
# 建议 QC：MAF>=0.01 过滤（freq=X.mean(0)/2），过滤后 ~50,436 个位点

# --- wheat（降级备选）：X (599,1279) 0/1, Y (599,4) 无缺失, A (599,599) ---
convw = rdata.conversion.convert(rdata.parser.parse_file(
    'genomic-selection-pig/data/wheat.RData'))
Xw, Yw, Aw = (np.asarray(convw[k]) for k in ['wheat.X', 'wheat.Y', 'wheat.A'])
```

注意：**pig t1 是弱信号性状**（Task A 实测 GBLUP 随机CV r≈0.056±0.016）——Task C 的密度曲线
在 pig 上会整体压得很低、饱和点判断困难；建议 pig/wheat 都跑，wheat（随机CV r≈0.44）曲线形态
更清晰，报告里两者并列并声明。E2 填补实验的"基因型还原准确率"在 pig 上注意分数剂量值
（还原准确率按四舍五入到 {0,1,2} 后比较，或报 RMSE，声明口径）。

## Task D：results.json 结构

```
{ "meta":   { runtime_min, seeds, datasets:{wheat:{role,traits:[env1,env2,env4,env5],...},
              pig:{role:"SUPPLEMENTARY...", traits:[t1]}}, protocols:{...}, engines:{...} },
  "checks": { equivalence:[...], equivalence_strict_max:0.0038, l2_reference:{...} },
  "results":[ { dataset, model, protocol, trait, seed, r, bias_slope, top10, n_eval, sec, extra }, ... ] }
```
- `model` ∈ {L0_pedBLUP(仅wheat), L1_GBLUP, L2_GBM, L3_wRidge}；`protocol` ∈ {random, group, forward}
- Tab1 渲染建议直接复刻 fig1 的分面逻辑；**中文解读模板必带两句**：
  ①"留家系 r < 随机CV r（泄漏哨兵通过）：wheat 0.220<0.438，pig -0.005<0.056"；
  ②"GBM 仅在随机CV口径领先（0.472 vs 0.438），留家系/前向口径反转——口径比模型重要"。
- 声明栏文案可引用：wheat 为正式数据（主选猪数据不可得已按规范降级）；pig t1 为补充分析。

## 约定

- Task A 的会话分支 `claude/nifty-hawking-nxija1` 已合并进 master；后续各 task 在各自分支开发、
  产物合回 master 供他人读取。
- 大文件纪律：`cache/`、`.venv/` 不入库；数据文件 <50MB 可入库（本仓库为演示性质）。
- biotech-gene 独立仓库迁移计划暂缓，待四个 task 收官后执行（Task A 会话里已有步骤）。
