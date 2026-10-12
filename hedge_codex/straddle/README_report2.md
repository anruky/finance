# 报告2最新数据复现

当前行情截至美东2026-10-07，共10轮，其中9轮已到期。每轮1 Call+1 Put，原入场与费用口径不变。

下载最新行情：python3 -B refresh_latest.py
重算报告2及优化报告3：python3 -B recompute_latest.py

不刷新行情只重建报告2：python3 -B generate_report2.py

原报告1维持旧数据。当前更新采用 refresh_latest.py 的增量流程。
