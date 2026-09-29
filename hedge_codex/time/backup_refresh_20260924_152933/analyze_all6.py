"""Causal ten-minute signals, later shared-minute execution; small-sample exploratory study."""
import json,math,statistics,bisect,hashlib
from pathlib import Path
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
OUT=Path(__file__).parent;ROOT=OUT/'report3_inputs';ET=ZoneInfo('America/New_York')
data=json.loads((ROOT/'skhy_report2_cycles.json').read_text());raw=json.loads((ROOT/'report2_market_data.json').read_text());cycles=data['cycles']
def bars(t):return {datetime.fromtimestamp(b['t']/1000,ET):b for b in raw[t+'_minute'] if b.get('v',0)>0 and time(9,30)<=datetime.fromtimestamp(b['t']/1000,ET).time()<time(16)}
stock=bars('SKHY');history_path=OUT/'prior_stock_closes.json'
if history_path.exists():daily=json.loads(history_path.read_text())
else:
 earlier=json.loads(Path('/Users/gavinz/git/finance/hedge_codex/sk/data/SKHY_intraday.json').read_text())['stock'];daily={r[0]:r[4] for r in earlier};history_path.write_text(json.dumps(daily,indent=2))
for b in raw['SKHY_day']:daily[datetime.fromtimestamp(b['t']/1000,ET).date().isoformat()]=b['c']
features=[];prepared=[]
for c in cycles:
 cm,pm=bars(c['call_ticker']),bars(c['ticker']);decision=datetime.fromisoformat(c['start']).replace(tzinfo=ET,hour=10)
 def latest(m):
  ks=[k for k in m if k.date()==decision.date() and k+timedelta(minutes=1)<=decision]
  if not ks:return None,None
  k=max(ks);return m[k]['c'],(decision-k).total_seconds()/60
 cp,ca=latest(cm);pp,pa=latest(pm);sp,sa=latest(stock)
 closes=[v for k,v in sorted(daily.items()) if k<c['start']][-11:];rets=[math.log(b/a) for a,b in zip(closes,closes[1:])];rv=statistics.stdev(rets)*math.sqrt(5)*100 if len(rets)>=10 else None
 reliable=all(v is not None for v in [cp,pp,sp,ca,pa]) and max(ca,pa)<=30
 estimate=(cp+pp)/sp*100 if reliable else None
 f=dict(id=c['id'],premium_pct=100*c['capital']/(100*c['stock_entry']),pretrade_pct=estimate,pretrade_call_age=ca,pretrade_put_age=pa,rv5_pct=rv,expensiveness=estimate/rv if estimate is not None and rv else None,break_even_up_pct=(c['strike']+c['capital']/100)/c['stock_entry']*100-100,break_even_down_pct=(c['strike']-c['capital']/100)/c['stock_entry']*100-100)
 features.append(f)
 common=sorted(set(cm)&set(pm));vals=[100*(cm[t]['o']+pm[t]['o']) for t in common]
 rows=[]
 for p in c['points']:
  t=datetime.fromisoformat(p['et']);fresh=p['kind']=='minute' and p['pnl'] is not None and max(p['call_age'],p['put_age'])<=10
  if p['kind']!='minute':continue
  i=bisect.bisect_left(common,t+timedelta(minutes=1));fill=None
  if i<len(common):fill=dict(et=common[i].isoformat(),value=vals[i],delay=(common[i]-t).total_seconds()/60,call=cm[common[i]]['o'],put=pm[common[i]]['o'])
  rows.append(dict(p=p,t=t,fresh=fresh,fill=fill,day=(t.date()-datetime.fromisoformat(c['start']).date()).days))
 prepared.append(dict(c=c,f=f,rows=rows))

