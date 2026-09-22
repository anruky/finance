#!/bin/bash
# ============================================================
# 三标的对冲策略汇总报告 · 一键刷新脚本
# ------------------------------------------------------------
# 用法:
#   ./refresh_summary.sh          默认: 全刷(股票日线 + 期权增量 + 实时指标 + 报告)
#   ./refresh_summary.sh --full   期权全量重拉(慢, 修复历史数据用)
#
# 默认模式走"增量": 期权只拉新增交易日, 所以逐轮明细 / KPI / 技术指标
# 都会一起刷新, 且通常几秒~几十秒完成。
# 注意: 这是美股, 日期统一用美国东部时间(ET)。盘中跑会带入当天未收盘的
# partial bar, 建议美股收盘后(美东 16:00 后, 即北京次日凌晨 04:00 后)刷。
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=/usr/bin/python3
FIN=/Users/gavinz/git/finance
TODAY=$(TZ=America/New_York date +%Y-%m-%d)
MODE="${1:-incr}"

echo "=========================================================="
echo "  三标的对冲策略汇总报告 · 一键刷新"
echo "  日期: $TODAY   模式: $MODE"
echo "=========================================================="

OPTS=""
if [ "$MODE" = "--full" ] || [ "$MODE" = "full" ]; then
  OPTS="--full"
fi

echo ""
echo "== [1/4] 拉取股票日线 (DRAM / SKHY / SNDK) =="
$PY "$FIN/data/data_puller.py" --ticker DRAM --stock-only --start 2026-04-02 --end "$TODAY"
$PY "$FIN/data/data_puller.py" --ticker SKHY --stock-only --start 2026-07-13 --end "$TODAY"
$PY "$FIN/data/data_puller.py" --ticker SNDK --stock-only --start 2026-05-26 --end "$TODAY"

echo ""
echo "== [2/4] 拉取期权链 (3 个周五到期, 增量) =="
$PY "$FIN/hedge/dram/data_puller_3fri.py"    --start 2026-04-02 --end "$TODAY" $OPTS
$PY "$FIN/hedge/sk/data_puller_3fri.py"      --start 2026-07-13 --end "$TODAY" $OPTS
$PY "$FIN/hedge/sandisk/data_puller_3fri.py" --start 2026-05-26 --end "$TODAY" $OPTS

echo ""
echo "== [3/4] 拉取实时技术指标快照 =="
$PY "$FIN/hedge/fetch_realtime.py"

echo ""
echo "== [3.5/4] 拉取 SKHY 早盘快照（final 报告「现在如何买」用开盘价替代全天 vw） =="
$PY "$FIN/hedge/sk/fetch_intraday_snapshot.py"

echo ""
echo "== [4/4] 生成汇总报告 =="
$PY "$FIN/hedge/gen_summary_report.py"

echo ""
echo "=========================================================="
echo "  完成 ✅  报告: $FIN/hedge/summary_report.html"
echo "=========================================================="
open "$FIN/hedge/summary_report.html"
