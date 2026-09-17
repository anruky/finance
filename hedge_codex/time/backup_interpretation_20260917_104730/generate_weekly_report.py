# -*- coding: utf-8 -*-
"""Weekly 100-share + two-put cycle replay, aligned by weekday, not calendar date."""
import argparse,json,hashlib,math
from datetime import datetime,timedelta,time
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York');CN=ZoneInfo('Asia/Shanghai')
SLOTS={0:0,3:1,4:2,5:3,6:4,7:5}
def build(root,out):
 raw=json.loads((root/'weekly_market_data.json').read_text());meta=raw['metadata']
 def minute_map(symbol):
  return {datetime.fromtimestamp(b['t']/1000,ET):b for b in raw[symbol+'_minute'] if b.get('v',0)>0 and time(9,30)<=datetime.fromtimestamp(b['t']/1000,ET).time()<time(16)}
 def day_map(symbol):return {datetime.fromtimestamp(b['t']/1000,ET).date().isoformat():b for b in raw[symbol+'_day']}
 stock=minute_map('SKHY');sd=day_map('SKHY');cycles=[]
 for day,ticker in meta['selected']:
  friday=datetime.fromisoformat(day).replace(tzinfo=ET);expiry=(friday+timedelta(days=7)).date().isoformat();strike=int(ticker[-8:])/1000
  pm=minute_map(ticker);pd=day_map(ticker)
  choices=sorted(t for t in pm if t.date()==friday.date() and t.hour>=10 and t in stock)
  assert choices,'No common entry minute: '+day
  entry=choices[0];s0=stock[entry]['o'];p0=pm[entry]['o'];capital=s0*100+p0*200
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
    age=None;put_time=None;kind='minute'
    if stamp==entry:S,P=s0,p0;kind='entry';age=0;put_time=entry
    elif stamp.hour==16:
     S=sd[dt]['c']
     if dt==expiry:P=max(strike-S,0);kind='expiry'
     else:P=pd.get(dt,{}).get('c');kind='close_review'
    else:S,_,_=last_completed(stock,stamp);P,put_time,age=last_completed(pm,stamp)
    spnl=100*(S-s0) if S is not None else None;ppnl=200*(P-p0) if P is not None else None
    pnl=spnl+ppnl if spnl is not None and ppnl is not None else None
    points.append(dict(x=xcoord(stamp),day=dt,et=stamp.isoformat(),cn=stamp.astimezone(CN).strftime('%m-%d %H:%M'),kind=kind,stock=S,put=P,stock_return_pct=100*(S/s0-1) if S else None,stock_pnl=spnl,put_pnl=ppnl,pnl=pnl,return_pct=100*pnl/capital if pnl is not None else None,put_age=age,put_bar=put_time.isoformat() if put_time else None))
  valid=[p for p in points if p['pnl'] is not None];final=points[-1]
  peak=max(valid,key=lambda p:p['pnl']);low=min(valid,key=lambda p:p['pnl'])
  cycles.append(dict(id=day,label=day[5:]+' → '+expiry[5:],start=day,expiry=expiry,ticker=ticker,strike=strike,signal_spot=stock[friday.replace(hour=9,minute=59)]['c'],entry_et=entry.isoformat(),entry_cn=entry.astimezone(CN).strftime('%m-%d %H:%M'),stock_entry=s0,put_entry=p0,capital=capital,completed=expiry<=meta['end'],last_day=final['day'],final=final,peak=peak,low=low,points=points,
   entry_put_volume=pm[entry]['v'],stale_count=sum(p['put_age'] is not None and p['put_age']>10 for p in points),missing_count=sum(p['pnl'] is None for p in points),holidays=[(friday+timedelta(days=diff)).date().isoformat() for diff in SLOTS if day<=(friday+timedelta(days=diff)).date().isoformat()<=last_day and (friday+timedelta(days=diff)).date().isoformat() not in dates]))
 # Build portfolio candles from synchronized causal minute marks, not leg highs.
 for c in cycles:
  pm=minute_map(c['ticker']);entry=datetime.fromisoformat(c['entry_et']);candles=[]
  for day in sorted(d for d in sd if c['start']<=d<=c['last_day']):
   base=datetime.fromisoformat(day).replace(tzinfo=ET,hour=9,minute=30);end=base.replace(hour=16)
   sm=None;pv=None;pt=None;marks=[];stamp=base
   while stamp<=end:
    previous=stamp-timedelta(minutes=1)
    if previous in stock:sm=stock[previous]['c']
    if previous in pm:pv=pm[previous]['c'];pt=previous
    if stamp==entry:sm=c['stock_entry'];pv=c['put_entry'];pt=entry
    if stamp>=entry:
     value=100*(sm-c['stock_entry'])+200*(pv-c['put_entry']) if sm is not None and pv is not None else None
     marks.append(dict(t=stamp,stock=sm,pnl=value,age=(stamp-pt).total_seconds()/60 if pt else None))
    stamp+=timedelta(minutes=1)
   stamp=max(base,entry)
   while stamp<end:
    # Preserve regular ten-minute grid after delayed entry.
    stop=min(base+timedelta(minutes=((int((stamp-base).total_seconds()/60)//10)+1)*10),end)
    mm=[m for m in marks if stamp<=m['t']<=stop]
    rec=dict(start=stamp.isoformat(),end=stop.isoformat(),day=day,stale=any(m['age'] is not None and m['age']>10 for m in mm))
    for field in ('stock','pnl'):
     vv=[m[field] for m in mm if m[field] is not None]
     rec[field]=dict(o=vv[0],h=max(vv),l=min(vv),c=vv[-1]) if vv else None
    candles.append(rec);stamp=stop
  c['candles']=candles;c['put_cost']=200*c['put_entry']
  for point in c['points']:point['pnl_to_put_cost_pct']=100*point['pnl']/c['put_cost'] if point['pnl'] is not None else None
 payload=dict(metadata=meta,cycles=cycles,stock_shares=100,put_contracts=2,source_sha256=hashlib.sha256((root/'weekly_market_data.json').read_bytes()).hexdigest())
 out.mkdir(parents=True,exist_ok=True);(out/'skhy_weekly_cycles.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
 template=Path(__file__).with_name('weekly_report_template.html').read_text();html=template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('</','<\\/'))
 for name in ['skhy_weekly_cycle_report.html','skhy_20260904_0911_10min_report.html']:(out/name).write_text(html)
 assert len(cycles)>=7
 sep4=next(c for c in cycles if c['start']=='2026-09-04');assert abs(sep4['final']['pnl']-938)<1e-6 and len(sep4['points'])==197
 for c in cycles:
  assert c['points'][0]['pnl']==0
  for p in c['points']:
   if p['pnl'] is not None:assert abs(p['pnl']-p['stock_pnl']-p['put_pnl'])<1e-7
   if p['kind']=='minute' and p['put_bar']:assert datetime.fromisoformat(p['put_bar'])+timedelta(minutes=1)<=datetime.fromisoformat(p['et'])
 write_markdown(payload,out)
 print(json.dumps([dict(cycle=c['label'],entry=c['entry_et'],K=c['strike'],capital=c['capital'],pnl=c['final']['pnl'],roi=c['final']['return_pct'],completed=c['completed'],last_day=c['last_day']) for c in cycles],ensure_ascii=False,indent=2))
def write_markdown(payload,out):
 def num(x):return '—' if x is None else f'{x:,.2f}'
 lines=['# SKHY 每周100股＋2张平值Put报告','', '[打开交互式双K线报告](skhy_weekly_cycle_report.html)','',f"数据截至美东 {payload['metadata']['end']}；每周五10:00选下周五到期、最接近平值的Put，等首个股票和Put共同成交分钟开仓。持有至下周五收盘。",'', '股票损益＝100×股价变化；Put损益＝200×Put单价变化；总收益／期权费＝组合毛收益÷两张Put初始权利金。此比例不是账户收益率。未扣费用。', '', '行情为历史成交估值，不保证按该价成交；旧价超过10分钟标记，缺当日价格留空。16:00为事后收盘复核，到期Put用内在价值。K线来自已完成分钟的同步持仓估值，不用两腿各自最高价拼接。各轮独立，周五10:00新仓与旧仓至16:00存在重叠。', '']
 for c in payload['cycles']:
  lines += ['## '+c['label']+('（进行中）' if not c['completed'] else ''),'',f"实际入场 ET {c['entry_et']}；行权价 ${c['strike']}；两张Put费用 ${c['put_cost']:,.2f}；总成本 ${c['capital']:,.2f}。",'',f"![组合收益与股票价格K线](cycle_{c['id']}.png)",'','| 美东时间 | 股票价 | 股价波动% | 股票收益$ | Put单价 | Put收益$ | 总收益$ | 总收益/期权费% | Put旧价分钟/状态 |','|---|---:|---:|---:|---:|---:|---:|---:|---|']
  for r in c['points']:lines.append('| '+' | '.join([r['et'][:16].replace('T',' '),*[num(r[k]) for k in ('stock','stock_return_pct','stock_pnl','put','put_pnl','pnl','pnl_to_put_cost_pct')],str(r['put_age']) if r['put_age'] is not None else r['kind']])+' |')
  lines+=['']
 (out/'skhy_weekly_cycle_report.md').write_text('\n'.join(lines))

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--output-dir',type=Path);args=ap.parse_args();build(args.dir,args.output_dir or args.dir)
