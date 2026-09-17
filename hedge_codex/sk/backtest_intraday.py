# -*- coding: utf-8 -*-
"""10:00 ET combo transactions; decisions use information available at 10:00."""
from datetime import date
import math
from backtest_audited import metrics

def call_ticker(pt):return pt[:-9]+'C'+pt[-8:]
def positive(v):return isinstance(v,(int,float)) and math.isfinite(v) and v>0

def opening(data,t,dt,hm="10:00"):
 b=data['minutes'].get(t,{}).get(dt,{}).get(hm)
 return b['o'] if b and b.get('v',0)>0 and positive(b.get('o')) else None

def execution(data,dt,pt,strategy,start=0,window=5):
 for minute in range(start,window+1):
  hm=f'{10+minute//60:02d}:{minute%60:02d}'
  sb=data['stock_minutes'].get(dt,{}).get(hm,{})
  S=sb.get('o');pp=opening(data,pt,dt,hm);cp=opening(data,call_ticker(pt),dt,hm) if strategy==1 else 0
  if positive(S) and sb.get('v',0)>0 and pp is not None and cp is not None:return hm,S,cp,pp
 return None

def choose(data,dt,min_volume=10):
 # Rank before examining execution bars. No substitution using later-day activity.
 for pt in data['candidates'].get(dt,[]):
  ct=call_ticker(pt)
  volumes=[sum(b.get('v',0) for hm,b in data['minutes'].get(t,{}).get(dt,{}).items() if '09:30'<=hm<'10:00') for t in (pt,ct)]
  if min(volumes)>=min_volume:return pt
 return None

