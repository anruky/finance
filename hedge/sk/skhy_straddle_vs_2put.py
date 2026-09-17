#!/usr/bin/env python3
"""
SKHY 逐轮对比：跨式(1 call + 1 put) vs 旧策略(100股 + 2 put)
================================================================
用相同参数（最近周五 + 跌15%/涨8%）分别跑两个策略，按「入场日」对齐轮次，
逐轮列出两个策略的【成本 / 收入 / 利润】完整拆解与差距。

结算口径（2026-09-15 修正）：
  熔断平仓一律按「内在价值」结算（不再用全天 vw），消除前视偏差。
  - 涨熔断：put 深度虚值 → 内在价值归零；跨式的 call 端按 max(exit-K,0) 结算
  - 跌熔断：put 实值 → 内在价值 = K − 触发价

- 旧策略 2put ：100 股 + 2 张 ATM put，每轮总利润 = 股票端涨跌 + put 净(put收入−put成本)
- 新策略 straddle：1 call + 1 put（不持股票），每轮净利 = 期权收入 − (call+put 成本)

输出临时报告：skhy_straddle_vs_2put_report.html（不动 final）
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SK = os.path.dirname(os.path.abspath(__file__))
DATA = "/Users/gavinz/git/finance/data"
OUT = os.path.join(SK, "skhy_straddle_vs_2put_report.html")

# ---- 复用两个回测核心（直接 import 模块，不改源文件） ----
sys.path.insert(0, SK)
import real_options_backtest_v10 as v10mod
import rescan_skhy_straddle as st
run_v10 = v10mod.run_v10
run_straddle = st.run_straddle

# 对齐参数（两策略共用）
DOWN = 15
UP = 8
TARGET = 2  # 最近周五


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def main():
    data = json.load(open(os.path.join(DATA, "SKHY_options_3fri.json")))
    day_map = {d["date"]: d for d in data}
    stock = json.load(open(os.path.join(DATA, "SKHY_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}
    se = closes[stock[0][0]]
    sx = closes[stock[-1][0]]

    # 两个策略跑相同参数
    old = run_v10(day_map, closes, bars, stock, se, sx, DOWN, TARGET, num_puts=2, up_pct=UP)
    new = run_straddle(day_map, closes, bars, stock, DOWN, TARGET, up_pct=UP)
    old["ratio"] = old["total"] / old["mdd"] if old["mdd"] > 0 else 0
    new["ratio"] = new["total"] / new["mdd"] if new["mdd"] > 0 else 0

    print(f"2put:  total ${old['total']:+,.0f}  mdd {old['mdd_pct']:.1f}%  ratio {old['ratio']:.2f}  rounds {old['n_rounds']}")
    print(f"strad: total ${new['total']:+,.0f}  mdd ${new['mdd']:,.0f}  ratio {new['ratio']:.2f}  rounds {new['n_rounds']}")

    # 按入场日对齐轮次
    old_by_entry = {rd["entry_date"]: rd for rd in old["rounds"]}
    new_by_entry = {rd["entry_date"]: rd for rd in new["rounds"]}
    entries = [rd["entry_date"] for rd in old["rounds"]]  # 保持时间顺序
    for e in new_by_entry.keys():
        if e not in entries:
            entries.append(e)

    # 组装逐轮完整对比行（含成本/收入/利润）
    rows = []
    wins_old = wins_new = ties = 0
    gap_sum = 0.0
    old_sum = 0.0
    new_sum = 0.0
    max_gap = 0.0
    max_gap_entry = None
    max_gap_winner = None
    for e in entries:
        ro = old_by_entry.get(e)
        rn = new_by_entry.get(e)
        if ro is None or rn is None:
            continue
        old_profit = ro["stock_pnl"] + ro["pnl"]          # 2put 每轮总利润
        new_profit = rn["pnl"]                            # 跨式每轮净利
        gap = old_profit - new_profit
        gap_sum += gap
        old_sum += old_profit
        new_sum += new_profit
        if abs(gap) > abs(max_gap):
            max_gap = gap
            max_gap_entry = e
            max_gap_winner = "2put" if gap > 0 else ("跨式" if gap < 0 else "平")
        if gap > 0.5:
            wins_old += 1
        elif gap < -0.5:
            wins_new += 1
        else:
            ties += 1

        if ro["kind"] == "持有中":
            exit_cell = f'{ro.get("expiry", ro["exit_date"])} 到期'
        else:
            exit_cell = ro["exit_date"]

        winner = ("<span class='c-red'>2put</span>" if gap > 0.5
                  else ("<span class='c-green'>跨式</span>" if gap < -0.5
                        else "<span class='c-gray'>平</span>"))
        rows.append(
            f'<tr>'
            f'<td>{e}</td><td>{exit_cell}</td><td>{ro["kind"]}</td>'
            f'<td>${ro["entry_spot"]:.1f}</td><td>${ro["exit_spot"]:.1f}</td><td>${ro["strike"]:g}</td>'
            # 2put 组
            f'<td class="c-green">-${ro["put_cost"]:,.0f}</td>'
            f'<td class="c-red">${ro["put_income"]:+,.0f}</td>'
            f'<td class="{pc(ro["stock_pnl"])}">${ro["stock_pnl"]:+,.0f}</td>'
            f'<td class="{pc(old_profit)}">${old_profit:+,.0f}</td>'
            # 跨式 组
            f'<td class="c-green">-${rn["call_cost"]:,.0f}</td>'
            f'<td class="c-green">-${rn["put_cost"]:,.0f}</td>'
            f'<td class="c-red">${rn["income"]:+,.0f}</td>'
            f'<td class="{pc(new_profit)}">${new_profit:+,.0f}</td>'
            # 差距
            f'<td class="{pc(gap)}">${gap:+,.0f}</td>'
            f'<td>{winner}</td>'
            f'</tr>')

    rows_html = "\n".join(rows)

    n_aligned = len(rows)
    avg_gap = gap_sum / n_aligned if n_aligned else 0
    total_gap = gap_sum

    # ---- 涨熔断专项：收入 vs 成本对比 ----
    up_rows = []
    for e in entries:
        ro = old_by_entry.get(e)
        rn = new_by_entry.get(e)
        if ro is None or rn is None or ro["kind"] != "上涨再平衡":
            continue
        stock_inc = ro["stock_pnl"]                      # 2put 收入 = 股票端
        call_inc = max(ro["exit_spot"] - ro["strike"], 0.0) * 100  # 跨式收入 = call 内在价值
        cost_2put = ro["put_cost"]                       # 2put 成本 = 2×put 权利金
        cost_strad = rn["call_cost"] + rn["put_cost"]    # 跨式成本 = call + put
        inc_gap = stock_inc - call_inc                   # 收入差（应为行权价档位偏差）
        cost_gap = cost_2put - cost_strad                # 成本差
        net_2put = stock_inc - cost_2put
        net_strad = call_inc - cost_strad
        up_rows.append(
            f'<tr>'
            f'<td>{e}</td><td>${ro["exit_spot"]:.1f}</td><td>${ro["strike"]:g}</td>'
            f'<td class="{pc(stock_inc)}">${stock_inc:+,.0f}</td>'
            f'<td class="{pc(call_inc)}">${call_inc:+,.0f}</td>'
            f'<td class="{pc(-inc_gap)}">${-inc_gap:+,.0f}</td>'
            f'<td class="c-green">${cost_2put:,.0f}</td>'
            f'<td class="c-green">${cost_strad:,.0f}</td>'
            f'<td class="{pc(-cost_gap)}">${-cost_gap:+,.0f}</td>'
            f'<td class="{pc(net_2put)}">${net_2put:+,.0f}</td>'
            f'<td class="{pc(net_strad)}">${net_strad:+,.0f}</td>'
            f'</tr>')
    up_rows_html = "\n".join(up_rows)

    # 涨熔断轮次汇总
    _inc_2put_sum = _inc_strad_sum = _cost_2put_sum = _cost_strad_sum = 0.0
    _n_up = 0
    for e in entries:
        ro = old_by_entry.get(e)
        rn = new_by_entry.get(e)
        if ro is None or rn is None or ro["kind"] != "上涨再平衡":
            continue
        _inc_2put_sum += ro["stock_pnl"]
        _inc_strad_sum += max(ro["exit_spot"] - ro["strike"], 0.0) * 100
        _cost_2put_sum += ro["put_cost"]
        _cost_strad_sum += rn["call_cost"] + rn["put_cost"]
        _n_up += 1

    # ---- 07-14 示例拆解（动态取数，修正口径）----
    ex = old_by_entry.get("2026-07-14")
    ex_html = ""
    if ex:
        ex_stock = ex["stock_pnl"]
        ex_putcost = ex["put_cost"]
        ex_putinc = ex["put_income"]
        ex_putnet = ex["pnl"]
        ex_total = ex_stock + ex_putnet
        ex_new = new_by_entry.get("2026-07-14")
        ex_html = (
            f'<div class="callout" style="background:rgba(245,195,68,.07);border-color:rgba(245,195,68,.3);">'
            f'<strong>示例：07-14 这轮 2put 总利润 ${ex_total:+,.0f} 是怎么来的？（修正后口径）</strong><br>'
            f'入场 spot ${ex["entry_spot"]:.2f}（07-14 开盘）→ 出场 spot ${ex["exit_spot"]:.2f}（07-15 开盘，涨 8.1% 触发涨熔断）：<br>'
            f'① 股票端 <strong>{money(ex_stock)}</strong> = ({ex["exit_spot"]:.2f} − {ex["entry_spot"]:.2f}) × 100 股；<br>'
            f'② put 端 <strong>{money(ex_putnet)}</strong> = put 收入 ${ex_putinc:,.0f} − put 成本 ${ex_putcost:,.0f}（2 张权利金）。'
            f'涨熔断时股价 {ex["exit_spot"]:.1f} 已高于行权价 {ex["strike"]:g}，put 深度虚值、内在价值归零 → put 收入 = $0，'
            f'只亏掉买入时的 2 张权利金 ${ex_putcost:,.0f}。<br>'
            f'合计 {ex_stock:+,.0f} + {ex_putnet:+,.0f} = <strong class="c-gold">${ex_total:+,.0f}</strong>。'
            f'（旧口径曾把全天 vw 的盘中急跌算成 put 收入 ${1115:.0f}，导致虚增到 $1418，已修正。）'
            f'</div>')

    css = """
