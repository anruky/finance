#!/usr/bin/env python3
"""Generate the complete QQQ biweekly (2-week) optimal strategy report (monochrome dark theme)."""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_local_backtest as m

# 买 call 对冲参数（已优化）
BUY_CALL_OTM = 0.0   # 买 call 的 OTM（0% = ATM，最及时）
BUY_CALL_NUM = 3     # 买 call 手数

r = m.run('QQQ', m.make_targets(50, 6, 15, 15), options_file='QQQ_options_2wk.json',
          buy_call_otm=BUY_CALL_OTM, buy_call_num=BUY_CALL_NUM)

stock = json.load(open('/Users/gavinz/git/finance/data/QQQ_stock.json'))
dates = [s[0] for s in stock]
closes = [s[4] for s in stock]
S0 = closes[0]
initial = r['initial']
S0_bt = initial / 200.0  # 回测起点股价（2024-08-19），B&H 以此为准（initial = 2手×100股×S0_bt）

# B&H max drawdown (from daily closes)
peak = closes[0]
bh_max_dd = 0.0
for c in closes:
    peak = max(peak, c)
    bh_max_dd = max(bh_max_dd, (peak - c) / peak)
bh_dd_pct = round(bh_max_dd * 100, 2)

# Yearly breakdown
from collections import defaultdict
yr_prem = defaultdict(float)
yr_cycles = defaultdict(int)
yr_states = defaultdict(lambda: defaultdict(int))
yr_end_val = {}
for c in r['cycle_list']:
    y = c['entry'][:4]
    yr_prem[y] += c['prem']
    yr_cycles[y] += 1
    yr_states[y][c['state']] += 1
    yr_end_val[c['expiry'][:4]] = c['value']

yr_close = {}
for d, c in zip(dates, closes):
    yr_close[d[:4]] = c

def yearly_dd(values, start_val):
    allv = [start_val] + list(values)
    pk = allv[0]
    dd = 0.0
    for v in allv:
        pk = max(pk, v)
        dd = max(dd, (pk - v) / pk)
    return dd * 100

yearly_rows = ''
prev_val = initial
prev_bh = S0_bt
bt_start = r['cycle_list'][0]['entry']  # 回测起点日期（期权首日），B&H 从此起算
for y in ['2024', '2025', '2026']:
    endv = yr_end_val.get(y)
    if endv is None:
        continue
    sret = (endv - prev_val) / prev_val * 100
    # 策略年内回撤（周期价值）
    strat_vals = [c['value'] for c in r['cycle_list'] if c['entry'][:4] == y]
    sdd = yearly_dd(strat_vals, prev_val)
    # B&H 年内回撤（日线，从回测起点起算）
    bh_vals = [c for d, c in zip(dates, closes) if d[:4] == y and d >= bt_start]
    bdd = yearly_dd(bh_vals, prev_bh)
    bh_c = yr_close.get(y)
    bret = (bh_c - prev_bh) / prev_bh * 100 if bh_c is not None else 0.0
    if bh_c is not None:
        prev_bh = bh_c
    st = dict(yr_states.get(y, {}))
    st_str = (f"A{st.get('A',0)} B{st.get('B',0)} C{st.get('C',0)} "
              f"D{st.get('D',0)} E{st.get('E',0)}")
    win = 'c-pos' if sret >= bret else 'c-neg'
    yearly_rows += (f"<tr><td class=\"bold\">{y}</td><td>{yr_cycles.get(y, 0)}</td>"
                    f"<td>${yr_prem.get(y, 0):,.0f}</td>"
                    f"<td class=\"{win}\">{sret:+.1f}%</td>"
                    f"<td>{sdd:.2f}%</td>"
                    f"<td>{bret:+.1f}%</td>"
                    f"<td>{bdd:.2f}%</td><td class=\"c-muted\">{st_str}</td></tr>")
    prev_val = endv

labels, sv, bv = [], [], []
for c in r['cycle_list']:
    labels.append(c['expiry'])
    sv.append(c['value'])
    try:
        bv.append(round(initial * closes[dates.index(c['expiry'])] / S0_bt, 0))
    except Exception:
        bv.append(None)
