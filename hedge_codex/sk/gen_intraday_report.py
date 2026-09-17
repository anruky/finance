# -*- coding: utf-8 -*-
import argparse,json,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from backtest_intraday import run_intraday
from report_helpers import money,pct,table,section,chart

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--data',type=Path);ap.add_argument('--output',type=Path);args=ap.parse_args();root=args.project_dir
 path=args.data or root/'data/SKHY_intraday.json';d=json.loads(path.read_text())
 a,b=[run_intraday(d,i,allow_topup=i==1) for i in (1,2)]
 def key(t):return (t['entry_date'],t['exit_date'],t['put'])
 aa={key(t):t for t in a['trades']};bb={key(t):t for t in b['trades']};rows=[]
 assert len(aa)==len(a['trades']) and len(bb)==len(b['trades']), 'Duplicate round key'
 for k in sorted(set(aa)|set(bb)):
  x,z=aa.get(k),bb.get(k);t=x or z
  rows.append(dict(entry=t['entry_date'],exit=t['exit_date'],put=t['put'],strike=t['strike'],expiry=t['expiry'],matched=bool(x and z),same_execution_times=bool(x and z and x['entry_time']==z['entry_time'] and x['exit_time']==z['exit_time']),strategy1=x,strategy2=z,
    s1_unit_cost=x['cost']/10 if x else None,s1_unit_pnl=x['pnl']/10 if x else None,difference=x['pnl']/10-z['pnl'] if x and z else None))
 result=dict(manifest=d['manifest'],strategy1=a,strategy2=b,rounds=rows)
 css=re.search(r'<style>(.*?)</style>',(root/'skhy_simulation_report.html').read_text(),re.S).group(1)
 parts=[]
 optimization_path=(args.output.parent if args.output else root)/'skhy_exit_optimization_results.json'
 if not optimization_path.exists():optimization_path=root/'skhy_exit_optimization_results.json'
 if optimization_path.exists():
  opt=json.loads(optimization_path.read_text());summaries={x['rule']['id']:x for x in opt['summaries']};best=summaries[opt['best_full']];chosen=summaries[opt['robust']]
  parts.append(section('新增：129组退出规则优化与验证',f"<p>策略1全期亏损最少的事后候选为 <strong>{best['rule']['label']}</strong>，净收益 {money(best['full']['pnl'])}。只按前段数据选择为 <strong>{chosen['rule']['label']}</strong>，后段未改善原规则的美元收益。扫描没有找到全期盈利且经验证有效的方案，下面仍保留15%／8%基准。</p><p><a href='skhy_exit_optimization_report.html'>打开退出策略优化报告：矩阵、指标检验、逐轮明细和压力测试</a></p>",'exit-optimization'))

 parts.append(section('独立执行账户结果（逐轮共同价格比较另列）','<div class="callout-gold"><strong>主情景采用10:00–15:59最早共同成交分钟。</strong>下列结果仍可能包含缺价跳单、延期及到期例外，不代表实际10:00报价下可完整执行的策略收益。请结合交易轮数与数据检查阅读。</div>'+table(['项目',a['name'],b['name']],[
 ['初始资金',money(a['initial']),money(b['initial'])],['期末净资产',money(a['curve'][-1]['equity']),money(b['curve'][-1]['equity'])],['净收益',money(a['pnl']),money(b['pnl'])],['净收益／累计实际投入',pct(a['return_pct']),pct(b['return_pct'])],['追加资金',money(a['additional_deposits']),money(b['additional_deposits'])],['累计实际投入',money(a['total_deposits']),money(b['total_deposits'])],['XIRR年化（短样本外推）',pct(a['xirr_pct']) if a['xirr_pct'] is not None else '—',pct(b['xirr_pct']) if b['xirr_pct'] is not None else '—'],['剔除入金影响的单位净值最大回撤',pct(a['mdd_pct']),pct(b['mdd_pct'])],['交易轮数（含期末持有）',len(a['trades']),len(b['trades'])],['首次实际开仓',a['trades'][0]['entry_date'] if a['trades'] else '无',b['trades'][0]['entry_date'] if b['trades'] else '无']])+'<p>总览与净值按策略1实际10组账户计算；逐轮成本与收益将策略1除以10，按1 Call＋1 Put与100股＋2 Put比较。策略2每轮实际卖出再买回股票，股票买卖费用均计入该轮。</p>','overview'))
 parts.append(section('追加资金记录与收益口径',table(['策略','日期','时间','追加金额'],[[r['name'],t['date'],t['time'],money(t['amount'])] for r in (a,b) for t in r['deposits']])+"<p>仅在即将成交且现金不足时补足缺口；入金不是利润。净收益＝期末现金及持仓市值－初始本金－全部追加。净收益/累计投入是未年化的简单资金比率，未考虑每笔资金占用天数。XIRR以初始和追加入金为负现金流、期末净资产为正现金流，按实际日期和365天计算；不足一年，年化仅为数学外推。</p><p>回撤采用单位净值：入金前按当前净资产发行等值份额，入金本身不改变单位净值，随后再计买入费用。曲线和最大回撤均剔除外部入金。<a href='https://support.microsoft.com/zh-cn/excel/functions/xirr-function'>XIRR日期口径参考</a>。</p>",'deposits'))
 parts.append(section('用户确认的执行规则与数据近似','''<ul>
<li>每日美东时间10:00检查股票相对本轮入场价是否下跌15%或上涨8%；触发则卖出旧组合并买入新组合。到期日也在10:00滚动，不等收盘才正常平仓。旧仓成交后，新仓最早从下一分钟开始寻找，且不晚于15:59，避免新仓使用早于旧仓平仓的价格。</li>
<li>10:00决策使用刚结束的09:59分钟收盘价；按这个可见价格重新选择近似平值合约。到期目标仍为2天、范围1–7天，行权价与当时股价偏离不超过3%。先按期限距离、再按行权价距离排序。</li>
<li>两策略使用同一候选池：Call和Put在09:30–09:59各累计至少成交10张。成交量筛选仅用决策前数据，替代旧版前日成交量筛选；此共同池为配对比较而设。先确定合约，之后在10:00–15:59窗口等待该合约成交，不用其他合约或全天价格替换。</li>
<li>选档固定在10:00，若等待较长，成交时可能已不再平值；不会事后按有利价格换档。成交代理：从10:00、10:01依次检查到15:59，选择股票和当前组合所有必要期权均有成交的最早共同分钟，并使用该分钟各自首笔价，买卖加减每边2%滑点（期权至少每股$0.01）及每张$0.65佣金；股票每次买入和卖出各5bps。各资产首笔可能发生在不同秒，分钟数据不能保证同步盘口成交。</li>
<li>策略1每轮10 Call＋10 Put，资金不足完整10组时在成交前按缺口追加现金，逐笔记录入金；策略2每轮先卖100股和旧Put，再同时买100股和2 Put，资金不足整个组合则跳过。首次入场前两账户均持现金。</li>
<li>整个窗口都缺必要期权的共同分钟数据时，旧组合延期，不伪造单腿成交。到期仍无法在窗口内平仓时，以收盘内在价值现金等价结算并处置股票，属于明确列示的到期例外，并非窗口内成交。本次是否发生此例外以数据检查表为准。</li>
<li>日终净值保留收盘估值，以衡量持仓期间回撤；缺日终价格时使用最近已知价与内在价值较大者并标记。期末未平仓只估值，不假装10:00已卖出。</li>
</ul><p>同初始本金$22,852.50，现金不计息、不借款；策略1允许追加资金，策略2保持原本金。本次沿用07-13～09-11日期窗口，改用分钟执行数据；旧收盘成交结果不再作为主报告结果。</p>''','rules'))
 parts.append(section('剔除入金影响的账户净值',chart(a,b),'equity'))
 def fmt(v):return money(v) if v is not None else '—'
 def signed(v):
  return '<span class="'+('c-red' if v>=0 else 'c-green')+'">'+f'${v:+,.2f}'+'</span>'
 shared=[];combined=[]
 for x in reversed(a['trades']):
  pc=x['put_cost']/5;pi=x['put_income']/5
  stock_cost=x['entry_spot']*100*(1+.0005)
  stock_income=x['exit_spot']*100*(1 if x['mark_only'] else 1-.0005)
  pnl2=pi-pc+stock_income-stock_cost
  call_bar=d['minutes'][x['call']][x['entry_date']][x['entry_time']]
  put_bar=d['minutes'][x['put']][x['entry_date']][x['entry_time']]
  row=dict(entry=x['entry_date'],entry_time=x['entry_time'],exit=x['exit_date'],exit_time=x['exit_time'],put=x['put'],strike=x['strike'],expiry=x['expiry'],entry_spot=x['entry_spot'],exit_spot=x['exit_spot'],call_price=call_bar['o'],put_price=put_bar['o'],
   s1_cost=x['cost']/10,s1_income=x['income']/10,s1_pnl=x['pnl']/10,s2_put_cost=pc,s2_put_income=pi,s2_stock_cost=stock_cost,s2_stock_income=stock_income,s2_total_cost=stock_cost+pc,s2_pnl=pnl2,difference=x['pnl']/10-pnl2,mark_only=x['mark_only'])
  shared.append(row)
  combined.append([x['entry_date']+' '+x['entry_time'],x['exit_date']+' '+x['exit_time'],x['reason'],money(x['entry_spot']),money(x['exit_spot']),f"{100*(x['exit_spot']/x['entry_spot']-1):+.2f}%",money(x['strike'])+' / '+x['expiry'],money(call_bar['o']),money(put_bar['o']),
   money(row['s1_cost']),money(row['s1_income']),signed(row['s1_pnl']),money(pc),money(pi),signed(pnl2),signed(row['difference'])])
 result['shared_price_rounds']=shared
 result['shared_price_basis']='Strategy1 execution schedule and raw prices; strategy2 repriced per round, not independent account returns'
 headers=['入场日／时间','出场日／时间','方式','入场spot','出场spot','波动','行权价／到期','Call价','Put价','成本','收入','利润','Put成本','Put收入','总利润','利润差①－②']
 grouped='<tr><th colspan="9">共同时间与价格（统一采用策略1）</th><th colspan="3">① 1 Call＋1 Put</th><th colspan="3">② 100股＋2 Put</th><th>对比</th></tr>'
 combined_html=table(headers,combined).replace('<table>','<table class="round-details">',1).replace('<thead>','<thead>'+grouped,1)
 parts.append(section('逐轮成本与收益：统一策略1时间与价格','<span id="profits"></span><p class="note">每周期一行，最新在前。股票、Call和Put均采用策略1的入场、退出时点及价格，策略2按这些共同价格重新计费和计算收益。以下是固定策略1交易日程的结构对比，不是策略2独立执行的账户回测。</p>'+combined_html+'<p class="note">①成本与收入为单组Call＋Put含费收支。②Put成本/收入仅含两张Put，总利润＝Put净收益＋100股同时间段净收益，股票每次买卖各扣5bps。共享Put每张费用相同，因此②Put收支为①单张Put的2倍。股票本金可由入场spot×100及买入费用得到；完整股票成本、回收额、组合总成本在结果JSON的shared_price_rounds中保留。期末未平仓统一用策略1期末估值，不额外扣虚构卖出费用。</p>','costs'))
 parts.append(section('共同价格与独立账户的区别',table(['口径','策略1（单组）','策略2（100股＋2 Put）'],[
 ['本表：策略1日程、共同价格利润合计',money(sum(r['s1_pnl'] for r in shared)),money(sum(r['s2_pnl'] for r in shared))],
 ['独立执行账户：策略1除以10后对照',money(a['pnl']/10),money(b['pnl'])]])+'<p>顶部总览、净值、追加资金和下面账户对账仍来自两策略各自的实际模拟路径；本表为剔除不同成交时间影响而重新定价，策略2表内利润不能直接与独立账户利润相加或混用。</p>','shared-basis'))
 parts.append(section('账户对账',table(['项目','策略1','策略2'],[
 ['逐轮净收益合计（策略1为单组）',money(sum(t['pnl']/10 for t in a['trades'])),money(sum(t['pnl'] for t in b['trades']))],['账户换算倍数','10','1'],['累计实际投入',money(a['total_deposits']),money(b['total_deposits'])],['期末净资产',money(a['curve'][-1]['equity']),money(b['curve'][-1]['equity'])],['全账户净收益＝期末资产－全部入金',money(a['pnl']),money(b['pnl'])],['对账残差',money(a['reconciliation']),money(b['reconciliation'])]])+'<p>股票首次也与Put同步买入，因此不再额外增加原版07-13至首次买Put之间的裸股票收益。未投入资金一直保留现金。</p>','reconcile'))
 quality=[]
 for k,label in [('no_candidate','10:00前无合格候选'),('no_entry_minute','开仓缺窗口内共同成交'),('no_exit_minute','平仓缺窗口内共同成交／延期'),('cash','资金不足／跳过')]:quality.append([label,a['skipped'][k],b['skipped'][k]])
 for k,label in [('expiry_close_fallback','到期日收盘结算例外'),('missing_eod_marks','日终缺价估算腿日'),('execution_intrinsic_anomalies','开仓价低于股票内在价值异常'),('eod_intrinsic_anomalies','日终非同步估值异常'),('entry_volume_shortfall','开仓张数超过该分钟成交量的腿次')]:quality.append([label,a['flags'][k],b['flags'][k]])
 parts.append(section('成交数据与可执行性检查',table(['检查项','策略1','策略2'],quality)+'<p>一分钟有成交仍不等于可同时成交全部张数；固定2%滑点未验证盘口深度。上述异常、延期和跳单会影响结果，不将分钟聚合模拟当作已验证的实盘收益。历史同步Quotes权限此前不足，当前未获取可成交Bid/Ask。</p>','quality'))
 sens=[]
 for slip in (0,.02,.05):
  x,y=[run_intraday(d,i,slip=slip,allow_topup=i==1) for i in (1,2)];sens.append(dict(slip=slip,s1=x['pnl'],s2=y['pnl'],s1_mdd=x['mdd_pct'],s2_mdd=y['mdd_pct']))
 result['slippage']=sens
 windows=[]
 for w in (0,5,10,30,60,359):
  x,y=[run_intraday(d,i,window=w,allow_topup=i==1) for i in (1,2)]
  windows.append(dict(window=w,s1_pnl=x['pnl'],s2_pnl=y['pnl'],s1_rounds=len(x['trades']),s2_rounds=len(y['trades']),s1_missing=x['skipped']['no_entry_minute'],s2_missing=y['skipped']['no_entry_minute']))
 result['execution_windows']=windows
 parts.append(section('等待几分钟的影响',table(['最后允许成交分钟','策略1账户净收益','策略2账户净收益','策略1轮数','策略2轮数','策略1缺价开仓次数','策略2缺价开仓次数'],[[f"{10+r['window']//60:02d}:{r['window']%60:02d}",money(r['s1_pnl']),money(r['s2_pnl']),r['s1_rounds'],r['s2_rounds'],r['s1_missing'],r['s2_missing']] for r in windows])+'<p>主情景按用户要求持续寻找至当天最后一个常规交易分钟15:59，不根据收益挑选窗口；各窗口均允许策略1补足资金。所有窗口统一采用先平仓、下一分钟起才可再开仓的时间顺序；因此严格10:00对照也按此规则重算。15:59代表15:59:00–15:59:59分钟桶，分钟数据无法确认各腿在桶内的准确成交先后。</p>','windows'))

 parts.append(section('分钟价格上的滑点敏感性',table(['每边期权滑点','策略1账户净收益','策略2账户净收益','策略1回撤','策略2回撤'],[[pct(r['slip']*100),money(r['s1']),money(r['s2']),pct(r['s1_mdd']),pct(r['s2_mdd'])] for r in sens]),'slippage'))
 parts.append(section('9月4日低Put成本问题的复核','<p>旧版用9月3日收盘选$162.50行权价，却以9月4日收盘$1.12买Put；新数据中该旧合约10:00分钟首笔为$2.31，股票约$169.99，已不同于旧版$177收盘价。新版按当日09:59末价重新选档，不能只把旧表Put价格换成$2.31而保留旧交易路径。</p><p><a href="skhy_intraday_results.json">分钟模型完整结果、逐日资金与跳单记录</a> · <a href="INTRADAY_README.md">分钟数据与复现说明</a> · <a href="skhy_simulation_report.html">历史波动相关因素研究（旧执行口径）</a></p>','audit'))
 css+='\n.round-details td {vertical-align:middle;} .round-details tbody tr:nth-child(even) {background:rgba(255,255,255,.018);} .round-details th {position:static;} .round-details td:nth-child(10),.round-details td:nth-child(13),.round-details td:nth-child(16) {border-left:2px solid var(--border);}'
 now=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
 html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY 美东10:00两策略回测</title><style>{css}</style></head><body><div class="wrap"><h1>SKHY 开盘半小时后交易：两策略对比</h1><p class="sub">策略1账户：10 Call＋10 Put；逐轮展示1 Call＋1 Put<br>策略2：每轮卖出再买入100股＋2 Put<br>每天10:00判断／10:00–15:59执行 · 下跌15%／上涨8% · 数据至09-11 · 更新 {now}</p><nav><a href="#overview">结果</a><a href="#rules">10:00规则</a><a href="#costs">逐轮成本与收益</a><a href="#quality">数据检查</a></nav>{''.join(parts)}</div></body></html>'''
 out=args.output or root/'skhy_straddle_report.html';out.write_text(html)
 (out.parent/'skhy_intraday_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 print(json.dumps([{k:r[k] for k in ['strategy','pnl','return_pct','mdd_pct','skipped','flags']} for r in (a,b)],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