def rule_name(r):
 gate='不轮空' if not r.get('gate') else ('10:00权利金/股价≤'+str(r['gate'][1])+'%' if r['gate'][0]=='premium' else '10:00权利金比/历史5日波动≤'+str(r['gate'][1]))
 if r['type']=='hold':s='持有到期'
 elif r['type']=='decay':s=f"时间递减：初始涨{r['up']}%/跌{r['down']}%，{r['schedule']['name']}"
 elif r['type']=='target':s=f"涨侧盈利{r['up']}% / 跌侧盈利{r['down']}%止盈"
 elif r['type']=='move':s=f"股价涨{r['up']}% / 跌{r['down']}%且净盈利离场"
 else:s=f"涨侧盈利{r['up']}% / 跌侧盈利{r['down']}%后启动回撤{r['trail']}个百分点止盈"
 return s+('；止损'+str(r['stop'])+'%' if r.get('stop') else '')+('；'+{4:'周二',5:'周三',6:'周四'}[r['cut']]+'15:30离场' if r.get('cut') else '')+'；'+gate

def evaluate(pre,r,slip=.02,age_limit=10,extra_delay=1):
 c,f=pre['c'],pre['f'];cost=c['capital']*(1+slip)+1.30;gate=r.get('gate')
 if gate:
  metric=f['pretrade_pct'] if gate[0]=='premium' else f['expensiveness']
  if metric is None or metric>gate[1]:return dict(id=c['id'],skipped=True,pnl=0.,gross=0.,cost=0.,roi=None,reason='入场报价不足' if metric is None else '权利金过贵',signal=None,exit=None,closed=True)
 def result(value,closed,exit,reason,signal=None,delay=None,fill=None):
  fee=0 if reason=='到期结算' else 1.30
  val=value*(1-slip) if reason!='到期结算' else value
  pnl=val-fee-cost
  return dict(id=c['id'],skipped=False,pnl=pnl,gross=value-c['capital'],cost=cost,roi=100*pnl/cost,reason=reason,signal=signal,exit=exit,delay=delay,closed=closed,exit_value=value,fill=fill)
 peak=-1e9;armed=False;trigger=None
 for row in pre['rows']:
  p=row['p'];t=row['t'];fresh=p['pnl'] is not None and max(p['call_age'],p['put_age'])<=age_limit
  timed=r.get('cut') and row['day']>=r['cut'] and t.time()>=time(15,30)
  if r['type']=='hold':continue
  reason=None
  if fresh:
   roi=100*((c['capital']+p['pnl'])*(1-slip)-1.3-cost)/cost;peak=max(peak,roi);direction='up' if p['stock_return_pct']>=0 else 'down';target=r[direction]
   if r['type']=='decay':
    stage='fri' if row['day']>=7 else 'thu' if row['day']>=6 else 'wed' if row['day']>=5 else None
    if stage:
     adjustment=r['schedule'][stage];target=target*adjustment['factor'] if 'factor' in adjustment else adjustment['absolute']
   if r.get('stop') and roi<=-r['stop']:reason='组合止损'
   elif r['type'] in ('target','decay') and roi>=target:reason=('上涨' if direction=='up' else '下跌')+'侧'+('时间递减退出' if r['type']=='decay' else '止盈')
   elif r['type']=='move' and roi>0 and ((direction=='up' and p['stock_return_pct']>=r['up']) or (direction=='down' and p['stock_return_pct']<=-r['down'])):reason='股价幅度触发且组合盈利'
   elif r['type']=='trail':
    if roi>=target:armed=True
    if armed and peak-roi>=r['trail']:reason='收益回撤止盈'
  if reason is None and timed:reason='时间退出'
  if reason:
   trigger=dict(et=p['et'],reason=reason,signal_roi=roi if fresh else None,stock_return=p['stock_return_pct']);fill=row['fill']
   if extra_delay>1:
    fill=next((rr['fill'] for rr in pre['rows'] if rr['t']>=t+timedelta(minutes=extra_delay-1) and rr['fill']),None)
   if fill:return result(fill['value'],True,fill['et'],reason,p['et'],fill['delay'] if extra_delay==1 else (datetime.fromisoformat(fill['et'])-t).total_seconds()/60,fill)
   break
 final=c['final'];value=c['capital']+final['pnl'];return result(value,c['completed'],final['et'],'到期结算' if c['completed'] else ('触发后无共同成交分钟，仍持仓' if trigger else '未到期估值'),trigger['et'] if trigger else None) | dict(unfilled_signal=trigger)

