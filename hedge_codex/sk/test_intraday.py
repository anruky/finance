# -*- coding: utf-8 -*-
import unittest,copy
from backtest_intraday import run_intraday,choose,execution,xirr
P='O:SKHY260717P00100000';C=P[:-9]+'C'+P[-8:]
def fixture():
 dates=['2026-07-13','2026-07-14','2026-07-17']
 bar=lambda p:dict(o=p,c=p,v=20)
 return dict(stock=[[d,100,100,100,100,1000] for d in dates],stock_minutes={d:{'09:59':bar(100),'10:00':bar(100)} for d in dates},
  contracts={P:dict(strike_price=100,expiration_date='2026-07-17')},candidates={d:[P] for d in dates[:-1]},
  minutes={t:{d:{'09:59':bar(3),'10:00':bar(3)} for d in dates} for t in (P,C)},daily={t:{d:bar(3) for d in dates} for t in (P,C)})
class Tests(unittest.TestCase):
 def test_simultaneous_stock_and_options_and_round_trip_fees(self):
  d=fixture();r=run_intraday(d,2,slip=0)
  t=r['trades'][0]
  self.assertEqual(t['entry_date'],'2026-07-13');self.assertEqual(t['exit_time'],'10:00')
  self.assertAlmostEqual(t['stock_cost'],10005);self.assertAlmostEqual(t['stock_income'],9995)
  self.assertAlmostEqual(t['stock_pnl'],-10);self.assertAlmostEqual(t['put_pnl'],-6.6)
  self.assertAlmostEqual(r['pnl'],-16.6)
 def test_no_close_price_execution_and_no_call_no_partial_entry(self):
  d=fixture();del d['minutes'][C]['2026-07-13']['10:00']
  r=run_intraday(d,1)
  self.assertEqual(r['trades'][0]['entry_date'],'2026-07-14')
  self.assertEqual(r['curve'][0]['equity'],r['initial'])
 def test_trigger_at_ten_uses_information_available_then(self):
  d=fixture();d['stock_minutes']['2026-07-14']['09:59']['c']=109
  d['stock_minutes']['2026-07-14']['10:00']['o']=110
  d['stock'][1][4]=80
  r=run_intraday(d,2)
  self.assertEqual(r['trades'][0]['reason'],'上涨滚动');self.assertEqual(r['trades'][0]['exit_spot'],110)
 def test_no_future_volume_filter(self):
  d=fixture();d['minutes'][C]['2026-07-13']['09:59']['v']=0;d['minutes'][C]['2026-07-13']['10:00']['v']=100000
  self.assertIsNone(choose(d,'2026-07-13'))
 def test_missing_exit_defers_entire_stock_combo(self):
  d=fixture();d['stock_minutes']['2026-07-14']['09:59']['c']=109;del d['minutes'][P]['2026-07-14']['10:00']
  r=run_intraday(d,2);self.assertEqual(r['skipped']['no_exit_minute'],1)
  self.assertEqual(r['trades'][0]['exit_date'],'2026-07-17')
 def test_expiry_missing_execution_is_explicit_exception(self):
  d=fixture();del d['minutes'][P]['2026-07-17']['10:00']
  r=run_intraday(d,2);self.assertEqual(r['flags']['expiry_close_fallback'],1)
  self.assertEqual(r['trades'][0]['exit_time'],'16:00 settlement')
 def test_insufficient_cash_never_partial_position(self):
  d=fixture();r=run_intraday(d,2,initial=500)
  self.assertEqual(r['trades'],[]);self.assertEqual(r['pnl'],0)
 def test_earliest_common_minute_and_window_limit(self):
  d=fixture();dt='2026-07-13'
  del d['minutes'][C][dt]['10:00']
  for hm in ['10:01','10:02','10:06']:
   d['stock_minutes'][dt][hm]=dict(o=100,c=100,v=100)
   d['minutes'][C][dt][hm]=dict(o=3,c=3,v=10)
  d['minutes'][P][dt]['10:02']=dict(o=4,c=4,v=10)
  self.assertEqual(execution(d,dt,P,1)[0],'10:02')
  self.assertIsNone(execution(d,dt,P,1,window=1))
  self.assertEqual(run_intraday(d,1)['trades'][0]['entry_time'],'10:02')
 def test_reentry_never_precedes_exit(self):
  d=fixture();dt='2026-07-14';d['stock_minutes'][dt]['09:59']['c']=109
  for hm in ['10:01','10:02']:
   d['stock_minutes'][dt][hm]=dict(o=109,c=109,v=100)
   for t in (P,C):d['minutes'][t][dt][hm]=dict(o=3,c=3,v=20)
  r=run_intraday(d,2)
  self.assertEqual(r['trades'][0]['exit_time'],'10:00')
  self.assertEqual(r['trades'][1]['entry_time'],'10:01')
 def test_deposits_are_not_profit_and_do_not_jump_nav(self):
  d=fixture();r=run_intraday(d,1,initial=100,allow_topup=True)
  self.assertEqual(r['skipped']['cash'],0)
  self.assertEqual(len(r['deposits']),1)
  self.assertAlmostEqual(r['total_deposits'],r['trades'][0]['cost'])
  self.assertAlmostEqual(r['pnl'],r['curve'][-1]['equity']-r['total_deposits'])
  self.assertAlmostEqual(r['curve'][0]['unit_nav'],6000/r['total_deposits'])
  self.assertLess(r['curve'][0]['unit_nav'],1)
 def test_xirr_matches_known_cashflows(self):
  self.assertAlmostEqual(xirr(1000,'2025-01-01',[],1100,'2026-01-01'),10)
  from datetime import date
  dt='2025-07-01';days=(date(2026,1,1)-date.fromisoformat(dt)).days
  end=1100+500*1.1**(days/365)
  self.assertAlmostEqual(xirr(1000,'2025-01-01',[dict(date=dt,amount=500)],end,'2026-01-01'),10)
 def test_window_crosses_hour_and_does_not_backdate(self):
  d=fixture();dt='2026-07-13'
  del d['minutes'][C][dt]['10:00']
  for t in (P,C):d['minutes'][t][dt]['11:02']=dict(o=3,c=3,v=20)
  d['stock_minutes'][dt]['11:02']=dict(o=100,c=100,v=100)
  self.assertIsNone(execution(d,dt,P,1,window=61))
  self.assertEqual(execution(d,dt,P,1,window=359)[0],'11:02')
  self.assertIsNone(execution(d,dt,P,1,start=63,window=359))
 def test_ten_contracts_and_reconciliation(self):
  d=fixture();r=run_intraday(d,1)
  self.assertEqual(r['trades'][0]['pairs'],10)
  self.assertAlmostEqual(r['pnl'],sum(t['pnl'] for t in r['trades']))
  for row in r['curve']:self.assertAlmostEqual(row['equity'],sum(row[k] for k in ['cash','stock_value','call_value','put_value']))
if __name__=='__main__':unittest.main()
