# 报告2最新数据复现

当前行情截至美东2026-09-23，共8轮，其中7轮已到期。每轮1 Call+1 Put，原入场与费用口径不变。

下载最新行情：python3 -B refresh_latest.py
重算报告2及优化报告3：python3 -B recompute_latest.py

不刷新行情只重建报告2：python3 -B generate_report2.py

原报告1维持旧数据。旧fetch_report2.py基于原报告1的旧行情文件，当前更新采用refresh_latest.py的增量流程。
