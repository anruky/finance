"""Causal, single-position straddle rotation. No broker orders. Historical trades only."""
import argparse, ast, bisect, hashlib, json, math, sys, time as clock
from pathlib import Path
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
START='2026-07-31'
BASE=Path(__file__).resolve().parent
CACHE=BASE/'rotation_cache'
POLS=[('near','固定本周五（周五顺延）',None),('far','固定下周五',None),('ratio10','下周加价≤10%',1.10),('ratio25','下周加价≤25%',1.25),('ratio50','下周加价≤50%',1.50),('sqrt','费用／√剩余天数较低',None)]
def save(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,allow_nan=False));tmp.replace(p)
def stamp(ms):return datetime.fromtimestamp(ms/1000,ET)
def iso(t):return t.isoformat() if t else None
class Market:
 def __init__(self,offline=False,end=None):
  sys.path.insert(0,'/Users/gavinz/git/finance/hedge_codex/sk')
  from refresh_data import Client,last_completed_date
  self.offline=offline;self.end=end or last_completed_date();self.client=None;self.maps={};self.chains={};self.calls=0;self.last_request=0
  if not offline:
   tree=ast.parse(Path('/Users/gavinz/git/finance/data/data_puller.py').read_text())
   key=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='API_KEY' for t in n.targets))
   self.client=Client(key)
  self.stock=self.bars('SKHY');self.days={stamp(b['t']).date().isoformat():b for b in self.fetch('stock_day_'+self.end,'/v2/aggs/ticker/SKHY/range/1/day/'+START+'/'+self.end,{'adjusted':'false','sort':'asc','limit':50000})}
  assert self.days,'No stock daily bars';self.end=min(self.end,max(self.days));self.sessions=sorted(self.days)
  self.stock_times=sorted(self.stock);self.limit=datetime.fromisoformat(self.end).replace(tzinfo=ET,hour=16)
  print('Market through',self.end,'sessions',len(self.sessions),flush=True)
 def fetch(self,key,url,params):
  p=CACHE/(key+'.json')
  if p.exists():return json.loads(p.read_text())
  if self.offline:raise RuntimeError('Offline cache missing: '+key)
  clock.sleep(max(0,13-(clock.monotonic()-self.last_request)))
  for attempt in range(4):
   try:
    self.last_request=clock.monotonic();rows=self.client.pages(url,params);break
   except RuntimeError as exc:
    if 'retries exhausted' not in str(exc) or attempt==3:raise
    print('Rate limit: pausing before retry',key,flush=True);clock.sleep(60)
  save(p,rows);self.calls+=1
  if self.calls%10==0:print('Downloaded',self.calls,'datasets',flush=True)
  clock.sleep(.25);return rows
 def bars(self,ticker):
  if ticker not in self.maps:
   rows=self.fetch(ticker.replace(':','_')+'_minute_'+self.end,'/v2/aggs/ticker/'+ticker+'/range/1/minute/'+START+'/'+self.end,{'adjusted':'false','sort':'asc','limit':50000})
   self.maps[ticker]={stamp(b['t']):b for b in rows if b.get('v',0)>0 and time(9,30)<=stamp(b['t']).time()<time(16)}
  return self.maps[ticker]
 def stock_at(self,t):
  i=bisect.bisect_right(self.stock_times,t-timedelta(minutes=1))-1
  if i<0:return None
  k=self.stock_times[i]
  return self.stock[k]['c'] if k.date()==t.date() and t-k<=timedelta(minutes=2) else None
 def nextday(self,t):
  ds=t.date().isoformat();n=bisect.bisect_right(self.sessions,ds)
  return datetime.fromisoformat(self.sessions[n]).replace(tzinfo=ET,hour=10) if n<len(self.sessions) else None
 def reentry(self,t):
  k=t.replace(second=0,microsecond=0)+timedelta(minutes=10-t.minute%10)
  k=max(k,k.replace(hour=10,minute=0))
  return k if k.time()<=time(15,30) else self.nextday(t)
 def contract(self,t,expiry,spot):
  ds=t.date().isoformat();key=(ds,expiry)
  if key not in self.chains:
   old=CACHE/('chain_'+ds+'_'+expiry+'.json')
   if old.exists():self.chains[key]=json.loads(old.read_text())
   else:
    hi=(t.date()+timedelta(days=14)).isoformat()
    chain=self.fetch('chain_all_'+ds,'/v3/reference/options/contracts',{'underlying_ticker':'SKHY','as_of':ds,'contract_type':'put','expiration_date.gt':ds,'expiration_date.lte':hi,'limit':1000})
    self.chains[key]=[r for r in chain if r['expiration_date']==expiry]
  choices=[r for r in self.chains[key] if r.get('shares_per_contract')==100]
  if not choices:return None
  r=min(choices,key=lambda r:(abs(r['strike_price']-spot),r['strike_price']))
  put=r['ticker'];call=put[:-9]+'C'+put[-8:]
  return dict(expiry=expiry,strike=r['strike_price'],put=put,call=call)
 def candidates(self,t):
  spot=self.stock_at(t)
  if spot is None:return {}
  fri=t.date()+timedelta(days=(4-t.weekday())%7)
  # No new 0DTE positions. Friday has next Friday as its sole candidate.
  expiries=[fri,fri+timedelta(days=7)] if t.weekday()!=4 else [fri+timedelta(days=7)]
  result={}
  for e in expiries:
   kind='near' if e==fri else 'far';c=self.contract(t,e.isoformat(),spot)
   if c:result[kind]=c
  return result
 def quote(self,c,t):
  vals={};age={};times={}
  for leg in ['call','put']:
   bars=self.bars(c[leg]);keys=sorted(bars);i=bisect.bisect_right(keys,t-timedelta(minutes=1))-1
   if i<0:return None
   k=keys[i];a=(t-k).total_seconds()/60
   if k.date()!=t.date() or a>10:return None
   vals[leg]=bars[k]['c'];age[leg]=a;times[leg]=iso(k)
  stock=self.stock_at(t)
  if stock is None:return None
  premium=vals['call']+vals['put'];days=(datetime.fromisoformat(c['expiry']).replace(tzinfo=ET,hour=16)-t).total_seconds()/86400
  return dict({**c,**vals},call_ticker=c['call'],put_ticker=c['put'],stock=stock,premium=premium,cost=100*premium,pct=100*premium/stock,dte=days,score=(premium/stock)/math.sqrt(days),ages=age,quote_times=times)
 def fill(self,c,t,entry=False):
  cm=self.bars(c['call_ticker']);pm=self.bars(c['put_ticker'])
  for k in sorted(set(cm)&set(pm)&set(self.stock)):
   if k<t+timedelta(minutes=1):continue
   if entry and (k.date()!=t.date() or k.time()>time(15,30)):continue
   if k.date().isoformat()>c['expiry']:break
   cost=100*(cm[k]['o']+pm[k]['o']);spot=self.stock[k]['o']
   if entry and cost/(100*spot)>.12:continue
   return dict(time=iso(k),call=cm[k]['o'],put=pm[k]['o'],stock=spot,value=cost)
  return None

