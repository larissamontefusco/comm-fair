"""Budget-constrained stability and direct minimum coalition repair LPs."""
import pyomo.environ as pyo
from comfair.game.stability import solve_least_core
from .model import add_coalitions, audit_repair, build_model, extract, solve_model
from .results import CoalitionRepairResult, finite


def solve_epsilon_at_budget(problem, repair_budget_r):
    if not finite(repair_budget_r) or repair_budget_r < 0:
        raise ValueError('Repair budget must be finite and nonnegative')
    m = build_model(problem)
    m.epsilon = pyo.Var(domain=pyo.NonNegativeReals)
    add_coalitions(m, problem, m.epsilon)
    m.budget = pyo.Constraint(expr=m.R <= repair_budget_r)
    m.objective = pyo.Objective(expr=m.epsilon)
    primary = solve_model(m)
    epsilon = float(pyo.value(m.epsilon))
    # Epsilon is fixed exactly, not relaxed. This selects a minimum-volume witness
    # on the optimal face and makes every z_i tight without a fairness objective.
    m.epsilon.fix(epsilon)
    m.objective.set_value(m.R)
    secondary = solve_model(m)
    solver = primary | {'witness_pass': secondary, 'witness_rule': 'min R with primary epsilon fixed exactly'}
    witness = extract(m, problem, solver, epsilon=epsilon, budget=repair_budget_r)
    maximum = max(0., witness.diagnostics['maximum_multi_member_deficit_aud'])
    if abs(maximum - epsilon) > problem.tolerance:
        raise ValueError('Epsilon does not match reconstructed worst deficit')
    return witness


def solve_minimum_coalition_repair(problem, epsilon_target):
    if not finite(epsilon_target) or epsilon_target < 0:
        raise ValueError('Epsilon target must be finite and nonnegative')
    m = build_model(problem)
    add_coalitions(m, problem, epsilon_target)
    m.objective = pyo.Objective(expr=m.R)
    return extract(m, problem, solve_model(m), epsilon=epsilon_target)


def solve_coalition_repair(problem, individual, epsilon_star_m5, *, stability_tolerance=None):
    problem.validate()
    tol = problem.tolerance
    w = individual.witness
    audit_repair(problem, w.tau_aud, w.benefit_aud, w.bill_aud,
                 w.absolute_transfer_aud, w.repair_volume_aud)
    analytical = sum(max(0., -problem.u0[i]) for i in problem.members)
    if (not finite(individual.r_IR_aud) or individual.r_IR_aud < 0
            or abs(individual.r_IR_aud - w.repair_volume_aud) > tol
            or abs(individual.r_IR_aud - analytical) > tol):
        raise ValueError('Individual repair result is not valid for this market anchor')
    target_tol = tol if stability_tolerance is None else stability_tolerance
    if not finite(target_tol) or not 0 <= target_tol <= tol:
        raise ValueError('Stability tolerance must be in [0, monetary tolerance]')
    if not finite(epsilon_star_m5) or epsilon_star_m5 < 0:
        raise ValueError('Invalid M5 epsilon reference')
    reference, _ = solve_least_core(problem.values, len(problem.members), tol)
    epsilon_star = reference.epsilon_star_aud
    residual = epsilon_star - epsilon_star_m5
    if abs(residual) > tol:
        raise ValueError('M5 epsilon_star validation mismatch')
    # M5 remains the authoritative target. The new LP is an independent check.
    target = epsilon_star_m5 + target_tol
    at_ir = solve_epsilon_at_budget(problem, individual.r_IR_aud)
    witness = solve_minimum_coalition_repair(problem, target)
    at_cr = solve_epsilon_at_budget(problem, witness.repair_volume_aud)
    crp = witness.repair_volume_aud - individual.r_IR_aud
    rsg = at_ir.epsilon_aud - epsilon_star_m5
    if crp < -tol or rsg < -tol or at_cr.epsilon_aud > target + tol:
        raise ValueError('Coalition repair ordering or epsilon target failed')
    return CoalitionRepairResult(at_ir.epsilon_aud, epsilon_star, epsilon_star_m5, residual,
        target, target_tol, witness.repair_volume_aud, at_cr.epsilon_aud, crp, rsg,
        at_ir, witness, at_cr, reference.solver)
