"""Common financial LP and independent witness reconstruction."""
import math
import highspy
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition
from comfair.game.coalitions import mask_to_members
from comfair.game.provenance import solver_information
from comfair.game.stability import allocation_diagnostics
from .results import RepairWitness, finite


class RepairInfeasibleError(RuntimeError):
    """No feasible hard-no-harm repair exists at the supplied budget/target."""


def build_model(problem):
    problem.validate()
    m = pyo.ConcreteModel(name='ComFair market-anchored financial repair')
    m.I = pyo.Set(initialize=problem.members, ordered=True)
    m.tau = pyo.Var(m.I, domain=pyo.Reals)
    m.u = pyo.Var(m.I, domain=pyo.NonNegativeReals)
    m.z = pyo.Var(m.I, domain=pyo.NonNegativeReals)
    m.anchor = pyo.Constraint(m.I, rule=lambda m, i: m.u[i] == problem.u0[i] - m.tau[i])
    m.balance = pyo.Constraint(expr=sum(m.tau[i] for i in m.I) == 0)
    m.abs_positive = pyo.Constraint(m.I, rule=lambda m, i: m.z[i] >= m.tau[i])
    m.abs_negative = pyo.Constraint(m.I, rule=lambda m, i: m.z[i] >= -m.tau[i])
    m.R = pyo.Expression(expr=0.5 * sum(m.z[i] for i in m.I))
    return m


def add_coalitions(m, problem, epsilon):
    n = len(problem.members)
    masks = [s for s in range(1, 2**n - 1) if len(mask_to_members(s, n)) >= 2]
    m.S = pyo.Set(initialize=masks, ordered=True)
    m.coalition = pyo.Constraint(m.S, rule=lambda m, s:
        sum(m.u[i] for i in mask_to_members(s, n)) >= problem.values[s] - epsilon)


def solve_model(m):
    info = solver_information()
    highspy.Highs.resetGlobalScheduler(True)
    try:
        result = pyo.SolverFactory('highs').solve(m, options=info['options'], load_solutions=False)
    finally:
        highspy.Highs.resetGlobalScheduler(True)
    condition = result.solver.termination_condition
    if condition == TerminationCondition.infeasible:
        raise RepairInfeasibleError(f'Repair LP infeasible: {result.solver.status}/{condition}')
    if result.solver.status != SolverStatus.ok or condition != TerminationCondition.optimal:
        raise RuntimeError(f'Repair LP failed: {result.solver.status}/{condition}')
    m.solutions.load_from(result)
    return info | {'status': str(result.solver.status), 'termination_condition': str(condition)}


def audit_repair(problem, tau, benefits, bills, z, volume, *, epsilon=None, budget=None):
    problem.validate()
    ids = problem.members
    tol = problem.tolerance
    for mapping in (tau, benefits, bills, z):
        if (set(mapping) != set(ids) or any(type(i) is not int for i in mapping)
                or not all(finite(x) for x in mapping.values())):
            raise ValueError('Invalid repair witness mapping or non-finite amount')
    if not finite(volume) or volume < -tol:
        raise ValueError('Invalid repair volume')
    rows, diagnostic = allocation_diagnostics(problem.values, benefits, tol)
    multi = [row for row in rows if row['kind'] == 'proper_multi_member']
    worst = min(multi, key=lambda r: (-r['deficit_aud'], r['mask'])) if multi else None
    maximum = worst['deficit_aud'] if worst else 0.
    reconstructed = 0.5 * sum(abs(tau[i]) for i in ids)
    diagnostic.update(
        budget_balance_residual_aud=sum(tau.values()),
        benefit_anchor_residual_aud=max(abs(benefits[i] - problem.u0[i] + tau[i]) for i in ids),
        bill_reconstruction_residual_aud=max(abs(bills[i] - problem.market_bills[i] - tau[i]) for i in ids),
        benefit_bill_residual_aud=max(abs(problem.standalone[i] - bills[i] - benefits[i]) for i in ids),
        total_bill_preservation_residual_aud=sum(bills.values()) - sum(problem.market_bills.values()),
        total_benefit_preservation_residual_aud=sum(benefits.values()) - sum(problem.u0.values()),
        absolute_transfer_residual_aud=max(abs(z[i] - abs(tau[i])) for i in ids),
        repair_volume_reconstructed_aud=reconstructed,
        repair_volume_reconstruction_residual_aud=volume - reconstructed,
        auxiliary_volume_residual_aud=volume - 0.5 * sum(z.values()),
        worst_multi_member_coalition=worst,
        maximum_multi_member_deficit_aud=maximum)
    for name, value in diagnostic.items():
        if name.endswith('residual_aud') and (not math.isfinite(value) or abs(value) > tol):
            raise ValueError(f'Repair invariant failed: {name}={value}')
    if diagnostic['no_harm_violation_aud'] > tol or any(x < -tol for x in z.values()):
        raise ValueError('Repair violates hard no-harm or absolute-transfer bounds')
    if epsilon is not None:
        if not finite(epsilon) or epsilon < 0:
            raise ValueError('Invalid epsilon')
        violation = max(0., maximum - epsilon)
        diagnostic['coalition_inequality_violation_aud'] = violation
        if violation > tol:
            raise ValueError('Repair violates coalition target')
    if budget is not None:
        if not finite(budget) or budget < 0:
            raise ValueError('Invalid repair budget')
        diagnostic['repair_budget_violation_aud'] = max(0., reconstructed - budget, volume - budget)
        if diagnostic['repair_budget_violation_aud'] > tol:
            raise ValueError('Repair exceeds budget')
    return diagnostic


def extract(m, problem, solver, *, epsilon=None, budget=None):
    tau = {i: float(pyo.value(m.tau[i])) for i in problem.members}
    benefits = {i: float(pyo.value(m.u[i])) for i in problem.members}
    bills = {i: problem.market_bills[i] + tau[i] for i in problem.members}
    z = {i: float(pyo.value(m.z[i])) for i in problem.members}
    volume = float(pyo.value(m.R))
    diagnostic = audit_repair(problem, tau, benefits, bills, z, volume, epsilon=epsilon, budget=budget)
    return RepairWitness(tau, benefits, bills, z, volume, diagnostic, solver, epsilon, budget)
