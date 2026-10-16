"""Explicit model assumptions and input boundary; no Pyomo dependency."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path

import numpy as np
import yaml

REGISTRY_PATH = Path(__file__).resolve().parents[1] / 'config' / 'assumptions.yaml'


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'


@dataclass(frozen=True)
class BaselineParameters:
    dt_hours: float
    benchmark_days: int
    tariff_scale: float
    daily_connection_fee_aud: float
    pv_module_kw: float
    pv_nmot_c: float
    pv_gamma_per_c: float
    pv_derating: float
    battery_module_kwh: float
    battery_module_voltage_v: float
    battery_stack_current_a: float
    battery_round_trip_efficiency: float
    soc_min_fraction: float
    soc_max_fraction: float
    soc_initial_fraction: float
    degradation_aud_per_kwh: float
    flow_tolerance_kw: float
    energy_tolerance_kwh: float
    cost_tolerance_aud: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Non-finite baseline parameter')
        positive = ('dt_hours', 'benchmark_days', 'tariff_scale', 'pv_module_kw',
                    'battery_module_kwh', 'battery_module_voltage_v',
                    'battery_stack_current_a', 'flow_tolerance_kw',
                    'energy_tolerance_kwh', 'cost_tolerance_aud')
        if any(getattr(self, key) <= 0 for key in positive):
            raise ValueError('Baseline sizes, durations and tolerances must be positive')
        if not 0 < self.battery_round_trip_efficiency < 1:
            raise ValueError('LP baseline requires inefficient battery cycling')
        if not 0 <= self.soc_min_fraction <= self.soc_initial_fraction <= self.soc_max_fraction <= 1:
            raise ValueError('Invalid SOC fractions')
        if self.daily_connection_fee_aud < 0 or not 0 < self.pv_derating <= 1:
            raise ValueError('Invalid fee or PV derating')
        if self.degradation_aud_per_kwh != 0:
            raise ValueError('M3 implements zero degradation cost only')

    @property
    def eta(self) -> float:
        return math.sqrt(self.battery_round_trip_efficiency)

    @property
    def battery_module_kw(self) -> float:
        return self.battery_module_voltage_v * self.battery_stack_current_a / 1000


def load_baseline() -> tuple[BaselineParameters, dict]:
    raw = REGISTRY_PATH.read_bytes()
    registry = yaml.safe_load(raw)
    params = BaselineParameters(**{
        key: entry['value'] for key, entry in registry['assumptions']['baseline'].items()
    })
    provenance = {
        'registry_sha256': sha256(raw).hexdigest(),
        'assumptions': registry['assumptions'],
        'solver_configuration': registry['solver'],
    }
    return params, provenance


@dataclass
class PhysicalConfig:
    """Power arrays have shape (T,N)/(T,); member order is explicit.

    billing_days is mandatory even for synthetic short horizons. The official
    adapter uses 365. Inputs are validated at each solve because arrays are mutable.
    """
    member_ids: tuple[int, ...]
    demand_kw: np.ndarray
    pv_available_kw: np.ndarray
    battery_modules: tuple[int, ...]
    import_aud_per_kwh: np.ndarray
    export_aud_per_kwh: np.ndarray
    billing_days: float
    parameters: BaselineParameters
    provenance: dict

    def validate(self) -> None:
        if (not self.member_ids or len(set(self.member_ids)) != len(self.member_ids)
                or any(type(i) is not int or i not in range(1, 10) for i in self.member_ids)):
            raise ValueError('Member IDs must be distinct integers in 1..9')
        n = len(self.member_ids)
        if self.demand_kw.ndim != 2 or self.demand_kw.shape[1] != n or not len(self.demand_kw):
            raise ValueError('Demand must have shape (T,N), T > 0')
        t = len(self.demand_kw)
        for array, shape in ((self.demand_kw, (t, n)), (self.pv_available_kw, (t, n)),
                             (self.import_aud_per_kwh, (t,)), (self.export_aud_per_kwh, (t,))):
            if array.shape != shape or not np.isfinite(array).all() or (array < 0).any():
                raise ValueError('Invalid physical array: shape, finite values or non-negativity')
        if not ((self.import_aud_per_kwh > self.export_aud_per_kwh)
                & (self.export_aud_per_kwh > 0)).all():
            raise ValueError('LP baseline requires import tariff > FIT > 0')
        if (len(self.battery_modules) != n
                or any(type(x) is not int or x < 0 for x in self.battery_modules)):
            raise ValueError('Invalid battery module counts')
        if not math.isfinite(self.billing_days) or self.billing_days < 0:
            raise ValueError('Invalid explicit billing_days')
        # Revalidate parameters even when callers construct custom synthetic cases.
        self.parameters.__post_init__()

    def result_provenance(self) -> dict:
        inputs = {
            'member_ids': self.member_ids, 'demand_kw': self.demand_kw.tolist(),
            'pv_available_kw': self.pv_available_kw.tolist(),
            'battery_modules': self.battery_modules,
            'import_aud_per_kwh': self.import_aud_per_kwh.tolist(),
            'export_aud_per_kwh': self.export_aud_per_kwh.tolist(),
            'billing_days': self.billing_days, 'parameters': asdict(self.parameters),
        }
        return {**self.provenance, 'input_sha256': sha256(canonical_json(inputs).encode()).hexdigest(),
                'parameters': asdict(self.parameters), 'billing_days': self.billing_days,
                'period_count': len(self.demand_kw), 'period_axis': 'ordinal t=0..T-1',
                'eta_charge': self.parameters.eta, 'eta_discharge': self.parameters.eta,
                'battery_module_power_kw': self.parameters.battery_module_kw}


def config_from_benchmark(data) -> PhysicalConfig:
    """Adopt approved interpretations here; leave M2 workbook data untouched."""
    from .pv import pv_availability
    data.validate()
    p, provenance = load_baseline()
    if data.daily_connection_fee != p.daily_connection_fee_aud:
        raise ValueError('Workbook fee differs from approved baseline')
    if data.period_count * p.dt_hours != p.benchmark_days * 24:
        raise ValueError('Official horizon and approved billing duration disagree')
    ids = tuple(sorted(data.members))
    pv = np.column_stack([
        pv_availability(data.ghi_w_per_m2, data.temperature_c, data.members[i].dgs.pv_modules, p)
        for i in ids
    ])
    provenance.update({'workbook_sha256': data.workbook_sha256,
                       'workbook': Path(data.workbook_path).name,
                       'sheet': data.workbook_sheet,
                       'raw_tariff_unit_status': data.tariff_unit_status,
                       'tariff_interpretation': 'Approved AUD/kWh, raw scale 1.0; original labels retained in M2'})
    config = PhysicalConfig(ids, data.demand_hourly.copy(), pv,
                            tuple(data.members[i].dgs.battery_modules for i in ids),
                            data.grid_import_tariff_raw * p.tariff_scale,
                            data.feedin_tariff_raw * p.tariff_scale,
                            p.benchmark_days, p, provenance)
    config.validate()
    return config
