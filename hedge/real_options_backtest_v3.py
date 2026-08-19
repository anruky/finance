#!/usr/bin/env python3
"""
DRAM ETF 对冲策略回测 v3 —— 周期参数化 + 止盈立即开新仓
==========================================================
策略规则(按用户确认):
  - 股票: 数据第一天买入 100 股, 一直持有, 不卖
  - 每轮: 买入 2 手 ATM put, 到期日 = 开仓日 + 周期(cycle_days 日历天, 节假日顺延)
  - 止盈: 轮内 put 浮盈 >= 止盈线(= 入场股票价值 x tp_pct) 时, 平仓落袋, 当天立即开新仓(新仓重新算周期)
  - 周期 cycle_days 参数化(默认7天), 扫描找最优

数据约束: 真实期权链只有"最近到期日"(<=7天)。周期>7天的部分用 Black-Scholes
从真实 ATM put 价格反推隐含波动率 IV, 再外推到 N 天到期。
"""
import json
import os
import math
from collections import defaultdict
from datetime import datetime, timedelta

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_cycle_backtest_report.html"

def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def bs_put(S, K, T, sig, r=0.0):
    if T <= 0 or sig <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + sig * sig / 2) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

def implied_vol(S, K, T, market_price):
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs_put(S, K, T, mid) > market_price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2

def load():
    stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    opt = json.load(open(os.path.join(DATA, "DRAM_options.json")))
    closes = {r[0]: r[4] for r in stock}
    return stock, opt, closes

def build_daily_atm(opt):
    """每天 -> (spot, atm_strike, atm_vw, dte)"""
    out = {}
    for d in opt:
        if d.get("puts"):
            atm = min(d["puts"], key=lambda p: abs(p["strike"] - d["spot"]))
            out[d["date"]] = (d["spot"], atm["strike"], atm["vw"], d["dte"])
    return out

