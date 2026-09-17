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
 a,b=[run_intraday(d,i) for i in (1,2)]
 def key(t):return (t['entry_date'],t['entry_time'],t['exit_date'],t['exit_time'],t['put'])
 aa={key(t):t for t in a['trades']};bb={key(t):t for t in b['trades']};rows=[]
 for k in sorted(set(aa)|set(bb)):
  x,z=aa.get(k),bb.get(k);t=x or z
  rows.append(dict(entry=t['entry_date'],exit=t['exit_date'],put=t['put'],strike=t['strike'],expiry=t['expiry'],matched=bool(x and z),strategy1=x,strategy2=z,
    s1_unit_cost=x['cost']/10 if x else None,s1_unit_pnl=x['pnl']/10 if x else None,difference=x['pnl']/10-z['pnl'] if x and z else None))
 result=dict(manifest=d['manifest'],strategy1=a,strategy2=b,rounds=rows)
 css=re.search(r'<style>(.*?)</style>',(root/'skhy_simulation_report.html').read_text(),re.S).group(1)
 parts=[]
 parts.append(section('10:00–10:05执行窗口下的账户结果','<div class="callout-gold"><strong>主情景采用10:00–10:05最早共同成交分钟。</strong>下列结果仍可能包含缺价跳单、延期及到期例外，不代表实际10:00报价下可完整执行的策略收益。请结合交易轮数与数据检查阅读。</div>'+table(['项目',a['name'],b['name']],[
 ['初始资金',money(a['initial']),money(b['initial'])],['期末净资产',money(a['curve'][-1]['equity']),money(b['curve'][-1]['equity'])],['净收益',money(a['pnl']),money(b['pnl'])],['收益率',pct(a['return_pct']),pct(b['return_pct'])],['最大回撤',pct(a['mdd_pct']),pct(b['mdd_pct'])],['交易轮数（含期末持有）',len(a['trades']),len(b['trades'])],['首次实际开仓',a['trades'][0]['entry_date'] if a['trades'] else '无',b['trades'][0]['entry_date'] if b['trades'] else '无']])+'<p>总览与净值按策略1实际10组账户计算；逐轮成本与收益将策略1除以10，按1 Call＋1 Put与100股＋2 Put比较。策略2每轮实际卖出再买回股票，股票买卖费用均计入该轮。</p>','overview'))
 parts.append(section('用户确认的执行规则与数据近似','''<ul>
<li>每日美东时间10:00检查股票相对本轮入场价是否下跌15%或上涨8%；触发则卖出旧组合并买入新组合。到期日也在10:00滚动，不等收盘才正常平仓。旧仓成交后，新仓最早从下一分钟开始寻找，且不晚于10:05，避免新仓使用早于旧仓平仓的价格。</li>
<li>10:00决策使用刚结束的09:59分钟收盘价；按这个可见价格重新选择近似平值合约。到期目标仍为2天、范围1–7天，行权价与当时股价偏离不超过3%。先按期限距离、再按行权价距离排序。</li>
<li>两策略使用同一候选池：Call和Put在09:30–09:59各累计至少成交10张。成交量筛选仅用决策前数据，替代旧版前日成交量筛选；此共同池为配对比较而设。先确定合约，之后在10:00–10:05窗口等待该合约成交，不用其他合约或全天价格替换。</li>
<li>成交代理：从10:00、10:01依次检查到10:05，选择股票和当前组合所有必要期权均有成交的最早共同分钟，并使用该分钟各自首笔价，买卖加减每边2%滑点（期权至少每股$0.01）及每张$0.65佣金；股票每次买入和卖出各5bps。各资产首笔可能发生在不同秒，分钟数据不能保证同步盘口成交。</li>
<li>策略1每轮10 Call＋10 Put，资金不足完整10组则跳过；策略2每轮先卖100股和旧Put，再同时买100股和2 Put，资金不足整个组合则跳过。首次入场前两账户均持现金。</li>
<li>整个窗口都缺必要期权的共同分钟数据时，旧组合延期，不伪造单腿成交。到期仍无法在窗口内平仓时，以收盘内在价值现金等价结算并处置股票，属于明确列示的到期例外，并非窗口内成交。</li>
<li>日终净值保留收盘估值，以衡量持仓期间回撤；缺日终价格时使用最近已知价与内在价值较大者并标记。期末未平仓只估值，不假装10:00已卖出。</li>
</ul><p>同初始本金$22,852.50，现金不计息、不借款、不追加资金。本次沿用07-13～09-11日期窗口，改用分钟执行数据；旧收盘成交结果不再作为主报告结果。</p>''','rules'))
 parts.append(section('账户净值',chart(a,b),'equity'))
 def fmt(v):return money(v) if v is not None else '—'
 costrows=[];profitrows=[]
 for i,r in enumerate(rows,1):
  x,z=r['strategy1'],r['strategy2'];label=r['entry']+' '+(x or z)['entry_time']+' → '+r['exit']+' '+(x or z)['exit_time'];status='同轮可比' if r['matched'] else '路径不同／仅本策略成交'
  costrows.append([i,label,f"${r['strike']:g} / {r['expiry']}",status,fmt(x['call_cost']/10 if x else None),fmt(x['put_cost']/10 if x else None),fmt(r['s1_unit_cost']),fmt(z['stock_cost'] if z else None),fmt(z['put_cost'] if z else None),fmt(z['cost'] if z else None)])
  profitrows.append([i,label,(x or z)['reason'],fmt(r['s1_unit_pnl']),fmt(z['stock_pnl'] if z else None),fmt(z['put_pnl'] if z else None),fmt(z['pnl'] if z else None),fmt(r['difference']),pct(100*x['pnl']/x['cost']) if x else '—',pct(100*z['pnl']/z['cost']) if z else '—'])
 parts.append(section('逐轮成本：1 Call＋1 Put vs 100股＋2 Put',table(['行','入场 → 退出','行权价／到期','配对状态','1 Call成本','1 Put成本','策略1单组总成本','100股含费买入','2 Put成本','策略2总成本'],costrows)+'<p>策略2股票列现在是本轮真实模拟买入支出，已含买股费用；每轮退出另扣卖股费用。两策略若因资金或缺少某条腿数据而出现不同路径，不强行合并，不计算不对应轮次的收益差额。</p>','costs'))
 parts.append(section('逐轮收益：1 Call＋1 Put vs 100股＋2 Put',table(['行','入场 → 退出','退出方式','策略1单组净收益','策略2股票净收益','策略2 Put净收益','策略2总收益','策略1单组－策略2','策略1轮收益率','策略2轮收益率'],profitrows),'profits'))
 parts.append(section('账户对账',table(['项目','策略1','策略2'],[
 ['逐轮净收益合计（策略1为单组）',money(sum(t['pnl']/10 for t in a['trades'])),money(sum(t['pnl'] for t in b['trades']))],['账户换算倍数','10','1'],['全账户净收益',money(a['pnl']),money(b['pnl'])],['对账残差',money(a['reconciliation']),money(b['reconciliation'])]])+'<p>股票首次也与Put同步买入，因此不再额外增加原版07-13至首次买Put之间的裸股票收益。未投入资金一直保留现金。</p>','reconcile'))
 quality=[]
 for k,label in [('no_candidate','10:00前无合格候选'),('no_entry_minute','开仓缺窗口内共同成交'),('no_exit_minute','平仓缺窗口内共同成交／延期'),('cash','资金不足／跳过')]:quality.append([label,a['skipped'][k],b['skipped'][k]])
 for k,label in [('expiry_close_fallback','到期日收盘结算例外'),('missing_eod_marks','日终缺价估算腿日'),('execution_intrinsic_anomalies','开仓价低于股票内在价值异常'),('eod_intrinsic_anomalies','日终非同步估值异常'),('entry_volume_shortfall','开仓张数超过该分钟成交量的腿次')]:quality.append([label,a['flags'][k],b['flags'][k]])
 parts.append(section('成交数据与可执行性检查',table(['检查项','策略1','策略2'],quality)+'<p>一分钟有成交仍不等于可同时成交全部张数；固定2%滑点未验证盘口深度。上述异常、延期和跳单会影响结果，不将分钟聚合模拟当作已验证的实盘收益。历史同步Quotes权限此前不足，当前未获取可成交Bid/Ask。</p>','quality'))
 sens=[]
 for slip in (0,.02,.05):
  x,y=[run_intraday(d,i,slip=slip) for i in (1,2)];sens.append(dict(slip=slip,s1=x['pnl'],s2=y['pnl'],s1_mdd=x['mdd_pct'],s2_mdd=y['mdd_pct']))
 result['slippage']=sens
 windows=[]
 for w in (0,5,10):
  x,y=[run_intraday(d,i,window=w) for i in (1,2)]
  windows.append(dict(window=w,s1_pnl=x['pnl'],s2_pnl=y['pnl'],s1_rounds=len(x['trades']),s2_rounds=len(y['trades']),s1_missing=x['skipped']['no_entry_minute'],s2_missing=y['skipped']['no_entry_minute']))
 result['execution_windows']=windows
 parts.append(section('等待几分钟的影响',table(['最后允许成交分钟','策略1账户净收益','策略2账户净收益','策略1轮数','策略2轮数','策略1缺价开仓次数','策略2缺价开仓次数'],[[f"10:{r['window']:02d}",money(r['s1_pnl']),money(r['s2_pnl']),r['s1_rounds'],r['s2_rounds'],r['s1_missing'],r['s2_missing']] for r in windows])+'<p>主情景预设等待5分钟，不根据收益挑选窗口。所有窗口统一采用先平仓、下一分钟起才可再开仓的时间顺序；因此严格10:00对照也按此规则重算。10:05代表10:05:00–10:05:59分钟桶，分钟数据无法确认各腿在桶内的准确成交先后。</p>','windows'))

 parts.append(section('分钟价格上的滑点敏感性',table(['每边期权滑点','策略1账户净收益','策略2账户净收益','策略1回撤','策略2回撤'],[[pct(r['slip']*100),money(r['s1']),money(r['s2']),pct(r['s1_mdd']),pct(r['s2_mdd'])] for r in sens]),'slippage'))
 parts.append(section('9月4日低Put成本问题的复核','<p>旧版用9月3日收盘选$162.50行权价，却以9月4日收盘$1.12买Put；新数据中该旧合约10:00分钟首笔为$2.31，股票约$169.99，已不同于旧版$177收盘价。新版按当日09:59末价重新选档，不能只把旧表Put价格换成$2.31而保留旧交易路径。</p><p><a href="skhy_intraday_results.json">分钟模型完整结果、逐日资金与跳单记录</a> · <a href="INTRADAY_README.md">分钟数据与复现说明</a> · <a href="skhy_simulation_report.html">历史波动相关因素研究（旧执行口径）</a></p>','audit'))
 now=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
 html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY 美东10:00两策略回测</title><style>{css}</style></head><body><div class="wrap"><h1>SKHY 开盘半小时后交易：两策略对比</h1><p class="sub">策略1账户：10 Call＋10 Put；逐轮展示1 Call＋1 Put<br>策略2：每轮卖出再买入100股＋2 Put<br>每天10:00判断／10:00–10:05执行 · 下跌15%／上涨8% · 数据至09-11 · 更新 {now}</p><nav><a href="#overview">结果</a><a href="#rules">10:00规则</a><a href="#costs">逐轮成本</a><a href="#profits">逐轮收益</a><a href="#quality">数据检查</a></nav>{''.join(parts)}</div></body></html>'''
 out=args.output or root/'skhy_straddle_report.html';out.write_text(html)
 (out.parent/'skhy_intraday_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
 print(json.dumps([{k:r[k] for k in ['strategy','pnl','return_pct','mdd_pct','skipped','flags']} for r in (a,b)],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
