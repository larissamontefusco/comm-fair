"""Independent stdlib-only acceptance audit. Run as a file, without package imports.

python comfair/repair/audit.py --artifact-dir /results --upstream-dir comfair/artifacts
This reconstructs constraints/arithmetic; LP optimality is evidenced by recorded
solver termination and analytical synthetic tests, not inferred from feasibility.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

PINS = {
    'm3_baselines.json': '767c7c1538768d8db7840194597401bc133fd8ae5c23da3d497754d7cd8997aa',
    'm4_market.json': 'c8f3e274a9a7928926e80a93d33b68606b8e44fd568bc90fffea56d97c4bf54a',
    'm5_coalitions.json': 'cca30380f74cb0579e3024b401095779ae88bee7dee39f41554944810156bbb8',
    'm5_core.json': '985f155b46c170dc1069790cd5bdd7dfc6b6678f4214089063692cb72193a5ee',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, 'Duplicate JSON key')
            result[k] = v
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def audit(artifact_dir, upstream_dir):
    artifact_dir, upstream_dir = Path(artifact_dir), Path(upstream_dir)
    r = read(artifact_dir / 'm6_repair.json')
    curve = read(artifact_dir / 'm6_repair_curve.json')
    m3, m4, game, core = [read(upstream_dir / name) for name in PINS]
    for name, expected in PINS.items():
        require(sha(upstream_dir / name) == expected, f'Upstream hash: {name}')
    tol = game['core_tolerance_aud']
    require(tol == m3['provenance']['parameters']['cost_tolerance_aud'], 'Tolerance source')
    require(r['tolerances']['money_aud'] == curve['tolerances']['money_aud'] == tol, 'M6 tolerance')
    require(r['provenance'] == curve['provenance'], 'Canonical provenance differs')
    for name, expected in r['provenance']['upstream_artifact_hashes'].items():
        require(sha(upstream_dir / name) == expected, f'Upstream preservation: {name}')
    backend = upstream_dir.resolve().parents[1]
    for name, expected in r['provenance']['protected_file_sha256'].items():
        require(sha(backend / name) == expected, f'Protected file changed: {name}')
    for package in ('physical', 'market', 'game', 'repair'):
        h = hashlib.sha256()
        for path in sorted((backend / 'comfair' / package).glob('*.py')):
            h.update(path.name.encode() + b'\0' + path.read_bytes())
        require(h.hexdigest() == r['provenance'][package + '_source_sha256'], f'Source mismatch: {package}')
    require(r['provenance']['workbook_sha256'] == sha(backend / 'reader/ComErgy Benchmark Dataset 2026.xlsx'), 'Workbook')
    require(r['provenance']['registry_sha256'] == sha(backend / 'comfair/config/assumptions.yaml'), 'Registry')
    ids = [str(i) for i in range(1, 10)]
    u0 = {i: m4['members'][i]['u0_aud'] for i in ids}
    bills = {i: m4['members'][i]['C_market_aud'] for i in ids}
    outside = {i: m4['members'][i]['B_i_aud'] for i in ids}
    values = {}
    require(len(game['records']) == 512, 'Coalition count')
    def close(a, b, label):
        require(math.isfinite(a) and math.isfinite(b) and abs(a-b) <= tol, label)
    for mask, row in enumerate(game['records']):
        members = [i for i in range(1, 10) if mask & (1 << (i-1))]
        require(type(row['mask']) is int and row['mask'] == mask and row['members'] == members, 'Coalition masks/members')
        value = sum(outside[str(i)] for i in members) - row['coalition_cost_aud']
        close(row['value_aud'], value, 'Value formula')
        values[mask] = row['value_aud']
        if len(members) == 1: close(values[mask], 0., 'Singleton value')
    require(values[0] == 0., 'Empty value')
    close(values[511], m3['v_N_aud'], 'Grand value')
    close(sum(u0.values()), values[511], 'Market efficiency')
    require(r['market_anchor']['u0_aud'] == u0, 'M4 is not the repair anchor')
    for i in ids: close(outside[i] - bills[i], u0[i], 'Market bill/benefit')
    multi = [s for s in range(1, 511) if s.bit_count() >= 2]
    def deficits(u):
        return {s: values[s] - sum(u[str(i)] for i in range(1, 10) if s & (1 << (i-1))) for s in range(512)}
    market_deficits = deficits(u0)
    market_core = min(u0.values()) >= -tol and max(market_deficits.values()) <= tol
    require(r['interpretation']['market_already_core'] is market_core, 'Market core classification')
    audited = []
    def witness(w, label, epsilon=None, budget=None):
        tau, u, cost, z = (w[k] for k in ('tau_aud', 'benefit_aud', 'bill_aud', 'absolute_transfer_aud'))
        for mapping in (tau, u, cost, z):
            require(set(mapping) == set(ids), label + ' member coverage')
            require(all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) for v in mapping.values()), label + ' finite')
        close(sum(tau.values()), 0., label + ' zero sum')
        close(sum(u.values()), values[511], label + ' efficiency')
        close(sum(cost.values()), sum(bills.values()), label + ' total bills')
        require(min(u.values()) >= -tol, label + ' no harm')
        for i in ids:
            close(cost[i], bills[i] + tau[i], label + ' bill')
            close(u[i], u0[i] - tau[i], label + ' benefit')
            close(u[i], outside[i] - cost[i], label + ' outside option')
            close(z[i], abs(tau[i]), label + ' absolute value')
        volume = .5 * sum(abs(x) for x in tau.values())
        close(volume, w['repair_volume_aud'], label + ' repair volume')
        close(volume, .5 * sum(z.values()), label + ' auxiliary volume')
        d = deficits(u); worst = max(d[s] for s in multi)
        if epsilon is not None:
            require(epsilon >= 0 and worst <= epsilon + tol, label + ' coalition constraints')
        if budget is not None:
            require(volume <= budget + tol, label + ' budget')
        require(w['solver']['status'] == 'ok' and w['solver']['termination_condition'] == 'optimal', label + ' solver')
        audited.append(label)
        return volume, max(0., worst)
    ir, cr = r['individual'], r['coalition']
    ir_volume, _ = witness(ir['witness'], 'individual')
    analytical = sum(max(0., -x) for x in u0.values())
    close(ir_volume, ir['r_IR_aud'], 'r_IR optimum')
    close(ir_volume, analytical, 'r_IR analytical identity')
    close(ir['r_IR_analytical_aud'], analytical, 'Stored analytical r_IR')
    close(ir['identity_residual_aud'], ir['r_IR_aud'] - analytical, 'Identity residual')
    _, e_ir = witness(cr['epsilon_IR_witness'], 'epsilon_IR', cr['epsilon_IR_aud'], ir['r_IR_aud'])
    close(e_ir, cr['epsilon_IR_aud'], 'epsilon_IR reconstruction')
    star = core['certificate']['epsilon_star_aud']
    close(cr['epsilon_star_m5_aud'], star, 'M5 epsilon')
    close(cr['epsilon_star_aud'], star, 'Independent least-core check')
    close(cr['epsilon_star_validation_residual_aud'], cr['epsilon_star_aud']-star, 'Epsilon check residual')
    target = star + r['tolerances']['stability_target_aud']
    close(cr['epsilon_target_aud'], target, 'Target tolerance')
    cr_volume, _ = witness(cr['witness'], 'coalition', target)
    close(cr_volume, cr['r_CR_aud'], 'r_CR volume')
    _, e_cr = witness(cr['epsilon_at_r_CR_witness'], 'epsilon_at_r_CR', cr['epsilon_at_r_CR_aud'], cr_volume)
    close(e_cr, cr['epsilon_at_r_CR_aud'], 'epsilon(r_CR) reconstruction')
    require(e_cr <= target + tol, 'Coalition repair target')
    close(cr['CRP_aud'], cr_volume - ir_volume, 'CRP formula')
    close(cr['RSG_aud'], e_ir - star, 'RSG formula')
    require(cr['CRP_aud'] >= -tol and cr['RSG_aud'] >= -tol, 'Repair ordering')
    require(r['interpretation']['repair_required_for_individual_rationality'] is (ir_volume > tol), 'IR interpretation')
    require(r['interpretation']['additional_coalition_repair_required'] is (cr_volume-ir_volume > tol), 'CRP interpretation')
    require([row['member_id'] for row in r['members']] == list(range(1,10)), 'Member table')
    for row in r['members']:
        i = str(row['member_id'])
        for key, expected in (('B_i_aud',outside[i]), ('u0_aud',u0[i]), ('C_market_aud',bills[i])):
            close(row[key], expected, 'Member market decomposition')
        for suffix, w in (('IR',ir['witness']), ('CR',cr['witness'])):
            for key, source in (('tau','tau_aud'), ('u','benefit_aud'), ('C','bill_aud')):
                close(row[f'{key}_{suffix}_aud'], w[source][i], 'Member repair decomposition')
    points = curve['points']
    require(bool(points), 'Empty repair curve')
    budgets = [p['repair_budget_aud'] for p in points]
    require(any(abs(b-ir_volume)<=tol for b in budgets) and any(abs(b-cr_volume)<=tol for b in budgets), 'Curve endpoints')
    eps = []
    for j, p in enumerate(points):
        used, e = witness(p['witness'], f'curve_{j}', p['epsilon_aud'], p['repair_budget_aud'])
        close(used, p['repair_volume_used_aud'], 'Curve used volume')
        close(e, p['epsilon_aud'], 'Curve epsilon reconstruction')
        eps.append(e)
    gaps = [b-a for a,b in zip(budgets,budgets[1:])]
    require(all(g>0 for g in gaps), 'Curve order')
    mono = max([0.] + [b-a for a,b in zip(eps,eps[1:])])
    require(mono <= tol, 'Curve monotonicity')
    slopes = [(b-a)/g for a,b,g in zip(eps,eps[1:],gaps)]
    for j in range(len(slopes)-1):
        require(slopes[j]-slopes[j+1] <= 2*tol/gaps[j]+2*tol/gaps[j+1], 'Curve convexity')
    require(curve['degenerate_curve'] is (abs(cr_volume-ir_volume)<=tol), 'Degenerate curve flag')
    require(curve['diagnostics']['monotonicity_check'] and curve['diagnostics']['convexity_check'], 'Curve flags')
    return {'status':'PASS', 'coalition_count':len(values), 'witnesses_audited':audited,
        'r_IR_aud':ir_volume, 'r_CR_aud':cr_volume, 'epsilon_IR_aud':e_ir,
        'epsilon_star_aud':star, 'epsilon_at_r_CR_aud':e_cr,
        'CRP_aud':cr_volume-ir_volume, 'RSG_aud':e_ir-star,
        'curve_points':len(points), 'market_already_core':market_core,
        'budget_balance_max_abs_aud':max(abs(sum(w['tau_aud'].values())) for w in
            [ir['witness'],cr['witness'],cr['epsilon_IR_witness'],cr['epsilon_at_r_CR_witness']])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir', type=Path, required=True)
    parser.add_argument('--upstream-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.artifact_dir, args.upstream_dir), indent=2, allow_nan=False))
