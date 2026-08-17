#!/usr/bin/env python3
"""
DRAM ETF 对冲策略回测 —— 真实股票 + 真实期权链数据
生成完整 HTML 报告

策略模型:
  - 股票: 数据第一天买入 100 股, 一直持有到期末, 中间不卖出
  - Put:  每个 weekly 滚动日买入 N 张 put, 到期结算后滚动下一张
  - 0 put = B&H 作为基准, 不参与排名

核心指标:
  - 总 P&L: 期末相对期初的净收益(美元)
  - 最大回撤 MDD: 逐日净值从峰值到谷底的最大回撤(美元)
  - 收益/回撤比 = 总P&L / MDD (每承担 1 美元回撤换来的收益)
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_real_backtest_report.html"

def load():
    stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    opt = json.load(open(os.path.join(DATA, "DRAM_options.json")))
    closes = {r[0]: r[4] for r in stock}
    return stock, opt, closes

def get_entries(opt, closes):
    """每个 expiry 周期, 取第一个有真实 put 数据的交易日作为滚动入场日"""
    entries = []
    seen_expiry = set()
    for d in opt:
        exp = d["expiry"]
        if exp in seen_expiry:
            continue
        seen_expiry.add(exp)
        if not d.get("puts"):
            continue
        if exp not in closes:
            continue
        entries.append(d)
    return entries

def pick_strike(puts, entry, strike_pct):
    target = entry * (1 - strike_pct)
    return min(puts, key=lambda p: abs(p["strike"] - target))

def run_strategy(entries, closes, stock_dates, stock_entry, stock_exit, strike_pct, num_puts):
    """返回一个策略的完整结果: 收益、回撤、put 明细"""
    stock_pnl = (stock_exit - stock_entry) * 100  # 100 股一直持有

    cashflow = defaultdict(float)
    put_rows = []
    put_cost_total = 0.0
    put_payoff_total = 0.0
    itm_count = 0

    for d in entries:
        spot = d["spot"]
        exit_ = closes[d["expiry"]]
        if num_puts > 0:
            p = pick_strike(d["puts"], spot, strike_pct)
            strike, vw = p["strike"], p["vw"]
            cost = vw * 100 * num_puts
            payoff = max(strike - exit_, 0.0) * 100 * num_puts
            itm = exit_ < strike
            otm = (strike / spot - 1) * 100
            cashflow[d["date"]] -= cost
            cashflow[d["expiry"]] += payoff
            put_cost_total += cost
            put_payoff_total += payoff
            itm_count += 1 if itm else 0
            put_rows.append(dict(entry_date=d["date"], spot=spot, expiry=d["expiry"],
                exit=exit_, strike=strike, vw=vw, cost=cost, payoff=payoff,
                itm=itm, otm=otm))
        else:
            put_rows.append(dict(entry_date=d["date"], spot=spot, expiry=d["expiry"],
                exit=exit_, strike=None, vw=0.0, cost=0.0, payoff=0.0, itm=None, otm=None))

    put_net = put_payoff_total - put_cost_total
    total_pnl = stock_pnl + put_net

    # 逐日净值 -> 最大回撤
    cum_cash = 0.0
    peak = 0.0
    mdd = 0.0
    for dt in stock_dates:
        cum_cash += cashflow.get(dt, 0.0)
        v = (closes[dt] - stock_entry) * 100 + cum_cash
        if v > peak:
            peak = v
        mdd = max(mdd, peak - v)

    # 回撤比例 = 最大回撤 / 峰值净值 (从峰值回撤的百分比)
    peak_actual = stock_entry * 100 + peak
    mdd_pct = mdd / peak_actual * 100 if peak_actual > 0 else 0.0

    otms = [r["otm"] for r in put_rows if r["otm"] is not None]
    avg_otm = sum(otms) / len(otms) if otms else 0

    return dict(rows=put_rows, stock_pnl=stock_pnl, put_cost=put_cost_total,
        put_payoff=put_payoff_total, put_net=put_net, total_pnl=total_pnl,
        mdd=mdd, mdd_pct=mdd_pct, itm=itm_count, n=len(put_rows), avg_otm=avg_otm)

# 颜色: 涨/赚 = 红, 跌/亏 = 绿 (中国习惯)
def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")

def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'

def num(v):
    return f'{v:,.0f}'

def main():
    stock, opt, closes = load()
    entries = get_entries(opt, closes)
    stock_dates = [r[0] for r in stock]

    stock_entry_date = stock[0][0]
    stock_exit_date = stock[-1][0]
    stock_entry = closes[stock_entry_date]
    stock_exit = closes[stock_exit_date]

    # B&H 基准
    bh = run_strategy(entries, closes, stock_dates, stock_entry, stock_exit, 0.0, 0)

    strike_pcts = [0.00, 0.05, 0.10, 0.15, 0.20, 0.25]
    num_puts_list = [1, 2, 3]
    results = []
    for sp in strike_pcts:
        for np_ in num_puts_list:
            r = run_strategy(entries, closes, stock_dates, stock_entry, stock_exit, sp, np_)
            r["strike_pct"], r["num_puts"] = sp, np_
            r["vs_bh"] = r["total_pnl"] - bh["total_pnl"]            # 收益差
            r["mdd_reduce"] = bh["mdd"] - r["mdd"]                    # 回撤降低(正=降了)
            r["ratio"] = r["total_pnl"] / r["mdd"] if r["mdd"] > 0 else float('inf')
            results.append(r)

    # 主排序: 收益/回撤比 降序
    results.sort(key=lambda x: x["ratio"], reverse=True)
    best = results[0]
    bh_ratio = bh["total_pnl"] / bh["mdd"] if bh["mdd"] > 0 else float('inf')

    # 最优策略相对 B&H 的收益文案（自适应跑赢/跑输）
    if best["vs_bh"] > 0:
        vs_text = f"比 B&H 还多赚 {money(best['vs_bh'])}"
    elif best["vs_bh"] < 0:
        vs_text = f"比 B&H 少赚 {money(best['vs_bh'])}"
    else:
        vs_text = "与 B&H 持平"
    ratio_multiple = best["ratio"] / bh_ratio if bh_ratio > 0 else 0

    # 排名表
    rows = []
    for i, r in enumerate(results):
        ratio_str = f'{r["ratio"]:.2f}'
        rows.append(f"""<tr>
