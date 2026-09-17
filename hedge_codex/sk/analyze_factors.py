#!/usr/bin/env python3
"""Lagged, exploratory volatility-factor diagnostics; no changes to 100 shares/2 puts."""
import argparse
from datetime import datetime
import json
import hashlib
import math
from pathlib import Path
import sys
import numpy as np

NAMES={
 'log_volume':'当日成交量（对数）','rvol5':'相对成交量 RVOL5','rvol20':'相对成交量 RVOL20',
 'volume_change':'成交量较前日变化','dollar_rvol5':'相对成交金额5日',
 'abs_return':'当日绝对涨跌幅','down_return':'当日下跌幅','range_pct':'当日高低振幅',
 'gap_abs':'当日绝对跳空','atr5':'ATR5 / 股价','atr14':'ATR14 / 股价',
 'rv5':'近5日已实现波动','rv10':'近10日已实现波动','bb_width20':'布林带宽度20日',
 'distance_ma20':'偏离MA20的绝对幅度','amihud':'单位成交金额价格冲击',
 'put_cost7':'7天ATM两张Put裸保费率','put_tv7':'7天ATM时间价值率（期限归一）',
 'put_volume7':'7天ATM Put成交量（对数）',
 'SMH_abs_return':'SMH当日绝对涨跌幅','SMH_rv5':'SMH近5日波动',
 'QQQ_rv5':'QQQ近5日波动','MU_abs_return':'美光当日绝对涨跌幅',
 'MU_rv5':'美光近5日波动','SNDK_rv5':'闪迪近5日波动','DRAM_rv5':'DRAM近5日波动',
}


def basic_features(stock):
    f={};returns=[];tr=[]
    for i,row in enumerate(stock):
        dt,o,h,l,c,v=row; prev=stock[i-1][4] if i else None
        r=math.log(c/prev) if prev else None
        if r is not None:returns.append(r)
        tr.append(max(h-l,abs(h-prev),abs(l-prev)) if prev else h-l)
        x={'age':i,'log_volume':math.log(v),'range_pct':100*(h-l)/c}
        if i:
            x.update(abs_return=100*abs(r),down_return=100*max(-r,0),gap_abs=100*abs(math.log(o/prev)),
                     volume_change=100*(v/stock[i-1][5]-1),amihud=100*abs(r)/(v*c/1e6))
        for n in (5,20):
            if i>=n:
                x['rvol'+str(n)]=v/np.mean([a[5]for a in stock[i-n:i]])
        if i>=5:x['dollar_rvol5']=v*c/np.mean([a[4]*a[5]for a in stock[i-5:i]])
        for n in (5,14):
            if i>=n-1:x['atr'+str(n)]=100*np.mean(tr[-n:])/c
        for n in (5,10):
            if len(returns)>=n:x['rv'+str(n)]=100*math.sqrt(sum(z*z for z in returns[-n:]))
        if i>=19:
            prices=[a[4]for a in stock[i-19:i+1]];mid=np.mean(prices)
            x['bb_width20']=100*4*np.std(prices)/mid
            x['distance_ma20']=100*abs(c/mid-1)
        f[dt]=dict(x)
    return f


def labels(stock):
    out={}
    for i,row in enumerate(stock):
        x={};c=row[4]
        for n in (1,3,5,10):
            if i+n>=len(stock):continue
            future=stock[i+1:i+n+1]
            r=[math.log(stock[j][4]/stock[j-1][4])for j in range(i+1,i+n+1)]
            x['rv'+str(n)]=100*math.sqrt(sum(z*z for z in r))
            x['end'+str(n)]=future[-1][0]
            if n==5:
                x['range5']=100*(max(a[2]for a in future)-min(a[3]for a in future))/c
                x['endpoint5']=100*abs(future[-1][4]/c-1)
                x['close_excursion5']=100*max(abs(a[4]/c-1)for a in future)
                x['excursion5']=100*max(max(abs(a[2]/c-1),abs(a[3]/c-1))for a in future)
        out[row[0]]=x
    return out


def ranks(a):
    a=np.asarray(a);order=np.argsort(a);r=np.zeros(len(a),float);i=0
    while i<len(a):
        j=i+1
        while j<len(a)and a[order[j]]==a[order[i]]:j+=1
        r[order[i:j]]=(i+j-1)/2;i=j
    return r


