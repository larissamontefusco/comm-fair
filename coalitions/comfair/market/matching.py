"""Proportional matching of the original M3 dispatch, without adjustments."""
from dataclasses import replace

import numpy as np

from comfair.physical import PhysicalConfig, PhysicalResult
from comfair.physical.results import audit_dispatch, validate_result
from .results import MatchingResult, MemberPositions


def require_close(name, actual, expected, tolerance) -> float:
    delta = np.asarray(actual) - np.asarray(expected)
    if not np.isfinite(delta).all():
        raise ValueError(f'{name}: non-finite residual')
    maximum = float(np.abs(delta).max(initial=0))
    if maximum > tolerance:
        bad = np.flatnonzero(np.abs(delta) > tolerance)
        details = [(int(t), float(delta.flat[t])) for t in bad[:20]]
        raise ValueError(f'{name}: STOP; max residual={maximum}, tolerance={tolerance}, '
                         f'violations={len(bad)}, first indices/residuals={details}')
    return maximum


def validate_physical_input(physical: PhysicalResult, config: PhysicalConfig) -> dict:
    config.validate()
    ids = physical.coalition_members
    if not ids or tuple(sorted(set(ids))) != ids or set(ids) != set(physical.members):
        raise ValueError('M4 requires a nonempty, canonical physical coalition')
    if any(i not in config.member_ids for i in ids):
        raise ValueError('Physical members not in config')
    if physical.provenance['input_sha256'] != config.result_provenance()['input_sha256']:
        raise ValueError('Physical/config input provenance mismatch')
    if physical.solver['status'] != 'ok' or physical.solver['termination_condition'] != 'optimal':
        raise ValueError('Physical solve is not optimal')
    tol = config.parameters.flow_tolerance_kw
    for i in ids:
        j = config.member_ids.index(i)
        m = physical.members[i]
        require_close('Demand/config mismatch', m.demand_kw, config.demand_kw[:, j], tol)
        require_close('PV/config mismatch', m.pv_available_kw, config.pv_available_kw[:, j], tol)
        require_close('PV curtailment reconstruction', m.pv_curtailed_kw,
                      np.subtract(m.pv_available_kw, m.pv_used_kw), tol)
    _, diagnostics = audit_dispatch(config, physical.members, physical.grid_import_kw, physical.grid_export_kw)
    validate_result(replace(physical, diagnostics=diagnostics), config.parameters)
    require_close('Aggregate demand', physical.aggregate_demand_kw,
                  np.sum([physical.members[i].demand_kw for i in ids], axis=0), tol)
    p = config.parameters
    variable = float(np.dot(config.import_aud_per_kwh, physical.grid_import_kw)
                     - np.dot(config.export_aud_per_kwh, physical.grid_export_kw)) * p.dt_hours
    fixed = len(ids) * config.billing_days * p.daily_connection_fee_aud
    for name, actual, expected in (
        ('Physical variable cost', physical.variable_grid_cost_aud, variable),
        ('Physical fixed fee', physical.fixed_connection_cost_aud, fixed),
        ('Physical total cost', physical.total_cost_aud, variable + fixed),
    ):
        require_close(name, actual, expected, p.cost_tolerance_aud)
    return diagnostics


def match_local(physical: PhysicalResult, config: PhysicalConfig) -> MatchingResult:
    """Power decomposition: r=d+ch-pv-dis, L=min(sum positive r,sum negative r)."""
    validate_physical_input(physical, config)
    ids = physical.coalition_members
    residual = np.asarray([
        np.asarray(physical.members[i].demand_kw) + physical.members[i].battery_charge_kw
        - np.asarray(physical.members[i].pv_used_kw) - physical.members[i].battery_discharge_kw
        for i in ids
    ])
    deficit, surplus = np.maximum(residual, 0), np.maximum(-residual, 0)
    D, S = deficit.sum(axis=0), surplus.sum(axis=0)
    L = np.minimum(D, S)
    buy = L * np.divide(deficit, D, out=np.zeros_like(deficit), where=D > 0)
    sell = L * np.divide(surplus, S, out=np.zeros_like(surplus), where=S > 0)
    grid_import, grid_export = deficit - buy, surplus - sell
    tol = config.parameters.flow_tolerance_kw
    diagnostics = {}
    for name, actual, expected in (
        ('max_local_buy_clearing_residual_kw', buy.sum(axis=0), L),
        ('max_local_sell_clearing_residual_kw', sell.sum(axis=0), L),
        ('max_net_local_position_residual_kw', (buy - sell).sum(axis=0), 0),
        ('max_grid_import_reconstruction_residual_kw', grid_import.sum(axis=0), physical.grid_import_kw),
        ('max_grid_export_reconstruction_residual_kw', grid_export.sum(axis=0), physical.grid_export_kw),
        ('max_member_balance_residual_kw', grid_import - grid_export + buy - sell, residual),
    ):
        diagnostics[name] = require_close(name, actual, expected, tol)
    positions = {i: MemberPositions(*[a[j].tolist() for a in (
        residual, deficit, surplus, buy, sell, buy - sell, grid_import, grid_export)])
        for j, i in enumerate(ids)}
    return MatchingResult(positions, D.tolist(), S.tolist(), L.tolist(), diagnostics)
