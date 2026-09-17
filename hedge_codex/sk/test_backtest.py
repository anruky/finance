import copy
import unittest
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo
from backtest_audited import Config, run, metrics, pick, window_metrics
from refresh_data import last_completed_date


def fixture():
    days = ['2026-07-13', '2026-07-14', '2026-07-15', '2026-07-16', '2026-07-17']
    stock = [[d, 100, 101, 99, 100, 10000] for d in days]
    return dict(stock=stock, listed={d:['P'] for d in days},
        contracts={'P':dict(strike_price=100, expiration_date=days[-1])},
        history={'P':{d:dict(c=3, v=100) for d in days}})


class AccountingTests(unittest.TestCase):
    def cfg(self, **kw):
        return replace(Config(puts=1, slip=0, commission=0, stock_bps=0), **kw)

    def test_put_asset_offsets_premium_not_full_cost_drawdown(self):
        d = fixture(); r = run(d, self.cfg(), end='2026-07-14')
        self.assertAlmostEqual(r['curve'][-1]['put_value'], 300)
        self.assertAlmostEqual(r['pnl'], -1)  # one-cent minimum price friction
        self.assertAlmostEqual(r['reconciliation'], 0)

    def test_expiry_uses_stock_intrinsic_without_option_bar(self):
        d = fixture(); d['stock'][-1][4] = 90
        del d['history']['P']['2026-07-17']
        r = run(d, self.cfg())
        self.assertEqual(r['trades'][0]['reason'], '到期结算')
        self.assertAlmostEqual(r['trades'][0]['income'], 999)
        self.assertEqual(r['missing_marks'], 0)

    def test_missing_exit_defers_instead_of_inventing_fill(self):
        d = fixture(); d['stock'][1][4] = 110; d['stock'][2][4] = 130
        del d['history']['P']['2026-07-16']
        r = run(d, self.cfg(), end='2026-07-16')
        self.assertEqual(r['skipped']['deferred_exit'], 1)
        self.assertTrue(r['trades'][0]['mark_only'])
        self.assertFalse(r['eligible'])

    def test_future_strike_does_not_change_past_selection(self):
        d = fixture(); e = copy.deepcopy(d)
        e['contracts']['F'] = dict(strike_price=100, expiration_date='2026-07-17')
        e['history']['F'] = {'2026-07-14':dict(c=.1, v=100)}
        e['listed']['2026-07-14'].append('F')
        self.assertEqual(pick(d, '2026-07-13', '2026-07-14', 100, self.cfg()),
                         pick(e, '2026-07-13', '2026-07-14', 100, self.cfg()))

    def test_21_day_does_not_silently_use_short_expiry(self):
        self.assertIsNone(pick(fixture(), '2026-07-13', '2026-07-14', 100, self.cfg(target=21)))

    def test_real_cost_skip_preserves_stock_and_cash(self):
        d = fixture(); d['stock'][2][4] = 105
        r = run(d, self.cfg(cap=1), end='2026-07-15')
        self.assertEqual(len(r['trades']), 0)
        self.assertEqual(r['skipped']['cost_cap'], 1)
        self.assertAlmostEqual(r['pnl'], 500)

    def test_mdd_percentage_uses_each_running_peak(self):
        # Dollar MDD occurs later, while percentage MDD occurs earlier.
        m = metrics([dict(equity=x) for x in [200, 100, 1000, 800]], 100)
        self.assertEqual(m['mdd'], 200)
        self.assertEqual(m['mdd_pct'], 50)

    def test_cash_budget_prevents_unfunded_buy(self):
        r = run(fixture(), self.cfg(reserve=0))
        self.assertFalse(r['trades'])
        self.assertGreater(r['skipped']['cash'], 0)

    def test_future_data_does_not_rewrite_existing_equity(self):
        d = fixture(); r = run(d, self.cfg(), end='2026-07-15')
        d['stock'][-1][4] = 5; d['history']['P']['2026-07-17']['c'] = 95
        e = run(d, self.cfg())
        self.assertEqual(r['curve'], e['curve'][:3])

    def test_anomalous_exit_disqualifies_even_if_no_position_remains(self):
        d = fixture(); d['stock'][2][4] = 130; d['stock'][3][4] = 90
        r = run(d, self.cfg(), end='2026-07-16')
        self.assertEqual(r['execution_anomalies'], 1)
        self.assertFalse(r['eligible'])

    def test_anomalous_entry_is_flagged(self):
        d = fixture(); d['stock'][1][4] = 90
        r = run(d, self.cfg(), end='2026-07-14')
        self.assertEqual(r['execution_anomalies'], 1)
        self.assertEqual(r['async_marks'], 1)
        self.assertFalse(r['eligible'])

    def test_holdout_uses_inherited_starting_equity(self):
        r = run(fixture(), self.cfg())
        w = window_metrics(r, '2026-07-15')
        self.assertEqual(w['start_equity'], r['curve'][2]['equity'])
        self.assertAlmostEqual(w['pnl'], r['curve'][-1]['equity']-r['curve'][2]['equity'])

    def test_latest_date_before_us_open_and_after_close(self):
        self.assertEqual(last_completed_date(datetime(2026,9,14,3,0,tzinfo=ZoneInfo('America/New_York'))), '2026-09-11')
        self.assertEqual(last_completed_date(datetime(2026,9,14,17,0,tzinfo=ZoneInfo('America/New_York'))), '2026-09-14')


if __name__ == '__main__':
    unittest.main()