def corr(x,y,spearman=True):
    if len(x)<4:return None
    x=ranks(x) if spearman else np.asarray(x,float)
    y=ranks(y) if spearman else np.asarray(y,float)
    if np.std(x)<1e-12 or np.std(y)<1e-12:return None
    return float(np.corrcoef(x,y)[0,1])


def residual_corr(rows):
    if len(rows)<10:return None
    rows=[r for r in rows if r['past_rv5'] is not None]
    if len(rows)<10:return None
    # Partial rank correlation controlling sample age and past realised volatility.
    a=np.column_stack([np.ones(len(rows)),ranks([r['age']for r in rows]),ranks([r['past_rv5']for r in rows])])
    x=ranks([r['x']for r in rows]);y=ranks([r['y']for r in rows])
    ex=x-a@np.linalg.lstsq(a,x,rcond=None)[0];ey=y-a@np.linalg.lstsq(a,y,rcond=None)[0]
    return corr(ex,ey,False)


def block_interval(rows, seed=20260914, repeats=800):
    n=len(rows)
    if n<15:return None
    rng=np.random.default_rng(seed);samples=[];block=5
    for _ in range(repeats):
        starts=rng.integers(0,n-block+1,size=math.ceil(n/block))
        idx=np.concatenate([np.arange(s,s+block)for s in starts])[:n]
        r=corr([rows[i]['x']for i in idx],[rows[i]['y']for i in idx])
        if r is not None:samples.append(r)
    return [float(z)for z in np.quantile(samples,[.025,.975])] if samples else None


def pairs(features, targets, key, outcome='rv5'):
    end_key='end'+outcome[2:] if outcome.startswith('rv')else 'end5'
    return [dict(date=dt,x=float(f[key]),y=float(targets[dt][outcome]),end=targets[dt][end_key],
                 age=f['age'],past_rv5=f.get('rv5'))
            for dt,f in features.items() if key in f and outcome in targets[dt]]


def summary(features, targets, key, boundary):
    rows=pairs(features,targets,key)
    xy=lambda rows:corr([r['x']for r in rows],[r['y']for r in rows])
    train=[r for r in rows if r['end']<=boundary]
    test=[r for r in rows if r['date']>boundary]
    # Non-overlapping forward windows. Adjacent blocks share only the boundary close.
    nonoverlap=[]
    for r in rows:
        if not nonoverlap or r['date']>=nonoverlap[-1]['end']:nonoverlap.append(r)
    interval=block_interval(rows)
    horizon={}
    for h in (1,3,5,10):
        pp=pairs(features,targets,key,'rv'+str(h));horizon[str(h)]={'rho':xy(pp),'n':len(pp)}
    threshold=float(np.median([r['x']for r in train])) if len(train)>=8 else None
    groups={}
    if threshold is not None:
        for name,rs in [('train',train),('test',test)]:
            hi=[r['y']for r in rs if r['x']>=threshold];lo=[r['y']for r in rs if r['x']<threshold]
            groups[name]=dict(high_n=len(hi),low_n=len(lo),high_mean=float(np.mean(hi))if hi else None,
                              low_mean=float(np.mean(lo))if lo else None)
    return dict(key=key,name=NAMES[key],n=len(rows),rho=xy(rows),pearson=corr([r['x']for r in rows],[r['y']for r in rows],False),
                interval=interval,train_rho=xy(train),train_n=len(train),test_rho=xy(test),test_n=len(test),
                exclude_first10=xy([r for r in rows if r['age']>=10]),partial_age_rv5=residual_corr(rows),
                partial_n=sum(r['past_rv5']is not None for r in rows),
                matched_raw_rho=xy([r for r in rows if r['past_rv5']is not None]),
                nonoverlap_rho=xy(nonoverlap),nonoverlap_n=len(nonoverlap),horizons=horizon,
                range_rho=xy(pairs(features,targets,key,'range5')),
                endpoint_rho=xy(pairs(features,targets,key,'endpoint5')),
                close_excursion_rho=xy(pairs(features,targets,key,'close_excursion5')),
                threshold=threshold,groups=groups,pairs=rows)


