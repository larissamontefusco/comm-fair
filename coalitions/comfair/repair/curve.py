"""Deterministic sampling of the exact callable epsilon(r), not an r_CR estimator."""
from .coalition import solve_epsilon_at_budget
from .results import RepairCurve, finite


def curve_diagnostics(points, tolerance):
    if not points or not finite(tolerance) or tolerance <= 0:
        raise ValueError('Nonempty curve and positive tolerance required')
    budgets = [p['repair_budget_aud'] for p in points]
    eps = [p['epsilon_aud'] for p in points]
    if any(not finite(x) or x < 0 for x in budgets + eps):
        raise ValueError('Invalid curve point')
    gaps = [b - a for a, b in zip(budgets, budgets[1:])]
    if any(gap <= 0 for gap in gaps):
        raise ValueError('Curve budgets must be strictly increasing')
    monotonic = max([0.] + [b - a for a, b in zip(eps, eps[1:])])
    slopes = [(b - a) / gap for a, b, gap in zip(eps, eps[1:], gaps)]
    # Each slope uses two monetary outputs. Propagate their absolute tolerance
    # through division; no unrelated dimensionless threshold is invented.
    slope_tols = [2 * tolerance / a + 2 * tolerance / b for a, b in zip(gaps, gaps[1:])]
    violations = [max(0., a - b) for a, b in zip(slopes, slopes[1:])]
    convex = all(v <= t for v, t in zip(violations, slope_tols))
    breaks = [budgets[j + 1] for j, (a, b, t) in enumerate(zip(slopes, slopes[1:], slope_tols)) if b - a > t]
    return {'monotonicity_check': monotonic <= tolerance, 'convexity_check': convex,
            'shape_check_scope': 'trivially satisfied: one point' if len(points) == 1 else 'sampled finite differences; not symbolic proof',
            'maximum_monotonicity_violation_aud': monotonic,
            'maximum_slope_order_violation': max([0.] + violations),
            'slope_order_tolerances': slope_tols, 'slopes': slopes,
            'sampled_approximate_breakpoint_budgets_aud': breaks}


def generate_curve(problem, individual, coalition, *, point_count=21):
    if type(point_count) is not int or point_count < 2:
        raise ValueError('Nondegenerate grid requires at least two points')
    lower, upper = individual.r_IR_aud, coalition.r_CR_aud
    if upper < lower - problem.tolerance:
        raise ValueError('r_CR is below r_IR')
    degenerate = abs(upper - lower) <= problem.tolerance
    if lower == upper:
        budgets = [lower]
    elif degenerate:
        budgets = sorted([lower, upper])  # Preserve both raw endpoints; no clipping.
    else:
        budgets = [lower] + [lower + j / (point_count - 1) * (upper - lower) for j in range(1, point_count - 1)] + [upper]
    cached = {lower: coalition.epsilon_IR_witness, upper: coalition.epsilon_at_r_CR_witness}
    points = []
    for budget in budgets:
        witness = cached[budget] if budget in cached else solve_epsilon_at_budget(problem, budget)
        worst = witness.diagnostics['worst_multi_member_coalition']
        points.append({'repair_budget_aud': budget, 'repair_volume_used_aud': witness.repair_volume_aud,
            'epsilon_aud': witness.epsilon_aud,
            'worst_coalition_mask': worst['mask'] if worst else None,
            'worst_coalition_members': worst['members'] if worst else [],
            'worst_deficit_aud': worst['deficit_aud'] if worst else 0.,
            'minimum_member_benefit_aud': min(witness.benefit_aud.values()),
            'witness': witness.to_dict()})
    diagnostic = curve_diagnostics(points, problem.tolerance)
    if not diagnostic['monotonicity_check'] or not diagnostic['convexity_check']:
        raise ValueError('Repair curve monotonicity/convexity failed')
    return RepairCurve(degenerate, points, diagnostic)
