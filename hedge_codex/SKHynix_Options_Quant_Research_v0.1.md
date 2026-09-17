# SK Hynix / U.S. Options Quant Research --- Working Notes v0.1

> Purpose: turn our discussion into a living specification for a
> research/monitoring program.\
> This is an initial draft and should be updated as the model develops.

## 1. Core research objective

Build a systematic framework for estimating how known future events and
unexpected news may affect SK Hynix-related U.S. trading instruments,
especially the probability and direction of price moves.

The system should separate: - event probability; - expected direction; -
expected magnitude of the stock move; - actual market reaction after the
event; - post-event review and model calibration.

## 2. First event-prediction sample

We agreed to preserve the pre-event forecast rather than revise it after
seeing the result, so it can be used as a genuine calibration sample.

Initial four-way forecast: - Large rise (close-to-close \>= +5%): 12% -
Small rise (0% to +5%): 30% - Small decline (0% to -5%): 40% - Large
decline (\<= -5%): 18%

Therefore: - Absolute move \>= 5%: 30% - Absolute move \< 5%: 70%

The largest single branch in this first estimate is a small decline
(40%).

After the event, record: 1. what actually happened; 2. whether direction
was wrong; 3. whether volatility/magnitude was wrong; 4. which
assumptions or information sources should be recalibrated.

## 3. News/event-source monitoring

Goal: detect original information as early as practical instead of
relying only on later media reports.

Potential source layers:

### Layer A --- Original / primary sources

-   Relevant X accounts
-   Company investor-relations releases
-   Official company announcements
-   Regulatory filings
-   Government/regulatory announcements
-   Relevant executives or industry participants

### Layer B --- Rapid confirmation

-   Major financial news wires and reputable financial media
-   Used to verify the original report and understand market
    interpretation

### Layer C --- Industry-chain information

Monitor important related companies and themes, including: -
memory/HBM; - AI accelerators; - major customers; - competitors; -
semiconductor supply chain.

Each captured item should eventually contain: - source; - original
timestamp; - entity/company; - headline/text; - relevance to SK Hynix; -
novelty; - expected direction; - expected magnitude; - confidence; -
confirmation status.

## 4. Options strategy being researched

Two structures discussed:

### Structure A

-   Long 100 shares
-   Long 2 puts near ATM / slightly OTM

### Structure B

-   Long 1 put near ATM / slightly OTM
-   Long 1 call near ATM / slightly OTM

Research the practical equivalence/differences using put-call parity
while accounting for: - strike mismatch; - stock price; - option
premiums; - interest/cash yield; - dividends where relevant; - bid/ask
spreads; - execution costs; - implied volatility/skew.

For the user's simplified weekly decision process, small
interest/dividend effects may initially be ignored, but the full model
should retain the ability to include them.

## 5. Critical research area: time decay and early exit

The current simple exit logic is approximately: - close early after a
sufficiently large upward stock move (currently around +8%); - close
early after a sufficiently large downward stock move (currently around
-15%).

This is intentionally recognized as too coarse because it does not
adequately model option mark-to-market value before expiration.

The improved model must explicitly study: - theta/time decay; -
days/hours to expiration; - delta; - gamma; - vega; - implied-volatility
changes; - bid/ask spread; - stock movement; - option mark-to-market
value; - total portfolio P&L; - early-exit P&L versus holding to
expiration.

Important hypothesis to test: A relatively small stock move early in the
holding period may already create a profitable mark-to-market exit
because substantial option time value remains. The same stock move very
close to expiration may produce a very different result.

Do not assume this hypothesis is always true; test it using actual
option-chain data.

## 6. Path-dependent exit model

Instead of only asking, "Where is the stock at expiration?", model the
full path.

For each observation time, calculate: - current stock price; - stock
return since entry; - remaining DTE; - current put/call bid, ask,
midpoint and last; - current implied volatility; - Greeks where
available; - mark-to-market value of each leg; - total strategy P&L; -
percentage return on premium/risk capital; - estimated slippage if
closed immediately.

Then test exit rules such as: - close when total portfolio profit
reaches X%; - close when absolute stock move reaches X%; - close when a
profit target is reached before a certain DTE; - close after a
volatility spike; - dynamic thresholds based on remaining time; -
compare closing now versus expected value of continuing to hold.

## 7. High-priority TODO: real-time data collector

Build a monitoring program before attempting fully automated execution.

Initial target: - poll the underlying and relevant option chain
approximately every 30 seconds during U.S. trading hours; - save the
observations to a historical database; - calculate current strategy
mark-to-market P&L; - trigger an alert when configured conditions are
met; - user manually executes the trade at Firstrade initially.

Data to store: - timestamp; - underlying bid/ask/last; - option
symbol; - expiration; - strike; - put/call; - bid; - ask; - midpoint; -
last; - volume; - open interest; - implied volatility; - Greeks if
available; - portfolio mark-to-market; - event/news state.

This database will later support: - backtesting; - time-decay
analysis; - exit-rule optimization; - event studies; - comparison of
predicted versus realized volatility.

## 8. Execution architecture

Phase 1: Data collection + analytics + alerts + manual execution.

Phase 2: Paper/simulated execution and validation.

Phase 3: Only if useful and supported by a broker/API, add automated
order execution as a separate execution layer.

Keep broker execution separate from the research/model code so changing
brokers does not require rebuilding the model.

## 9. Immediate development priorities

1.  Choose reliable U.S. stock and options real-time data source.
2.  Build 30-second data collector.
3.  Define database schema.
4.  Build live portfolio P&L calculator.
5.  Add alert engine.
6.  Collect enough intraday option data for analysis.
7.  Build time-decay/path-dependent simulator.
8.  Backtest alternative early-exit rules.
9.  Add event/news-source monitor.
10. Create event-prediction log and post-event calibration workflow.

## 10. Working principle

Do not optimize only for expiration payoff.

The main research question is:

**Given the current stock move, remaining time, option prices, implied
volatility and upcoming events, is closing the position now better than
continuing to hold it under the strategy's rules?**

This document is a working specification, not a claim that any
particular strategy is profitable.
