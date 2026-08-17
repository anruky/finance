#!/usr/bin/env python3
"""Generate the complete QQQ biweekly (2-week) optimal strategy report."""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_local_backtest as m

r = m.run('QQQ', m.make_targets(50, 6, 15, 15), options_file='QQQ_options_2wk.json')

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
prev_bh = S0
for y in ['2024', '2025', '2026']:
    endv = yr_end_val.get(y)
    if endv is None:
        continue
    sret = (endv - prev_val) / prev_val * 100
    # 策略年内回撤（周期价值）
    strat_vals = [c['value'] for c in r['cycle_list'] if c['entry'][:4] == y]
    sdd = yearly_dd(strat_vals, prev_val)
    # B&H 年内回撤（日线）
    bh_vals = [c for d, c in zip(dates, closes) if d[:4] == y]
    bdd = yearly_dd(bh_vals, prev_bh)
    bh_c = yr_close.get(y)
    bret = (bh_c - prev_bh) / prev_bh * 100 if bh_c is not None else 0.0
    if bh_c is not None:
        prev_bh = bh_c
    st = dict(yr_states.get(y, {}))
    st_str = (f"A{st.get('A',0)} B{st.get('B',0)} C{st.get('C',0)} "
              f"D{st.get('D',0)} E{st.get('E',0)}")
    color = '#27ae60' if sret >= bret else '#e74c3c'
    yearly_rows += (f"<tr><td><b>{y}</b></td><td>{yr_cycles.get(y, 0)}</td>"
                    f"<td>${yr_prem.get(y, 0):,.0f}</td>"
                    f"<td style='color:{color};font-weight:600'>{sret:+.1f}%</td>"
                    f"<td>{sdd:.2f}%</td>"
                    f"<td>{bret:+.1f}%</td>"
                    f"<td>{bdd:.2f}%</td><td>{st_str}</td></tr>")
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

state_color = {'A': '#666', 'B': '#27ae60', 'C': '#e74c3c', 'D': '#f39c12', 'E': '#e67e22'}
rows = ''
for c in r['cycle_list']:
    sc = state_color.get(c['state'], '#666')
    chg = c['exp_px'] - c['spot']
    chg_str = f"{chg:+.0f}" if abs(chg) >= 0.5 else "0"
    try:
        bh_val = round(initial * closes[dates.index(c['expiry'])] / S0_bt, 0)
    except Exception:
        bh_val = round(200 * c['exp_px'], 0)
    rows += (f"<tr><td>{c['entry']}</td><td>{c['expiry']}</td><td>{c['spot']:.0f}</td>"
             f"<td>{c['exp_px']:.0f}</td><td style='color:{'#27ae60' if chg >= 0 else '#e74c3c'}'>{chg_str}</td>"
             f"<td>{c['put']}</td><td>{c['call']}</td><td>${c['prem']:,.0f}</td>"
             f"<td style='color:{sc};font-weight:600'>{c['state']}</td>"
             f"<td>${c['pnl']:+,.0f}</td><td>${c['value']:,.0f}</td>"
             f"<td>${bh_val:,.0f}</td></tr>")

final_val = r['final']
net = final_val - initial
total_income = r['premium'] + r['gains']
total_cost = r['losses'] + r['interest']

