"""Official M4 run: python -m comfair.market.run_market --output PATH."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from comfair.data import load_benchmark
from comfair.physical import config_from_benchmark, solve_physical
from comfair.physical.config import canonical_json
from .matching import require_close
from .settlement import settle_market

DEFAULT_BASELINE = Path(__file__).resolve().parents[1] / 'artifacts' / 'm3_baselines.json'


def source_hash(directory: Path) -> str:
    h = sha256()
    for path in sorted(directory.glob('*.py')):
        h.update(path.name.encode() + b'\0' + path.read_bytes())
    return h.hexdigest()


def validate_baseline(baseline: dict, physical, config) -> dict[int, float]:
    """Reject stale, inconsistent or incompatible M3 artifacts before using B_i."""
    tol = config.parameters.cost_tolerance_aud
    if baseline['schema_version'] != 1 or baseline['milestone'] != 'M3' or baseline['currency'] != 'AUD':
        raise ValueError('Invalid M3 artifact schema')
    current = physical.provenance
    saved = baseline['provenance']
    for key in ('input_sha256', 'registry_sha256', 'workbook_sha256', 'parameters', 'billing_days', 'solver_configuration_used'):
        if saved[key] != current[key]:
            raise ValueError(f'M3 baseline provenance mismatch: {key}')
    from comfair import physical as package
    if saved['physical_source_sha256'] != source_hash(Path(package.__file__).parent):
        raise ValueError('M3 physical source hash mismatch')
    standalone = {int(i): value for i, value in baseline['B_i_aud'].items()}
    if (set(standalone) != set(config.member_ids) or len(standalone) != len(baseline['B_i_aud'])
            or not all(np.isfinite(v) for v in standalone.values())):
        raise ValueError('Invalid M3 standalone member costs')
    if not baseline['validation']['all_solves_optimal'] or not baseline['validation']['all_dispatch_checks_passed']:
        raise ValueError('M3 artifact was not validated')
    if len(baseline['B0']) != len(standalone):
        raise ValueError('M3 artifact has missing singleton records')
    seen = set()
    for record in baseline['B0']:
        if len(record['coalition_members']) != 1:
            raise ValueError('M3 B0 must contain singleton records')
        i = record['coalition_members'][0]
        if i in seen or i not in standalone:
            raise ValueError('M3 B0 members duplicated or unknown')
        seen.add(i)
        if record['solver']['status'] != 'ok' or record['solver']['termination_condition'] != 'optimal':
            raise ValueError('M3 standalone record not optimal')
        require_close('M3 B_i consistency', record['total_cost_aud'], standalone[i], tol)
    for key in ('name', 'version', 'pyomo_version', 'options'):
        if baseline['B1']['solver'][key] != physical.solver[key]:
            raise ValueError(f'M3 solver provenance mismatch: {key}')
    require_close('M3 grand objective', physical.total_cost_aud, baseline['C_N_aud'], tol)
    require_close('M3 B1 objective consistency', baseline['B1']['total_cost_aud'], baseline['C_N_aud'], tol)
    require_close('M3 B0 sum', sum(standalone.values()), baseline['sum_B_i_aud'], tol)
    require_close('M3 surplus', sum(standalone.values()) - physical.total_cost_aud, baseline['v_N_aud'], tol)
    # Catch changed alternate-optimum dispatch aggregates as well as changed cost.
    for key, value in physical.kpis.items():
        threshold = config.parameters.flow_tolerance_kw if key.endswith('_kw') else config.parameters.energy_tolerance_kwh
        require_close('M3 physical KPI ' + key, value, baseline['B1']['kpis'][key], threshold)
    return standalone


def run_market(baseline_path=DEFAULT_BASELINE) -> tuple[dict, dict]:
    started = perf_counter()
    baseline_path = Path(baseline_path)
    baseline_bytes = baseline_path.read_bytes()
    baseline = json.loads(baseline_bytes)
    data = load_benchmark()
    config = config_from_benchmark(data)
    physical = solve_physical(config.member_ids, config)
    standalone = validate_baseline(baseline, physical, config)
    result = settle_market(physical, config, standalone)
    require_close('Official market total benefit versus M3', result.kpis['total_benefit_aud'],
                  baseline['v_N_aud'], config.parameters.cost_tolerance_aud)
    if baseline_path.read_bytes() != baseline_bytes:
        raise ValueError('M3 artifact changed during M4 run')
    if sha256(Path(data.workbook_path).read_bytes()).hexdigest() != data.workbook_sha256:
        raise ValueError('Workbook changed during M4 run')
    artifact = result.to_dict(include_runtime=False)
    artifact['milestone'] = 'M4'
    artifact['currency'] = 'AUD'
    artifact['provenance'].update({'m3_artifact_sha256': sha256(baseline_bytes).hexdigest(),
                                   'm3_artifact_filename': baseline_path.name,
                                   'market_source_sha256': source_hash(Path(__file__).parent),
                                   'physical_diagnostics': physical.diagnostics})
    runtime = {'physical_solve_seconds': physical.solver['runtime_seconds'],
               'pricing_pass_seconds': result.pricing['runtime_seconds'],
               'total_seconds': perf_counter() - started,
               'scope': 'Total includes ingestion, physical solve, provenance checks, pricing, matching, settlement and audits; excludes file writes.'}
    return artifact, runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    artifact, runtime = run_market(args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime_path = args.output.with_suffix('.runtime.json')
    artifact['runtime_diagnostics_file'] = runtime_path.name
    encoded = canonical_json(artifact)
    runtime['artifact_sha256'] = sha256(encoded.encode()).hexdigest()
    args.output.write_text(encoded)
    runtime_path.write_text(canonical_json(runtime))
    print(canonical_json({'kpis': artifact['kpis'], 'diagnostics': artifact['diagnostics'], 'runtime': runtime}))


if __name__ == '__main__':
    main()
