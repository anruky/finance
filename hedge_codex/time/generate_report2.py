# -*- coding: utf-8 -*-
"""Weekly one-call plus one-put cycle replay, aligned by weekday, not calendar date."""
import argparse,json,hashlib,math
from datetime import datetime,timedelta,time
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York');CN=ZoneInfo('Asia/Shanghai')
SLOTS={0:0,3:1,4:2,5:3,6:4,7:5}
def build(root,out):
 raw=json.loads((root/'report2_market_data.json').read_text());meta=raw['metadata']
 def minute_map(symbol):
  return {datetime.fromtimestamp(b['t']/1000,ET):b for b in raw[symbol+'_minute'] if b.get('v',0)>0 and time(9,30)<=datetime.fromtimestamp(b['t']/1000,ET).time()<time(16)}
 def day_map(symbol):return {datetime.fromtimestamp(b['t']/1000,ET).date().isoformat():b for b in raw[symbol+'_day']}
 stock=minute_map('SKHY');sd=day_map('SKHY');cycles=[]
 for day,ticker in meta['selected']:
  friday=datetime.fromisoformat(day).replace(tzinfo=ET);expiry=(friday+timedelta(days=7)).date().isoformat();strike=int(ticker[-8:])/1000
  pm=minute_map(ticker);pd=day_map(ticker);call_ticker=ticker[:-9]+'C'+ticker[-8:];cm=minute_map(call_ticker);cd=day_map(call_ticker)
  choices=sorted(t for t in pm if t.date()==friday.date() and t.hour>=10 and t in stock and t in cm)
  assert choices,'No common entry minute: '+day
  entry=choices[0];s0=stock[entry]['o'];p0=pm[entry]['o'];c0=cm[entry]['o'];capital=(c0+p0)*100
  last_day=min(expiry,meta['end']);points=[]
  def xcoord(dt):
   diff=(dt.date()-friday.date()).days
   return SLOTS[diff]+(dt.hour*60+dt.minute-570)/390*.92
  def last_completed(mapping,dt):
   keys=[t for t in mapping if t.date()==dt.date() and t+timedelta(minutes=1)<=dt]
   if not keys:return None,None,None
   k=max(keys);return mapping[k]['c'],k,int((dt-k).total_seconds()/60)
  dates=sorted(d for d in sd if day<=d<=last_day)
  for dt in dates:
   base=datetime.fromisoformat(dt).replace(tzinfo=ET);begin=base.replace(hour=9,minute=30);end=base.replace(hour=16)
   times=[]
   while begin<=end:
    if begin>=entry:times.append(begin)
    begin+=timedelta(minutes=10)
   if dt==day and entry not in times:times.append(entry);times.sort()
   for stamp in times:
    age=None;put_time=None;call_age=None;call_time=None;kind='minute'
    if stamp==entry:S,P,C=s0,p0,c0;kind='entry';age=call_age=0;put_time=call_time=entry
    elif stamp.hour==16:
     S=sd[dt]['c']
     if dt==expiry:P=max(strike-S,0);C=max(S-strike,0);kind='expiry'
     else:P=pd.get(dt,{}).get('c');C=cd.get(dt,{}).get('c');kind='close_review'
    else:S,_,_=last_completed(stock,stamp);P,put_time,age=last_completed(pm,stamp);C,call_time,call_age=last_completed(cm,stamp)
    spnl=100*(C-c0) if C is not None else None;ppnl=100*(P-p0) if P is not None else None
    pnl=spnl+ppnl if spnl is not None and ppnl is not None else None
    points.append(dict(x=xcoord(stamp),day=dt,et=stamp.isoformat(),cn=stamp.astimezone(CN).strftime('%m-%d %H:%M'),kind=kind,stock=S,put=P,stock_return_pct=100*(S/s0-1) if S else None,call_pnl=spnl,call=C,call_age=call_age,call_bar=call_time.isoformat() if call_time else None,premium_return_pct=100*pnl/capital if pnl is not None else None,put_pnl=ppnl,pnl=pnl,return_pct=100*pnl/capital if pnl is not None else None,put_age=age,put_bar=put_time.isoformat() if put_time else None))
  valid=[p for p in points if p['pnl'] is not None];final=points[-1]
  peak=max(valid,key=lambda p:p['pnl']);low=min(valid,key=lambda p:p['pnl'])
  cycles.append(dict(id=day,label=day[5:]+' → '+expiry[5:],start=day,expiry=expiry,ticker=ticker,call_ticker=call_ticker,call_entry=c0,premium=capital,entry_call_volume=cm[entry]['v'],strike=strike,signal_spot=stock[friday.replace(hour=9,minute=59)]['c'],entry_et=entry.isoformat(),entry_cn=entry.astimezone(CN).strftime('%m-%d %H:%M'),stock_entry=s0,put_entry=p0,capital=capital,completed=expiry<=meta['end'],last_day=final['day'],final=final,peak=peak,low=low,points=points,
   entry_put_volume=pm[entry]['v'],stale_count=sum(any(p[k] is not None and p[k]>10 for k in ['put_age','call_age']) for p in points),missing_count=sum(p['pnl'] is None for p in points),holidays=[(friday+timedelta(days=diff)).date().isoformat() for diff in SLOTS if day<=(friday+timedelta(days=diff)).date().isoformat()<=last_day and (friday+timedelta(days=diff)).date().isoformat() not in dates]))

 payload=dict(metadata=meta,cycles=cycles,stock_shares=0,call_contracts=1,put_contracts=1,source_sha256=hashlib.sha256((root/'report2_market_data.json').read_bytes()).hexdigest())
 out.mkdir(parents=True,exist_ok=True)
 (out/'skhy_report2_cycles.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
 template=Path(__file__).with_name('report2_template.html').read_text()
 (out/'skhy_report2_straddle.html').write_text(template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('</','<\\/')))
 md=['# 报告2：每轮1张Call＋1张Put','', '[打开交互式报告](skhy_report2_straddle.html)','', '每周五10:00起等待股票、Call、Put同一成交分钟，以分钟开盘价估算入场；同一行权价、下周五到期。股票只作参考，不买股票。持有至到期，无熔断。总收益率分母为Call＋Put的总权利金。未扣费用。','', '盘中仅取当时已完成的当日分钟收盘价；旧价显示年龄，缺价留空。16:00为事后日线复核，到期用内在价值。成交估值不保证可成交。报告1的gav解读仅为原策略复盘参考，不视为本策略结论。','']
 for c in cycles:
  assert c['points'][0]['pnl']==0
  md += ['## '+c['label'],'',f"入场：{c['entry_et']}；K={c['strike']}；Call费用 ${100*c['call_entry']:.2f}；Put费用 ${100*c['put_entry']:.2f}；总权利金 ${c['capital']:.2f}。",'', '| 美东时间 | 股价 | 股价涨跌% | Call价 | Call收益$ | Put价 | Put收益$ | 总收益$ | 收益/权利金% | Call年龄/Put年龄(分钟) |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
  for p in c['points']:
   if p['pnl'] is not None:assert abs(p['pnl']-p['call_pnl']-p['put_pnl'])<1e-7
   for field in ['call_bar','put_bar']:
    if p['kind']=='minute' and p[field]:assert datetime.fromisoformat(p[field])+timedelta(minutes=1)<=datetime.fromisoformat(p['et'])
   md.append('| '+' | '.join([p['et'][:16].replace('T',' ')]+['—' if p[k] is None else f"{p[k]:,.2f}" for k in ['stock','stock_return_pct','call','call_pnl','put','put_pnl','pnl','premium_return_pct']]+[f"{p['call_age']} / {p['put_age']} ({p['kind']})"] )+' |')
  md+=['']
 (out/'skhy_report2_straddle.md').write_text('\n'.join(md))
 print(json.dumps([dict(cycle=c['label'],entry=c['entry_et'],capital=c['capital'],pnl=c['final']['pnl'],return_pct=c['final']['premium_return_pct']) for c in cycles],indent=2))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--output-dir',type=Path);args=ap.parse_args();build(args.dir,args.output_dir or args.dir)
