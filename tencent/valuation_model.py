"""Tencent research model. Amounts and share counts in RMB 100 million and 100 million shares.
All forecasts are analyst assumptions; historical inputs have citations in the report.
"""
from datetime import date
from pathlib import Path
import json

PRICE = 425.80
FX = 1 / 1.1725  # 2026-10-12 CNY/HKD quote, convert to RMB per HKD
AS_OF = date(2026, 10, 13)
SHARES = 92.0  # conservative diluted equity denominator, a model assumption
segments = [3692.81, 1449.73, 2294.35, 80.77]
forecast = []
for year, growth, margin, finance, nci, investment, shares, sbc in [
    (2026, [.09,.20,.085,.08], .36, -10, 40, 250, 92, 240),
    (2027, [.09,.17,.10,.05], .36, -30, 45, 260, 91, 250),
    (2028, [.08,.15,.10,.05], .37, -40, 50, 280, 90, 260),
]:
    segments = [v*(1+g) for v,g in zip(segments, growth)]
    revenue = sum(segments)
    operating = revenue*margin
    tax = (operating+finance)*.20
    core = operating+finance-tax-nci
    profit = core+investment
    forecast.append(dict(year=year, segments=segments.copy(), revenue=revenue,
        margin=margin, operating=operating, finance=finance, tax=tax, nci=nci,
        core=core, investment=investment, profit=profit, shares=shares, sbc=sbc,
        eps=profit/shares, economic_eps=(profit-sbc)/shares))

cash_assumptions = dict(
    core_profit=[2600,2930,3200,3450,3700],
    depreciation_amortisation=[1000,1100,1200,1300,1400],
    reinvestment_including_compute_prepayments=[1950,1900,1700,1650,1650],
    other_working_capital=[100,150,150,150,150],
    media_and_lease_payments=[300,320,330,350,360],
    economic_sbc_reserve=[250,260,270,280,290],
)
cf = [cash_assumptions['core_profit'][i]+cash_assumptions['depreciation_amortisation'][i]
    -cash_assumptions['reinvestment_including_compute_prepayments'][i]
    -cash_assumptions['other_working_capital'][i]
    -cash_assumptions['media_and_lease_payments'][i]
    -cash_assumptions['economic_sbc_reserve'][i] for i in range(5)]
listed, unlisted, excess_cash = 4872*.85, 3879*.60, 200
assets=listed+unlisted+excess_cash
def dcf(r=.10,g=.03, flows=None, asset_value=assets):
    flows=flows or cf
    times=[(date(y,12,31)-AS_OF).days/365 for y in range(2027,2032)]
    stub_t=(date(2026,12,31)-AS_OF).days/365
    stub=-100/(1+r)**stub_t  # remaining 2026 owner cash flow assumption
    pv=sum(c/(1+r)**t for c,t in zip(flows,times))
    terminal=flows[-1]*(1+g)/(r-g)/(1+r)**times[-1]
    core=stub+pv+terminal
    return dict(core=core,explicit=stub+pv,terminal=terminal,assets=asset_value,
        value=core+asset_value,price=(core+asset_value)/SHARES/FX,
        terminal_share=terminal/core)

economic_eps=forecast[1]['economic_eps']
pe=economic_eps*15/FX
sotp=( (forecast[1]['core']-250)*15+assets )/SHARES/FX
cash_value=dcf()['price']
weighted=pe*.4+cash_value*.4+sotp*.2
current_equity=PRICE*SHARES*FX
lo,hi=.01,5
for _ in range(80):
    k=(lo+hi)/2
    if dcf(flows=[x*k for x in cf])['value']>current_equity: hi=k
    else: lo=k
reverse_scale=(lo+hi)/2
investment_asset_sensitivity = []
for label, listed_ratio, unlisted_ratio in [
    ('wider_discount', .70, .40), ('base', .85, .60), ('narrower_discount', .95, .80),
]:
    portfolio_nav = 4872*listed_ratio + 3879*unlisted_ratio
    scenario_assets = portfolio_nav + excess_cash
    scenario_dcf = dcf(asset_value=scenario_assets)['price']
    scenario_sotp = ((forecast[1]['core']-250)*15+scenario_assets)/SHARES/FX
    investment_asset_sensitivity.append(dict(
        label=label, listed_ratio=listed_ratio, unlisted_ratio=unlisted_ratio,
        investment_nav=portfolio_nav, investment_per_share=portfolio_nav/SHARES/FX,
        dcf_price=scenario_dcf, sotp_price=scenario_sotp,
        weighted_price=pe*.4+scenario_dcf*.4+scenario_sotp*.2,
    ))
# Holding counts are from dated issuer disclosures; constant-holding illustrations,
# not an October portfolio certification and not added to the June aggregate NAV.
holding_value_illustrations_usd_100m = dict(
    pdd=783468116/4*81.96/1e8,
    sea=104264743*95.93/1e8,
    spotify_affiliated_gross=16631969*527.45/1e8,
    spotify_wholly_owned_entities=12355769*527.45/1e8,
)
out=dict(price=PRICE,fx=FX,valuation_shares=SHARES,forecast=forecast,
    cash_assumptions=cash_assumptions,cash_flows=cf,
    assets=dict(listed=listed,unlisted=unlisted,excess_cash=excess_cash,total=assets),
    investment_asset_sensitivity=investment_asset_sensitivity,
    holding_value_illustrations_usd_100m=holding_value_illustrations_usd_100m,
    investment_asset_stress_per_share=dict(
        listed_value_down_20pct=4872*.20*.85/SHARES/FX,
        unlisted_book_down_30pct=3879*.30*.60/SHARES/FX,
        net_asset_plus_1000=1000/SHARES/FX,
        weighted_net_asset_plus_1000=.60*1000/SHARES/FX),
    dcf=dcf(),pe_price=pe,sotp_price=sotp,weighted_price=weighted,
    reverse_dcf_scale=reverse_scale,reverse_terminal_cf=cf[-1]*reverse_scale,
    dcf_sensitivity=[[dcf(r,g)['price'] for g in [.02,.03,.04]] for r in [.09,.10,.11]],
    pe_sensitivity=[[eps*m/FX for m in [12,15,18]] for eps in [25,28.635,33]],
)
Path(__file__).with_name('valuation_model.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2))
