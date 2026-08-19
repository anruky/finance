#!/usr/bin/env python3
"""
DRAM 对冲策略 v9 —— 开盘价熔断(盘中不触发)
==================================================
用户需求: 盘中不盯盘, 熔断只看每天开盘价(open)。
- 开盘价相对入场价 跌8% → 开盘平仓 put + 开盘重买
- 开盘价相对入场价 涨8% → 开盘平仓 put + 开盘重买
- 盘中(low/high)不触发
- 到期日: 开盘先判熔断(触发就开盘平仓), 不触发才持有到收盘到期结算
- 开仓/重开都用开盘价 open
"""
import json
import os
import math
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_v9_backtest_report.html"


def load_3fri():
    data = json.load(open(os.path.join(DATA, "DRAM_options_3fri.json")))
    return data, {d["date"]: d for d in data}


def load_stock():
    stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}  # [date, open, high, low, close, vol]
    return stock, closes, bars


def pick_friday(day, target=7):
    return min(day["fridays"], key=lambda f: abs(f["dte"] - target))


def atm_put(friday, spot):
    if not friday["puts"]:
        return None
    return min(friday["puts"], key=lambda p: abs(p["strike"] - spot))


def pick_put(day, spot, target=7):
    f = pick_friday(day, target)
    p = atm_put(f, spot)
    if p is None:
        return None
    return dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"])


def find_put_price(day, expiry, strike):
    for f in day["fridays"]:
        if f["expiry"] == expiry:
            for p in f["puts"]:
                if abs(p["strike"] - strike) < 1e-9:
                    return p["vw"]
    return None


def compute_mdd(stock, closes, stock_entry, cashflow):
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for r in stock:
        dt = r[0]
        cum += cashflow.get(dt, 0.0)
        v = (closes[dt] - stock_entry) * 100 + cum
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    peak_actual = stock_entry * 100 + peak
    return dict(mdd=mdd, mdd_pct=mdd / peak_actual * 100 if peak_actual > 0 else 0.0)


def run_v9(day_map, closes, bars, stock, stock_entry, stock_exit, move_pct, num_puts=2):
    stock_pnl = (stock_exit - stock_entry) * 100
    cashflow = defaultdict(float)
    put_net = 0.0
    rounds = []
    down_hits = 0
    up_hits = 0
    expiries = 0
    pos = None
    d = move_pct / 100.0

    for r in stock:
        date = r[0]
        S = closes[date]
        o, h, l, c = bars[date][1], bars[date][2], bars[date][3], bars[date][4]
        day = day_map.get(date)

        # 无持仓: 开盘开新仓
        if pos is None:
            if day is None:
                continue
            pp = pick_put(day, o)
            if pp is None:
                continue
            cost = pp["vw"] * 100 * num_puts
            pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"],
                       entry_spot=o, cost=cost, entry_date=date)
            cashflow[date] -= cost
            continue

        p0 = pos["entry_spot"]
        dn_hit = o <= p0 * (1 - d)
        up_hit = o >= p0 * (1 + d)

        # 到期日: 开盘先判熔断, 不触发才到期结算
        if date >= pos["expiry"]:
            if dn_hit or up_hit:
                vw_hit = find_put_price(day, pos["expiry"], pos["strike"])
                if vw_hit is not None:
                    payoff = vw_hit * 100 * num_puts
                else:
                    payoff = max(pos["strike"] - o, 0.0) * 100 * num_puts if dn_hit else 0.0
                put_net += payoff - pos["cost"]
                cashflow[date] += payoff
                kind = "下跌止盈" if dn_hit else "上涨再平衡"
                rounds.append(dict(kind=kind, entry_date=pos["entry_date"], exit_date=date,
                                   strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=o,
                                   pnl=payoff - pos["cost"], stock_pnl=(o - pos["entry_spot"]) * 100,
                                   put_cost=pos["cost"], put_income=payoff))
                if dn_hit:
                    down_hits += 1
                else:
                    up_hits += 1
                pos = None
                if day is not None:
                    pp = pick_put(day, o)
                    if pp is not None:
                        cost = pp["vw"] * 100 * num_puts
                        pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"],
                                   entry_spot=o, cost=cost, entry_date=date)
                        cashflow[date] -= cost
            else:
                payoff = max(pos["strike"] - S, 0.0) * 100 * num_puts
                put_net += payoff - pos["cost"]
                cashflow[date] += payoff
                rounds.append(dict(kind="到期", entry_date=pos["entry_date"], exit_date=date,
                                   strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=S,
                                   pnl=payoff - pos["cost"], stock_pnl=(S - pos["entry_spot"]) * 100,
                                   put_cost=pos["cost"], put_income=payoff))
                expiries += 1
                pos = None
                if day is not None:
                    pp = pick_put(day, S)
                    if pp is not None:
                        cost = pp["vw"] * 100 * num_puts
                        pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"],
                                   entry_spot=S, cost=cost, entry_date=date)
                        cashflow[date] -= cost
            continue

        # 未到期: 开盘价熔断
        if dn_hit:
            vw_hit = find_put_price(day, pos["expiry"], pos["strike"])
            payoff = vw_hit * 100 * num_puts if vw_hit is not None else max(pos["strike"] - o, 0.0) * 100 * num_puts
            put_net += payoff - pos["cost"]
            cashflow[date] += payoff
            rounds.append(dict(kind="下跌止盈", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=o,
                               pnl=payoff - pos["cost"], stock_pnl=(o - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=payoff))
            down_hits += 1
            pos = None
            if day is not None:
                pp = pick_put(day, o)
                if pp is not None:
                    cost = pp["vw"] * 100 * num_puts
                    pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"],
                               entry_spot=o, cost=cost, entry_date=date)
                    cashflow[date] -= cost
            continue

        if up_hit:
            vw_hit = find_put_price(day, pos["expiry"], pos["strike"])
            payoff = vw_hit * 100 * num_puts if vw_hit is not None else 0.0
            put_net += payoff - pos["cost"]
            cashflow[date] += payoff
            rounds.append(dict(kind="上涨再平衡", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=o,
                               pnl=payoff - pos["cost"], stock_pnl=(o - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=payoff))
            up_hits += 1
            pos = None
            if day is not None:
                pp = pick_put(day, o)
                if pp is not None:
                    cost = pp["vw"] * 100 * num_puts
                    pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"],
                               entry_spot=o, cost=cost, entry_date=date)
                    cashflow[date] -= cost
            continue

    total = stock_pnl + put_net
    md = compute_mdd(stock, closes, stock_entry, cashflow)
    return dict(total=total, stock_pnl=stock_pnl, put_net=put_net, down_hits=down_hits,
                up_hits=up_hits, expiries=expiries, rounds=rounds, n_rounds=len(rounds), **md)


