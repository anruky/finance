"""Mark open wheel positions to daily option closes; rolling one-year return."""
import json
from pathlib import Path
from datetime import datetime,timedelta,timezone
import sys
import qqq_biweekly_backtest as m

def build_valuation(data_dir, result, allow_network=True):
    root=Path(data_dir)
    stock=json.load(open(root/'QQQ_stock.json'));prices={s[0]:s for s in stock}
    chains={c['date']:c for c in json.load(open(root/'QQQ_options_2wk.json'))}
    cache_path=root/'qqq_valuation_quotes.json'
    cache=json.load(open(cache_path)) if cache_path.exists() else {}
    def quote(expiry, cp, strike, day):
        tk=f"QQQ{expiry[2:4]}{expiry[5:7]}{expiry[8:10]}{cp}{int(round(strike*1000)):08d}"
        key=day+'|'+tk
        if key not in cache:
            if not allow_network:raise ValueError('Missing option close '+key)
            sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
            import data_puller as p
            import requests
            success=False
            for host in ['https://api.polygon.io','https://api.massive.com']:
                try:
                    response=requests.get(host+f'/v2/aggs/ticker/O:{tk}/range/1/day/{day}/{day}',params={'apiKey':p.API_KEY,'adjusted':'false'},timeout=25)
                    if response.status_code==200:
                        payload=response.json();bars=payload.get('results',[])
                        if bars:
                            cache[key]={'close':bars[0]['c'],'request_id':payload.get('request_id'),'provider':'Polygon/Massive','date':day,'ticker':tk,'bar':bars[0]}
                            success=True;break
                except requests.RequestException:pass
            if not success:raise ValueError('No option close available '+key)
        return cache[key]['close']
    def equity(day):
        completed=[c for c in result['cycle_list'] if c['expiry']<=day]
        prev=completed[-1] if completed else None
        start_value=prev['value_raw'] if prev else result['initial']
        if prev and prev['expiry']==day:return {'date':day,'equity':start_value,'open_options':False}
        entry=prev['expiry'] if prev else result['start']
        chain=chains.get(entry)
        if not chain or not (entry<day<chain['expiry']):raise ValueError('No active cycle for valuation '+day)
        target=m.make_targets(20,6,10,15)[prev['state'] if prev else 'A']
        put=m.find_real_put(chain['puts'],target['put'],chain['dte'],chain['spot'])
        call=m.find_real_call(chain['calls'],target['call'],chain['dte'],chain['spot'])
        cash=start_value-100*chain['spot']+100*(put['prem']+call['prem'])
        put_close=quote(chain['expiry'],'P',put['strike'],day)
        call_close=quote(chain['expiry'],'C',call['strike'],day)
        long_value=0;hedge_cost=0
        hits=[s for s in stock if entry<s[0]<=day and s[2]>=call['strike']]
        if hits:
            hedge=m.find_call_prem_near(chain['calls'],round(call['strike']/m.strike_step(chain['spot']))*m.strike_step(chain['spot']))
            if hedge is None:raise ValueError('No hedge entry quote')
            hedge_cost=300*hedge['prem'];cash-=hedge_cost
            long_value=300*quote(chain['expiry'],'C',hedge['strike'],day)
        liabilities=100*(put_close+call_close)
        value=cash+100*prices[day][4]-liabilities+long_value
        return {'date':day,'equity':value,'open_options':True,'entry':entry,'expiry':chain['expiry'],'cash':cash,'shares':100,'stock_close':prices[day][4],'put_strike':put['strike'],'call_strike':call['strike'],'put_close':put_close,'call_close':call_close,'short_option_liability':liabilities,'hedge_cost':hedge_cost,'hedge_market_value':long_value,'hedge_trigger_date':hits[0][0] if hits else None}
    end_day=stock[-1][0];d=datetime.strptime(end_day,'%Y-%m-%d')
    try:base_target=d.replace(year=d.year-1).strftime('%Y-%m-%d')
    except ValueError:base_target=d.replace(year=d.year-1,day=28).strftime('%Y-%m-%d')
    base_day=max(day for day in prices if day<=base_target)
    begin=equity(base_day);end=equity(end_day)
    output={'as_of':end_day,'requested_year_start':base_target,'start':begin,'end':end,'one_year_return_pct':(end['equity']/begin['equity']-1)*100,'method':'One-year change in existing strategy equity including open-option close marks; no restart; non-trading anniversary uses preceding trading close. Hedge entry costs retain original entry-day VWAP convention.','retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
    cache_path.write_text(json.dumps(cache,ensure_ascii=False,indent=2))
    (root/'qqq_biweekly_valuation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    return output