def compute(project, markets):
    data=json.loads((project/'data/SKHY_put_history.json').read_text())
    results=json.loads((project/'results.json').read_text());base=results['results'][1]
    assert base['config']['puts']==2
    stock=data['stock'];f=basic_features(stock);target=labels(stock)
    for ticker,rows in markets['stocks'].items():
        local=basic_features(rows)
        for dt,x in f.items():
            for metric in ('rv5','abs_return'):
                key=ticker+'_'+metric
                if key in NAMES and metric in local.get(dt,{}):x[key]=local[dt][metric]
    sys.path.insert(0,str(project))
    from backtest_audited import Config,pick
    option_snapshots={}
    for row in stock:
        dt,c=row[0],row[4]
        chosen=pick(data,dt,dt,c,Config(target=7,puts=2))
        if chosen is None:continue
        t,p=chosen;con=data['contracts'][t];b=data['history'][t][dt]
        days=(datetime.fromisoformat(con['expiration_date'])-datetime.fromisoformat(dt)).days
        f[dt]['put_cost7']=200*p/(100*c)*100
        f[dt]['put_tv7']=200*max(p-max(con['strike_price']-c,0),0)/(100*c)*100*math.sqrt(7/days)
        f[dt]['put_volume7']=math.log(b['v'])
        option_snapshots[dt]=dict(ticker=t,price=p,expiry=con['expiration_date'],strike=con['strike_price'],dte=days)
    stats=[summary(f,target,k,results['boundary'])for k in NAMES]
    # Descriptive association within actual executed 2-put rounds. No deleting rounds or reselecting parameters.
    round_rows=[]
    closes={r[0]:r[4]for r in stock}
    for t in base['trades']:
        signal=t['signal_date'];x=f[signal];pnl=(closes[t['exit_date']]-t['entry_spot'])*100+t['pnl']
        round_rows.append(dict(signal=signal,entry=t['entry_date'],exit=t['exit_date'],mark_only=t['mark_only'],
                         rvol5=x.get('rvol5'),rv5=x.get('rv5'),atr5=x.get('atr5'),
                         cost_pct=t['cost']/(100*t['entry_spot'])*100,
                         round_pnl=pnl,put_pnl=t['pnl']))
    round_associations=[]
    for key in ('rvol5','rv5','atr5'):
        rows=[r for r in round_rows if not r['mark_only'] and r[key] is not None]
        round_associations.append(dict(key=key,n=len(rows),rho=corr([r[key]for r in rows],[r['round_pnl']for r in rows])))
    peer=[]
    for ticker,rows in markets['stocks'].items():
        pf=basic_features(rows);pt=labels(rows)
        peer.append(dict(ticker=ticker,n_bars=len(rows),start=rows[0][0],end=rows[-1][0],
             factors={k:dict(n=len(pairs(pf,pt,k)),rho=corr([r['x']for r in pairs(pf,pt,k)],[r['y']for r in pairs(pf,pt,k)]))for k in ('rvol5','range_pct','rv5')}))
    # Association with today's range, to distinguish contemporaneous from future information.
    volume_same={k:corr([x[k]for x in f.values()if k in x],[x['range_pct']for x in f.values()if k in x])for k in ('log_volume','rvol5','rvol20')}
    latest=stock[-1][0];latest_values=[]
    for k in NAMES:
        prior=[x[k]for dt,x in f.items()if dt<latest and k in x]
        v=f[latest].get(k)
        latest_values.append(dict(key=k,name=NAMES[k],value=v,
                         percentile=100*sum(z<=v for z in prior)/len(prior)if v is not None and prior else None))
    return dict(manifest={'asof':latest,'shares':100,'puts':2,'stock_n':len(stock),'boundary':results['boundary'],
                         'dataset_sha256':hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),
                         'market_data':markets['manifest'],'factor_count':len(stats),'main_target':'next 5 trading-day sqrt(sum(log returns squared))*100; not annualised',
                         'bootstrap':'moving blocks of 5 observations, 800 repeats, seed 20260914; descriptive, not multiple-testing corrected'},
                stats=stats,features=f,targets=target,rounds=round_rows,round_associations=round_associations,
                peers=peer,volume_same_day=volume_same,latest=latest_values,option_snapshots=option_snapshots)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent)
    ap.add_argument('--market-data',type=Path)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args();markets=json.loads((args.market_data or args.project_dir/'data/factor_market_data.json').read_text())
    a=compute(args.project_dir,markets);out=args.output or args.project_dir/'factor_analysis.json'
    out.write_text(json.dumps(a,ensure_ascii=False,indent=2,allow_nan=False))
    for r in sorted(a['stats'],key=lambda r:abs(r['rho']or 0),reverse=True):
        print(r['key'],'n',r['n'],'rho',r['rho'],'train',r['train_rho'],'test',r['test_rho'],'partial',r['partial_age_rv5'])
    print('Wrote',out)


if __name__=='__main__':main()
