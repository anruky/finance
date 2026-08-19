#!/usr/bin/env python3
"""
DRAM ETF 对冲策略回测 v2 —— 带止盈的滚动对冲
================================================
策略:
  - 股票: 数据第一天买入 100 股, 一直持有, 不卖
  - Put:  每个 weekly 周期买入 2 手 ATM put, 每日盯盘:
      当 put 浮盈 >= 止盈线(默认 5% = 入场股票价值 x 5%) 时, 平仓落袋, 当天立即开新一轮
      否则持有到到期日结算
  - 周期: weekly(约7天), 节假日顺延(数据里 expiry 已自动顺延)

止盈线 = put 浮盈 / 入场时股票价值, 可配置(默认 5%)
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_tp_backtest_report.html"

def load():
    stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    opt = json.load(open(os.path.join(DATA, "DRAM_options.json")))
    closes = {r[0]: r[4] for r in stock}
    return stock, opt, closes

def group_by_expiry(opt, closes):
    groups = defaultdict(list)
    for d in opt:
        if d["expiry"] in closes and d.get("puts"):
            groups[d["expiry"]].append(d)
    out = {}
    for exp, days in groups.items():
        days = sorted(days, key=lambda x: x["date"])
        for day in days:
            day["put_map"] = {p["strike"]: p for p in day["puts"]}
        out[exp] = days
    return out

def atm_strike(day):
    return min(day["puts"], key=lambda p: abs(p["strike"] - day["spot"]))

def compute_mdd(stock_dates, closes, stock_entry, cashflow):
    cum = 0.0; peak = 0.0; mdd = 0.0
    for dt in stock_dates:
        cum += cashflow.get(dt, 0.0)
        v = (closes[dt] - stock_entry) * 100 + cum
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    peak_actual = stock_entry * 100 + peak
    mdd_pct = mdd / peak_actual * 100 if peak_actual > 0 else 0.0
    return dict(mdd=mdd, mdd_pct=mdd_pct)

def run_hold_to_expiry(groups, closes, stock_dates, stock_entry, stock_exit, num_puts):
    stock_pnl = (stock_exit - stock_entry) * 100
    cashflow = defaultdict(float)
    put_cost = 0.0; put_payoff = 0.0; itm = 0; n = 0
    for exp in sorted(groups.keys()):
        days = groups[exp]
        entry = days[0]
        p = atm_strike(entry)
        strike, vw = p["strike"], p["vw"]
        cost = vw * 100 * num_puts
        exit_ = closes[exp]
        payoff = max(strike - exit_, 0.0) * 100 * num_puts
        cashflow[entry["date"]] -= cost
        cashflow[exp] += payoff
        put_cost += cost; put_payoff += payoff
        itm += 1 if exit_ < strike else 0
        n += 1
    put_net = put_payoff - put_cost
    total = stock_pnl + put_net
    md = compute_mdd(stock_dates, closes, stock_entry, cashflow)
    return dict(total=total, stock_pnl=stock_pnl, put_cost=put_cost, put_payoff=put_payoff,
                put_net=put_net, itm=itm, n=n, **md)

def run_with_take_profit(groups, closes, stock_dates, stock_entry, stock_exit,
                         num_puts, tp_pct):
    stock_pnl = (stock_exit - stock_entry) * 100
    cashflow = defaultdict(float)
    put_net = 0.0
    rounds = []
    tp_hits = 0; expiries = 0
    for exp in sorted(groups.keys()):
        days = groups[exp]
        pos = None
        for day in days:
            if pos is None:
                p = atm_strike(day)
                cost = p["vw"] * 100 * num_puts
                pos = dict(strike=p["strike"], vw=p["vw"], date=day["date"],
                           stock_value=day["spot"] * 100, cost=cost, entry_spot=day["spot"])
                cashflow[day["date"]] -= cost
                continue
            strike = pos["strike"]
            cur_vw = day["put_map"][strike]["vw"] if strike in day["put_map"] else max(strike - day["spot"], 0.0)
            put_float = (cur_vw - pos["vw"]) * 100 * num_puts
            tp_threshold = pos["stock_value"] * tp_pct / 100.0
            if put_float >= tp_threshold:
                put_net += put_float
                cashflow[day["date"]] += cur_vw * 100 * num_puts
                rounds.append(dict(kind="止盈", entry_date=pos["date"], exit_date=day["date"],
                                   strike=pos["strike"], entry_spot=pos["entry_spot"],
                                   exit_spot=day["spot"], pnl=put_float))
                tp_hits += 1
                p2 = atm_strike(day)
                cost2 = p2["vw"] * 100 * num_puts
                pos = dict(strike=p2["strike"], vw=p2["vw"], date=day["date"],
                           stock_value=day["spot"] * 100, cost=cost2, entry_spot=day["spot"])
                cashflow[day["date"]] -= cost2
        if pos is not None:
            exit_ = closes[exp]
            payoff = max(pos["strike"] - exit_, 0.0) * 100 * num_puts
            round_pnl = payoff - pos["cost"]
            put_net += round_pnl
            cashflow[exp] += payoff
            rounds.append(dict(kind="到期", entry_date=pos["date"], exit_date=exp,
                               strike=pos["strike"], entry_spot=pos["entry_spot"],
                               exit_spot=exit_, pnl=round_pnl))
            expiries += 1
    total = stock_pnl + put_net
    md = compute_mdd(stock_dates, closes, stock_entry, cashflow)
    return dict(total=total, stock_pnl=stock_pnl, put_net=put_net, tp_hits=tp_hits,
                expiries=expiries, rounds=rounds, n_rounds=len(rounds), **md)

def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")

def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'

def main():
    stock, opt, closes = load()
    stock_dates = [r[0] for r in stock]
    stock_entry = closes[stock_dates[0]]
    stock_exit = closes[stock_dates[-1]]
    groups = group_by_expiry(opt, closes)

    base = run_hold_to_expiry(groups, closes, stock_dates, stock_entry, stock_exit, 2)
    base_ratio = base["total"] / base["mdd"]

    tp_list = [3, 4, 5, 6, 8, 10, 12, 15, 20, 25]
    results = []
    for tp in tp_list:
        r = run_with_take_profit(groups, closes, stock_dates, stock_entry, stock_exit, 2, tp)
        r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else float('inf')
        r["tp_pct"] = tp
        results.append(r)

    best = max(results, key=lambda x: x["ratio"])
    r5 = next(r for r in results if r["tp_pct"] == 5)
    r20 = next(r for r in results if r["tp_pct"] == 20)

    # 排名表
    rows = []
    for r in results:
        mark = " ✅" if r["ratio"] == best["ratio"] else ""
        rows.append(f"""<tr>