:root { --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }
.wrap { max-width:1360px; margin:0 auto; }
h1 { font-size:24px; margin-bottom:6px; }
h2 { font-size:18px; margin:30px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }
h3 { font-size:15px; margin:18px 0 8px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:24px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:18px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }
.kpi .label { color:var(--muted); font-size:13px; font-weight:600; }
.kpi .value { font-size:22px; font-weight:700; margin-top:4px; }
.kpi .sub { color:var(--muted); font-size:12px; margin-top:3px; margin-bottom:0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }
th { background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }
th:first-child, td:first-child { text-align:left; }
.grp-2put { background:rgba(255,82,82,.10); color:var(--red); }
.grp-strad { background:rgba(38,194,129,.10); color:var(--green); }
.grp-up { background:rgba(245,195,68,.10); color:var(--gold); }
.c-red { color:var(--red); font-weight:600; }
.c-green { color:var(--green); font-weight:600; }
.c-gray { color:var(--muted); }
.c-gold { color:var(--gold); font-weight:700; }
.callout { background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px;
  padding:12px 16px; margin:12px 0; font-size:13px; line-height:1.9; }
.note { color:var(--muted); font-size:12px; margin-top:8px; }
code { background:#20242d; border:1px solid var(--border); border-radius:4px; padding:1px 6px;
  font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; color:var(--gold); }
