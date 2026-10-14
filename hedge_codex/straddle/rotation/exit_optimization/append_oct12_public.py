# -*- coding: utf-8 -*-
"""Append the verified Oct12 public minute series to the fixed strategy's open round only."""
from pathlib import Path
from datetime import datetime,time,timezone
import json,copy,hashlib,sys
BASE=Path(__file__).parent;ROOT=Path('/Users/gavinz/git/finance/hedge_codex/straddle/rotation/exit_optimization');sys.path.insert(0,str(ROOT));import optimize_rotation_exits as opt
core=opt.core;core.CACHE=BASE/'market_cache';ET=core.ET;old_end='2026-10-09';end='2026-10-12'
latest=json.loads((BASE/'best_strategy_latest.json').read_text());assert latest['data_end']==old_end
result=copy.deepcopy(latest['result']);open_trades=[t for t in result['trades'] if t['status']=='仍持仓估值'];assert len(open_trades)==1;tr=open_trades[0]
needed=['SKHY',tr['contract']['call_ticker'],tr['contract']['put_ticker']];provenance=[]
for ticker in needed:
 symbol=ticker.removeprefix('O:');src=BASE/'public_market_data'/(symbol+'_'+end+'.json');data=json.loads(src.read_text());assert data['meta']['symbol']==symbol and data['meta']['currency']=='USD';q=data['indicators']['quote'][0];bars=[]
 for i,ts in enumerate(data['timestamp']):
  stamp=datetime.fromtimestamp(ts,ET)
  if stamp.date().isoformat()!=end or stamp.second or not time(9,30)<=stamp.time()<time(16):continue
  if any(q[f][i] is None for f in ['open','high','low','close','volume']):continue
  bars.append(dict(t=ts*1000,o=q['open'][i],h=q['high'][i],l=q['low'][i],c=q['close'][i],v=q['volume'][i]))
 assert bars
 old=BASE/'market_cache'/(ticker.replace(':','_')+'_minute_'+old_end+'.json');history=json.loads(old.read_text());merged={b['t']:b for b in history};merged.update({b['t']:b for b in bars});out=BASE/'market_cache'/(ticker.replace(':','_')+'_minute_'+end+'.json');core.save(out,[merged[k] for k in sorted(merged)])
 copied=BASE/'public_market_data';copied.mkdir(exist_ok=True);core.save(copied/(symbol+'_'+end+'.json'),data)
 provenance.append(dict(ticker=ticker,provider='Yahoo Finance public chart',url='https://query1.finance.yahoo.com/v8/finance/chart/'+symbol,day=end,returned_points=len(data['timestamp']),regular_minute_points=len(bars),positive_volume_minutes=sum(b['v']>0 for b in bars),sha256=hashlib.sha256(src.read_bytes()).hexdigest(),raw_file='public_market_data/'+symbol+'_'+end+'.json'))
 if ticker=='SKHY':
  daily=json.loads((BASE/'market_cache'/('stock_day_'+old_end+'.json')).read_text());meta=data['meta'];day=dict(t=int(datetime.fromisoformat(end).replace(tzinfo=ET).timestamp()*1000),o=bars[0]['o'],h=meta.get('regularMarketDayHigh',max(b['h'] for b in bars)),l=meta.get('regularMarketDayLow',min(b['l'] for b in bars)),c=meta['regularMarketPrice'],v=meta.get('regularMarketVolume',sum(b['v'] for b in bars)))
  assert abs(day['c']-162.23)<.001;daily.append(day);core.save(BASE/'market_cache'/('stock_day_'+end+'.json'),daily)
# Reuse finalized histories for the one carried combination; never change historical closed trades.
m=core.Market(True,end);new=opt.Engine(m).closing(tr['contract'],tr['entry'],tr['rule'] if 'rule' in tr else result['rule'])
assert new['status']=='仍持仓估值','A new exit requires continuing the fixed-rule rotation, not just marking the old position.'
tr.update(new);tr['gross']=tr['exit']['value']-tr['entry']['value'];tr['roi']=100*tr['gross']/tr['entry']['value'];tr['call_pnl']=100*(tr['exit']['call']-tr['entry']['call']);tr['put_pnl']=100*(tr['exit']['put']-tr['entry']['put'])
realized=0;equity=[dict(time=core.START+'T10:00:00-04:00',value=0)];peak=0;dd=0
for t in result['trades']:
 equity.append(dict(time=t['entry']['time'],value=realized));equity.extend(dict(time=x['time'],value=realized+x['pnl']) for x in t['curve']);equity.append(dict(time=t['exit']['time'],value=realized+t['gross']))
 if t['status']!='仍持仓估值':realized+=t['gross']
for x in equity:peak=max(peak,x['value']);dd=max(dd,peak-x['value'])
result['equity']=equity;result['stats'].update(realized=realized,floating=tr['gross'],total=realized+tr['gross'],drawdown=dd,worst=min(t['gross'] for t in result['trades']))
latest.update(data_end=end,requested_end=end,result=result,source_note='截至10/9为Massive历史成交；10/12补充Yahoo Finance公开分钟行情，并与Investing.com收盘期权链核对。策略与原选优结果不变。',sources=provenance,checked_at_utc=datetime.now(timezone.utc).isoformat())
assert abs(tr['exit']['call']-1.70)<.001 and abs(tr['exit']['put']-6.95)<.001
assert all(a==b for a,b in zip(json.loads((BASE/'best_strategy_latest.json').read_text())['result']['trades'][:-1],result['trades'][:-1]))
core.save(BASE/'best_strategy_latest.json',latest);core.save(BASE/'oct12_market_provenance.json',dict(day=end,records=provenance,crosscheck_url='https://ca.investing.com/equities/sk-hynix-adr-options',crosscheck_as_of='2026-10-12 20:14 GMT',stock_close=162.23,call_last=1.70,put_last=6.95))
print('Oct12 appended',tr['exit'],'gross',tr['gross'],'latest_total',result['stats']['total']);print('Maximum Oct12 observed combination ROI',max(x['roi'] for x in tr['curve'] if x['time'].startswith(end)))
