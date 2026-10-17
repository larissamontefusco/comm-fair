"""Deficits and hard-no-harm least-core. No market-distance or repair variables."""
import math
from time import perf_counter
from .coalitions import mask_to_members, coalition_kind, validate_n
from .provenance import solver_information
from .results import CoreCertificate


def validate_game(values, n, tolerance):
    validate_n(n)
    if not math.isfinite(tolerance) or tolerance<=0:
        raise ValueError('Positive finite core tolerance required')
    if set(values)!=set(range(2**n)) or any(type(k) is not int for k in values):
        raise ValueError('Game requires exactly all masks')
    if any(isinstance(v,bool) or not math.isfinite(v) for v in values.values()):
        raise ValueError('Non-finite game value')
    if values[0]!=0 or any(abs(values[1<<i])>tolerance for i in range(n)):
        raise ValueError('Expected normalized empty/singleton values')


def allocation_diagnostics(values, allocation, tolerance):
    n = len(allocation)
    validate_game(values,n,tolerance)
    if set(allocation)!=set(range(1,n+1)) or any(type(i) is not int for i in allocation) or any(not math.isfinite(v) for v in allocation.values()):
        raise ValueError('Invalid allocation member mapping/values')
    grand = 2**n-1
    rows = []
    for mask in range(2**n):
        members = mask_to_members(mask,n)
        total = sum(allocation[i] for i in members)
        deficit = values[mask]-total
        rows.append({'mask':mask,'members':list(members),'kind':coalition_kind(mask,n),
                     'benefit_sum_aud':total,'deficit_aud':deficit,
                     'blocking':0<mask<grand and deficit>tolerance,
                     'classification':'blocking' if deficit>tolerance else 'indifferent' if abs(deficit)<=tolerance else 'nonblocking'})
    proper = rows[1:grand]
    worst = min(proper,key=lambda r:(-r['deficit_aud'],r['mask'])) if proper else None
    worst_blocking = worst if worst and worst['blocking'] else None
    efficiency = sum(allocation.values())-values[grand]
    harm = max(0.,-min(allocation.values()))
    summary = {'proper_blocking_count':sum(r['blocking'] for r in proper),
               'singleton_blocking_count':sum(r['blocking'] for r in proper if len(r['members'])==1),
               'proper_multi_member_blocking_count':sum(r['blocking'] for r in proper if len(r['members'])>=2),
               'maximum_positive_proper_deficit_aud':max(0.,worst['deficit_aud']) if worst else 0.,
               'worst_proper_coalition':worst,'worst_blocking_coalition':worst_blocking,
               'sum_u_aud':sum(allocation.values()),'efficiency_residual_aud':efficiency,
               'minimum_member_benefit_aud':min(allocation.values()),'no_harm_violation_aud':harm,
               'allocation_in_core':abs(efficiency)<=tolerance and harm<=tolerance and not any(r['blocking'] for r in proper),
               'empty_deficit_aud':rows[0]['deficit_aud'],'grand_deficit_aud':rows[grand]['deficit_aud'],
               'blocking_count_by_size':{str(k):sum(r['blocking'] for r in proper if len(r['members'])==k) for k in range(1,n)}}
    return rows, summary


def audit_witness(values, allocation, epsilon, tolerance):
    if not math.isfinite(epsilon) or epsilon<0:
        raise ValueError('Least-core epsilon must be finite and nonnegative')
    rows, d = allocation_diagnostics(values,allocation,tolerance)
    multi = [r for r in rows if r['kind']=='proper_multi_member']
    worst = min(multi,key=lambda r:(-r['deficit_aud'],r['mask'])) if multi else None
    maximum = worst['deficit_aud'] if worst else 0.
    if abs(d['efficiency_residual_aud'])>tolerance or d['no_harm_violation_aud']>tolerance:
        raise ValueError('Witness violates efficiency or hard no-harm')
    if maximum>epsilon+tolerance:
        raise ValueError('Witness coalition inequality violated')
    if epsilon>tolerance and abs(maximum-epsilon)>tolerance:
        raise ValueError('Positive epsilon does not match reconstructed worst deficit')
    d.update(maximum_coalition_deficit_at_witness_aud=max(r['deficit_aud'] for r in rows),
             maximum_proper_multi_member_deficit_aud=maximum,
             worst_coalition_at_witness=worst,
             maximum_least_core_inequality_violation_aud=max(0.,maximum-epsilon),
             binding_or_near_binding_coalitions=[r['mask'] for r in multi if abs(epsilon-r['deficit_aud'])<=tolerance],
             binding_no_harm_members=[i for i,v in allocation.items() if abs(v)<=tolerance])
    return d


