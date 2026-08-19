#!/usr/bin/env python3
"""
DRAM 对冲策略 v7 —— 不对称双向再平衡 + B&H 对比
==================================================
- 下跌止盈线 down% / 上涨再平衡线 up% 独立可调(不对称)
- 加入 B&H(纯持股)对比
- 数据: DRAM_options_3fri.json(真实多周五到期日), 每轮买 dte 最接近 7 天的 ATM put
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_v7_backtest_report.html"

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

def run_v7(day_map, closes, stock, stock_entry, stock_exit, down_pct, up_pct, num_puts=2):
    """down_pct: 下跌止盈线; up_pct: 上涨再平衡线。9999 表示该方向永不触发"""
    stock_pnl = (stock_exit - stock_entry) * 100
    cashflow = defaultdict(float)
    put_net = 0.0
    rounds = []
    down_hits = 0
    up_hits = 0
    expiries = 0
    pos = None

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
                       entry_spot=S, cost=cost, entry_date=date)
            cashflow[date] -= cost
            continue

        if date >= pos["expiry"]:
            payoff = max(pos["strike"] - S, 0.0) * 100 * num_puts
            round_pnl = payoff - pos["cost"]
            put_net += round_pnl
            cashflow[date] += payoff
            rounds.append(dict(kind="到期", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=S,
                               pnl=round_pnl, stock_pnl=(S - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=payoff))
            expiries += 1
            pos = None
            if day is not None:
                f = pick_friday(day); p = atm_put(f, S)
                if p is not None:
                    cost = p["vw"] * 100 * num_puts
                    pos = dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                               entry_spot=S, cost=cost, entry_date=date)
                    cashflow[date] -= cost
            continue

        cur_vw = find_put_price(day, pos["expiry"], pos["strike"]) if day is not None else None
        if cur_vw is None:
            cur_vw = max(pos["strike"] - S, 0.0)
        put_float = (cur_vw - pos["vw"]) * 100 * num_puts
        p0 = pos["entry_spot"]

        down_trigger = S <= p0 * (1 - down_pct / 100.0)
        up_trigger = S >= p0 * (1 + up_pct / 100.0)

        if down_trigger:
            put_net += put_float
            cashflow[date] += cur_vw * 100 * num_puts
            rounds.append(dict(kind="下跌止盈", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=S,
                               pnl=put_float, stock_pnl=(S - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=cur_vw * 100 * num_puts))
            down_hits += 1
            pos = None
            if day is not None:
                f = pick_friday(day); p = atm_put(f, S)
                if p is not None:
                    cost = p["vw"] * 100 * num_puts
                    pos = dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                               entry_spot=S, cost=cost, entry_date=date)
                    cashflow[date] -= cost
            continue

        if up_trigger:
            put_net += put_float
            cashflow[date] += cur_vw * 100 * num_puts
            rounds.append(dict(kind="上涨再平衡", entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=S,
                               pnl=put_float, stock_pnl=(S - pos["entry_spot"]) * 100,
                               put_cost=pos["cost"], put_income=cur_vw * 100 * num_puts))
            up_hits += 1
            pos = None
            if day is not None:
                f = pick_friday(day); p = atm_put(f, S)
                if p is not None:
                    cost = p["vw"] * 100 * num_puts
                    pos = dict(expiry=f["expiry"], strike=p["strike"], vw=p["vw"],
                               entry_spot=S, cost=cost, entry_date=date)
                    cashflow[date] -= cost
            continue

    total = stock_pnl + put_net
    md = compute_mdd(stock, closes, stock_entry, cashflow)
    return dict(total=total, stock_pnl=stock_pnl, put_net=put_net, down_hits=down_hits,
                up_hits=up_hits, expiries=expiries, rounds=rounds, n_rounds=len(rounds), **md)

def bh_benchmark(stock, closes):
    """纯持股 B&H: 收益 + 回撤"""
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]
    pnl = (stock_exit - stock_entry) * 100
    peak = 0.0; mdd = 0.0
    for r in stock:
        v = (closes[r[0]] - stock_entry) * 100
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    peak_actual = stock_entry * 100 + peak
    mdd_pct = mdd / peak_actual * 100 if peak_actual > 0 else 0.0
    return dict(total=pnl, mdd=mdd, mdd_pct=mdd_pct)

def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")

def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'

def main():
    data, day_map = load_3fri()
    stock, closes = load_stock()
    stock_entry = closes[stock[0][0]]
    stock_exit = closes[stock[-1][0]]

    bh = bh_benchmark(stock, closes)
    bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0
    print(f"B&H(纯持股): 收益 ${bh['total']:+,.0f}, 回撤 {bh['mdd_pct']:.1f}%, 比 {bh_ratio:.2f}")
    print()

    # 等到期(无止盈无再平衡)
    hold = run_v7(day_map, closes, stock, stock_entry, stock_exit, 9999, 9999)
    hold_ratio = hold["total"] / hold["mdd"] if hold["mdd"] > 0 else 0
    print(f"等到期(买put无再平衡): 收益 ${hold['total']:+,.0f}, 回撤 {hold['mdd_pct']:.1f}%, 比 {hold_ratio:.2f}")
    print()

    down_list = [2, 3, 4, 5, 6, 8]
    up_list = [4, 6, 8, 10, 15]
    print("=== 跌止盈 x 涨再平衡 矩阵(总收益) ===")
    print(f"{'跌\\涨':>8} " + " ".join(f"{u:>6}%" for u in up_list))
    all_results = []
    for d in down_list:
        row = []
        for u in up_list:
            r = run_v7(day_map, closes, stock, stock_entry, stock_exit, d, u)
            r["down"] = d
            r["up"] = u
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            all_results.append(r)
            row.append(r)
        print(f"{d:>6}% | " + " ".join(f"{r['total']:>6.0f}" for r in row))

    best = max(all_results, key=lambda x: x["ratio"])
    # 对账: 明细各轮周期总利润之和 vs 总收益, 差额=空档期股票涨跌
    brounds = best["rounds"]
    best["_sum_round_total"] = sum(rd["stock_pnl"] + rd["pnl"] for rd in brounds)
    best["_sum_round_stock"] = sum(rd["stock_pnl"] for rd in brounds)
    best["_gap_stock"] = best["stock_pnl"] - best["_sum_round_stock"]
    # 空档分段: 开头 + 中间断档
    first_entry = brounds[0]["entry_date"]
    gap_segments = [(stock[0][0], first_entry,
                     (closes[first_entry] - closes[stock[0][0]]) * 100)]
    for i in range(1, len(brounds)):
        pe = brounds[i - 1]["exit_date"]
        ce = brounds[i]["entry_date"]
        if pe != ce:
            gap_segments.append((pe, ce, (closes[ce] - closes[pe]) * 100))
    best["_gap_segments"] = gap_segments
    print()
    print(f"全局最优(收益/回撤比): 跌 {best['down']}% + 涨 {best['up']}%")
    print(f"  收益 ${best['total']:+,.0f}, 回撤 {best['mdd_pct']:.1f}%, 比 {best['ratio']:.2f}")
    print(f"  对账: 明细周期总利润和 ${best['_sum_round_total']:+,.0f} + 空档股票涨跌 ${best['_gap_stock']:+,.0f} = 总收益 ${best['total']:+,.0f}")

    # 用户建议的 4%/10%
    r410 = next(r for r in all_results if r["down"] == 4 and r["up"] == 10)
    print(f"用户建议(跌4%+涨10%): 收益 ${r410['total']:+,.0f}, 回撤 {r410['mdd_pct']:.1f}%, 比 {r410['ratio']:.2f}")

    json.dump({"bh": bh, "hold": hold, "results": all_results}, open("/tmp/dram_v7_results.json", "w"), indent=2, default=str)
    generate_html(best, bh, hold, all_results, down_list, up_list)

def generate_html(best, bh, hold, all_results, down_list, up_list):
    bh_ratio = bh["total"] / bh["mdd"] if bh["mdd"] > 0 else 0
    hold_ratio = hold["total"] / hold["mdd"] if hold["mdd"] > 0 else 0

    matrix = {(r["down"], r["up"]): r for r in all_results}
    matrix_rows = []
    for d in down_list:
        cells = []
        for u in up_list:
            r = matrix[(d, u)]
            is_best = (d == best["down"] and u == best["up"])
            cls = "c-gold" if is_best else ("c-red" if r["total"] > 0 else "c-green")
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">${r["total"]:+,.0f}{mark}</td>')
        matrix_rows.append(f"<tr><td>{d}%</td>{''.join(cells)}</tr>")

    # 三基准对比
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

    # 利润来源
    kind_put = defaultdict(float)
    kind_n = defaultdict(int)
    for rd in best["rounds"]:
        kind_put[rd["kind"]] += rd["pnl"]
        kind_n[rd["kind"]] += 1
    gap_stock = best["stock_pnl"] - sum(rd["stock_pnl"] for rd in best["rounds"])
    breakdown = f"""
