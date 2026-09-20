# 基因组选择实验阶梯：ML 能否打败 BLUP？

面试级可复现实验。核心问题：**LLM/ML 能否打败 BLUP？** 用实验阶梯（L0 系谱BLUP → L1 GBLUP →
L2 梯度提升 → L3 加权先验演示）+ 三种评估口径（随机CV / 留家系代理 / 前向代理）× 3 seeds 实测回答。

## 交付物
- `gs_pig_ladder.ipynb` — 已执行、含全部输出的 notebook（数据获取实录、核验、全部实验、图表、SELF-QA）
- `results.json` — 每个实验格子的指标（数据集×模型×口径×性状×seed）+ meta + 检查
- `SUMMARY.md` — 一页结论（首行含数据降级声明）
- `env.txt` — pip freeze

## 数据说明（重要）
主选 Cleveland et al. 2012 (G3) PIC 猪数据集的**完整版（5性状+系谱）在本执行环境的网络策略下不可得**
（PMC/OUP/figshare/dryad/zenodo/wayback 全部被代理 403 拦截，GitHub 镜像只有 t1 单性状 curated 版）。
按任务规范降级：**正式阶梯 = BGLR wheat**（gdlc/BGLR-R@de839cf, data/wheat.RData）；
**补充分析 = 真实猪基因型 3,534×52,843 + t1**（QuantGen/G2P-Datasets@a7bf58a, 00070_PigDataPICG3），
明确标注、不冒充主选。细节见 notebook 首个 markdown 与 SUMMARY.md 局限一节。

## 复现
```bash
python3 -m venv .venv && .venv/bin/pip install -r <(sed 's/ @ .*//' env.txt)  # 或逐包安装 env.txt
# data/ 由 notebook 数据获取 cell 自动从上述两个公开 GitHub 仓库浅克隆复制
.venv/bin/jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 gs_pig_ladder.ipynb
```
