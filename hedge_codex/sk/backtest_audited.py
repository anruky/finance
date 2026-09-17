"""Daily-bar research engine with lagged decisions and a self-financing ledger.

No daily aggregate is an executable quote. Results are conditional simulations,
not an implementation of the old same-open/VWAP strategy.
"""
from dataclasses import dataclass, asdict
from datetime import date
import math
import statistics


@dataclass(frozen=True)
class Config:
    target: int = 2
    down: float = 15
    up: float = 8
    puts: int = 2
    moneyness: float = 1.0
    cap: float = 0.0
    min_volume: int = 10
    trend: bool = False
    atr_trigger: bool = False
    slip: float = .02
    commission: float = .65
    stock_bps: float = 5
    reserve: float = .5

    def label(self):
        return (f'{self.puts}P · {self.target}D · 跌{self.down:g}/涨{self.up:g}'
                + (f' · {self.moneyness:.0%}行权价' if self.moneyness != 1 else '')
                + (f' · 保费≤{self.cap:g}%' if self.cap else '')
                + (' · MA20弱势' if self.trend else '')
                + (' · ATR阈值' if self.atr_trigger else ''))


def dte(expiry, day):
    return (date.fromisoformat(expiry)-date.fromisoformat(day)).days


def price(bar):
    if not bar or not isinstance(bar.get('c'), (int, float)):
        return None
    return bar['c'] if math.isfinite(bar['c']) and bar['c'] > 0 and bar.get('v', 0) > 0 else None


def metrics(curve, initial):
    peak = initial
    max_dd = max_pct = 0.
    returns = []
    prev = initial
    for row in curve:
        v = row['equity']
        peak = max(peak, v)
        max_dd = max(max_dd, peak-v)
        max_pct = max(max_pct, (peak-v)/peak if peak else 0)
        returns.append(v/prev-1 if prev else 0)
        prev = v
    pnl = (curve[-1]['equity'] if curve else initial) - initial
    return dict(pnl=pnl, return_pct=100*pnl/initial, mdd=max_dd, mdd_pct=100*max_pct,
                pnl_mdd=pnl/max_dd if max_dd else None,
                worst_day_pct=min(returns, default=0)*100)


def pick(dataset, signal_date, execution_date, spot, cfg):
    """Choose once using only contracts and trades visible on signal_date."""
    bounds = {2:(1, 7), 7:(5, 10), 14:(11, 17), 21:(18, 24)}
    lo, hi = bounds[cfg.target]
    choices = []
    for ticker in dataset['listed'].get(signal_date, []):
        contract = dataset['contracts'][ticker]
        days = dte(contract['expiration_date'], execution_date)
        if not lo <= days <= hi:
            continue
        k = contract['strike_price']
        if abs(k/(spot*cfg.moneyness)-1) > .03:
            continue
        bar = dataset['history'][ticker].get(signal_date)
        p = price(bar)
        if p is None or bar.get('v', 0) < cfg.min_volume:
            continue
        # Avoid using clearly asynchronous/invalid prints as the entry signal.
        if p + .05 < max(k-spot, 0):
            continue
        choices.append((abs(days-cfg.target), abs(k-spot*cfg.moneyness), ticker, p))
    return min(choices)[2:] if choices else None


def indicators(stock):
    ma, atr = {}, {}
    tr = []
    for i, row in enumerate(stock):
        dt, o, h, l, c, v = row
        tr.append(max(h-l, abs(h-stock[i-1][4]), abs(l-stock[i-1][4])) if i else h-l)
        ma[dt] = statistics.mean(r[4] for r in stock[i-19:i+1]) if i >= 19 else None
        atr[dt] = statistics.mean(tr[-14:])/c*100 if i >= 13 else None
    return ma, atr


