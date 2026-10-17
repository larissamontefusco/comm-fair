"""Serializable physical domain outputs and independently recomputed diagnostics."""
from dataclasses import asdict, dataclass

import numpy as np

from .config import canonical_json


@dataclass
class MemberDispatch:
    demand_kw: list[float]
    pv_available_kw: list[float]
    pv_used_kw: list[float]
    pv_curtailed_kw: list[float]
    battery_charge_kw: list[float]
    battery_discharge_kw: list[float]
    soc_kwh: list[float]  # T+1 states; all-zero for members without storage.


@dataclass
class PhysicalResult:
    coalition_members: tuple[int, ...]
    total_cost_aud: float
    variable_grid_cost_aud: float
    fixed_connection_cost_aud: float
    grid_import_kw: list[float]
    grid_export_kw: list[float]
    aggregate_demand_kw: list[float]
    members: dict[int, MemberDispatch]
    kpis: dict[str, float]
    diagnostics: dict
    solver: dict
    provenance: dict

    def to_dict(self, *, include_dispatch: bool = True, include_runtime: bool = True) -> dict:
        result = asdict(self)
        # Canonical JSON types, including member keys and coalition list.
        result['coalition_members'] = list(self.coalition_members)
        result['members'] = {str(i): result['members'][i] for i in sorted(self.members)}
        if not include_dispatch:
            for key in ('members', 'grid_import_kw', 'grid_export_kw', 'aggregate_demand_kw'):
                result.pop(key)
        if not include_runtime:
            result['solver'].pop('runtime_seconds', None)
        return result

    def to_json(self, *, include_runtime: bool = True) -> str:
        return canonical_json(self.to_dict(include_runtime=include_runtime))


def simultaneous_flows(a, b, tolerance_kw: float) -> dict:
    overlap = np.minimum(a, b)
    periods = np.flatnonzero(overlap > tolerance_kw)
    return {'max_overlap_kw': float(np.max(overlap, initial=0)),
            'count': int(len(periods)),
            'periods': [{'t': int(t), 'overlap_kw': float(overlap[t]),
                         'first_flow_kw': float(a[t]), 'second_flow_kw': float(b[t])}
                        for t in periods]}


def audit_dispatch(config, members, grid_import, grid_export) -> tuple[dict, dict]:
    """Reconstruct balances, bounds and endpoints from plain output arrays."""
    p = config.parameters
    t = len(grid_import)
    for flow in (grid_import, grid_export):
        if np.asarray(flow).shape != (len(config.demand_kw),) or not np.isfinite(flow).all():
            raise ValueError("Invalid grid dispatch shape or non-finite values")
    demand = np.zeros(t)
    pv_available = np.zeros(t)
    pv_used = np.zeros(t)
    charge = np.zeros(t)
    discharge = np.zeros(t)
    max_soc_residual = max_soc_bounds = max_endpoint = max_power_bounds = max_pv_bounds = 0.0
    battery_simultaneity = {}
    for i, dispatch in members.items():
        d, avail, used, ch, dis, soc = [np.asarray(getattr(dispatch, field)) for field in (
            'demand_kw', 'pv_available_kw', 'pv_used_kw', 'battery_charge_kw',
            'battery_discharge_kw', 'soc_kwh')]
        for array in (d, avail, used, ch, dis, soc):
            if not np.isfinite(array).all():
                raise ValueError("Non-finite member dispatch")
        if any(a.shape != (t,) for a in (d, avail, used, ch, dis)) or soc.shape != (t + 1,):
            raise ValueError("Invalid member dispatch shape")
        idx = config.member_ids.index(i)
        capacity = config.battery_modules[idx] * p.battery_module_kwh
        power = config.battery_modules[idx] * p.battery_module_kw
        demand += d
        pv_available += avail
        pv_used += used
        charge += ch
        discharge += dis
        max_soc_residual = max(max_soc_residual, float(np.abs(np.diff(soc) -
                               (p.eta * ch - dis / p.eta) * p.dt_hours).max()))
        max_soc_bounds = max(max_soc_bounds, float(np.maximum(capacity * p.soc_min_fraction - soc, 0).max()),
                             float(np.maximum(soc - capacity * p.soc_max_fraction, 0).max()))
        max_endpoint = max(max_endpoint, abs(float(soc[0]) - capacity * p.soc_initial_fraction),
                           abs(float(soc[-1]) - capacity * p.soc_initial_fraction))
        max_power_bounds = max(max_power_bounds, float(np.maximum(-ch, 0).max()),
                               float(np.maximum(-dis, 0).max()), float(np.maximum(ch - power, 0).max()),
                               float(np.maximum(dis - power, 0).max()))
        max_pv_bounds = max(max_pv_bounds, float(np.maximum(-used, 0).max()),
                            float(np.maximum(used - avail, 0).max()))
        battery_simultaneity[str(i)] = simultaneous_flows(ch, dis, p.flow_tolerance_kw)
    balance = np.asarray(grid_import) + pv_used + discharge - np.asarray(grid_export) - demand - charge
    energy = lambda a: float(np.sum(a) * p.dt_hours)
    kpis = {
        'demand_kwh': energy(demand), 'grid_import_kwh': energy(grid_import),
        'grid_export_kwh': energy(grid_export), 'peak_grid_import_kw': float(max(grid_import, default=0)),
        'pv_available_kwh': energy(pv_available), 'pv_used_kwh': energy(pv_used),
        'pv_curtailed_kwh': energy(pv_available - pv_used),
        'battery_charge_kwh': energy(charge), 'battery_discharge_kwh': energy(discharge),
        'battery_throughput_kwh': energy(charge + discharge),
    }
    diagnostics = {
        'max_balance_residual_kw': float(np.abs(balance).max(initial=0)),
        'max_energy_balance_residual_kwh': float(np.abs(balance).max(initial=0) * p.dt_hours),
        'max_soc_dynamics_residual_kwh': max_soc_residual,
        'max_soc_bound_violation_kwh': max_soc_bounds,
        'max_soc_endpoint_residual_kwh': max_endpoint,
        'max_battery_power_violation_kw': max_power_bounds,
        'max_pv_bound_violation_kw': max_pv_bounds,
        'max_grid_nonnegative_violation_kw': float(max(0, -min(grid_import), -min(grid_export))),
        'grid_simultaneity': simultaneous_flows(grid_import, grid_export, p.flow_tolerance_kw),
        'battery_simultaneity': battery_simultaneity,
    }
    return kpis, diagnostics


def validate_result(result: PhysicalResult, parameters) -> None:
    """Fail closed on invalid dispatch, including material simultaneous flows."""
    d = result.diagnostics
    for key, value in d.items():
        if key.startswith('max_'):
            tol = parameters.energy_tolerance_kwh if key.endswith('_kwh') else parameters.flow_tolerance_kw
            if not np.isfinite(value) or value > tol:
                raise ValueError(f'Physical validation failed: {key}={value}, tolerance={tol}')
    flows = {'grid': d['grid_simultaneity'], **d['battery_simultaneity']}
    failures = {key: value for key, value in flows.items() if value['count']}
    if failures:
        raise ValueError('Material simultaneous flows; STOP before changing LP: ' + canonical_json(failures))
    if not np.isfinite(result.total_cost_aud):
        raise ValueError('Non-finite physical cost')
