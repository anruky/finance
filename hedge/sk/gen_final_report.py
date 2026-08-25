#!/usr/bin/env python3
"""
SKHY（SK海力士美股 ADR）对冲策略最终报告生成器
===============================================
涨熔断 × 跌熔断 不对称扫描，找真正最优参数（不沿用 DRAM 的对称 15%）。
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = "/Users/gavinz/git/finance/data"
OUT_HTML = "/Users/gavinz/git/finance/hedge/sk/skhy_final_report.html"

# 复用 v10 的核心逻辑
exec(open(os.path.join(os.path.dirname(__file__), "real_options_backtest_v10.py")).read().split("def pc(")[0])
OUT_HTML = "/Users/gavinz/git/finance/hedge/sk/skhy_final_report.html"  # 覆盖 exec 引入的 v10 输出路径

TARGET_LABELS = {2: "最近周五(1-4天)", 7: "7天(6-11天)", 14: "14天(13-18天)", 21: "21天(20-21天)"}
SYM_MOVES = [8, 10, 15, 20]              # 对称参考（周期 × 熔断线）
ASYM_MOVES = [8, 10, 12, 15, 18, 20, 25]  # 不对称扫描（涨/跌独立）


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

    # 1. 对称扫描，先确定最优周期
    sym_results = []
    for target in TARGET_LABELS:
        for m in SYM_MOVES:
            r = run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, m, target)
            r["target"] = target
            r["move"] = m
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            sym_results.append(r)
    best_sym = max(sym_results, key=lambda x: x["ratio"])
    best_target = best_sym["target"]

    # 2. 不对称扫描（针对最优周期，涨/跌熔断独立）
    asym_results = []
    for down in ASYM_MOVES:
        for up in ASYM_MOVES:
            r = run_v10(day_map, closes, bars, stock, stock_entry, stock_exit, down, best_target, up_pct=up)
            r["down"] = down
            r["up"] = up
            r["ratio"] = r["total"] / r["mdd"] if r["mdd"] > 0 else 0
            asym_results.append(r)
    best = max(asym_results, key=lambda x: x["ratio"])

    # 最新期权数据(用于"现在如何买")
    last = data[-1]
    last_spot = last["spot"]
    latest_date = last["date"]
    near_f = min([f for f in last["fridays"] if f["dte"] > 0], key=lambda f: abs(f["dte"] - best_target))
    near_atm = min(near_f["puts"], key=lambda p: abs(p["strike"] - last_spot))
    near_expiry = near_f["expiry"]
    near_dte = near_f["dte"]
    near_strike = near_atm["strike"]
    near_vw = near_atm["vw"]
    cost_2 = near_vw * 100 * 2
    up_line = last_spot * (1 + best["up"] / 100.0)
    dn_line = last_spot * (1 - best["down"] / 100.0)

    # 股票端点（供模板动态化）
    meta = dict(
        entry_date=stock[0][0], entry_price=stock_entry,
        exit_date=stock[-1][0], exit_price=stock_exit,
        n_days=len(stock),
    )
    all_closes = [closes[r[0]] for r in stock]
    meta["max_price"] = max(all_closes)
    meta["min_price"] = min(all_closes)

    # DRAM 同期对比：用 DRAM 原策略（7天+15%对称），完整数据延续滚动，算 07-13 后净值变化
    dram_data = json.load(open(os.path.join(DATA, "DRAM_options_3fri.json")))
    dram_day_map = {d["date"]: d for d in dram_data}
    dram_stock = json.load(open(os.path.join(DATA, "DRAM_stock.json")))
    dram_closes = {r[0]: r[4] for r in dram_stock}
    dram_bars = {r[0]: r for r in dram_stock}
    dram_se = dram_closes[dram_stock[0][0]]
    dram_sx = dram_closes[dram_stock[-1][0]]

    def _dram_cf(move_pct, target, num_puts=2):
        cashflow = defaultdict(float)
        pos = None
        d = move_pct / 100.0
        for r in dram_stock:
            date = r[0]; S = dram_closes[date]; o = dram_bars[date][1]
            day = dram_day_map.get(date)
            if pos is None:
                if day is None: continue
                pp = pick_put(day, o, target)
                if pp is None: continue
                cost = pp["vw"] * 100 * num_puts
                pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost)
                cashflow[date] -= cost; continue
            p0 = pos["entry_spot"]
            dn = o <= p0 * (1 - d); up = o >= p0 * (1 + d)
            if date >= pos["expiry"]:
                if dn or up:
                    vw_h = find_put_price(day, pos["expiry"], pos["strike"])
                    payoff = vw_h * 100 * num_puts if vw_h is not None else (max(pos["strike"]-o, 0)*100*num_puts if dn else 0.0)
                    cashflow[date] += payoff; pos = None
                    if day is not None:
                        pp = pick_put(day, o, target)
                        if pp is not None:
                            cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost); cashflow[date] -= cost
                else:
                    payoff = max(pos["strike"]-S, 0)*100*num_puts
                    cashflow[date] += payoff; pos = None
                    if day is not None:
                        pp = pick_put(day, S, target)
                        if pp is not None:
                            cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=S, cost=cost); cashflow[date] -= cost
                continue
            if dn:
                vw_h = find_put_price(day, pos["expiry"], pos["strike"])
                payoff = vw_h * 100 * num_puts if vw_h is not None else max(pos["strike"]-o, 0)*100*num_puts
                cashflow[date] += payoff; pos = None
                if day is not None:
                    pp = pick_put(day, o, target)
                    if pp is not None:
                        cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost); cashflow[date] -= cost
                continue
            if up:
                vw_h = find_put_price(day, pos["expiry"], pos["strike"])
                payoff = vw_h * 100 * num_puts if vw_h is not None else 0.0
                cashflow[date] += payoff; pos = None
                if day is not None:
                    pp = pick_put(day, o, target)
                    if pp is not None:
                        cost = pp["vw"]*100*num_puts; pos = dict(expiry=pp["expiry"], strike=pp["strike"], vw=pp["vw"], entry_spot=o, cost=cost); cashflow[date] -= cost
                continue
        return cashflow

    dram_cf = _dram_cf(15, 7)
    cum = 0.0
    dram_eq = {}
    for r in dram_stock:
        cum += dram_cf.get(r[0], 0.0)
        dram_eq[r[0]] = (dram_closes[r[0]] - dram_se) * 100 + cum

    base_dt = meta["entry_date"]
    if base_dt not in dram_eq:
        base_dt = min(d for d in dram_eq if d >= base_dt)
    base_eq = dram_eq[base_dt]
    end_eq = dram_eq[dram_stock[-1][0]]
    dram_net = end_eq - base_eq
    dram_cap = dram_closes[base_dt] * 100

    peak = base_eq; dram_mdd = 0.0
    for r in dram_stock:
        if r[0] >= base_dt:
            v = dram_eq[r[0]]; peak = max(peak, v); dram_mdd = max(dram_mdd, peak - v)
    dram_peak_actual = dram_se * 100 + peak
    dram_st_mdd_pct = dram_mdd / dram_peak_actual * 100 if dram_peak_actual > 0 else 0

    b13 = dram_closes[base_dt]
    dram_bh_ret = (dram_sx / b13 - 1) * 100
    bpeak = (b13 - dram_se) * 100; bmdd = 0.0
    for r in dram_stock:
        if r[0] >= base_dt:
            v = (dram_closes[r[0]] - dram_se) * 100; bpeak = max(bpeak, v); bmdd = max(bmdd, bpeak - v)
    bpeak_actual = dram_se * 100 + bpeak
    dram_bh_mdd_pct = bmdd / bpeak_actual * 100 if bpeak_actual > 0 else 0

    dram_cmp = dict(
        days=sum(1 for r in dram_stock if r[0] >= base_dt),
        bh_ret=dram_bh_ret, bh_mdd=dram_bh_mdd_pct,
        st_ret=dram_net / dram_cap * 100, st_mdd=dram_st_mdd_pct,
        st_ratio=dram_net / dram_mdd if dram_mdd > 0 else 0,
        down=15, up=15, target=7,
    )

    generate_html(best, asym_results, best_sym, best_target, bh, bh_ratio,
                  last_spot, latest_date, near_expiry, near_dte, near_strike, near_vw,
                  cost_2, up_line, dn_line, meta, dram_cmp)


def generate_html(best, asym_results, best_sym, best_target, bh, bh_ratio,
                  last_spot, latest_date, near_expiry, near_dte, near_strike, near_vw,
                  cost_2, up_line, dn_line, meta, dram_cmp):
    best_label = TARGET_LABELS[best_target]

    # 不对称矩阵（收益）
    matrix_rows = []
    for down in ASYM_MOVES:
        cells = []
        for up in ASYM_MOVES:
            r = next(x for x in asym_results if x["down"] == down and x["up"] == up)
            is_best = (down == best["down"] and up == best["up"])
            cls = "c-gold" if is_best else ("c-red" if r["total"] > 0 else "c-green")
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">${r["total"]:+,.0f}{mark}</td>')
        matrix_rows.append(f"<tr><td>{down}%</td>{''.join(cells)}</tr>")

    # 比率矩阵
    ratio_rows = []
    for down in ASYM_MOVES:
        cells = []
        for up in ASYM_MOVES:
            r = next(x for x in asym_results if x["down"] == down and x["up"] == up)
            is_best = (down == best["down"] and up == best["up"])
            cls = "c-gold" if is_best else ""
            mark = " ★" if is_best else ""
            cells.append(f'<td class="{cls}">{r["ratio"]:.2f}{mark}</td>')
        ratio_rows.append(f"<tr><td>{down}%</td>{''.join(cells)}</tr>")

    # 最优策略明细
    best_rounds = "\n".join(f"""<tr>