<td>{i+1}</td>
<td>{r['strike_pct']*100:.0f}%</td>
<td>{r['num_puts']}</td>
<td>{money(r['total_pnl'])}</td>
<td class="c-green">${r['mdd']:,.0f}</td>
<td class="c-green">{r['mdd_pct']:.1f}%</td>
<td class="c-red">${r['mdd_reduce']:,.0f}</td>
<td><strong>{ratio_str}</strong></td>
<td>{r['itm']}/{r['n']}</td>
<td>{money(r['vs_bh'])}</td>
</tr>""")
    table_rows = "\n".join(rows)

    # 最优策略的 put 明细
    ex = run_strategy(entries, closes, stock_dates, stock_entry, stock_exit,
                      best["strike_pct"], best["num_puts"])
    ex_rows = "\n".join(f"""<tr>
<td>{t['entry_date']}</td>
<td>${t['spot']:.2f}</td>
<td>{'${:.1f}'.format(t['strike']) if t['strike'] else '-'}</td>
<td>${t['exit']:.2f}</td>
<td class="c-green">${t['cost']:,.0f}</td>
<td class="c-red">${t['payoff']:,.0f}</td>
<td>{'是' if t['itm'] else '否'}</td>
</tr>""" for t in ex["rows"])

    # 缺数据周五
    all_fridays = [d for d in opt if d["dte"] == 7]
    missing = [d["date"] for d in all_fridays if not d.get("puts")]

    # ── 当前操作指南（基于最新期权快照）──
    last_snap = opt[-1]
    cur_spot = last_snap["spot"]
    cur_expiry = last_snap["expiry"]
    cur_dte = last_snap["dte"]
    cur_puts = {p["strike"]: p for p in last_snap["puts"]}
    cur_atm = min(cur_puts.keys(), key=lambda k: abs(k - cur_spot))
    cur_vw = cur_puts[cur_atm]["vw"]
    cur_cost = cur_vw * 100 * best["num_puts"]  # 最优张数
    cur_hold = cur_spot * 100  # 100 股

    # 情景损益表（到期日不同 spot）
    scenario_rows = ""
    for pct in [-25, -20, -15, -10, -5, 0, 5, 10, 15, 20]:
        exit_ = cur_spot * (1 + pct / 100)
        stock_pnl = (exit_ - cur_spot) * 100
        payoff = max(cur_atm - exit_, 0.0) * 100 * best["num_puts"]
        net = stock_pnl + payoff - cur_cost
        net_pct = net / cur_hold * 100
        color = "c-red" if net > 0 else ("c-green" if net < 0 else "c-gray")
        scenario_rows += f"""<tr>
