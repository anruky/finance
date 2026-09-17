import json, unittest, math
from pathlib import Path
from backtest_straddle import run_straddle
from capital_report import annualize
ROOT=Path('/Users/gavinz/git/finance/hedge_codex/sk')
class CapitalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=json.loads((ROOT/'data/SKHY_put_history.json').read_text());cls.calls=json.loads((ROOT/'data/SKHY_call_history.json').read_text())
 def test_legacy_unchanged(self):
  r=run_straddle(self.data,self.calls)
  self.assertAlmostEqual(r['pnl'],2156.0355);self.assertAlmostEqual(r['mdd_pct'],13.990166772342437)
 def test_unit_is_fully_funded_and_matches_original_schedule(self):
  old=run_straddle(self.data,self.calls);r=run_straddle(self.data,self.calls,initial_capital=old['trades'][0]['cost'])
  self.assertEqual(r['skipped']['cash'],0)
  self.assertEqual([(t['put'],t['entry_date'],t['exit_date']) for t in old['trades']],[(t['put'],t['entry_date'],t['exit_date']) for t in r['trades']])
  self.assertAlmostEqual(r['pnl'],old['pnl']);self.assertGreaterEqual(r['cash_min'],-1e-8)
  annualize(r,r['trades'][0]['entry_date'])
  self.assertEqual(r['calendar_days'],58)
  self.assertAlmostEqual(r['ending_equity']/(1+r['annualized_pct']/100)**(58/365),r['initial'])
 def test_full_budget_and_accounting(self):
  r=run_straddle(self.data,self.calls,all_in=True)
  self.assertEqual(r['trades'][0]['pairs'],10)
  self.assertAlmostEqual(r['pnl'],-20386.8005)
  self.assertGreaterEqual(r['cash_min'],-1e-8)
  self.assertGreater(len(set(t['pairs'] for t in r['trades'])),1)
  for x in r['curve']:self.assertAlmostEqual(x['equity'],x['cash']+x['call_value']+x['put_value'])
  cash=r['initial']
  for t in r['trades']:
   self.assertEqual(t['pairs'],int((cash+1e-9)/t['unit_cost']))
   self.assertAlmostEqual(t['cost'],t['unit_cost']*t['pairs'])
   cash+=t['income']-t['cost']
  self.assertAlmostEqual(cash,r['curve'][-1]['equity'])
 def test_fixed_ten_and_insufficient_cash(self):
  one=run_straddle(self.data,self.calls)
  r=run_straddle(self.data,self.calls,fixed_pairs=10)
  self.assertEqual(len(r['trades']),14)
  self.assertTrue(all(t['pairs']==10 for t in r['trades']))
  self.assertAlmostEqual(r['pnl'],10*one['pnl'])
  self.assertEqual(r['skipped']['cash'],0)
  self.assertGreaterEqual(r['cash_min'],0)
  for row in r['curve']:
   self.assertAlmostEqual(row['equity'],row['cash']+row['call_value']+row['put_value'])
  poor=run_straddle(self.data,self.calls,initial_capital=2082.10,fixed_pairs=10)
  self.assertGreater(poor['skipped']['cash'],0)
  self.assertGreaterEqual(poor['cash_min'],0)
  self.assertTrue(all(t['pairs']==10 for t in poor['trades']))
 def test_unaffordable_no_borrowing(self):
  r=run_straddle(self.data,self.calls,initial_capital=.01,all_in=True)
  self.assertEqual(r['trades'],[]);self.assertGreater(r['skipped']['cash'],0);self.assertEqual(r['pnl'],0)
if __name__=='__main__':unittest.main()