pairs = [(l, s, b) for l, s, b in zip(labels, sv, bv) if b is not None]
labels = [p[0] for p in pairs]
sv = [p[1] for p in pairs]
bv = [p[2] for p in pairs]

cycle_rows_data = []
prev_bh_val = initial
for c in r['cycle_list']:
    chg = c['exp_px'] - c['spot']
    chg_str = f"{chg:+.0f}" if abs(chg) >= 0.5 else "0"
    chg_cls = 'c-pos' if chg >= 0 else 'c-neg'
    pnl_cls = 'c-pos' if c['pnl'] >= 0 else 'c-neg'
    try:
        bh_val = round(initial * closes[dates.index(c['expiry'])] / S0_bt, 0)
    except Exception:
        bh_val = round(200 * c['exp_px'], 0)
    bh_pnl = bh_val - prev_bh_val
    bh_pnl_cls = 'c-pos' if bh_pnl >= 0 else 'c-neg'
    prev_bh_val = bh_val
    cycle_rows_data.append((c, chg_str, chg_cls, pnl_cls, bh_val, bh_pnl, bh_pnl_cls))

# 倒序输出（最新周期在前）
rows = ''
for c, chg_str, chg_cls, pnl_cls, bh_val, bh_pnl, bh_pnl_cls in reversed(cycle_rows_data):
    if c['action1']:
        buy_cost_str = f"${c['buy_call_cost']:,.0f}"
        buy_val_str = f"${c['buy_call_value']:,.0f}"
    else:
        buy_cost_str = '<span class="c-muted">—</span>'
        buy_val_str = '<span class="c-muted">—</span>'
    rows += (f"<tr><td>{c['entry']}</td><td>{c['expiry']}</td><td>{c['spot']:.0f}</td>"
             f"<td>{c['exp_px']:.0f}</td><td class=\"{chg_cls}\">{chg_str}</td>"
             f"<td>{c['put']}</td><td>{c['call']}</td><td>${c['prem']:,.0f}</td>"
             f"<td>{buy_cost_str}</td><td>{buy_val_str}</td>"
             f"<td class=\"bold\">{c['state']}</td>"
             f"<td class=\"{pnl_cls}\">${c['pnl']:+,.0f}</td>"
             f"<td class=\"{bh_pnl_cls}\">${bh_pnl:+,.0f}</td>"
             f"<td>${c['value']:,.0f}</td><td>${bh_val:,.0f}</td></tr>")

# Put/Call OTM per state (for strategy params table)
state_meta = {
    'A': ('低波动（均到期作废）', '50%', '6%'),
    'B': ('大涨（call被行权）', '50%', '6%'),
    'C': ('剧烈震荡后下行', '15%', '15%'),
    'D': ('涨后回调', '50%', '6%'),
    'E': ('大跌（put被行权）', '15%', '15%'),
}
otm_stat = defaultdict(lambda: {'put': [], 'call': []})
for c in r['cycle_list']:
    otm_stat[c['state']]['put'].append((c['spot'] - c['put']) / c['spot'] * 100)
    otm_stat[c['state']]['call'].append((c['call'] - c['spot']) / c['spot'] * 100)

param_rows = ''
for s in ['A', 'B', 'C', 'D', 'E']:
    desc, pt, ct = state_meta[s]
    d = otm_stat.get(s)
    if d and d['put']:
        p, cl = d['put'], d['call']
        potm = f"{sum(p)/len(p):.1f}%（{min(p):.1f}~{max(p):.1f}）"
        cotm = f"{sum(cl)/len(cl):.1f}%（{min(cl):.1f}~{max(cl):.1f}）"
    else:
        potm = cotm = '<span class="c-muted">—</span>'
    param_rows += (f"<tr><td class=\"bold\">{s}</td><td>{desc}</td>"
                   f"<td>{pt}</td><td>{ct}</td>"
                   f"<td>{potm}</td><td>{cotm}</td></tr>")

final_val = r['final']
net = final_val - initial
total_income = r['premium'] + r['gains'] + r['call_value']
total_cost = r['losses'] + r['call_cost']

chart_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chart.umd.min.js')).read()

