#!/usr/bin/env python3
"""
SKHY 自适应策略 —— 每轮按 put/call 相对贵贱动态切换结构
================================================================
规则（用户指定）：
  · put 比 call 贵        → 1 call + 1 put（跨式，纯做多波动）
  · put 比 call 便宜/相等 → 2 put + 100 股（股票 + 2张put对冲）

依据：put skew 决定哪种结构成本更划算——
  · put 贵（市场对下跌担忧高，skew 大）→ 买 2 张贵 put 太烧钱，改买 1 put + 1 相对便宜的 call；
  · put 便宜（慢牛/乐观）→ 2 张便宜 put 对冲 + 100 股吃慢牛上涨。

结算口径（2026-09-15 修正）：熔断平仓一律按内在价值结算（消除前视偏差）。

输出临时报告：skhy_adaptive_report.html（不动 final）
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SK = os.path.dirname(os.path.abspath(__file__))
DATA = "/Users/gavinz/git/finance/data"
OUT = os.path.join(SK, "skhy_adaptive_report.html")

sys.path.insert(0, SK)
import real_options_backtest_v10 as v10mod
import rescan_skhy_straddle as st
pick_friday = v10mod.pick_friday
atm_put = v10mod.atm_put
run_v10 = v10mod.run_v10
run_straddle = st.run_straddle

DOWN = 15
UP = 8
TARGET = 2  # 最近周五


def run_adaptive(day_map, closes, bars, stock, move_pct, target, up_pct=None):
    net = 0.0
    rounds = []
    down_hits = up_hits = expiries = 0
    n_straddle = n_2put = 0
    pos = None
    d = move_pct / 100.0
    u = (up_pct if up_pct is not None else move_pct) / 100.0

    def open_pos(date, spot):
        day = day_map.get(date)
        if day is None:
            return None
        f = pick_friday(day, target)
        if f is None or not f["puts"] or not f["calls"]:
            return None
        p = atm_put(f, spot)
        if p is None:
            return None
        K = p["strike"]
        c = next((x for x in f["calls"] if abs(x["strike"] - K) < 1e-9), None)
        if c is None:
            return None
        put_price = p["vw"]
        call_price = c["vw"]
        # 决策：put 比 call 贵 → straddle；否则 → 2put + 股票
        if put_price > call_price:
            struct = "straddle"
            cost = (call_price + put_price) * 100
        else:
            struct = "2put"
            cost = put_price * 100 * 2
        return dict(expiry=f["expiry"], strike=K,
                    put_price=put_price, call_price=call_price,
                    struct=struct, cost=cost, entry_spot=spot, entry_date=date)

    def settle(struct, exit_price, strike, entry_spot):
        """返回 (income, stock_pnl, put_payoff, call_payoff)"""
        if struct == "straddle":
            call_pay = max(exit_price - strike, 0.0) * 100
            put_pay = max(strike - exit_price, 0.0) * 100
            return call_pay + put_pay, 0.0, put_pay, call_pay
        else:  # 2put
            stock_pnl = (exit_price - entry_spot) * 100
            put_pay = max(strike - exit_price, 0.0) * 100 * 2
            return stock_pnl + put_pay, stock_pnl, put_pay, 0.0

    def record(pos, kind, exit_date, exit_price):
        income, stock_pnl, put_pay, call_pay = settle(
            pos["struct"], exit_price, pos["strike"], pos["entry_spot"])
        pnl = income - pos["cost"]
        rounds.append(dict(
            kind=kind, entry_date=pos["entry_date"], exit_date=exit_date,
            struct=pos["struct"], strike=pos["strike"],
            entry_spot=pos["entry_spot"], exit_spot=exit_price,
            put_price=pos["put_price"], call_price=pos["call_price"],
            cost=pos["cost"], income=income, pnl=pnl,
            stock_pnl=stock_pnl, put_payoff=put_pay, call_payoff=call_pay,
            expiry=pos["expiry"]))

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
                if pos["struct"] == "straddle":
                    n_straddle += 1
                else:
                    n_2put += 1
            continue

        p0 = pos["entry_spot"]
        dn_hit = o <= p0 * (1 - d)
        up_hit = o >= p0 * (1 + u)

        if date >= pos["expiry"]:
            if dn_hit or up_hit:
                exit_price = o
                kind = "下跌止盈" if dn_hit else "上涨再平衡"
                if dn_hit:
                    down_hits += 1
                else:
                    up_hits += 1
            else:
                exit_price = S
                kind = "到期"
                expiries += 1
            record(pos, kind, date, exit_price)
            pos = open_pos(date, exit_price)
            if pos is not None:
                if pos["struct"] == "straddle":
                    n_straddle += 1
                else:
                    n_2put += 1
            continue

        if dn_hit:
            record(pos, "下跌止盈", date, o)
            down_hits += 1
            pos = open_pos(date, o)
            if pos is not None:
                if pos["struct"] == "straddle":
                    n_straddle += 1
                else:
                    n_2put += 1
            continue

        if up_hit:
            record(pos, "上涨再平衡", date, o)
            up_hits += 1
            pos = open_pos(date, o)
            if pos is not None:
                if pos["struct"] == "straddle":
                    n_straddle += 1
                else:
                    n_2put += 1
            continue

    # 末尾未平仓 mark-to-market
    if pos is not None:
        last_date = stock[-1][0]
        S_last = closes[last_date]
        record(pos, "持有中", last_date, S_last)

    total = sum(rd["pnl"] for rd in rounds)
    return dict(total=total, rounds=rounds, n_rounds=len(rounds),
                down_hits=down_hits, up_hits=up_hits, expiries=expiries,
                n_straddle=n_straddle, n_2put=n_2put)


def round_mdd(rounds, pnl_fn):
    """累计逐轮盈亏曲线的最大回撤（绝对金额），对三种结构口径统一。"""
    sorted_rounds = sorted(rounds, key=lambda r: r["entry_date"])
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for rd in sorted_rounds:
        cum += pnl_fn(rd)
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return mdd


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def main():
    data = json.load(open(os.path.join(DATA, "SKHY_options_3fri.json")))
    day_map = {d["date"]: d for d in data}
    stock = json.load(open(os.path.join(DATA, "SKHY_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}
    se = closes[stock[0][0]]
    sx = closes[stock[-1][0]]

    # 自适应策略
    adp = run_adaptive(day_map, closes, bars, stock, DOWN, TARGET, up_pct=UP)
    adp_mdd = round_mdd(adp["rounds"], lambda rd: rd["pnl"])
    adp_ratio = adp["total"] / adp_mdd if adp_mdd > 0 else 0

    # 固定 2put
    fixed_2put = run_v10(day_map, closes, bars, stock, se, sx, DOWN, TARGET, num_puts=2, up_pct=UP)
    f2p_rounds = [dict(entry_date=rd["entry_date"], pnl=rd["stock_pnl"] + rd["pnl"]) for rd in fixed_2put["rounds"]]
    f2p_sum = sum(r["pnl"] for r in f2p_rounds)
    f2p_mdd = round_mdd(f2p_rounds, lambda rd: rd["pnl"])
    f2p_ratio = f2p_sum / f2p_mdd if f2p_mdd > 0 else 0

    # 固定跨式
    fixed_strad = run_straddle(day_map, closes, bars, stock, DOWN, TARGET, up_pct=UP)
    fst_rounds = [dict(entry_date=rd["entry_date"], pnl=rd["pnl"]) for rd in fixed_strad["rounds"]]
    fst_sum = sum(r["pnl"] for r in fst_rounds)
    fst_mdd = round_mdd(fst_rounds, lambda rd: rd["pnl"])
    fst_ratio = fst_sum / fst_mdd if fst_mdd > 0 else 0

    print(f"自适应: total ${adp['total']:+,.0f}  mdd ${adp_mdd:,.0f}  ratio {adp_ratio:.2f}  "
          f"straddle {adp['n_straddle']} 轮 / 2put {adp['n_2put']} 轮")
    print(f"固定2put: total ${f2p_sum:+,.0f}  mdd ${f2p_mdd:,.0f}  ratio {f2p_ratio:.2f}")
    print(f"固定跨式: total ${fst_sum:+,.0f}  mdd ${fst_mdd:,.0f}  ratio {fst_ratio:.2f}")

    # 逐轮明细
    detail_rows = []
    for rd in adp["rounds"]:
        struct_txt = ("<span class='c-gold'>跨式</span>" if rd["struct"] == "straddle"
                      else "<span class='c-red'>2put</span>")
        if rd["kind"] == "持有中":
            exit_cell = f'{rd.get("expiry", rd["exit_date"])} 到期'
        else:
            exit_cell = rd["exit_date"]
        # 成本/收入拆解（按结构）
        if rd["struct"] == "straddle":
            cost_cell = f'<span class="c-green">${rd["call_price"]*100:,.0f}+${rd["put_price"]*100:,.0f}</span>'
            inc_cell = f'<span class="c-red">${rd["income"]:+,.0f}</span>'
        else:
            cost_cell = f'<span class="c-green">${rd["put_price"]*200:,.0f}</span>'
            inc_cell = f'<span class="c-red">${rd["put_payoff"]:+,.0f}</span>'
        detail_rows.append(
            f'<tr>'
            f'<td>{rd["entry_date"]}</td>{f"<td>{exit_cell}</td>"}<td>{rd["kind"]}</td>'
            f'<td>{struct_txt}</td>'
            f'<td>${rd["entry_spot"]:.1f}</td><td>${rd["exit_spot"]:.1f}</td><td>${rd["strike"]:g}</td>'
            f'<td>${rd["put_price"]:.2f}</td><td>${rd["call_price"]:.2f}</td>'
            f'<td>{cost_cell}</td><td>{inc_cell}</td>'
            f'<td class="{pc(rd["pnl"])}">${rd["pnl"]:+,.0f}</td>'
            f'</tr>')
    detail_html = "\n".join(detail_rows)

    # 结构分布
    n_total = adp["n_rounds"]
    pct_s = adp["n_straddle"] / n_total * 100 if n_total else 0
    pct_2 = adp["n_2put"] / n_total * 100 if n_total else 0

    css = """
