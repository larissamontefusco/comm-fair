"""Dual prices from a fresh solve of the unchanged authoritative M3 LP."""
from time import perf_counter

import numpy as np

from .matching import require_close, validate_physical_input
from .results import PricingResult, physical_fingerprint


def protect_prices(marginal, grid, fit) -> tuple[list[float], list[bool], list[str]]:
    arrays = [np.asarray(x, dtype=float) for x in (marginal, grid, fit)]
    marginal, grid, fit = arrays
    if (marginal.ndim != 1 or any(x.shape != marginal.shape or not np.isfinite(x).all() for x in arrays)
            or not ((grid > fit) & (fit > 0)).all()):
        raise ValueError('Invalid marginal price or tariff arrays')
    price = np.minimum(grid, np.maximum(fit, marginal))
    directions = np.where(marginal < fit, 'to_fit', np.where(marginal > grid, 'to_grid', 'none'))
    return price.tolist(), (directions != 'none').tolist(), directions.tolist()


def price_physical(physical, config) -> PricingResult:
    """Raw balance dual is +dC/d(demand kW); lambda=raw_dual/dt, AUD/kWh.

    Sign +1 is verified by import/export marginal and finite-difference tests.
    The pricing solution never replaces the original physical dispatch.
    """
    validate_physical_input(physical, config)
    before = physical_fingerprint(physical)
    started = perf_counter()
    import highspy
    import pyomo.environ as pyo
    from pyomo.opt import SolverStatus, TerminationCondition
    from pyomo import __version__ as pyomo_version
    from comfair.physical.model import build_model

    m = build_model(physical.coalition_members, config)
    if any(v.is_integer() or v.is_binary() for v in m.component_data_objects(pyo.Var)):
        raise ValueError('M4 pricing requires the approved continuous M3 LP')
    m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    solver = pyo.SolverFactory('highs')
    if not solver.available(exception_flag=False):
        raise RuntimeError('HiGHS unavailable for pricing')
    options = physical.solver['options'].copy()
    highspy.Highs.resetGlobalScheduler(True)
    try:
        solved = solver.solve(m, options=options, tee=False, load_solutions=False)
    finally:
        highspy.Highs.resetGlobalScheduler(True)
    if solved.solver.status != SolverStatus.ok or solved.solver.termination_condition != TerminationCondition.optimal:
        raise RuntimeError(f'Pricing solve not optimal: {solved.solver.status}/{solved.solver.termination_condition}')
    m.solutions.load_from(solved)
    objective = float(pyo.value(m.cost))
    residual = require_close('Pricing objective versus M3', objective, physical.total_cost_aud,
                             config.parameters.cost_tolerance_aud)
    raw = np.array([m.dual[m.balance[t]] for t in m.T], dtype=float)
    if not np.isfinite(raw).all():
        raise ValueError('Non-finite balance dual')
    marginal = raw / config.parameters.dt_hours  # sign +1; never abs(dual).
    protected, clipped, direction = protect_prices(marginal, config.import_aud_per_kwh, config.export_aud_per_kwh)
    if physical_fingerprint(physical) != before:
        raise ValueError('Pricing mutated physical dispatch')
    info = {'name': 'highs', 'version': highspy.Highs().version(), 'pyomo_version': pyomo_version,
            'status': str(solved.solver.status), 'termination_condition': str(solved.solver.termination_condition),
            'options': options, 'dual_sign_multiplier': 1,
            'dual_units': 'AUD/kW of additional period demand',
            'normalization': 'lambda = +raw_dual / dt_hours; AUD/kWh',
            'runtime_seconds': perf_counter() - started}
    return PricingResult(raw.tolist(), marginal.tolist(), protected, clipped, direction,
                         objective, residual, before, info)