def next_expiry(date_str, cycle_days, trade_set):
    """到期日 = 开仓日 + cycle_days 日历天, 顺延到下一个交易日"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    exp = d + timedelta(days=cycle_days)
    while exp.strftime("%Y-%m-%d") not in trade_set:
        exp += timedelta(days=1)
        if (exp - d).days > cycle_days + 12:
            exp = d + timedelta(days=cycle_days)
            break
    return exp.strftime("%Y-%m-%d")

def _open_position(date, daily_atm, trade_set, cycle_days, num_puts, cashflow):
    """开新仓, 返回 pos dict (或 None)"""
    if date not in daily_atm:
        return None
    spot, atm_strike, atm_vw, dte = daily_atm[date]
    iv = implied_vol(spot, atm_strike, dte / 365.0, atm_vw)
    exp_date = next_expiry(date, cycle_days, trade_set)
    cost = bs_put(spot, atm_strike, cycle_days / 365.0, iv) * 100 * num_puts
    cashflow[date] -= cost
    return dict(strike=atm_strike, iv=iv, entry_spot=spot,
                stock_value=spot * 100, cost=cost, entry_date=date, exp_date=exp_date)

def run_v3(stock, closes, daily_atm, cycle_days, tp_pct, num_puts=2):
    stock_dates = [r[0] for r in stock]
    trade_set = set(stock_dates)
    stock_entry = closes[stock_dates[0]]
    stock_exit = closes[stock_dates[-1]]
    stock_pnl = (stock_exit - stock_entry) * 100

    cashflow = defaultdict(float)
    put_net = 0.0
    rounds = []
    tp_hits = 0
    expiries = 0
    pos = None

    for date in stock_dates:
        S = closes[date]
        if pos is None:
            pos = _open_position(date, daily_atm, trade_set, cycle_days, num_puts, cashflow)
            continue

        # 到期结算
        if date >= pos["exp_date"]:
            payoff = max(pos["strike"] - S, 0.0) * 100 * num_puts
            put_net += payoff - pos["cost"]
            cashflow[date] += payoff
            rounds.append(dict(kind="到期", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"],
                               exit_spot=S, pnl=payoff - pos["cost"]))
            expiries += 1
            pos = _open_position(date, daily_atm, trade_set, cycle_days, num_puts, cashflow)
            continue

        # mark-to-market (固定 IV)
        T_remaining = (datetime.strptime(pos["exp_date"], "%Y-%m-%d") - datetime.strptime(date, "%Y-%m-%d")).days / 365.0
        T_entry = (datetime.strptime(pos["exp_date"], "%Y-%m-%d") - datetime.strptime(pos["entry_date"], "%Y-%m-%d")).days / 365.0
        cur_price = bs_put(S, pos["strike"], T_remaining, pos["iv"])
        entry_price = bs_put(pos["entry_spot"], pos["strike"], T_entry, pos["iv"])
        put_float = (cur_price - entry_price) * 100 * num_puts
        tp_threshold = pos["stock_value"] * tp_pct / 100.0
        if put_float >= tp_threshold:
            put_net += put_float
            cashflow[date] += cur_price * 100 * num_puts
            rounds.append(dict(kind="止盈", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"],
                               exit_spot=S, pnl=put_float))
            tp_hits += 1
            pos = _open_position(date, daily_atm, trade_set, cycle_days, num_puts, cashflow)

    total = stock_pnl + put_net
    mdd = compute_mdd(stock, closes, stock_entry, cashflow)
    return dict(total=total, stock_pnl=stock_pnl, put_net=put_net, tp_hits=tp_hits,
                expiries=expiries, rounds=rounds, n_rounds=len(rounds), **mdd)

def compute_mdd(stock, closes, stock_entry, cashflow):
    cum = 0.0; peak = 0.0; mdd = 0.0
    for r in stock:
        dt = r[0]
        cum += cashflow.get(dt, 0.0)
        v = (closes[dt] - stock_entry) * 100 + cum
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    peak_actual = stock_entry * 100 + peak
    return dict(mdd=mdd, mdd_pct=mdd / peak_actual * 100 if peak_actual > 0 else 0.0)

def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")

def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'

def main():
    stock, opt, closes = load()
    daily_atm = build_daily_atm(opt)

    print("=== 周期 × 止盈线 扫描 (ATM/2put) ===")
    print(f"{'周期(天)':>8} | " + " ".join(f"{tp}%止盈" for tp in [5,10,15,20]) + " | " + f"{'总收益/回撤/比':>20}")
    print("-" * 90)

    all_results = []
    for cd in [5, 7, 10, 14, 21, 30]:
        row = []
        for tp in [5, 10, 15, 20]:
            r = run_v3(stock, closes, daily_atm, cd, tp, 2)
            r["cycle_days"] = cd
            r["tp_pct"] = tp
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else float('inf')
            all_results.append(r)
            row.append(r)
        line = f"{cd:>6}天 | " + " ".join(f"${r['total']:>6,.0f}" for r in row) + " | "
        best_in_row = max(row, key=lambda x: x["ratio"])
        line += f"最优{best_in_row['tp_pct']}%止盈: ${best_in_row['total']:,.0f}/{best_in_row['mdd_pct']:.1f}%/比{best_in_row['ratio']:.2f}"
        print(line)

    best = max(all_results, key=lambda x: x["ratio"])
    print()
    print(f"全局最优: 周期 {best['cycle_days']}天 + 止盈 {best['tp_pct']}%")
    print(f"  收益 ${best['total']:+,.0f} | 回撤 ${best['mdd']:,.0f} ({best['mdd_pct']:.1f}%) | 比 {best['ratio']:.2f}")

    # 默认 7天/5%止盈
    r_default = next(r for r in all_results if r["cycle_days"] == 7 and r["tp_pct"] == 5)
    print(f"默认(7天/5%止盈): 收益 ${r_default['total']:+,.0f} | 回撤 {r_default['mdd_pct']:.1f}% | 比 {r_default['ratio']:.2f}")

    json.dump(all_results, open("/tmp/dram_cycle_results.json", "w"), indent=2, default=str)

    # 生成 HTML
    generate_html(best, r_default, all_results)

def generate_html(best, r_default, all_results):
    rows = []
    for r in sorted(all_results, key=lambda x: x["ratio"], reverse=True):
        mark = " ✅" if r["cycle_days"] == best["cycle_days"] and r["tp_pct"] == best["tp_pct"] else ""
        rows.append(f"""<tr>