<td>{rd['entry_date']}</td>
<td>{rd['exit_date']}</td>
<td>{rd['kind']}</td>
<td>${rd['entry_spot']:.1f}</td>
<td>${rd['exit_spot']:.1f}</td>
<td class="{pc(rd['exit_spot']-rd['entry_spot'])}">{(rd['exit_spot']/rd['entry_spot']-1)*100:+.1f}%</td>
<td>${rd['strike']:.0f}</td>
<td class="{pc(rd['stock_pnl'])}">${rd['stock_pnl']:+,.0f}</td>
<td class="c-green">-${rd['put_cost']:,.0f}</td>
<td class="c-green">{rd['put_cost']/(rd['entry_spot']*100)*100:.1f}%</td>
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
    if mdd_reduce >= 0:
        mdd_desc = f'回撤从 {bh["mdd_pct"]:.1f}% 降到 <span class="c-green">{best["mdd_pct"]:.1f}%</span>（降了 <span class="c-red">{mdd_reduce:.1f} 个百分点</span>）'
        mdd_kpi_label = "回撤比例降幅"
        mdd_kpi_val_cls = "c-red"
    else:
        mdd_desc = f'回撤从 {bh["mdd_pct"]:.1f}% 升到 <span class="c-red">{best["mdd_pct"]:.1f}%</span>（升了 <span class="c-green">{abs(mdd_reduce):.1f} 个百分点</span>）'
        mdd_kpi_label = "回撤比例升幅"
        mdd_kpi_val_cls = "c-green"

    skhy_ret = best["total"] / (meta["entry_price"] * 100) * 100

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SKHY 对冲策略最终报告（涨/跌熔断不对称优化）</title>
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
.callout-warn {{ background:rgba(245,195,68,.06); border:1px solid rgba(245,195,68,.3); border-radius:10px;
  padding:14px 16px; margin:12px 0; font-size:14px; }}
