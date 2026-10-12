# 每周期报告复现

在本目录执行：

```sh
python3 -B fetch_weekly.py
python3 -B generate_weekly_report.py
python3 -B render_cycle_charts.py
```

首个命令使用项目现有付费行情客户端和凭据，仅下载历史行情。报告默认7/31周期；下拉选择其他周期。Markdown配套每周期PNG。7/31起的七个周期固定在下载脚本，后续新增周需扩展选约流程。所有收益为未扣费用的估值，非保证成交价。没有启动定时任务。
