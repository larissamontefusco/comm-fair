"""Official M6 financial diagnostics from frozen M4/M5 artifacts."""
import argparse
from pathlib import Path
from time import perf_counter
from comfair.game.checkpoint import atomic_json
from comfair.game.stability import allocation_diagnostics
from comfair.physical.config import canonical_json
from .coalition import solve_coalition_repair
from .curve import generate_curve
from .individual import solve_individual_repair
from .provenance import digest, load_inputs, protected_hashes, verify_hashes


CANONICAL = ('m6_repair.json', 'm6_repair_curve.json')


def build_artifacts(inputs):
    problem = inputs.problem
    tol = problem.tolerance
    started = perf_counter()
    individual = solve_individual_repair(problem)
    ir_seconds = perf_counter() - started
    started = perf_counter()
    coalition = solve_coalition_repair(problem, individual, inputs.epsilon_star_m5)
    cr_seconds = perf_counter() - started
    started = perf_counter()
    curve = generate_curve(problem, individual, coalition)
    curve_seconds = perf_counter() - started
    _, market = allocation_diagnostics(problem.values, problem.u0, tol)
    members = []
    for i in problem.members:
        members.append({'member_id': i, 'B_i_aud': problem.standalone[i],
            'C_market_aud': problem.market_bills[i], 'u0_aud': problem.u0[i],
            'tau_IR_aud': individual.witness.tau_aud[i], 'C_IR_aud': individual.witness.bill_aud[i],
            'u_IR_aud': individual.witness.benefit_aud[i],
            'tau_CR_aud': coalition.witness.tau_aud[i], 'C_CR_aud': coalition.witness.bill_aud[i],
            'u_CR_aud': coalition.witness.benefit_aud[i]})
    shared = {'schema_version': 1, 'milestone': 'M6', 'currency': 'AUD',
        'provenance': inputs.provenance, 'member_ids': list(problem.members),
        'tolerances': {'money_aud': tol, 'stability_target_aud': tol,
            'repair_equality_aud': tol, 'curve_monotonicity_aud': tol,
            'slope_rule': '2*money/gap_left + 2*money/gap_right'},
        'normalization': 'No clipping or rounding of raw transfers or KPIs'}
    repair = shared | {'v_N_aud': problem.values[2**len(problem.members) - 1],
        'market_anchor': {'u0_aud': problem.u0, 'diagnostics': market,
            'epsilon_at_zero_budget_feasible': min(problem.u0.values()) >= 0},
        'members': members, 'individual': individual.to_dict(), 'coalition': coalition.to_dict(),
        'interpretation': {
            'repair_required_for_individual_rationality': individual.r_IR_aud > tol,
            'additional_coalition_repair_required': coalition.CRP_aud > tol,
            'market_already_core': market['allocation_in_core'],
            'market_already_best_resilience': individual.r_IR_aud <= tol and coalition.r_CR_aud <= tol,
            'scope': 'Annual perfect-foresight game; financial repair necessity, not fairness/governance'}}
    curve_artifact = shared | {'r_IR_aud': individual.r_IR_aud, 'r_CR_aud': coalition.r_CR_aud,
        'epsilon_IR_aud': coalition.epsilon_IR_aud, 'epsilon_star_aud': coalition.epsilon_star_m5_aud,
        'epsilon_target_aud': coalition.epsilon_target_aud, **curve.to_dict()}
    return repair, curve_artifact, {'individual_seconds': ir_seconds,
        'coalition_seconds': cr_seconds, 'curve_seconds': curve_seconds, 'physical_solve_count': 0}


def run_repair(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if any((output_dir / name).exists() for name in CANONICAL):
        raise ValueError('Use a fresh output directory; existing canonical results are preserved')
    started = perf_counter()
    try:
        before = protected_hashes()
        inputs = load_inputs()
        repair, curve, runtime = build_artifacts(inputs)
        verify_hashes()
        if protected_hashes() != before:
            raise ValueError('Protected upstream files changed during M6')
        for name, data in zip(CANONICAL, (repair, curve)):
            atomic_json(output_dir / name, data)
        runtime.update(total_seconds=perf_counter() - started,
            artifact_hashes={name: digest(output_dir / name) for name in CANONICAL},
            timing_scope='Total includes provenance, small financial LPs, validations and canonical writes; no physical optimisation')
        atomic_json(output_dir / 'm6.runtime.json', runtime)
        print(canonical_json({'status': 'DONE', 'interpretation': repair['interpretation'], 'runtime': runtime}))
        return repair, curve, runtime
    except Exception as exc:
        atomic_json(output_dir / 'm6_failure.json', {'status': 'BLOCKED',
            'exception_type': type(exc).__name__, 'reason': str(exc)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    run_repair(parser.parse_args().output_dir)
