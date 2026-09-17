# -*- coding: utf-8 -*-
import json,hashlib
from pathlib import Path
from backtest_intraday import run_intraday
from exit_rules import features,candidates

def period(result,start=0,end=None):
 curve=result['curve'];end=end or len(curve);last=curve[end-1]
 before=curve[start-1] if start else dict(equity=result['initial'],total_deposits=result['initial'],unit_nav=1)
 pnl=(last['equity']-last['total_deposits'])-(before['equity']-before['total_deposits'])
 peak=before['unit_nav'];dd=0;profit_peak=0;dollar_dd=0
 for r in curve[start:end]:
  peak=max(peak,r['unit_nav']);dd=max(dd,100*(peak-r['unit_nav'])/peak)
  cum=(r['equity']-r['total_deposits'])-(before['equity']-before['total_deposits'])
  profit_peak=max(profit_peak,cum);dollar_dd=max(dollar_dd,profit_peak-cum)
 return dict(pnl=pnl,mdd_pct=dd,profit_drawdown=dollar_dd,score=pnl-.5*dollar_dd,additional_deposits=last['total_deposits']-before['total_deposits'],unit_return_pct=100*(last['unit_nav']/before['unit_nav']-1))

def run(root,out):
 data_path=root/'data/SKHY_intraday.json';d=json.loads(data_path.read_text());feat=features(d);rules=candidates()
 results={};summaries=[];strategy2_scan=[]
 baseline=run_intraday(d,1,allow_topup=True)
 for i,rule in enumerate(rules):
  r=run_intraday(d,1,allow_topup=True,exit_rule=rule,feature_map=feat);results[rule['id']]=r
  summaries.append(dict(rule=rule,train=period(r,0,31),validation=period(r,31),full=period(r),rounds=len(r['trades'])))
  r2=run_intraday(d,2,exit_rule=rule,feature_map=feat)
  strategy2_scan.append(dict(rule=rule,train=period(r2,0,31),validation=period(r2,31),full=period(r2),rounds=len(r2['trades'])))
  if (i+1)%25==0:print('Rules completed',i+1,'/',len(rules),flush=True)
 baseline_id=next(x['id'] for x in rules if x.get('down')==15 and x.get('up')==8)
 assert abs(results[baseline_id]['pnl']-baseline['pnl'])<1e-7
 best_train=max(summaries,key=lambda x:(x['train']['pnl'],x['train']['score']))
 robust=max(summaries,key=lambda x:(x['train']['score'],x['train']['pnl']))
 best_full=max(summaries,key=lambda x:x['full']['pnl'])
 threshold_train=max((x for x in summaries if x['rule']['family']=='threshold'),key=lambda x:x['train']['score'])
 selected={v['rule']['id']:v for v in (best_train,robust,best_full,threshold_train)}
 # Actually replay a changing-rule account, preserving the live positions at fold boundaries.
 schedule={};folds=[]
 for train_end,test_end in [(20,28),(28,36),(36,44)]:
  winner=max(summaries,key=lambda x:period(results[x['rule']['id']],0,train_end)['score'])
  for row in d['stock'][train_end:test_end]:schedule[row[0]]=winner['rule']
  folds.append(dict(train_end=d['stock'][train_end-1][0],test_start=d['stock'][train_end][0],test_end=d['stock'][test_end-1][0],rule=winner['rule'],start_index=train_end,end_index=test_end))
 live=run_intraday(d,1,allow_topup=True,feature_map=feat,rule_schedule=schedule)
 for f in folds:
  f['live']=period(live,f['start_index'],f['end_index']);f['baseline']=period(baseline,f['start_index'],f['end_index'])
 details={}
 for ident,v in selected.items():
  rule=v['rule'];r=results[ident];r2=run_intraday(d,2,exit_rule=rule,feature_map=feat)
  sensitivity=[]
  for slip in (.02,.05):
   for window in (5,30,359):
    rr=run_intraday(d,1,slip=slip,window=window,allow_topup=True,exit_rule=rule,feature_map=feat)
    sensitivity.append(dict(slip=slip,window=window,full=period(rr),validation=period(rr,31),rounds=len(rr['trades']),flags=rr['flags'],skipped=rr['skipped']))
  details[ident]=dict(summary=v,strategy1=r,strategy2=r2,sensitivity=sensitivity)
 # Train-only stability map around the selected fixed thresholds.
 neighbors=[];tr=threshold_train['rule']
 dns=sorted({x['rule']['down'] for x in summaries if x['rule']['family']=='threshold'});ups=sorted({x['rule']['up'] for x in summaries if x['rule']['family']=='threshold'})
 for x in summaries:
  r=x['rule']
  if r['family']=='threshold' and abs(dns.index(r['down'])-dns.index(tr['down']))<=1 and abs(ups.index(r['up'])-ups.index(tr['up']))<=1:neighbors.append(x)
 res=dict(strategy2_scan=strategy2_scan,method=dict(n_rules=len(rules),train='2026-07-13..2026-08-24',validation='2026-08-25..2026-09-11',score='training cash-flow-neutral dollar P&L minus 0.5 times dollar drawdown of cumulative P&L',data_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),important='Validation interval already examined in prior reports; retrospective temporal validation, not untouched future OOS'),baseline=baseline,baseline_periods=dict(train=period(baseline,0,31),validation=period(baseline,31),full=period(baseline)),summaries=summaries,best_train=best_train['rule']['id'],robust=robust['rule']['id'],best_full=best_full['rule']['id'],threshold_train=threshold_train['rule']['id'],details=details,neighbors=neighbors,walkforward=dict(folds=folds,result=live,validation=period(live,20),baseline_validation=period(baseline,20)))
 out.write_text(json.dumps(res,ensure_ascii=False,indent=2,allow_nan=False))
 print('SELECTION',json.dumps({k:next(x for x in summaries if x['rule']['id']==res[k]) for k in ('best_train','robust','best_full','threshold_train')},ensure_ascii=False,indent=2))
 print('WALKFORWARD',res['walkforward']['validation'],res['walkforward']['baseline_validation'])
 return res
if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--output',type=Path);args=ap.parse_args()
 run(args.project_dir,args.output or args.project_dir/'skhy_exit_optimization_results.json')