<td>{r['cycle_days']}天{mark}</td>
<td>{r['tp_pct']}%</td>
<td>{money(r['total'])}</td>
<td class="c-green">${r['mdd']:,.0f}</td>
<td class="c-green">{r['mdd_pct']:.1f}%</td>
<td>{r['tp_hits']}</td>
<td>{r['expiries']}</td>
<td><strong>{r['ratio']:.2f}</strong></td>
</tr>""")
    table_rows = "\n".join(rows)

    # 最优策略明细
    best_rounds = "\n".join(f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['strike']:.0f}</td>
<td>${rd['entry_spot']:.1f}</td>
<td>${rd['exit_spot']:.1f}</td>
<td>{rd['kind']}</td>
<td class="{'c-red' if rd['pnl']>0 else 'c-green'}">${rd['pnl']:+,.0f}</td>
</tr>""" for rd in best["rounds"])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM 对冲策略 v3 —— 周期参数化 + 止盈</title>
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
th {{ background:#1d212a; color:var(--muted); font-weight:600; }}
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
<h1>DRAM 对冲策略 v3 <span style="color:var(--muted);font-size:15px;">（周期参数化 + 止盈立即开新仓）</span></h1>
<p class="sub">真实股票 + 真实期权链（IV 从真实价反推，长周期用 Black-Scholes 外推） · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>策略规则</h2>
<div class="callout">
<strong>股票</strong>：一直持有 100 股不卖。<br>
<strong>每轮</strong>：买入 2 手 ATM put，到期日 = 开仓日 + 周期（cycle_days 日历天，节假日顺延）。<br>
<strong>止盈</strong>：轮内 put 浮盈 ≥ 止盈线（入场股票价值 × X%）→ 平仓落袋，<strong>当天立即开新仓</strong>（新仓重新算周期）。<br>
<strong>双参数</strong>：周期（5~30 天）× 止盈线（5~20%）。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
全局最优：<strong class="c-gold">周期 {best['cycle_days']} 天 + 止盈 {best['tp_pct']}%</strong> ——
收益 {money(best['total'])}，回撤 <span class="c-green">{best['mdd_pct']:.1f}%</span>，收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>。
默认的「7 天 / 5% 止盈」：收益 {money(r_default['total'])}，回撤 {r_default['mdd_pct']:.1f}%，比 {r_default['ratio']:.2f}。
</div>
<div class="kpis">
<div class="kpi"><div class="label">最优收益</div><div class="value c-red">${best['total']:+,.0f}</div><div class="sub">周期{best['cycle_days']}天/{best['tp_pct']}%止盈</div></div>
<div class="kpi"><div class="label">最优回撤</div><div class="value c-green">{best['mdd_pct']:.1f}%</div><div class="sub">${best['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">收益/回撤比</div><div class="value c-gold">{best['ratio']:.2f}</div><div class="sub">止盈{best['tp_hits']}次/到期{best['expiries']}次</div></div>
<div class="kpi"><div class="label">默认7天/5%止盈</div><div class="value c-red">${r_default['total']:+,.0f}</div><div class="sub">比 {r_default['ratio']:.2f}</div></div>
</div>
</div>

<div class="card">
<h2>周期 × 止盈线 全扫描（按收益/回撤比降序）</h2>
<div class="tbl-scroll">
<table>
<tr><th>周期</th><th>止盈线</th><th>总收益</th><th>最大回撤</th><th>回撤比例</th><th>止盈次数</th><th>到期次数</th><th>收益/回撤比</th></tr>
{table_rows}
</table>
</div>
<p class="note">✅ = 全局最优。</p>
</div>

<div class="card">
<h2>最优策略逐轮明细：{best['cycle_days']}天 / {best['tp_pct']}% 止盈</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>行权价</th><th>入场spot</th><th>出场spot</th><th>方式</th><th>P&L</th></tr>
{best_rounds}
</table>
</div>
</div>

<div class="card">
<h2>说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>IV 来源</strong>：每轮开仓日，用当天真实 ATM put 的成交量加权价（vw）反推隐含波动率（Black-Scholes），不是凭空假设。</li>
<li><strong>长周期外推</strong>：真实期权链只有 ≤7 天到期，周期 7 天以上的用反推出的 IV 外推（假设 IV 期限结构平坦）。</li>
<li><strong>止盈即时开新仓</strong>：止盈/到期当天立即开下一轮，新仓从当天重新算周期。</li>
<li><strong>仅供研究</strong>：不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"报告已生成: {OUT_HTML}")

if __name__ == "__main__":
    main()
