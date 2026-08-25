#!/usr/bin/env python3
"""
DRAM ETF 对冲策略最终报告生成器
================================
按 final_report_0818.html 的格式，输出 v10 最优策略（7 天 + 15% 熔断）的完整报告。
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram/dram_final_report.html"

# 复用 v10 的核心逻辑
exec(open(os.path.join(os.path.dirname(__file__), "real_options_backtest_v10.py")).read().split("def pc(")[0])
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram/dram_final_report.html"  # 覆盖 exec 引入的 v10 输出路径

TARGET_LABELS = {2: "最近周五(1-4天)", 7: "7天(6-11天)", 14: "14天(13-18天)", 21: "21天(20-21天)"}
MOVES = [8, 10, 15, 20]


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def main():
    data, day_map = load_3fri()
    stock, closes, bars = load_stock()
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]

    bh = bh_benchmark(stock, closes)
    bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0

    # 16 组合扫描
    results = []
    for target in TARGET_LABELS:
        for m in MOVES:
            r = run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, m, target)
            r["target"] = target
            r["move"] = m
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            results.append(r)

    best = max(results, key=lambda x: x["ratio"])
    results_sorted = sorted(results, key=lambda x: x["ratio"], reverse=True)

    # 最新期权数据(用于"现在如何买")
    last = data[-1]
    last_spot = last["spot"]
    latest_date = last["date"]
    # 次近周五(7天) ATM put（跳过 dte=0 的当天到期期权）
    near_f = min([f for f in last["fridays"] if f["dte"] > 0], key=lambda f: abs(f["dte"] - 7))
    near_atm = min(near_f["puts"], key=lambda p: abs(p["strike"] - last_spot))
    near_expiry = near_f["expiry"]
    near_dte = near_f["dte"]
    near_strike = near_atm["strike"]
    near_vw = near_atm["vw"]
    cost_2 = near_vw * 100 * 2
    up_line = last_spot * 1.15
    dn_line = last_spot * 0.85

    # 韩股领先关系数据（三星/海力士 vs DRAM 半年归一化对比）
    kr_data = json.load(open(os.path.join(os.path.dirname(__file__), "kr_dram_compare.json")))

    generate_html(best, results_sorted, bh, bh_ratio,
                  last_spot, latest_date, near_expiry, near_dte, near_strike, near_vw,
                  cost_2, up_line, dn_line, kr_data)


def generate_html(best, results_sorted, bh, bh_ratio, last_spot, latest_date,
                  near_expiry, near_dte, near_strike, near_vw, cost_2, up_line, dn_line, kr_data):
    # 韩股领先关系数据
    kr_dates = json.dumps(kr_data["dates"])
    kr_sam = json.dumps(kr_data["samsung"])
    kr_hyn = json.dumps(kr_data["hynix"])
    kr_dram = json.dumps(kr_data["dram"])
    c = kr_data["corr"]
    # 最优策略明细
    best_rounds = "\n".join(f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['kind']}</td>
<td>${rd['entry_spot']:.1f}</td>
<td>${rd['exit_spot']:.1f}</td>
<td>${rd['strike']:.0f}</td>
<td class="{pc(rd['stock_pnl'])}">${rd['stock_pnl']:+,.0f}</td>
<td class="c-green">-${rd['put_cost']:,.0f}</td>
<td class="c-red">${rd['put_income']:+,.0f}</td>
<td class="{pc(rd['stock_pnl']+rd['pnl'])}">${rd['stock_pnl']+rd['pnl']:+,.0f}</td>
</tr>""" for rd in reversed(best["rounds"]))

    # 情景损益表(假设持有到期的微笑曲线)
    scenario_rows = []
    for pct in [-25, -20, -15, -10, -5, 0, 5, 10, 15, 20]:
        exit_ = last_spot * (1 + pct / 100)
        stock_pnl = (exit_ - last_spot) * 100
        payoff = max(near_strike - exit_, 0) * 200
        net = stock_pnl + payoff - cost_2
        scenario_rows.append(f"""<tr>
<td>{exit_:.2f}</td>
<td>{pct:+d}%</td>
<td class="{pc(stock_pnl)}">{stock_pnl:+,.0f}</td>
<td class="{pc(payoff)}">{payoff:+,.0f}</td>
<td class="{pc(net)}">{net:+,.0f}</td>
<td class="{pc(net)}">{net/(last_spot*100)*100:+.1f}%</td>
</tr>""")
    scenario_html = "\n".join(scenario_rows)

    mdd_reduce = bh["mdd_pct"] - best["mdd_pct"]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM ETF 对冲策略最终报告（周期×熔断线优化）</title>
