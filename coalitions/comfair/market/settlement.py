"""Baseline bills and diagnostics; negative benefits are retained unchanged."""
import numpy as np

from .matching import match_local, require_close
from .pricing import price_physical, protect_prices
from .results import (MarketResult, MemberSettlement, PRICE_TOLERANCE_AUD_PER_KWH,
                      physical_fingerprint)


def settle_market(physical, config, standalone_costs: dict[int, float], *, pricing=None) -> MarketResult:
    """Decompose a fixed physical solution and bill it at the protected LP anchor.

    standalone_costs must cover exactly the physical coalition, in AUD with the
    same assumptions. The official runner validates the M3 baseline provenance.
    """
    ids = physical.coalition_members
    if set(standalone_costs) != set(ids) or not all(np.isfinite(v) for v in standalone_costs.values()):
        raise ValueError('Standalone costs must be finite and cover exactly the coalition')
    before = physical_fingerprint(physical)
    matching = match_local(physical, config)
    price = price_physical(physical, config) if pricing is None else pricing
    if price.physical_result_sha256 != before:
        raise ValueError('Pricing/physical dispatch provenance mismatch')
    p = config.parameters
    if price.solver['status'] != 'ok' or price.solver['termination_condition'] != 'optimal':
        raise ValueError('Pricing is not optimal')
    require_close('Pricing objective', price.objective_aud, physical.total_cost_aud, p.cost_tolerance_aud)
    grid, fit = config.import_aud_per_kwh, config.export_aud_per_kwh
    lam = np.asarray(price.lambda_aud_per_kwh)
    raw = np.asarray(price.raw_dual_aud_per_kw)
    if raw.shape != grid.shape or lam.shape != grid.shape:
        raise ValueError('Pricing arrays have incorrect period count')
    require_close('Dual normalization', lam, raw / p.dt_hours, PRICE_TOLERANCE_AUD_PER_KWH)
    protected, clipped, directions = protect_prices(lam, grid, fit)
    bar = np.asarray(price.protected_price_aud_per_kwh)
    if bar.shape != grid.shape or not np.isfinite(bar).all() or ((bar < fit) | (bar > grid)).any():
        raise ValueError('Protected price bounds violated')
    require_close('Protected price reconstruction', bar, protected, PRICE_TOLERANCE_AUD_PER_KWH)
    if price.clipped != clipped or price.clipping_direction != directions:
        raise ValueError('Price clipping metadata mismatch')
    members = {}
    dt = p.dt_hours
    fixed = config.billing_days * p.daily_connection_fee_aud
    for i in ids:
        m = matching.members[i]
        gimp = float(np.dot(grid, m.grid_import_kw) * dt)
        gexp = float(np.dot(fit, m.grid_export_kw) * dt)
        buy = float(np.dot(bar, m.local_buy_kw) * dt)
        sell = float(np.dot(bar, m.local_sell_kw) * dt)
        bill = fixed + gimp - gexp + buy - sell
        benefit = float(standalone_costs[i]) - bill
        members[i] = MemberSettlement(
            float(standalone_costs[i]), fixed,
            float(np.sum(m.grid_import_kw) * dt), float(np.sum(m.grid_export_kw) * dt),
            float(np.sum(m.local_buy_kw) * dt), float(np.sum(m.local_sell_kw) * dt),
            gimp, gexp, buy, sell, bill, benefit, benefit < -p.cost_tolerance_aud)
    total = lambda field: float(sum(getattr(m, field) for m in members.values()))
    market_cost = total('C_market_aud')
    total_benefit = total('u0_aud')
    surplus_value = float(sum(standalone_costs.values()) - physical.total_cost_aud)
    bill_residual = market_cost - physical.total_cost_aud
    payment_residual = total('local_purchase_charge_aud') - total('local_sale_revenue_aud')
    benefit_residual = total_benefit - surplus_value
    for name, residual in (('Market revenue adequacy', bill_residual),
                           ('Internal payments balance', payment_residual),
                           ('Benefits versus cooperative surplus', benefit_residual)):
        require_close(name, residual, 0, p.cost_tolerance_aud)
    local_hourly_residual = bar * np.sum([
        np.subtract(m.local_buy_kw, m.local_sell_kw) for m in matching.members.values()], axis=0) * dt
    local_hourly_max = require_close('Hourly local payments', local_hourly_residual, 0, p.cost_tolerance_aud)
    benefits = {i: m.u0_aud for i, m in members.items()}
    local_energy = float(np.sum(matching.local_trade_kw) * dt)
    demand_energy = float(np.sum(physical.aggregate_demand_kw) * dt)
    count = len(bar)
    at_fit = np.isclose(bar, fit, atol=PRICE_TOLERANCE_AUD_PER_KWH, rtol=0)
    at_grid = ~at_fit & np.isclose(bar, grid, atol=PRICE_TOLERANCE_AUD_PER_KWH, rtol=0)
    interior = ~(at_fit | at_grid)
    kpis = {
        'local_energy_traded_kwh': local_energy,
        'local_trade_fraction_of_demand': local_energy / demand_energy if demand_energy else None,
        'local_trading_periods': int(np.count_nonzero(np.asarray(matching.local_trade_kw) > p.flow_tolerance_kw)),
        'protected_price_mean_aud_per_kwh': float(bar.mean()),
        'protected_price_median_aud_per_kwh': float(np.median(bar)),
        'protected_price_min_aud_per_kwh': float(bar.min()),
        'protected_price_max_aud_per_kwh': float(bar.max()),
        'total_grid_import_charges_aud': total('grid_import_charge_aud'),
        'total_fit_revenues_aud': total('grid_export_revenue_aud'),
        'total_internal_market_payments_aud': total('local_purchase_charge_aud'),
        'total_internal_market_revenues_aud': total('local_sale_revenue_aud'),
        'total_fixed_fees_aud': total('fixed_fee_aud'), 'total_market_cost_aud': market_cost,
        'C_N_aud': physical.total_cost_aud, 'total_benefit_aud': total_benefit, 'v_N_aud': surplus_value,
        'harmed_member_count': sum(m.harmed for m in members.values()),
        'maximum_individual_harm_aud': max(0.0, -min(benefits.values())),
        'minimum_u0_aud': min(benefits.values()), 'maximum_u0_aud': max(benefits.values()),
        'mean_u0_aud': float(np.mean(list(benefits.values()))),
        'worst_market_member': min(ids, key=lambda i: (benefits[i], i)),
        'best_market_member': min(ids, key=lambda i: (-benefits[i], i)),
        'revenue_adequacy_residual_aud': bill_residual,
    }
    for label, mask in (
        ('clipped_to_fit', np.asarray(directions) == 'to_fit'),
        ('clipped_to_grid', np.asarray(directions) == 'to_grid'),
        ('at_fit', at_fit), ('at_grid', at_grid), ('interior', interior),
        ('materially_clipped', np.abs(bar - lam) > PRICE_TOLERANCE_AUD_PER_KWH),
    ):
        kpis[label + '_periods'] = int(np.count_nonzero(mask))
        kpis[label + '_fraction'] = float(np.count_nonzero(mask) / count)
    diagnostics = dict(matching.diagnostics,
                       pricing_objective_residual_aud=price.objective_residual_aud,
                       local_payment_balance_residual_aud=payment_residual,
                       max_hourly_local_payment_residual_aud=local_hourly_max,
                       revenue_adequacy_residual_aud=bill_residual,
                       benefit_sum_residual_aud=benefit_residual,
                       max_price_bound_violation_aud_per_kwh=0.0)
    hourly = {'t': list(range(count)), 'raw_dual_aud_per_kw': price.raw_dual_aud_per_kw,
              'lambda_aud_per_kwh': price.lambda_aud_per_kwh,
              'protected_price_aud_per_kwh': price.protected_price_aud_per_kwh,
              'clipped': price.clipped, 'clipping_direction': price.clipping_direction,
              'grid_tariff_aud_per_kwh': grid.tolist(), 'fit_aud_per_kwh': fit.tolist(),
              'local_trade_kw': matching.local_trade_kw,
              'aggregate_deficit_kw': matching.aggregate_deficit_kw,
              'aggregate_surplus_kw': matching.aggregate_surplus_kw,
              'physical_grid_import_kw': physical.grid_import_kw.copy(),
              'physical_grid_export_kw': physical.grid_export_kw.copy()}
    if physical_fingerprint(physical) != before:
        raise ValueError('Settlement mutated physical dispatch')
    provenance = {'physical_result_sha256': before, 'physical': physical.provenance,
                  'matching_rule': 'proportional residual deficit/surplus; L=min(D,S)',
                  'matching_source': 'User-approved M4 baseline; no bids or member priority in benchmark',
                  'price_tolerance_aud_per_kwh': PRICE_TOLERANCE_AUD_PER_KWH,
                  'flow_tolerance_kw': p.flow_tolerance_kw, 'money_tolerance_aud': p.cost_tolerance_aud,
                  'fraction_definition': 'local traded kWh / aggregate demand kWh; includes storage-related residual trades',
                  'tie_break': 'lowest member ID for equal benefit', 'repair': 'not implemented'}
    return MarketResult(members, matching.members, hourly, kpis, diagnostics, price.solver.copy(), provenance)
