#!/usr/bin/env python3
"""
SKHY 自适应策略 —— 熔断参数最优化扫描（临时程序，不动 final）
================================================================
策略（用户指定，固定结构切换规则）：
  · put 比 call 贵        → 1 call + 1 put（跨式）
  · put 比 call 便宜/相等 → 2 put + 100 股

本次只扫描「熔断参数」：
  · 跌熔断 down : 5 / 8 / 10 / 12 / 15 / 20 / 25 %
  · 涨熔断 up   : 5 / 8 / 10 / 12 / 15 / 20 / 25 %
  · 周期 target 固定为 2（最近周五，adaptive 当前默认）

结算口径：熔断/到期/持有中一律按内在价值结算（2026-09-15 修正前视偏差）。

输出临时报告：skhy_adaptive_rescan_report.html
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SK = os.path.dirname(os.path.abspath(__file__))
DATA = "/Users/gavinz/git/finance/data"
OUT = os.path.join(SK, "skhy_adaptive_rescan_report.html")

sys.path.insert(0, SK)
import skhy_adaptive as A
run_adaptive = A.run_adaptive
round_mdd = A.round_mdd

TARGET = 2  # 最近周五（固定）
DOWNS = [5, 8, 10, 12, 15, 20, 25]
UPS = [5, 8, 10, 12, 15, 20, 25]


def pc(v):
    return "c-red" if v > 0 else ("c-green" if v < 0 else "c-gray")


def money(v):
    return f'<span class="{pc(v)}">${v:+,.0f}</span>'


def bg(value, vmin, vmax, kind):
    """热力图单元格背景色：kind='pnl' 红涨绿跌，kind='ratio' 金色深浅"""
    if vmax == vmin:
        a = 0.0
    else:
        a = (value - vmin) / (vmax - vmin)
    a = max(0.0, min(1.0, a))
    if kind == "pnl":
        if value >= 0:
            return f"background:rgba(255,82,82,{0.08 + 0.30 * a});"
        else:
            return f"background:rgba(38,194,129,{0.08 + 0.30 * (1 - a)});"
    else:  # ratio
        return f"background:rgba(245,195,68,{0.06 + 0.30 * a});"


def main():
    data = json.load(open(os.path.join(DATA, "SKHY_options_3fri.json")))
    day_map = {d["date"]: d for d in data}
    stock = json.load(open(os.path.join(DATA, "SKHY_stock.json")))
    closes = {r[0]: r[4] for r in stock}
    bars = {r[0]: r for r in stock}

    print(f"SKHY 数据: {stock[0][0]} ~ {stock[-1][0]} ({len(stock)} 交易日)")

    # ============ 熔断二维扫描 ============
    results = []
    for down in DOWNS:
        for up in UPS:
            r = run_adaptive(day_map, closes, bars, stock, down, TARGET, up_pct=up)
            mdd = round_mdd(r["rounds"], lambda rd: rd["pnl"])
            r["down"] = down
            r["up"] = up
            r["mdd"] = mdd
            r["ratio"] = r["total"] / mdd if mdd > 0 else 0
            results.append(r)
    print(f"扫描完成: {len(results)} 组熔断组合")

    best = max(results, key=lambda x: x["ratio"])
    best_total = max(results, key=lambda x: x["total"])
    print(f"最优(收益/回撤比): 跌{best['down']}%/涨{best['up']}% -> 收益${best['total']:+,.0f} "
          f"回撤${best['mdd']:,.0f} 比{best['ratio']:.2f}")
    print(f"最优(总收益): 跌{best_total['down']}%/涨{best_total['up']}% -> 收益${best_total['total']:+,.0f} "
          f"回撤${best_total['mdd']:,.0f} 比{best_total['ratio']:.2f}")

    # 当前参数（adaptive 默认跌15/涨8）对比
    cur = next(r for r in results if r["down"] == 15 and r["up"] == 8)

    # ============ 敏感性切片 ============
    def slice_rows(fixed_kind, fixed_val, sweep_vals, sweep_kind):
        """固定一个参数，扫另一个。返回 html 行列表。"""
        rows = []
        for v in sweep_vals:
            if fixed_kind == "down":
                down, up = fixed_val, v
            else:
                down, up = v, fixed_val
            r = next(x for x in results if x["down"] == down and x["up"] == up)
            is_best = (r is best)
            mark = ' <span class="c-gold">★</span>' if is_best else ""
            rows.append(
                f'<tr><td>{v}%</td>'
                f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
                f'<td>${r["mdd"]:,.0f}</td>'
                f'<td class="c-gold">{r["ratio"]:.2f}</td>'
                f'<td>{r["n_rounds"]}</td>'
                f'<td>跨式{r["n_straddle"]} / 2put{r["n_2put"]}</td>'
                f'<td>{r["down_hits"]}</td><td>{r["up_hits"]}</td><td>{r["expiries"]}</td></tr>'
            )
        return "\n".join(rows)

    up_slice_html = slice_rows("down", 15, UPS, "up")   # 固定跌15%，扫涨
    down_slice_html = slice_rows("up", 8, DOWNS, "down")  # 固定涨8%，扫跌

    # ============ 熔断矩阵（收益 + 回撤比）============
    pnl_mat = {d: [next(x for x in results if x["down"] == d and x["up"] == u)["total"] for u in UPS] for d in DOWNS}
    ratio_mat = {d: [next(x for x in results if x["down"] == d and x["up"] == u)["ratio"] for u in UPS] for d in DOWNS}
    pnl_vals = [v for d in DOWNS for v in pnl_mat[d]]
    ratio_vals = [v for d in DOWNS for v in ratio_mat[d]]

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

    pnl_matrix_html = matrix_html(pnl_mat, pnl_vals, "pnl", "熔断矩阵 —— 总收益")
    ratio_matrix_html = matrix_html(ratio_mat, ratio_vals, "ratio", "熔断矩阵 —— 收益/回撤比")

    # Top 10
    top10 = sorted(results, key=lambda x: x["ratio"], reverse=True)[:10]
    top10_rows = []
    for i, r in enumerate(top10, 1):
        is_best = (r is best)
        mark = ' <span class="c-gold">★最优</span>' if is_best else ""
        n_s = r["n_straddle"]; n_2 = r["n_2put"]
        top10_rows.append(
            f'<tr><td>{i}</td>'
            f'<td>{r["down"]}%</td><td>{r["up"]}%</td>'
            f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
            f'<td>${r["mdd"]:,.0f}</td>'
            f'<td class="c-gold">{r["ratio"]:.2f}</td>'
            f'<td>{r["n_rounds"]}</td>'
            f'<td>跨式{n_s} / 2put{n_2}</td>'
            f'<td>{r["down_hits"]}</td><td>{r["up_hits"]}</td><td>{r["expiries"]}</td></tr>'
        )
    top10_html = "\n".join(top10_rows)

    # 旧 vs 新 对比
    def cmp_row(name, r, is_best=False):
        mark = ' <span class="c-gold">★最优</span>' if is_best else ""
        return (f'<tr><td style="color:var(--muted);">{name}</td>'
                f'<td>{r["down"]}%</td><td>{r["up"]}%</td>'
                f'<td class="{pc(r["total"])}">${r["total"]:+,.0f}{mark}</td>'
                f'<td>${r["mdd"]:,.0f}</td><td class="c-gold">{r["ratio"]:.2f}</td>'
                f'<td>{r["n_rounds"]}</td></tr>')

    cmp_rows = (cmp_row("当前参数（adaptive 默认）", cur) +
                cmp_row("新最优（收益/回撤比）", best, is_best=True))

    # 最优组合逐轮明细
    detail_rows = []
    for rd in reversed(best["rounds"]):
        struct_txt = ("<span class='c-gold'>跨式</span>" if rd["struct"] == "straddle"
                      else "<span class='c-red'>2put</span>")
        if rd["kind"] == "持有中":
            exit_cell = f'<td>{rd.get("expiry", rd["exit_date"])} 到期</td>'
        else:
            exit_cell = f'<td>{rd["exit_date"]}</td>'
        detail_rows.append(
            f'<tr><td>{rd["entry_date"]}</td>{exit_cell}<td>{rd["kind"]}</td>'
            f'<td>{struct_txt}</td>'
            f'<td>${rd["entry_spot"]:.1f}</td><td>${rd["exit_spot"]:.1f}</td><td>${rd["strike"]:g}</td>'
            f'<td>${rd["put_price"]:.2f}</td><td>${rd["call_price"]:.2f}</td>'
            f'<td class="c-green">${rd["cost"]:,.0f}</td>'
            f'<td class="c-red">${rd["income"]:+,.0f}</td>'
            f'<td class="{pc(rd["pnl"])}">${rd["pnl"]:+,.0f}</td></tr>'
        )
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

    def kpi(label, value_html, sub=""):
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value_html}</div><div class="sub">{sub}</div></div>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>SKHY 自适应策略 —— 熔断参数最优化扫描</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<h1>SKHY 自适应策略 —— 熔断参数最优化扫描</h1>
<p class="sub">结构切换固定（put 贵→跨式，put 便宜→2put）· 只扫熔断参数 · 周期=最近周五 · 熔断按内在价值结算 · 数据 {stock[0][0]} ~ {stock[-1][0]}（{len(stock)} 交易日） · 生成于 {datetime.now(ET).strftime('%Y-%m-%d %H:%M')}（美东 ET）</p>

<div class="kpis">
{kpi('数据跨度', f'{len(stock)} 天', f'{stock[0][0]} ~ {stock[-1][0]}')}
{kpi('新最优总收益', money(best['total']), f'跌{best["down"]}%/涨{best["up"]}%')}
{kpi('新最优回撤', f'${best["mdd"]:,.0f}', f'收益/回撤比 {best["ratio"]:.2f}')}
{kpi('总收益最高组合', money(best_total['total']), f'跌{best_total["down"]}%/涨{best_total["up"]}% · 回撤${best_total["mdd"]:,.0f}')}
{kpi('当前参数(跌15/涨8)', money(cur['total']), f'回撤${cur["mdd"]:,.0f} · 比 {cur["ratio"]:.2f}')}
</div>

<div class="callout">
<strong>结论：</strong>在自适应策略（put 贵→跨式，put 便宜→2put）框架下，扫描 {len(results)} 组熔断参数后，<strong class="c-gold">最优（收益/回撤比）</strong>为：
跌熔断 <strong>{best["down"]}%</strong>、涨熔断 <strong>{best["up"]}%</strong>，
总收益 <strong class="{pc(best['total'])}">${best['total']:+,.0f}</strong>、回撤 <strong>${best['mdd']:,.0f}</strong>、收益/回撤比 <strong class="c-gold">{best['ratio']:.2f}</strong>。
<br><br>
<strong style="color:var(--gold);">⚠️ 但这是一个「孤立的尖峰」</strong>——最优点（跌15%/涨8%）周围一圈参数几乎全是负收益（见下方矩阵）。
49 组里只有这 1 个点是显著赚钱的，它的邻居（跌15/涨10 → $2,101、跌10/涨8 → $110、跌20/涨8 → −$1,537）要么大幅缩水要么直接转负。
这意味着最优参数对数据极度敏感，是 44 个交易日里「某几次 +8%~+9% 上涨 + 两次 -16% 大跌」被刚好框住的产物，<strong>换一段行情这个尖峰就会移动甚至消失</strong>，不能当稳定规律。
</div>

<div class="card">
<h2 style="margin-top:0;">当前参数 vs 新最优</h2>
<div class="tbl-scroll">
<table>
<tr><th>参数集</th><th>跌熔断</th><th>涨熔断</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th></tr>
{cmp_rows}
</table>
</div>
<p class="note">当前参数 = 自适应策略默认的跌15%/涨8%。回撤为「累计逐轮盈亏曲线最大回撤」（绝对金额），与 adaptive 报告口径一致。</p>
</div>

<div class="card">
<h2 style="margin-top:0;">Top 10 熔断组合（按收益/回撤比排序）</h2>
<div class="tbl-scroll">
<table>
<tr><th>#</th><th>跌熔断</th><th>涨熔断</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th><th>结构分布</th><th>跌触发</th><th>涨触发</th><th>到期</th></tr>
{top10_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">熔断比例扫描（不对称矩阵）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">固定周期=最近周五，扫描跌熔断 × 涨熔断。★ 单元格为全局最优（回撤比口径）。</p>
{pnl_matrix_html}
{ratio_matrix_html}
</div>

<div class="card">
<h2 style="margin-top:0;">涨熔断敏感性（固定跌熔断 15%）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">只改涨熔断，看收益如何随涨熔断变化。★ = 全局最优点。关键：涨熔断从 8% 抬到 10%，收益从 $3,617 掉到 $2,101；抬到 25% 直接 −$2,820。</p>
<div class="tbl-scroll">
<table>
<tr><th>涨熔断</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th><th>结构分布</th><th>跌触发</th><th>涨触发</th><th>到期</th></tr>
{up_slice_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">跌熔断敏感性（固定涨熔断 8%）</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">只改跌熔断。★ = 全局最优点。关键：跌熔断从 15% 降到 10% 或升到 20%，收益都从 +$3,617 崩到 $110 或 −$1,537。</p>
<div class="tbl-scroll">
<table>
<tr><th>跌熔断</th><th>总收益</th><th>回撤</th><th>收益/回撤比</th><th>轮数</th><th>结构分布</th><th>跌触发</th><th>涨触发</th><th>到期</th></tr>
{down_slice_html}
</table>
</div>
</div>

<div class="card">
<h2 style="margin-top:0;">新最优组合逐轮明细</h2>
<p class="note" style="margin-top:0;margin-bottom:10px;">跌{best["down"]}%/涨{best["up"]}%。结构：<span class="c-gold">跨式</span>=1call+1put（put贵时），<span class="c-red">2put</span>=2put+100股（put便宜时）。方式：到期 / 上涨再平衡 / 下跌止盈 / 持有中。</p>
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
<li><strong>结构切换规则固定</strong>：每轮入场看 ATM put 权利金 vs call 权利金，put 贵→跨式（1call+1put），put 便宜/相等→2put+100股。本次只优化熔断参数，不改结构规则。</li>
<li><strong>结算口径</strong>：熔断/到期/持有中一律按<strong>内在价值</strong>结算（2026-09-15 修正前视偏差）。涨熔断时 put 虚值归零。</li>
<li><strong>回撤口径</strong>：统一用「累计逐轮盈亏曲线最大回撤」（绝对金额），与 adaptive 报告内部口径一致。</li>
<li><strong>本程序为临时扫描</strong>（<code>rescan_skhy_adaptive.py</code>），不改动 final 程序/报告。</li>
<li><strong>过拟合警示</strong>：SKHY 仅 {len(stock)} 个交易日，样本短、波动大，参数稳定性低，仅供研究，不构成投资建议。</li>
<li><strong>关于最优参数的可靠性</strong>：本次最优（跌15%/涨8%）在 49 组里是唯一显著为正的「孤立尖峰」，周围邻居大多转负。这是参数对样本过拟合的典型特征——它精准命中了 44 天里「两次 -16% 大跌 + 若干次 +8%~+9% 上涨」的节奏，但换一段行情（比如没有那两次大跌、或上涨幅度普遍超过 10%）这个点就会失效。建议把它当作「这段行情的事后最优」，而非「可外推的规律」。</li>
</ul>
</div>

</div>
</body>
</html>"""

    with open(OUT, "w") as f:
        f.write(html)
    print(f"\n临时报告已生成: {OUT}")
    print(f"  扫描 {len(results)} 组熔断 → 最优比 {best['ratio']:.2f} (当前 {cur['ratio']:.2f})")


if __name__ == "__main__":
    main()
