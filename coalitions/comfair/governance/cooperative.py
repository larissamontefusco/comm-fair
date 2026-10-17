"""Full-subset Shapley and certified iterative lexicographic nucleolus."""
from fractions import Fraction
from math import factorial, isfinite
import pyomo.environ as pyo
from comfair.game.coalitions import mask_to_members, validate_n
from comfair.repair.model import solve_model


def validate_values(values, n):
    validate_n(n)
    if set(values) != set(range(2**n)) or any(type(k) is not int for k in values):
        raise ValueError('Expected every canonical coalition mask exactly once')
    if any(isinstance(v, bool) or not isfinite(v) for v in values.values()) or values[0] != 0:
        raise ValueError('Nonfinite or unnormalized game')


def shapley(values, n):
    validate_values(values, n)
    result = {}
    for i in range(1, n+1):
        bit = 1 << (i-1)
        result[i] = sum(factorial(s.bit_count()) * factorial(n-s.bit_count()-1) / factorial(n)
                        * (values[s | bit] - values[s]) for s in range(2**n) if not s & bit)
    return result


def leave_one_out(values, n, tolerance):
    validate_values(values, n)
    grand = 2**n-1
    raw = {i: values[grand] - values[grand ^ (1 << (i-1))] for i in range(1,n+1)}
    total = sum(raw.values())
    allocation = None if abs(total) <= tolerance else {i: values[grand]*x/total for i,x in raw.items()}
    return raw, allocation


class ExactBasis:
    """Rational Gaussian elimination on 0/1 incidence vectors; no rank threshold."""
    def __init__(self, n):
        self.n = n
        self.rows = {}

    def reduce(self, mask):
        row = [Fraction(int(bool(mask & (1 << j)))) for j in range(self.n)]
        for pivot, basis in sorted(self.rows.items()):
            factor = row[pivot]
            row = [a-factor*b for a,b in zip(row,basis)]
        return row

    def contains(self, mask):
        return not any(self.reduce(mask))

    def add(self, mask):
        row = self.reduce(mask)
        if not any(row):
            return False
        pivot = next(j for j,x in enumerate(row) if x)
        divisor = row[pivot]
        self.rows[pivot] = [x/divisor for x in row]
        return True


