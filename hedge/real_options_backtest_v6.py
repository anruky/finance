#!/usr/bin/env python3
"""
DRAM 对冲策略 v6 —— 统一股票涨跌幅口径的双向再平衡
=====================================================
口径统一(按用户确认): 涨跌都用"股票相对开仓价的涨跌幅 X%"触发, 对称:
  - 股票从开仓价 P0 跌 X%  → 平仓 put 落袋, 重新开仓(新 P0=当前价)
  - 股票从开仓价 P0 涨 X%  → put 失去保护, 平仓重新开仓(新 P0=当前价)
  - 到期结算后重开
扫描 X = 5% / 10% / 15% / 20%, 对比"等到期"(X=∞, 无止盈)

数据: DRAM_options_3fri.json(真实多周五到期日), 每轮买 dte 最接近 7 天的 ATM put
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_v6_backtest_report.html"

def load_3fri():
    data = json.load(open(os.path.join(DATA, "DRAM_options_3fri.json")))
    day_map = {d["date"]: d for d in data}
    return data, day_map

def load_stock():
    stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    return stock, closes

def pick_friday(day, target=7):
    return min(day["fridays"], key=lambda f: abs(f["dte"] - target))

def atm_put(friday, spot):
    if not friday["puts"]:
        return None
    return min(friday["puts"], key=lambda p: abs(p["strike"] - spot))

def find_put_price(day, expiry, strike):
    for f in day["fridays"]:
        if f["expiry"] == expiry:
            for p in f["puts"]:
                if abs(p["strike"] - strike) < 1e-9:
                    return p["vw"]
    return None

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

def run_v6(day_map, closes, stock, stock_entry, stock_exit, move_pct, num_puts=2):
    """move_pct: 涨跌触发幅度(%)。move_pct=9999 表示永无止盈(等到期)"""
    stock_pnl = (stock_exit - stock_entry) * 100
    cashflow = defaultdict(float)
    put_net = 0.0
    rounds = []
    down_hits = 0
    up_hits = 0
    expiries = 0

    pos = None  # {expiry, strike, vw, entry_spot, stock_value, cost, entry_date}

    for r in stock:
        date = r[0]
        S = closes[date]
        day = day_map.get(date)

        if pos is None:
            if day is None:
                continue
            f = pick_friday(day)
            p = atm_put(f, S)
            if p is None:
                continue
            cost = p["vw"] * 100 * num_puts
            pos = dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                       entry_spot=S, stock_value=S * 100, cost=cost, entry_date=date)
            cashflow[date] -= cost
            continue

        # 到期结算
        if date >= pos["expiry"]:
            payoff = max(pos["strike"] - S, 0.0) * 100 * num_puts
            round_pnl = payoff - pos["cost"]
            put_net += round_pnl
            cashflow[date] += payoff
            rounds.append(dict(kind="到期", entry_date=pos["entry_date"], exit_date=date,
                               expiry=pos["expiry"], strike=pos["strike"],
                               entry_spot=pos["entry_spot"], exit_spot=S, pnl=round_pnl,
                               stock_pnl=(S - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=payoff))
            expiries += 1
            pos = None
            if day is not None:
                f = pick_friday(day)
                p = atm_put(f, S)
                if p is not None:
                    cost = p["vw"] * 100 * num_puts
                    pos = dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                               entry_spot=S, stock_value=S * 100, cost=cost, entry_date=date)
                    cashflow[date] -= cost
            continue

        # mark-to-market
        if day is not None:
            cur_vw = find_put_price(day, pos["expiry"], pos["strike"])
        else:
            cur_vw = None
        if cur_vw is None:
            cur_vw = max(pos["strike"] - S, 0.0)
        put_float = (cur_vw - pos["vw"]) * 100 * num_puts

        # 触发判定(统一股票涨跌幅口径)
        p0 = pos["entry_spot"]
        down_trigger = S <= p0 * (1 - move_pct / 100.0)
        up_trigger = S >= p0 * (1 + move_pct / 100.0)

        # 1) 下跌止盈
        if down_trigger:
            put_net += put_float
            cashflow[date] += cur_vw * 100 * num_puts
            rounds.append(dict(kind="下跌止盈", entry_date=pos["entry_date"], exit_date=date,
                               expiry=pos["expiry"], strike=pos["strike"],
                               entry_spot=pos["entry_spot"], exit_spot=S, pnl=put_float,
                               stock_pnl=(S - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=cur_vw * 100 * num_puts))
            down_hits += 1
            pos = None
            if day is not None:
                f = pick_friday(day)
                p = atm_put(f, S)
                if p is not None:
                    cost = p["vw"] * 100 * num_puts
                    pos = dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                               entry_spot=S, stock_value=S * 100, cost=cost, entry_date=date)
                    cashflow[date] -= cost
            continue

        # 2) 上涨再平衡
        if up_trigger:
            put_net += put_float
            cashflow[date] += cur_vw * 100 * num_puts
            rounds.append(dict(kind="上涨再平衡", entry_date=pos["entry_date"], exit_date=date,
                               expiry=pos["expiry"], strike=pos["strike"],
                               entry_spot=pos["entry_spot"], exit_spot=S, pnl=put_float,
                               stock_pnl=(S - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=cur_vw * 100 * num_puts))
            up_hits += 1
            pos = None
            if day is not None:
                f = pick_friday(day)
                p = atm_put(f, S)
                if p is not None:
                    cost = p["vw"] * 100 * num_puts
                    pos = dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                               entry_spot=S, stock_value=S * 100, cost=cost, entry_date=date)
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
    stock, closes = load_stock()
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]

    print(f"股票: ${stock_entry:.2f} -> ${stock_exit:.2f}, 持有收益 ${(stock_exit-stock_entry)*100:+,.0f}")
    print()

    # 等到期 baseline
    base = run_v6(day_map, closes, stock, stock_entry, stock_exit, 9999)
    base_ratio = base["total"] / base["mdd"] if base["mdd"] > 0 else 0
    print(f"等到期(无止盈): 收益 ${base['total']:+,.0f}, 回撤 {base['mdd_pct']:.1f}%, 比 {base_ratio:.2f}")
    print()

    print("=== 涨跌 X% 双向触发扫描 ===")
    print(f"{'触发幅度':>10} {'总收益':>10} {'put净':>9} {'回撤':>8} {'回撤%':>7} {'跌止盈':>7} {'涨再平衡':>8} {'到期':>6} {'收益/回撤':>9}")
    print("-" * 85)
    results = []
    for x in [2, 3, 4, 5, 6, 8, 10, 15, 20]:
        r = run_v6(day_map, closes, stock, stock_entry, stock_exit, x)
        r["move_pct"] = x
        r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
        results.append(r)
        print(f"{x:>8}% ${r['total']:>9,.0f} ${r['put_net']:>8,.0f} "
              f"${r['mdd']:>7,.0f} {r['mdd_pct']:>6.1f}% {r['down_hits']:>6} {r['up_hits']:>7} {r['expiries']:>6} {r['ratio']:>8.2f}")

    best = max(results, key=lambda x: x["ratio"])
    print()
    print(f"最优触发幅度: {best['move_pct']}%")
    print(f"  收益 ${best['total']:+,.0f} | 回撤 {best['mdd_pct']:.1f}% | 比 {best['ratio']:.2f}")

    json.dump({"base": base, "results": results}, open("/tmp/dram_v6_results.json", "w"), indent=2, default=str)
    generate_html(best, base, results)

def generate_html(best, base, results):
    base_ratio = base["total"] / base["mdd"] if base["mdd"] > 0 else 0
    rows = []
    for r in sorted(results, key=lambda x: x["ratio"], reverse=True):
        mark = " ✅" if r["move_pct"] == best["move_pct"] else ""
        rows.append(f"""<tr>
