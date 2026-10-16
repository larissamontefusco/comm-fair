"""Annual source audit and canonical target arrays, with origin-bounded history."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import csv

import numpy as np

from .schemas import MEMBERS, TARGETS
from .splits import split_metadata

BACKEND = Path(__file__).resolve().parents[2]
READER = BACKEND / 'reader'
INPUTS = BACKEND / 'inputs'
WORKBOOK_HASH = 'c559bd7dc946b2f0c01c8cc96beea75c783f3b48bdd7fe6da855b2ef01f75370'
# Preserve the application's published CSV locations as validation references.
# Scientific targets come from the workbook and the unchanged full-precision M3 proxy.
LOAD_SOURCE = INPUTS / 'com_energy_consumption.csv'
PV_SOURCE = INPUTS / 'com_energy_production.csv'


def file_record(path):
    path = Path(path)
    return {'path': 'backend/' + str(path.relative_to(BACKEND)),
            'sha256': sha256(path.read_bytes()).hexdigest()}


@dataclass
class History:
    origin_t: int
    values: np.ndarray  # (origin_t, 9): contains no future target observations.

    def validate(self):
        if (type(self.origin_t) is not int or self.origin_t < 0
                or self.values.shape != (self.origin_t, 9)
                or not np.isfinite(self.values).all() or (self.values < 0).any()):
            raise ValueError('Invalid history or observations beyond origin')


@dataclass
class ForecastDataset:
    load_kw: np.ndarray
    pv_available_kw: np.ndarray
    member_ids: tuple[int, ...]
    zero_pv_members: tuple[int, ...]
    provenance: dict

    def validate(self):
        if self.member_ids != MEMBERS:
            raise ValueError('Member mapping/order must be 1..9')
        if tuple(sorted(set(self.zero_pv_members))) != self.zero_pv_members or any(i not in MEMBERS for i in self.zero_pv_members):
            raise ValueError('Invalid zero-PV members')
        for a in (self.load_kw, self.pv_available_kw):
            if a.shape != (8760, 9) or not np.isfinite(a).all() or (a < 0).any():
                raise ValueError('Annual targets require finite nonnegative shape (8760,9)')
        if any(np.any(self.pv_available_kw[:, i - 1] != 0) for i in self.zero_pv_members):
            raise ValueError('Nonzero PV for a member without PV capacity')

    def history(self, target, origin_t):
        if target not in TARGETS or type(origin_t) is not int or not 0 <= origin_t <= 8760:
            raise ValueError('Invalid target/origin')
        # Copy before handing data to a forecaster. No full-series reference escapes.
        values = getattr(self, target)[:origin_t].copy()
        values.flags.writeable = False
        result = History(origin_t, values)
        result.validate()
        return result


def read_wide_csv(path):
    with Path(path).open(newline='') as stream:
        rows = list(csv.reader(stream))
    expected = ['timestamp'] + [f'member_{i}' for i in MEMBERS]
    if not rows or rows[0] != expected or len(rows) != 8761 or any(len(r) != 10 for r in rows[1:]):
        raise ValueError('Unexpected source rows/member columns')
    stamps = [r[0] for r in rows[1:]]
    parsed = [datetime.fromisoformat(s) for s in stamps]
    if len(set(stamps)) != 8760 or any(b - a != timedelta(hours=1) for a, b in zip(parsed, parsed[1:])):
        raise ValueError('Duplicate/misaligned synthetic transport timestamps')
    try:
        values = np.array([[float(v) for v in r[1:]] for r in rows[1:]])
    except ValueError as exc:
        raise ValueError('Missing or nonnumeric target') from exc
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError('Nonfinite or negative source target')
    return values, stamps


def load_forecasting_data():
    from comfair.data import load_benchmark
    from comfair.physical.config import load_baseline
    from comfair.physical.pv import pv_availability

    data = load_benchmark(READER / 'ComErgy Benchmark Dataset 2026.xlsx')
    if data.workbook_sha256 != WORKBOOK_HASH:
        raise ValueError('Official workbook hash mismatch')
    load, lt = read_wide_csv(LOAD_SOURCE)
    pv_csv, pt = read_wide_csv(PV_SOURCE)
    if lt != pt:
        raise ValueError('Load/PV ordinal alignment failed')
    if not np.array_equal(load, data.demand_hourly):
        raise ValueError('Consumption differs from validated workbook')
    params, _ = load_baseline()
    pv = np.column_stack([pv_availability(data.ghi_w_per_m2, data.temperature_c,
                         data.members[i].dgs.pv_modules, params) for i in MEMBERS])
    if not np.array_equal(pv_csv, np.round(pv, 3)):
        raise ValueError('PV CSV is not the verified three-decimal M3 proxy')
    zero = tuple(i for i in MEMBERS if data.members[i].dgs.pv_modules == 0)
    sources = {'load_csv': file_record(LOAD_SOURCE), 'pv_csv': file_record(PV_SOURCE),
               'workbook': file_record(Path(data.workbook_path)),
               'load_reader': file_record(READER / 'read_ec_consumption.py'),
               'pv_reader': file_record(READER / 'read_ec_production.py'),
               'pv_proxy': file_record(BACKEND / 'comfair/physical/pv.py'),
               'physical_config': file_record(BACKEND / 'comfair/physical/config.py'),
               'assumptions': file_record(BACKEND / 'comfair/config/assumptions.yaml'),
               'forecasting_loader': file_record(Path(__file__))}
    audit = {'schema_version': 1, 'status': 'PASS', 'sources': sources,
             'workbook_sha256': data.workbook_sha256,
             'member_ids': list(MEMBERS),
             'columns': ['timestamp'] + [f'member_{i}' for i in MEMBERS],
             'shapes': {'load_csv': [8760, 10], 'pv_csv': [8760, 10], 'each_target': [8760, 9]},
             'targets': list(TARGETS), 'units': {t: 'kW' for t in TARGETS},
             'missing_counts': {t: 0 for t in TARGETS}, 'nonfinite_counts': {t: 0 for t in TARGETS},
             'negative_counts': {t: 0 for t in TARGETS}, 'duplicate_time_rows': 0,
             'repeated_value_vectors': {'load': 8760 - len(np.unique(load, axis=0)),
                                        'pv': 8760 - len(np.unique(pv_csv, axis=0))},
             'zero_pv_members': list(zero),
             'time_contract': {'first_t': 0, 'last_t': 8759, 'resolution_hours': 1,
                               'timestamp_semantics': 'synthetic transport/display only',
                               'synthetic_first': lt[0], 'synthetic_last': lt[-1]},
             'split_contract': split_metadata(),
             'alignment_checks': {'load_pv_member_columns_identical': True,
                                  'transport_timestamps_identical': True,
                                  'load_matches_workbook_exactly': True,
                                  'pv_csv_matches_rounded_m3': True},
             'canonical_pv': {'source': 'M3_FULL_PRECISION',
                              'definition': 'unchanged M3 pv_availability, full precision',
                              'canonical_sources': ['workbook', 'pv_proxy', 'physical_config', 'assumptions'],
                              'csv_role': 'validation/reference only; not the canonical target',
                              'csv_relation': 'pv_csv == round(pv_m3_full_precision, 3)',
                              'csv_max_difference_kw': float(abs(pv_csv - pv).max()),
                              'csv_differing_cells': int(np.count_nonzero(pv_csv - pv))},
             'warnings': ['Synthetic 2025 is not factual calendar evidence.',
                          'PV CSV is rounded to 3 decimals; canonical target reuses exact M3 proxy.',
                          'Repeated numeric vectors (including night PV zeros) are valid, not duplicate time rows.',
                          'Realised weather constructs evaluation targets only, never future operational features.']}
    dataset = ForecastDataset(data.demand_hourly.copy(), pv, MEMBERS, zero,
                              {'sources': sources, 'target_definition': audit['canonical_pv']})
    dataset.validate()
    return dataset, audit