.note {{ color:var(--muted); font-size:12px; margin-top:8px; }}
.tbl-scroll {{ overflow-x:auto; }}
</style>
</head>
<body>
<div class="wrap">
<h1>SKHY 对冲策略最终报告 <span style="color:var(--muted);font-size:15px;">（涨熔断 × 跌熔断 不对称优化 · 开盘价熔断）</span></h1>
<p class="sub">数据源：SKHY_stock.json（{meta['n_days']} 交易日）+ SKHY_options_3fri.json（真实 3 周五到期日期权链） · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="card">
<h2>策略模型</h2>
<div class="callout">
<strong>股票：{meta['entry_date']} 买入 100 股 @ ${meta['entry_price']:.2f}，一直持有到 {meta['exit_date']} @ ${meta['exit_price']:.2f}，中间不卖出。</strong><br>
<strong>Put：每次买入「{best_label}」的 ATM put 2 张，真实成交价 vw。</strong><br>
<strong>熔断（不对称）</strong>：开盘价相对入场价 <strong class="c-green">跌 {best['down']}%</strong> 或 <strong class="c-red">涨 {best['up']}%</strong> 就开盘平仓 + 重买；盘中不触发。没触发就持有到期，再滚动下一轮。<br>
<strong>2:1 过度对冲</strong>：2 张 put 覆盖 200 股 vs 持有 100 股，下跌时 put 赔付是股票亏损的 2 倍。<br>
<strong>基准 = B&H</strong>：收益 <span class="c-red">${bh['total']:+,.0f}</span>，最大回撤 <span class="c-green">${bh['mdd']:,.0f}（{bh['mdd_pct']:.1f}%）</span>，收益/回撤比 {bh_ratio:.2f}。
</div>
</div>

