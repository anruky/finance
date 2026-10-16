# -*- coding: utf-8 -*-
from pathlib import Path
from datetime import datetime,time,timedelta,timezone
import json,copy,hashlib,sys,requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
http=requests.Session();http.mount('https://',HTTPAdapter(max_retries=Retry(total=4,backoff_factor=1,status_forcelist=[429,500,502,503,504])))
BASE=Path(__file__).parent
sys.path.insert(0,str(BASE));import optimize_rotation_exits as opt
core=opt.core;core.CACHE=BASE/'market_cache';ET=core.ET
end='2026-10-14';old_end='2026-10-12'
latest=json.loads((BASE/'best_strategy_latest.json').read_text());assert latest['data_end']==old_end
assert not latest.get('entry_execution_version'), 'Legacy one-off updater: use refresh_best_strategy.py for corrected entry execution'
result=copy.deepcopy(latest['result']);records=[]
def ingest(ticker,raw=None):
 symbol=ticker.removeprefix('O:');dest=BASE/'public_market_data'/(symbol+'_'+end+'.json')
 if raw is None:
  if dest.exists():raw=json.loads(dest.read_text())
  else:
   params=dict(period1=int(datetime(2026,10,13,tzinfo=ET).timestamp()),period2=int(datetime(2026,10,15,tzinfo=ET).timestamp()),interval='1m')
   resp=http.get('https://query1.finance.yahoo.com/v8/finance/chart/'+symbol,params=params,headers={'User-Agent':'Mozilla/5.0'},timeout=30);
   if resp.status_code==404:
    print('No public minute series',symbol,flush=True);core.save(core.CACHE/(ticker.replace(':','_')+'_minute_'+end+'.json'),[]);records.append(dict(ticker=ticker,provider='Yahoo Finance public chart',status='No minute series (HTTP 404); candidate unavailable, never zero-priced',url=resp.url));return
   resp.raise_for_status();raw=resp.json()['chart']['result'][0]
 assert raw['meta']['symbol']==symbol and raw['meta']['currency']=='USD';core.save(dest,raw)
 q=raw['indicators']['quote'][0];bars=[];closes={}
 for i,ts in enumerate(raw['timestamp']):
  dt=datetime.fromtimestamp(ts,ET);ds=dt.date().isoformat()
  if not old_end<ds<=end:continue
  if dt.time()==time(16) and q['close'][i] is not None:closes[ds]=q['close'][i]
  if dt.second or not time(9,30)<=dt.time()<time(16) or any(q[f][i] is None for f in ['open','high','low','close','volume']):continue
  bars.append(dict(t=ts*1000,o=q['open'][i],h=q['high'][i],l=q['low'][i],c=q['close'][i],v=q['volume'][i]))
 assert bars,'No regular minute data '+symbol
 oldfiles=sorted(f for f in core.CACHE.glob(ticker.replace(':','_')+'_minute_????-??-??.json') if f.stem[-10:]<=old_end)
 history=json.loads(oldfiles[-1].read_text()) if oldfiles else []
 merged={b['t']:b for b in history};merged.update({b['t']:b for b in bars});core.save(core.CACHE/(ticker.replace(':','_')+'_minute_'+end+'.json'),[merged[k] for k in sorted(merged)])
 counts={ds:sum(core.stamp(b['t']).date().isoformat()==ds and b['v']>0 for b in bars) for ds in ['2026-10-13',end]}
 records.append(dict(ticker=ticker,provider='Yahoo Finance public chart',url='https://query1.finance.yahoo.com/v8/finance/chart/'+symbol,days=counts,raw_file=str(dest.relative_to(BASE)),sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
 print('Imported',symbol,counts,flush=True)
 if ticker=='SKHY':
  daily=json.loads((core.CACHE/('stock_day_'+old_end+'.json')).read_text())
  for ds in ['2026-10-13',end]:
   bs=[b for b in bars if core.stamp(b['t']).date().isoformat()==ds];assert len(bs)==390,(ds,len(bs))
   close=closes.get(ds)
   meta=raw['meta']
   if close is None and datetime.fromtimestamp(meta['regularMarketTime'],ET).date().isoformat()==ds:close=meta['regularMarketPrice']
   if close is None:
    daily_raw=json.loads((BASE/'public_market_data'/'SKHY_daily_2026-10-14.json').read_text());core.save(BASE/'public_market_data'/'SKHY_daily_2026-10-14.json',daily_raw)
    close=next(daily_raw['indicators']['quote'][0]['close'][i] for i,ts in enumerate(daily_raw['timestamp']) if datetime.fromtimestamp(ts,ET).date().isoformat()==ds)
   daily.append(dict(t=int(datetime.fromisoformat(ds).replace(tzinfo=ET).timestamp()*1000),o=bs[0]['o'],h=max(b['h'] for b in bs),l=min(b['l'] for b in bs),c=close,v=sum(b['v'] for b in bs)))
   print('Stock close',ds,close,flush=True)
  core.save(core.CACHE/('stock_day_'+end+'.json'),daily)
for ticker in ['SKHY','O:SKHY261016C00167500','O:SKHY261016P00167500']:ingest(ticker,json.loads((BASE/'public_market_data'/(ticker.removeprefix('O:')+'_'+end+'.json')).read_text()))
class LatestMarket(core.Market):
 def bars(self,ticker):
  if not (core.CACHE/(ticker.replace(':','_')+'_minute_'+self.end+'.json')).exists() or (BASE/'public_market_data'/(ticker.removeprefix('O:')+'_'+end+'.json')).exists():
   if not any(rec['ticker']==ticker for rec in records):ingest(ticker)
  return super().bars(ticker)
 def contract(self,t,expiry,spot):
  # Contract reference only; no quote assumptions or fabricated strikes.
  was=self.offline;self.offline=False
  if self.client is None:
   import ast
   from refresh_data import Client
   tree=ast.parse(Path('/Users/gavinz/git/finance/data/data_puller.py').read_text());key=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(a,ast.Name) and a.id=='API_KEY' for a in n.targets));self.client=Client(key)
  try:return super().contract(t,expiry,spot)
  finally:self.offline=was
