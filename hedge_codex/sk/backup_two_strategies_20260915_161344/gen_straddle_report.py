#!/usr/bin/env python3
"""Generate an independent long-straddle report alongside the original hedge report."""
import argparse
from dataclasses import replace
from datetime import datetime
import hashlib,json,math,re
from pathlib import Path
from zoneinfo import ZoneInfo
from backtest_audited import Config,run,window_metrics
from backtest_straddle import run_straddle,paired_rounds,cash_interest
from refresh_data import atomic_json
from capital_report import scenarios,render


def money(v):return f'<span class="{"c-red"if v>=0 else "c-green"}">${v:+,.2f}</span>'
def ratio(v):return '—'if v is None else f'{v:.2f}'
def table(head,rows):return '<div class="tbl-scroll"><table><thead><tr>'+''.join(f'<th>{v}</th>'for v in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{v}</td>'for v in row)+'</tr>'for row in rows)+'</tbody></table></div>'
def section(title,body,ident=''):return f'<section class="card" id="{ident}"><h2>{title}</h2>{body}</section>'
def slim(r):return {k:v for k,v in r.items()if k not in ('trades','curve')}


def chart(rr):
    W,H,L,R,T,B=1000,300,55,980,20,258
    vals=[[z['equity']/r['initial']*100 for z in r['curve']]for r in rr]
    lo=math.floor(min(min(x)for x in vals)/5)*5-5;hi=math.ceil(max(max(x)for x in vals)/5)*5+5
    n=len(vals[0]);x=lambda i:L+i*(R-L)/(n-1);y=lambda v:B-(v-lo)/(hi-lo)*(B-T)
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="跨式、原策略与持股基准净值"><title>同初始资金组合净值</title>']
    for j in range(6):
        v=lo+j*(hi-lo)/5;s.append(f'<line x1="{L}" x2="{R}" y1="{y(v):.2f}" y2="{y(v):.2f}" stroke="#262b36"/><text x="{L-7}" y="{y(v)+4:.2f}" fill="#9aa3b2" font-size="11" text-anchor="end">{v:.0f}</text>')
    for vs,color in zip(vals,['#f5c344','#4da3ff','#9aa3b2']):
        pts=' '.join(f'{x(i):.2f},{y(v):.2f}'for i,v in enumerate(vs));s.append(f'<polyline points="{pts}" stroke="{color}" stroke-width="2" fill="none"/>')
    for i in list(range(0,n-3,7))+[n-1]:s.append(f'<text x="{x(i):.2f}" y="{B+23}" fill="#9aa3b2" font-size="11" text-anchor="middle">{rr[0]["curve"][i]["date"][5:]}</text>')
    return ''.join(s)+'</svg><p class="note">金：1 Call＋1 Put＋现金；蓝：100股＋2 Put；灰：同资金持股基准。初始净值=100，现金主情景不计息。</p>'


def main():
    ap=argparse.ArgumentParser(description=__doc__);root=Path(__file__).resolve().parent
    ap.add_argument('--project-dir',type=Path,default=root);ap.add_argument('--calls',type=Path)
    ap.add_argument('--output',type=Path);args=ap.parse_args();project=args.project_dir
    data=json.loads((project/'data/SKHY_put_history.json').read_text());calls=json.loads((args.calls or project/'data/SKHY_call_history.json').read_text())
    assert calls['manifest']['put_dataset_sha256']==hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),'Call/Put bundles differ; refresh data'
    cfg=Config();original=run(data,cfg);original['name']='100股＋2 Put'
    bh=run(data,replace(cfg,puts=0));bh['name']='持股基准＋同额备用金'
    st=run_straddle(data,calls,cfg)
    cap=scenarios(data,calls,cfg,st)
    for r in (st,original,bh):r['holdout']=window_metrics(r,'2026-08-24')
    paired=paired_rounds(data,calls,original,cfg)
    matched=[(t['entry_date'],t['exit_date'],t['put'])for t in st['trades']]==[(t['entry_date'],t['exit_date'],t['ticker'])for t in original['trades']]
    available=[r for r in paired if r['available']]
    paired_delta=sum(r['delta']for r in available)
    outside=original['pnl']-sum(r['original_round']for r in paired)
    if matched and len(available)==len(paired):assert abs(st['pnl']-original['pnl']-(paired_delta-outside))<1e-6
    grid=[]
    for dn in [8,10,12,15,18,20,25]:
        for up in [8,10,12,15,18,20,25]:
            r=run_straddle(data,calls,replace(cfg,down=dn,up=up));grid.append(dict(down=dn,up=up,**slim(r)))
    periods=[run_straddle(data,calls,replace(cfg,target=t))for t in (2,7,14,21)]
    sensitivities=[run_straddle(data,calls,replace(cfg,slip=s))for s in (0,.02,.05)]
    interest=[dict(strategy=r['name'],**cash_interest(r,rate))for rate in (0,.04)for r in (st,original,bh)]
    result=dict(capital_scenarios=cap,manifest=calls['manifest'],base=st,original=original,benchmark=bh,paired=paired,
        schedules_match=matched,paired_delta=paired_delta,stock_outside_rounds=outside,
        grid=grid,periods=periods,slippage=sensitivities,interest=interest)
    out=args.output or project/'skhy_straddle_report.html';out.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(out.parent/'skhy_straddle_results.json',result)
    reference=(project/'skhy_simulation_report.html').read_text();css=re.search(r'<style>(.*?)</style>',reference,re.S).group(1)
    start,end=data['stock'][0][0],data['stock'][-1][0]
    cards='<div class="kpis">'+''.join(f'<div class="kpi"><div class="label">{title}</div><div class="value">{v}</div><div class="sub">{sub}</div></div>'for title,v,sub in [
        ('跨式全期盈亏',money(st['pnl']),f'资金收益 {st["return_pct"]:.2f}%'),
        ('跨式最大回撤',f'{st["mdd_pct"]:.2f}%',f'美元回撤 ${st["mdd"]:,.2f}'),
        ('原策略全期盈亏',money(original['pnl']),f'回撤 {original["mdd_pct"]:.2f}%'),
        ('同轮次跨式收益差',money(paired_delta),f'{len(available)}/{len(paired)}轮可配对')])+'</div>'
    parts=[render(cap,st,table,section,money)]
    parts.append(section('旧基准：只买1组并保留现金',f'''<div class="callout-gold"><strong>1张Call＋1张Put的基准模拟全期收益为 {money(st['pnl'])}，资金收益率 {st['return_pct']:.2f}%。</strong><br>比原100股＋2张Put全期少 {money(original['pnl']-st['pnl'])}，但不能把这个差额全部理解为跨式更差：原策略在首轮期权开仓前已获得股票收益。</div>{cards}
<p>在相同合约、相同入场/退出日的配对轮次内，跨式合计比原组合多 {money(paired_delta)}。这部分观察差额仍包含成交摩擦、资金定价和非同步末价影响，尚不能认定为实盘可获得的结构优势。</p>''','conclusion'))
    parts.append(section('回测模型：股票退出，保留现金',f'''<ul><li><strong>仓位：</strong>每轮1张Call＋1张Put，同一行权价、同一到期日、每张乘数100；不持有股票，不用释放本金增加张数。</li>
<li><strong>资金：</strong>与原报告同初始资金 ${st['initial']:,.2f}，余款留现金。主情景现金利率0%；另列假设4%年利率的固定路径敏感性，不把4%当作实际可获得利率。</li>
<li><strong>信号：</strong>前日股票收盘相对该轮入场股价下跌15%或上涨8%，次日滚动两条腿；否则持有至到期。目标2天，选择实际剩余1–7日内最接近的期限。</li>
<li><strong>选档：</strong>沿用原Put选择，Call必须同档、同到期，且前日实际挂牌、成交量至少10张；两条腿当天均有价格才模拟组合成交。</li>
<li><strong>价格与费用：</strong>日线末价模拟，期权每边滑点2%（最低$0.01/股）、每张佣金$0.65。平仓缺任一腿价格时两腿一起延迟，不伪造单腿成交。</li>
<li><strong>到期：</strong>按内在价值作现金等价结算；价内腿计$1行权费和100股价值的5bps股票平仓摩擦，以保持零股票。期末未到期持仓只估值，未假设售出。</li></ul>
<p class="note">严格沿用旧报告 {start}～{end} 的44个交易日做可比试验，没有把新Call与更晚股票日期混用。Call补拉时间为 {calls['manifest']['fetched_at_utc']}。</p>''','model'))
    parts.append(section('与原策略和基准比较',table(['策略','全期盈亏','资金收益率','最大回撤','收益/回撤','新增期盈亏','新增期收益率'],[[r['name'],money(r['pnl']),f'{r["return_pct"]:.2f}%',f'{r["mdd_pct"]:.2f}%',ratio(r['pnl_mdd']),money(r['holdout']['pnl']),f'{r["holdout"]["return_pct"]:.2f}%']for r in (st,original,bh)])+'<p class="note">新增区间为08-25～09-11，继承08-24持仓与现金。资金收益率按各区间期初实际净值计算，故同时列示美元盈亏；此表仅保留旧现金账户比较，期权实际本金口径见报告顶部。</p>'+chart([st,original,bh]),'comparison'))
    parts.append(section('为什么全期少赚，但同轮次却略高',table(['项目','金额'],[
        ['跨式：期权轮次净损益合计',money(sum(r['straddle_round']for r in available))],
        ['原组合：相同轮次股票＋双Put净损益',money(sum(r['original_round']for r in available))],
        ['同轮次跨式减原组合',money(paired_delta)],
        ['原组合轮次外股票净损益（含首次股票费用）',money(outside)],
        ['全期跨式减原组合',money(st['pnl']-original['pnl'])]])+f'''<p>独立回测交易路径与原组合<strong>{'完全一致'if matched else '不完全一致'}</strong>。首轮期权于 {st['trades'][0]['entry_date']} 开仓；在此之前，原方案已持有100股，跨式方案持现金。{('全期差额 = 同轮次差额 − 原组合轮次外股票损益。'if matched else '路径不同，配对比较仅作单独诊断，不能直接解释全部差额。')}</p>
<p class="note">配对表固定原交易日程，不是另一个择时优化结果；它隔离了初始裸股票持有区间，有助于比较两种波动结构本身。</p>''','decomposition'))
    parts.append(section('逐轮明细：1 Call＋1 Put',table(['信号日','入场 → 退出','行权价','到期日','方式','Call支出','Put支出','Call净损益','Put净损益','组合净损益'],[
        [t['signal_date'],t['entry_date']+' → '+t['exit_date'],f'${t["strike"]:g}',t['expiry'],t['reason'],f'${t["call_cost"]:,.2f}',f'${t["put_cost"]:,.2f}',money(t['call_pnl']),money(t['put_pnl']),money(t['pnl'])]for t in reversed(st['trades'])])+f'''<div class="callout">Call累计净损益 {money(st['call_pnl'])} ＋ Put累计净损益 {money(st['put_pnl'])} = 总盈亏 {money(st['pnl'])}。账本残差 ${st['reconciliation']:.8f}。</div><p class="note">支出含开仓摩擦及佣金，净损益另计退出摩擦或到期费用；期末持有行按市值计入。最低现金为 ${st['cash_min']:,.2f}，累计滚动支出为 ${st['premium']:,.2f}，累计支出不等于同时占用本金。</p>''','trades'))
    parts.append(section('同轮次配对：省保费是否等于多盈利',table(['入场 → 退出','行权价','双Put支出','跨式支出','原组合轮内净损益','跨式轮内净损益','跨式减原组合','入场平价偏差'],[
        [r['entry']+' → '+r['exit'],f'${r["strike"]:g}',f'${r["original_cost"]:,.2f}',f'${r["straddle_cost"]:,.2f}',money(r['original_round']),money(r['straddle_round']),money(r['delta']),money(r['entry_gap'])]if r['available']else[r['entry']+' → '+r['exit'],r['strike'],'—','缺行情','—','—','—','—']for r in reversed(paired)])+'''<p class="note">入场平价偏差 = 100×(股票末价＋Put末价−Call末价−行权价)，暂不扣利息、分红和美式提前行权影响。到期两结构支付差为100K；轮内毛损益差来自平价偏差变化，费用另计。日线末价不同时，偏差也会被放大，不能据此认定存在可成交套利。Call便宜可能仅因虚值，不能只比较两种保费支出。</p>''','paired'))
    matrix=[]
    moves=[8,10,12,15,18,20,25]
    for dn in moves:matrix.append([f'跌{dn}%']+[money(next(r['pnl']for r in grid if r['down']==dn and r['up']==up))for up in moves])
    parts.append(section('涨跌滚动阈值矩阵（跨式全期净收益）',table(['目标2天']+[f'涨{v}%'for v in moves],matrix)+'<p class="note">49组仅作样本内敏感性，不用其中最高值替换原15%/8%主参数；完整异常标记、缺价/缺合约次数和回撤保存在结果JSON。</p>','matrix'))
    parts.append(section('期限与成交摩擦敏感性',table(['目标期限','净盈亏','最大回撤','轮数','缺Call信号次数','缺失估值腿日'],[[r['config']['target'],money(r['pnl']),f'{r["mdd_pct"]:.2f}%',len(r['trades']),r['skipped']['no_call'],r['missing_marks']]for r in periods])+table(['每边比例滑点','全期盈亏','最大回撤'],[[f'{r["config"]["slip"]:.0%}',money(r['pnl']),f'{r["mdd_pct"]:.2f}%']for r in sensitivities])+'<p class="note">期限严格范围依次为1–7、5–10、11–17、18–24日；缺同档Call时不替代成不同档跨式。0%滑点仍含最低一分钱价差和佣金。</p>','sensitivity'))
    parts.append(section('剩余现金利息：同资金、同利率比较',table(['假设现金年利率','策略','累计现金利息','计息后净盈亏','计息后最大回撤'],[[f'{r["rate"]:.0%}',r['strategy'],money(r['interest']),money(r['pnl']),f'{r["mdd_pct"]:.2f}%']for r in interest])+'''<p class="note">按相邻交易日间自然天数、前日现金、ACT/365计息；固定原交易路径，不用利息加仓。4%是研究假设而非实际账户报价；不含税费、股息、借券或账户利率阶梯。</p>''','cash'))
    parts.append(section('结论与数据限制',f'''<ul><li><strong>跨式能跑通：</strong>{len(st['trades'])}轮，初始资金与原方案相同，余款现金保留；主模型没有扩大风险单位。</li>
<li><strong>全期与同轮次要分别看：</strong>全期收益低于原策略，主要比较差异包含原有裸股票区间；同轮次跨式的观察优势为 {money(paired_delta)}，尚不能作为实盘切换的充分依据。</li>
<li><strong>行情：</strong>补齐{calls['manifest']['n_contracts']}个实际挂牌Call，使用现有完整Put包；每条腿都是真实日线成交聚合，不是理论定价。</li>
<li><strong>估值限制：</strong>主策略缺失估值腿日 {st['missing_marks']}；低于同日股票收盘内在价值的估值腿日 {st['async_marks']}；同类模拟成交异常 {st['execution_anomalies']}。历史同步Quotes此前返回403，日线末价不是同时刻可成交Bid/Ask。</li>
<li><strong>样本与验证：</strong>仅44个交易日，新增区间13日；全样本阈值扫描不是事前样本外验证。期权到期现金等价处理未模拟结算资金等待、提前行权或借券。</li></ul>
<p><a href="skhy_straddle_results.json">下载完整结果与逐日现金/Call/Put市值</a> · <a href="STRADDLE_README.md">复现说明</a> · <a href="skhy_simulation_report.html">原100股＋2Put报告</a></p>
<p class="note">平价关系参考：<a href="https://prd-web.optionseducation.org/advancedconcepts/put-call-parity">OIC Put/Call Parity</a>。本报告展示历史条件模拟，不把非同步价差当作可执行收益。</p>''','notes'))
    now=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
    html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY 1 Call＋1 Put 策略回测报告</title><style>{css}</style></head><body><div class="wrap"><h1>SKHY 1 Call＋1 Put 策略回测报告</h1><p class="sub">资金口径已更新 · 实际保费本金固定1组／每轮固定10组 · {start}～{end}（44个交易日）<br>保持原跌15% / 涨8%滚动规则 · 生成于 {now} 北京时间</p><nav><a href="#capital">本金与收益</a><a href="#capital-chart">仓位净值</a><a href="#full-trades">固定10组明细</a><a href="#conclusion">旧现金基准</a><a href="#comparison">净值比较</a><a href="#decomposition">差额拆解</a><a href="#trades">逐轮明细</a><a href="#paired">同轮配对</a><a href="#matrix">阈值矩阵</a><a href="#cash">现金利息</a></nav>{''.join(parts)}</div></body></html>'''
    out.write_text(html)
    print('Report:',out)
    print('Straddle:',st['pnl'],st['mdd_pct'],'original:',original['pnl'],'paired delta:',paired_delta,'outside stock:',outside,'matched:',matched)


if __name__=='__main__':main()
