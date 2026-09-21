"""管线节点：qc / merge / retrain / validate / mating / report。

每个节点暴露 run(config, batch_id) -> summary dict，通过磁盘产物解耦，
核心算法为纯函数，便于独立单测（tests/ 对每个节点均有断言测试）。
"""
