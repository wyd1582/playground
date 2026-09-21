"""refpop_agent —— 参考群更新 Agent 管线（演示原型）。

端到端流程：新一代数据到达 → QC门禁 → 合并参考群 → 重训GBLUP → 前向验证
→ 选配建议 → HTML报告。

除报告中的中文摘要段（可选 LLM，默认 Mock）外，全部节点为确定性代码、可单测。
本仓库全部数据为模拟生成 —— 见 data/DEFECTS.md 与 README.md 的诚实性声明。
"""

__version__ = "0.1.0"
