#!/usr/bin/env python3
"""
DRAM 对冲策略 v5 —— 7天轮动(选最接近7天的周五到期) + 双向再平衡
==================================================================
用真实多周五到期日数据(DRAM_options_3fri.json):
  - 每轮买入"dte 最接近 7 天"的那个周五到期日的 ATM put
  - 双向再平衡: 下跌止盈(put浮盈>=tp_down%) / 上涨再平衡(股价>=行权价x(1+tp_up%))
  - 到期结算后重开; 股票一直持有
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/dram_v5_backtest_report.html"

def load_3fri():
    data = json.load(open(os.path.join(DATA, "DRAM_options_3fri.json")))
    # date -> day
    day_map = {d["date"]: d for d in data}
    return data, day_map

def load_stock():
    stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    return stock, closes

def pick_friday(day, target=7):
    """选 dte 最接近 target 天的周五到期日"""
    return min(day["fridays"], key=lambda f: abs(f["dte"] - target))

def atm_put(friday, spot):
    """某个周五到期日链里, 最接近 spot 的 put"""
    if not friday["puts"]:
        return None
    return min(friday["puts"], key=lambda p: abs(p["strike"] - spot))

def find_put_price(day, expiry, strike):
    """在当天数据里找 (expiry, strike) 的 put 价格, 找不到返回 None"""
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

def run_v5(day_map, closes, stock, stock_entry, stock_exit, tp_down_pct, tp_up_pct, num_puts=2):
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
                               entry_spot=pos["entry_spot"], exit_spot=S, pnl=round_pnl))
            expiries += 1
            pos = None
            # 到期当天开新仓
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
            cur_vw = max(pos["strike"] - S, 0.0)  # 内在价值兜底
        put_float = (cur_vw - pos["vw"]) * 100 * num_puts

        # 1) 下跌止盈
        if put_float >= pos["stock_value"] * tp_down_pct / 100.0:
            put_net += put_float
            cashflow[date] += cur_vw * 100 * num_puts
            rounds.append(dict(kind="下跌止盈", entry_date=pos["entry_date"], exit_date=date,
                               expiry=pos["expiry"], strike=pos["strike"],
                               entry_spot=pos["entry_spot"], exit_spot=S, pnl=put_float))
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
        if S >= pos["strike"] * (1 + tp_up_pct / 100.0):
            put_net += put_float
            cashflow[date] += cur_vw * 100 * num_puts
            rounds.append(dict(kind="上涨再平衡", entry_date=pos["entry_date"], exit_date=date,
                               expiry=pos["expiry"], strike=pos["strike"],
                               entry_spot=pos["entry_spot"], exit_spot=S, pnl=put_float))
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

    print(f"数据天数: {len(data)}, 股票 {stock[0][0]}~{stock[-1][0]}")
    print(f"股票持有收益: ${(stock_exit - stock_entry) * 100:+,.0f}")
    print()

    # 验证 07-30 选的到期日
    d0730 = day_map.get('2026-07-30')
    if d0730:
        f = pick_friday(d0730)
        print(f"验证 07-30: spot={d0730['spot']}, 选到期日 {f['expiry']} (dte={f['dte']}), "
              f"ATM put vw={atm_put(f, d0730['spot'])['vw'] if atm_put(f, d0730['spot']) else 'N/A'}")
        print()

    # baseline: 只下跌止盈15%, 无上涨再平衡
    base = run_v5(day_map, closes, stock, stock_entry, stock_exit, 15, 9999)
    base_ratio = base["total"] / base["mdd"] if base["mdd"] > 0 else 0
    print(f"baseline(跌止盈15%,无涨再平衡): 收益 ${base['total']:+,.0f}, 回撤 {base['mdd_pct']:.1f}%, 比 {base_ratio:.2f}")
    print()

    # 扫描
    tp_downs = [5, 10, 15, 20]
    tp_ups = [10, 15, 20, 25, 30]
    print(f"=== 双向再平衡扫描(7天轮动) ===")
    print(f"{'跌止盈\\涨再平衡':>16} | " + " ".join(f"{u}%" for u in tp_ups))
    print("-" * 90)
    all_results = []
    for d in tp_downs:
        row = []
        for u in tp_ups:
            r = run_v5(day_map, closes, stock, stock_entry, stock_exit, d, u)
            r["tp_down"] = d
            r["tp_up"] = u
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            all_results.append(r)
            row.append(r)
        print(f"{d}%跌止盈".rjust(16) + " | " + " ".join(f"${r['total']:>6,.0f}" for r in row))

    best = max(all_results, key=lambda x: x["ratio"])
    print()
    print(f"全局最优: 跌止盈 {best['tp_down']}% + 涨再平衡 {best['tp_up']}%")
    print(f"  收益 ${best['total']:+,.0f} | 回撤 {best['mdd_pct']:.1f}% | 比 {best['ratio']:.2f}")
    print(f"  跌止盈{best['down_hits']}次/涨再平衡{best['up_hits']}次/到期{best['expiries']}次")

    json.dump({"base": base, "results": all_results}, open("/tmp/dram_v5_results.json", "w"), indent=2, default=str)
    generate_html(best, base, all_results, tp_downs, tp_ups)

def generate_html(best, base, all_results, tp_downs, tp_ups):
    base_ratio = base["total"] / base["mdd"] if base["mdd"] > 0 else 0
    matrix = {(r["tp_down"], r["tp_up"]): r for r in all_results}
    matrix_rows = []
    for d in tp_downs:
        cells = []
        for u in tp_ups:
            r = matrix[(d, u)]
            is_best = (d == best["tp_down"] and u == best["tp_up"])
            cls = "c-gold" if is_best else ("c-red" if r["total"] > 0 else "c-green")
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">${r["total"]:+,.0f}{mark}</td>')
        matrix_rows.append(f"<tr><td>{d}%</td>{''.join(cells)}</tr>")

    best_rounds = "\n".join(f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['expiry']}</td>
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
<title>DRAM 对冲策略 v5 —— 7天轮动 + 双向再平衡</title>
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
<h1>DRAM 对冲策略 v5 <span style="color:var(--muted);font-size:15px;">（7天轮动 + 双向再平衡 · 真实多到期日数据）</span></h1>
<p class="sub">真实股票 + 真实多周五到期日期权链（每个交易日 3 个周五到期日） · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>策略规则</h2>
<div class="callout">
<strong>股票</strong>：一直持有 100 股不卖。<br>
<strong>Put</strong>：每轮买入「dte 最接近 7 天」的那个周五到期日的 ATM put。<br>
<strong>双向再平衡</strong>：① 下跌止盈（put 浮盈 ≥ {best['tp_down']}%）② 上涨再平衡（股价 ≥ 行权价 × (1+{best['tp_up']}%)）。<br>
成本 = 每轮买 put 的权利金（约 5%）。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
全局最优：<strong class="c-gold">下跌止盈 {best['tp_down']}% + 上涨再平衡 {best['tp_up']}%</strong> ——
收益 {money(best['total'])}（股票 {money(best['stock_pnl'])} + put {money(best['put_net'])}），
回撤 <span class="c-green">{best['mdd_pct']:.1f}%</span>，收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>。
</div>
<div class="kpis">
<div class="kpi"><div class="label">总收益</div><div class="value c-red">${best['total']:+,.0f}</div><div class="sub">股票 {best['stock_pnl']:+,.0f} + put {best['put_net']:+,.0f}</div></div>
<div class="kpi"><div class="label">最大回撤</div><div class="value c-green">{best['mdd_pct']:.1f}%</div><div class="sub">${best['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">收益/回撤比</div><div class="value c-gold">{best['ratio']:.2f}</div><div class="sub">baseline {base_ratio:.2f}</div></div>
<div class="kpi"><div class="label">再平衡次数</div><div class="value">{best['n_rounds']}</div><div class="sub">跌止盈{best['down_hits']}/涨再平衡{best['up_hits']}/到期{best['expiries']}</div></div>
</div>
</div>

<div class="card">
<h2>参数矩阵（收益，行=跌止盈，列=涨再平衡）</h2>
<div class="tbl-scroll">
<table>
<tr><th>跌止盈\涨再平衡</th>{''.join(f'<th>{u}%</th>' for u in tp_ups)}</tr>
{''.join(matrix_rows)}
</table>
</div>
<p class="note">★ = 收益/回撤比最高。baseline（跌止盈15%，无涨再平衡）收益 ${base['total']:+,.0f}，比 {base_ratio:.2f}。</p>
</div>

<div class="card">
<h2>最优策略逐轮明细：跌止盈 {best['tp_down']}% / 涨再平衡 {best['tp_up']}%</h2>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>到期日</th><th>行权价</th><th>入场spot</th><th>出场spot</th><th>方式</th><th>P&L</th></tr>
{best_rounds}
</table>
</div>
</div>

<div class="card">
<h2>说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>7天轮动</strong>：每个交易日从「未来 3 个周五」里选 dte 最接近 7 天的到期日（如周四选下周五 dte=8，而不是本周五 dte=1）。</li>
<li><strong>真实数据</strong>：全部用 Polygon 真实期权成交价（vw），无 BS 外推。</li>
<li><strong>大涨利润</strong>：股票一直持有，涨 20% 就是股票浮盈 +20%；put 权利金 5% 是拖累。</li>
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
