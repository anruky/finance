# -*- coding: utf-8 -*-
import json,ast
from pathlib import Path
p=Path(__file__).parent;d=json.loads((p/'exit_optimization_results.json').read_text())
parent=p.parent if (p.parent/'build_rotation_report.py').exists() else Path('/Users/gavinz/git/finance/hedge_codex/straddle/rotation')
tree=ast.parse((parent/'build_rotation_report.py').read_text());values={}
for node in tree.body:
 if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant):
  for name in node.targets:
   if isinstance(name,ast.Name):values[name.id]=node.value.value
css=values['css'];chart=values['js'].split('let setups={};',1)[1].split('function drawEquity()',1)[0]
for r in d['results']:r['id']=r['rule']['id'];r['name']=r['rule']['name']
groups={}
for r in d['results']:
 key='none' if r['rule']['days'] is None else str(r['rule']['days'])+'_'+r['rule']['clock']
 if key not in groups or (r['stats']['total'],-r['stats']['drawdown'])>(groups[key]['stats']['total'],-groups[key]['stats']['drawdown']):groups[key]=r
d['groups']={k:r['id'] for k,r in groups.items()};d['chart_ids']=list(dict.fromkeys(['E00']+[r['id'] for r in groups.values()]))
body='''<main><div class="muted">SKHY · 报告5 · 固定选约，优化退出</div><h1>平方根时间选约＋强制平仓轮动</h1><p id="asof"></p><div class="cards" id="cards"></div>
<section><h2>当前样本内的最优方案</h2><div id="best"></div><p class="note">“最优”仅指本报告44组规则在同一历史区间内合计毛收益最高，收益包含期末持仓估值。全部历史用于比较，没有独立验证集；平仓参数和强平时点都可能过拟合。最大回撤由可用成交估值点计算，缺价期间可能低估真实回撤。</p></section>
<section><h2>只改变强平时间：原止盈规则保持不变</h2><p>原规则为涨侧150%／跌侧10%，到期周三、周四、周五分别乘75%、50%、25%，不设止损。先看加入提前3天或2天强平带来的变化。选约评分不变，但进入强平窗口的期限会被排除，因此后续轮动路径也会随之改变。</p><div class="scroll" id="ablation"></div></section>
<section><h2>每类强平时间的最优组合</h2><p>这一表在各类强平时间内部，同时选择止盈与止损参数，因此与上一表的“只改强平时间”不同。</p><div class="scroll" id="groups"></div></section>
<section><h2>累计毛收益曲线：原规则与各类最优</h2><div class="legend" id="legend"></div><div class="chart"><canvas id="equity"></canvas><div class="tip" id="equitytip"></div></div></section>
<section><h2>全部44组平仓策略</h2><p>40组＝4种涨跌目标×2种止损设置×5种强平时点；另加4组仅按时间强平的对照。止盈目标为组合相对本次期权成本的盈利百分比，涨跌方向按股价相对本次入场价判断。所有开仓仍由同一费用／√剩余天数规则决定。</p><div class="scroll" id="ranking"></div></section>
<section><h2>逐笔买卖：时间、股价、费用和盈亏</h2><div class="toolbar"><label>平仓策略 <select id="policy"></select></label></div><div id="ruletext" class="note"></div><div class="scroll" id="ledger"></div><p class="muted">美东时间；每次1 Call＋1 Put，每张100股。到期结算与期末估值分别标注。止盈或强平只是信号，实际成交可能延迟，盈亏不一定等于目标。</p></section>
<section><h2>单笔持仓曲线</h2><div class="toolbar"><label>交易 <select id="trade"></select></label></div><div id="tradeinfo"></div><div class="legend"><span style="color:#58dcc0">组合毛收益$ · 左轴</span><span style="color:#54afff">股票涨跌% · 右轴</span></div><div class="chart"><canvas id="tradechart"></canvas><div class="tip" id="tradetip"></div></div></section>
<section><h2>强平是否按时执行</h2><div class="scroll" id="forced"></div><p class="muted">提前3天＝周二，提前2天＝周三，按自然日和美东时间计算。到时即触发，不要求组合盈利，也不要求当天仍有足够新鲜的估值；但卖出仍须有后续实际共同成交分钟。表中列出到截止时仍未退出的交易，包括较早触发止盈／止损却延迟成交的情况。不能把触发时间当作实际卖出时间。</p></section>
<section><h2>重新开仓与轮空</h2><div class="scroll" id="decisions"></div><p>先剔除已经进入强平窗口的到期日，再在其余候选中比较（Call＋Put报价）／股价／√剩余自然日。权利金超过股价12%则轮空，实际模拟入场也检查12%上限。被强平的近期期权不会立即买回。</p></section>
<section><h2>固定的执行口径</h2><p>每次仅持有一组期权。每次平仓后，下一个10分钟检查点且不早于10:00重新评估；15:30后顺延下一交易日。没有盈利目标的“仅按时间强平”方案也同样轮动。开仓失败或费用过贵则下一交易日10:00再评估。买下周合约时，只在其到期周降低止盈目标。</p><p>选约取当时已完成分钟价；两腿价格年龄≤10分钟，同行权价、同到期日，选择最接近平值合约。若候选暂缺价格，固定最初评估时的行权价继续等待当日后续检查点。周五不新买0DTE，只考虑下周五。所有交易从信号至少一分钟后寻找两腿与股票的首个共同成交分钟，按分钟开盘价估算；不保证实盘可以按此成交。强平优先于同一时点的止损和止盈。</p><p>期末仍持仓以当天两腿最后成交价估值，详情保留价格年龄。总收益为已实现＋未实现毛收益，不扣交易费用，不计算年化。最低现金需求允许盈利再投入和追加资金；累计权利金是多次周转总额。</p><p>强平是控制剩余持有时间的一种规则，不意味着提前2天或3天就一定划算。时间衰减并非线性，成交价中已包含时间价值，不另外扣Theta。参考 <a href="https://www.optionseducation.org/advancedconcepts/theta">OIC：Theta</a>。</p><p><a href="exit_optimization_results.json">全部计算结果</a> · <a href="optimize_rotation_exits.py">计算程序</a> · <a href="README.md">复现说明</a> · <a href="../skhy_report4_rotation.html">报告4</a></p></section></main>'''
js=r'''
const $=id=>document.getElementById(id),fmt=(v,n=2)=>v==null?'—':Number(v).toLocaleString('en-US',{minimumFractionDigits:n,maximumFractionDigits:n}),money=v=>'$'+fmt(v),dt=s=>s?s.slice(5,16).replace('T',' '):'—',pc=v=>fmt(v)+'%',color=v=>v>=0?'pos':'neg';
const colors=['#ffd166','#58dcc0','#54afff','#e69dff','#ff8d70','#d4e46b'];const table=(h,rs)=>'<table><thead><tr>'+h.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+rs.map(r=>'<tr>'+r.map(x=>'<td>'+x+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const best=D.results.find(r=>r.id===D.best),base=D.results.find(r=>r.id==='E00'),sorted=[...D.results].sort((a,b)=>b.stats.total-a.stats.total||a.stats.drawdown-b.stats.drawdown);
const forcedBest=sorted.find(r=>r.rule.days!=null);
const force=r=>r.days==null?'不强平':`到期前${r.days}天 ${r.clock}`;
const ruletext=r=>`${r.up==null?'没有止盈目标':`初始涨侧盈利${r.up}%／跌侧盈利${r.down}%，到期周三×75%、周四×50%、周五×25%`}；${r.stop==null?'不设止损':`亏损${r.stop}%触发止损`}；${force(r)}。`;
$('asof').textContent=`${D.start} 至 ${D.end}｜仅保留费用／√剩余天数选约｜12%费用上限｜${D.rules_count}组退出规则`;
$('cards').innerHTML=[['最高合计毛收益',money(best.stats.total)],['比原规则增加',money(best.stats.total-base.stats.total)],['已实现／未实现',money(best.stats.realized)+' / '+money(best.stats.floating)],['观察点最大回撤',money(best.stats.drawdown)]].map(([a,b])=>`<div class="card">${a}<strong>${b}</strong></div>`).join('');
$('best').innerHTML=`<p><strong>${ruletext(best.rule)}</strong></p><p>共开仓${best.stats.positions}笔，已平仓${best.stats.closed}笔，其中${best.stats.wins}笔盈利；强平实际成交${best.stats.forced}笔。合计毛收益${money(best.stats.total)}，原规则为${money(base.stats.total)}。最大单笔亏损${money(Math.max(0,-best.stats.worst))}，最低现金需求${money(best.stats.required_cash)}。</p><p>${best.rule.days==null?'这次最高收益方案不需要强平，不能因为临近到期衰减快就默认提前平仓一定更好。':`周五到期时，按本方案最迟在${best.rule.days===3?'周二':'周三'}${best.rule.clock}发出强平信号；随后重新选约，已到强平窗口的本周期权不再买入。`}</p>`;
$('best').innerHTML+=`<p><strong>若必须强平：</strong>${forcedBest.id} ${ruletext(forcedBest.rule)} 合计毛收益${money(forcedBest.stats.total)}，比原规则少${money(base.stats.total-forcedBest.stats.total)}；最大单笔亏损${money(Math.max(0,-forcedBest.stats.worst))}，观察点回撤${money(forcedBest.stats.drawdown)}。减少单笔损失不等于同等幅度减少账户回撤。</p>`;
const heads=['编号','涨／跌初始目标','止损','强平时间','合计毛收益','已实现','期末浮盈亏','相对原规则','开仓／平仓','强平成交','最大回撤','最差单笔','累计权利金','最低现金需求'];
const row=r=>{let s=r.stats,q=r.rule;return[r.id,q.up==null?'仅按时间':q.up+'% / '+q.down+'%',q.stop==null?'无':q.stop+'%',force(q),`<b class="${color(s.total)}">${money(s.total)}</b>`,money(s.realized),money(s.floating),money(s.total-base.stats.total),s.positions+' / '+s.closed,s.forced,money(s.drawdown),money(s.worst),money(s.premium_turnover),money(s.required_cash)]};
$('ablation').innerHTML=table(heads,D.results.filter(r=>r.rule.up===150&&r.rule.down===10&&r.rule.stop==null).map(row));$('groups').innerHTML=table(heads,Object.values(D.groups).map(id=>row(D.results.find(r=>r.id===id))));$('ranking').innerHTML=table(heads,sorted.map(row));
const curves=D.chart_ids.map(id=>D.results.find(r=>r.id===id));$('legend').innerHTML=curves.map((r,i)=>`<span style="color:${colors[i]}">${r.id} ${force(r.rule)}</span>`).join('');
$('policy').innerHTML=sorted.map(r=>`<option value="${r.id}">${r.id} ${r.name} · ${money(r.stats.total)}</option>`).join('');$('policy').value=D.best;let current=best,trade;
function choose(){current=D.results.find(r=>r.id===$('policy').value);$('ruletext').textContent=ruletext(current.rule);$('ledger').innerHTML=table(['笔次','买入时间','买入股价／K','到期日','计划强平','信号时间','卖出／估值时间','退出股价','Call买→卖','Put买→卖','支出','回收／估值','毛盈亏','收益率','状态／原因'],current.trades.map(t=>[t.id,dt(t.entry.time),fmt(t.entry.stock)+' / '+fmt(t.contract.strike),t.contract.expiry,dt(t.deadline),dt(t.signal?.time),dt(t.exit.time),fmt(t.exit.stock),fmt(t.entry.call)+' → '+fmt(t.exit.call),fmt(t.entry.put)+' → '+fmt(t.exit.put),money(t.entry.value),money(t.exit.value),`<b class="${color(t.gross)}">${money(t.gross)}</b>`,pc(t.roi),t.status+' / '+(t.signal?.reason||'—')]));
$('forced').innerHTML=table(['笔次','到期日','计划强平','实际信号','退出原因','实际卖出／结算','延迟分钟','状态','毛盈亏'],current.trades.filter(t=>t.deadline&&Date.parse(t.exit.time)>=Date.parse(t.deadline)).map(t=>[t.id,t.contract.expiry,dt(t.deadline),dt(t.signal?.time),t.signal?.reason||'未触发成交',dt(t.exit.time),t.status==='模拟平仓'?fmt((Date.parse(t.exit.time)-Date.parse(t.deadline))/60000,0):'未模拟成交',t.status,money(t.gross)]));
$('decisions').innerHTML=table(['观察时间','选择结果','排除的到期日','原因'],current.decisions.map(x=>[dt(x.time),x.action+(x.expiry?' '+x.expiry:''),x.excluded_expiries.join('、')||'—',x.reason||'合格候选中费用／√天数较低']));$('trade').innerHTML=current.trades.map((t,i)=>`<option value="${i}">第${t.id}笔 ${dt(t.entry.time)} → ${dt(t.exit.time)} · ${money(t.gross)}</option>`).join('');chooseTrade()}
function chooseTrade(){trade=current.trades[+$('trade').value||0];if(!trade)return;let t=trade;$('tradeinfo').innerHTML=`<p>行权价${fmt(t.contract.strike)}，到期${t.contract.expiry}；入场股价${money(t.entry.stock)}，退出／估值股价${money(t.exit.stock)}。Call盈亏${money(t.call_pnl)}，Put盈亏${money(t.put_pnl)}，组合${money(t.gross)}。${t.exit.ages?'期末Call／Put价格年龄 '+t.exit.ages.call+'／'+t.exit.ages.put+'分钟。':''}</p>`;drawTrade()}
let setups={};
'''+chart+r'''
function drawEquity(){chart('equity','equitytip',curves.map((r,i)=>({name:r.id+' '+force(r.rule),color:colors[i],points:r.equity})))}
function drawTrade(){if(!trade)return;let t=trade,pts=[{time:t.entry.time,pnl:0,stock:t.entry.stock},...t.curve,{time:t.exit.time,pnl:t.gross,stock:t.exit.stock}];chart('tradechart','tradetip',[{name:'组合毛收益',color:'#58dcc0',points:pts.map(p=>({time:p.time,value:p.pnl}))},{name:'股票涨跌',color:'#54afff',axis:1,points:pts.map(p=>({time:p.time,value:(p.stock/t.entry.stock-1)*100}))}],true)}
$('policy').onchange=choose;$('trade').onchange=chooseTrade;choose();drawEquity();window.addEventListener('resize',()=>{drawEquity();drawTrade()});
'''
result='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SKHY报告5：轮动平仓策略优化</title><style>'+css+'</style></head><body>'+body+'<script>const D='+json.dumps(d,ensure_ascii=False,allow_nan=False).replace('</','<\\/')+';\n'+js+'</script></body></html>'
(p/'skhy_report5_exit_optimization.html').write_text(result);print('Built report5; best',d['best'])