m=LatestMarket(True,end);engine=opt.Engine(m);r=result['rule'];tr=result['trades'][-1];assert tr['status']=='仍持仓估值'
def finalize(tr,new):
 tr.update(new);x=tr['exit'];e=tr['entry'];tr.update(gross=x['value']-e['value'],roi=100*(x['value']-e['value'])/e['value'],call_pnl=100*(x['call']-e['call']),put_pnl=100*(x['put']-e['put']));print('Round',tr['id'],tr['entry'],tr['status'],tr['exit'],'gross',tr['gross'],flush=True)
finalize(tr,engine.closing(tr['contract'],tr['entry'],r))
t=m.reentry(datetime.fromisoformat(tr['exit']['time'])) if tr['status']!='仍持仓估值' else None
while t and t<=m.limit:
 dec,q,e=engine.opening(t,r);result['decisions'].append(dec)
 if e is None:t=m.nextday(t);continue
 tr=dict(id=len(result['trades'])+1,decision=dec,contract=q,entry=e);finalize(tr,engine.closing(q,e,r));result['trades'].append(tr);t=m.reentry(datetime.fromisoformat(tr['exit']['time'])) if tr['status']!='仍持仓估值' else None
realized=0;equity=[dict(time=core.START+'T10:00:00-04:00',value=0)];capital=0;peak=0;dd=0
for tr in result['trades']:
 capital=max(capital,tr['entry']['value']-realized);equity.append(dict(time=tr['entry']['time'],value=realized));equity.extend(dict(time=x['time'],value=realized+x['pnl']) for x in tr['curve']);equity.append(dict(time=tr['exit']['time'],value=realized+tr['gross']))
 if tr['status']!='仍持仓估值':realized+=tr['gross']
floating=sum(t['gross'] for t in result['trades'] if t['status']=='仍持仓估值');equity.append(dict(time=core.iso(m.limit),value=realized+floating))
for x in equity:peak=max(peak,x['value']);dd=max(dd,peak-x['value'])
closed=[t for t in result['trades'] if t['status']!='仍持仓估值'];result['equity']=equity
result['stats']=dict(total=realized+floating,realized=realized,floating=floating,positions=len(result['trades']),closed=len(closed),wins=sum(t['gross']>0 for t in closed),premium_turnover=sum(t['entry']['value'] for t in result['trades']),required_cash=capital,drawdown=dd,worst=min(t['gross'] for t in result['trades']),forced=0,skips=sum(d['action']=='轮空' for d in result['decisions']))
latest.update(data_end=end,requested_end=end,result=result,checked_at_utc=datetime.now(timezone.utc).isoformat(),source_note='原选优结果不变；10/9前沿用Massive历史，10/12至10/14补充Yahoo Finance公开分钟行情。期末两腿按各自最后成交价估值，价龄见各轮细节。',sources=latest.get('sources',[])+records,provenance_file='oct14_market_provenance.json')
assert json.loads((BASE/'best_strategy_latest.json').read_text())['result']['trades'][:-1]==result['trades'][:11]
core.save(BASE/'best_strategy_latest.json',latest);core.save(BASE/'oct14_market_provenance.json',dict(end=end,checked_at_utc=latest['checked_at_utc'],records=records,previous='oct12_market_provenance.json',note='Regular-session minute OHLC trades only. Stock daily closes use timestamped 16:00 markers or same-day regularMarketPrice; option final marks use last positive-volume regular minute close.'))
print('STATS',result['stats'])