def run(dataset, cfg=Config(), start=None, end=None):
    all_stock = dataset['stock']
    stock = [r for r in all_stock if (start is None or r[0] >= start) and (end is None or r[0] <= end)]
    if not stock:
        raise ValueError('Empty backtest window')
    ma, atr = indicators(all_stock)
    initial = stock[0][4]*100*(1+cfg.reserve)
    stock_cost = stock[0][4]*100*cfg.stock_bps/10000
    cash = initial-stock[0][4]*100-stock_cost
    curve, trades = [], []
    pos = None
    fees, premium = stock_cost, 0.
    skipped = dict(no_contract=0, cost_cap=0, no_fill=0, cash=0, trend=0, deferred_exit=0)
    missing_marks = async_marks = execution_anomalies = protected = 0
    skip_until = ''
    actual_dtes = []

    for i, row in enumerate(stock):
        dt, spot = row[0], row[4]
        prev = stock[i-1] if i else None
        exit_reason = None
        if pos:
            if dt >= pos['expiry']:
                exit_reason = '到期结算'
            elif prev:
                down, up = cfg.down, cfg.up
                if cfg.atr_trigger:
                    if atr[prev[0]] is not None:
                        down = min(25, max(8, 2*atr[prev[0]]))
                        up = min(25, max(8, 1.5*atr[prev[0]]))
                if prev[4] <= pos['entry_spot']*(1-down/100):
                    exit_reason = '下跌滚动'
                elif prev[4] >= pos['entry_spot']*(1+up/100):
                    exit_reason = '上涨滚动'
            if exit_reason:
                if exit_reason == '到期结算':
                    p = max(pos['strike']-spot, 0)
                    # American physical exercise: model exercise + buying back
                    # delivered stock, preserving the strategic 100-share book.
                    fee = cfg.puts*(1 + spot*100*cfg.stock_bps/10000) if p > 0 else 0.
                    income = p*100*cfg.puts-fee
                else:
                    p = price(dataset['history'][pos['ticker']].get(dt))
                    if p is None:
                        skipped['deferred_exit'] += 1
                    fee = cfg.commission*cfg.puts
                    income = max(0, p-max(.01, p*cfg.slip))*100*cfg.puts-fee if p is not None else None
                if p is not None:
                    if exit_reason != '到期结算' and p+.05 < max(pos['strike']-spot, 0):
                        execution_anomalies += 1
                    cash += income
                    fees += fee
                    trades.append(dict(**pos, exit_date=dt, reason=exit_reason, income=income,
                                       pnl=income-pos['cost'], mark_only=False))
                    pos = None

        # No first-day hedge: signals are formed after the first observed close.
        if cfg.puts and pos is None and prev and dt >= skip_until:
            if cfg.trend and (ma[prev[0]] is None or prev[4] >= ma[prev[0]]):
                skipped['trend'] += 1
            else:
                candidate = pick(dataset, prev[0], dt, prev[4], cfg)
                if candidate is None:
                    skipped['no_contract'] += 1
                else:
                    ticker, signal_p = candidate
                    con = dataset['contracts'][ticker]
                    signal_cost = (signal_p+max(.01, signal_p*cfg.slip))*100*cfg.puts+cfg.commission*cfg.puts
                    limit = prev[4]*100*cfg.cap/100 if cfg.cap else float('inf')
                    p = price(dataset['history'][ticker].get(dt))
                    if signal_cost > limit:
                        skipped['cost_cap'] += 1
                        skip_until = con['expiration_date']
                    elif p is None:
                        skipped['no_fill'] += 1
                    else:
                        cost = (p+max(.01, p*cfg.slip))*100*cfg.puts+cfg.commission*cfg.puts
                        if cost > limit:
                            # Predetermined dollar cap behaves as a limit order.
                            skipped['cost_cap'] += 1
                            skip_until = con['expiration_date']
                        elif cost > cash:
                            skipped['cash'] += 1
                        else:
                            if p+.05 < max(con['strike_price']-spot, 0):
                                execution_anomalies += 1
                            cash -= cost
                            fees += cfg.commission*cfg.puts
                            premium += cost
                            pos = dict(ticker=ticker, expiry=con['expiration_date'], strike=con['strike_price'],
                                       signal_date=prev[0], entry_date=dt, entry_spot=spot,
                                       cost=cost, last_mark=p)
                            actual_dtes.append(dte(con['expiration_date'], dt))
        mark = 0.
        estimated = False
        if pos:
            protected += 1
            p = price(dataset['history'][pos['ticker']].get(dt))
            if p is None:
                missing_marks += 1
                estimated = True
                p = max(pos['last_mark'], max(pos['strike']-spot, 0))
            else:
                pos['last_mark'] = p
                if p+.05 < max(pos['strike']-spot, 0):
                    async_marks += 1
            mark = p*100*cfg.puts
        curve.append(dict(date=dt, equity=100*spot+cash+mark, cash=cash, stock=100*spot,
                          put_value=mark, estimated=estimated,
                          holding=pos['ticker'] if pos else None))
    if pos:
        income = curve[-1]['put_value']
        trades.append(dict(**pos, exit_date=stock[-1][0], reason='期末持有／市值',
                           income=income, pnl=income-pos['cost'], mark_only=True))
    m = metrics(curve, initial)
    stock_pnl = (stock[-1][4]-stock[0][4])*100-stock_cost
    put_pnl = sum(t['pnl'] for t in trades)
    reconciliation = m['pnl']-stock_pnl-put_pnl
    if abs(reconciliation) > 1e-6:
        raise AssertionError('Ledger does not reconcile')
    return dict(config=asdict(cfg), label=cfg.label(), initial=initial, **m,
                stock_pnl=stock_pnl, put_pnl=put_pnl, fees=fees, premium=premium,
                missing_marks=missing_marks, async_marks=async_marks, execution_anomalies=execution_anomalies,
                eligible=missing_marks == 0 and async_marks == 0 and execution_anomalies == 0,
                protected_pct=100*protected/len(stock), actual_dtes=actual_dtes,
                min_cash=min(r['cash'] for r in curve), skipped=skipped,
                curve=curve, trades=trades, reconciliation=reconciliation)


def window_metrics(result, boundary):
    """Continuous portfolio change after boundary, including inherited positions."""
    before = [r for r in result['curve'] if r['date'] <= boundary]
    after = [r for r in result['curve'] if r['date'] > boundary]
    if not before or not after:
        return None
    return dict(start_equity=before[-1]['equity'], **metrics(after, before[-1]['equity']))
