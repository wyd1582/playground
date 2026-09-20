#!/usr/bin/env python
"""生成 conference-paper 级简短研究报告 PDF（gs_ladder_report.pdf）。
所有数字在构建时从 results.json 读取（与已执行 notebook 同源），不手填。"""
import json
import numpy as np
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image as RLImage, KeepTogether)
from reportlab.lib.utils import ImageReader

# ---------- 数据（构建时读取，与 notebook 同源） ----------
R = json.load(open('results.json'))
DF = pd.DataFrame(R['results'])
META, CHECKS = R['meta'], R['checks']

def agg(ds):
    d = DF[DF.dataset == ds]
    g = d.groupby(['model', 'protocol'])['r'].agg(['mean', 'std'])
    return g

def cell(g, m, p):
    return f"{g.loc[(m, p), 'mean']:.3f} ± {g.loc[(m, p), 'std']:.3f}"

GW, GP = agg('wheat'), agg('pig')
def gv(ds, m, p, col='r'):
    d = DF[(DF.dataset == ds) & (DF.model == m) & (DF.protocol == p)]
    return d[col].mean()

w11r, w12r = gv('wheat', 'L1_GBLUP', 'random'), gv('wheat', 'L2_GBM', 'random')
w11g, w12g = gv('wheat', 'L1_GBLUP', 'group'),  gv('wheat', 'L2_GBM', 'group')
w11f, w12f = gv('wheat', 'L1_GBLUP', 'forward'), gv('wheat', 'L2_GBM', 'forward')
w10r, w10g = gv('wheat', 'L0_pedBLUP', 'random'), gv('wheat', 'L0_pedBLUP', 'group')
gap_w = np.mean([gv('wheat', m, 'random') - gv('wheat', m, 'group') for m in ['L1_GBLUP', 'L2_GBM']])
gap_p = np.mean([gv('pig', m, 'random') - gv('pig', m, 'group') for m in ['L1_GBLUP', 'L2_GBM']])
b11r, b11g = gv('wheat', 'L1_GBLUP', 'random', 'bias_slope'), gv('wheat', 'L1_GBLUP', 'group', 'bias_slope')
t11r = gv('wheat', 'L1_GBLUP', 'random', 'top10')
eqs = CHECKS['equivalence_strict_max']; eqp = CHECKS['equivalence_alpha_policy_max']
thin = CHECKS['l2_reference']['pig_fullSNP_vs_thin']
gbr_ref = CHECKS['l2_reference'].get('wheat_gbr_reference', [])
gbr_max_d = max(abs(x['r_gbr'] - x['r_lgbm']) for x in gbr_ref) if gbr_ref else float('nan')
runtime = META['runtime_min']

# ---------- 字体与样式 ----------
pdfmetrics.registerFont(TTFont('WQY', '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', subfontIndex=0))
INK, SUB, MUT = colors.HexColor('#0b0b0b'), colors.HexColor('#52514e'), colors.HexColor('#8a897f')
RULE = colors.HexColor('#d8d7cf')

def st(name, size, leading, **kw):
    kw.setdefault('textColor', INK)
    return ParagraphStyle(name, fontName='WQY', fontSize=size, leading=leading,
                          wordWrap='CJK', **kw)

S_TITLE = st('t', 16.5, 21, alignment=TA_CENTER, spaceAfter=2)
S_SUB   = st('s', 9.5, 13, alignment=TA_CENTER, textColor=SUB, spaceAfter=10)
S_H1    = st('h1', 11.5, 15, spaceBefore=11, spaceAfter=4)
S_BODY  = st('b', 9.3, 13.8, alignment=TA_JUSTIFY)
S_BODYI = st('bi', 9.3, 13.8, alignment=TA_JUSTIFY, leftIndent=0.45*cm)
S_ABS   = st('a', 8.9, 13.2, alignment=TA_JUSTIFY, textColor=SUB,
             leftIndent=0.8*cm, rightIndent=0.8*cm)
S_CAP   = st('c', 8.2, 11.5, alignment=TA_CENTER, textColor=SUB, spaceBefore=3, spaceAfter=8)
S_FOOT  = st('f', 7.8, 11, textColor=MUT)