css = """
:root { --bg:#0d0d0d; --card:#161616; --border:#2e2e2e; --text:#f0f0f0; --muted:#9a9a9a;
  --pos:#ffffff; --neg:#8a8a8a; }
* { box-sizing:border-box; margin:0; padding:0; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6; padding:32px 20px; }
.wrap { max-width:1080px; margin:0 auto; }
h1 { font-size:26px; margin-bottom:6px; }
h2 { font-size:19px; margin:0 0 14px; padding-left:10px; border-left:3px solid var(--pos); }
.sub { color:var(--muted); font-size:13px; margin-bottom:24px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:18px; }
.kpi { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }
.kpi .label { color:var(--muted); font-size:12px; }
.kpi .value { font-size:22px; font-weight:700; margin-top:4px; color:var(--text); }
.card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:18px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th,td { padding:8px 10px; text-align:right; border-bottom:1px solid var(--border); white-space:nowrap; }
th { background:#1e1e1e; color:var(--muted); font-weight:600; }
th:first-child, td:first-child { text-align:left; }
th:nth-child(2), td:nth-child(2) { text-align:left; }
.c-pos { color:var(--pos); font-weight:600; }
.c-neg { color:var(--neg); font-weight:600; }
.c-muted { color:var(--muted); }
.bold { font-weight:700; color:var(--text); }
.note { color:var(--muted); font-size:12px; margin-top:8px; }
.tbl-scroll { overflow:auto; max-height:560px; }
.disc { font-size:11px; color:var(--muted); line-height:1.6; border-top:1px solid var(--border); padding-top:12px; margin-top:20px; }
"""

chart_script = """
new Chart(document.getElementById('c'), {
  type:'line',
  data:{labels:__LABELS__,
    datasets:[
      {label:'Wheel策略', data:__SV__, borderColor:'#ffffff', backgroundColor:'rgba(255,255,255,.10)', fill:true, tension:.3, pointRadius:0, borderWidth:2},
      {label:'买入持有', data:__BV__, borderColor:'#8a8a8a', borderDash:[6,4], tension:.3, pointRadius:0, borderWidth:2, fill:false}
    ]},
  options:{responsive:true, interaction:{mode:'index',intersect:false},
    plugins:{legend:{position:'top',labels:{boxWidth:12,font:{size:11},color:'#f0f0f0'}}},
    scales:{
      x:{ticks:{maxTicksLimit:12,font:{size:10},color:'#9a9a9a'},grid:{color:'#262626'}},
      y:{ticks:{font:{size:10},color:'#9a9a9a',callback:v=>'$'+Math.round(v/1000)+'k'},grid:{color:'#262626'}}
    }}
});
"""
chart_script = (chart_script.replace('__LABELS__', json.dumps(labels))
                            .replace('__SV__', json.dumps(sv))
                            .replace('__BV__', json.dumps(bv)))

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QQQ Wheel 2周周期最优策略报告</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
<h1>QQQ Wheel 策略 · 2周周期最优配置 <span style="color:var(--muted);font-size:15px;">（真实期权数据）</span></h1>
<p class="sub">区间 2024-08-19 ~ 2026-08-14（499 交易日）· 真实历史期权数据（VWAP）· 周期 14 天（周五到期）· 参数 A/B/D 50%/6%，C/E 15%/15%</p>

<div class="kpis">
  <div class="kpi"><div class="label">策略年化收益</div><div class="value c-pos">{r['ann']:.2f}%</div></div>
  <div class="kpi"><div class="label">策略总收益</div><div class="value c-pos">{r['total_ret']:+.2f}%</div></div>
  <div class="kpi"><div class="label">最大回撤</div><div class="value">{r['dd']:.2f}%</div></div>
  <div class="kpi"><div class="label">买入持有年化</div><div class="value">{r['bh_ann']:.2f}%</div></div>
  <div class="kpi"><div class="label">买入持有回撤</div><div class="value">{bh_dd_pct}%</div></div>
  <div class="kpi"><div class="label">周期数</div><div class="value">{r['cycles']}</div></div>
  <div class="kpi"><div class="label">权利金收入</div><div class="value">${r['premium']:,.0f}</div></div>