def solve_least_core(values, n, tolerance):
    """min epsilon; sum u=v(N); u>=0; u(S)+epsilon>=v(S), 2<=|S|<n.

    When v(N) < 0 the hard-no-harm constraint (u[i]>=0 for all i) and
    the efficiency constraint (sum u = v(N)) are simultaneously infeasible by
    arithmetic: no nonnegative numbers can sum to a strictly negative value.
    This is an economic property of the game, not a solver defect.  The function
    returns a certificate with infeasible_hard_no_harm=True and NaN member values
    instead of raising.
    """
    validate_game(values, n, tolerance)
    v_N = values[2**n - 1]

    if v_N < 0:
        # Hard-no-harm allocation is structurally infeasible: sum(u) = v(N) < 0
        # cannot hold under u[i] >= 0.  Return a clean certificate; do not call solver.
        empty_alloc = {i: float('nan') for i in range(1, n + 1)}
        diagnostics = {
            'infeasible_reason': (
                'v(N) < 0: the grand-coalition saves less than nothing relative to '
                'standalone costs.  A hard-no-harm allocation (u[i]>=0, sum u=v(N)) '
                'is infeasible by arithmetic; no least-core certificate was computed.'
            ),
            'v_N_aud': v_N,
        }
        solver_info = {
            'name': 'none',
            'status': 'skipped',
            'termination_condition': 'infeasible_hard_no_harm',
        }
        return CoreCertificate(
            core_nonempty=False,
            epsilon_star_aud=float('nan'),
            least_core_allocation_u_aud=empty_alloc,
            v_N_aud=v_N,
            diagnostics=diagnostics,
            solver=solver_info,
            core_tolerance_aud=tolerance,
            interpretation=(
                'Hard-no-harm least-core allocation is infeasible: v(N) < 0. '
                'This is an economic finding, not a solver error. '
                'Cooperation under this model and scenario does not create net value '
                'for the grand coalition relative to standalone costs.'
            ),
            infeasible_hard_no_harm=True,
        ), 0.0

    import highspy
    import pyomo.environ as pyo
    from pyomo.opt import SolverStatus, TerminationCondition
    started = perf_counter()
    info = solver_information()
    m = pyo.ConcreteModel(name='ComFair hard-no-harm least-core certificate')
    m.I = pyo.RangeSet(1,n)
    masks = [mask for mask in range(1,2**n-1) if len(mask_to_members(mask,n))>=2]
    m.S = pyo.Set(initialize=masks,ordered=True)
    m.u = pyo.Var(m.I,domain=pyo.NonNegativeReals)
    m.epsilon = pyo.Var(domain=pyo.NonNegativeReals)
    m.efficiency = pyo.Constraint(expr=sum(m.u[i] for i in m.I)==values[2**n-1])
    m.coalition = pyo.Constraint(m.S,rule=lambda m,mask:sum(m.u[i] for i in mask_to_members(mask,n))+m.epsilon>=values[mask])
    m.objective = pyo.Objective(expr=m.epsilon)
    highspy.Highs.resetGlobalScheduler(True)
    try:
        solved = pyo.SolverFactory('highs').solve(m,options=info['options'],load_solutions=False)
    finally:
        highspy.Highs.resetGlobalScheduler(True)
    if solved.solver.status!=SolverStatus.ok or solved.solver.termination_condition!=TerminationCondition.optimal:
        raise RuntimeError(f'Least-core failed: {solved.solver.status}/{solved.solver.termination_condition}')
    m.solutions.load_from(solved)
    allocation = {i:float(pyo.value(m.u[i])) for i in range(1,n+1)}
    epsilon = float(pyo.value(m.epsilon))
    diagnostics = audit_witness(values,allocation,epsilon,tolerance)
    info.update(status=str(solved.solver.status),termination_condition=str(solved.solver.termination_condition))
    certificate = CoreCertificate(epsilon<=tolerance,epsilon,allocation,values[2**n-1],diagnostics,info,tolerance)
    return certificate, perf_counter()-started