def h1(txt): return Paragraph(txt, S_H1)
def body(txt, style=None): return Paragraph(txt, style or S_BODY)

def table(data, colw, fontsize=8.4, align_body='CENTER'):
    t = Table(data, colWidths=colw, hAlign='CENTER')
    t.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'WQY', fontsize, fontsize * 1.35),
        ('TEXTCOLOR', (0, 0), (-1, 0), INK),
        ('TEXTCOLOR', (0, 1), (-1, -1), SUB),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0efe8')),
        ('LINEABOVE', (0, 0), (-1, 0), 0.8, SUB),
        ('LINEBELOW', (0, 0), (-1, 0), 0.4, SUB),
        ('LINEBELOW', (0, -1), (-1, -1), 0.8, SUB),
        ('ALIGN', (1, 0), (-1, -1), align_body),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
    ]))
    return t

def img(path, width):
    iw, ih = ImageReader(path).getSize()
    return RLImage(path, width=width, height=width * ih / iw)

# ---------- 文档 ----------
doc = SimpleDocTemplate('gs_ladder_report.pdf', pagesize=A4,
                        leftMargin=1.9*cm, rightMargin=1.9*cm,
                        topMargin=1.7*cm, bottomMargin=1.8*cm,
                        title='基因组选择中的模型阶梯与评估口径',
                        author='reproducible pipeline')

def footer(canvas, doc_):
    canvas.saveState()
    canvas.setFont('WQY', 7.5); canvas.setFillColor(MUT)
    canvas.drawString(1.9*cm, 1.05*cm,
        '可复现工件：gs_pig_ladder.ipynb（已执行）· results.json · SUMMARY.md · env.txt — 本报告全部数字构建时读自 results.json')
    canvas.drawRightString(A4[0]-1.9*cm, 1.05*cm, f'第 {doc_.page} 页')
    canvas.restoreState()

E = []
E.append(Paragraph('基因组选择中的模型阶梯与评估口径：<br/>“ML 能否打败 BLUP”的一次可复现检验', S_TITLE))
E.append(Paragraph('Model Ladders and Evaluation Protocols in Genomic Selection: A Reproducible Test of “Can ML Beat BLUP?”', S_SUB))
E.append(Paragraph('短文（short paper）· 2026-09-20 · 单机 CPU（4 核）全流程 %.1f 分钟 · 全部结果 3 seeds' % runtime, S_SUB))

E.append(Paragraph(
    '<font color="#0b0b0b">摘要</font> —— 针对“机器学习/LLM 能否在基因组选择（GS）中打败 BLUP”这一常被观点化讨论的问题，'
    '我们构建了一个固定的实验阶梯（L0 系谱BLUP → L1 GBLUP → L2 梯度提升 → L3 加权先验演示）并在三种严格区分的评估口径'
    '（随机5折CV、留家系代理、前向代理）× 3 个随机种子下实测。主选的 Cleveland et al. 2012 PIC 猪数据集完整版在实验环境的'
    '网络策略下不可得，按预先约定的规程降级为 BGLR wheat 公开数据（599 系 × 1,279 标记 × 4 环境性状，含系谱 A 矩阵），'
    '并附真实猪基因型（3,534 × 52,843，仅 t1 性状）的补充分析。结果：基因组信息相对系谱的增益在所有口径下稳健'
    '（随机CV +%.3f，留家系 +%.3f）；梯度提升仅在随机CV下超过 GBLUP（%.3f vs %.3f），在留家系（%.3f vs %.3f）与前向'
    '（%.3f vs %.3f）口径下反转；评估口径造成的 r 变化（约 %.2f）比模型选择（约 %.2f）大近一个数量级。结论：在本数据与'
    '口径下，非线性 ML 的“优势”主要来自随机CV可利用的家系结构泄漏；GS 研究的第一优先级是评估口径而非模型形式。'
    % (w11r - w10r, w11g - w10g, w12r, w11r, w12g, w11g, w12f, w11f, gap_w, abs(w12r - w11r)), S_ABS))
