"""M7 frozen-input boundary, including typed workbook metadata."""
from dataclasses import dataclass
from pathlib import Path
import platform
from importlib.metadata import version
from comfair.data import load_benchmark
from comfair.physical.config import load_baseline
from comfair.game.checkpoint import read_json
from comfair.repair.provenance import ARTIFACTS, BACKEND, digest, load_inputs as load_repair_inputs
from comfair.repair.provenance import protected_hashes as old_protected
from comfair.repair.audit import audit as audit_m6
from comfair.market.run_market import source_hash

M6_HASHES={'m6_repair.json':'95eaf66746d6baa636145acadd702d11d5d4874a40b42b8eae766ed6deefa749',
 'm6_repair_curve.json':'15c38a3325ce4196035477a2aff5743ab05992744eb65e6598260aac3ab03aed'}


def protected_hashes():
    result=old_protected()
    for p in [*list((BACKEND/'comfair/repair').glob('*')),BACKEND/'tests/test_repair.py',
              *[ARTIFACTS/name for name in (*M6_HASHES,'m6.runtime.json')]]:
        if p.is_file():result[str(p.relative_to(BACKEND))]=digest(p)
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class GovernanceInputs:
    problem: object
    epsilon_star: float
    m3: dict
    m4: dict
    m6: dict
    metadata: dict
    dt: float
    provenance: dict


def load_inputs():
    for name,h in M6_HASHES.items():
        if digest(ARTIFACTS/name)!=h:raise ValueError(f'M7 upstream hash mismatch: {name}')
    upstream=load_repair_inputs()
    audit_m6(ARTIFACTS,ARTIFACTS)
    data=load_benchmark();p,_=load_baseline()
    metadata={i:{'annual_income_aud':m.annual_income_aud,'household_type':m.household_type,
        'occupant_count':m.occupant_count,'annual_demand_kwh':float(data.demand_hourly[:,i-1].sum()*p.dt_hours),
        'pv_modules':m.dgs.pv_modules,'battery_modules':m.dgs.battery_modules,
        'pv_capacity_kw':m.dgs.pv_modules*p.pv_module_kw,'battery_capacity_kwh':m.dgs.battery_modules*p.battery_module_kwh}
        for i,m in sorted(data.members.items())}
    provenance=upstream.provenance | {'starting_git_commit':'8442dc9',
        'governance_source_sha256':source_hash(Path(__file__).parent),
        'upstream_artifact_hashes':upstream.provenance['upstream_artifact_hashes'] | M6_HASHES,
        'protected_file_sha256':protected_hashes(),'python_version':platform.python_version(),
        'libraries':{name:version(name) for name in ('numpy','pyomo','highspy','matplotlib')},
        'money_tolerance_aud':p.cost_tolerance_aud,'nucleolus_tightness_aud':p.cost_tolerance_aud/100,
        'rank_method':'exact rational incidence elimination',
        'share_tolerance':p.cost_tolerance_aud/max(1.,abs(upstream.problem.values[511])),
        'physical_resolve_count':0,'metadata_role':'descriptive KPIs only; capacities reuse approved M3 registry'}
    return GovernanceInputs(upstream.problem,upstream.epsilon_star_m5,
        read_json(ARTIFACTS/'m3_baselines.json'),read_json(ARTIFACTS/'m4_market.json'),
        read_json(ARTIFACTS/'m6_repair.json'),metadata,p.dt_hours,provenance)
