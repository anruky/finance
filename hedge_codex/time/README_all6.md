# 最新周期策略研究

数据截至美东2026-09-23，8轮中7轮已到期，全部参与训练；未到期轮仅展示。沿用19,977条候选、毛收益与原执行口径。

刷新与复现：
```sh
python3 -B refresh_latest.py
python3 -B recompute_latest.py
```

refresh_latest.py复用已确认的旧合约和旧已到期数据，只增量下载新周期及未完整周期；download_cache保存下载缓存。API密钥读取现有数据程序，不写入报告。recompute_latest.py先生成报告2账本，再更新report3_inputs快照，重算排名、验证、生成报告3。

无需网络的重算：analyze_all6.py → verify_all6.py → build_all6.py。

全部已到期周期均用于选参，不保留验证集。策略结果是样本内最优，不保证未来最优。期权价已包含时间价值，不额外重复扣Theta。