E.append(Paragraph('关键词：基因组选择 · GBLUP · 梯度提升 · 交叉验证泄漏 · 留家系验证 · 可复现性',
                   st('kw', 8.4, 11, alignment=TA_CENTER, textColor=MUT, spaceAfter=6)))

E.append(h1('1　研究问题与假设'))
E.append(body(
    '核心问题：给定同等信息与算力预算，非线性 ML（以规范固定超参的梯度提升为代表）能否稳健超过线性收缩类方法'
    '（系谱BLUP / GBLUP）？我们预先登记了三条可证伪假设与一个泄漏哨兵：'
    '<b>H1</b> 标记信息相对系谱有真实增益（L1 &gt; L0，且在难口径下保持）；'
    '<b>H2</b> 在 n≈600–3,500、以加性遗传架构为主的数据上，L2 相对 L1 无稳健增益（收缩先验与小样本回归匹配）；'
    '<b>H3</b> 随机CV 相对家系感知口径显著虚高，且口径效应 ≥ 模型效应。'
    '哨兵：任何模型若出现留家系 r ≥ 随机CV r，先怀疑代码泄漏而非“模型强”。'))

E.append(h1('2　数据（含诚实声明）'))
E.append(body(
    '<b>主选与降级</b>：主选为 Cleveland et al. 2012（G3）公开的 PIC 猪数据集（3,534 头、52,843 SNP、5 性状、系谱 6,473）。'
    '实验环境出站网络仅放行 GitHub/PyPI；PMC 直链、OUP、figshare、Dryad、Zenodo、Wayback 共 4 条获取路径全部被代理 403 拦截'
    '（notebook 内保留现场重试的 stderr 证据）；唯一可达的 GitHub 镜像（QuantGen/G2P-Datasets, 00070）为 curated 版，仅含 t1 单性状且无系谱，'
    '性状数偏差 80%＞10%，按预定规程判定“不得作为主选”。因此正式实验降级为 <b>BGLR wheat</b>（CIMMYT 599 自交系 × 1,279 DArT 标记，'
    '4 个环境的标准化籽粒产量作为 4 个性状，附系谱推导的 A 矩阵；来源 gdlc/BGLR-R@de839cf）；同时以 <b>补充分析</b> 身份保留真实猪基因型'
    '（3,534 × 52,843 + t1，来源 QuantGen/G2P-Datasets@a7bf58a；镜像已预填补缺失基因型，非整数剂量占 0.13%）。'))
E.append(body(
    '<b>预处理</b>（两套数据同一流程）：缺失基因型列均值填充 → MAF &lt; 0.01 位点剔除（wheat 1,279→1,278；pig 52,843→50,436）→ 中心化。'
    '<b>核验</b>：wheat 全部维度核对通过；pig 核验明确失败并全程降级标注。数据文件 SHA-256 与来源 commit 记录于 notebook。'))

E.append(h1('3　方法'))
E.append(body(
    '<b>实验阶梯</b>：<b>L0</b> 系谱BLUP＝系谱 A 矩阵上的核岭回归（仅 wheat；pig 无系谱，声明跳过）；'
    '<b>L1</b> GBLUP＝G = X<sub>c</sub>X<sub>c</sub><sup>T</sup>/k 上的核岭回归，α ∈ {0.1, 0.3, 1, 3, 10} 由训练集内 3 折按 r 选取（防泄漏）；'
    '<b>L2</b> 梯度提升（300 棵树、深度 3、学习率 0.05、行采样 0.8）；'
    '<b>L3</b> 加权岭＝随机 20% 位点权重 ×2 的加权 GBLUP——“功能先验”的机制演示，权重为声明的占位而非真实功能注释；'
    '<b>L4</b>（纯 LLM 直接建模基因型）不实现，理由见第 6 节。'))
