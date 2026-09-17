# -*- coding: utf-8 -*-
"""Compare fixed 10 straddles with 100 shares + 2 puts, on matched rounds."""
import argparse,json,re,math
from pathlib import Path
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo
from backtest_audited import Config,run
from backtest_straddle import run_straddle

def money(x):return f'${x:,.2f}'
def pct(x):return f'{x:.2f}%'
def table(headers,rows):
 return '<div class="tbl-scroll"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def section(title,body,ident):return f'<section class="card" id="{ident}"><h2>{title}</h2>{body}</section>'
def chart(a,b):
 vals=[[r['equity']/x['initial']*100 for r in x['curve']] for x in (a,b)]
 lo=math.floor(min(map(min,vals))/10)*10-10;hi=math.ceil(max(map(max,vals))/10)*10+10
 y=lambda v:270-(v-lo)/(hi-lo)*245
 out=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 320" role="img" aria-label="两个策略同本金净值"><title>策略1与策略2净值</title>']
 for j in range(6):
  v=lo+(hi-lo)*j/5
  out.append(f'<line x1="60" x2="970" y1="{y(v):.2f}" y2="{y(v):.2f}" stroke="#303645"/><text x="50" y="{y(v)+4:.2f}" fill="#aaa" text-anchor="end" font-size="12">{v:.0f}</text>')
 for vv,col in zip(vals,['#f5c344','#4da3ff']):
  pts=' '.join(f'{60+i*910/(len(vv)-1):.2f},{y(v):.2f}' for i,v in enumerate(vv))
  out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5"/>')
 for i in (0,10,20,30,len(vals[0])-1):
  out.append(f'<text x="{60+i*910/(len(vals[0])-1):.2f}" y="300" fill="#aaa" text-anchor="middle" font-size="12">{a["curve"][i]["date"][5:]}</text>')
 return ''.join(out)+'</svg><p>金：策略1（10 Call＋10 Put）；蓝：策略2（100股＋2 Put）。同初始本金归一化为100，包含现金及未平仓资产市值。</p>'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--output',type=Path);args=ap.parse_args();root=args.project_dir
 data=json.loads((root/'data/SKHY_put_history.json').read_text());calls=json.loads((root/'data/SKHY_call_history.json').read_text())
 import hashlib
 assert calls['manifest']['put_dataset_sha256']==hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
 cfg=Config(down=15,up=8,puts=2)
 a=run_straddle(data,calls,cfg,fixed_pairs=10);b=run(data,cfg)
 a['name']='策略1：10 Call＋10 Put';b['name']='策略2：100股＋2 Put'
 sig=lambda t:(t['signal_date'],t['entry_date'],t['exit_date'],t['expiry'],t['strike'])
 assert [sig(t) for t in a['trades']]==[sig(t) for t in b['trades']], 'Paths differ; cannot match rounds by row'
 assert all(t['pairs']==10 for t in a['trades'])
 prices={r[0]:r[4] for r in data['stock']};rounds=[]
 for i,(x,z) in enumerate(zip(a['trades'],b['trades']),1):
  stock_value=z['entry_spot']*100;stock_pnl=(prices[z['exit_date']]-z['entry_spot'])*100
  rounds.append(dict(round=i,entry=x['entry_date'],exit=x['exit_date'],expiry=x['expiry'],strike=x['strike'],reason=x['reason'],mark_only=x['mark_only'],
   s1_pairs=1,s1_account_pairs=x['pairs'],s1_account_pnl=x['pnl'],s1_call_cost=x['call_cost']/x['pairs'],s1_put_cost=x['put_cost']/x['pairs'],s1_cost=x['cost']/x['pairs'],s2_stock_value=stock_value,s2_put_cost=z['cost'],s2_capital=stock_value+z['cost'],
   s1_pnl=x['pnl']/x['pairs'],s2_stock_pnl=stock_pnl,s2_put_pnl=z['pnl'],s2_pnl=stock_pnl+z['pnl'],difference=x['pnl']/x['pairs']-stock_pnl-z['pnl'],
   s1_round_roi_pct=100*x['pnl']/x['cost'],s2_round_roi_pct=100*(stock_pnl+z['pnl'])/(stock_value+z['cost'])))
 outside=b['pnl']-sum(t['s2_pnl'] for t in rounds)
 assert abs(a['pnl']-sum(t['s1_pnl']*t['s1_account_pairs'] for t in rounds))<1e-6
 result=dict(round_comparison_basis='1 Call + 1 Put versus 100 shares + 2 Put; strategy1 account remains 10 pairs',strategy1=a,strategy2=b,rounds=rounds,strategy2_outside_round_pnl=outside,manifest=calls['manifest'])
 css=re.search(r'<style>(.*?)</style>',(root/'skhy_simulation_report.html').read_text(),re.S).group(1)
 parts=[]
 parts.append(section('两策略总览',table(['项目',a['name'],b['name']],[
 ['初始账户资金',money(a['initial']),money(b['initial'])],['期末净资产',money(a['curve'][-1]['equity']),money(b['curve'][-1]['equity'])],
 ['全期净收益',money(a['pnl']),money(b['pnl'])],['账户收益率',pct(a['return_pct']),pct(b['return_pct'])],['最大回撤',pct(a['mdd_pct']),pct(b['mdd_pct'])],
 ['配对轮数',len(rounds),len(rounds)],['现金不足跳单',a['skipped']['cash'],b['skipped'].get('cash',0)]])+f'<p>策略1本期比策略2多赚 {money(a["pnl"]-b["pnl"])}，但最大回撤更大。两者初始资金相同，期权数量和风险暴露不同；收益差额同时反映仓位规模与组合结构，不能单独归因于Call＋Put结构。</p>','overview'))
 parts.append(section('统一规则与成本口径','''<ul><li>共同触发：前日股票收盘相对该轮入场股价下跌15%或上涨8%，下一交易日模拟滚动；否则持有至到期。“熔断”在此指滚动触发，并非止损成交价保证。</li>
<li>策略1：每轮固定10张Call＋10张Put，同一行权价、同一到期日，每张乘数100；利润留现金，资金不足完整10组则跳过，不减少张数、不借款、不追加资金。</li>
<li>策略2：持续持有100股，每轮买2张Put；滚动时仅更换Put，不反复卖出和重买股票。期权到期采用现金等价处理，维持100股敞口。</li>
<li>共同Put选档：目标2天，实际剩余1–7天、优先最接近目标期限；前日挂牌及成交量筛选。策略1另要求匹配Call可用。本样本两策略14轮入场、退出、行权价和到期日全部一致。</li>
<li>费用：期权每边2%滑点、最低每股$0.01，每张佣金$0.65；股票5bps；到期价内腿含行权和股票平仓摩擦。现金利息为0。</li></ul>
<p><strong>逐轮成本：</strong>策略1按1张Call＋1张Put列含费支出（实际10组账本除以10）；策略2列100股在本轮入场时的市值＋两张Put含费支出，作为轮初资产占用参考。股票市值并非本轮新增支付，不能把每轮股票市值相加作为累计投入。</p>
<p><strong>逐轮收益：</strong>策略1按1张Call＋1张Put列净损益（实际10组账本除以10）；总览、净值及滑点敏感性仍按实际10组账户计算；策略2是该轮100股价格变动损益＋两张Put净损益。股票首次买入费用放在轮次外对账，避免重复扣费。期末仍持有的最后一轮只计市值。各轮收益率仅按各自轮初资产成本计算，不能相加当账户收益率。</p>''','rules'))
 parts.append(section('同本金账户净值',chart(a,b),'equity'))
 parts.append(section('每轮成本对比：1 Call＋1 Put vs 100股＋2 Put',table(['轮次','入场 → 退出','行权价／到期','策略1 1 Call支出','策略1 1 Put支出','策略1 单组合计支出','策略2 股票市值','策略2 Put支出','策略2 资产占用'],[
 [t['round'],t['entry']+' → '+t['exit'],f"${t['strike']:g} / {t['expiry']}",money(t['s1_call_cost']),money(t['s1_put_cost']),money(t['s1_cost']),money(t['s2_stock_value']),money(t['s2_put_cost']),money(t['s2_capital'])] for t in rounds]),'costs'))
 parts.append(section('每轮收益对比：1 Call＋1 Put vs 100股＋2 Put',table(['轮次','入场 → 退出','退出方式','策略1 单组净收益','策略2 股票损益','策略2 Put损益','策略2 合计收益','策略1单组－策略2','策略1 轮收益率','策略2 轮收益率'],[
 [t['round'],t['entry']+' → '+t['exit'],t['reason'],money(t['s1_pnl']),money(t['s2_stock_pnl']),money(t['s2_put_pnl']),money(t['s2_pnl']),money(t['difference']),pct(t['s1_round_roi_pct']),pct(t['s2_round_roi_pct'])] for t in rounds]),'profits'))
 parts.append(section('逐轮与全期账本对账',table(['项目','策略1（单组→10组账户）','策略2（100股＋2 Put）'],[
 ['期权轮次内合计净收益',money(sum(t['s1_pnl'] for t in rounds)),money(sum(t['s2_pnl'] for t in rounds))],
 ['换算到账户的轮内净收益',money(sum(t['s1_pnl']*t['s1_account_pairs'] for t in rounds)),money(sum(t['s2_pnl'] for t in rounds))],
 ['轮次外净收益（含首次股票费用）',money(0),money(outside)],['全期净收益',money(a['pnl']),money(b['pnl'])]])+f'<p>逐轮表策略1为单组口径，其收益合计乘以10后才对应实际账户收益；当前模型每张费用线性计入，因此可按实际张数归一化，这不是另行增加或减少账户仓位。策略2于07-13买入100股，首轮期权07-15才开仓；这段股票收益扣除首次买股费用后为 {money(outside)}。它单列在轮次外，因此逐轮收益合计与全期收益不同。所有交易行、逐日现金及资产市值均保存在结果JSON。</p>','reconcile'))
 sens=[]
 for slip in (0,.02,.05):
  conf=replace(cfg,slip=slip);x=run_straddle(data,calls,conf,fixed_pairs=10);y=run(data,conf)
  sens.append(dict(slip=slip,strategy1_pnl=x['pnl'],strategy2_pnl=y['pnl'],strategy1_mdd=x['mdd_pct'],strategy2_mdd=y['mdd_pct']))
 result['slippage']=sens
 parts.append(section('相同成交摩擦敏感性',table(['每边滑点','策略1净收益','策略2净收益','策略1最大回撤','策略2最大回撤'],[[pct(t['slip']*100),money(t['strategy1_pnl']),money(t['strategy2_pnl']),pct(t['strategy1_mdd']),pct(t['strategy2_mdd'])] for t in sens])+ '<p>每档独立重跑完整资金路径，仍保留最低一分钱价差和佣金。</p>','slippage'))
 parts.append(section('数据与结果边界',f'''<p>本次统一策略和报告结构，沿用2026-07-13至09-11的44个交易日行情。价格为历史日线聚合末价，缺少同步Bid/Ask与盘口深度，固定10组的实际可成交性尚未验证。策略1估值异常腿日 {a['async_marks']}、成交异常 {a['execution_anomalies']}；策略2估值异常腿日 {b['async_marks']}、成交异常 {b['execution_anomalies']}。模型沿用到期现金等价结算，未模拟实物交割融资、提前行权或结算延迟。结果属于条件模拟。</p>
<p><a href="skhy_strategy_comparison_results.json">完整两策略结果与逐轮数据</a> · <a href="skhy_simulation_report.html">原100股＋2Put报告及波动相关因素研究</a></p>''','notes'))
 now=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
 html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY 两策略逐轮成本与收益对比</title><style>{css}</style></head><body><div class="wrap"><h1>SKHY 两策略成本与收益对比</h1><p class="sub">账户：策略1每轮10 Call＋10 Put ｜ 策略2为100股＋每轮2 Put<br>逐轮对比：策略1按1 Call＋1 Put归一化，策略2保持100股＋2 Put<br>共同下跌15%／上涨8%滚动 · 2026-07-13～09-11 · 更新于 {now}</p><nav><a href="#overview">总览</a><a href="#costs">逐轮成本</a><a href="#profits">逐轮收益</a><a href="#reconcile">账本对账</a></nav>{''.join(parts)}</div></body></html>'''
 out=args.output or root/'skhy_straddle_report.html';out.write_text(html)
 (out.parent/'skhy_strategy_comparison_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 print(json.dumps(dict(rounds=len(rounds),strategy1_pnl=a['pnl'],strategy2_pnl=b['pnl'],outside=outside),ensure_ascii=False))
if __name__=='__main__':main()