</div>

<div class="card">
<h2>按年度汇总</h2>
<table>
<thead><tr><th>年份</th><th>周期数</th><th>权利金</th><th>策略收益</th><th>策略回撤</th><th>买入持有</th><th>B&H回撤</th><th>状态分布</th></tr></thead>
<tbody>{yearly_rows}</tbody>
</table>
<p class="note">白色=当年跑赢买入持有，灰色=跑输。2024 为 8月19日起的区间，2026 为截至 8月14日的区间。</p>
</div>

<div class="card">
<h2>策略参数</h2>
<table>
<thead><tr><th>状态</th><th>含义</th><th>卖 Put 年化目标</th><th>卖 Call 年化目标</th><th>Put OTM（均值/范围）</th><th>Call OTM（均值/范围）</th></tr></thead>
<tbody>{param_rows}</tbody>
</table>
<div style="margin-top:12px;padding:12px 16px;background:#1e1e1e;border:1px solid var(--border);border-radius:8px;font-size:13px;">
<strong>买 call 对冲参数（已优化）</strong>：股价触及卖出的 call 行权价时，买 <strong>{BUY_CALL_NUM} 手 {BUY_CALL_OTM*100:.0f}% OTM（ATM）call</strong> 对冲踏空上行。<span class="c-muted">（搜索结论：OTM 越小越好，0% 最优；手数越多牛市收益越高，选 3 手为平衡）</span>
</div>
<p class="note">OTM=行权价相对入场价的偏离（Put 为现价下方、Call 为现价上方），由真实回测数据统计。资金结构：2手资金 = 1手持股 + 1手现金 · 到期日=每两周后的周五</p>
</div>

<div class="card">
<h2>收入与成本</h2>
<table>
<thead><tr><th>收入</th><th>金额</th><th>成本</th><th>金额</th></tr></thead>
<tbody>
<tr><td>权利金收入</td><td>${r['premium']:,.0f}</td><td>股票亏损</td><td>${r['losses']:,.0f}</td></tr>
<tr><td>股票收益</td><td>${r['gains']:,.0f}</td><td>买call权利金</td><td>${r['call_cost']:,.0f}</td></tr>
<tr><td>买call到期收益</td><td>${r['call_value']:,.0f}</td><td></td><td></td></tr>
<tr><td class="bold">合计收入</td><td class="bold">${total_income:,.0f}</td><td class="bold">合计成本</td><td class="bold">${total_cost:,.0f}</td></tr>
</tbody>
</table>
<p class="note">初始资金 ${initial:,.0f} → 终值 ${final_val:,.0f} · 净盈亏 +{net:,.0f}（{net/initial*100:.1f}%）</p>
</div>

<div class="card">
<h2>组合价值走势（策略 vs 买入持有）</h2>
<canvas id="c" height="120"></canvas>
</div>

<div class="card">
<h2>完整周期明细（{r['cycles']} 周期）</h2>
<div class="tbl-scroll">
<table>
<thead><tr><th>入场日</th><th>到期日</th><th>入场价</th><th>到期股价</th><th>涨跌</th><th>Put行权价</th><th>Call行权价</th><th>权利金</th><th>买call成本</th><th>买call收益</th><th>结果</th><th>策略周期盈亏</th><th>B&H周期盈亏</th><th>组合价值</th><th>B&H价值</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
<p class="note">按时间倒序（最新周期在前）。涨跌=到期股价相对入场价变动；白色=正、灰色=负。买call成本/收益仅「触发买call对冲」的周期有值（—表示未触发）。B&H价值=同等资金满仓持有到期的价值。</p>
</div>

<div class="disc">免责声明：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。</div>
</div>
<script>__CHART_JS__</script>
<script>{chart_script}</script>
</body>
</html>"""

html = html.replace('__CHART_JS__', chart_js)

open('qqq_wheel_biweekly_report.html', 'w').write(html)
print('完整报告已生成: qqq_wheel_biweekly_report.html')
print(f"年化 {r['ann']:.2f}% 总收益 {r['total_ret']:.2f}% 回撤 {r['dd']:.2f}% 周期 {r['cycles']}")
