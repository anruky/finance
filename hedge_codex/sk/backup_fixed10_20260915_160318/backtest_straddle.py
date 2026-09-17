"""One Call + one Put, with remaining capital in cash; prior-close decisions."""
from dataclasses import asdict
from datetime import date
from backtest_audited import Config,pick,price,metrics
from refresh_straddle_data import call_ticker


def impact(p,slip):return max(.01,p*slip)


def run_straddle(data,calls,cfg=Config(),initial_capital=None,all_in=False):
    stock=data['stock'];initial=stock[0][4]*100*(1+cfg.reserve) if initial_capital is None else initial_capital
    assert initial>0
    cash=initial;pos=None;curve=[];trades=[];fees=0.;premium=0.
    skipped=dict(no_put=0,no_call=0,no_fill=0,cash=0,deferred_exit=0)
    missing=anomalies=execution_anomalies=0
    for i,row in enumerate(stock):
        dt,S=row[0],row[4];prev=stock[i-1]if i else None
        reason=None
        if pos:
            if dt>=pos['expiry']:reason='到期结算'
            elif prev[4]<=pos['entry_spot']*(1-cfg.down/100):reason='下跌滚动'
            elif prev[4]>=pos['entry_spot']*(1+cfg.up/100):reason='上涨滚动'
            if reason:
                if reason=='到期结算':
                    cp=max(S-pos['strike'],0);pp=max(pos['strike']-S,0)
                    fee=1+S*100*cfg.stock_bps/10000 if cp+pp>0 else 0.
                    ci=100*cp-(fee if cp else 0);pi=100*pp-(fee if pp else 0)
                else:
                    cp=price(calls['history'][pos['call']].get(dt));pp=price(data['history'][pos['put']].get(dt))
                    fee=2*cfg.commission
                    if cp is None or pp is None:
                        skipped['deferred_exit']+=1
                    else:
                        ci=max(0,cp-impact(cp,cfg.slip))*100-cfg.commission
                        pi=max(0,pp-impact(pp,cfg.slip))*100-cfg.commission
                        execution_anomalies+=int(cp+.05<max(S-pos['strike'],0))+int(pp+.05<max(pos['strike']-S,0))
                if cp is not None and pp is not None:
                    ci*=pos['pairs'];pi*=pos['pairs'];fee*=pos['pairs']
                    cash+=ci+pi;fees+=fee
                    trades.append(dict(**pos,exit_date=dt,exit_spot=S,reason=reason,call_income=ci,put_income=pi,
                        income=ci+pi,pnl=ci+pi-pos['cost'],call_pnl=ci-pos['call_cost'],put_pnl=pi-pos['put_cost'],
                        exit_gap=100*(S+pp-cp-pos['strike']),mark_only=False))
                    pos=None
        if pos is None and prev:
            candidate=pick(data,prev[0],dt,prev[4],cfg)
            if candidate is None:skipped['no_put']+=1
            else:
                pt,_=candidate;ct=call_ticker(pt);con=data['contracts'][pt]
                previous=calls['history'].get(ct,{}).get(prev[0]);pc=price(previous)
                if ct not in calls['listed'].get(prev[0],[])or pc is None or previous['v']<cfg.min_volume or pc+.05<max(prev[4]-con['strike_price'],0):
                    skipped['no_call']+=1
                else:
                    cp=price(calls['history'][ct].get(dt));pp=price(data['history'][pt].get(dt))
                    if cp is None or pp is None:skipped['no_fill']+=1
                    else:
                        cc=100*(cp+impact(cp,cfg.slip))+cfg.commission
                        ppc=100*(pp+impact(pp,cfg.slip))+cfg.commission
                        pairs=int((cash+1e-9)/(cc+ppc)) if all_in else 1
                        if pairs<1 or cc+ppc>cash+1e-8:skipped['cash']+=1
                        else:
                            unit_cost=cc+ppc;cc*=pairs;ppc*=pairs
                            cash-=cc+ppc;fees+=2*cfg.commission*pairs;premium+=cc+ppc
                            execution_anomalies+=int(cp+.05<max(S-con['strike_price'],0))+int(pp+.05<max(con['strike_price']-S,0))
                            pos=dict(pairs=pairs,unit_cost=unit_cost,previous_volume=min(previous['v'],data['history'][pt][prev[0]]['v']),call=ct,put=pt,strike=con['strike_price'],expiry=con['expiration_date'],
                                signal_date=prev[0],entry_date=dt,entry_spot=S,call_cost=cc,put_cost=ppc,cost=cc+ppc,
                                last_call=cp,last_put=pp,entry_gap=100*(S+pp-cp-con['strike_price']))
        cm=pm=0.;estimated=False
        if pos:
            for leg,bundle,intrinsic in [('call',calls,max(S-pos['strike'],0)),('put',data,max(pos['strike']-S,0))]:
                q=price(bundle['history'][pos[leg]].get(dt))
                if q is None:
                    q=max(pos['last_'+leg],intrinsic);missing+=1;estimated=True
                else:
                    pos['last_'+leg]=q;anomalies+=int(q+.05<intrinsic)
                if leg=='call':cm=100*q*pos['pairs']
                else:pm=100*q*pos['pairs']
        curve.append(dict(date=dt,equity=cash+cm+pm,cash=cash,call_value=cm,put_value=pm,
                          pairs=pos['pairs'] if pos else 0,estimated=estimated,holding=pos['put']if pos else None))
    if pos:
        trades.append(dict(**pos,exit_date=stock[-1][0],exit_spot=stock[-1][4],reason='期末持有／市值',
            call_income=cm,put_income=pm,income=cm+pm,pnl=cm+pm-pos['cost'],
            call_pnl=cm-pos['call_cost'],put_pnl=pm-pos['put_cost'],
            exit_gap=100*(stock[-1][4]+pm/(100*pos['pairs'])-cm/(100*pos['pairs'])-pos['strike']),mark_only=True))
    m=metrics(curve,initial);reconciliation=m['pnl']-sum(t['pnl']for t in trades)
    assert abs(reconciliation)<1e-6
    return dict(config=asdict(cfg),name='1 Call＋1 Put＋现金',initial=initial,all_in=all_in,**m,fees=fees,premium=premium,
        cash_min=min(r['cash']for r in curve),call_pnl=sum(t['call_pnl']for t in trades),
        put_pnl=sum(t['put_pnl']for t in trades),missing_marks=missing,async_marks=anomalies,
        execution_anomalies=execution_anomalies,eligible=not(missing or anomalies or execution_anomalies),
        skipped=skipped,curve=curve,trades=trades,reconciliation=reconciliation)


