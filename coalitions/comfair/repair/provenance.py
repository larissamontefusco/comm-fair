"""Immutable M4 market anchor and M5 exact game; no physical solve calls."""
from dataclasses import dataclass, fields
from pathlib import Path
from comfair.game.checkpoint import read_json
from comfair.game.provenance import (ARTIFACTS, BACKEND, EXPECTED, digest,
    load_trusted_inputs as load_m5_inputs)
from comfair.game.results import CoalitionRecord
from comfair.game.run_game import protected_hashes as upstream_protected_hashes
from comfair.game.stability import allocation_diagnostics, audit_witness
from comfair.market.run_market import source_hash
from .results import RepairProblem

M5_HASHES = {
    'm5_coalitions.json': 'cca30380f74cb0579e3024b401095779ae88bee7dee39f41554944810156bbb8',
    'm5_core.json': '985f155b46c170dc1069790cd5bdd7dfc6b6678f4214089063692cb72193a5ee',
}
STARTING_COMMIT = 'f0dcd8f'


def verify_hashes(root=ARTIFACTS):
    for name, expected in (EXPECTED | M5_HASHES).items():
        if digest(root / name) != expected:
            raise ValueError(f'M6 upstream hash mismatch: {name}')


def protected_hashes():
    result = upstream_protected_hashes()
    paths = [p for p in (BACKEND / 'comfair/game').rglob('*')
             if p.is_file() and '__pycache__' not in p.parts]
    paths += [ARTIFACTS / name for name in (*M5_HASHES, 'm5.runtime.json')]
    paths += [BACKEND / 'tests' / name for name in ('test_physical.py', 'test_market.py', 'test_game.py')]
    result.update({str(p.relative_to(BACKEND)): digest(p) for p in sorted(paths)})
    return dict(sorted(result.items()))


def validate_m5(game, core, trusted, market_bills):
    tol = trusted.config.parameters.cost_tolerance_aud
    for artifact in (game, core):
        if (artifact['schema_version'] != 1 or artifact['milestone'] != 'M5'
                or artifact['currency'] != 'AUD' or artifact['member_ids'] != list(range(1, 10))
                or artifact['core_tolerance_aud'] != tol):
            raise ValueError('Invalid M5 schema/members/tolerance')
        for key, value in trusted.provenance.items():
            if artifact['provenance'].get(key) != value:
                raise ValueError(f'M5 provenance mismatch: {key}')
    if game['provenance'] != core['provenance']:
        raise ValueError('M5 game/core provenance mismatch')
    if game['B_i_aud'] != {str(i): b for i, b in trusted.standalone.items()}:
        raise ValueError('M5 outside options mismatch')
    rows = game['records']
    if len(rows) != 512 or [r['mask'] for r in rows] != list(range(512)):
        raise ValueError('M5 requires exactly 512 unique canonical masks')
    keys = [f.name for f in fields(CoalitionRecord)]
    for row in rows:
        CoalitionRecord.from_dict({k: row[k] for k in keys}).validate(trusted.standalone, tol)
    values = {row['mask']: row['value_aud'] for row in rows}
    grand = trusted.reused[511]['total_cost_aud']
    if abs(rows[-1]['coalition_cost_aud'] - grand) > tol or abs(core['v_N_aud'] - values[511]) > tol:
        raise ValueError('M5 grand value/cost mismatch')
    market = {str(i): v for i, v in trusted.market_benefits.items()}
    if core['market']['u0_aud'] != market:
        raise ValueError('M5/M4 market anchor mismatch')
    market_rows, diagnostics = allocation_diagnostics(values, trusted.market_benefits, tol)
    if diagnostics != core['market']['diagnostics'] or diagnostics != game['diagnostics']['market']:
        raise ValueError('M5 market diagnostics mismatch')
    for row, calculated in zip(rows, market_rows):
        for saved, key in (('market_benefit_sum_aud', 'benefit_sum_aud'), ('market_deficit_aud', 'deficit_aud')):
            if abs(row[saved] - calculated[key]) > tol:
                raise ValueError('M5 market deficit reconstruction failed')
        if row['market_blocking'] is not calculated['blocking']:
            raise ValueError('M5 blocking classification mismatch')
    cert = core['certificate']
    witness = {int(i): v for i, v in cert['least_core_allocation_u_aud'].items()}
    audit_witness(values, witness, cert['epsilon_star_aud'], tol)
    if cert['core_nonempty'] is not (cert['epsilon_star_aud'] <= tol):
        raise ValueError('M5 core status mismatch')
    problem = RepairProblem(dict(trusted.standalone), market_bills, dict(trusted.market_benefits), values, tol)
    problem.validate()
    return problem


@dataclass(frozen=True)
class RepairInputs:
    problem: RepairProblem
    epsilon_star_m5: float
    provenance: dict


def load_inputs():
    verify_hashes()
    trusted = load_m5_inputs()  # Input/provenance validation only; no optimisation.
    m4 = read_json(ARTIFACTS / 'm4_market.json')
    game = read_json(ARTIFACTS / 'm5_coalitions.json')
    core = read_json(ARTIFACTS / 'm5_core.json')
    bills = {int(i): row['C_market_aud'] for i, row in m4['members'].items()}
    problem = validate_m5(game, core, trusted, bills)
    for name, expected in game['provenance']['protected_file_sha256'].items():
        if digest(BACKEND / name) != expected:
            raise ValueError(f'M5 protected provenance mismatch: {name}')
    provenance = dict(trusted.provenance)
    provenance.update(starting_git_commit=STARTING_COMMIT,
        repair_source_sha256=source_hash(Path(__file__).parent),
        upstream_artifact_hashes=EXPECTED | M5_HASHES,
        market_anchor='M4 members.u0_aud; M5 witness is only a certificate',
        physical_resolve_count=0, protected_file_sha256=protected_hashes())
    return RepairInputs(problem, core['certificate']['epsilon_star_aud'], provenance)