:root { --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e6e8ec; --muted:#9aa3b2;
  --red:#ff5252; --green:#26c281; --accent:#4da3ff; --gold:#f5c344; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }
.wrap { max-width:1240px; margin:0 auto; }
h1 { font-size:24px; margin-bottom:6px; }
h2 { font-size:18px; margin:30px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }
.sub { color:var(--muted); font-size:13px; margin-bottom:24px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:18px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }
.kpi .label { color:var(--muted); font-size:13px; font-weight:600; }
.kpi .value { font-size:22px; font-weight:700; margin-top:4px; }
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
  padding:12px 16px; margin:12px 0; font-size:13px; line-height:1.9; }
.note { color:var(--muted); font-size:12px; margin-top:8px; }
code { background:#20242d; border:1px solid var(--border); border-radius:4px; padding:1px 6px;
  font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; color:var(--gold); }
.tbl-scroll { overflow-x:auto; }
"""

    def kpi(label, value_html, sub=""):
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value_html}</div><div class="sub">{sub}</div></div>')

    # 三策略对比行
    def cmp_row(name, total, mdd, ratio, extra, best=False):
        mark = ' <span class="c-gold">★最优</span>' if best else ""
        return (f'<tr><td>{name}{mark}</td>'
                f'<td class="{pc(total)}">${total:+,.0f}</td>'
                f'<td>${mdd:,.0f}</td>'
                f'<td class="c-gold">{ratio:.2f}</td>'
                f'<td>{extra}</td></tr>')

    best_name = max([("自适应", adp["total"], adp_ratio), ("固定2put", f2p_sum, f2p_ratio), ("固定跨式", fst_sum, fst_ratio)],
                    key=lambda x: x[2])[0]

    cmp_html = (
        cmp_row("自适应（put贵→跨式，put便宜→2put）", adp["total"], adp_mdd, adp_ratio,
                f'{adp["n_rounds"]} 轮 · 跨式{adp["n_straddle"]} / 2put{adp["n_2put"]}', best_name == "自适应") +
        cmp_row("固定 2put（100股+2put）", f2p_sum, f2p_mdd, f2p_ratio, f'{len(f2p_rounds)} 轮', best_name == "固定2put") +
        cmp_row("固定 跨式（1call+1put）", fst_sum, fst_mdd, fst_ratio, f'{len(fst_rounds)} 轮', best_name == "固定跨式")
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>SKHY 自适应策略报告</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<h1>SKHY 自适应策略：按 put/call 贵贱动态切换结构</h1>
<p class="sub">规则：put 比 call 贵 → 1 call + 1 put（跨式）；put 比 call 便宜/相等 → 2 put + 100 股 · 最近周五 + 跌{DOWN}%/涨{UP}% · 熔断按内在价值结算 · 数据 {stock[0][0]} ~ {stock[-1][0]}（{len(stock)} 交易日） · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="kpis">
{kpi('自适应总收益', money(adp['total']), f'共 {adp["n_rounds"]} 轮')}
{kpi('回撤(逐轮累计)', f'${adp_mdd:,.0f}', f'收益/回撤比 {adp_ratio:.2f}')}
{kpi('结构分布', f'{adp["n_straddle"]} : {adp["n_2put"]}', f'跨式 {pct_s:.0f}% / 2put {pct_2:.0f}%')}
{kpi('触发统计', f'跌{adp["down_hits"]} / 涨{adp["up_hits"]} / 到期{adp["expiries"]}', '')}
</div>

<div class="callout">
<strong>策略逻辑：</strong>每轮入场时看 ATM 期权的 <strong>put 权利金 vs call 权利金</strong>——
put 贵（skew 大、市场担忧下跌）时，买 2 张贵 put 太烧钱，改买 <strong>1 put + 1 相对便宜的 call</strong>（跨式）；
put 便宜（慢牛/乐观）时，用 <strong>2 张便宜 put 对冲 + 100 股吃慢牛上涨</strong>。
本质是把「put skew」这个因子变成每轮的择时开关。
</div>

<div class="card">
<h2 style="margin-top:0;">三策略对比（统一逐轮累计回撤口径）</h2>
<div class="tbl-scroll">
<table>
<tr><th>策略</th><th>总收益</th><th>回撤(逐轮累计)</th><th>收益/回撤比</th><th>说明</th></tr>
{cmp_html}
</table>
</div>
<p class="note">回撤 = 累计逐轮盈亏曲线的最大回撤（绝对金额），三种结构统一口径，可直接对比。固定 2put 逐轮盈亏 = 股票端 + put 净。</p>
</div>

<div class="card">
<h2 style="margin-top:0;">自适应策略逐轮明细</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">
「结构」列：<span class="c-gold">跨式</span> = put 比 call 贵时选的 1call+1put；<span class="c-red">2put</span> = put 比 call 便宜时选的 2put+100股。
「成本」列：跨式 = call权利金+put权利金；2put = 2×put权利金。「收入」列：跨式 = call/put 结算收入；2put = put 结算收入（股票端见利润）。
</p>
<div class="tbl-scroll">
<table>
<tr><th>入场日</th><th>出场日</th><th>方式</th><th>结构</th><th>入场spot</th><th>出场spot</th><th>行权价</th><th>put价</th><th>call价</th><th>成本</th><th>收入</th><th>利润</th></tr>
{detail_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">说明</h2>
<ul style="font-size:13px;color:var(--text);padding-left:20px;line-height:1.9;">
<li><strong>结算口径</strong>：熔断平仓、到期、持有中（mark-to-market）一律按<strong>内在价值</strong>结算（2026-09-15 修正前视偏差）。涨熔断时 put 深度虚值归零；跌熔断时实值腿按内在价值结算。持有中估值不再用全天 vw（否则"最后一天刚买入的仓"估值恒等于成本、净利恒 0）。</li>
<li><strong>决策时点</strong>：每轮入场日开盘，选 ATM 行权价，取该行权价 put 与 call 的 vw 权利金，比较后定结构。判断用「put_vw &gt; call_vw」。</li>
<li><strong>2put 结构</strong>：利润 = 股票端涨跌 + put 结算收入 − 2×put权利金。</li>
<li><strong>跨式结构</strong>：利润 = (call + put 结算收入) − (call + put 权利金)。无股票本金。</li>
<li><strong>回撤口径</strong>：统一用「累计逐轮盈亏曲线最大回撤」，与 final 报告的「相对市值百分比」/「现金净值」口径不同，仅本报告内部三策略对比时一致。</li>
<li><strong>本程序为临时策略</strong>（<code>skhy_adaptive.py</code>），不改动 final 程序/报告。</li>
<li><strong>过拟合警示</strong>：SKHY 仅 {len(stock)} 个交易日，样本短、波动大，仅供研究，不构成投资建议。</li>
</ul>
</div>

</div>
</body>
</html>"""

    with open(OUT, "w") as f:
        f.write(html)
    print(f"\n自适应策略报告已生成: {OUT}")


if __name__ == "__main__":
    main()