<td>{r['move_pct']}%{mark}</td>
<td>{money(r['total'])}</td>
<td class="c-green">${r['mdd']:,.0f}</td>
<td class="c-green">{r['mdd_pct']:.1f}%</td>
<td>{r['down_hits']}</td>
<td>{r['up_hits']}</td>
<td>{r['expiries']}</td>
<td><strong>{r['ratio']:.2f}</strong></td>
<td>{money(r['total'] - base['total'])}</td>
</tr>""")
    table_rows = "\n".join(rows)

    best_rounds = "\n".join(f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['strike']:.0f}</td>
<td>${rd['entry_spot']:.1f}</td>
<td>${rd['exit_spot']:.1f}</td>
<td>{rd['kind']}</td>
<td class="{'c-red' if rd['stock_pnl']>0 else 'c-green'}">${rd['stock_pnl']:+,.0f}</td>
<td class="c-green">-${rd['put_cost']:,.0f}</td>
<td class="c-red">${rd['put_income']:+,.0f}</td>
<td class="{'c-red' if rd['stock_pnl']+rd['pnl']>0 else 'c-green'}">${rd['stock_pnl']+rd['pnl']:+,.0f}</td>
</tr>""" for rd in reversed(best["rounds"]))

    # 利润来源分解
    from collections import defaultdict
    kind_put = defaultdict(float)
    kind_round = defaultdict(float)
    kind_n = defaultdict(int)
    for rd in best["rounds"]:
        kind_put[rd["kind"]] += rd["pnl"]
        kind_round[rd["kind"]] += rd["stock_pnl"] + rd["pnl"]
        kind_n[rd["kind"]] += 1
    sum_round = sum(rd["stock_pnl"] + rd["pnl"] for rd in best["rounds"])
    gap_stock = best["stock_pnl"] - sum(rd["stock_pnl"] for rd in best["rounds"])

    breakdown_rows = f"""
<tr><td>股票全程涨跌（一直持有）</td><td class="c-red">${best['stock_pnl']:+,.0f}</td><td>—</td></tr>
<tr><td>&nbsp;&nbsp;其中：持仓期间（计入各轮）</td><td class="c-red">${best['stock_pnl'] - gap_stock:+,.0f}</td><td>—</td></tr>
<tr><td>&nbsp;&nbsp;其中：空档期（缺数据周五，裸持）</td><td class="c-red">${gap_stock:+,.0f}</td><td>—</td></tr>
<tr><td>put 净收益</td><td class="{pc(best['put_net'])}">${best['put_net']:+,.0f}</td><td>—</td></tr>
<tr><td>&nbsp;&nbsp;└ 下跌止盈 put 净</td><td class="c-red">${kind_put['下跌止盈']:+,.0f}</td><td>{kind_n['下跌止盈']} 次</td></tr>
<tr><td>&nbsp;&nbsp;└ 上涨再平衡 put 净</td><td class="c-green">${kind_put['上涨再平衡']:+,.0f}</td><td>{kind_n['上涨再平衡']} 次</td></tr>
<tr><td>&nbsp;&nbsp;└ 到期 put 净</td><td class="c-red">${kind_put['到期']:+,.0f}</td><td>{kind_n['到期']} 次</td></tr>
<tr><td><strong>总收益</strong></td><td><strong class="c-gold">${best['total']:+,.0f}</strong></td><td>= 股票 + put</td></tr>"""


    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM 对冲策略 v6 —— 统一股票涨跌幅口径</title>
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
<h1>DRAM 对冲策略 v6 <span style="color:var(--muted);font-size:15px;">（统一股票涨跌幅口径）</span></h1>
<p class="sub">真实股票 + 真实多周五到期日期权链 · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>口径（已统一）</h2>
<div class="callout">
<strong>股票一直持有</strong>。每轮买入 ATM put（行权价=开仓价 P0）。<br>
<strong>触发线用股票涨跌幅 X%</strong>（相对开仓价 P0，涨跌对称）：<br>
&nbsp;&nbsp;· 跌 X%（S ≤ P0×(1−X%)）→ 平仓 put 落袋，重开<br>
&nbsp;&nbsp;· 涨 X%（S ≥ P0×(1+X%)）→ put 失去保护，平仓重开<br>
<strong>等到期</strong>（X=∞）作为基准。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
{('最优触发幅度 ' + str(best['move_pct']) + '%') if best['move_pct'] < 9999 else '无止盈（等到期）最优'}：
收益 {money(best['total'])}，回撤 <span class="c-green">{best['mdd_pct']:.1f}%</span>，收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>。
等到期基准：收益 {money(base['total'])}，回撤 {base['mdd_pct']:.1f}%，比 {base_ratio:.2f}。
</div>
<div class="kpis">
<div class="kpi"><div class="label">最优收益</div><div class="value c-red">${best['total']:+,.0f}</div><div class="sub">触发 {best['move_pct']}%</div></div>
<div class="kpi"><div class="label">最优回撤</div><div class="value c-green">{best['mdd_pct']:.1f}%</div><div class="sub">${best['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">收益/回撤比</div><div class="value c-gold">{best['ratio']:.2f}</div><div class="sub">等到期 {base_ratio:.2f}</div></div>
<div class="kpi"><div class="label">触发次数</div><div class="value">{best['n_rounds']}</div><div class="sub">跌止盈{best['down_hits']}/涨再平衡{best['up_hits']}/到期{best['expiries']}</div></div>
</div>
</div>

<div class="card">
<h2>触发幅度扫描（按收益/回撤比降序）</h2>
<div class="tbl-scroll">
<table>
<tr><th>触发幅度</th><th>总收益</th><th>最大回撤</th><th>回撤比例</th><th>跌止盈</th><th>涨再平衡</th><th>到期</th><th>收益/回撤比</th><th>vs 等到期</th></tr>
{table_rows}
</table>
</div>
<p class="note">等到期基准：收益 ${base['total']:+,.0f}，回撤 {base['mdd_pct']:.1f}%，比 {base_ratio:.2f}。</p>
</div>

<div class="card">
<h2>最优策略逐轮明细：触发 {best['move_pct']}%</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>行权价</th><th>入场spot</th><th>出场spot</th><th>方式</th><th>股票涨跌</th><th>put成本</th><th>put收入</th><th>周期总利润</th></tr>
{best_rounds}
</table>
</div>
<p class="note">「股票涨跌」= 这一轮期间(入场→出场)股票涨跌的浮盈变化(股票一直持有不卖)；「周期总利润」= 股票涨跌 + put 收入 − put 成本。注意：轮与轮之间的空档期(缺数据周五)的股票涨跌不计入任何一轮，所以各轮「股票涨跌」之和 ≠ 股票全程涨跌(全程涨跌已单独计入总收益)。</p>
</div>

<div class="card">
<h2>利润来源分解（触发 {best['move_pct']}%）</h2>
<div class="tbl-scroll">
<table>
<tr><th>项目</th><th>金额</th><th>说明</th></tr>
{breakdown_rows}
</table>
</div>
<p class="note">「周期总利润」各轮之和 = 持仓期间股票涨跌 + put净 = {sum_round:+,.0f}，不等于总收益 {best['total']:+,.0f}，差额 {gap_stock:+,.0f} 是空档期(缺数据周五)的裸持股票涨跌，单独计入总收益。</p>
</div>

<div class="card">
<h2>说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>口径</strong>：触发线统一用「股票相对开仓价的涨跌幅 X%」，不是 put 收益、不是组合净收益。</li>
<li><strong>止盈的意义</strong>：捕捉「7 天内先跌后涨 / 先涨后跌」的来回波动；若单边行情，止盈反而可能增加成本。</li>
<li><strong>数据</strong>：真实多周五到期日（dte 最接近 7 天），Polygon 真实成交价。</li>
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
