# -*- coding: utf-8 -*-
from pathlib import Path
from datetime import datetime,timezone
import json,copy,sys
BASE=Path(__file__).parent;sys.path.insert(0,str(BASE))
from entry_execution import EntryEngine,core
core.CACHE=BASE/'market_cache'
old=json.loads((BASE/'best_strategy_latest.json').read_text());result=copy.deepcopy(old['result']);end=old['data_end'];records=[]
class RecentMarket(core.Market):
 def fetch(self,key,url,params):
  if '_minute_' in key and not (core.CACHE/(key+'.json')).exists():url=url.replace('/'+core.START+'/'+end,'/2026-10-13/'+end)
  existed=(core.CACHE/(key+'.json')).exists();rows=super().fetch(key,url,params)
  if not existed:records.append(dict(cache_file='market_cache/'+key+'.json',provider='Massive / Polygon',endpoint=url,rows=len(rows)))
  return rows
m=RecentMarket(False,end);engine=EntryEngine(m);r=result['rule']
# The carry-in round is unchanged; replay all entries after its first new exit.
result['trades']=result['trades'][:12];cut=result['trades'][-1]['exit']['time'];result['decisions']=[d for d in result['decisions'] if d['time']<cut]
t=m.reentry(datetime.fromisoformat(cut))
while t and t<=m.limit:
 dec,q,e=engine.opening(t,r);result['decisions'].append(dec)
 if e is None:
  if dec['action']=='数据待验证':raise RuntimeError('Incomplete daily candidate data; preserve published report until filled')
  t=m.nextday(t);continue
 new=engine.closing(q,e,r);x=new['exit'];gross=x['value']-e['value'];tr=dict(id=len(result['trades'])+1,decision=dec,contract=q,entry=e,**new,gross=gross,roi=100*gross/e['value'],call_pnl=100*(x['call']-e['call']),put_pnl=100*(x['put']-e['put']));result['trades'].append(tr)
 print('ROUND',tr['id'],q['expiry'],q['strike'],e,new['status'],x,'gross',gross,flush=True)
 t=m.reentry(datetime.fromisoformat(x['time'])) if new['status']!='仍持仓估值' else None
realized=0;equity=[dict(time=core.START+'T10:00:00-04:00',value=0)];capital=0;peak=0;dd=0
for tr in result['trades']:
 capital=max(capital,tr['entry']['value']-realized);equity.append(dict(time=tr['entry']['time'],value=realized));equity.extend(dict(time=x['time'],value=realized+x['pnl']) for x in tr['curve']);equity.append(dict(time=tr['exit']['time'],value=realized+tr['gross']))
 if tr['status']!='仍持仓估值':realized+=tr['gross']
floating=sum(t['gross'] for t in result['trades'] if t['status']=='仍持仓估值');equity.append(dict(time=core.iso(m.limit),value=realized+floating))
for x in equity:peak=max(peak,x['value']);dd=max(dd,peak-x['value'])
closed=[t for t in result['trades'] if t['status']!='仍持仓估值'];result['equity']=equity
result['stats']=dict(total=realized+floating,realized=realized,floating=floating,positions=len(result['trades']),closed=len(closed),wins=sum(t['gross']>0 for t in closed),premium_turnover=sum(t['entry']['value'] for t in result['trades']),required_cash=capital,drawdown=dd,worst=min(t['gross'] for t in result['trades']),forced=0,skips=sum(d['action']=='轮空' for d in result['decisions']))
assert result['trades'][:12]==old['result']['trades'][:12]
old.update(result=result,checked_at_utc=datetime.now(timezone.utc).isoformat(),entry_execution_version='latest_same_day_trade_v1',entry_execution_effective_after=cut,source_note=old['source_note']+' 修正10/13起重开仓：使用当日最近已完成成交价，不设15分钟价龄上限；不要求两腿同分钟成交。原选优与修正前已完成交易保持不变。',execution_note='新入场是最近成交价模拟，并非历史买卖盘报价；价格时间与价龄逐腿列出。平仓触发及模拟卖出规则保持原口径。')
old['sources'].extend(records);core.save(BASE/'best_strategy_latest.json',old);core.save(BASE/'entry_execution_correction.json',dict(effective_after=cut,scope='Only subsequent entries; original selection and first 12 rounds unchanged',new_sources=records,convention=old['execution_note']));print('STATS',result['stats'],flush=True)