<div class="card">
<h2>核心结论</h2>
<div class="callout-gold">
<strong>最优组合：{best_label} put + 跌 {best['down']}% / 涨 {best['up']}% 熔断（不对称）——这是「不盯盘」前提下的最优策略。</strong><br>
收益 <span class="c-red">${best['total']:+,.0f}</span>（比 B&H 多赚 <span class="c-red">${best['total']-bh['total']:+,.0f}</span>），
{mdd_desc}。
收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>，是 B&H（{bh_ratio:.2f}）的 <strong class="c-gold">{best['ratio']/bh_ratio:.1f} 倍</strong>。
</div>
<div class="kpis">
<div class="kpi"><div class="label">B&H 收益</div><div class="value c-red">${bh['total']:+,.0f}</div><div class="sub">回撤 {bh['mdd_pct']:.1f}% · 比 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">策略收益</div><div class="value c-red">${best['total']:+,.0f}</div><div class="sub">{best_label} · 跌{best['down']}%/涨{best['up']}%</div></div>
<div class="kpi"><div class="label">策略回撤比例</div><div class="value c-red">{best['mdd_pct']:.1f}%</div><div class="sub">回撤 ${best['mdd']:,.0f}</div></div>
<div class="kpi"><div class="label">{mdd_kpi_label}</div><div class="value {mdd_kpi_val_cls}">{mdd_reduce:+.1f}%</div><div class="sub">{bh['mdd_pct']:.1f}% → {best['mdd_pct']:.1f}%</div></div>
<div class="kpi"><div class="label">收益/回撤比</div><div class="value c-gold">{best['ratio']:.2f}</div><div class="sub">B&H 为 {bh_ratio:.2f}</div></div>
<div class="kpi"><div class="label">股票收益</div><div class="value c-red">${best['stock_pnl']:+,.0f}</div><div class="sub">put 净 {money(best['put_net'])}</div></div>
</div>
<p class="note">回撤比例 = 最大回撤 ÷ 峰值净值。收益/回撤比 = 总收益 ÷ 最大回撤，越高越好。</p>
</div>

