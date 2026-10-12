# -*- coding: utf-8 -*-
"""Freeze sqrt-time entry selection; compare causal exit rules with single-position rotation."""
import sys,json,copy,argparse,hashlib
from pathlib import Path
from datetime import datetime,timedelta,time
BASE=Path(__file__).resolve().parent
PARENT=Path('/Users/gavinz/git/finance/hedge_codex/straddle/rotation') if not (BASE.parent/'rotation_backtest.py').exists() else BASE.parent
sys.path.insert(0,str(PARENT))
import rotation_backtest as core
core.CACHE=BASE/'market_cache'
ET=core.ET
class Engine:
 def __init__(self,m):self.m=m;self.quote_cache={};self.entry_cache={};self.exit_cache={}
 def quote(self,c,t):
  k=(c['call'],c['put'],t)
  if k not in self.quote_cache:self.quote_cache[k]=self.m.quote(c,t)
  return self.quote_cache[k]
 def deadline(self,expiry,r):
  if r['days'] is None:return None
  h,mi=map(int,r['clock'].split(':'));return datetime.fromisoformat(expiry).replace(tzinfo=ET,hour=h,minute=mi)-timedelta(days=r['days'])
 def opening(self,initial,r):
  key=(initial,r['days'],r['clock'])
  if key in self.entry_cache:return copy.deepcopy(self.entry_cache[key])
  m=self.m;t=initial;contracts=m.candidates(t);last={};chosen=None;reason='缺少新鲜报价';excluded=[]
  while t.date()==initial.date() and t.time()<=time(15,30):
   quotes={k:q for k,c in contracts.items() if (q:=self.quote(c,t)) is not None};last=quotes
   eligible={k:q for k,q in quotes.items() if self.deadline(q['expiry'],r) is None or t<self.deadline(q['expiry'],r)}
   excluded=[q['expiry'] for q in quotes.values() if self.deadline(q['expiry'],r) is not None and t>=self.deadline(q['expiry'],r)]
   chosen=core.select(eligible,'sqrt',None,t.weekday()==4)
   if chosen:break
   if quotes:reason='已进入强平窗口或费用超过12%';break
   t+=timedelta(minutes=10)
  dec=dict(time=core.iso(t if t.time()<=time(15,30) else initial),strike_selection_time=core.iso(initial),candidates=last,excluded_expiries=excluded)
  entry=m.fill(chosen,t,True) if chosen else None
  if chosen and entry and self.deadline(chosen['expiry'],r) and datetime.fromisoformat(entry['time'])>=self.deadline(chosen['expiry'],r):entry=None;reason='可成交时间已进入强平窗口'
  if not entry:
   if chosen and reason!='可成交时间已进入强平窗口':reason='无合格共同成交分钟'
   dec.update(action='轮空',reason=reason);out=(dec,None,None)
  else:
   dec.update(action='开仓',expiry=chosen['expiry'],choice='near' if chosen is last.get('near') else 'far');out=(dec,chosen,entry)
  self.entry_cache[key]=out;return copy.deepcopy(out)
 def closing(self,q,e,r):
  m=self.m;et=datetime.fromisoformat(e['time']);expiry=datetime.fromisoformat(q['expiry']).replace(tzinfo=ET,hour=16);deadline=self.deadline(q['expiry'],r)
  c=dict(call=q['call_ticker'],put=q['put_ticker'],expiry=q['expiry'],strike=q['strike']);t=et.replace(minute=et.minute//10*10,second=0)+timedelta(minutes=10);curve=[];signal=None
  while t<=min(expiry,m.limit):
   if t.date().isoformat() in m.days and time(9,40)<=t.time()<time(16):
    quote=self.quote(c,t);reason=None;roi=None;target=None
    if quote:
     pnl=quote['cost']-e['value'];roi=100*pnl/e['value'];up=quote['stock']>=e['stock'];days=(expiry.date()-t.date()).days
     factor={0:.25,1:.5,2:.75}.get(days,1);target=(r['up'] if up else r['down'])
     if target is not None:target*=factor
     curve.append(dict(time=core.iso(t),pnl=pnl,stock=quote['stock'],roi=roi))
     if r['stop'] is not None and roi<=-r['stop']:reason='组合止损'
     elif target is not None and roi>=target:reason=('涨侧' if up else '跌侧')+'止盈'
    if deadline and t>=deadline:reason='到期前强制平仓'
    if reason:
     signal=dict(time=core.iso(t),reason=reason,roi=roi,target=target,deadline=core.iso(deadline),quotes=quote);fill=m.fill(q,t)
     if fill:return dict(status='模拟平仓',exit=fill,signal=signal,curve=curve,deadline=core.iso(deadline))
     break
   t+=timedelta(minutes=10)
  if expiry<=m.limit:
   stock=m.days[q['expiry']]['c'];call=max(stock-q['strike'],0);put=max(q['strike']-stock,0);x=dict(time=core.iso(expiry),stock=stock,call=call,put=put,value=100*(call+put));status='到期结算'
  else:
   vals={};ages={}
   for leg in ['call','put']:
    bars=m.bars(q[leg+'_ticker']);ks=[k for k in bars if k.date()==m.limit.date() and k<m.limit]
    if not ks:raise RuntimeError('Missing same-day final mark: '+q[leg+'_ticker'])
    k=max(ks);vals[leg]=bars[k]['c'];ages[leg]=(m.limit-k).total_seconds()/60
   x=dict(time=core.iso(m.limit),stock=m.days[m.end]['c'],call=vals['call'],put=vals['put'],value=100*(vals['call']+vals['put']),ages=ages);status='仍持仓估值'
  return dict(status=status,exit=x,signal=signal,curve=curve,deadline=core.iso(deadline))
 def run(self,r):
  m=self.m;t=datetime.fromisoformat(core.START).replace(tzinfo=ET,hour=10);trades=[];decisions=[]
  while t and t<=m.limit:
   dec,q,e=self.opening(t,r);decisions.append(dec)
   if e is None:t=m.nextday(t);continue
   result=self.closing(q,e,r);x=result['exit'];gross=x['value']-e['value']
   tr=dict(id=len(trades)+1,decision=dec,contract=q,entry=e,**result,gross=gross,roi=100*gross/e['value'],call_pnl=100*(x['call']-e['call']),put_pnl=100*(x['put']-e['put']));trades.append(tr)
   t=m.reentry(datetime.fromisoformat(x['time'])) if result['status']!='仍持仓估值' else None
  realized=0;equity=[dict(time=core.START+'T10:00:00-04:00',value=0)];capital=0;peak=0;dd=0
  for tr in trades:
   capital=max(capital,tr['entry']['value']-realized);equity.append(dict(time=tr['entry']['time'],value=realized))
   equity.extend(dict(time=x['time'],value=realized+x['pnl']) for x in tr['curve']);equity.append(dict(time=tr['exit']['time'],value=realized+tr['gross']))
   if tr['status']!='仍持仓估值':realized+=tr['gross']
  floating=sum(tr['gross'] for tr in trades if tr['status']=='仍持仓估值');equity.append(dict(time=core.iso(m.limit),value=realized+floating))
  for point in equity:peak=max(peak,point['value']);dd=max(dd,peak-point['value'])
  closed=[tr for tr in trades if tr['status']!='仍持仓估值']
  stats=dict(total=realized+floating,realized=realized,floating=floating,positions=len(trades),closed=len(closed),wins=sum(tr['gross']>0 for tr in closed),premium_turnover=sum(tr['entry']['value'] for tr in trades),required_cash=capital,drawdown=dd,worst=min([tr['gross'] for tr in trades] or [0]),forced=sum(tr['status']=='模拟平仓' and bool(tr['signal']) and tr['signal']['reason']=='到期前强制平仓' for tr in trades),skips=sum(dec['action']=='轮空' for dec in decisions))
  return dict(rule=r,stats=stats,trades=trades,decisions=decisions,equity=equity)
def rules():
 out=[];windows=[(None,None),(3,'10:00'),(3,'15:30'),(2,'10:00'),(2,'15:30')]
 for up,down in [(150,10),(80,10),(40,10),(80,5)]:
  for stop in [None,35]:
   for days,clock in windows:
    name=f'涨{up}%／跌{down}%，到期周递减'+(f'；止损{stop}%' if stop else '；无止损')+(f'；提前{days}天{clock}强平' if days else '；不强平')
    out.append(dict(id=f'E{len(out):02d}',name=name,up=up,down=down,stop=stop,days=days,clock=clock))
 for days,clock in windows[1:]:out.append(dict(id=f'E{len(out):02d}',name=f'仅提前{days}天{clock}强平',up=None,down=None,stop=None,days=days,clock=clock))
 return out
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--end',default='2026-10-08');ap.add_argument('--only-unforced',action='store_true');args=ap.parse_args();m=core.Market(args.offline,args.end);engine=Engine(m);rs=rules();results=[]
 if args.only_unforced:rs=[r for r in rs if r['days'] is None]
 for i,r in enumerate(rs):
  print('RULE',i+1,'/',len(rs),r['name'],flush=True);path=BASE/'checkpoints'/m.end/(r['id']+'.json')
  if path.exists():result=json.loads(path.read_text());assert result['rule']==r
  else:result=engine.run(r);core.save(path,result)
  results.append(result);print('RESULT',r['id'],result['stats'],flush=True)
 d=dict(start=core.START,end=m.end,created_at=datetime.now(ET).isoformat(),rules_count=len(rs),results=results,best=max(results,key=lambda r:(r['stats']['total'],-r['stats']['drawdown']))['rule']['id'])
 core.save(BASE/('unforced_results.json' if args.only_unforced else 'exit_optimization_results.json'),d);print('COMPLETE',d['best'],flush=True)