.tbl-scroll { overflow-x:auto; }
"""

    def kpi(label, value_html, sub=""):
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value_html}</div><div class="sub">{sub}</div></div>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>SKHY 跨式 vs 2put 逐轮对比（内在价值结算）</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<h1>SKHY 逐轮对比：跨式(1 call + 1 put) vs 旧策略(100股 + 2 put)</h1>
<p class="sub">对齐参数：最近周五 + 跌{DOWN}%/涨{UP}% · 结算口径：熔断平仓按内在价值（已修正前视偏差）· 数据 {stock[0][0]} ~ {stock[-1][0]}（{len(stock)} 交易日） · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="kpis">
{kpi('2put 总利润(逐轮和)', money(old_sum), f'回撤 {old["mdd_pct"]:.1f}% · 比 {old["ratio"]:.2f}')}
{kpi('跨式 总利润(逐轮和)', money(new_sum), f'回撤 ${new["mdd"]:,.0f} · 比 {new["ratio"]:.2f}')}
{kpi('总差距(2put−跨式)', money(total_gap), '正=2put多赚')}
{kpi('平均每轮差距', money(avg_gap), f'共 {n_aligned} 轮对齐')}
{kpi('胜场 2put : 跨式', f'<span class="c-red">{wins_old}</span> : <span class="c-green">{wins_new}</span>', f'平 {ties} 轮')}
{kpi('最大单轮差距', money(max_gap), f'{max_gap_entry} · {max_gap_winner}赢')}
</div>

<div class="callout">
<strong>核心结论（修正口径后）：</strong>两个策略轮次完全对齐（相同入场日、行权价、熔断/到期触发），唯一区别在「结构」：
<strong>2put = 股票端(100股) + 2张put</strong>；<strong>跨式 = 1 call + 1 put（无股票）</strong>。
<strong>{wins_old}</strong> 轮 2put 多赚、<strong>{wins_new}</strong> 轮跨式多赚、{ties} 轮打平，14 轮求和差距仅 <strong>${total_gap:+,.0f}</strong>。
修正前视偏差后，两者仍然五五开——慢牛里 2put 靠「股票腿」吃肉，跨式靠「波动放大轮次」追回，谁也没明显跑赢谁。
</div>

{ex_html}

<div class="card">
<h2 style="margin-top:0;">涨熔断轮次专项：收入几乎一样，差异全在成本</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">
涨熔断时，两策略都在「吃上涨」：<strong>2put 靠股票腿</strong>（收入 = 出场spot − 入场spot），<strong>跨式靠 call 腿</strong>（收入 = 出场spot − 行权价）。
两者收入差 = 行权价档位偏差（入场spot 与 ATM 行权价之间那几块钱），因此<strong>收入几乎一样</strong>，真正的差异在<strong>成本</strong>：
2put 付出 <strong>2×put 权利金</strong>，跨式付出 <strong>call + put 权利金</strong>。
</p>
<div class="tbl-scroll">
<table>
<tr>
<th rowspan="2">入场日</th><th rowspan="2">出场spot</th><th rowspan="2">行权价</th>
<th colspan="3" class="grp-up" style="text-align:center;">收入（吃上涨）</th>
<th colspan="3" class="grp-up" style="text-align:center;">成本（权利金）</th>
<th colspan="2" class="grp-up" style="text-align:center;">净利</th>
</tr>
<tr>
<th>2put(股票端)</th><th>跨式(call端)</th><th>收入差</th>
<th>2put(2×put)</th><th>跨式(call+put)</th><th>成本差</th>
<th>2put</th><th>跨式</th>
</tr>
{up_rows_html}
</table>
</div>
<p class="note">「收入差」= 2put收入 − 跨式收入（正值=2put多赚这段，即行权价档位偏差）；「成本差」= 2put成本 − 跨式成本（负值=跨式成本更高）。涨熔断轮次合计：2put 收入 ${_inc_2put_sum:+,.0f} / 跨式收入 ${_inc_strad_sum:+,.0f}；2put 成本 ${_cost_2put_sum:,.0f} / 跨式成本 ${_cost_strad_sum:,.0f}。</p>
</div>

<div class="card">
<h2 style="margin-top:0;">逐轮完整对照（含成本 / 收入 / 利润）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">
「2put」= 100 股 + 2 张 ATM put（put成本为 2 张权利金）；「跨式」= 1 张 ATM call + 1 张 ATM put（同行权价同到期日）。
绿色 = 成本（支出），红色 = 收入（流入）。「2put总利润」= put净 + 股票端；「跨式净利」= 期权收入 − (call+put 成本)；「差距」= 2put总利润 − 跨式净利（正=2put多赚，负=跨式多赚）。
</p>
<div class="tbl-scroll">
<table>
<tr>
<th rowspan="2">入场日</th><th rowspan="2">出场日</th><th rowspan="2">方式</th>
<th rowspan="2">入场spot</th><th rowspan="2">出场spot</th><th rowspan="2">行权价</th>
<th colspan="4" class="grp-2put" style="text-align:center;">2put（100股 + 2 put）</th>
<th colspan="4" class="grp-strad" style="text-align:center;">跨式（1 call + 1 put）</th>
<th rowspan="2">差距</th><th rowspan="2">本轮胜者</th>
</tr>
<tr>
<th>put成本</th><th>put收入</th><th>股票端</th><th>总利润</th>
<th>call成本</th><th>put成本</th><th>期权收入</th><th>净利</th>
</tr>
{rows_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>结算口径（2026-09-15 修正）</strong>：熔断平仓一律按<strong>内在价值</strong>结算，不再用全天成交量加权价 vw。旧口径在「开盘触发熔断、但全天 vw 含盘中反向波动」的日子会产生前视偏差（如 07-15 开盘 181.81 触发涨熔断卖出，put 却按全天 vw（含盘中暴跌到 166 的成交）结算出 $1115 虚增收入）。修正后：涨熔断时 put 深度虚值→内在价值归零；跌熔断时 put 实值→内在价值 = 行权价 − 触发价。</li>
<li><strong>对齐口径</strong>：两策略都用相同参数（最近周五 + 跌{DOWN}%/涨{UP}%），且都用「最近周五的 ATM 行权价」，因此每一轮的入场日、出场日、行权价、触发方式完全一致，可逐轮直接对比。</li>
<li><strong>2put 每轮总利润</strong> = 股票端涨跌(stock_pnl) + put 净(pnl)。其中 put 净 = put 收入 − put 成本（2 张权利金）。</li>
<li><strong>跨式每轮净利</strong> = (call 收入 + put 收入) − (call 成本 + put 成本)。无股票本金，回撤为纯现金绝对金额。</li>
<li><strong>涨熔断时收入为何几乎一样</strong>：2put 股票端收入 = (出场spot − 入场spot)×100；跨式 call 端收入 = (出场spot − 行权价)×100。入场spot 与 ATM 行权价只差一个档位（≤$2.5），所以两者收入几乎相等，差异集中在成本端。</li>
<li><strong>口径说明</strong>：顶部「总利润(逐轮和)」= 14 轮逐轮净现金流之和（从首日开盘价起算），与逐轮明细严格自洽。run_v10 报告的官方 total（${old['total']:,.0f}）额外包含「首日收盘价→首日开盘价」这段股票基准差，故两者不同——本对比统一用逐轮口径。</li>
<li><strong>回撤口径不同</strong>：2put 为「相对股票市值百分比」，跨式为「现金净值绝对金额」，两者回撤数字不可直接比；但「收益/回撤比」均按 总收益÷最大回撤(绝对金额) 计算，可对比。</li>
<li><strong>本程序为临时对比</strong>（<code>skhy_straddle_vs_2put.py</code>），不改动 final 报告；但本次已同步修正核心回测 <code>real_options_backtest_v10.py</code> / <code>rescan_skhy_straddle.py</code> 的熔断结算口径（这是对所有标的都生效的 bug 修复）。</li>
<li><strong>过拟合警示</strong>：SKHY 仅 {len(stock)} 个交易日，样本短、波动大，仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""

    with open(OUT, "w") as f:
        f.write(html)
    print(f"\n对比报告已生成: {OUT}")
    print(f"  2put 逐轮和 ${old_sum:+,.0f} vs 跨式 ${new_sum:+,.0f}，总差距 ${total_gap:+,.0f}")
    print(f"  胜场: 2put {wins_old} / 跨式 {wins_new} / 平 {ties}，平均每轮差距 ${avg_gap:+,.0f}")
    print(f"  涨熔断轮次 {_n_up} 轮：收入 2put {_inc_2put_sum:+,.0f}/跨式 {_inc_strad_sum:+,.0f}，成本 2put {_cost_2put_sum:,.0f}/跨式 {_cost_strad_sum:,.0f}")


if __name__ == "__main__":
    main()