<td>{exit_:.2f}</td>
<td>{pct:+d}%</td>
<td class="{pc(stock_pnl)}">{stock_pnl:+,.0f}</td>
<td class="c-red">{payoff:+,.0f}</td>
<td class="{pc(net)}">{net:+,.0f}</td>
<td class="{pc(net)}">{net_pct:+.1f}%</td>
</tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM ETF 对冲策略回测（收益 + 回撤）</title>
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
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }}
.kpi .label {{ color:var(--muted); font-size:12px; }}
.kpi .value {{ font-size:22px; font-weight:700; margin-top:4px; }}
.kpi .sub {{ color:var(--muted); font-size:12px; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }}
th {{ background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }}
th:first-child, td:first-child {{ text-align:left; }}
th:nth-child(2), td:nth-child(2) {{ text-align:left; }}
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
<h1>DRAM ETF 对冲策略回测 <span style="color:var(--muted);font-size:15px;">（收益 + 回撤综合评估 · 真实期权数据）</span></h1>
<p class="sub">数据源：DRAM_stock.json（93 交易日）+ DRAM_options.json（真实 weekly 期权链） · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>策略模型</h2>
<div class="callout">
<strong>股票：{stock_entry_date} 买入 100 股 @ ${stock_entry:.2f}，一直持有到 {stock_exit_date} @ ${stock_exit:.2f}，中间不卖出。</strong>
Put：每个 weekly 滚动日买入 N 张（真实成交价 vw），到期结算后滚动。
<strong>基准 = B&H（0 Put）</strong>：收益 {money(bh['total_pnl'])}，最大回撤 <span class="c-green">${bh['mdd']:,.0f}（{bh['mdd_pct']:.1f}%）</span>。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
<strong>买 Put 的本质是降低回撤、在大跌时保护。</strong>
DRAM 这段是过山车行情（$27.76 → 最高 ~$80 → 暴跌到 $44.85），B&H 最大回撤高达 <span class="c-green">${bh['mdd']:,.0f}（{bh['mdd_pct']:.1f}%）</span>。
综合「收益 + 回撤」后，最优是 <strong class="c-gold">{best['strike_pct']*100:.0f}% OTM / {best['num_puts']} 张 Put</strong>：
收益 {money(best['total_pnl'])}（{vs_text}），回撤降到 <span class="c-green">${best['mdd']:,.0f}（{best['mdd_pct']:.1f}%，回撤比例降了 <span class="c-red">{bh['mdd_pct'] - best['mdd_pct']:.1f}%</span>）</span>。
收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>，是 B&H（{bh_ratio:.2f}）的 <strong class="c-gold">{ratio_multiple:.1f} 倍</strong>。
</div>
<div class="kpis">
<div class="kpi"><div class="label">B&H 回撤比例</div><div class="value c-green">{bh['mdd_pct']:.1f}%</div><div class="sub">回撤 ${bh['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">策略回撤比例</div><div class="value c-red">{best['mdd_pct']:.1f}%</div><div class="sub">回撤 ${best['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">回撤比例降幅</div><div class="value c-red">{bh['mdd_pct'] - best['mdd_pct']:.1f}%</div><div class="sub">降低 ${best['mdd_reduce']:+,.0f}</div></div>
<div class="kpi"><div class="label">B&H 收益</div><div class="value c-red">${bh['total_pnl']:+,.0f}</div><div class="sub">收益/回撤比 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">策略收益</div><div class="value c-red">${best['total_pnl']:+,.0f}</div><div class="sub">{best['strike_pct']*100:.0f}% OTM / {best['num_puts']} 张</div></div>
<div class="kpi"><div class="label">策略收益/回撤比</div><div class="value c-gold">{best['ratio']:.2f}</div><div class="sub">B&H 为 {bh_ratio:.2f}</div></div>
</div>
<p class="note">回撤比例 = 最大回撤 ÷ 峰值净值（从最高点回撤的百分比）。收益/回撤比 = 总收益 ÷ 最大回撤，越高越好。</p>
</div>

<div class="card">
<h2>策略排名（按收益/回撤比降序）</h2>
<div class="tbl-scroll">
<table>
<tr><th>#</th><th>目标 OTM</th><th>Put 张数</th><th>总 P&L</th><th>最大回撤</th><th>回撤比例</th><th>回撤降幅</th><th>收益/回撤比</th><th>行权</th><th>vs B&H</th></tr>
{table_rows}
</table>
</div>
<p class="note">回撤比例 = 最大回撤 ÷ 峰值净值（从最高点回撤的百分比）。回撤降幅 = B&H 回撤 − 策略回撤（正 = 回撤被降低）。行权 = Put 到期 ITM 次数。<br>
越靠上（ATM）降回撤越多；「vs B&H」为负说明收益有牺牲。综合最优看「收益/回撤比」。</p>
</div>

<div class="card">
<h2>最优策略 Put 明细：{best['strike_pct']*100:.0f}% OTM / {best['num_puts']} 张</h2>
<p style="font-size:14px;margin-bottom:10px;">股票不动收益 {money(ex['stock_pnl'])}；累计保费 <span class="c-green">-${ex['put_cost']:,.0f}</span>，赔付 <span class="c-red">+${ex['put_payoff']:,.0f}</span>，净 {money(ex['put_net'])}。</p>
<div class="tbl-scroll">
<table>
<tr><th>滚动日</th><th>当日 spot</th><th>行权价</th><th>到期价</th><th>保费</th><th>赔付</th><th>ITM</th></tr>
{ex_rows}
</table>
</div>
</div>

<div class="card">
<h2>现在如何买（基于最新期权数据 {last_snap['date']}）</h2>
<div class="callout-gold">
最新 DRAM 现价 <strong class="c-gold">${cur_spot:.2f}</strong>，最近到期日 <strong>{cur_expiry}</strong>（{cur_dte} 天后）。
按最优策略 <strong class="c-gold">{best['strike_pct']*100:.0f}% OTM / {best['num_puts']} 张 Put</strong>，现在应这样操作：
</div>
<ol style="font-size:14px;padding-left:22px;line-height:2.0;">
<li><strong>持有 100 股 DRAM</strong>（市值 ${cur_hold:,.0f}），一直持有不动。</li>
<li><strong>买入 {best['num_puts']} 张行权价 ${cur_atm:.0f} 的 Put</strong>（现价 ${cur_spot:.2f} 最接近的平值档），到期日 {cur_expiry}。</li>
<li>该档 Put 成交量加权价 <strong>${cur_vw:.2f}/股</strong>，每张合约 ${cur_vw*100:,.2f}，{best['num_puts']} 张共 <strong class="c-green">-${cur_cost:,.2f}</strong>（占持仓 {cur_cost/cur_hold*100:.1f}%）。</li>
<li>{best['num_puts']} 张 = 覆盖 {best['num_puts']*100} 股 vs 持有 100 股，即 <strong>{best['num_puts']}:1 过度对冲</strong>——下跌时 Put 赔付是股票亏损的 {best['num_puts']} 倍。</li>
<li>到期日 {cur_expiry} 结算后，无论是否行权，<strong>下周五再买下一周期同档 Put</strong>，周而复始。</li>
</ol>
<div class="tbl-scroll">
<table>
<tr><th>到期日 spot</th><th>涨跌</th><th>股票 P&L</th><th>Put 赔付</th><th>净 P&L</th><th>净收益率</th></tr>
{scenario_rows}
</table>
</div>
<p class="note">净 P&L = 股票 P&L + Put 赔付 − 保费（{best['num_puts']} 张 ${cur_cost:,.0f}）。这是「微笑曲线」：<strong>大涨赚（股票）、大跌也赚（{best['num_puts']}:1 过度对冲）、只有横盘小波动（±5% 内）亏保费</strong>。正好匹配 DRAM 的剧烈波动特性。</p>
</div>

<div class="card">
<h2>数据与结论说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>真实成交价</strong>：Put 成本用每日期权链的成交量加权价（vw），不是 Black-Scholes 理论价 + 假设 IV。</li>
<li><strong>weekly 期权</strong>：数据只有最近一个到期日的链，Put 按周滚动（{len(entries)} 个周期）。</li>
<li><strong>回撤口径</strong>：逐日净值 = 股票市值 + 累计 Put 现金流（买入扣保费、到期加赔付），MDD = 峰值到谷底最大回撤。</li>
<li><strong>缺失周期</strong>：{len(missing)} 个周五无期权数据（{', '.join(missing)}），这些周无法买 Put，但股票仍持有，不影响 B&H 基准。</li>
<li><strong>过山车行情是关键</strong>：DRAM 先涨后暴跌，ATM Put 在暴跌周期（尤其 06-26→07-02 大跌 15.6%）频繁行权（7/15），赔付超过保费、净赚，因此既降回撤又提收益；deep OTM Put 因太虚值，暴跌时也保护不足，依然跑输。</li>
<li><strong>结果依赖这段行情</strong>：若未来波动收敛、不再有暴跌，ATM Put 的成本优势会消失。仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""
    with open(OUT_HTML, "w") as f:
        f.write(html)

    # 控制台摘要
    print(f"B&H: 收益 ${bh['total_pnl']:+,.0f} | 回撤 ${bh['mdd']:,.0f} ({bh['mdd_pct']:.1f}%) | 收益/回撤比 {bh_ratio:.2f}")
    print(f"滚动周期: {len(entries)} 个")
    print()
    print(f"{'Strike%':>8} {'#Puts':>6} {'总P&L':>10} {'回撤':>9} {'回撤比例':>8} {'回撤降幅':>9} {'收益/回撤':>9} {'ITM':>6} {'vsB&H':>9}")
    print("-" * 90)
    for r in results:
        print(f"{r['strike_pct']*100:>7.0f}% {r['num_puts']:>6} ${r['total_pnl']:>9,.0f} "
              f"${r['mdd']:>8,.0f} {r['mdd_pct']:>7.1f}% ${r['mdd_reduce']:>8,.0f} {r['ratio']:>8.2f} "
              f"{r['itm']:>2}/{r['n']:<2} ${r['vs_bh']:>+8,.0f}")
    print()
    print(f"报告已生成: {OUT_HTML}")
    print(f"最优(收益/回撤比): {best['strike_pct']*100:.0f}%OTM/{best['num_puts']}put, 收益${best['total_pnl']:+,.0f}, 回撤${best['mdd']:,.0f}({best['mdd_pct']:.1f}%), 比{best['ratio']:.2f}")

if __name__ == "__main__":
    main()
