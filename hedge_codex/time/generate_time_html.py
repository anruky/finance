# -*- coding: utf-8 -*-
"""Standalone HTML, ten-minute portfolio P&L candles from causal minute marks."""
import json,argparse,hashlib
from pathlib import Path
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York');CN=ZoneInfo('Asia/Shanghai')
def build(root,out):
 raw=json.loads((root/'market_data.json').read_text());ledger=json.loads((root/'skhy_10min_pnl.json').read_text());entry=ledger['entry'];s0=entry['stock_price'];p0=entry['put_price'];ticker='O:SKHY260911P00170000'
 def bars(symbol):return {datetime.fromtimestamp(b['t']/1000,ET):b for b in raw[symbol+'_minute'] if b.get('v',0)>0 and time(9,30)<=datetime.fromtimestamp(b['t']/1000,ET).time()<time(16)}
 stocks,puts=bars('SKHY'),bars(ticker)
 days=sorted({k.date().isoformat() for k in stocks});minutes=[]
 for day in days:
  start=datetime.fromisoformat(day).replace(tzinfo=ET,hour=10 if day=='2026-09-04' else 9,minute=0 if day=='2026-09-04' else 30)
  end=start.replace(hour=16,minute=0);last_s=None;last_p=None;last_pt=None
  # Intraday option observations before the holding start remain available, then entry anchors zero.
  for t in sorted(stocks):
   if t.date()==start.date() and t+timedelta(minutes=1)<=start:last_s=stocks[t]['c']
  for t in sorted(puts):
   if t.date()==start.date() and t+timedelta(minutes=1)<=start:last_p=puts[t]['c'];last_pt=t
  stamp=start
  while stamp<=end:
   if stamp==datetime.fromisoformat(entry['et']):last_s=s0;last_p=p0;last_pt=stamp
   else:
    completed=stamp-timedelta(minutes=1)
    if completed in stocks:last_s=stocks[completed]['c']
    if completed in puts:last_p=puts[completed]['c'];last_pt=completed
   total=100*(last_s-s0)+200*(last_p-p0) if last_s is not None and last_p is not None else None
   minutes.append(dict(et=stamp.isoformat(),cn=stamp.astimezone(CN).strftime('%m-%d %H:%M'),day=day,hm=stamp.strftime('%H:%M'),pnl=total,stock_price=last_s,put_price=last_p,
    age=int((stamp-last_pt).total_seconds()/60) if last_pt else None,stock_pnl=100*(last_s-s0) if last_s is not None else None,put_pnl=200*(last_p-p0) if last_p is not None else None))
   stamp+=timedelta(minutes=1)
 candles={}
 for interval in (10,30,60):
  cs=[]
  for day in days:
   mm=[r for r in minutes if r['day']==day];start=datetime.fromisoformat(mm[0]['et']);end=datetime.fromisoformat(mm[-1]['et']);stamp=start
   while stamp<end:
    stop=min(stamp+timedelta(minutes=interval),end)
    samples=[r for r in mm if stamp<=datetime.fromisoformat(r['et'])<=stop];valid=[r for r in samples if r['pnl'] is not None]
    if valid:
     vv=[r['pnl'] for r in valid]
     cs.append(dict(day=day,start=stamp.strftime('%H:%M'),end=stop.strftime('%H:%M'),cn_start=stamp.astimezone(CN).strftime('%m-%d %H:%M'),cn_end=stop.astimezone(CN).strftime('%m-%d %H:%M'),o=vv[0],h=max(vv),l=min(vv),c=vv[-1],samples=len(valid),expected=len(samples),stale=any(r['age']>10 for r in valid),max_age=max(r['age'] for r in valid),last=valid[-1]))
    stamp=stop
  candles[str(interval)]=cs
 assert len(candles['10'])==192
 for cs in candles.values():
  for r in cs:assert r['l']<=min(r['o'],r['c'])<=max(r['o'],r['c'])<=r['h']
 payload=dict(entry=entry,days=days,candles=candles,minutes=minutes,observations=ledger['rows'],final=ledger['rows'][-1],source_sha256=hashlib.sha256((root/'market_data.json').read_bytes()).hexdigest())
 out.mkdir(parents=True,exist_ok=True);(out/'skhy_pnl_candles.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
 template=Path(__file__).with_name('time_report_template.html').read_text()
 html=template.replace('__PAYLOAD__',json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('</','<\\/'))
 (out/'skhy_20260904_0911_10min_report.html').write_text(html)
 print('10-minute candles:',len(candles['10']),'minute marks:',len(minutes),'last trading mark:',candles['10'][-1]['c'],'expiration review:',payload['final']['gross_pnl'])
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--output-dir',type=Path);args=ap.parse_args();build(args.dir,args.output_dir or args.dir)
