#!/usr/bin/env python3
"""
SKHY 跨式（Straddle）策略 —— 全参数重扫（临时程序，不动现有 final 程序/报告）
=====================================================================
把「100 股 + 2 put（1:2 对冲）」改成「1 call + 1 put（买入跨式，纯做多波动）」：
  · 不持有股票，每次入场买入 1 张 ATM call + 1 张 ATM put（同一行权价、同一到期日）
  · 熔断线：开盘价 跌 down% / 涨 up% 触发平仓（卖出 call+put）+ 重开
  · 到期：按内在价值结算（call=max(S-K,0)，put=max(K-S,0)）

扫描参数空间：
  · 周期 target : 2(最近周五) / 7 / 14 / 21 天
  · 跌熔断 down  : 5 / 8 / 10 / 12 / 15 / 20 / 25 %
  · 涨熔断 up    : 5 / 8 / 10 / 12 / 15 / 20 / 25 %

输出临时报告：skhy_straddle_report.html
"""
import json
import os
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# 复用现有回测核心的辅助函数（只读加载，不改动源文件）
_code = open(os.path.join(os.path.dirname(__file__), "real_options_backtest_v10.py")).read().split("def pc(")[0]
_ns = {}
exec(_code, _ns)
pick_friday = _ns["pick_friday"]
atm_put = _ns["atm_put"]
find_put_price = _ns["find_put_price"]

DATA = "/Users/gavinz/git/finance/data"
OUT = os.path.join(os.path.dirname(__file__), "skhy_straddle_report.html")

TARGET_LABELS = {2: "最近周五(1-4天)", 7: "7天(6-11天)", 14: "14天(13-18天)", 21: "21天(20-21天)"}
DOWNS = [5, 8, 10, 12, 15, 20, 25]
UPS = [5, 8, 10, 12, 15, 20, 25]


# ---------- straddle 专用函数 ----------

def atm_call(friday, spot):
    if not friday["calls"]:
        return None
    return min(friday["calls"], key=lambda c: abs(c["strike"] - spot))


def find_call_price(day, expiry, strike):
    for f in day["fridays"]:
        if f["expiry"] == expiry:
            for c in f["calls"]:
                if abs(c["strike"] - strike) < 1e-9:
                    return c["vw"]
    return None


def pick_straddle(day, spot, target):
    """买入跨式：ATM put 的行权价作为统一 K，call/put 同 K 同到期日。"""
    f = pick_friday(day, target)
    if not f["calls"] or not f["puts"]:
        return None
    p = atm_put(f, spot)
    K = p["strike"]
    c = next((x for x in f["calls"] if abs(x["strike"] - K) < 1e-9), None)
    if c is None:
        c = atm_call(f, spot)
        K = c["strike"]
        p = next((x for x in f["puts"] if abs(x["strike"] - K) < 1e-9), None)
        if p is None:
            return None
    return dict(expiry=f["expiry"], strike=K, call_vw=c["vw"], put_vw=p["vw"])


def straddle_mtm(day, expiry, strike, S):
    """按当天 vw 估值 call+put，缺则用内在价值兜底。返回 (call价, put价)。"""
    cv = find_call_price(day, expiry, strike)
    pv = find_put_price(day, expiry, strike)
    if cv is None:
        cv = max(S - strike, 0.0)
    if pv is None:
        pv = max(strike - S, 0.0)
    return cv, pv


def compute_mdd_cash(stock, cashflow):
    """纯现金流（无股票本金）净值曲线的最大回撤。"""
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for r in stock:
        cum += cashflow.get(r[0], 0.0)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    mdd_pct = mdd / peak * 100 if peak > 0 else 0.0
    return dict(mdd=mdd, mdd_pct=mdd_pct)