<div class="card">
<h2>涨熔断 × 跌熔断 不对称扫描（总收益）</h2>
<p style="font-size:13px;color:var(--muted);margin-bottom:8px;">周期 = {best_label}（先由对称扫描确定）。★ = 全局最优（收益/回撤比）。行 = 跌熔断，列 = 涨熔断。</p>
<div class="tbl-scroll">
<table>
<tr><th>跌\涨</th>{''.join(f'<th>{m}%</th>' for m in ASYM_MOVES)}</tr>
{''.join(matrix_rows)}
</table>
</div>
</div>

<div class="card">
<h2>收益/回撤比 矩阵</h2>
<div class="tbl-scroll">
<table>
<tr><th>跌\涨</th>{''.join(f'<th>{m}%</th>' for m in ASYM_MOVES)}</tr>
{''.join(ratio_rows)}
</table>
</div>
</div>

<div class="card">
<h2>为什么是「跌 {best['down']}% + 涨 {best['up']}%」</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>涨熔断要更灵敏（{best['up']}%），不是对称的 15%</strong>：SKHY 是次新股，涨得急、来回波动频繁——涨 8% 就追高，能精准捕捉「涨了又回调」的每一波（如 07-14 涨 8% 追高到 strike 181，07-15 大跌 16% 时高行权价 put 赔付 $3,667）。涨熔断太迟钝（15%）会让 put 停留在旧行权价，回调时保护不足。</li>
<li><strong>跌熔断 {best['down']}%</strong>：跌到 {best['down']}% 才止盈落袋，只捕捉真正的趋势下跌，避免小波动反复付权利金。</li>
<li><strong>对称 15% 只是 DRAM 的结论</strong>：DRAM 是涨 8% 追高后继续涨、反复亏权利金，所以 DRAM 最优是涨 15%；SKHY 的波动节奏相反（涨了就回调），最优涨熔断是 8%。<strong>两标的最优参数不能通用。</strong></li>
</ul>
<div class="callout-warn">
<strong>⚠️ 过拟合警示</strong>：SKHY 仅 {meta['n_days']} 个交易日、{best['n_rounds']} 轮交易。最优的「涨 {best['up']}%」高度依赖「涨了就回调」这个具体节奏（尤其 07-15 那笔 $3,667 赔付）。若未来 SKHY 变成单边慢涨（涨了不回调），8% 追高会频繁亏权利金。这个参数是短数据下的拟合结果，稳定性远低于长周期回测，仅供研究。
</div>
</div>

<div class="card">
<h2>最优策略逐轮明细：跌 {best['down']}% / 涨 {best['up']}% 熔断</h2>
<p style="font-size:14px;margin-bottom:10px;">共 {best['n_rounds']} 轮（跌熔断 {best['down_hits']} 次 / 涨熔断 {best['up_hits']} 次 / 到期 {best['expiries']} 次）。股票不动收益 {money(best['stock_pnl'])}；put 净 {money(best['put_net'])}。</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>入场spot</th><th>出场spot</th><th>波动比例</th><th>行权价</th><th>股票涨跌</th><th>put成本</th><th>成本占比</th><th>put收入</th><th>周期总利润</th></tr>
{best_rounds}
</table>
</div>
<p class="note">周期总利润 = 股票涨跌 + put收入 − put成本。倒序排列（最近的交易在最上）。</p>
</div>

