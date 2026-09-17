"""Focused audit of causal decisions, later execution, gating and P&L."""
import json,copy
from pathlib import Path
from datetime import datetime,timedelta
p=Path(__file__).parent
ns={'__file__':str(p/'analyze_exit.py')};code=(p/'analyze_exit.py').read_text().split("rules=[dict(id='hold'")[0];exec(compile(code,'audit_engine','exec'),ns)
d=json.loads((p/'exit_optimization.json').read_text());byid={c['id']:c for c in d['cycles']};pre={x['c']['id']:x for x in ns['prepared']}
checked=0
for key,results in d['selected_results'].items():
 rule=d['selected'][key]
 for r in results:
  c=byid[r['id']]
  if r['skipped']:
   assert r['cost']==r['pnl']==0
   continue
  assert abs(r['cost']-(c['capital']*1.02+1.3))<1e-7
  value=r['exit_value'];expected=value-r['cost'] if r['reason']=='到期结算' else value*.98-1.3-r['cost']
  assert abs(r['pnl']-expected)<1e-7
  if r['fill']:
   assert datetime.fromisoformat(r['exit'])>=datetime.fromisoformat(r['signal'])+timedelta(minutes=1)
   assert abs(r['fill']['call']*100+r['fill']['put']*100-r['exit_value'])<1e-7
  if r['signal']:
   signal=next(x['p'] for x in pre[c['id']]['rows'] if x['p']['et']==r['signal'])
   for leg in ['call','put']:
    if signal[leg+'_bar']:assert datetime.fromisoformat(signal[leg+'_bar'])+timedelta(minutes=1)<=datetime.fromisoformat(signal['et'])
   # Perturb all later observations: an already generated first signal cannot move.
   altered=copy.deepcopy(pre[c['id']])
   for row in altered['rows']:
    if row['p']['et']>r['signal'] and row['p']['pnl'] is not None:row['p']['pnl']=999999
   rr=ns['evaluate'](altered,rule)
   assert rr['signal']==r['signal']
  checked+=1
for wf in d['walk_forward']:
 for day in wf['training']:assert byid[day]['expiry']<wf['cycle']
assert max(byid[d['cycles'][i]['id']]['expiry'] for i in d['train_ids'])<min(d['cycles'][i]['start'] for i in d['test_ids'])
assert d['test_ids']==[4,5]
assert all(d['cycles'][i]['completed'] for i in d['train_ids']+d['test_ids'])
for f in d['features']:
 assert f['pretrade_call_age']>=1 and f['pretrade_put_age']>=1
print('PASS:',checked,'non-skipped scenarios; net reconciliation, later execution, causal signals, future-observation perturbations, temporal split and walk-forward overlap checks.')
# Compare asynchronous leg execution using exactly the same precomputed decision signals.
alternative=[]
for key in ['train_selected','full_sample_best']:
 rows=[]
 for r in d['selected_results'][key]:
  if r['skipped'] or not r['signal']:rows.append(dict(id=r['id'],pnl=r['pnl'],note='无退出信号或轮空'));continue
  c=byid[r['id']];start=datetime.fromisoformat(r['signal'])+timedelta(minutes=1);receipts=0;fills=[]
  for leg,symbol in [('call',c['call_ticker']),('put',c['ticker'])]:
   m=ns['bars'](symbol);ks=sorted(t for t in m if t>=start)
   if ks:
    t=ks[0];price=m[t]['o'];receipts+=price*100*.98-.65;fills.append(dict(leg=leg,et=t.isoformat(),price=price,mode='逐腿成交分钟开盘估算'))
   else:
    price=c['final'][leg];receipts+=price*100 if c['completed'] else price*100*.98-.65;fills.append(dict(leg=leg,et=c['final']['et'],price=price,mode='到期结算' if c['completed'] else '未成交估值'))
  rows.append(dict(id=r['id'],pnl=receipts-r['cost'],fills=fills))
 alternative.append(dict(strategy=key,results=rows))
(p/'execution_sensitivity.json').write_text(json.dumps(alternative,ensure_ascii=False,indent=2))
print('Alternate execution totals (same signals, independently close each leg):',[(x['strategy'],round(sum(r['pnl'] for r in x['results'][:6]),2)) for x in alternative])
