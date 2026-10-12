# SKHY 跨式与保护性期权策略报告

目录已由 `time` 改名为 `straddle`。五个报告入口：

| 报告 | 内容 | 打开 |
| --- | --- | --- |
| 报告1 | 每周100股＋2张Put，逐周期收益曲线与解读 | [报告1](skhy_weekly_cycle_report.html) |
| 报告2 | 每周1张Call＋1张Put | [报告2](skhy_report2_straddle.html) |
| 报告3 | 不同平仓策略比较、时间衰减目标、最优策略逐周期成交明细 | [报告3](skhy_report3_all6_time_decay.html) |
| 报告4 | 平仓后轮动开仓：本周五、下周五与期限费用性价比 | [报告4](rotation/skhy_report4_rotation.html) |
| 报告5 | 固定平方根时间选约，比较44组止盈、止损与提前强平规则 | [报告5](rotation/exit_optimization/skhy_report5_exit_optimization.html) |

## 更新与复现

在本目录执行：

```sh
python3 -B refresh_latest.py
python3 -B recompute_latest.py
python3 -B verify_all6.py
```

第一步下载行情，第二步重算报告2和报告3，第三步校验结果。只重建现有报告3可运行 `python3 -B build_all6.py`。报告1的独立流程见 [README_weekly.md](README_weekly.md)。更多说明见 [README_report2.md](README_report2.md) 和 [README_all6.md](README_all6.md)。

## 文件用途

- `brd_gav.md`：原始需求和解读。
- `weekly_*`、`skhy_weekly_*`、`cycle_*.png`：报告1行情、结果、模板和配图。
- `report2_*`、`skhy_report2_*`：报告2行情、模板和结果。
- `report3_inputs/`：报告3使用的行情与周期输入快照，复现时需要保留。
- `all6_*`、`best_exit_cycle_details.json`、`prior_stock_closes.json`：平仓优化结果、候选策略评分、图表与历史股价。
- `*.py`：下载、计算、生成及校验程序；`*manifest.json`：文件校验摘要。
- `skhy_report3_exit_optimization.html` 和 `skhy_20260904_0911_10min_report.html`：兼容已有链接的报告入口。

本次目录整理移除了历史备份、旧单周期版本及已被替代的优化程序和结果；报告2/3已刷新至美东2026-10-07，共10轮，其中9轮已到期；报告1维持原数据。

报告4行情截至美东2026-10-08，独立数据、缓存、程序和说明集中在 `rotation/`，不改动报告1/2/3。

报告5使用相同的2026-07-31至2026-10-08区间，仅保留平方根时间选约，比较44组退出规则；详细文件在 `rotation/exit_optimization/`。