def run_intraday(data,strategy,initial=22852.50,slip=.02,down=15,up=8,min_volume=10,window=359,allow_topup=False,exit_rule=None,feature_map=None,rule_schedule=None):
 assert 0<=window<=359
 assert strategy in (1,2)
 cash=initial;pos=None;curve=[];trades=[];events=[]
 deposits=[];units=initial;total_deposits=initial;unit_curve=[]
 skips=dict(no_signal=0,no_candidate=0,no_entry_minute=0,no_exit_minute=0,cash=0)
 flags=dict(expiry_close_fallback=0,missing_eod_marks=0,execution_intrinsic_anomalies=0,eod_intrinsic_anomalies=0,entry_volume_shortfall=0)
 def buy(p,n):return n*(100*(p+max(.01,p*slip))+.65)
 def sell(p,n):return n*(100*max(0,p-max(.01,p*slip))-.65)
 def close_position(dt,S,cp,pp,reason,expiry=False,hm="10:00"):
  nonlocal cash,pos
  if strategy==1:
   if expiry:
    ci=1000*cp-(10*(1+S*100*.0005) if cp else 0);pi=1000*pp-(10*(1+S*100*.0005) if pp else 0)
   else:ci=sell(cp,10);pi=sell(pp,10)
   si=0
  else:
   ci=0;pi=200*pp-(2*(1+S*100*.0005) if pp else 0) if expiry else sell(pp,2)
   si=100*S*(1-.0005)
  income=ci+pi+si;cash+=income
  trades.append(dict(**pos,exit_date=dt,exit_time='16:00 settlement' if expiry else hm,exit_spot=S,reason=reason,mark_only=False,
                     call_income=ci,put_income=pi,stock_income=si,income=income,pnl=income-pos['cost'],call_pnl=ci-pos['call_cost'],put_pnl=pi-pos['put_cost'],stock_pnl=si-pos['stock_cost']))
  pos=None
 for dt,so,sh,sl,Sclose,sv in data['stock']:
  sm=data['stock_minutes'].get(dt,{})
  signal=sm.get('09:59',{}).get('c');available_from=0
  if not positive(signal):skips['no_signal']+=1
  else:
   if pos:
    reason='到期日窗口内滚动' if dt>=pos['expiry'] else '下跌滚动' if signal<=pos['entry_spot']*(1-down/100) else '上涨滚动' if signal>=pos['entry_spot']*(1+up/100) else None
    active_rule=(rule_schedule or {}).get(dt,exit_rule)
    if active_rule is not None:
     from exit_rules import reason as decide_exit
     reason=decide_exit(active_rule,data,dt,pos,signal,(feature_map or {}).get(dt,{}),strategy,slip)
    if reason:
     fill=execution(data,dt,pos['put'],strategy,window=window)
     if fill is None:
      skips['no_exit_minute']+=1;events.append(dict(date=dt,action='exit_deferred',reason='no common execution minute in allowed window',put=pos['put']))
     else:
      hm,S,cp,pp=fill
      close_position(dt,S,cp,pp,reason,hm=hm)
      available_from=(int(hm[:2])-10)*60+int(hm[3:])+1
   if pos is None:
    pt=choose(data,dt,min_volume)
    if pt is None:skips['no_candidate']+=1
    else:
     ct=call_ticker(pt);con=data['contracts'][pt];fill=execution(data,dt,pt,strategy,start=available_from,window=window)
     if fill is None:
      skips['no_entry_minute']+=1;events.append(dict(date=dt,action='entry_skipped',reason='no common execution minute in allowed window',put=pt))
     else:
      hm,S,cp,pp=fill
      cc=buy(cp,10) if strategy==1 else 0;pc=buy(pp,10 if strategy==1 else 2);sc=100*S*(1+.0005) if strategy==2 else 0;cost=cc+pc+sc
      if cost>cash+1e-8 and allow_topup:
       amount=cost-cash
       assert cash>0, 'Cannot unitize additional funding after total loss'
       units+=amount/(cash/units)
       cash+=amount;total_deposits+=amount
       deposits.append(dict(date=dt,time=hm,amount=amount,reason='fixed-position funding gap'))
      if cost>cash+1e-8:
       skips['cash']+=1;events.append(dict(date=dt,action='entry_skipped',reason='cash',required=cost,available=cash))
      else:
       cash-=cost
       flags['execution_intrinsic_anomalies']+=int(pp+.05<max(con['strike_price']-S,0))+(int(cp+.05<max(S-con['strike_price'],0)) if strategy==1 else 0)
       qty=10 if strategy==1 else 2
       flags['entry_volume_shortfall']+=int(data['minutes'][pt][dt][hm]['v']<qty)
       if strategy==1:flags['entry_volume_shortfall']+=int(data['minutes'][ct][dt][hm]['v']<10)
       pos=dict(put=pt,call=ct,strike=con['strike_price'],expiry=con['expiration_date'],entry_date=dt,entry_time=hm,signal_date=dt,signal_price=signal,entry_spot=S,
        call_cost=cc,put_cost=pc,stock_cost=sc,cost=cost,pairs=10 if strategy==1 else 0,put_contracts=qty,last_put=pp,last_call=cp)
   # If any leg is unavailable at 10:00 on expiration, unavoidable settlement is disclosed.
  if pos and dt>=pos['expiry']:
   flags['expiry_close_fallback']+=1
   close_position(dt,Sclose,max(Sclose-pos['strike'],0),max(pos['strike']-Sclose,0),'到期窗口缺行情／收盘结算例外',True)
  cm=pm=stockmark=0
  if pos:
   stockmark=100*Sclose if strategy==2 else 0
   for leg in (('put','call') if strategy==1 else ('put',)):
    b=data['daily'].get(pos[leg],{}).get(dt);q=b.get('c') if b else None
    intrinsic=max(pos['strike']-Sclose,0) if leg=='put' else max(Sclose-pos['strike'],0)
    if not positive(q):q=max(pos['last_'+leg],intrinsic);flags['missing_eod_marks']+=1
    else:pos['last_'+leg]=q;flags['eod_intrinsic_anomalies']+=int(q+.05<intrinsic)
    if leg=='put':pm=q*100*pos['put_contracts']
    else:cm=q*1000
  unit_curve.append(dict(date=dt,equity=(cash+cm+pm+stockmark)/units*initial))
  curve.append(dict(date=dt,unit_nav=(cash+cm+pm+stockmark)/units,total_deposits=total_deposits,equity=cash+cm+pm+stockmark,cash=cash,call_value=cm,put_value=pm,stock_value=stockmark))
 if pos:
  income=cm+pm+stockmark
  trades.append(dict(**pos,exit_date=data['stock'][-1][0],exit_time='EOD mark',exit_spot=data['stock'][-1][4],reason='期末持有／收盘市值',mark_only=True,
    call_income=cm,put_income=pm,stock_income=stockmark,income=income,pnl=income-pos['cost'],call_pnl=cm-pos['call_cost'],put_pnl=pm-pos['put_cost'],stock_pnl=stockmark-pos['stock_cost']))
 m=metrics(unit_curve,initial);m['pnl']=curve[-1]['equity']-total_deposits
 m['return_pct']=100*m['pnl']/total_deposits
 residual=m['pnl']-sum(t['pnl'] for t in trades)
 assert abs(residual)<1e-6 and min(x['cash'] for x in curve)>-1e-7
 return dict(name='策略1：10 Call＋10 Put' if strategy==1 else '策略2：100股＋2 Put',strategy=strategy,initial=initial,**m,total_deposits=total_deposits,additional_deposits=total_deposits-initial,deposits=deposits,unit_curve=unit_curve,xirr_pct=xirr(initial,data['stock'][0][0],deposits,curve[-1]['equity'],data['stock'][-1][0]),trades=trades,curve=curve,skipped=skips,flags=flags,events=events,reconciliation=residual,
  config=dict(rule_schedule=rule_schedule,exit_rule=exit_rule,down=down,up=up,slip=slip,min_morning_volume=min_volume,decision='09:59 completed minute close at 10:00',execution='earliest common minute 10:00 through window end; reentry strictly after exit minute',window_minutes=window,allow_topup=allow_topup,stock_bps=5,commission=.65))


def xirr(initial,start,deposits,ending,end):
 """Conventional deposit-only investor cash flows, ACT/365, annualized percent."""
 days=(date.fromisoformat(end)-date.fromisoformat(start)).days
 if days<=0 or ending<=0:return None
 flows=[(start,initial)]+[(d['date'],d['amount']) for d in deposits]
 def value(g):
  return sum(amount*math.exp(g*(date.fromisoformat(end)-date.fromisoformat(dt)).days/365) for dt,amount in flows)-ending
 lo,hi=-700.,700.
 if value(lo)>0 or value(hi)<0:return None
 for _ in range(200):
  mid=(lo+hi)/2
  if value(mid)>0:hi=mid
  else:lo=mid
 return math.expm1((lo+hi)/2)*100
