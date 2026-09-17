import unittest
from dataclasses import replace
from backtest_audited import Config,run
from backtest_straddle import run_straddle,cash_interest


def fixture():
    days=['2026-07-13','2026-07-14','2026-07-15','2026-07-16','2026-07-17']
    pt='O:SKHY260717P00100000';ct='O:SKHY260717C00100000'
    d=dict(stock=[[t,100,101,99,100,10000]for t in days],listed={t:[pt]for t in days},
        contracts={pt:dict(strike_price=100,expiration_date=days[-1])},history={pt:{t:dict(c=3,v=100)for t in days}})
    c=dict(listed={t:[ct]for t in days},history={ct:{t:dict(c=3,v=100)for t in days}})
    return d,c,pt,ct


class StraddleTests(unittest.TestCase):
    def test_same_initial_capital_and_cash_plus_two_assets(self):
        d,c,_,_=fixture();r=run_straddle(d,c)
        self.assertEqual(r['initial'],run(d)['initial'])
        for row in r['curve']:self.assertAlmostEqual(row['equity'],row['cash']+row['call_value']+row['put_value'])
        self.assertAlmostEqual(r['pnl'],r['call_pnl']+r['put_pnl'])

    def test_no_call_means_no_naked_put_entry(self):
        d,c,p,t=fixture();c['listed']={}
        r=run_straddle(d,c);self.assertFalse(r['trades']);self.assertEqual(r['pnl'],0)

    def test_missing_exit_defers_both_legs(self):
        d,c,p,t=fixture();d['stock'][2][4]=120
        del c['history'][t]['2026-07-16']
        r=run_straddle(d,c)
        self.assertEqual(r['skipped']['deferred_exit'],1)
        self.assertEqual(r['trades'][0]['exit_date'],'2026-07-17')

    def test_expiry_needs_no_quote_and_leaves_no_stock(self):
        d,c,p,t=fixture();d['stock'][-1][4]=110
        del c['history'][t]['2026-07-17'];del d['history'][p]['2026-07-17']
        r=run_straddle(d,c)
        self.assertAlmostEqual(r['trades'][0]['income'],993.5)
        self.assertEqual(r['curve'][-1]['equity'],r['curve'][-1]['cash'])

    def test_flat_price_parity_when_fees_aligned(self):
        d,c,p,t=fixture();cfg=replace(Config(),stock_bps=0)
        self.assertAlmostEqual(run_straddle(d,c,cfg)['pnl'],run(d,cfg)['pnl'])

    def test_signal_is_lagged(self):
        d,c,p,t=fixture();d['stock'][2][4]=120
        r=run_straddle(d,c)
        self.assertEqual(r['trades'][0]['exit_date'],'2026-07-16')

    def test_interest_zero_and_fixed_cash_interest(self):
        d,c,p,t=fixture();c['listed']={};r=run_straddle(d,c)
        self.assertEqual(cash_interest(r,0)['pnl'],r['pnl'])
        expected=r['initial']*((1+.04/365)**4-1)
        self.assertAlmostEqual(cash_interest(r,.04)['interest'],expected)


if __name__=='__main__':unittest.main()
