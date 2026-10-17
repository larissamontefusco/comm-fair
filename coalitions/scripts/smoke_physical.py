#!/usr/bin/env python3
"""Bounded synthetic physical/market smoke test; not an annual benchmark rerun."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from comfair.physical import PhysicalConfig, load_baseline, solve_physical
from comfair.market import settle_market


def main():
    parameters, provenance = load_baseline()
    config = PhysicalConfig(
        member_ids=(1, 2), demand_kw=np.array([[1., 1.], [1., 1.]]),
        pv_available_kw=np.array([[2., 0.], [0., 0.]]), battery_modules=(0, 0),
        import_aud_per_kwh=np.array([.25, .25]), export_aud_per_kwh=np.array([.05, .05]),
        billing_days=2 / 24, parameters=parameters, provenance=provenance,
    )
    standalone = {i: solve_physical({i}, config).total_cost_aud for i in config.member_ids}
    grand = solve_physical(config.member_ids, config)
    market = settle_market(grand, config, standalone)
    if grand.solver['termination_condition'] != 'optimal':
        raise RuntimeError('Physical solve was not optimal')
    if grand.total_cost_aud > sum(standalone.values()) + parameters.cost_tolerance_aud:
        raise ValueError('Synthetic cooperation dominance failed')
    print('PASS: synthetic two-member/two-hour physical LP and protected-price settlement')
    print('Solver:', grand.solver['name'], grand.solver['version'])
    print('Synthetic cooperative surplus (AUD):', sum(standalone.values()) - grand.total_cost_aud)
    print('Settlement validated:', type(market).__name__)


if __name__ == '__main__':
    main()