def bh_benchmark(stock, closes):
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]
    pnl = (stock_exit - stock_entry) * 100
    peak = 0.0
    mdd = 0.0
    for r in stock:
        v = (closes[r[0]] - stock_entry) * 100
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    peak_actual = stock_entry * 100 + peak
    mdd_pct = mdd / peak_actual * 100 if peak_actual > 0 else 0.0
    return dict(total=pnl, mdd=mdd, mdd_pct=mdd_pct)


def main():
    data, day_map = load_3fri()
    stock, closes, bars = load_stock()
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]

    bh = bh_benchmark(stock, closes)
    bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0
    print(f"B&H: 收益 ${bh['total']:+,.0f}, 回撤 {bh['mdd_pct']:.1f}%, 比 {bh_ratio:.2f}")
    print()

    print("=== 开盘价熔断扫描(收益/回撤) ===")
    print(f"{'熔断线':>6} {'总收益':>10} {'put净':>10} {'回撤%':>7} {'跌止盈':>6} {'涨再平衡':>7} {'到期':>5} {'收益/回撤':>8}")
    print("-" * 75)
    results = []
    for m in [4, 6, 8, 10, 15, 20]:
        r = run_v9(day_map, closes, bars, stock, stock_entry, stock_exit, m)
        r["move"] = m
        r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
        results.append(r)
        print(f"{m:>4}%  ${r['total']:>9,.0f} ${r['put_net']:>9,.0f} {r['mdd_pct']:>6.1f}% "
              f"{r['down_hits']:>6} {r['up_hits']:>7} {r['expiries']:>5} {r['ratio']:>8.2f}")

    best = max(results, key=lambda x: x["ratio"])
    print()
    print(f"最优(收益/回撤比): 熔断 {best['move']}%  收益 ${best['total']:+,.0f} 回撤 {best['mdd_pct']:.1f}% 比 {best['ratio']:.2f}")

    json.dump({"bh": bh, "results": results}, open("/tmp/dram_v9_results.json", "w"), indent=2, default=str)
    generate_html(best, bh, results)


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def generate_html(best, bh, results):
    bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0

    rows = "\n".join(f"""<tr>
<td>{r['move']}%</td>
<td>{money(r['total'])}</td>
<td>{money(r['put_net'])}</td>
<td>{r['mdd_pct']:.1f}%</td>
<td>{r['down_hits']}</td>
<td>{r['up_hits']}</td>
<td>{r['expiries']}</td>
<td><strong>{r['ratio']:.2f}</strong></td>
</tr>""" for r in results)

    best_rounds = "\n".join(f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['kind']}</td>