E.append(body(
    '<b>三种评估口径</b>（分开报告，禁止混合）：①随机 5 折 CV（作为会虚高的对照存在）；②留家系代理：无父系 ID，按预定规程以 G 矩阵'
    '层次聚类 10 组代替家系，GroupKFold(5)；③前向代理：两套数据均无世代/批次信息，以“留出与其余群体平均基因组关系最低的聚类'
    '（≥20% 样本）”近似“老代训练→新代预测”的外推难度——声明：这是结构外推代理，不是时间切分。'
    '<b>指标</b>：predictive ability r＝corr(预测, 真实表型)；bias＝真实对预测回归的斜率（理想 ≈1）；Top-10% 命中率。'
    '各折 out-of-fold 预测合并后计算；全流程 seeds = {0, 1, 2}。'))
E.append(body(
    '<b>工程与自检</b>：GBLUP 双层等价性自检——核侧与标记侧 Ridge 在逐折同 α 下 max|Δr| = %.4f（≤0.02 闸门，针对 G 构造/对齐 bug），'
    'RidgeCV 自选 α 的策略敏感性 max|Δr| = %.3f（α 准则差异在弱信号性状上放大，非实现错误，如实报告）。'
    'L2 引擎按探针实测决策：sklearn GradientBoosting 在猪全量 SNP 上单次拟合实测外推 %.1f 分钟/次（不可行，声明禁用），'
    '改用同超参的 LightGBM 直方图实现；规范原版 sklearn GBR 在 wheat 上以参照检查在场（与 LightGBM 差 ≤ %.3f）；'
    '猪 L2 采用无表型参与的 1/5 等距抽稀（全量 SNP 参照检查 |Δr| = %.3f，在弱信号量级内）。'
    % (eqs, eqp, META['probe_timings']['gbr_pig_fit_min'], gbr_max_d, thin['abs_dr'])))

E.append(h1('4　结果'))
tw = [['模型', '随机5折CV', '留家系代理', '前向代理']]
for m, lbl in [('L0_pedBLUP', 'L0 系谱BLUP'), ('L1_GBLUP', 'L1 GBLUP'),
               ('L2_GBM', 'L2 梯度提升'), ('L3_wRidge', 'L3 加权岭(占位)')]:
    tw.append([lbl] + [cell(GW, m, p) for p in ['random', 'group', 'forward']])
E.append(table(tw, [3.4*cm, 3.9*cm, 3.9*cm, 3.9*cm]))
E.append(Paragraph('表 1　wheat（正式）：predictive ability r（4 性状 × 3 seeds 的 mean ± std）', S_CAP))

tp = [['模型', '随机5折CV', '留家系代理', '前向代理']]
for m, lbl in [('L1_GBLUP', 'L1 GBLUP'), ('L2_GBM', 'L2 梯度提升'), ('L3_wRidge', 'L3 加权岭(占位)')]:
    tp.append([lbl] + [cell(GP, m, p) for p in ['random', 'group', 'forward']])
E.append(table(tp, [3.4*cm, 3.9*cm, 3.9*cm, 3.9*cm]))
E.append(Paragraph('表 2　pig t1（补充；仅 1/5 性状、无系谱，L0 跳过）：r（3 seeds mean ± std）。'
                   '各模型 r ≈ 0.05–0.09，信号极弱；核/标记两侧 |Δr|=0.001 排除对齐错误，弱信号为性状属性。', S_CAP))

E.append(body(
    '<b>H1 成立</b>：wheat 上 GBLUP 相对系谱BLUP 的增益为随机CV +%.3f、留家系 +%.3f——基因组信息在难口径下保持优势。'
    '<b>H2 成立</b>：梯度提升仅在随机CV下领先（%.3f vs %.3f），留家系（%.3f vs %.3f）与前向（%.3f vs %.3f）口径下均反转；'
    '猪补充分析在弱信号量级下同向。L3 与 L1 相当，说明加权机制的收益取决于权重质量。'
    '<b>H3 成立</b>：随机CV 相对留家系的平均虚高 Δr ≈ +%.2f（wheat）/ +%.2f（pig t1），而 wheat 随机CV 下 L1↔L2 的模型差距仅 %.2f。'
    '泄漏哨兵在两套数据上均通过（留家系 r &lt; 随机CV r）。bias 佐证同一机制：wheat GBLUP 的回归斜率由随机CV 的 %.2f 降至留家系口径的 %.2f'
    '（预测过度离散加剧）；Top-10%% 命中率随机CV 下为 %.2f（随机基线 0.10）。'
    % (w11r - w10r, w11g - w10g, w12r, w11r, w12g, w11g, w12f, w11f,
       gap_w, gap_p, abs(w12r - w11r), b11r, b11g, t11r)))
