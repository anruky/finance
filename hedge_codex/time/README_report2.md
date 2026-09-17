# 报告2：1 Call＋1 Put

沿用报告1七个周期、ATM行权价和截至2026-09-16的数据区间。股票不持仓，仅为涨跌幅参考。两腿必须在10:00之后同一股票成交分钟均有成交，以分钟开盘价估算入场。共同分钟比报告1更晚时，明确记录，不伪造10:00成交。

复现：
```sh
python3 -B fetch_report2.py
python3 -B generate_report2.py
```

行情文件为report2_market_data.json；计算账本为skhy_report2_cycles.json。HTML默认7/31周期。所有损益未扣佣金和价差，不保证成交；到期用经济内在价值，不模拟实物交割。报告1的gav复盘仅保留为参考。
