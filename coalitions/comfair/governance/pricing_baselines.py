"""Reprice unchanged M4 quantities, preserving grid/fixed bill components."""
import math


def reprice(m4, rule, dt, tolerance):
    h=m4['hourly'];grid=h['grid_tariff_aud_per_kwh'];fit=h['fit_aud_per_kwh']
    if len(grid)!=len(fit) or not grid or dt<=0:
        raise ValueError('Invalid price horizon/duration')
    if rule=='protected':price=h['protected_price_aud_per_kwh']
    elif rule=='midpoint':price=[.5*(g+f) for g,f in zip(grid,fit)]
    elif rule=='lower':price=list(fit)
    elif rule=='upper':price=list(grid)
    else:raise ValueError('Unknown price rule')
    if len(price)!=len(grid) or any(not math.isfinite(p) or p<f or p>g for p,f,g in zip(price,fit,grid)):
        raise ValueError('Invalid/protection-violating price')
    bills={};benefits={};local_total=0.;local_rows={}
    quantities=m4['member_hourly']
    if set(quantities)!=set(m4['members']):raise ValueError('Missing member clearing quantities')
    for member,row in sorted(m4['members'].items(),key=lambda x:int(x[0])):
        q=quantities[member];buy=q['local_buy_kw'];sell=q['local_sell_kw']
        if len(buy)!=len(price) or len(sell)!=len(price) or any(not math.isfinite(x) or x<0 for x in buy+sell):
            raise ValueError('Invalid member local quantities')
        payment=sum(p*(b-s)*dt for p,b,s in zip(price,buy,sell))
        fixed_grid=row['fixed_fee_aud']+row['grid_import_charge_aud']-row['grid_export_revenue_aud']
        cost=fixed_grid+payment
        if rule=='protected':
            if abs(cost-row['C_market_aud'])>tolerance:raise ValueError('M4 protected reconstruction failed')
            cost=row['C_market_aud']  # Authoritative value, after independent reconstruction.
        bills[int(member)]=cost
        benefits[int(member)]=row['u0_aud'] if rule=='protected' else row['B_i_aud']-cost
        local_total+=payment;local_rows[member]=payment
    hourly_balance=max(abs(sum(quantities[i]['local_buy_kw'][t]-quantities[i]['local_sell_kw'][t] for i in quantities)) for t in range(len(price)))
    revenue=sum(bills.values())-m4['kpis']['C_N_aud']
    if abs(local_total)>tolerance or abs(revenue)>tolerance or hourly_balance*max(price)*dt>tolerance:
        raise ValueError('Price settlement clearing/revenue adequacy failed')
    return benefits, {'rule':rule,'price_aud_per_kwh':price,'bills_aud':bills,
        'local_payments_aud':local_rows,'local_payment_residual_aud':local_total,
        'revenue_adequacy_residual_aud':revenue,'maximum_local_clearing_residual_kw':hourly_balance,
        'quantities_source':'unchanged M4 member_hourly; no redispatch'}