chart_js = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chart.umd.min.js')).read()

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>QQQ Wheel 2周周期最优策略报告</title>
<script>__CHART_JS__</script>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;background:#f5f6fa;margin:0;padding:24px;color:#1a1a2e}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}.sub{{color:#666;font-size:13px;margin-bottom:20px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.card .k{{font-size:12px;color:#888;margin-bottom:6px}}.card .v{{font-size:20px;font-weight:700}}
.v.green{{color:#27ae60}}.v.red{{color:#e74c3c}}.v.blue{{color:#2d6cdf}}.v.dark{{color:#1a1a2e}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06);margin-bottom:24px;font-size:13px}}
th,td{{padding:9px 10px;text-align:right;border-bottom:1px solid #eee}}
th{{background:#fafbfc;color:#666;font-weight:600}}td:first-child,th:first-child{{text-align:left}}
.chart-box{{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.06);margin-bottom:24px}}
h2{{font-size:16px;margin:16px 0 10px}}.cfg{{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.06);margin-bottom:16px}}
.cfg table{{margin:0;box-shadow:none}}.disc{{font-size:11px;color:#999;line-height:1.6;border-top:1px solid #eee;padding-top:12px;margin-top:20px}}
.scroll{{max-height:560px;overflow:auto}}
</style></head><body><div class="wrap">
<h1>QQQ Wheel 策略 · 2周周期最优配置</h1>
<div class="sub">区间 2024-08-19 ~ 2026-08-14（499交易日）· 真实历史期权数据（VWAP）· 周期14天（周五到期）</div>
<div class="cards">
  <div class="card"><div class="k">策略年化收益</div><div class="v green">22.50%</div></div>
  <div class="card"><div class="k">策略总收益</div><div class="v green">+49.66%</div></div>
  <div class="card"><div class="k">最大回撤</div><div class="v dark">8.37%</div></div>
  <div class="card"><div class="k">买入持有年化</div><div class="v blue">23.43%</div></div>
  <div class="card"><div class="k">买入持有回撤</div><div class="v red">{bh_dd_pct}%</div></div>
  <div class="card"><div class="k">周期数</div><div class="v dark">{r['cycles']}</div></div>
  <div class="card"><div class="k">权利金收入</div><div class="v dark">${r['premium']:,.0f}</div></div>
</div>

<div class="cfg"><h2>按年度汇总</h2><table><thead><tr><th>年份</th><th>周期数</th><th>权利金</th><th>策略收益</th><th>策略回撤</th><th>买入持有</th><th>B&H回撤</th><th>状态分布</th></tr></thead><tbody>
{yearly_rows}
</tbody></table>
<div style="font-size:12px;color:#888;margin-top:8px">绿色=当年跑赢买入持有，红色=跑输。2024 为 8月19日起的区间，2026 为截至 8月14日的区间。</div></div>

<div class="cfg"><h2>策略参数</h2><table><thead><tr><th>状态</th><th>含义</th><th>卖 Put 年化目标</th><th>卖 Call 年化目标</th></tr></thead><tbody>
<tr><td>A</td><td>低波动（均到期作废）</td><td>50%</td><td>6%</td></tr>
<tr><td>B</td><td>大涨（call被行权）</td><td>50%</td><td>6%</td></tr>
<tr><td>C</td><td>剧烈震荡后下行</td><td>15%</td><td>15%</td></tr>
<tr><td>D</td><td>涨后回调</td><td>50%</td><td>6%</td></tr>
<tr><td>E</td><td>大跌（put被行权）</td><td>15%</td><td>15%</td></tr>
</tbody></table>
<div style="font-size:12px;color:#888;margin-top:8px">资金结构：2手资金 = 1手持股 + 1手现金 · 融资年化11% · 到期日=每两周后的周五</div></div>

<div class="cfg"><h2>收入与成本</h2><table><thead><tr><th>收入</th><th>金额</th><th>成本</th><th>金额</th></tr></thead><tbody>
<tr><td>权利金收入</td><td>${r['premium']:,.0f}</td><td>股票亏损</td><td>${r['losses']:,.0f}</td></tr>
<tr><td>股票收益</td><td>${r['gains']:,.0f}</td><td>融资成本</td><td>${r['interest']:,.0f}</td></tr>
<tr><td><b>合计收入</b></td><td><b>${total_income:,.0f}</b></td><td><b>合计成本</b></td><td><b>${total_cost:,.0f}</b></td></tr>
</tbody></table>
<div style="font-size:12px;color:#888;margin-top:8px">初始资金 ${initial:,.0f} → 终值 ${final_val:,.0f} · 净盈亏 +{net:,.0f}（{net/initial*100:.1f}%）</div></div>

<div class="chart-box"><h2>组合价值走势（策略 vs 买入持有）</h2><canvas id="c" height="120"></canvas></div>

<h2>完整周期明细（{r['cycles']} 周期）</h2>
<div class="scroll"><table><thead><tr><th>入场日</th><th>到期日</th><th>入场价</th><th>到期股价</th><th>涨跌</th><th>Put行权价</th><th>Call行权价</th><th>权利金</th><th>结果</th><th>周期盈亏</th><th>组合价值</th><th>B&H价值</th></tr></thead><tbody>
{rows}
</tbody></table></div>

<script>
new Chart(document.getElementById('c'), {{
  type:'line', data:{{labels:{json.dumps(labels)},
  datasets:[{{label:'Wheel策略', data:{json.dumps(sv)}, borderColor:'#2d6cdf', backgroundColor:'rgba(45,108,223,.12)', fill:true, tension:.3, pointRadius:0, borderWidth:2}},
  {{label:'买入持有', data:{json.dumps(bv)}, borderColor:'#e67e22', borderDash:[6,4], tension:.3, pointRadius:0, borderWidth:2, fill:false}}]}},
  options:{{responsive:true, interaction:{{mode:'index',intersect:false}},
  plugins:{{legend:{{position:'top',labels:{{boxWidth:12,font:{{size:11}}}}}}}},
  scales:{{x:{{ticks:{{maxTicksLimit:12,font:{{size:10}}}}}},y:{{ticks:{{font:{{size:10}},callback:v=>'$'+Math.round(v/1000)+'k'}}}}}}}}
}});
</script>
<div class="disc">免责声明：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。</div>
</div></body></html>"""

html = html.replace('__CHART_JS__', chart_js)

open('qqq_wheel_biweekly_report.html', 'w').write(html)
print('完整报告已生成: qqq_wheel_biweekly_report.html')
print(f"年化 {r['ann']:.2f}% 总收益 {r['total_ret']:.2f}% 回撤 {r['dd']:.2f}% 周期 {r['cycles']}")