<td>${rd['entry_spot']:.1f}</td>
<td>${rd['exit_spot']:.1f}</td>
<td class="{pc(rd['stock_pnl'])}">${rd['stock_pnl']:+,.0f}</td>
<td class="c-green">-${rd['put_cost']:,.0f}</td>
<td class="c-red">${rd['put_income']:+,.0f}</td>
<td class="{pc(rd['stock_pnl']+rd['pnl'])}">${rd['stock_pnl']+rd['pnl']:+,.0f}</td>
</tr>""" for rd in reversed(best["rounds"]))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM 对冲 v9 —— 开盘价熔断</title>
<style>
:root {{ --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text); font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; line-height:1.6; padding:32px 20px; }}
.wrap {{ max-width:1080px; margin:0 auto; }}
h1 {{ font-size:26px; margin-bottom:6px; }}
h2 {{ font-size:19px; margin:32px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }}
.sub {{ color:var(--muted); font-size:13px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }}
th {{ background:#1d212a; color:var(--muted); font-weight:600; }}
th:first-child, td:first-child {{ text-align:left; }}
.c-red {{ color:var(--red); font-weight:600; }}
.c-green {{ color:var(--green); font-weight:600; }}
.c-gold {{ color:var(--gold); font-weight:700; }}
.callout {{ background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px; padding:14px 16px; margin:12px 0; font-size:14px; }}
.callout-gold {{ background:rgba(245,195,68,.08); border:1px solid rgba(245,195,68,.35); border-radius:10px; padding:14px 16px; margin:12px 0; font-size:14px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.tbl-scroll {{ overflow-x:auto; }}
</style>
</head>
<body>
<div class="wrap">
<h1>DRAM 对冲 v9 <span style="color:var(--muted);font-size:15px;">（开盘价熔断，盘中不触发）</span></h1>
<p class="sub">熔断只看开盘价 · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>熔断线扫描（开盘价触发）</h2>
<div class="tbl-scroll">
<table>
<tr><th>熔断线</th><th>总收益</th><th>put净</th><th>回撤</th><th>跌止盈</th><th>涨再平衡</th><th>到期</th><th>收益/回撤</th></tr>
{rows}
</table>
</div>
<p class="note">B&H 基准：收益 ${bh['total']:+,.0f}，回撤 {bh['mdd_pct']:.1f}%，比 {bh_ratio:.2f}。</p>
</div>

<div class="card">
<h2>核心结论：开盘价口径下最优线右移到 15%</h2>
<div class="callout-gold">
只看开盘价（不盯盘）后，<strong class="c-gold">{best['move']}% 熔断线最优</strong>：收益 {money(best['total'])}，回撤 {best['mdd_pct']:.1f}%，比 {best['ratio']:.2f}。
而 8% 反而差（+$1,546，比 0.89）——开盘价只捕捉「跳空」，DRAM 跳空 8% 很常见（趋势延续），跳空 15% 才是真转折。
</div>
<div class="tbl-scroll">
<table>
<tr><th>触发口径</th><th>最优熔断线</th><th>收益</th><th>回撤</th><th>收益/回撤</th></tr>
<tr><td>收盘价（v7）</td><td>4%</td><td class="c-red">+$3,451</td><td>9.1%</td><td>6.34</td></tr>
<tr><td>盘中价（v8）</td><td>8%</td><td class="c-red">+$3,455</td><td>13.2%</td><td>4.32</td></tr>
<tr><td><strong>开盘价（v9）</strong></td><td><strong class="c-gold">{best['move']}%</strong></td><td class="c-red">${best['total']:+,.0f}</td><td>{best['mdd_pct']:.1f}%</td><td><strong>{best['ratio']:.2f}</strong></td></tr>
</table>
</div>
<p class="note">规律：触发信号越迟钝（收盘→盘中→开盘），最优熔断线越宽（4%→8%→15%），捕捉波动的能力也越弱。</p>
</div>

<div class="card">
<h2>最优策略逐轮明细：熔断 {best['move']}%</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>入场spot</th><th>出场spot</th><th>股票涨跌</th><th>put成本</th><th>put收入</th><th>周期总利润</th></tr>
{best_rounds}
</table>
</div>
</div>

<div class="card">
<h2>说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>开盘价触发</strong>：每天开盘价相对入场价 跌/涨 move% 就触发，开盘平仓 + 开盘重买；盘中(high/low)不触发。</li>
<li><strong>到期日</strong>：开盘先判熔断（触发就开盘平仓），不触发才持有到收盘到期结算。</li>
<li><strong>开仓/重开</strong>：都用开盘价 open。</li>
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