<td>{r['tp_pct']}%{mark}</td>
<td>{money(r['total'])}</td>
<td class="c-green">${r['mdd']:,.0f}</td>
<td class="c-green">{r['mdd_pct']:.1f}%</td>
<td>{r['tp_hits']}</td>
<td>{r['expiries']}</td>
<td><strong>{r['ratio']:.2f}</strong></td>
<td>{money(r['total'] - base['total'])}</td>
</tr>""")
    table_rows = "\n".join(rows)

    # 5% 明细
    def rounds_html(rounds):
        out = ""
        for rd in rounds:
            k = rd["kind"]
            color = "c-red" if rd["pnl"] > 0 else "c-green"
            out += f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['strike']:.0f}</td>
<td>${rd['entry_spot']:.1f}</td>
<td>${rd['exit_spot']:.1f}</td>
<td>{k}</td>
<td class="{color}">${rd['pnl']:+,.0f}</td>
</tr>"""
        return out
    r5_rows = rounds_html(r5["rounds"])
    r20_rows = rounds_html(r20["rounds"])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM 对冲策略回测 v2 —— 带止盈的滚动对冲</title>
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
<h1>DRAM 对冲策略回测 v2 <span style="color:var(--muted);font-size:15px;">（带止盈的滚动对冲）</span></h1>
<p class="sub">数据源：DRAM_stock.json + DRAM_options.json（真实 weekly 期权链） · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>策略模型（带止盈）</h2>
<div class="callout">
<strong>股票</strong>：{stock_dates[0]} 买入 100 股 @ ${stock_entry:.2f}，一直持有不卖。<br>
<strong>Put</strong>：每个 weekly 周期（7天，节假日顺延）买入 2 手 ATM put，每日盯盘。<br>
<strong>止盈规则</strong>：当 put 浮盈 ≥ 止盈线（= 入场时股票价值 × X%）时，<strong>平仓落袋，当天立即开新一轮</strong>；否则持有到到期日结算。<br>
<strong>止盈线</strong>：可配置，默认 5%（用户设定），回测扫描 3%～25%。
</div>
</div>