def nucleolus(values, n, tolerance, *, tightness_tolerance=None):
    """Imputation nucleolus, including singleton excesses; epsilon may be negative.

    Auxiliary face LPs certify universal tightness, not tightness at one vertex.
    Only exact linearly independent normals are fixed. Fixed-span excesses are
    removed from subsequent objectives because they cannot vary on that face.
    """
    validate_values(values,n)
    if not isfinite(tolerance) or tolerance <= 0:
        raise ValueError('Positive tolerance required')
    tight_tol = tolerance/100 if tightness_tolerance is None else tightness_tolerance
    if not 0 < tight_tol <= tolerance:
        raise ValueError('Invalid tightness tolerance')
    grand = 2**n-1
    basis = ExactBasis(n); basis.add(grand)
    equalities = {grand: values[grand]}
    remaining = set(range(1,grand))
    stages = []
    previous = float('inf')
    solver = None
    allocation = {1: values[grand]} if n == 1 else None
    if n == 1:
        return allocation, {'certified_unique':True,'rank':1,'stages':[], 'rank_method':'exact rational incidence elimination'}
    for step in range(n):
        m = pyo.ConcreteModel(name='ComFair imputation nucleolus')
        m.I = pyo.RangeSet(1,n)
        m.u = pyo.Var(m.I, bounds=lambda m,i:(values[1 << (i-1)],None))
        m.e = pyo.Var(domain=pyo.Reals)
        m.F = pyo.Set(initialize=sorted(equalities),ordered=True)
        m.fixed = pyo.Constraint(m.F,rule=lambda m,s: sum(m.u[i] for i in mask_to_members(s,n)) == equalities[s])
        m.S = pyo.Set(initialize=sorted(remaining),ordered=True)
        m.excess = pyo.Constraint(m.S,rule=lambda m,s: values[s]-sum(m.u[i] for i in mask_to_members(s,n)) <= m.e)
        m.objective = pyo.Objective(expr=m.e)
        solver = solve_model(m)
        level = float(pyo.value(m.e))
        if level > previous+tolerance:
            raise RuntimeError('Nucleolus lexicographic levels increased')
        previous = level
        candidate = {i:float(pyo.value(m.u[i])) for i in m.I}
        tight = [s for s in sorted(remaining) if abs(values[s]-sum(candidate[i] for i in mask_to_members(s,n))-level) <= tight_tol]
        m.e.fix(level)
        universal = []
        face_checks = []
        # Maximum possible sum u(S) on the optimal face measures the largest slack.
        for s in tight:
            expr = sum(m.u[i] for i in mask_to_members(s,n))
            m.objective.set_value(-expr)
            solve_model(m)
            slack = float(pyo.value(expr)) - (values[s]-level)
            face_checks.append({'mask':s,'maximum_slack_aud':slack})
            if slack < -tolerance:
                raise RuntimeError('Invalid nucleolus optimal-face slack')
            if slack <= tight_tol:
                universal.append(s)
        bounds = []
        for i in m.I:
            bit = 1 << (i-1)
            if basis.contains(bit) or abs(candidate[i]-values[bit]) > tight_tol:
                continue
            m.objective.set_value(-m.u[i]); solve_model(m)
            spread = float(pyo.value(m.u[i]))-values[bit]
            if spread <= tight_tol:
                bounds.append(bit)
        added = []
        for s in universal:
            if basis.add(s):
                equalities[s] = values[s]-level
                added.append({'mask':s,'sum_benefit_aud':equalities[s],'reason':'universal_excess'})
        for bit in bounds:
            if basis.add(bit):
                equalities[bit] = values[bit]
                added.append({'mask':bit,'sum_benefit_aud':equalities[bit],'reason':'universal_imputation_bound'})
        if not added:
            raise RuntimeError('Nucleolus unresolved: no universally tight independent constraint')
        removed = [s for s in sorted(remaining) if basis.contains(s)]
        stages.append({'stage':step+1,'excess_level_aud':level,'rank':len(basis.rows),
            'universal_masks':universal,'fixed_imputation_bounds':bounds,'added_equalities':added,
            'face_checks':face_checks,'removed_fixed_span_masks':removed})
        remaining.difference_update(removed)
        if len(basis.rows) == n:
            # Solve the independent equalities and validate all original imputation bounds.
            import numpy as np
            matrix = [[int(bool(s & (1 << j))) for j in range(n)] for s in equalities]
            vector = np.linalg.solve(matrix,list(equalities.values()))
            allocation = dict(enumerate(map(float,vector),1))
            if any(allocation[i] < values[1 << (i-1)]-tolerance for i in allocation):
                raise RuntimeError('Nucleolus imputation bound failed')
            for stage in stages:
                for row in stage['added_equalities']:
                    if abs(sum(allocation[i] for i in mask_to_members(row['mask'],n))-row['sum_benefit_aud']) > tolerance:
                        raise RuntimeError('Nucleolus equality reconstruction failed')
            break
    if allocation is None or abs(sum(allocation.values())-values[grand]) > tolerance:
        raise RuntimeError('Nucleolus uniqueness/efficiency unresolved')
    # Verify every stage's surviving inequalities at the final allocation.
    active = set(range(1,grand))
    for stage in stages:
        if any(values[s]-sum(allocation[i] for i in mask_to_members(s,n)) > stage['excess_level_aud']+tolerance for s in active):
            raise RuntimeError('Nucleolus lexicographic certificate inequality failed')
        active.difference_update(stage['removed_fixed_span_masks'])
    return allocation, {'certified_unique':True,'rank':len(basis.rows),'stages':stages,
        'tightness_tolerance_aud':tight_tol,'rank_method':'exact rational incidence elimination',
        'solver':solver,'proper_coalitions_include_singletons':True,'excess_zero_floor':False}