def run_straddle(day_map, closes, bars, stock, move_pct, target, up_pct=None):
    straddle_net = 0.0
    cashflow = defaultdict(float)
    rounds = []
    down_hits = up_hits = expiries = 0
    pos = None
    d = move_pct / 100.0
    u = (up_pct if up_pct is not None else move_pct) / 100.0

    def open_pos(date, spot):
        ps = pick_straddle(day_map.get(date), spot, target)
        if ps is None:
            return None
        call_cost = ps["call_vw"] * 100
        put_cost = ps["put_vw"] * 100
        return dict(expiry=ps["expiry"], strike=ps["strike"],
                    call_vw=ps["call_vw"], put_vw=ps["put_vw"],
                    call_cost=call_cost, put_cost=put_cost,
                    cost=call_cost + put_cost, entry_spot=spot, entry_date=date)

    for r in stock:
        date = r[0]
        S = closes[date]
        o = bars[date][1]
        day = day_map.get(date)

        if pos is None:
            if day is None:
                continue
            pos = open_pos(date, o)
            if pos is not None:
                cashflow[date] -= pos["cost"]
            continue

        p0 = pos["entry_spot"]
        dn_hit = o <= p0 * (1 - d)
        up_hit = o >= p0 * (1 + u)

        # 熔断平仓：按内在价值结算（只算实值腿，虚值腿归零），消除全天 vw 的前视偏差
        def settle(exit_date, S_at):
            return (max(S_at - pos["strike"], 0.0) + max(pos["strike"] - S_at, 0.0)) * 100

        if date >= pos["expiry"]:
            if dn_hit or up_hit:
                payoff = settle(date, o)
                exit_spot = o
                kind = "下跌止盈" if dn_hit else "上涨再平衡"
            else:
                payoff = (max(S - pos["strike"], 0.0) + max(pos["strike"] - S, 0.0)) * 100
                exit_spot = S
                kind = "到期"
            straddle_net += payoff - pos["cost"]
            cashflow[date] += payoff
            rounds.append(dict(kind=kind, entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=exit_spot,
                               pnl=payoff - pos["cost"], cost=pos["cost"], income=payoff,
                               call_cost=pos["call_cost"], put_cost=pos["put_cost"]))
            if dn_hit:
                down_hits += 1
            elif up_hit:
                up_hits += 1
            else:
                expiries += 1
            pos = open_pos(date, exit_spot)
            if pos is not None:
                cashflow[date] -= pos["cost"]
            continue

        if dn_hit or up_hit:
            payoff = settle(date, o)
            straddle_net += payoff - pos["cost"]
            cashflow[date] += payoff
            kind = "下跌止盈" if dn_hit else "上涨再平衡"
            rounds.append(dict(kind=kind, entry_date=pos["entry_date"], exit_date=date,
                               strike=pos["strike"], entry_spot=pos["entry_spot"], exit_spot=o,
                               pnl=payoff - pos["cost"], cost=pos["cost"], income=payoff,
                               call_cost=pos["call_cost"], put_cost=pos["put_cost"]))
            if dn_hit:
                down_hits += 1
            else:
                up_hits += 1
            pos = open_pos(date, o)
            if pos is not None:
                cashflow[date] -= pos["cost"]
            continue

    # 未平仓 mark-to-market（按内在价值估值，与熔断/到期结算口径一致）
    if pos is not None:
        last_date = stock[-1][0]
        S_last = closes[last_date]
        payoff = (max(S_last - pos["strike"], 0.0) + max(pos["strike"] - S_last, 0.0)) * 100
        straddle_net += payoff - pos["cost"]
        cashflow[last_date] += payoff
        rounds.append(dict(kind="持有中", entry_date=pos["entry_date"], exit_date=last_date,
                           expiry=pos["expiry"], strike=pos["strike"],
                           entry_spot=pos["entry_spot"], exit_spot=S_last,
                           pnl=payoff - pos["cost"], cost=pos["cost"], income=payoff,
                           call_cost=pos["call_cost"], put_cost=pos["put_cost"]))

    md = compute_mdd_cash(stock, cashflow)
    return dict(total=straddle_net, straddle_net=straddle_net, down_hits=down_hits,
                up_hits=up_hits, expiries=expiries, rounds=rounds, n_rounds=len(rounds), **md)


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def bg(value, vmin, vmax, kind):
    if vmax == vmin:
        a = 0.0
    else:
        a = (value - vmin) / (vmax - vmin)
    a = max(0.0, min(1.0, a))
    if kind == "pnl":
        if value >= 0:
            return f"background:rgba(255,82,82,{0.08 + 0.30 * a});"
        return f"background:rgba(38,194,129,{0.08 + 0.30 * (1 - a)});"
    return f"background:rgba(245,195,68,{0.06 + 0.30 * a});"


