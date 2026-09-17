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
   if r.get('stop') and roi<=-r['stop']:reason='组合止损'
   elif r['type']=='target' and roi>=target:reason=('上涨' if direction=='up' else '下跌')+'侧止盈'
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
print('Rules:',len(rules),flush=True)
results={r['id']:[evaluate(p,r) for p in prepared] for r in rules}
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
train=[0,1,2];test=[4,5];completed=list(range(6));best_train=choose(train);best_full=choose(completed);best_no_gate=choose(train,[r for r in rules if not r['gate']]);symmetric=choose(train,[r for r in rules if r['type']=='target' and r['up']==r['down'] and not r['gate']]);wf=[]
# Prior cycle expires Friday16:00, so at next Friday10:00 it is NOT yet completed.
for i in range(3,7):
 known=[j for j in range(i) if cycles[j]['expiry']<cycles[i]['start']]
 r=choose(known);wf.append(dict(cycle=cycles[i]['id'],training=[cycles[j]['id'] for j in known],rule=r,result=results[r['id']][i]))
peaks=[]
for pre in prepared:
 c=pre['c'];allp=[p for p in c['points'] if p['pnl'] is not None];fresh=[r['p'] for r in pre['rows'] if r['fresh']];best=max(allp,key=lambda x:x['pnl']);bf=max(fresh,key=lambda x:x['pnl']);cost=c['capital']*1.02+1.3
 peaks.append(dict(id=c['id'],gross_peak=best['pnl'],peak_time=best['et'],fresh_peak=bf['pnl'],fresh_peak_time=bf['et'],fresh_peak_net=(c['capital']+bf['pnl'])*.98-1.3-cost,final=c['final']['pnl']))
selected={'baseline':rules[0],'train_selected':best_train,'full_sample_best':best_full,'no_gate':best_no_gate,'symmetric':symmetric}
payload=dict(metadata=data['metadata'],features=features,peaks=peaks,rules_count=len(rules),selected=selected,selected_results={k:results[r['id']] for k,r in selected.items()},walk_forward=wf,cycles=cycles,train_ids=train,test_ids=test,ranking=[dict(rule=r,train=stats(results[r['id']][:3]),test=stats([results[r['id']][i] for i in test]),full=stats(results[r['id']][:6])) for r in sorted(rules,key=lambda r:stats(results[r['id']][:6])['pnl'],reverse=True)[:20]],stress=[dict(slip=slip,age_limit=age,results=[evaluate(p,best_train,slip,age) for p in prepared]) for slip,age in [(0,10),(.01,10),(.02,10),(.05,10),(.02,5),(.02,30)]],gates=[dict(rule=r,stats=stats(results[r['id']][:6]),results=results[r['id']]) for r in rules if r['type']=='hold'],hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['skhy_report2_cycles.json','report2_market_data.json']})
(OUT/'exit_optimization.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
(OUT/'rule_search_summary.json').write_text(json.dumps([dict(rule=r,train=stats(results[r['id']][:3]),test=stats([results[r['id']][i] for i in test]),full=stats(results[r['id']][:6])) for r in rules],ensure_ascii=False,indent=2))
for k,r in selected.items():print(k,r['name'],stats(results[r['id']][:3]),stats([results[r['id']][i] for i in test]),flush=True)
print('features',features,flush=True)
