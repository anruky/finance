# -*- coding: utf-8 -*-
import json,html
from pathlib import Path
P=Path(__file__).parent;d=json.loads((P/'all6_optimization.json').read_text())
N=len(d['training_ids']);end=d['metadata']['end']
labels={'baseline':'持有到期，不轮空','hold_gate':'持有到期＋费用轮空','symmetric':'涨跌相同固定止盈','asymmetric':'涨跌不同固定止盈','timed':'固定止盈＋指定日强制退出','trailing':'收益回撤止盈','stock_move':'股价幅度＋组合盈利退出','decay_symmetric':'涨跌相同＋时间递减','decay_asymmetric':'涨跌不同＋时间递减','decay_no_gate':'时间递减，不轮空','all_best':'全搜索最高'}
def n(x):return '—' if x is None else f'{x:,.2f}'
def m(x):return '$'+n(x)
def e(x):return html.escape(str(x))
def table(head,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
ranked=sorted([k for k in labels if k not in ['all_best','baseline','hold_gate']],key=lambda k:d['comparison'][k]['pnl'],reverse=True)
comparison=table(['策略类别（各自最佳参数）','全部已到期周期总毛收益','全部已到期周期总净收益','参与/盈利轮数','累计买入成本','最差一轮净收益'],[[labels[k],m(sum(r['gross'] for r in d['selected_results'][k][:N])),m(d['comparison'][k]['pnl']),str(d['comparison'][k]['trades'])+' / '+str(d['comparison'][k]['wins']),m(d['comparison'][k]['cost']),m(d['comparison'][k]['worst'])] for k in ranked])
params=table(['策略类别','选出的具体参数'],[[labels[k],e(d['selected'][k]['name'])] for k in ranked])
profile=table(['降目标方案','一起重选初始参数后的最高净收益','初始涨/跌侧目标','轮空与止损'],[[e(x['schedule']['name']),m(x['stats']['pnl']),str(x['rule']['up'])+'% / '+str(x['rule']['down'])+'%',e(x['rule']['name'].split('；',1)[-1])] for x in d['profiles']])
ablation=table(['其他条件完全不变，仅改变时间目标','全部已到期周期总净收益','相对原固定目标'],[[e(d['selected']['asymmetric']['name']),m(d['comparison']['asymmetric']['pnl']),'—']]+[[e(x['rule']['schedule']['name']),m(x['stats']['pnl']),m(x['stats']['pnl']-d['comparison']['asymmetric']['pnl'])] for x in d['ablation']])
rule=d['selected']['decay_asymmetric'];sched=rule['schedule'];stages=[('入场周五～下周二',None),('下周三',sched['wed']),('下周四',sched['thu']),('到期周五',sched['fri'])]
def target(base,a):return base if a is None else base*a['factor'] if 'factor' in a else a['absolute']
schedule_table=table(['时段（美东）','股票相对入场价≥0：净收益目标','股票相对入场价<0：净收益目标'],[[name,n(target(rule['up'],a))+'%',n(target(rule['down'],a))+'%'] for name,a in stages])

stress=table(['规则','买入/卖出摩擦','最大价格年龄','全部已到期周期总净收益'],[[labels[x['key']],str(round(x['slip']*100))+'%',str(x['age'])+'分钟',m(x['stats']['pnl'])] for x in d['stress'] if x['key']!='all_best'])
time_rows=[]
for x in d['time_value'][:N]:
 c=next(c for c in d['cycles'] if c['id']==x['id']);expiry=c['expiry']
 for r in x['rows']:
  from datetime import datetime
  dow=datetime.fromisoformat(r['et']).weekday()
  if dow not in [2,3]:continue
  time_rows.append([x['id'][5:],r['et'][:16].replace('T',' '),m(r['value']),m(r['intrinsic']),m(r['extrinsic']),str(r['call_age'])+' / '+str(r['put_age'])])
time_table=table(['开仓周期','周三/周四采样ET','Call＋Put市场估值','内在价值合计','剩余外在价值估计','两腿价格年龄分钟'],time_rows)
options=''.join('<option value="'+k+'"'+(' selected' if k=='all_best' else '')+'>'+label+'</option>' for k,label in labels.items() if k not in ['baseline','hold_gate'])

comparison_note=('固定涨跌目标与时间递减方案并列最高。' if abs(d['comparison']['asymmetric']['pnl']-d['comparison']['decay_asymmetric']['pnl'])<1e-7 else '固定目标与时间递减方案的总收益不同，见下方排名。')
best=d['selected']['all_best'];best_results=d['selected_results']['all_best'];completed_profit=sum(best_results[i]['pnl'] for i in d['training_ids']);ongoing=sum(r['pnl'] for c,r in zip(d['cycles'],best_results) if not c['completed'])
def stamp(t):return t[:16].replace('T',' ') if t else '—'
ledger=[];best_rows=[]
for c,r in zip(d['cycles'],best_results):
 skipped=r['skipped'];kind='轮空' if skipped else '模拟卖出' if r.get('fill') else '到期结算' if r['closed'] else '持仓估值（未卖出）'
 cp=None if skipped else r['fill']['call'] if r.get('fill') else c['final']['call']
 pp=None if skipped else r['fill']['put'] if r.get('fill') else c['final']['put']
 proceeds=None if skipped else r['cost']+r['pnl']
 reason=r['reason']+('；曾触发但无后续共同成交分钟' if r.get('unfilled_signal') else '')
 row=dict(cycle=c['label'],completed=c['completed'],status=kind,entry=None if skipped else c['entry_et'],strike=c['strike'],call_entry=None if skipped else c['call_entry'],put_entry=None if skipped else c['put_entry'],cost=r['cost'],signal=r['signal'],sell_time=r['exit'] if r.get('fill') else None,settlement_or_mark_time=r['exit'] if not skipped and not r.get('fill') else None,call_exit=cp,put_exit=pp,net_proceeds=proceeds,gross=r['gross'],net=r['pnl'],return_pct=r['roi'],reason=reason)
 ledger.append(row)
 best_rows.append([c['label'],kind,stamp(row['entry']),n(c['strike']),n(row['call_entry'])+' / '+n(row['put_entry']),m(r['cost']),stamp(r['signal']),stamp(row['sell_time']),stamp(row['settlement_or_mark_time']),n(cp)+' / '+n(pp),m(proceeds) if proceeds is not None else '—',m(r['gross']),m(r['pnl']),n(r['roi'])+'%' if r['roi'] is not None else '—',e(reason)])
best_table=table(['周期','状态','买入时间ET','行权价','买入Call / Put单价','买入总成本','触发时间ET','实际模拟卖出ET','结算/估值时间ET','退出/结算/估值Call / Put单价','净回收金额','毛损益','净损益','净收益率','原因'],best_rows)
(P/'best_exit_cycle_details.json').write_text(json.dumps(dict(rule=best,as_of=d['metadata']['end'],completed_profit=completed_profit,ongoing_pnl=ongoing,cycles=ledger),ensure_ascii=False,indent=2))

body=f'''<header><div class="eyebrow">SKHY · 报告3更新 · 全部已到期周期全部训练</div><h1>不同退出策略的总收益<br>加入周三、周四降低盈利要求</h1><p>固定每轮1 Call＋1 Put。共{len(d['cycles'])}个周期，其中{N}个已到期周期全部参与选参与排名；未到期周期仅展示。行情截至美东{end}。</p><a href="skhy_report2_straddle.html">原报告2</a> · <a href="all6_optimization.json">完整结果</a> · <a href="all6_rule_scores.json">全部规则评分</a></header>
<section><h2>最优平仓策略：按已到期周期总净收益排序</h2><p class="note">{e(best['name'])}。每轮1 Call＋1 Put，退出后本轮不重新开仓。股票相对本轮买入价上涨时，用上涨侧组合收益目标；下跌时用下跌侧目标。最高值为当前网格和训练样本内结果，不代表未来最优。</p><div class="cards"><div class="card">{N}个已到期周期净收益<strong>{m(completed_profit)}</strong></div><div class="card">未到期周期当前净估值<strong>{m(ongoing)}</strong><small>截至{end}，未纳入排名</small></div><div class="card">合计已实现＋当前净估值<strong>{m(completed_profit+ongoing)}</strong></div></div><p>{comparison_note}默认展示总净收益最高、按既定排序选出的规则；不同平仓策略的排名与参数见下方。净收益已扣原示例摩擦，不是保证可成交价格。</p></section>
<section><h2>最优策略逐周期明细：买入、卖出与收益</h2>{best_table}<p class="muted">每个周期一条记录，所有时间为美东时间。只有两腿存在信号后的共同成交分钟，才填写“实际模拟卖出”时间；到期结算不冒充主动卖出，仍持仓的周期不填写卖出时间。价格均为每股报价，1张合约乘数100。买入总成本含2%加价和两张合计$1.30佣金；主动卖出净回收含2%减价和$1.30佣金，到期按内在价值结算。净损益＝净回收−买入总成本。</p><a href="best_exit_cycle_details.json">下载最优策略逐轮账本</a></section>
<section><h2>不同策略的全部已到期周期总收益</h2>{comparison}<p class="muted">各类策略都在同一全部已到期周期中独立选择最佳参数，允许费用轮空的类别可能只交易部分轮次；轮空记0收益，表内同时列参与轮数和累计投入。累计买入成本是各次交易投入之和，不是账户初始资金，不年化。每轮固定一组，不复投、不在提前退出后重开本轮。</p><details><summary>展开各类最佳参数</summary>{params}</details></section>
<section><h2>时间递减方案：每天用哪个目标</h2>{schedule_table}<p>周三、周四及到期周五从09:30起切换当天目标，仍每10分钟检查一次。09:30没有已完成的当日行情时，等到符合价格年龄条件的采样点再判断。股票高于本周期实际入场价用上涨侧目标，低于则用下跌侧目标。净收益率＝（模拟卖出净收入−买入总成本）÷买入总成本。</p><p>例如周四，股价在入场价上方时的净收益目标为{n(target(rule['up'],sched['thu']))}%，在入场价下方时为{n(target(rule['down'],sched['thu']))}%。这些较小收益目标已经按示例成本扣费判断，但真实价差与成交延迟仍可能把最终盈利变成亏损。</p><p class="muted">若触发退出但后续缺少两腿共同成交分钟，则继续持有至到期；表中明确标识。不能把该轮利润全部归因于主动止盈。</p></section>
<section><h2>只降低目标，和重新优化初始目标，是两件事</h2><p>固定本次样本内最好的涨跌不同目标规则：{e(d['selected']['asymmetric']['name'])}。只加入不同的时间递减幅度，结果如下：</p>{ablation}<p>保持其他条件不变，各时间递减方案的总收益见上表；避免把重新选择初始参数的效果误认为降低时间目标本身的效果。</p><p>再允许同时重选初始涨跌目标、轮空与止损，各种时间方案在本样本能达到的最好结果：</p>{profile}<p>各类参数都已用最新的完整周期重新选择；这些是样本内比较，不代表未来表现。</p></section>
<section><h2>不同平仓策略的收益曲线与卖出时点</h2><div class="toolbar"><label>策略 <select id="strategy">{options}</select></label><label>对照平仓策略 <select id="compare">{options}</select></label><label>周期 <select id="cycle"></select></label></div><p class="note" id="ruleText"></p><div id="roundTable"></div><p id="roundInfo"></p><div class="legend"><span style="color:#ffd166">金色：对照平仓策略净损益</span><span style="color:#43caaa">绿色：主选平仓策略净损益</span><span style="color:#38bdf8">蓝色：股票涨跌% · 右轴</span></div><div class="chartwrap"><canvas id="chart"></canvas><div id="tip"></div></div><p class="muted">绿色退出后保持已实现模拟收益；轮空为0。两条零值虚线分别对应总收益$0、股票0%。鼠标悬停查看具体数字；时间递减策略还显示当天、当前股价方向对应的退出目标。未到期周期的结果不计入上方总收益。</p></section>
<section><h2>时间衰竭已经体现在期权价格中，不重复扣费</h2><p>长仓期权受时间价值损耗影响，平值期权临近到期时损耗往往更快，但期权市场价同时受股价、隐含波动率等影响，不能把几天的价格下降全部当成Theta。参考 <a href="https://prd-web.optionseducation.org/advancedconcepts/theta">OIC：Theta</a>。</p><p>本回测使用真实历史期权成交价，时间价值变化已包含在收益中；因此不额外每天减一个“时间衰竭成本”，避免重复计算。此次通过降低周三、周四的退出目标应对剩余时间减少，并测试到期前保本/小亏退出。</p>{time_table}<p class="muted">外在价值估计＝100×(Call价＋Put价)−100×|股价−行权价|。每个周三、周四选两腿价格年龄≤10分钟、最接近10:00的可用观察点，实际时间列出。两腿与股票并非同秒报价，出现负外在价值表示成交价不同步或数据问题，不是负Theta，也不裁剪为0。表中差额只作观察，不等于纯时间损耗、没有作为选参信号。</p></section>
<section><h2>成本与成交条件仍会改变结果</h2>{stress}<p>标准口径：买入两腿各加2%，卖出各减2%；每张每次$0.65佣金。到期按内在价值结算，无卖出摩擦。信号只用当时已完成的当日分钟，Call和Put价格年龄≤10分钟；信号后至少一分钟，取两腿首个共同成交分钟开盘价模拟退出。若无共同分钟，则保留到期或最新估值。这不是历史Bid/Ask，不保证实际能按该价卖出。</p><p>轮空费用比在周五10:00用已完成的最新两腿价格除以参考股价计算，价格年龄≤30分钟；不是用稍后实际入场价格倒推。过滤上限也已随最新样本重新选择，实际轮空周期见明细。表中总收益已扣示例成本，不代表券商实际收费。</p></section>
<section><h2>复现与口径</h2><p>全部已到期周期全部训练，不再展示旧版的三轮训练／两轮验证结论。所有策略只在开仓时做轮空判断，在盘中使用过去可知信息；未结束周期不参与选参。总收益优先，要求至少两轮成交；并列时按最差轮次、简单条件及固定编号排序。</p><p><a href="analyze_all6.py">分析程序</a> · <a href="build_all6.py">报告生成器</a> · <a href="README_all6.md">复现说明</a>。报告1保留；报告2基础账本同步刷新；旧版报告3已备份。本次刷新股票及新增／未完整周期的Call、Put行情，已结束旧周期复用原数据；所有已到期周期全部用于训练；原行情及报告已备份。</p></section>'''
css='''*{box-sizing:border-box}body{margin:0;background:#0e121b;color:#e7edf7;font:14px/1.8 system-ui,-apple-system,"PingFang SC",sans-serif;color-scheme:dark}main{max-width:1450px;margin:auto;padding:32px 24px}h1{font-size:31px;margin:8px 0}h2{font-size:21px;margin-top:0}.eyebrow{color:#f5ca75;letter-spacing:2px}.muted,small{color:#9cabbe}section{background:#171e2c;border:1px solid #2b3546;border-radius:14px;padding:24px;margin:22px 0}a{color:#79b7ff}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{background:#202a3b;padding:17px;border-radius:10px}.card strong{display:block;font-size:28px;color:#f5ca75}.note{border-left:3px solid #f5ca75;background:#f5ca7509;padding:14px}.scroll{overflow:auto;max-height:520px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #2b3546;padding:11px;text-align:right;white-space:nowrap}th{background:#202a3b;color:#9cabbe;position:sticky;top:0}td:first-child,th:first-child{text-align:left}td:first-child{white-space:normal;min-width:115px}.toolbar,.legend{display:flex;gap:20px;flex-wrap:wrap;margin:14px 0}select{padding:9px;background:#202c3e;color:#e7edf7;border:1px solid #3b4960;border-radius:6px;font:inherit}.chartwrap{position:relative}canvas{width:100%;height:450px;display:block}#tip{position:absolute;display:none;pointer-events:none;background:#080e18f5;border:1px solid #738398;padding:12px;border-radius:9px;z-index:2;max-width:300px;font-size:12px}summary{cursor:pointer;color:#79b7ff}@media(max-width:750px){main{padding:15px}.cards{grid-template-columns:1fr}section{padding:16px}h1{font-size:24px}}'''
js=(P/'all6_chart.js').read_text()
result='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY报告3：全部已到期周期全量训练与时间递减退出</title><style>'+css+'</style><main>'+body+'</main><script>const D='+json.dumps(d,ensure_ascii=False,allow_nan=False).replace('</','<\\/')+';\n'+js+'</script></html>'
for name in ['skhy_report3_all6_time_decay.html','skhy_report3_exit_optimization.html']:(P/name).write_text(result)
print('Generated all-six training report')

md=['# 平仓策略比较与最优策略逐轮明细','', '[打开交互报告](skhy_report3_all6_time_decay.html)','', best['name'],'',f"已到期周期总净收益：{m(completed_profit)}；未到期周期净估值：{m(ongoing)}。示例交易摩擦口径不变。",'', '| 周期 | 状态 | 实际模拟卖出ET | 结算或估值ET | 净损益 |','|---|---|---|---|---:|']
for row in ledger:md.append('| '+' | '.join([row['cycle'],row['status'],stamp(row['sell_time']),stamp(row['settlement_or_mark_time']),m(row['net'])])+' |')
md+=['','到期结算和仍持仓估值不是主动卖出。完整入场、触发、卖价、净回收金额及原因见HTML与best_exit_cycle_details.json。最高策略是当前样本内排名，不保证未来表现。']
(P/'report3_summary.md').write_text('\n'.join(md))