<div class="card">
<h2>现在如何买（基于最新期权数据 {latest_date}）</h2>
<div class="callout-gold">
最新 SKHY 现价 <strong class="c-gold">${last_spot:.2f}</strong>，最近到期日 <strong>{near_expiry}</strong>（dte {near_dte} 天）。
按最优策略 <strong class="c-gold">{best_label} + 跌 {best['down']}% / 涨 {best['up']}%</strong>，现在应这样操作：
</div>
<ol style="font-size:14px;padding-left:22px;line-height:2.0;">
<li><strong>持有 100 股 SKHY</strong>（市值 ${last_spot*100:,.0f}），一直持有不动。</li>
<li><strong>买入 2 张行权价 ${near_strike:.0f} 的 Put</strong>（现价 ${last_spot:.2f} 最接近的平值档），到期日 {near_expiry}。</li>
<li>该档 Put 成交量加权价 <strong>${near_vw:.2f}/股</strong>，每张 ${near_vw*100:,.2f}，2 张共 <strong class="c-green">-${cost_2:,.0f}</strong>（占持仓 {cost_2/(last_spot*100)*100:.1f}%）。</li>
<li><strong>熔断线（不对称）</strong>：开盘价涨到 <strong class="c-red">${up_line:.2f}</strong>（涨 {best['up']}%）或跌到 <strong class="c-green">${dn_line:.2f}</strong>（跌 {best['down']}%）就开盘平仓 put + 重买（盘中不盯盘）。</li>
<li>没触发熔断就持有到 {near_expiry} 到期，再滚动下一轮 {best_label} put。</li>
</ol>
<div class="tbl-scroll">
<table>
<tr><th>到期日 spot</th><th>涨跌</th><th>股票 P&L</th><th>Put 赔付</th><th>净 P&L</th><th>净收益率</th></tr>
{scenario_html}
</table>
</div>
<p class="note">净 P&L = 股票 P&L + Put 赔付 − 保费（2 张 ${cost_2:,.0f}）。这是「微笑曲线」：<strong>大涨赚（股票）、大跌也赚（2:1 过度对冲）、只有横盘小波动亏保费</strong>。注意：实际涨跌 {best['up']}%/{best['down']}% 会触发熔断提前平仓，不会真的持有到期。</p>
</div>

<div class="card">
<h2>与 DRAM 同期对比（{meta['entry_date']} ~ {meta['exit_date']}，{dram_cmp['days']} 交易日）</h2>
<p style="font-size:13px;color:var(--muted);margin-bottom:10px;">同一时间窗口（SKHY 上市至今）。SKHY 用其最优参数；DRAM 用原报告策略（7天+15% 对称）<strong>延续滚动</strong>（从 4 月建仓滚到现在，不重新建仓）。资金收益率 = 策略净值变化 ÷ 期初市值（100 股 × 首日收盘价）。</p>
<div class="tbl-scroll">
<table>
<tr><th>指标</th><th>SKHY（最优：{best_label} 跌{best['down']}%/涨{best['up']}%）</th><th>DRAM（7天+15% 对称，延续滚动）</th></tr>
<tr><td>B&H 资金收益率</td><td class="{pc(bh['total'])}">{bh['total']/(meta['entry_price']*100)*100:+.1f}%</td><td class="{pc(dram_cmp['bh_ret'])}">{dram_cmp['bh_ret']:+.1f}%</td></tr>
<tr><td>B&H 回撤比例</td><td class="c-green">{bh['mdd_pct']:.1f}%</td><td class="c-green">{dram_cmp['bh_mdd']:.1f}%</td></tr>
<tr><td><strong>策略资金收益率</strong></td><td class="{pc(skhy_ret)}"><strong>{skhy_ret:+.1f}%</strong></td><td class="{pc(dram_cmp['st_ret'])}">{dram_cmp['st_ret']:+.1f}%</td></tr>
<tr><td><strong>策略回撤比例</strong></td><td class="c-green"><strong>{best['mdd_pct']:.1f}%</strong></td><td class="c-green">{dram_cmp['st_mdd']:.1f}%</td></tr>
<tr><td><strong>收益/回撤比</strong></td><td class="{pc(best['ratio'])}"><strong>{best['ratio']:.2f}</strong></td><td class="{pc(dram_cmp['st_ratio'])}">{dram_cmp['st_ratio']:.2f}</td></tr>
</table>
</div>
<div class="callout">
<strong>同期对比结论</strong>：同样这 {dram_cmp['days']} 个交易日里，<strong>DRAM 跌了 {dram_cmp['bh_ret']:+.1f}%，SKHY 涨了 {bh['total']/(meta['entry_price']*100)*100:+.1f}%</strong>。买 put 对冲在两者身上都赚钱，但幅度不同：
<ul style="font-size:13px;padding-left:20px;line-height:1.9;">
<li><strong>SKHY 买 put 大赚</strong>：策略收益率 {skhy_ret:+.1f}%（B&H 仅 +2.0%），回撤从 {bh['mdd_pct']:.1f}% 降到 {best['mdd_pct']:.1f}%——因为次新股波动极大（一周动辄 ±15%），put 频繁赔付、远超保费。</li>
<li><strong>DRAM 同期买 put 也赚</strong>：策略收益率 {dram_cmp['st_ret']:+.1f}%（B&H {dram_cmp['bh_ret']:+.1f}%），回撤从 {dram_cmp['bh_mdd']:.1f}% 降到 {dram_cmp['st_mdd']:.1f}%——7 月 DRAM 有两波大跌（07-10、07-23 附近），put 赔付超过了保费，把下跌的股票亏损扭转为净赚。</li>
<li><strong>核心规律</strong>：买 put 对冲的收益，取决于「实际波动 vs 隐含波动」的差。两者这段都正期望，但 SKHY 次新股波动更极端（一周 ±15%），put 赔付幅度更大，所以赚得更多（{skhy_ret:+.1f}% vs {dram_cmp['st_ret']:+.1f}%）。</li>
</ul>
</div>
</div>