rules=[dict(id='hold',type='hold',gate=None)]
for up in [5,10,20,40,60,100,150]:
 for down in [2,5,10,20,40,60,100]:
  for stop in [None,20,35,50]:
   for cut in [None,4,5,6]:rules.append(dict(type='target',up=up,down=down,stop=stop,cut=cut,gate=None))
for up in [10,20,40,60]:
 for down in [5,10,20,40]:
  for trail in [5,10,20]:
   for stop in [None,35]:rules.append(dict(type='trail',up=up,down=down,trail=trail,stop=stop,cut=None,gate=None))
for up in [5,10,15,20]:
 for down in [3,5,8,10]:
  for stop in [None,35]:rules.append(dict(type='move',up=up,down=down,stop=stop,cut=None,gate=None))
base_rules=list(rules)
for r in base_rules:
 for gate in [('premium',8),('premium',10),('premium',12),('premium',14),('rv',.75),('rv',1),('rv',1.25),('rv',1.5)]:rules.append(dict(r,gate=gate))
for i,r in enumerate(rules):r['id']=f'R{i:04d}';r['name']=rule_name(r)
def stats(rr):
 pnl=[x['pnl'] for x in rr];return dict(pnl=sum(pnl),wins=sum(x>0 for x in pnl),trades=sum(not x['skipped'] for x in rr),cost=sum(x['cost'] for x in rr),worst=min(pnl) if pnl else 0,loss=sum(min(x,0) for x in pnl))
def choose(indices,subset=None):
 eligible=[]
 for r in subset or rules:
  st=stats([results[r['id']][i] for i in indices])
  if st['trades']<min(2,len(indices)):continue
  # Fixed cash P&L per one straddle; deterministic simplicity tie-break.
  eligible.append((st['pnl'],st['worst'],-int(bool(r.get('gate'))),-int(r['type']=='trail'),-int(r['id'][1:]),r))
 return max(eligible,key=lambda x:x[:-1])[-1]

schedules=[
 dict(name='周三75%／周四50%／到期日25%原目标',wed={'factor':.75},thu={'factor':.5},fri={'factor':.25}),
 dict(name='周三50%／周四25%／到期日10%原目标',wed={'factor':.5},thu={'factor':.25},fri={'factor':.1}),
 dict(name='周三25%／周四10%／到期日保本',wed={'factor':.25},thu={'factor':.1},fri={'absolute':0}),
 dict(name='周三50%原目标／周四起保本',wed={'factor':.5},thu={'absolute':0},fri={'absolute':0}),
 dict(name='周三起保本',wed={'absolute':0},thu={'absolute':0},fri={'absolute':0}),
 dict(name='周三50%原目标／周四≥−10%／到期日≥−20%',wed={'factor':.5},thu={'absolute':-10},fri={'absolute':-20})]
for up in [5,10,20,40,60,100,150]:
 for down in [2,5,10,20,40,60,100]:
  for schedule in schedules:
   for stop in [None,20,35,50]:
    for cut in [None,6]:
     for gate in [None,('premium',8),('premium',10),('premium',12),('premium',14)]:rules.append(dict(type='decay',up=up,down=down,schedule=schedule,stop=stop,cut=cut,gate=gate))
