# -*- coding: utf-8 -*-
"""Causal daily 10:00 exit features and finite, predeclared rule families."""
import math,statistics
from datetime import date

def features(data):
 out={};tr=[];closes=[];morning_vol=[];ret=[]
 for row in data['stock']:
  dt,o,h,l,c,v=row
  bars=[b for hm,b in sorted(data['stock_minutes'].get(dt,{}).items()) if '09:30'<=hm<'10:00']
  mv=sum(b.get('v',0) for b in bars)
  mr=bars[-1]['c']/bars[0]['o']-1 if bars else None
  rv=statistics.pstdev(ret[-5:]) if len(ret)>=5 else None
  slow=statistics.pstdev(ret[-10:]) if len(ret)>=10 else None
  out[dt]=dict(atr_pct=100*statistics.mean(tr[-7:])/closes[-1] if len(tr)>=7 else None,
   rvol=mv/statistics.mean(morning_vol[-5:]) if len(morning_vol)>=5 and statistics.mean(morning_vol[-5:]) else None,
   morning_return=mr,rv_ratio=rv/slow if rv is not None and slow else None)
  tr.append(max(h-l,abs(h-closes[-1]),abs(l-closes[-1])) if closes else h-l)
  if closes:ret.append(math.log(c/closes[-1]))
  closes.append(c);morning_vol.append(mv)
 return out

def morning_liquidation(data,dt,pos,strategy,slip):
 """Only common completed minutes 09:55–09:59, never later executions."""
 for minute in range(59,54,-1):
  hm=f'09:{minute:02d}';stock=data['stock_minutes'].get(dt,{}).get(hm)
  pb=data['minutes'].get(pos['put'],{}).get(dt,{}).get(hm)
  cb=data['minutes'].get(pos['call'],{}).get(dt,{}).get(hm) if strategy==1 else None
  if not stock or not pb or (strategy==1 and not cb):continue
  if pb.get('v',0)<=0 or (strategy==1 and cb.get('v',0)<=0):continue
  sell=lambda p,n:n*(100*max(0,p-max(.01,p*slip))-.65)
  income=sell(pb['c'],10 if strategy==1 else 2)
  income+=sell(cb['c'],10) if strategy==1 else 100*stock['c']*(1-.0005)
  return income/pos['cost']-1
 return None

def reason(rule,data,dt,pos,signal,feature,strategy,slip):
 dte=(date.fromisoformat(pos['expiry'])-date.fromisoformat(dt)).days
 if dte<=0:return '到期日窗口内滚动'
 down,up=rule.get('down',15),rule.get('up',8)
 if rule.get('family')=='atr' and feature.get('atr_pct') is not None:
  down=max(3,min(25,feature['atr_pct']*rule['atr_down']))
  up=max(3,min(25,feature['atr_pct']*rule['atr_up']))
 move=signal/pos['entry_spot']-1
 if move<=-down/100:return '下跌滚动'
 if move>=up/100:return '上涨滚动'
 age=(date.fromisoformat(dt)-date.fromisoformat(pos['entry_date'])).days
 if rule.get('max_age') and age>=rule['max_age']:return '持仓时间上限'
 if rule.get('exit_dte') is not None and dte<=rule['exit_dte']:return '到期前减小时间损耗'
 if rule.get('family') in ('option_roi','trailing'):
  roi=morning_liquidation(data,dt,pos,strategy,slip)
  if roi is not None:
   if rule.get('take_profit') is not None and roi>=rule['take_profit']:return '组合利润止盈'
   if rule.get('stop_loss') is not None and roi<=-rule['stop_loss']:return '组合亏损止损'
   peak=pos.get('best_signal_roi',0.)
   if rule.get('trail') is not None and peak>=rule.get('activation',.2) and roi<=peak-rule['trail']:return '利润回撤退出'
   pos['best_signal_roi']=max(peak,roi)
 if rule.get('family')=='volume_reversal':
  rvol=feature.get('rvol');mr=feature.get('morning_return')
  if rvol is not None and mr is not None and rvol>=rule['rvol'] and abs(move)>=rule['min_move']/100 and mr*move<0:return '放量反向波动'
 if rule.get('family')=='rv_cooldown' and feature.get('rv_ratio') is not None:
  if age>=rule['min_age'] and feature['rv_ratio']<=rule['rv_ratio']:return '历史波动收缩'
 return None

def candidates():
 out=[]
 def add(label,**kw):out.append(dict(id=f'r{len(out):03}',label=label,**kw))
 for dn in (5,7.5,10,12.5,15,17.5,20):
  for up in (3,4,5,6,7,7.5,8,9,10,12,15):add(f'跌{dn:g}%／涨{up:g}%',family='threshold',down=dn,up=up)
 for dn in (.75,1,1.5,2):
  for up in (.5,.75,1,1.5):add(f'ATR跌{dn:g}倍／涨{up:g}倍',family='atr',atr_down=dn,atr_up=up)
 for n in (1,2,3,4):add(f'最长持有{n}自然日',family='time',max_age=n)
 for n in (1,2):add(f'到期前{n}天退出',family='time',exit_dte=n)
 for tp in (.15,.25,.4,.6):
  for stop in (.2,.35,.5):add(f'组合止盈{tp:.0%}／止损{stop:.0%}',family='option_roi',take_profit=tp,stop_loss=stop)
 for act in (.15,.3):
  for trail in (.1,.2,.3):add(f'盈利{act:.0%}后回撤{trail:.0%}退出',family='trailing',activation=act,trail=trail)
 for rv in (1.2,1.5,2):
  for mv in (2,4):add(f'开盘量比≥{rv:g}且反向／累计波动≥{mv}%',family='volume_reversal',rvol=rv,min_move=mv)
 for ratio in (.5,.7,.9):
  for age in (2,3):add(f'RV5/RV10≤{ratio:g}／至少{age}天',family='rv_cooldown',rv_ratio=ratio,min_age=age)
 return out
