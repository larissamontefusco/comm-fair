"""Reproduce official B0/B1: python -m comfair.physical.run_baselines --output PATH."""
import argparse
from hashlib import sha256
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

from comfair.data import load_benchmark
from .config import canonical_json, config_from_benchmark
from .solver import solve_physical


def run_baselines(workbook_path=None) -> tuple[dict, dict]:
    start = perf_counter()
    data = load_benchmark(workbook_path)
    config = config_from_benchmark(data)
    results = []
    for i in config.member_ids:
        result = solve_physical({i}, config)
        results.append(result)
        print(f'B0 member {i}: {result.total_cost_aud:.9f} AUD ({result.solver["runtime_seconds"]:.2f}s)', file=sys.stderr)
    grand = solve_physical(config.member_ids, config)
    print(f'B1: {grand.total_cost_aud:.9f} AUD ({grand.solver["runtime_seconds"]:.2f}s)', file=sys.stderr)
    p = config.parameters
    summed_b0 = sum(r.total_cost_aud for r in results)
    # A concrete feasible grand-pool schedule: retain all singleton asset dispatch,
    # net their grid flows. Fixed fees are identical, netting cannot increase cost.
    net = np.sum([np.subtract(r.grid_import_kw, r.grid_export_kw) for r in results], axis=0)
    feasible_imp, feasible_exp = np.maximum(net, 0), np.maximum(-net, 0)
    feasible_cost = float(np.dot(config.import_aud_per_kwh, feasible_imp) -
                          np.dot(config.export_aud_per_kwh, feasible_exp)) * p.dt_hours + grand.fixed_connection_cost_aud
    from .results import audit_dispatch
    aggregated_members = {i: r.members[i] for i, r in zip(config.member_ids, results)}
    _, feasible_diagnostics = audit_dispatch(config, aggregated_members, feasible_imp, feasible_exp)
    if (grand.total_cost_aud > feasible_cost + p.cost_tolerance_aud
            or feasible_cost > summed_b0 + p.cost_tolerance_aud):
        raise ValueError('B1/feasible aggregation/summed B0 dominance validation failed')
    if feasible_diagnostics['max_energy_balance_residual_kwh'] > p.energy_tolerance_kwh:
        raise ValueError('Aggregated singleton schedule violates balance')
    if sha256(Path(data.workbook_path).read_bytes()).hexdigest() != data.workbook_sha256:
        raise ValueError('Workbook hash changed during run')
    source_dir = Path(__file__).parent
    source_hash = sha256()
    for path in sorted(source_dir.glob('*.py')):
        source_hash.update(path.name.encode() + b'\0' + path.read_bytes())
    provenance = grand.provenance | {'physical_source_sha256': source_hash.hexdigest()}
    def summary(r):
        record = r.to_dict(include_dispatch=False, include_runtime=False)
        record.pop('provenance')  # One identical full-config provenance for every S.
        return record
    artifact = {
        'schema_version': 1, 'milestone': 'M3', 'currency': 'AUD', 'provenance': provenance,
        'B_i_aud': {str(r.coalition_members[0]): r.total_cost_aud for r in results},
        'sum_B_i_aud': summed_b0, 'C_N_aud': grand.total_cost_aud,
        'v_N_aud': summed_b0 - grand.total_cost_aud,
        'B0': [summary(r) for r in results], 'B1': summary(grand),
        'validation': {'all_solves_optimal': True, 'all_dispatch_checks_passed': True,
                       'feasible_aggregation_cost_aud': feasible_cost,
                       'feasible_aggregation_max_energy_residual_kwh': feasible_diagnostics['max_energy_balance_residual_kwh'],
                       'B1_no_worse_than_feasible_aggregation': True,
                       'workbook_hash_unchanged': True},
        'runtime_note': 'Measured runtimes are in the adjacent .runtime.json file; excluded here for deterministic artifact bytes.',
    }
    runtime = {'B0_seconds': {str(r.coalition_members[0]): r.solver['runtime_seconds'] for r in results},
               'B1_seconds': grand.solver['runtime_seconds'], 'total_seconds': perf_counter() - start,
               'scope': 'Per-solve runtime includes model construction, solver and extraction; total includes ingestion and audits.'}
    return artifact, runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workbook', type=Path)
    args = parser.parse_args()
    artifact, runtime = run_baselines(args.workbook)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime_path = args.output.with_suffix('.runtime.json')
    artifact['runtime_diagnostics_file'] = runtime_path.name
    encoded = canonical_json(artifact)
    runtime['artifact_sha256'] = sha256(encoded.encode()).hexdigest()
    args.output.write_text(encoded)
    runtime_path.write_text(canonical_json(runtime))
    print(f'v(N): {artifact["v_N_aud"]:.9f} AUD; artifact: {args.output}', file=sys.stderr)


if __name__ == '__main__':
    main()
