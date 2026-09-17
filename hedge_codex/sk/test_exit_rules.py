# -*- coding: utf-8 -*-
import unittest,copy,json
from pathlib import Path
from exit_rules import reason,features,candidates,morning_liquidation
from backtest_intraday import run_intraday
from test_intraday import fixture,P,C
class ExitTests(unittest.TestCase):
 def pos(self):return dict(entry_date='2026-07-13',entry_spot=100,expiry='2026-07-17',put=P,call=C,cost=6000)
 def test_threshold_boundary(self):
  p=self.pos();d=fixture();rule=dict(family='threshold',up=7,down=5)
  self.assertEqual(reason(rule,d,'2026-07-14',p,107,{},1,.02),'上涨滚动')
  self.assertIsNone(reason(rule,d,'2026-07-14',p,106.99,{},1,.02))
  self.assertEqual(reason(rule,d,'2026-07-14',p,95,{},1,.02),'下跌滚动')
 def test_time_exit(self):
  self.assertEqual(reason(dict(family='time',max_age=1),fixture(),'2026-07-14',self.pos(),100,{},1,.02),'持仓时间上限')
 def test_option_signal_does_not_read_future_minute(self):
  d=fixture();rule=dict(family='option_roi',take_profit=.2)
  d['minutes'][C]['2026-07-14']['10:00']['c']=100
  self.assertIsNone(reason(rule,d,'2026-07-14',self.pos(),100,{},1,.02))
  d['minutes'][C]['2026-07-14']['09:59']['c']=6
  self.assertEqual(reason(rule,d,'2026-07-14',self.pos(),100,{},1,.02),'组合利润止盈')
 def test_atr_and_volume(self):
  self.assertEqual(reason(dict(family='atr',atr_down=1,atr_up=.5),fixture(),'2026-07-14',self.pos(),104,dict(atr_pct=8),1,.02),'上涨滚动')
  self.assertEqual(reason(dict(family='volume_reversal',rvol=1.5,min_move=2),fixture(),'2026-07-14',self.pos(),103,dict(rvol=2,morning_return=-.01),1,.02),'放量反向波动')
 def test_missing_pre_signal_option_data_is_not_backfilled(self):
  d=fixture();del d['minutes'][C]['2026-07-14']['09:59']
  self.assertIsNone(morning_liquidation(d,'2026-07-14',self.pos(),1,.02))
 def test_predeclared_rule_count(self):self.assertEqual(len(candidates()),129)
 def test_future_suffix_cannot_change_earlier_features_or_curve(self):
  root=Path('/Users/gavinz/git/finance/hedge_codex/sk');d=json.loads((root/'data/SKHY_intraday.json').read_text())
  short=dict(d,stock=d['stock'][:31]);f=features(d);fs=features(short)
  self.assertEqual(fs,{k:f[k] for k in fs})
  rule=dict(family='atr',atr_down=1,atr_up=.5)
  long=run_intraday(d,1,allow_topup=True,exit_rule=rule,feature_map=f)
  early=run_intraday(short,1,allow_topup=True,exit_rule=rule,feature_map=fs)
  self.assertEqual(long['curve'][:31],early['curve'])
 def test_default_regression(self):
  root=Path('/Users/gavinz/git/finance/hedge_codex/sk');d=json.loads((root/'data/SKHY_intraday.json').read_text())
  r=run_intraday(d,1,allow_topup=True)
  self.assertAlmostEqual(r['pnl'],-25928.4);self.assertAlmostEqual(r['additional_deposits'],15035.9)
if __name__=='__main__':unittest.main()
