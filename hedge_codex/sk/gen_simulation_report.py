#!/usr/bin/env python3
"""Render the refreshed simulation in the original SKHY report's visual format."""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime
from html import escape
import json
import math
from pathlib import Path
import statistics
import sys
from zoneinfo import ZoneInfo


CSS = '''
:root{--bg:#0f1115;--card:#171a21;--border:#262b36;--text:#e6e8ec;--muted:#9aa3b2;--red:#ff5252;--green:#26c281;--accent:#4da3ff;--gold:#f5c344}
*{box-sizing:border-box;margin:0;padding:0}body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.7;padding:32px 20px}.wrap{max-width:1080px;margin:0 auto}h1{font-size:26px;margin-bottom:6px}h2{font-size:19px;margin:0 0 14px;padding-left:10px;border-left:4px solid var(--accent)}h3{font-size:15px;margin:16px 0 8px}.sub{color:var(--muted);font-size:13px;margin-bottom:24px}.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:18px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}.kpi{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px}.kpi .label{color:var(--muted);font-size:12px}.kpi .value{font-size:22px;font-weight:700;margin-top:4px}.kpi .sub{color:var(--muted);font-size:12px;margin:2px 0 0}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap}th{background:#1d212a;color:var(--muted);font-weight:600}th:first-child,td:first-child{text-align:left}tr:hover td{background:rgba(77,163,255,.025)}.c-red{color:var(--red);font-weight:600}.c-green{color:var(--green);font-weight:600}.c-gray{color:var(--muted)}.c-gold{color:var(--gold);font-weight:700}.callout{background:rgba(77,163,255,.08);border:1px solid rgba(77,163,255,.3);border-radius:10px;padding:14px 16px;margin:12px 0;font-size:14px}.callout-gold,.callout-warn{background:rgba(245,195,68,.06);border:1px solid rgba(245,195,68,.3);border-radius:10px;padding:14px 16px;margin:12px 0;font-size:14px}.note{color:var(--muted);font-size:12px;margin-top:8px}.tbl-scroll{overflow-x:auto}p{margin:8px 0}ul,ol{padding-left:22px}li{margin:6px 0}.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}svg{width:100%;height:auto;display:block}a{color:var(--accent)}nav{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0 22px;font-size:13px}summary{color:var(--accent);cursor:pointer;padding:10px 0}.tag{display:inline-block;border:1px solid var(--border);border-radius:5px;padding:2px 7px;font-size:11px;color:var(--gold)}.legend{font-size:12px;margin-top:8px;display:flex;gap:18px;flex-wrap:wrap}.small{font-size:13px}.detail{margin-top:18px}footer{font-size:12px;color:var(--muted);padding:10px 0 24px}
@media(max-width:650px){body{padding:20px 12px}.card{padding:15px}.cols{grid-template-columns:1fr}h1{font-size:23px}.kpis{grid-template-columns:1fr 1fr}.kpi .value{font-size:21px}}
@media print{body{background:white;color:#202631;padding:0}.card,.kpi{background:white}.callout,.callout-gold,.callout-warn,th{background:#f3f5f8}.tbl-scroll{overflow:visible}th,td{padding:4px;font-size:9px}nav{display:none}.card{break-inside:avoid}.c-gray,.note,.sub{color:#59616b}}
'''


def money(v, digits=0):
    return f'<span class="{"c-red" if v>=0 else "c-green"}">${v:+,.{digits}f}</span>'


def num(v):
    return '—' if v is None else f'{v:.2f}'


def table(headers, rows):
    return '<div class="tbl-scroll"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in headers)+\
      '</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(c)+'</td>' for c in row)+'</tr>' for row in rows)+\
      '</tbody></table></table></div>'.replace('</table></table>','</table>')


def kpi(label, value, sub=''):
    return f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="sub">{sub}</div></div>'


def section(title, body, ident=''):
    return f'<section class="card"'+(f' id="{ident}"' if ident else '')+f'><h2>{title}</h2>{body}</section>'


