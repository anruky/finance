# -*- coding: utf-8 -*-
"""Entry proxy: latest completed same-session trade, no age cutoff.
This is an explicit last-trade execution assumption, not a historical ask quote.
Frozen comparison results and existing exit observations remain unchanged.
"""
from datetime import datetime,timedelta,time
import math
import optimize_rotation_exits as opt
core=opt.core
class EntryEngine(opt.Engine):
 def indicative(self,c,t):
  vals={};ages={};times={}
  for leg in ['call','put']:
   bars=self.m.bars(c[leg]);keys=[k for k in bars if k.date()==t.date() and k<=t-timedelta(minutes=1)]
   if not keys:return None
   k=max(keys);vals[leg]=bars[k]['c'];ages[leg]=(t-k).total_seconds()/60;times[leg]=core.iso(k)
  stock=self.m.stock_at(t)
  if stock is None:return None
  premium=vals['call']+vals['put'];days=(datetime.fromisoformat(c['expiry']).replace(tzinfo=core.ET,hour=16)-t).total_seconds()/86400
  return dict(**vals,call_ticker=c['call'],put_ticker=c['put'],expiry=c['expiry'],strike=c['strike'],stock=stock,premium=premium,cost=premium*100,pct=100*premium/stock,dte=days,score=(premium/stock)/math.sqrt(days),ages=ages,quote_times=times,price_basis='latest_same_day_trade_proxy')
 def snapshot(self,t,r):
  contracts=self.m.candidates(t)
  eligible={k:c for k,c in contracts.items() if self.deadline(c['expiry'],r) is None or t<self.deadline(c['expiry'],r)}
  quotes={k:q for k,c in eligible.items() if (q:=self.indicative(c,t)) is not None}
  missing=[k for k in eligible if k not in quotes]
  # A missing leg is unknown rather than evidence that this expiry cannot be bought.
  chosen=core.select(quotes,'sqrt',None,t.weekday()==4) if eligible and not missing else None
  return quotes,chosen,missing
 def opening(self,initial,r):
  t=initial;observations=[];last={};missing=[]
  while t.date()==initial.date() and t.time()<=time(15,30) and t<=self.m.limit:
   quotes,chosen,missing=self.snapshot(t,r);last=quotes
   observations.append(dict(time=core.iso(t),missing_candidates=missing))
   if chosen:
    ft=t+timedelta(minutes=1)
    if ft<=self.m.limit and ft.time()<=time(15,30) and ft in self.m.stock:
     # Fresh comparison at the modeled execution time; never keep a stale selected expiry.
     fresh,q,missing_fill=self.snapshot(ft,r)
     if q and not missing_fill:
      stock=self.m.stock[ft]['o']
      if q['cost']/(100*stock)<=.12:
       dec=dict(time=core.iso(t),strike_selection_time=core.iso(t),candidates=quotes,execution_candidates=fresh,action='开仓',expiry=q['expiry'],choice='near' if q is fresh.get('near') else 'far',execution_version='latest_same_day_trade_v1',observations=observations)
       entry=dict(time=core.iso(ft),stock=stock,call=q['call'],put=q['put'],value=q['cost'],price_basis=q['price_basis'],ages=q['ages'],quote_times=q['quote_times'])
       return dec,q,entry
   t+=timedelta(minutes=10)
  dec=dict(time=core.iso(initial),strike_selection_time=core.iso(initial),candidates=last,action='数据待验证' if missing else '轮空',reason='有候选缺少当日已完成成交，待补数据' if missing else '费用超过12%或当日无合格入场时间',execution_version='latest_same_day_trade_v1',observations=observations)
  return dec,None,None

def summarize(result,limit):
 realized=0;equity=[dict(time=core.START+'T10:00:00-04:00',value=0)];capital=0;peak=0;dd=0
 for tr in result['trades']:
  capital=max(capital,tr['entry']['value']-realized);equity.append(dict(time=tr['entry']['time'],value=realized))
  equity.extend(dict(time=x['time'],value=realized+x['pnl']) for x in tr['curve']);equity.append(dict(time=tr['exit']['time'],value=realized+tr['gross']))
  if tr['status']!='仍持仓估值':realized+=tr['gross']
 floating=sum(t['gross'] for t in result['trades'] if t['status']=='仍持仓估值');equity.append(dict(time=core.iso(limit),value=realized+floating))
 for x in equity:peak=max(peak,x['value']);dd=max(dd,peak-x['value'])
 closed=[t for t in result['trades'] if t['status']!='仍持仓估值'];result['equity']=equity
 result['stats']=dict(total=realized+floating,realized=realized,floating=floating,positions=len(result['trades']),closed=len(closed),wins=sum(t['gross']>0 for t in closed),premium_turnover=sum(t['entry']['value'] for t in result['trades']),required_cash=capital,drawdown=dd,worst=min([t['gross'] for t in result['trades']] or [0]),forced=sum(t['signal'] is not None and t['signal']['reason']=='到期前强制平仓' for t in closed),skips=sum(d['action']=='轮空' for d in result['decisions']))
 return result