<tr><td>股票全程涨跌</td><td class="c-red">${best['stock_pnl']:+,.0f}</td></tr>
<tr><td>└ 下跌止盈 put 净</td><td class="c-red">${kind_put['下跌止盈']:+,.0f}</td><td>{kind_n['下跌止盈']}次</td></tr>
<tr><td>└ 上涨再平衡 put 净</td><td class="c-green">${kind_put['上涨再平衡']:+,.0f}</td><td>{kind_n['上涨再平衡']}次</td></tr>
<tr><td>└ 到期 put 净</td><td class="c-red">${kind_put['到期']:+,.0f}</td><td>{kind_n['到期']}次</td></tr>
<tr><td><strong>总收益</strong></td><td><strong class="c-gold">${best['total']:+,.0f}</strong></td></tr>"""

    gap_rows = "\n".join(
        f'<tr><td>{a} → {b}</td><td class="c-red">${amt:+,.0f}</td></tr>'
        for a, b, amt in best["_gap_segments"])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DRAM 对冲策略 v7 —— 不对称再平衡 + B&H 对比</title>
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
.kpi .value {{ font-size:20px; font-weight:700; margin-top:4px; }}
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
<h1>DRAM 对冲策略 v7 <span style="color:var(--muted);font-size:15px;">（不对称再平衡 + B&H 对比）</span></h1>
<p class="sub">真实股票 + 真实多周五到期日期权链 · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>三个基准对比</h2>
<div class="kpis">
<div class="kpi"><div class="label">B&H（纯持股）</div><div class="value c-red">${bh['total']:+,.0f}</div><div class="sub">回撤 {bh['mdd_pct']:.1f}% · 比 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">等到期（买put无再平衡）</div><div class="value c-red">${hold['total']:+,.0f}</div><div class="sub">回撤 {hold['mdd_pct']:.1f}% · 比 {hold_ratio:.2f}</div></div>
<div class="kpi"><div class="label">最优双向再平衡</div><div class="value c-gold">${best['total']:+,.0f}</div><div class="sub">跌{best['down']}%/涨{best['up']}% · 回撤 {best['mdd_pct']:.1f}% · 比 {best['ratio']:.2f}</div></div>
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
最优是 <strong class="c-gold">下跌止盈 {best['down']}% + 上涨再平衡 {best['up']}%</strong>（对称）：
收益 {money(best['total'])}，回撤 {best['mdd_pct']:.1f}%，比 {best['ratio']:.2f}。
把上涨放宽到 10% 反而更差——DRAM 的「涨4%就回调」太频繁，涨10%才重新对齐会错过回调保护。
</div>
</div>

<div class="card">
<h2>跌止盈 × 涨再平衡 矩阵（总收益）</h2>
<div class="tbl-scroll">
<table>
<tr><th>跌止盈\涨再平衡</th>{''.join(f'<th>{u}%</th>' for u in up_list)}</tr>
{''.join(matrix_rows)}
</table>
</div>
<p class="note">★ = 收益/回撤比最高（跌4%+涨4%）。可见「涨再平衡」越大越差，不是越大越好。</p>
</div>

<div class="card">
<h2>最优策略逐轮明细：跌 {best['down']}% / 涨 {best['up']}%</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>行权价</th><th>入场spot</th><th>出场spot</th><th>方式</th><th>股票涨跌</th><th>put成本</th><th>put收入</th><th>周期总利润</th></tr>
{best_rounds}
</table>
</div>
</div>

<div class="card">
<h2>对账：明细加总 vs 总收益</h2>
<div class="tbl-scroll">
<table>
<tr><th>项目</th><th>金额</th></tr>
<tr><td>明细各轮「周期总利润」之和</td><td class="{'c-red' if best['_sum_round_total']>0 else 'c-green'}">${best['_sum_round_total']:+,.0f}</td></tr>
<tr><td>空档期股票涨跌（未买 put 期间）</td><td class="c-red">${best['_gap_stock']:+,.0f}</td></tr>
<tr><td><strong>总收益</strong></td><td><strong class="c-gold">${best['total']:+,.0f}</strong></td></tr>
</table>
</div>
<p class="note">空档期 = 没买到 put 的裸持区间（开头 + 缺数据周五），股票一直持有、涨跌照算，但没出现在任何一轮明细里，所以明细加总比总收益少 ${best['_gap_stock']:+,.0f}。</p>
<div class="tbl-scroll" style="margin-top:12px;">
<table>
<tr><th>空档区间</th><th>股票涨跌</th></tr>
{gap_rows}
</table>
</div>
</div>

<div class="card">
<h2>利润来源分解</h2>
<div class="tbl-scroll">
<table>
<tr><th>项目</th><th>金额</th><th>次数</th></tr>
{breakdown}
</table>
</div>
<p class="note">空档期(缺数据周五)股票涨跌 ${gap_stock:+,.0f} 单独计入总收益，不计入任何一轮。</p>
</div>

<div class="card">
<h2>说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>口径</strong>：下跌止盈线 down% 与上涨再平衡线 up% 独立可调，都用「股票相对开仓价涨跌幅」。</li>
<li><strong>为什么涨10%更差</strong>：DRAM 短期「涨4%就回调」极频繁，涨10%才重新对齐时 put 已 deep OTM、回调没保护；涨4%及时对齐，保护更好。</li>
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