<div class="card">
<h2>核心结论：止盈线不是越低越好，是条「驼峰曲线」</h2>
<div class="callout-gold">
<strong>默认的 5% 止盈线反而最差之一</strong>（收益 {money(r5['total'])}，比持有到期的 {money(base['total'])} 还少 {money(r5['total']-base['total'])}）。
<strong>最优是 20% 止盈线</strong>：收益 <strong class="c-gold">{money(best['total'])}</strong>（比持有到期多 {money(best['total']-base['total'])}），
回撤降到 <span class="c-green">{best['mdd_pct']:.1f}%</span>（持有到期为 {base['mdd_pct']:.1f}%），
收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>（持有到期为 {base_ratio:.2f}）。
</div>
<div class="kpis">
<div class="kpi"><div class="label">持有到期（无止盈）</div><div class="value c-red">${base['total']:+,.0f}</div><div class="sub">回撤 {base['mdd_pct']:.1f}% · 比 {base_ratio:.2f}</div></div>
<div class="kpi"><div class="label">5% 止盈（默认）</div><div class="value c-red">${r5['total']:+,.0f}</div><div class="sub">回撤 {r5['mdd_pct']:.1f}% · 比 {r5['ratio']:.2f}</div></div>
<div class="kpi"><div class="label">20% 止盈（最优）</div><div class="value c-gold">${best['total']:+,.0f}</div><div class="sub">回撤 {best['mdd_pct']:.1f}% · 比 {best['ratio']:.2f}</div></div>
<div class="kpi"><div class="label">最优 vs 持有到期</div><div class="value c-red">${best['total']-base['total']:+,.0f}</div><div class="sub">回撤还低 {base['mdd_pct']-best['mdd_pct']:.1f}pt</div></div>
</div>
</div>

<div class="card">
<h2>止盈线扫描（ATM / 2 手 Put）</h2>
<div class="tbl-scroll">
<table>
<tr><th>止盈线</th><th>总收益</th><th>最大回撤</th><th>回撤比例</th><th>止盈次数</th><th>到期次数</th><th>收益/回撤比</th><th>vs 持有到期</th></tr>
{table_rows}
</table>
</div>
<p class="note">✅ = 收益/回撤比最高。可见 3~5% 止盈线因频繁交易拖累反而差；15~20% 止盈线在极端暴跌时落袋，效果最好；25% 以上几乎不触发（等于持有到期）。</p>
</div>

<div class="card">
<h2>为什么 5% 止盈反而差？——「止盈后立马开新仓」的反弹陷阱</h2>
<p style="font-size:14px;margin-bottom:10px;">
低止盈线的问题有两个：<strong>① 每止盈一次就重新付一次保费</strong>（2 手 ATM put 约 5% 股票价值）；
<strong>② 止盈后立马开新仓，一旦行情反弹，新仓立刻亏损，把刚落袋的利润又吐回去</strong>。
看 5% 止盈线里 06 月底这段：06-22 暴跌止盈赚 {money(1454)}，但 06-23 开的新仓（strike 69）遇反弹，到期亏 -$627，两相抵消。
</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>行权价</th><th>入场spot</th><th>出场spot</th><th>结束方式</th><th>P&L</th></tr>
{r5_rows}
</table>
</div>
</div>

<div class="card">
<h2>最优 20% 止盈线的逐轮明细</h2>
<p style="font-size:14px;margin-bottom:10px;">只在极端暴跌时止盈（{best['tp_hits']} 次），落袋的是「灾难利润」，其余时间持有到期，享受完整保护。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>行权价</th><th>入场spot</th><th>出场spot</th><th>结束方式</th><th>P&L</th></tr>
{r20_rows}
</table>
</div>
</div>

<div class="card">
<h2>口径说明与结论</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>止盈线口径</strong>：put 浮盈 ÷ 入场时股票价值。你之前说「股票跌 10% 赚 5%」，那 5% 是<strong>组合净收益</strong>；在 2:1 对冲下，组合净收益 5% ≈ put 浮盈约 15%，正好落在最优区间（15~20%）。</li>
<li><strong>默认 5% 需要修正</strong>：若你说的 5% 是 put 浮盈口径，那 5% 太灵敏、效果差；建议把止盈线设到 <strong>15~20%</strong>。</li>
<li><strong>「立马开新仓」的固有缺陷</strong>：止盈后立即买新 put，反弹时会亏。可考虑改进为「止盈后等股价企稳（或等下一周）再开新仓」，减少反弹回吐。</li>
<li><strong>数据局限</strong>：每日一个收盘快照，止盈按收盘价触发；实际日内若用盘中价可能触发更频繁。缺 3 个周五（04-17/04-24/05-01）的期权数据，那几周无法开仓。</li>
<li><strong>仅供研究</strong>：不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""
    with open(OUT_HTML, "w") as f:
        f.write(html)

    print(f"报告已生成: {OUT_HTML}")
    print(f"持有到期: 收益 ${base['total']:+,.0f}, 回撤 {base['mdd_pct']:.1f}%, 比 {base_ratio:.2f}")
    print(f"5%止盈(默认): 收益 ${r5['total']:+,.0f}, 回撤 {r5['mdd_pct']:.1f}%, 比 {r5['ratio']:.2f}")
    print(f"20%止盈(最优): 收益 ${best['total']:+,.0f}, 回撤 {best['mdd_pct']:.1f}%, 比 {best['ratio']:.2f}")

if __name__ == "__main__":
    main()
