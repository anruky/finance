import json,copy
from pathlib import Path
from datetime import datetime,timedelta
P=Path(__file__).parent;d=json.loads((P/'all6_optimization.json').read_text());ns={'__file__':str(P/'analyze_all6.py')};exec(compile((P/'analyze_all6.py').read_text().split("rules=[dict(id='hold'")[0],'engine','exec'),ns)
assert d['training_ids']==list(range(6)) and d['validation_ids']==[]
assert len([c for c in d['cycles'] if c['completed']])==6
for key,rr in d['selected_results'].items():
 assert abs(sum(r['pnl'] for r in rr[:6])-d['comparison'][key]['pnl'])<1e-7
 for c,r in zip(d['cycles'],rr):
  if r['skipped']:assert r['pnl']==r['cost']==0;continue
  assert abs(r['cost']-c['capital']*1.02-1.3)<1e-7
  expected=r['exit_value']-r['cost'] if r['reason']=='到期结算' else r['exit_value']*.98-1.3-r['cost']
  assert abs(expected-r['pnl'])<1e-7
  if r['fill']:assert datetime.fromisoformat(r['exit'])>=datetime.fromisoformat(r['signal'])+timedelta(minutes=1)
  if r['signal']:
   pre=next(p for p in ns['prepared'] if p['c']['id']==r['id']);altered=copy.deepcopy(pre)
   for row in altered['rows']:
    if row['p']['et']>r['signal'] and row['p']['pnl'] is not None:row['p']['pnl']=999999
   assert ns['evaluate'](altered,d['selected'][key])['signal']==r['signal']
# Synthetic observations verify weekday target switching and direction; no future observations needed.
ET=ns['ET'];base=datetime(2026,8,7,10,tzinfo=ET)
c={'id':'fixture','capital':100,'completed':True,'final':{'pnl':0,'et':(base+timedelta(days=7)).replace(hour=16).isoformat()}}
r={'type':'decay','up':100,'down':20,'gate':None,'stop':None,'cut':None,'schedule':{'wed':{'factor':.5},'thu':{'factor':.25},'fri':{'factor':.1}}}
def row(day,roi,direction=1):
 t=base+timedelta(days=day);value=101.3*(1+roi/100)+1.3
 return {'t':t,'day':day,'p':{'et':t.isoformat(),'pnl':value-100,'call_age':1,'put_age':1,'stock_return_pct':direction},'fill':{'et':(t+timedelta(minutes=1)).isoformat(),'value':value,'delay':1}}
for day,roi in [(5,55),(6,30),(7,12)]:
 pre={'c':c,'f':{},'rows':[row(4,55),row(day,roi)]};result=ns['evaluate'](pre,r,slip=0);assert result['signal']==(base+timedelta(days=day)).isoformat()
pre={'c':c,'f':{},'rows':[row(4,11,-1),row(5,11,-1)]};assert ns['evaluate'](pre,r,slip=0)['signal']==(base+timedelta(days=5)).isoformat()
# Absolute targets at zero/negative net profit correctly override a percentage multiplier.
r2=dict(r,schedule={'wed':{'absolute':0},'thu':{'absolute':-10},'fri':{'absolute':-20}})
pre={'c':c,'f':{},'rows':[row(5,-5),row(6,-5)]};assert ns['evaluate'](pre,r2,slip=0)['signal']==(base+timedelta(days=6)).isoformat()
print('PASS: 11 strategy families × 7 rounds; six-only totals, fees, execution delays, causal first signals; Wed/Thu/Fri step-down, downside and loss-recovery target fixtures.')
