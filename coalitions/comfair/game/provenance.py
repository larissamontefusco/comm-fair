"""Fail-closed trusted upstream loading. No new annual physical/market solves."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import math

from comfair.data import load_benchmark
from comfair.physical import config_from_benchmark
from comfair.market.run_market import source_hash, validate_baseline
from comfair.market.matching import require_close
from comfair.physical.config import canonical_json
from .coalitions import members_to_mask

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND/'comfair/artifacts'
EXPECTED = {
    'm3_baselines.json':'767c7c1538768d8db7840194597401bc133fd8ae5c23da3d497754d7cd8997aa',
    'm4_market.json':'c8f3e274a9a7928926e80a93d33b68606b8e44fd568bc90fffea56d97c4bf54a',
    'forecasting/f0_data_audit.json':'3f1c541bec0d799284dbc8b069bbb2e79635cfebceb7aca44d181ae2597719e5',
    'forecasting/f0_baselines.json':'9b3f362bfbe35db2359288efec1b0a2c419c86d0fd8ac0828007889f370f030a',
    'forecasting/f0_predictions.csv':'35fa945bb3e1ebfb17948169da966ba3a253f1552ac5aac06c2f04f1ad857a9f',
    'forecasting/f1_champions.json':'78f77a7650b0a93c18793337dc91f4bf97aca49553b0b48c0a82225adf7dcf5c',
    'forecasting/f1_leaderboard.json':'05ea271c1f0cbcbcbc800971224fd2fa26919547852de1e1e8c9f4e805976743',
    'forecasting/f1_test_results.json':'de0ced800ea3c178941da5a70e97efd50b6e491fe8727a2f8e23f0a263a81559',
}
WORKBOOK_SHA256 = 'c559bd7dc946b2f0c01c8cc96beea75c783f3b48bdd7fe6da855b2ef01f75370'


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(data):
    return sha256(canonical_json(data).encode()).hexdigest()


def verify_artifacts(root=ARTIFACTS):
    for name, expected in EXPECTED.items():
        if digest(root/name) != expected:
            raise ValueError(f'Frozen upstream hash mismatch: {name}')


def solver_information():
    import highspy
    from pyomo import __version__
    from comfair.physical.config import load_baseline
    _, provenance = load_baseline()
    s = provenance['solver_configuration']
    return {'name':'highs', 'version':highspy.Highs().version(), 'pyomo_version':__version__,
            'options':{'solver':s['algorithm'],'threads':s['threads'],'random_seed':s['random_seed'],
                       'primal_feasibility_tolerance':s['primal_feasibility_tolerance'],
                       'dual_feasibility_tolerance':s['dual_feasibility_tolerance']}}


def compact_validation(summary, parameters):
    """Validate saved diagnostics, including required fields, before compacting."""
    d = summary['diagnostics']
    fields = ('max_balance_residual_kw','max_energy_balance_residual_kwh',
              'max_soc_dynamics_residual_kwh','max_soc_bound_violation_kwh',
              'max_soc_endpoint_residual_kwh','max_battery_power_violation_kw',
              'max_pv_bound_violation_kw','max_grid_nonnegative_violation_kw',
              'objective_reconstruction_residual_aud')
    result = {'optimal':True}
    for key in fields:
        value = d[key]
        tol = (parameters.cost_tolerance_aud if key.endswith('_aud') else
               parameters.energy_tolerance_kwh if key.endswith('_kwh') else parameters.flow_tolerance_kw)
        if not math.isfinite(value) or not 0 <= value <= tol:
            raise ValueError(f'Invalid physical diagnostic {key}={value}')
        result[key] = value
    flows = [d['grid_simultaneity'], *d['battery_simultaneity'].values()]
    if set(d['battery_simultaneity']) != {str(i) for i in summary['coalition_members']}:
        raise ValueError('Missing member simultaneity diagnostics')
    if any(f['count'] != 0 or f['periods'] or not math.isfinite(f['max_overlap_kw'])
           or not 0 <= f['max_overlap_kw'] <= parameters.flow_tolerance_kw for f in flows):
        raise ValueError('Material or invalid simultaneous physical flows')
    result.update(grid_simultaneous_count=0, battery_simultaneous_count=0,
                  maximum_simultaneous_overlap_kw=max(f['max_overlap_kw'] for f in flows))
    return result


@dataclass
class TrustedInputs:
    config: object
    standalone: dict
    market_benefits: dict
    reused: dict
    provenance: dict
    harmed_member_count: int


def validate_upstream(m3, m4, config):
    current = config.result_provenance()
    info = solver_information()
    current['solver_configuration_used'] = info['options']
    # Reuse M4's M3 consistency checks with an explicit artifact-only view.
    # Hash pinning is the trust anchor; this view is not a newly solved dispatch.
    view = SimpleNamespace(provenance=current,solver=info,total_cost_aud=m3['C_N_aud'],kpis=m3['B1']['kpis'])
    standalone = validate_baseline(m3, view, config)
    if config.member_ids != tuple(range(1,10)) or len(config.demand_kw)!=8760:
        raise ValueError('Official M5 requires canonical 9 members and 8760 periods')
    if m3['B1']['coalition_members'] != list(config.member_ids):
        raise ValueError('Grand coalition member mapping mismatch')
    if m4['schema_version']!=1 or m4['milestone']!='M4' or m4['currency']!='AUD':
        raise ValueError('Invalid M4 schema')
    if m4['provenance']['m3_artifact_sha256'] != EXPECTED['m3_baselines.json']:
        raise ValueError('M4/M3 artifact provenance mismatch')
    if m4['provenance']['market_source_sha256'] != source_hash(BACKEND/'comfair/market'):
        raise ValueError('M4 source hash mismatch')
    for key in ('input_sha256','registry_sha256','workbook_sha256','parameters','billing_days','solver_configuration_used'):
        if m4['provenance']['physical'][key] != current[key]:
            raise ValueError(f'M4 physical provenance mismatch: {key}')
    tol = config.parameters.cost_tolerance_aud
    require_close('M4 monetary tolerance',m4['provenance']['money_tolerance_aud'],tol,0.)
    if set(m4['members']) != {str(i) for i in config.member_ids}:
        raise ValueError('M4 member mapping mismatch')
    benefits = {}
    for i in config.member_ids:
        row = m4['members'][str(i)]
        require_close('M4 outside option',row['B_i_aud'],standalone[i],tol)
        require_close('M4 benefit',row['u0_aud'],standalone[i]-row['C_market_aud'],tol)
        if row['harmed'] is not (row['u0_aud'] < -tol):
            raise ValueError('M4 harmed-member classification mismatch')
        benefits[i] = row['u0_aud']
    harmed = sum(v < -tol for v in benefits.values())
    if harmed != m4['kpis']['harmed_member_count']:
        raise ValueError('M4 harmed-member count mismatch')
    require_close('M4 efficiency',sum(benefits.values()),m3['v_N_aud'],tol)
    require_close('M4 surplus',m4['kpis']['v_N_aud'],m3['v_N_aud'],tol)
    require_close('M4 physical objective',m4['kpis']['C_N_aud'],m3['C_N_aud'],tol)
    for row in [*m3['B0'],m3['B1']]:
        if any(row['solver'][k]!=v for k,v in info.items()):
            raise ValueError('M3 per-coalition solver configuration mismatch')
        compact_validation(row,config.parameters)
    return standalone, benefits, harmed


def load_trusted_inputs():
    verify_artifacts()
    data = load_benchmark()
    if data.workbook_sha256 != WORKBOOK_SHA256:
        raise ValueError('Official workbook hash mismatch')
    config = config_from_benchmark(data)
    m3 = json.loads((ARTIFACTS/'m3_baselines.json').read_text())
    m4 = json.loads((ARTIFACTS/'m4_market.json').read_text())
    standalone, benefits, harmed = validate_upstream(m3,m4,config)
    reused = {members_to_mask(r['coalition_members']):r for r in [*m3['B0'],m3['B1']]}
    config_provenance = config.result_provenance()
    provenance = {'workbook_sha256':data.workbook_sha256,
                  'registry_sha256':config_provenance['registry_sha256'],
                  'input_sha256':config_provenance['input_sha256'],
                  'physical_source_sha256':source_hash(BACKEND/'comfair/physical'),
                  'market_source_sha256':source_hash(BACKEND/'comfair/market'),
                  'game_source_sha256':source_hash(Path(__file__).parent),
                  'upstream_artifact_hashes':dict(EXPECTED),
                  'checkpoint_base_commit':'f30cd22', 'solver':solver_information(),
                  'coalition_representation':'v1: bit i-1 -> member i; ascending mask',
                  'core_tolerance_aud':config.parameters.cost_tolerance_aud,
                  'tolerance_source':'unchanged M3 parameters.cost_tolerance_aud',
                  'flow_tolerance_kw':config.parameters.flow_tolerance_kw,
                  'energy_tolerance_kwh':config.parameters.energy_tolerance_kwh}
    return TrustedInputs(config,standalone,benefits,reused,provenance,harmed)