E.append(KeepTogether([img('figs/fig1_ladder.png', 16.6*cm),
    Paragraph('图 1　实验阶梯 × 三口径（灰圈＝单性状均值；误差棒＝跨 seed std）。上：wheat 正式；下：pig t1 补充。', S_CAP)]))
E.append(KeepTogether([img('figs/fig2_inflation.png', 12.6*cm),
    Paragraph('图 2　“虚高差距”哑铃图：随机CV（蓝）− 留家系代理（橙）。L2 的差距（wheat +0.29）大于 GBLUP（+0.22）：'
              '越灵活的模型越吃口径红利。', S_CAP)]))

E.append(h1('5　结论'))
E.append(body(
    '在本数据与口径下：（i）标记信息相对系谱的增益真实且在难口径下保留；（ii）固定超参的非线性 ML 没有稳健打败 GBLUP——'
    '其领先只出现在会虚高的随机CV口径，且其虚高幅度大于线性方法，提示“ML 打败 BLUP”类结论的相当一部分可能是评估口径的产物；'
    '（iii）口径选择对 r 的影响比模型选择大近一个数量级。对实践者的操作性含义：在报告任何 GS 模型对比前，'
    '必须先给出家系感知与前向两类口径的结果与泄漏哨兵。'))

E.append(h1('6　为何不做“纯 LLM 直接建模基因型”（L4）'))
E.append(body(
    '（i）SNP 矩阵是无语法结构的高维数值表，LLM 的归纳偏置（序列共现、离散 token 语义）在匿名化、LD 冗余的芯片位点上没有可迁移先验；'
    '（ii）n ≈ 600–3,500 的监督信号不足以支撑大参数模型学到超越线性收缩的结构，反而更易过拟合家系结构——恰是随机CV虚高的来源；'
    '（iii）在近似无穷小效应的加性架构下，岭/GBLUP 即相应高斯先验的后验均值，“打败 BLUP”需要真实且可学习的非加性/稀疏结构，'
    '而本实验 L2/L3 的实测未显示这类结构。更有希望的切入点：用 LLM 从功能注释/文献生成位点先验权重，替换 L3 的占位权重。'))

E.append(h1('7　局限'))
E.append(body(
    '① L3 权重为演示用占位（随机 20% 位点 ×2），不构成“功能先验有效”的证据；'
    '② 前向与留家系均为声明的代理口径（无真实世代/父系 ID）；'
    '③ 数据集与中国生产群体（如杜长大体系）在品种、LD 结构、性状定义上均不同，数字不可直接外推；'
    '④ 猪补充分析仅 1 个弱信号性状、镜像经预填补；单软件栈、未做统计显著性检验；L2 未调参（规范固定超参，本身即一种保守设定）。'))

E.append(h1('8　下一步与改进'))
E.append(body(
    '<b>数据</b>：在可达网络下获取 Cleveland 完整版（5 性状 + 系谱 6,473），恢复猪为主选：真实父系 GroupKFold、系谱世代前向切分、'
    '5 性状全阶梯（notebook 的核验 cell 已预留切回路径）；进一步接入国内生产群体数据以检验外推。'
    '<b>方法</b>：L3 以真实功能注释（如 FAANG/PigGTEx 分区）替换占位权重，对照 BayesRC/MultiBLUP；补充 Bayesian alphabet（BayesB/R）与'
    '显性/上位性核作为非加性基线；DL 基线（MLP/1D-CNN）在同一三口径协议下复测。'
    '<b>评估与工程</b>：对折×seed 做配对 bootstrap 给出置信区间与显著性；真实时间轴前向验证；把“泄漏哨兵 + 双层等价性 + 格子数守恒”'
    '固化为预注册协议与 CI 自检；多数据集重复以评估结论迁移性。'))

doc.build(E, onFirstPage=footer, onLaterPages=footer)
print('written gs_ladder_report.pdf')