def ma(values, n):
    return [statistics.mean(values[i-n+1:i+1]) if i>=n-1 else None for i in range(len(values))]


def rsi(values, n=14):
    gains=[max(values[i]-values[i-1],0) for i in range(1,len(values))]
    losses=[max(values[i-1]-values[i],0) for i in range(1,len(values))]
    if len(gains)<n:return None
    g,l=statistics.mean(gains[:n]),statistics.mean(losses[:n])
    for i in range(n,len(gains)):
        g=(g*(n-1)+gains[i])/n;l=(l*(n-1)+losses[i])/n
    return 100-100/(1+g/l) if l else (100 if g else 50)


def ticks(n, step):
    values=list(range(0,n,step))
    if values and n-1-values[-1]<3:
        values.pop()
    return values+[n-1]


def candle(stock):
    W,H,L,R,T,B=1000,300,58,980,20,260
    n=len(stock);close=[r[4] for r in stock];avg=ma(close,20)
    low=math.floor(min(r[3] for r in stock)/10)*10;high=math.ceil(max(r[2] for r in stock)/10)*10
    if high<=low:high=low+10
    x=lambda i:L+(R-L)*(i+.5)/n
    y=lambda v:T+(high-v)/(high-low)*(B-T)
    s=[f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="SKHY日K线与MA20"><title>SKHY 日K线与MA20</title>']
    for i in range(6):
        v=low+(high-low)*i/5;yy=y(v)
        s.append(f'<line x1="{L}" y1="{yy:.2f}" x2="{R}" y2="{yy:.2f}" stroke="#262b36"/><text x="{L-8}" y="{yy+4:.2f}" fill="#9aa3b2" font-size="11" text-anchor="end">${v:.0f}</text>')
    width=min(12,(R-L)/n*.6)
    for i,(dt,o,h,l,c,v) in enumerate(stock):
        col='#ff5252' if c>=o else '#26c281';xx=x(i)
        s.append(f'<g><title>{dt} 开{o:.2f} 高{h:.2f} 低{l:.2f} 收{c:.2f}</title><line x1="{xx:.2f}" y1="{y(h):.2f}" x2="{xx:.2f}" y2="{y(l):.2f}" stroke="{col}"/><rect x="{xx-width/2:.2f}" y="{min(y(o),y(c)):.2f}" width="{width:.2f}" height="{max(abs(y(o)-y(c)),1.2):.2f}" fill="{col}"/></g>')
    pts=' '.join(f'{x(i):.2f},{y(v):.2f}' for i,v in enumerate(avg) if v is not None)
    s.append(f'<polyline points="{pts}" fill="none" stroke="#c792ea" stroke-width="2"/>')
    for i in ticks(n,max(1,n//7)):
        s.append(f'<text x="{x(i):.2f}" y="{B+24}" fill="#9aa3b2" font-size="11" text-anchor="middle">{stock[i][0][5:]}</text>')
    s.append('</svg>');return ''.join(s)


def equity_chart(results, boundary):
    W,H,L,R,T,B=1000,290,55,980,22,250
    vals=[[r['equity']/res['initial']*100 for r in res['curve']] for res in results]
    lo=math.floor(min(min(v) for v in vals)/5)*5-5;hi=math.ceil(max(max(v) for v in vals)/5)*5+5
    n=len(vals[0]);x=lambda i:L+i*(R-L)/(n-1);y=lambda v:B-(v-lo)/(hi-lo)*(B-T)
    s=[f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="基准、2张与1张Put的净值曲线"><title>初始资金=100的组合净值</title>']
    for j in range(6):
        v=lo+(hi-lo)*j/5
        s.append(f'<line x1="{L}" y1="{y(v):.2f}" x2="{R}" y2="{y(v):.2f}" stroke="#262b36"/><text x="{L-7}" y="{y(v)+4:.2f}" text-anchor="end" fill="#9aa3b2" font-size="11">{v:.0f}</text>')
    cut=next(i for i,r in enumerate(results[0]['curve']) if r['date']==boundary)
    s.append(f'<line x1="{x(cut):.2f}" x2="{x(cut):.2f}" y1="{T}" y2="{B}" stroke="#f5c344" stroke-dasharray="4 5"/><text x="{x(cut)+7:.2f}" y="{T+12}" fill="#f5c344" font-size="11">新增区间 →</text>')
    for j,color in enumerate(['#9aa3b2','#4da3ff','#f5c344']):
        pts=' '.join(f'{x(i):.2f},{y(v):.2f}' for i,v in enumerate(vals[j]))
        s.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
    for i in ticks(n,7):
        s.append(f'<text x="{x(i):.2f}" y="{B+23}" fill="#9aa3b2" font-size="11" text-anchor="middle">{results[0]["curve"][i]["date"][5:]}</text>')
    return ''.join(s)+'</svg>'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent)
    ap.add_argument('--output',type=Path)
    ap.add_argument('--factor-analysis',type=Path,help='Optional factor JSON; defaults to project factor_analysis.json')
    args=ap.parse_args();root=args.project_dir;out=args.output or root/'skhy_simulation_report.html'
    sys.path.insert(0,str(root))
    from backtest_audited import Config,run,indicators
    data=json.loads((root/'data/SKHY_put_history.json').read_text())
    a=json.loads((root/'results.json').read_text());rr=a['results'];bh,base,one=rr[:3]
    stock=data['stock'];closes={r[0]:r[4] for r in stock};series=list(closes.values())
    start,end=stock[0][0],stock[-1][0];boundary=a['boundary'];latest=stock[-1][4]
    avg,atr=indicators(stock);moves=sorted({r['config']['down'] for r in a['grid']})
    cfg=Config(**base['config']);cap_results={}
    for down in moves:
        for up in moves:cap_results[(down,up)]=run(data,replace(cfg,down=down,up=up,cap=11))
    threshold_grid=[r for r in a['grid'] if r['config']['puts']==2 and r['config']['target']==2]
    bestscore=max(r['full']['pnl_mdd'] for r in threshold_grid)
    ties=[r for r in threshold_grid if abs(r['full']['pnl_mdd']-bestscore)<1e-9]
    sections=[]
    board=candle(stock)+'<div class="legend"><span style="color:#c792ea">紫线：MA20</span><span>红涨绿跌 · 悬停 K 线查看 OHLC</span></div>'
    board+=table(['指标','最新值','说明'],[
        ['收盘价',f'${latest:.2f}',f'{end} 完整日线'],
        ['MA5 / MA10 / MA20',' / '.join(f'${ma(series,n)[-1]:.2f}' for n in (5,10,20)),'简单移动平均'],
        ['RSI14',f'{rsi(series):.2f}','Wilder 平滑；仅作行情描述'],
        ['ATR14 / 收盘价',f'{atr[end]:.2f}%','14 日简单平均真实波幅'],
        ['最新成交股数',f'{stock[-1][5]:,.0f}','股票成交量'],
        ['区间股价涨幅',f'{(latest/series[0]-1)*100:+.2f}%','不含保费与交易成本']])
    sections.append(section('行情与技术指标',board,'market'))
    sections.append(section('策略模型',f'''<p><strong>股票：{start} 收盘买入 100 股 @ ${series[0]:.2f}，持有至 {end} @ ${latest:.2f}。</strong></p>
<p>每 100 股配置 2 张 Put（原参数），对比 1 张 Put、虚值 Put、不同期限与保费轮空规则。初始保费备用金为股票成本的 50%，所有方案和基准均使用 <strong>${base['initial']:,.2f}</strong> 初始资金。</p>
<p>前一交易日收盘形成涨跌信号并选择合约，下一交易日按期权日线末价加费用模拟成交。ATM 依据<strong>前日</strong>股价选取；触发跌 15%／涨 8% 就滚动，未触发则持有至到期。目标 2 天选实际 DTE 1–7 天内最接近的挂牌合约。</p>
<p class="note">本次使用修正模型，区别于原报告“当日开盘触发＋全天 VWAP 成交”。每边滑点 2%（最低 $0.01/股），佣金每张 $0.65；股票成本 5 bps。逐日净值包含股票、现金和持仓 Put 的市值。</p>'''))
    kpis='<div class="kpis">'+kpi('B&H 收益',money(bh['pnl']),f'回撤 {bh["mdd_pct"]:.2f}%')+kpi('原参数 · 2 张 Put',money(base['pnl']),f'资金收益 {base["return_pct"]:.2f}%')+kpi('改为 1 张 Put',money(one['pnl']),f'资金收益 {one["return_pct"]:.2f}%')+kpi('2 张 Put 最大回撤',f'{base["mdd_pct"]:.2f}%',f'美元回撤 ${base["mdd"]:,.0f}')+kpi('1 张 Put 收益/回撤比',num(one['pnl_mdd']),f'2 张 {base["pnl_mdd"]:.2f} · B&H {bh["pnl_mdd"]:.2f}')+'</div>'
    sections.append(section('核心结论',f'''<div class="callout-gold"><strong>全期看，2 张 Put 改善了这段行情的回撤；新增上涨区间看，减为 1 张 Put 的保费拖累更小。</strong><br>
原参数组合全期收益 {money(base['pnl'])}，比基准多 {money(base['pnl']-bh['pnl'])}；回撤由 {bh['mdd_pct']:.2f}% 降为 {base['mdd_pct']:.2f}%。1 张 Put 全期收益 {money(one['pnl'])}，收益/回撤比 {one['pnl_mdd']:.2f}。</div>
{kpis}<p>但不能据此宣布实盘最优。2 张 Put 在新增区间只取得 {money(base['holdout']['pnl'],2)}，而持股基准为 {money(bh['holdout']['pnl'],2)}；1 张 Put 为 {money(one['holdout']['pnl'],2)}。</p>
<p class="note">上述回撤均含同额备用金；不能直接与旧报告不含备用金的 34.6% 比较。原参数存在 {base['async_marks']} 个不同步估值日、{base['execution_anomalies']} 次异常价格成交，均保留为条件模拟，详见报告末尾。</p>''','conclusion'))
    sections.append(section('组合净值曲线',equity_chart([bh,base,one],boundary)+'''<div class="legend"><span style="color:#9aa3b2">灰：持股基准</span><span style="color:#4da3ff">蓝：2 张 Put</span><span style="color:#f5c344">金：1 张 Put</span></div><p class="note">初始资金归一为 100，期末持仓按市值计入。虚线为旧报告截止日，之后为新增区间。</p>'''))
    def matrix(field, cap=False):
        rows=[]
        for down in moves:
            cells=[f'跌 {down:g}%']
            for up in moves:
                r=cap_results[(down,up)] if cap else next(g['full'] for g in threshold_grid if g['config']['down']==down and g['config']['up']==up)
                value=money(r[field]) if field=='pnl' else num(r[field])
                cells.append(value+(' †' if not r['eligible'] else ''))
            rows.append(cells)
        return table(['下跌 / 上涨']+[f'涨 {up:g}%' for up in moves],rows)
    sections.append(section('涨熔断 × 跌熔断 不对称扫描（总收益）',f'<p class="small">固定 2 张 Put、目标 2 天；行 = 跌幅阈值，列 = 涨幅阈值。金额为全期净盈亏。</p>'+matrix('pnl')+'<p class="note">† 该参数存在缺失估值或价格不同步，不能进入严格质量筛选排名。相同收益可能代表本段行情的交易路径完全相同。</p>','matrix'))
    sections.append(section('收益/回撤比矩阵',matrix('pnl_mdd')+f'<p class="note">比值 = 全期净盈亏 / 美元最大回撤；固定 2 张 Put 的最高值为 {bestscore:.2f}，共有 {len(ties)} 组参数同分。不能将任意一个并列阈值解释为独有最优点。</p>'))
    capbest=max(cap_results.values(),key=lambda r:r['pnl'])
    sections.append(section('轮空策略不对称扫描（保费 >11% 跳过该轮）',matrix('pnl',True)+f'''<p class="note">基于前日可见价格和固定美元限额决定是否买入。跳过 Put 后，100 股继续持有，至原计划到期日再评估；没有事后删去股票利润。</p><p>在本次固定 2 天、2 张 Put 的轮空扫描中，样本内最高净收益为 {money(capbest['pnl'])}，参数：{escape(capbest['label'])}。这仍属于样本内比较。</p>'''))
    details=[]
    for t in reversed(base['trades']):
        sp=(closes[t['exit_date']]-t['entry_spot'])*100
        details.append([t['entry_date'],t['exit_date'],t['reason'],f'${t["strike"]:g}',
             f'${t["entry_spot"]:.2f}',f'${closes[t["exit_date"]]:.2f}',money(sp),
             f'${t["cost"]:,.2f}',f'${t["income"]:,.2f}',money(t['pnl'],2),money(sp+t['pnl'],2)])
    round_stock=sum((closes[t['exit_date']]-t['entry_spot'])*100 for t in base['trades'])
    residual=base['stock_pnl']-round_stock
    sections.append(section('逐轮明细：2 张 Put · 跌 15% / 涨 8%',table(['入场日','退出/估值日','方式','行权价','入场股价','退出股价','轮内股票盈亏','Put支出','收入/市值','Put净损益','轮内合计'],details)+f'''<div class="callout">全期策略收益 {money(base['pnl'],2)} = 股票净损益 {money(base['stock_pnl'],2)} ＋ Put 净损益 {money(base['put_pnl'],2)}。<br>逐轮“轮内合计”之和与全期收益相差 {money(residual,2)}，来自轮次以外的股票持有区间及股票首日交易费用。</div><p class="note">股票全程持有，逐轮股票盈亏仅归属该轮入场至退出期间。最后一轮若标为“期末持有／市值”，收入一栏是持仓市值，并非实际卖出所得。所有轮次倒序排列。</p>''','trades'))
    skip=rr[5]
    sections.append(section('轮空规则验证',table(['同一跌15% / 涨8%参数','不轮空','11% 保费轮空'],[
        ['全期收益',money(base['pnl'],2),money(skip['pnl'],2)],
        ['最大回撤',f'{base["mdd_pct"]:.2f}%',f'{skip["mdd_pct"]:.2f}%'],
        ['实际轮数',len(base['trades']),len(skip['trades'])],
        ['收盘持有Put覆盖率',f'{base["protected_pct"]:.1f}%',f'{skip["protected_pct"]:.1f}%'],
        ['新增区间盈亏',money(base['holdout']['pnl'],2),money(skip['holdout']['pnl'],2)]])+f'<div class="callout-warn">本次真实轮空重跑使全期收益变化 {money(skip["pnl"]-base["pnl"],2)}。原报告“11% 轮空普遍提升收益”的结论，在修正模拟中不成立。</div>'))
    closed=[t for t in base['trades'] if not t['mark_only']];losers=[t for t in closed if t['pnl']<0];biggest=max(closed,key=lambda t:t['pnl'])
    sections.append(section('亏损轮与盈利集中度',table(['观察项','结果'],[
        ['已结束轮数 / Put亏损轮数',f'{len(closed)} / {len(losers)}'],
        ['亏损轮Put净损益合计',money(sum(t['pnl'] for t in losers),2)],
        ['最大单轮Put盈利',f'{biggest["entry_date"]} → {biggest["exit_date"]}：{money(biggest["pnl"],2)}'],
        ['其余轮次Put净损益（含期末估值）',money(base['put_pnl']-biggest['pnl'],2)],
        ['累计新仓保费支出（含开仓费用）',f'${base["premium"]:,.2f}']])+'''<p>收益高度依赖少数大幅下跌的保护赔付。涨跌幅不足、持续上涨或频繁滚动时，保费支出容易占主导。股票上涨可能使组合赚钱，但不代表 Put 本身赚钱。</p><p class="note">上述“Put亏损轮”只比较期权支出与收入，不等同于股票＋期权整个组合该轮亏损。</p>'''))
    compare=[]
    for r in rr:
        compare.append([r['name'],money(r['pnl']),f'{r["return_pct"]:+.2f}%',f'{r["mdd_pct"]:.2f}%',num(r['pnl_mdd']),money(r['holdout']['pnl']),str(len(r['trades'])),('有异常 †' if not r['eligible'] else '未见已检异常')])
    sections.append(section('策略优化方案横向对比',table(['方案','全期收益','资金收益率','最大回撤','收益/回撤','新增期盈亏','轮数','数据检查'],compare)+'''<div class="callout"><strong>下一阶段优先验证：1 张 ATM Put、1 张轻度虚值 Put。</strong><br>重点比较较低保费与较弱保护之间的取舍，而不是继续细分阈值。MA20、ATR 和成本过滤未显示可直接推广的稳定优势。</div><p class="note">虚值比例按前日股票价格确定，并允许挂牌行权价偏离目标最多 3%。期限范围分别为 1–7、5–10、11–17、18–24 天；缺合约或资金不足则不买入。</p>''','optimization'))
    sections.append(section(f'新增区间验证（2026-08-25 ~ {end}）',table(['方案','期初组合净值','新增期盈亏','新增期收益率','新增期最大回撤'],[
        [r['name'],f'${r["holdout"]["start_equity"]:,.2f}',money(r['holdout']['pnl'],2),f'{r["holdout"]["return_pct"]:+.2f}%',f'{r["holdout"]["mdd_pct"]:.2f}%'] for r in rr[:5]])+f'''<p>这一区间继承旧报告截止日 {boundary} 的实际持仓和现金，不重新建仓。各方案期初净值不同，收益率分母也随之不同，因此同时列示美元盈亏。</p><div class="callout-warn">全组合开发期扫描 392 组参数；排除估值缺失及已发现的价格不同步后，有 {a['clean_count']} 组满足至少 3 轮的条件。按开发期收益/回撤比与基准比较，筛选结果为：<strong>{escape(a['selected'])}</strong>。</div><p class="note">本次属于事后重建的时间切分，新增区间只有 {sum(r[0]>boundary for r in stock)} 个交易日。不能作为事前登记的真实样本外实验或稳定年化收益证据。</p>''','validation'))
    latestrows=[]
    for exp in sorted({data['contracts'][t]['expiration_date'] for t in data['listed'][end]})[:3]:
        ts=[t for t in data['listed'][end] if data['contracts'][t]['expiration_date']==exp and data['history'][t].get(end,{}).get('v',0)>0]
        if not ts:continue
        t=min(ts,key=lambda t:abs(data['contracts'][t]['strike_price']-latest));c=data['contracts'][t];q=data['history'][t][end]
        latestrows.append([exp,f'${c["strike_price"]:g}',f'${q["c"]:.2f}',f'${q["vw"]:.4f}',f'{q["v"]:,.0f}',f'${q["c"]*100:,.2f}',f'${q["c"]*200:,.2f}',f'{q["c"]*2/latest*100:.2f}%'])
    sections.append(section(f'最新期权快照（{end}）',f'<p>股票收盘 <strong class="c-gold">${latest:.2f}</strong>。各到期日选择当日最接近股票收盘价的有成交 Put：</p>'+table(['到期日','行权价','日线末价','全天VWAP','成交量','1张裸保费','2张裸保费','2张占股票市值'],latestrows)+'''<p class="note">这是历史完整日线快照，不是实时买卖盘口，也不是立即下单建议。裸保费未含费用；开仓阈值还取决于实际建仓价格。同期 DRAM 未用本模型重算，本报告不沿用旧版跨标的收益对比。</p>''','snapshot'))
    sections.append(section('交易摩擦敏感性',table(['Put张数','每边比例滑点','全期收益','最大回撤','新增区间收益'],[
        [r['puts'],f'{r["slip"]:.0%}',money(r['pnl'],2),f'{r["mdd_pct"]:.2f}%',money(r['holdout']['pnl'],2)] for r in a['sensitivity']])+'''<p class="note">0% 仍包含每股最低 $0.01 价差和佣金，不是零摩擦；改变滑点也可能因现金预算约束改变后续成交路径。</p>'''))
    sections.append(section('数据与结论说明',f'''<ul class="small"><li><strong>数据已刷新：</strong>{start} 至 {end}，{len(stock)} 个完整股票交易日，{data['manifest']['n_contracts']} 个历史实际挂牌 Put。拉取时间：{escape(data['manifest']['fetched_at_utc'])}。</li>
<li><strong>同步价格限制：</strong>期权日线末价不一定与股票收盘同步。原参数出现 {base['async_marks']} 个持仓估值日及 {base['execution_anomalies']} 次模拟成交的期权末价低于股票收盘对应内在价值超过 $0.05；未把它们修成理论价格。</li>
<li><strong>报价权限：</strong>本次历史 Quotes 查询返回 HTTP 403，无法用同步 Bid/Ask 验证成交。所有收益均为条件模拟，“未见已检异常”也不证明价格同步。</li>
<li><strong>缺失值处理：</strong>缺卖出价则延迟退出；缺市值则显式估计并取消严格排名资格。到期以等价现金流模拟行权及买回股票以维持 100 股，计行权费和股票摩擦；未模拟提前行权、借券和结算等待。</li>
<li><strong>资金口径：</strong>无杠杆，保费受现金预算约束；不计现金利息、股息和税费。收益为价格回报，期末持仓按市值而非实际清仓计入。</li>
<li><strong>回撤定义：</strong>逐日净值 = 股票市值 + 现金 + Put 市值；百分比回撤按每一天当时的历史峰值计算。美元最大回撤与百分比最大回撤可能发生在不同日期。</li>
<li><strong>复现与明细：</strong><a href="results.json">全部模拟结果 JSON</a> · <a href="skhy_final_report.html">方法审计报告</a> · <a href="README.md">复现说明</a>。本报告的 11% 轮空矩阵另存于 <a href="simulation_report_extra.json">补充模拟结果</a>。</li></ul>
<p class="note">资料口径：<a href="https://massive.com/docs/rest/options/aggregates/custom-bars">Massive 期权日线与 VWAP 定义</a>；<a href="https://prd-web.optionseducation.org/strategies/all-strategies/protective-put-married-put">OIC 保护性 Put 说明</a>。仅用于策略研究。</p>'''))
    generated=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
    html=f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY 对冲策略模拟报告 · {end}</title><style>{CSS}</style></head><body><div class="wrap"><h1>SKHY 对冲策略模拟报告 <span style="color:var(--muted);font-size:15px">（涨 / 跌阈值不对称扫描 · 更新版）</span></h1><p class="sub">参考原报告结构与样式 · {start} ~ {end}（{len(stock)} 交易日） · 生成于 {generated} 北京时间<br>修正日线模拟：前日信号、次日期权末价估算 · 本文金额均为美元</p><nav><a href="#market">行情</a><a href="#conclusion">核心结论</a><a href="#matrix">参数矩阵</a><a href="#trades">逐轮明细</a><a href="#optimization">优化对比</a><a href="#validation">新增区间</a><a href="#snapshot">期权快照</a></nav>{''.join(sections)}<footer>SKHY Simulation Report · 原版深色卡片 / 红涨绿跌 / 参数矩阵与逐轮明细 · 无外部脚本依赖</footer></div></body></html>'''
    factors=args.factor_analysis or root/'factor_analysis.json'
    if factors.exists():
        from factor_report import apply_factors
        html=apply_factors(html,json.loads(factors.read_text()),a,data)
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(html)
    extra={'source_results':'results.json','source_manifest':data['manifest'],
           'cap_scan':[dict(down=dn,up=up,**r) for (dn,up),r in cap_results.items()]}
    (out.parent/'simulation_report_extra.json').write_text(json.dumps(extra,ensure_ascii=False,indent=2,allow_nan=False))
    print('Generated',out,'sections',len(sections),'rounds',len(base['trades']),'cap simulations',len(cap_results))


if __name__=='__main__':
    main()