def cash_interest(result,annual_rate):
    """Apply cash interest to a fixed trading path, without increasing positions."""
    interest=0.;curve=[];previous=None
    for row in result['curve']:
        if previous:
            days=(date.fromisoformat(row['date'])-date.fromisoformat(previous['date'])).days
            interest+=(previous['cash']+interest)*annual_rate*days/365
        curve.append(dict(row,equity=row['equity']+interest,cash=row['cash']+interest))
        previous=row
    return dict(rate=annual_rate,interest=interest,curve=curve,**metrics(curve,result['initial']))


def paired_rounds(data,calls,original,cfg=Config()):
    """Price both structures on the ORIGINAL exact schedule; unavailable legs stay missing."""
    closes={r[0]:r[4]for r in data['stock']};out=[]
    for old in original['trades']:
        pt=old['ticker'];ct=call_ticker(pt);entry=old['entry_date'];end=old['exit_date'];K=old['strike']
        cp=price(calls['history'].get(ct,{}).get(entry));pp=price(data['history'][pt].get(entry))
        row=dict(entry=entry,exit=end,strike=K,put=pt,call=ct,
            original_round=(closes[end]-old['entry_spot'])*100+old['pnl'],original_cost=old['cost'])
        if cp is None or pp is None:
            out.append(dict(row,available=False));continue
        c_cost=100*(cp+impact(cp,cfg.slip))+cfg.commission
        p_cost=100*(pp+impact(pp,cfg.slip))+cfg.commission
        if old['reason']=='到期结算':
            ce=max(closes[end]-K,0);pe=max(K-closes[end],0)
            fee=1+closes[end]*100*cfg.stock_bps/10000 if ce+pe>0 else 0
            income=100*(ce+pe)-fee
        else:
            ce=price(calls['history'][ct].get(end));pe=price(data['history'][pt].get(end))
            if ce is None or pe is None:
                out.append(dict(row,available=False));continue
            income=100*(ce+pe) if old['mark_only']else 100*(max(0,ce-impact(ce,cfg.slip))+max(0,pe-impact(pe,cfg.slip)))-2*cfg.commission
        entrygap=100*(old['entry_spot']+pp-cp-K);exitgap=100*(closes[end]+pe-ce-K)
        out.append(dict(row,available=True,straddle_cost=c_cost+p_cost,straddle_round=income-c_cost-p_cost,
            delta=income-c_cost-p_cost-row['original_round'],entry_gap=entrygap,exit_gap=exitgap,
            gross_structure_difference=exitgap-entrygap,mark_only=old['mark_only']))
    return out