def select(quotes,policy,ratio,friday=False):
 good={k:v for k,v in quotes.items() if v['pct']<=12};near=good.get('near');far=good.get('far')
 if policy=='near':return far if friday else near
 if policy=='far':return far
 if not near:return far
 if not far:return near
 if policy=='sqrt':return min([near,far],key=lambda x:(x['score'],x['cost']))
 return far if far['premium']<=near['premium']*ratio else near

def close_position(m,q,entry):
 et=datetime.fromisoformat(entry['time']);expiry=datetime.fromisoformat(q['expiry']).replace(tzinfo=ET,hour=16)
 c={'call':q['call_ticker'],'put':q['put_ticker'],'expiry':q['expiry'],'strike':q['strike']}
 t=et.replace(minute=(et.minute//10)*10,second=0)+timedelta(minutes=10);trigger=None;curve=[]
 while t<=min(m.limit,expiry):
  if t.date().isoformat() in m.days and time(9,40)<=t.time()<time(16):
   quote=m.quote(c,t)
   if quote:
    pnl=quote['cost']-entry['value'];roi=pnl/entry['value']*100;up=quote['stock']>=entry['stock']
    remaining=(expiry.date()-t.date()).days;factor=.25 if remaining==0 else .5 if remaining==1 else .75 if remaining==2 else 1
    target=(150 if up else 10)*factor
    curve.append(dict(time=iso(t),pnl=pnl,stock=quote['stock'],roi=roi))
    if roi>=target:
     trigger=dict(time=iso(t),roi=roi,target=target,side='涨侧' if up else '跌侧',quotes=quote)
     fill=m.fill(q,t)
     if fill:return dict(status='模拟平仓',exit=fill,signal=trigger,curve=curve)
     break
  t+=timedelta(minutes=10)
 if expiry<=m.limit:
  assert q['expiry'] in m.days,'Expiry session missing'
  spot=m.days[q['expiry']]['c'];call=max(spot-q['strike'],0);put=max(q['strike']-spot,0)
  return dict(status='到期结算',exit=dict(time=iso(expiry),stock=spot,call=call,put=put,value=100*(call+put)),signal=trigger,curve=curve)
 # Common fresh observation preferred; otherwise disclose ages of last same-day trades at market close.
 last=m.limit;vals={};ages={}
 for leg in ['call','put']:
  bars=m.bars(q[leg+'_ticker']);keys=[k for k in bars if k.date()==last.date() and k<last]
  if not keys:raise RuntimeError('Missing latest-day mark '+q[leg+'_ticker'])
  k=max(keys);vals[leg]=bars[k]['c'];ages[leg]=(last-k).total_seconds()/60
 return dict(status='仍持仓估值',exit=dict(time=iso(last),stock=m.days[m.end]['c'],call=vals['call'],put=vals['put'],value=100*(vals['call']+vals['put']),ages=ages),signal=trigger,curve=curve)

def run(m,policy,name,ratio):
 t=datetime.fromisoformat(START).replace(tzinfo=ET,hour=10);trades=[];decisions=[]
 while t and t<=m.limit:
  initial=t;contracts=m.candidates(t);chosen=None;lastquotes={};lastreason='缺少足够新鲜的两腿成交价'
  # Fix strike from the initial observation, wait intraday for usable prices; expensive quotes skip until next session.
  while t.date()==initial.date() and t.time()<=time(15,30):
   quotes={k:v for k,c in contracts.items() if (v:=m.quote(c,t)) is not None};lastquotes=quotes
   chosen=select(quotes,policy,ratio,t.weekday()==4)
   if chosen:break
   if quotes and (policy!='far' or 'far' in quotes) and (policy!='near' or ('far' if t.weekday()==4 else 'near') in quotes):lastreason='可选期限权利金超过12%';break
   t+=timedelta(minutes=10)
  decision=dict(time=iso(t if t.time()<=time(15,30) else initial),strike_selection_time=iso(initial),candidates=lastquotes)
  if not chosen:
   decision.update(action='轮空',reason=lastreason);decisions.append(decision);t=m.nextday(initial);continue
  entry=m.fill(chosen,t,entry=True)
  if not entry:
   decision.update(action='轮空',reason='当日无满足12%上限的两腿与股票共同成交分钟');decisions.append(decision);t=m.nextday(initial);continue
  decision.update(action='开仓',expiry=chosen['expiry'],choice='near' if chosen is lastquotes.get('near') else 'far');decisions.append(decision)
  result=close_position(m,chosen,entry);exit=result['exit'];gross=exit['value']-entry['value']
  row=dict(id=len(trades)+1,decision=decision,contract=chosen,entry=entry,**result,gross=gross,roi=100*gross/entry['value'],call_pnl=100*(exit['call']-entry['call']),put_pnl=100*(exit['put']-entry['put']))
  trades.append(row);print(policy,'trade',row['id'],entry['time'],'->',exit['time'],result['status'],round(gross,2),flush=True)
  t=m.reentry(datetime.fromisoformat(exit['time'])) if result['status']!='仍持仓估值' else None
 closed=[r for r in trades if r['status']!='仍持仓估值'];floating=sum(r['gross'] for r in trades if r['status']=='仍持仓估值')
 realized=sum(r['gross'] for r in closed);cash=0;peak=0;dd=0
 for r in closed:cash+=r['gross'];peak=max(peak,cash);dd=max(dd,peak-cash)
 return dict(id=policy,name=name,ratio=ratio,trades=trades,decisions=decisions,stats=dict(realized=realized,floating=floating,total=realized+floating,closed=len(closed),positions=len(trades),wins=sum(r['gross']>0 for r in closed),premium_turnover=sum(r['entry']['value'] for r in trades),max_single_cost=max([r['entry']['value'] for r in trades] or [0]),closed_drawdown=dd,skips=sum(r['action']=='轮空' for r in decisions)))

def validate(d):
 for r in d['results']:
  prev=None
  for t in r['trades']:
   e=t['entry'];x=t['exit'];assert prev is None or e['time']>prev;prev=x['time']
   assert e['time']>t['decision']['time'];assert e['value']/(100*e['stock'])<=.12+1e-12
   assert datetime.fromisoformat(t['contract']['expiry']).date()>datetime.fromisoformat(e['time']).date()
   assert abs(t['gross']-(x['value']-e['value']))<1e-7
   assert abs(t['gross']-t['call_pnl']-t['put_pnl'])<1e-7
   if t['status']=='模拟平仓':assert datetime.fromisoformat(x['time'])>=datetime.fromisoformat(t['signal']['time'])+timedelta(minutes=1)
  assert abs(r['stats']['total']-sum(t['gross'] for t in r['trades']))<1e-7
 print('PASS: chronological nonoverlapping trades, causal signal/fill, premium cap, expiration and P&L reconciliation',flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--end');args=ap.parse_args();m=Market(args.offline,args.end);results=[]
 for policy,name,ratio in POLS:
  print('START',policy,flush=True);r=run(m,policy,name,ratio);results.append(r);save(CACHE/'checkpoints'/('rotation_'+policy+'.json'),r)
 d=dict(start=START,end=m.end,created_at=datetime.now(ET).isoformat(),results=results,exit_rule=dict(up=150,down=10,wed=.75,thu=.5,fri=.25),premium_cap_pct=12)
 validate(d);save(BASE/'rotation_results.json',d);print('COMPLETE',json.dumps([{k:r[k] for k in ['id','stats']} for r in results]),flush=True)