for i,r in enumerate(rules):r['id']=f'A{i:05d}';r['name']=rule_name(r)
completed=[i for i,c in enumerate(cycles) if c['completed']]
assert completed==list(range(6)), 'This report is explicitly a six-completed-cycle study'
print('All-six training; rules:',len(rules),flush=True)
results={r['id']:[evaluate(p,r) for p in prepared] for r in rules}
groups={
 'baseline':lambda r:r['type']=='hold' and not r['gate'],
 'hold_gate':lambda r:r['type']=='hold',
 'symmetric':lambda r:r['type']=='target' and r['up']==r['down'] and not r.get('cut'),
 'asymmetric':lambda r:r['type']=='target' and r['up']!=r['down'] and not r.get('cut'),
 'timed':lambda r:r['type']=='target' and r.get('cut'),
 'trailing':lambda r:r['type']=='trail',
 'stock_move':lambda r:r['type']=='move',
 'decay_symmetric':lambda r:r['type']=='decay' and r['up']==r['down'],
 'decay_asymmetric':lambda r:r['type']=='decay' and r['up']!=r['down'],
 'decay_no_gate':lambda r:r['type']=='decay' and not r['gate'],
 'all_best':lambda r:True}
selected={k:choose(completed,[r for r in rules if match(r)]) for k,match in groups.items()}
profiles=[]
for schedule in schedules:
 r=choose(completed,[r for r in rules if r['type']=='decay' and r['schedule']['name']==schedule['name']]);profiles.append(dict(schedule=schedule,rule=r,stats=stats(results[r['id']][:6]),results=results[r['id']]))
# Isolate time lowering: change schedule only, retain fixed best rule's entry gate and risk parameters.
fixed=selected['asymmetric'];ablation=[]
for schedule in schedules:
 r=dict(fixed,type='decay',schedule=schedule);r['name']=rule_name(r);rr=[evaluate(p,r) for p in prepared];ablation.append(dict(rule=r,stats=stats(rr[:6]),results=rr))
selected_results={k:results[r['id']] for k,r in selected.items()}
summaries=[dict(rule=r,full=stats(results[r['id']][:6])) for r in rules]
leader=selected['all_best'];leader_pnl=stats(results[leader['id']][:6])['pnl'];ties=[r for r in rules if abs(stats(results[r['id']][:6])['pnl']-leader_pnl)<1e-7]
stress=[]
for key in ['asymmetric','decay_asymmetric','all_best']:
 for slip,age in [(0,10),(.01,10),(.02,10),(.05,10),(.02,5),(.02,30)]:
  rr=[evaluate(p,selected[key],slip,age) for p in prepared];stress.append(dict(key=key,slip=slip,age=age,stats=stats(rr[:6]),results=rr))
# Time value is observed option market price minus contemporaneous intrinsic value, not an extra cost to deduct.
time_value=[]
for c in cycles:
 rows=[]
 for day in sorted(set(p['day'] for p in c['points'])):
  eligible=[p for p in c['points'] if p['day']==day and p['kind']=='minute' and p['pnl'] is not None and p['stock'] is not None and max(p['call_age'],p['put_age'])<=10]
  if not eligible:continue
  point=min(eligible,key=lambda p:abs(int(p['et'][11:13])*60+int(p['et'][14:16])-600));value=100*(point['call']+point['put']);intrinsic=100*abs(point['stock']-c['strike'])
  rows.append(dict(et=point['et'],value=value,intrinsic=intrinsic,extrinsic=value-intrinsic,call_age=point['call_age'],put_age=point['put_age']))
 time_value.append(dict(id=c['id'],entry_extrinsic=c['capital']-100*abs(c['stock_entry']-c['strike']),rows=rows))
payload=dict(metadata=data['metadata'],cycles=cycles,features=features,selected=selected,selected_results=selected_results,comparison={k:stats(v[:6]) for k,v in selected_results.items()},rules_count=len(rules),training_ids=completed,validation_ids=[],profiles=profiles,ablation=ablation,stress=stress,time_value=time_value,ties_count=len(ties),ties=ties[:30],ranking=sorted(summaries,key=lambda x:x['full']['pnl'],reverse=True)[:30],input_hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['skhy_report2_cycles.json','report2_market_data.json']})
(OUT/'all6_optimization.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
(OUT/'all6_rule_scores.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2))
for k,r in selected.items():print(k,r['name'],payload['comparison'][k],flush=True)
print('Equivalent maximum rules:',len(ties),flush=True)
