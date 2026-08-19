#!/usr/bin/env python3
"""
DRAM 对冲策略 v10 —— 周期 × 熔断线 二维对比
==================================================
对比不同 put 周期(最近周五1-4天 / 7天 / 14天 / 21天) × 熔断线(8/10/15/20%)。
口径: 开盘价熔断(盘中不触发), 2手put(2:1对冲)。
"""
import json
import os
import math
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_v10_backtest_report.html"

TARGET_LABELS = {2: "最近周五(1-4天)", 7: "7天(6-11天)", 14: "14天(13-18天)", 21: "21天(20-21天)"}
MOVES = [8, 10, 15, 20]


def load_3fri():
    data = json.load(open(os.path.join(DATA, "DRAM_options_3fri.json")))
    return data, {d["date"]: d for d in data}


def load_stock():
    stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}
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


def run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, move_pct, target, num_puts=2):
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
        o = bars[date][1]
        day = day_map.get(date)

        if pos is None:
            if day is None:
                continue
            pp = pick_put(day, o, target)
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
                    pp = pick_put(day, o, target)
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
                    pp = pick_put(day, S, target)
                    if pp is not None:
                        cost = pp["vw"] * 100 * num_puts
                        pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"],
                                   entry_spot=S, cost=cost, entry_date=date)
                        cashflow[date] -= cost
            continue

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
                pp = pick_put(day, o, target)
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
                pp = pick_put(day, o, target)
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
    print(f"B&H: 收益 ${bh['total']:+,.0f}, 回撤 {bh['mdd_pct']:.1f}%, 比 {bh_ratio:.2f}")

    # 二维扫描: 周期 × 熔断线
    results = []
    for target in TARGET_LABELS:
        for m in MOVES:
            r = run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, m, target)
            r["target"] = target
            r["move"] = m
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            results.append(r)

    print("\n=== 周期 × 熔断线 矩阵(总收益) ===")
    print(f"{'周期':>16} " + " ".join(f"{m:>8}%" for m in MOVES))
    for target in TARGET_LABELS:
        row = [next(r for r in results if r["target"] == target and r["move"] == m) for m in MOVES]
        print(f"{TARGET_LABELS[target]:>16} " + " ".join(f"${r['total']:>8,.0f}" for r in row))

    best = max(results, key=lambda x: x["ratio"])
    print(f"\n全局最优(收益/回撤比): {TARGET_LABELS[best['target']]} + 熔断 {best['move']}%")
    print(f"  收益 ${best['total']:+,.0f}, 回撤 {best['mdd_pct']:.1f}%, 比 {best['ratio']:.2f}")

    json.dump({"bh": bh, "results": results}, open("/tmp/dram_v10_results.json", "w"), indent=2, default=str)
    generate_html(best, bh, results)


def generate_html(best, bh, results):
    bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0

    # 收益矩阵
    matrix_rows = []
    for target in TARGET_LABELS:
        cells = []
        for m in MOVES:
            r = next(x for x in results if x["target"] == target and x["move"] == m)
            is_best = (target == best["target"] and m == best["move"])
            cls = "c-gold" if is_best else ("c-red" if r["total"] > 0 else "c-green")
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">${r["total"]:+,.0f}{mark}</td>')
        matrix_rows.append(f"<tr><td>{TARGET_LABELS[target]}</td>{''.join(cells)}</tr>")

    # 比率矩阵
    ratio_rows = []
    for target in TARGET_LABELS:
        cells = []
        for m in MOVES:
            r = next(x for x in results if x["target"] == target and x["move"] == m)
            is_best = (target == best["target"] and m == best["move"])
            cls = "c-gold" if is_best else ""
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">{r["ratio"]:.2f}{mark}</td>')
        ratio_rows.append(f"<tr><td>{TARGET_LABELS[target]}</td>{''.join(cells)}</tr>")

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
<title>DRAM 对冲 v10 —— 周期 × 熔断线对比</title>
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
.callout-gold {{ background:rgba(245,195,68,.08); border:1px solid rgba(245,195,68,.35); border-radius:10px; padding:14px 16px; margin:12px 0; font-size:14px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.tbl-scroll {{ overflow-x:auto; }}
</style>
</head>
<body>
<div class="wrap">
<h1>DRAM 对冲 v10 <span style="color:var(--muted);font-size:15px;">（周期 × 熔断线二维对比）</span></h1>
<p class="sub">开盘价熔断 · 2手put · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
全局最优：<strong class="c-gold">{TARGET_LABELS[best['target']]} + 熔断 {best['move']}%</strong>。
收益 {money(best['total'])}，回撤 {best['mdd_pct']:.1f}%，收益/回撤比 {best['ratio']:.2f}。
周期越短越划算：最近周五(1-4天) &gt; 7天 &gt; 14天 &gt; 21天。
</div>
</div>

<div class="card">
<h2>总收益矩阵（周期 × 熔断线）</h2>
<div class="tbl-scroll">
<table>
<tr><th>周期\熔断线</th>{''.join(f'<th>{m}%</th>' for m in MOVES)}</tr>
{''.join(matrix_rows)}
</table>
</div>
<p class="note">B&H 基准：收益 ${bh['total']:+,.0f}，回撤 {bh['mdd_pct']:.1f}%，比 {bh_ratio:.2f}。★ = 全局最优(收益/回撤比)。</p>
</div>

<div class="card">
<h2>收益/回撤比矩阵</h2>
<div class="tbl-scroll">
<table>
<tr><th>周期\熔断线</th>{''.join(f'<th>{m}%</th>' for m in MOVES)}</tr>
{''.join(ratio_rows)}
</table>
</div>
</div>

<div class="card">
<h2>最优策略逐轮明细：{TARGET_LABELS[best['target']]} + 熔断 {best['move']}%</h2>
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
<li><strong>周期</strong>：最近周五(dte 1-4天) / 7天(6-11天) / 14天(13-18天) / 21天(20-21天)，对应买入 dte 最接近该天数的周五到期 put。</li>
<li><strong>熔断</strong>：开盘价相对入场价 跌/涨 move% 触发，开盘平仓+重买；盘中不触发。</li>
<li><strong>对冲</strong>：2手 put 对 100股(2:1过度对冲)。</li>
<li><strong>未计交易摩擦</strong>：短周期滚动频繁，实盘佣金+价差会吃掉部分优势。</li>
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