def main():
    data = json.load(open(os.path.join(DATA, "SKHY_options_3fri.json")))
    day_map = {d["date"]: d for d in data}
    stock = json.load(open(os.path.join(DATA, "SKHY_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}
    se = closes[stock[0][0]]
    sx = closes[stock[-1][0]]

    # B&H 基准
    bh_pnl = (sx - se) * 100
    peak = 0.0; mdd = 0.0
    for r in stock:
        v = (closes[r[0]] - se) * 100
        peak = max(peak, v); mdd = max(mdd, peak - v)
    bh_mdd_pct = mdd / (se * 100 + peak) * 100 if (se * 100 + peak) > 0 else 0
    bh_ratio = bh_pnl / mdd if mdd > 0 else 0

    print(f"SKHY 数据: {stock[0][0]} ~ {stock[-1][0]} ({len(stock)} 交易日), 首日 ${se:.2f} -> 末日 ${sx:.2f}")
    print(f"B&H 基准: 收益 ${bh_pnl:+,.0f}, 回撤 {bh_mdd_pct:.1f}%, 比 {bh_ratio:.2f}")

    # ============ 三维扫描（周期 × 跌 × 涨）============
    results = []
    for target in TARGET_LABELS:
        for down in DOWNS:
            for up in UPS:
                r = run_straddle(day_map, closes, bars, stock, down, target, up_pct=up)
                r["target"] = target; r["down"] = down; r["up"] = up
                r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
                results.append(r)
    print(f"扫描完成: {len(results)} 组参数组合")

    best = max(results, key=lambda x: x["ratio"])
    best_total = max(results, key=lambda x: x["total"])
    print(f"最优(收益/回撤比): 周期{best['target']} 跌{best['down']}%/涨{best['up']}% "
          f"-> 收益${best['total']:+,.0f} 回撤${best['mdd']:,.0f} 比{best['ratio']:.2f}")
    print(f"最优(总收益): 周期{best_total['target']} 跌{best_total['down']}%/涨{best_total['up']}% "
          f"-> 收益${best_total['total']:+,.0f} 回撤${best_total['mdd']:,.0f} 比{best_total['ratio']:.2f}")

    # 旧策略（100股+2put，最近周五+跌15/涨8）对比
    run_v10 = _ns["run_v10"]
    old = run_v10(day_map, closes, bars, stock, se, sx, 15, 2, num_puts=2, up_pct=8)
    old["ratio"] = old["total"] / old["mdd"] if old["mdd"] > 0 else 0

    # ============ 切片 ============
    # 熔断矩阵（固定最优周期）
    def cell(d, field):
        return [next(x for x in results if x["target"] == best["target"] and x["down"] == d and x["up"] == u)[field] for u in UPS]

    pnl_mat = {d: cell(d, "total") for d in DOWNS}
    ratio_mat = {d: cell(d, "ratio") for d in DOWNS}
    pnl_vals = [v for d in DOWNS for v in pnl_mat[d]]
    ratio_vals = [v for d in DOWNS for v in ratio_mat[d]]
    pnl_min, pnl_max = min(pnl_vals), max(pnl_vals)
    ratio_min, ratio_max = min(ratio_vals), max(ratio_vals)

    # 周期切片（固定最优跌/涨）
    target_slice = [next(r for r in results if r["down"] == best["down"] and r["up"] == best["up"] and r["target"] == t) for t in TARGET_LABELS]

    # ============ 报告渲染 ============
    def kpi(label, value_html, sub=""):
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value_html}</div><div class="sub">{sub}</div></div>')

    top10 = sorted(results, key=lambda x: x["ratio"], reverse=True)[:10]
    top10_rows = []
    for i, r in enumerate(top10, 1):
        is_best = (r is best)
        mark = ' <span class="c-gold">★最优</span>' if is_best else ""
        top10_rows.append(
            f'<tr><td>{i}</td><td>{TARGET_LABELS[r["target"]]}</td>'
            f'<td>{r["down"]}%</td><td>{r["up"]}%</td>'
            f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
            f'<td>${r["mdd"]:,.0f}</td>'
            f'<td class="c-gold">{r["ratio"]:.2f}</td>'
            f'<td>{r["n_rounds"]}</td>'
            f'<td>{r["down_hits"]}</td><td>{r["up_hits"]}</td><td>{r["expiries"]}</td></tr>')
    top10_html = "\n".join(top10_rows)

    def matrix_html(mat, vals, kind, title):
        head = "".join(f"<th>涨{up}%</th>" for up in UPS)
        rows = []
        for down in DOWNS:
            tds = []
            for i in range(len(UPS)):
                v = mat[down][i]
                txt = f"${v:+,.0f}" if kind == "pnl" else f"{v:.2f}"
                tds.append(f'<td style="{bg(v, min(vals), max(vals), kind)}">{txt}</td>')
            rows.append(f"<tr><td>跌{down}%</td>{''.join(tds)}</tr>")
        return (f'<div style="margin-top:6px;"><h3 style="font-size:15px;color:var(--text);margin:18px 0 8px;">{title}</h3>'
                f'<table><tr><th>跌\\涨</th>{head}</tr>{"".join(rows)}</table></div>')

    pnl_matrix_html = matrix_html(pnl_mat, pnl_vals, "pnl", "熔断矩阵 —— 总收益（固定最优周期）")
    ratio_matrix_html = matrix_html(ratio_mat, ratio_vals, "ratio", "熔断矩阵 —— 收益/回撤比（固定最优周期）")

    target_rows = []
    for r in target_slice:
        is_best = (r["target"] == best["target"])
        mark = ' <span class="c-gold">★</span>' if is_best else ""
        target_rows.append(
            f'<tr><td>{TARGET_LABELS[r["target"]]}</td>'
            f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
            f'<td>${r["mdd"]:,.0f}</td>'
            f'<td class="c-gold">{r["ratio"]:.2f}</td>'
            f'<td>{r["n_rounds"]}</td></tr>')
    target_rows_html = "\n".join(target_rows)

    # 旧 vs 新 对比
    cmp_rows = (
        f'<tr><td style="color:var(--muted);">旧策略（100股 + 2put）</td>'
        f'<td>最近周五</td><td>15%</td><td>8%</td>'
        f'<td class="{pc(old["total"])}">${old["total"]:+,.0f}</td>'
        f'<td>{old["mdd_pct"]:.1f}%</td><td>{old["ratio"]:.2f}</td><td>{old["n_rounds"]}</td></tr>'
        f'<tr><td style="color:var(--gold);font-weight:700;">新策略（1 call + 1 put）</td>'
        f'<td>{TARGET_LABELS[best["target"]]}</td><td>{best["down"]}%</td><td>{best["up"]}%</td>'
        f'<td class="{pc(best["total"])}">${best["total"]:+,.0f}</td>'
        f'<td>${best["mdd"]:,.0f}</td><td class="c-gold">{best["ratio"]:.2f}</td><td>{best["n_rounds"]}</td></tr>'
    )

    # 逐轮明细
    detail_rows = []
    for rd in reversed(best["rounds"]):
        total_r = rd["pnl"]
        cost_ratio = rd["cost"] / (rd["entry_spot"] * 100) * 100 if rd["entry_spot"] else 0
        if rd["kind"] == "持有中":
            exit_cell = f'<td>{rd.get("expiry", rd["exit_date"])} 到期</td>'
        else:
            exit_cell = f'<td>{rd["exit_date"]}</td>'
        detail_rows.append(
            f'<tr><td>{rd["entry_date"]}</td>{exit_cell}<td>{rd["kind"]}</td>'
            f'<td>${rd["entry_spot"]:.1f}</td><td>${rd["exit_spot"]:.1f}</td>'
            f'<td>${rd["strike"]:g}</td>'
            f'<td class="c-green">-${rd["call_cost"]:,.0f}</td>'
            f'<td class="c-green">-${rd["put_cost"]:,.0f}</td>'
            f'<td class="c-red">${rd["income"]:+,.0f}</td>'
            f'<td class="{pc(total_r)}">${total_r:+,.0f}</td>'
            f'<td class="c-green">{cost_ratio:.1f}%</td></tr>')
    detail_html = "\n".join(detail_rows)

    css = """
:root { --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }
.wrap { max-width:1180px; margin:0 auto; }
h1 { font-size:24px; margin-bottom:6px; }
h2 { font-size:18px; margin:30px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }
h3 { font-size:15px; margin:18px 0 8px; }
.sub { color:var(--muted); font-size:13px; margin-bottom:24px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; margin-bottom:18px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }
.kpi .label { color:var(--muted); font-size:13px; font-weight:600; }
.kpi .value { font-size:24px; font-weight:700; margin-top:4px; }
.kpi .sub { color:var(--muted); font-size:12px; margin-top:3px; margin-bottom:0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }
th { background:#1d212a; color:var(--muted); font-weight:600; position:sticky; top:0; }
th:first-child, td:first-child { text-align:left; }
.c-red { color:var(--red); font-weight:600; }
.c-green { color:var(--green); font-weight:600; }
.c-gray { color:var(--muted); }
.c-gold { color:var(--gold); font-weight:700; }
.callout { background:rgba(77,163,255,.08); border:1px solid rgba(77,163,255,.3); border-radius:10px;
  padding:12px 16px; margin:12px 0; font-size:13px; }
.note { color:var(--muted); font-size:12px; margin-top:8px; }
code { background:#20242d; border:1px solid var(--border); border-radius:4px; padding:1px 6px;
  font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; color:var(--gold); }
.tbl-scroll { overflow-x:auto; }
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>SKHY 跨式(Straddle)策略重扫报告</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<h1>SKHY（SK海力士 ADR）跨式 Straddle 策略 —— 全参数重扫</h1>
<p class="sub">策略：1 call + 1 put（买入跨式，不持股票）· 数据 {stock[0][0]} ~ {stock[-1][0]}（{len(stock)} 交易日） · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="kpis">
{kpi('数据跨度', f'{len(stock)} 天', f'{stock[0][0]} ~ {stock[-1][0]}')}
{kpi('B&H 基准收益', money(bh_pnl), f'回撤 {bh_mdd_pct:.1f}% · 比 {bh_ratio:.2f}')}
{kpi('新最优总收益', money(best['total']), f'{TARGET_LABELS[best["target"]]} · 跌{best["down"]}%/涨{best["up"]}%')}
{kpi('新最优回撤(现金)', f'${best["mdd"]:,.0f}', f'收益/回撤比 {best["ratio"]:.2f}')}
{kpi('总收益最高组合', money(best_total['total']), f'跌{best_total["down"]}%/涨{best_total["up"]}% · 回撤${best_total["mdd"]:,.0f}')}
</div>

<div class="callout">
<strong>结论：</strong>在最新 {len(stock)} 个交易日数据上，扫描 {len(results)} 组参数后，<strong class="c-gold">跨式最优（收益/回撤比）组合</strong>为：
周期 <strong>{TARGET_LABELS[best["target"]]}</strong>、跌熔断 <strong>{best["down"]}%</strong>、涨熔断 <strong>{best["up"]}%</strong>，
总收益 <strong class="{pc(best['total'])}">${best['total']:+,.0f}</strong>、回撤 <strong>${best['mdd']:,.0f}</strong>、收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>。
</div>

<div class="card">
<h2 style="margin-top:0;">旧策略 vs 新策略</h2>
<div class="tbl-scroll">
<table>
<tr><th>策略</th><th>周期</th><th>跌熔断</th><th>涨熔断</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th></tr>
{cmp_rows}
</table>
</div>
<p class="note">旧策略 = 现有 final 报告（<code>skhy_final_report.html</code>）的最优：100 股 + 2 put（1:2），最近周五 + 跌15%/涨8%，回撤为相对股票市值的百分比口径。新策略 = 1 call + 1 put（跨式，无股票本金），回撤为纯现金净值的绝对金额。两者回撤口径不同，<strong>收益/回撤比（绝对金额口径）可直接对比</strong>。</p>
</div>

<div class="card">
<h2 style="margin-top:0;">Top 10 参数组合（按收益/回撤比排序）</h2>
<div class="tbl-scroll">
<table>
<tr><th>#</th><th>周期</th><th>跌熔断</th><th>涨熔断</th><th>总收益</th><th>回撤(现金)</th><th>收益/回撤比</th><th>轮数</th><th>跌触发</th><th>涨触发</th><th>到期</th></tr>
{top10_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">熔断比例扫描（不对称矩阵）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">固定最优周期 {TARGET_LABELS[best["target"]]}，扫描跌熔断 × 涨熔断。</p>
{pnl_matrix_html}
{ratio_matrix_html}
</div>

<div class="card">
<h2 style="margin-top:0;">周期敏感性</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">固定最优熔断跌{best["down"]}%/涨{best["up"]}%，只改周期。</p>
<div class="tbl-scroll">
<table>
<tr><th>周期</th><th>总收益</th><th>回撤(现金)</th><th>收益/回撤比</th><th>轮数</th></tr>
{target_rows_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">新最优组合逐轮明细</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">周期 {TARGET_LABELS[best["target"]]} + 跌{best["down"]}%/涨{best["up"]}% + 1 call + 1 put。方式：到期 / 上涨再平衡 / 下跌止盈 / 持有中（数据截止未平仓，按现价估值）。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>入场spot</th><th>出场spot</th><th>行权价</th><th>call成本</th><th>put成本</th><th>期权收入</th><th>周期净利</th><th>成本占比</th></tr>
{detail_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>策略结构</strong>：每次入场买入 <strong>1 张 ATM call + 1 张 ATM put</strong>（同一行权价、同一到期日），不持有股票，纯做多波动——大涨靠 call 端、大跌靠 put 端，横盘两头烧时间价值。</li>
<li><strong>熔断口径</strong>：开盘价相对入场价 跌 down% / 涨 up% 触发平仓（卖出 call+put，优先用当天 vw，缺则内在价值）+ 重开；盘中不触发。</li>
<li><strong>到期口径</strong>：call 内在价值 max(S-K,0) + put 内在价值 max(K-S,0)。</li>
<li><strong>回撤口径</strong>：跨式无股票本金，回撤 = 纯现金净值曲线的最大回撤（绝对金额），与旧 put 策略的「相对市值百分比」口径不同，但两者 <code>收益/回撤比 = 总收益 / 最大回撤(绝对金额)</code> 可直接对比。</li>
<li><strong>成本占比</strong> = (call+put 权利金) ÷ (入场 spot × 100)，即相对等值股票市值的权利金比例。</li>
<li><strong>本程序为临时重扫</strong>（<code>rescan_skhy_straddle.py</code>），不改动现有 <code>gen_final_report.py</code> / <code>real_options_backtest_v10.py</code> / <code>skhy_final_report.html</code>。</li>
<li><strong>过拟合警示</strong>：SKHY 仅 {len(stock)} 个交易日，样本短、波动大，参数稳定性低，仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""

    with open(OUT, "w") as f:
        f.write(html)
    print(f"\n临时报告已生成: {OUT}")
    print(f"  扫描 {len(results)} 组参数 → 最优比 {best['ratio']:.2f}（旧 100股+2put 比 {old['ratio']:.2f}）")


if __name__ == "__main__":
    main()