<style>
:root {{ --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }}
.wrap {{ max-width:1080px; margin:0 auto; }}
h1 {{ font-size:26px; margin-bottom:6px; }}
h2 {{ font-size:19px; margin:32px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }}
.kpi .label {{ color:var(--muted); font-size:12px; }}
.kpi .value {{ font-size:22px; font-weight:700; margin-top:4px; }}
.kpi .sub {{ color:var(--muted); font-size:12px; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }}
th {{ background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }}
th:first-child, td:first-child {{ text-align:left; }}
.c-red {{ color:var(--red); font-weight:600; }}
.c-green {{ color:var(--green); font-weight:600; }}
.c-gray {{ color:var(--muted); }}
.c-gold {{ color:var(--gold); font-weight:700; }}
.callout {{ background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }}
.callout-gold {{ background:rgba(245,195,68,.08); border:1px solid rgba(245,195,68,.35); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.tbl-scroll {{ overflow-x:auto; }}
</style>
</head>
<body>
<div class="wrap">
<h1>DRAM ETF 对冲策略最终报告 <span style="color:var(--muted);font-size:15px;">（周期 × 熔断线 双参数优化 · 开盘价熔断）</span></h1>
<p class="sub">数据源：DRAM_stock.json（93 交易日）+ DRAM_options_3fri.json（真实 3 周五到期日期权链） · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>策略模型</h2>
<div class="callout">
<strong>股票：2026-04-02 买入 100 股 @ $27.76，一直持有到 2026-08-14 @ $57.32，中间不卖出。</strong><br>
<strong>Put：每次买入「7 天到期」的 ATM put（次近周五，dte 6-11 天）2 张，真实成交价 vw。</strong><br>
<strong>熔断：开盘价相对入场价 跌 15% 或 涨 15% 就开盘平仓 + 重买；盘中不触发。</strong>没触发熔断就持有到期，再滚动下一轮。<br>
<strong>2:1 过度对冲</strong>：2 张 put 覆盖 200 股 vs 持有 100 股，下跌时 put 赔付是股票亏损的 2 倍。<br>
<strong>基准 = B&H</strong>：收益 <span class="c-red">$+2,956</span>，最大回撤 <span class="c-green">$3,587（44.4%）</span>，收益/回撤比 0.82。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
<strong>最优组合：7 天 put + 15% 熔断——这是「不盯盘」前提下的最优策略。</strong>
收益 <span class="c-red">${best['total']:+,.0f}</span>（比 B&H 多赚 <span class="c-red">${best['total']-bh['total']:+,.0f}</span>），
回撤从 44.4% 降到 <span class="c-green">{best['mdd_pct']:.1f}%</span>（降了 <span class="c-red">{mdd_reduce:.1f} 个百分点</span>）。
收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>，是 B&H（0.82）的 <strong class="c-gold">{best['ratio']/bh_ratio:.1f} 倍</strong>。
</div>
<div class="kpis">
<div class="kpi"><div class="label">B&H 收益</div><div class="value c-red">${bh['total']:+,.0f}</div><div class="sub">回撤 {bh['mdd_pct']:.1f}% · 比 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">策略收益</div><div class="value c-red">${best['total']:+,.0f}</div><div class="sub">7天 + 15%</div></div>
<div class="kpi"><div class="label">策略回撤比例</div><div class="value c-red">{best['mdd_pct']:.1f}%</div><div class="sub">回撤 ${best['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">回撤比例降幅</div><div class="value c-red">{mdd_reduce:.1f}%</div><div class="sub">44.4% → {best['mdd_pct']:.1f}%</div></div>
<div class="kpi"><div class="label">收益/回撤比</div><div class="value c-gold">{best['ratio']:.2f}</div><div class="sub">B&H 为 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">股票收益</div><div class="value c-red">${best['stock_pnl']:+,.0f}</div><div class="sub">put 净 {money(best['put_net'])}</div></div>
</div>
<p class="note">回撤比例 = 最大回撤 ÷ 峰值净值。收益/回撤比 = 总收益 ÷ 最大回撤，越高越好。</p>
</div>

<div class="card">
<h2>策略演进：为什么是 15% 熔断 + 7 天</h2>

<div class="callout">
<strong>触发价口径对比</strong>——盘中价 vs 开盘价：
</div>
<div class="tbl-scroll">
<table>
<tr><th>触发口径</th><th>盯盘需求</th><th>最优熔断线</th><th>收益</th><th>回撤</th><th>收益/回撤比</th></tr>
<tr><td>盘中价（high/low）</td><td>需盯盘</td><td>8%</td><td class="c-red">$+3,455</td><td>13.2%</td><td><strong class="c-gold">4.32</strong></td></tr>
<tr><td>开盘价（open）</td><td>不盯盘</td><td><strong class="c-gold">15%</strong></td><td class="c-red">$+3,630</td><td>28.5%</td><td>1.91</td></tr>
</table>
</div>
<p class="note">规律：触发信号越迟钝（盘中 → 开盘），最优熔断线越宽（8% → 15%）。盘中熔断捕捉能力更强（比 4.32），开盘熔断不盯盘但能力弱（比 1.91）。</p>

<h2>为什么是 15% 熔断</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>开盘价只捕捉「跳空」</strong>：盘中 low/high 的波动不触发，只有开盘跳空才触发。</li>
<li><strong>DRAM 跳空 8% 很常见，且往往是趋势延续</strong>：涨 8% 熔断追高重买，第二天又跳空高开，新 put 又变虚值，反复亏权利金——8% 熔断 23 次、put 净亏 $1,410。</li>
<li><strong>跳空 15% 才是真正的趋势转折</strong>（见顶/见底），此时熔断重开才划算——15% 只触发 7 次、put 净赚 $674。</li>
<li>所以「不盯盘、只看开盘」的口径下，熔断线必须放宽到 15%，才能过滤掉趋势延续的假信号。</li>
</ul>
<div class="callout">
<strong>已验证不对称组合</strong>：跌/涨熔断线独立扫描（跌 10/15/20/25% × 涨 10/15/20/25%），
<strong class="c-gold">跌 15% + 涨 15%（对称）仍是全局最优（收益/回撤比 1.91）</strong>，任何不对称组合都无法超过它。
关键在「涨 15%」这一档：涨 10% 太灵敏（比 1.76）、涨 20% 太迟钝（比 1.85），涨 15% 最划算。
</div>

<h2>为什么是 7 天（不是最近周五、也不是周一）</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>数据只有周五到期</strong>：DRAM 期权历史只有周五到期（加 3 个节假日顺延周四），周一/周三到期 8 月才上市、历史数据拉不到，所以周期只能选周五。</li>
<li><strong>7 天最优（次近周五）</strong>：15% 熔断下，7天($3,630) &gt; 最近周五1-4天($3,063) &gt; 14天($2,060) &gt; 21天($1,866)。7 天是平衡点——比长周期便宜、比 1-4 天稳定（避开节假日 dte=0 边界、滚动不过于频繁）。</li>
</ul>

<div class="callout-gold">
<strong>更好的策略是「盘中熔断 8%」（收益/回撤比 4.32），但需要盯盘。</strong><br>
本报告的「开盘价 15%」是 <strong class="c-gold">不盯盘前提下的最优策略</strong>——用每天只看一次开盘，换取放弃盘中捕捉波动的能力（收益/回撤比从 4.32 降到 1.91）。
</div>
</div>

<div class="card">
<h2>最优策略逐轮明细：7 天 + 15% 熔断</h2>
<p style="font-size:14px;margin-bottom:10px;">共 {best['n_rounds']} 轮（跌熔断 {best['down_hits']} 次 / 涨熔断 {best['up_hits']} 次 / 到期 {best['expiries']} 次）。股票不动收益 {money(best['stock_pnl'])}；put 净 {money(best['put_net'])}。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>入场spot</th><th>出场spot</th><th>行权价</th><th>股票涨跌</th><th>put成本</th><th>put收入</th><th>周期总利润</th></tr>
{best_rounds}
</table>
</div>
<p class="note">周期总利润 = 股票涨跌 + put收入 − put成本。倒序排列（最近的交易在最上）。</p>
</div>

<div class="card">
<h2>现在如何买（基于最新期权数据 {latest_date}）</h2>
<div class="callout-gold">
最新 DRAM 现价 <strong class="c-gold">${last_spot:.2f}</strong>，最近到期日 <strong>{near_expiry}</strong>（dte {near_dte} 天）。
按最优策略 <strong class="c-gold">7 天 + 15% 熔断</strong>，现在应这样操作：
</div>
<ol style="font-size:14px;padding-left:22px;line-height:2.0;">
<li><strong>持有 100 股 DRAM</strong>（市值 ${last_spot*100:,.0f}），一直持有不动。</li>
<li><strong>买入 2 张行权价 ${near_strike:.0f} 的 Put</strong>（现价 ${last_spot:.2f} 最接近的平值档），到期日 {near_expiry}。</li>
<li>该档 Put 成交量加权价 <strong>${near_vw:.2f}/股</strong>，每张 ${near_vw*100:,.2f}，2 张共 <strong class="c-green">-${cost_2:,.0f}</strong>（占持仓 {cost_2/(last_spot*100)*100:.1f}%）。</li>
<li><strong>熔断线 15%</strong>：开盘价涨到 <strong class="c-red">${up_line:.2f}</strong> 或跌到 <strong class="c-green">${dn_line:.2f}</strong> 就开盘平仓 put + 重买（盘中不盯盘）。</li>
<li>没触发熔断就持有到 {near_expiry} 到期，再滚动下一轮 7 天 put。</li>
</ol>
<div class="tbl-scroll">
<table>
<tr><th>到期日 spot</th><th>涨跌</th><th>股票 P&L</th><th>Put 赔付</th><th>净 P&L</th><th>净收益率</th></tr>
{scenario_html}
</table>
</div>
<p class="note">净 P&L = 股票 P&L + Put 赔付 − 保费（2 张 ${cost_2:,.0f}）。这是「微笑曲线」：<strong>大涨赚（股票）、大跌也赚（2:1 过度对冲）、只有横盘小波动亏保费</strong>。注意：实际涨跌 15% 会触发熔断提前平仓，不会真的持有到期。</p>
</div>

<div class="card">
<h2>韩股领先关系：三星 / 海力士 vs DRAM（半年归一化）</h2>
<p style="font-size:13px;color:var(--muted);margin-bottom:10px;">三星电子、SK海力士（韩国盘）vs DRAM ETF（美股盘），收盘价归一化，起点=100。</p>
<div style="display:flex;flex-wrap:wrap;gap:18px;margin-bottom:10px;font-size:13px;color:var(--muted);">
<span style="display:flex;align-items:center;gap:6px;"><span style="width:16px;height:3px;border-radius:2px;background:#4da3ff;"></span>三星电子 +44%</span>
<span style="display:flex;align-items:center;gap:6px;"><span style="width:16px;height:3px;border-radius:2px;background:#f5a05a;"></span>SK海力士 +101%</span>
<span style="display:flex;align-items:center;gap:6px;"><span style="width:16px;height:3px;border-radius:2px;background:#26c281;"></span>DRAM ETF +96%</span>
</div>
<div style="position:relative;height:340px;">
<canvas id="krChart" role="img" aria-label="三星电子、SK海力士、DRAM ETF 半年归一化价格平滑曲线对比"></canvas>
</div>
<div class="tbl-scroll" style="margin-top:14px;">
<table>
<tr><th>领先 / 滞后关系（日涨跌幅相关系数）</th><th>三星</th><th>海力士</th></tr>
<tr><td>韩股当天 vs DRAM 当天（韩股先动）</td><td class="c-red">0.42</td><td class="c-red">0.45</td></tr>
<tr><td>DRAM 隔夜 vs 韩股次日（美股先动）</td><td class="c-red">0.39</td><td class="c-red">0.45</td></tr>
<tr><td>韩股当天 vs DRAM 次日（跨天预测）</td><td class="c-green">-0.16</td><td class="c-green">-0.21</td></tr>
</table>
</div>
<p class="note"><strong>结论</strong>：不是韩股单方面领先，而是<strong>双向传导</strong>——韩股当天先动、DRAM 当天跟随（0.42~0.45），美股隔夜动、韩股次日跟随（0.39~0.45），强度相当。海力士与 DRAM 高度同步（+101% vs +96%），是最佳「当天」先行指标；但韩股当天信息当天就被 DRAM 消化，无法跨天预测。对开盘价熔断策略的启示：每天收盘看海力士/三星涨跌，可提前约 8 小时预判当晚 DRAM 开盘方向。</p>
</div>

<div class="card">
<h2>数据与结论说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>真实成交价</strong>：Put 成本用每日期权链的成交量加权价（vw），不是 Black-Scholes 理论价 + 假设 IV。</li>
<li><strong>多到期日数据</strong>：DRAM_options_3fri.json 每天含 3 个周五到期日（dte 1-4 / 6-11 / 13-21 天），可真实对比不同周期，无需 BS 外推。</li>
<li><strong>开盘价熔断</strong>：只在美国开盘瞬间判断一次（开盘价 vs 入场价涨跌 15%），盘中 low/high 不触发——符合「不盯盘」的实盘操作。</li>
<li><strong>回撤口径</strong>：逐日净值 = 股票市值 + 累计 Put 现金流，MDD = 峰值到谷底最大回撤。</li>
<li><strong>7 天最优</strong>：15% 熔断下 7天($3,630) 优于最近周五1-4天($3,063)、14天($2,060)、21天($1,866)。7 天是权利金成本与滚动频率的平衡点。</li>
<li><strong>未计交易摩擦</strong>：实盘佣金 + bid-ask 价差会吃掉部分优势，周期越短越明显。</li>
<li><strong>结果依赖这段行情</strong>：DRAM 先涨后暴跌（$27.76 → ~$80 → $44.85），高波动是策略赚钱的前提。仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
new Chart(document.getElementById('krChart'), {{
  type: 'line',
  data: {{ labels: {kr_dates}, datasets: [
    {{ label: '三星电子', data: {kr_sam}, borderColor: '#4da3ff', backgroundColor: '#4da3ff', borderWidth: 2, pointRadius: 0, tension: 0.4, cubicInterpolationMode: 'monotone', fill: false }},
    {{ label: 'SK海力士', data: {kr_hyn}, borderColor: '#f5a05a', backgroundColor: '#f5a05a', borderWidth: 2, pointRadius: 0, tension: 0.4, cubicInterpolationMode: 'monotone', fill: false }},
    {{ label: 'DRAM ETF', data: {kr_dram}, borderColor: '#26c281', backgroundColor: '#26c281', borderWidth: 2, pointRadius: 0, tension: 0.4, cubicInterpolationMode: 'monotone', fill: false, borderDash: [6,4] }}
  ] }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ autoSkip: true, maxTicksLimit: 10, font: {{ size: 11 }}, color: '#9aa3b2' }}, grid: {{ display: false }} }},
      y: {{ title: {{ display: true, text: '归一化（起点=100）', font: {{ size: 11 }}, color: '#9aa3b2' }}, ticks: {{ font: {{ size: 11 }}, color: '#9aa3b2' }}, grid: {{ color: 'rgba(154,163,178,0.15)' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"最终报告已生成: {OUT_HTML}")
    print(f"最优: {TARGET_LABELS[best['target']]} + {best['move']}% 熔断, 收益 ${best['total']:+,.0f}, 回撤 {best['mdd_pct']:.1f}%, 比 {best['ratio']:.2f}")


if __name__ == "__main__":
    main()