<div class="card">
<h2>数据与结论说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>⚠️ 数据长度限制</strong>：SKHY 于 2026-07-13 在 Nasdaq 上市（ADR），至今仅 {meta['n_days']} 个交易日（约 6 周）。样本极少，仅 {best['n_rounds']} 轮交易，本报告的参数结论可靠性远低于长周期回测，仅供研究参考。</li>
<li><strong>真实成交价</strong>：Put 成本用每日期权链的成交量加权价（vw），不是 Black-Scholes 理论价 + 假设 IV。</li>
<li><strong>多到期日数据</strong>：SKHY_options_3fri.json 每天含 3 个周五到期日（dte 1-4 / 6-11 / 13-21 天），可真实对比不同周期，无需 BS 外推。</li>
<li><strong>开盘价熔断</strong>：只在美国开盘瞬间判断一次，盘中 low/high 不触发——符合「不盯盘」的实盘操作。</li>
<li><strong>回撤口径</strong>：逐日净值 = 股票市值 + 累计 Put 现金流，MDD = 峰值到谷底最大回撤。</li>
<li><strong>不对称扫描</strong>：涨熔断与跌熔断独立扫描（{len(ASYM_MOVES)}×{len(ASYM_MOVES)} 组合），发现 SKHY 最优是「跌 {best['down']}% + 涨 {best['up']}%」，与 DRAM 的对称 15% 不同——两标的最优参数不能通用。</li>
<li><strong>未计交易摩擦</strong>：实盘佣金 + bid-ask 价差会吃掉部分优势，周期越短越明显。</li>
<li><strong>结果依赖这段行情</strong>：SKHY 先涨后暴跌（${meta['entry_price']:.2f} → ~${meta['max_price']:.0f} → ${meta['min_price']:.2f}），高波动是策略赚钱的前提。仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"最终报告已生成: {OUT_HTML}")
    print(f"最优: {best_label} + 跌 {best['down']}% / 涨 {best['up']}%, 收益 ${best['total']:+,.0f}, 回撤 {best['mdd_pct']:.1f}%, 比 {best['ratio']:.2f}")


if __name__ == "__main__":
    main()
