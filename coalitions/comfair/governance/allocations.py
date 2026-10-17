"""Explicit project governance objectives; no metadata enters an LP."""
import pyomo.environ as pyo
from comfair.game.coalitions import mask_to_members
from comfair.repair.model import solve_model
from .cooperative import validate_values


def constrained_allocation(values, n, epsilon_star, anchor, kind):
    validate_values(values,n)
    if kind not in ('closest_core_l1_to_market','fair_least_core_maxmin','maxmin_benefit'):
        raise ValueError('Unknown governance objective')
    m = pyo.ConcreteModel(name=kind)
    m.I = pyo.RangeSet(1,n)
    m.u = pyo.Var(m.I,domain=pyo.NonNegativeReals)
    m.efficiency = pyo.Constraint(expr=sum(m.u[i] for i in m.I)==values[2**n-1])
    masks=[s for s in range(1,2**n-1) if s.bit_count()>=2]
    m.S=pyo.Set(initialize=masks,ordered=True)
    m.coalition=pyo.Constraint(m.S,rule=lambda m,s:sum(m.u[i] for i in mask_to_members(s,n))>=values[s]-epsilon_star)
    phases=[]; floor=None
    if kind != 'closest_core_l1_to_market':
        m.floor=pyo.Var(domain=pyo.Reals)
        m.minimum=pyo.Constraint(m.I,rule=lambda m,i:m.u[i]>=m.floor)
        m.objective=pyo.Objective(expr=-m.floor)
        phases.append(solve_model(m));floor=float(pyo.value(m.floor));m.floor.fix(floor)
    else:
        m.objective=pyo.Objective(expr=0.)
    target={i:values[2**n-1]/n for i in m.I} if kind=='fair_least_core_maxmin' else anchor
    m.z=pyo.Var(m.I,domain=pyo.NonNegativeReals)
    m.abs1=pyo.Constraint(m.I,rule=lambda m,i:m.z[i]>=m.u[i]-target[i])
    m.abs2=pyo.Constraint(m.I,rule=lambda m,i:m.z[i]>=target[i]-m.u[i])
    m.objective.set_value(sum(m.z[i] for i in m.I))
    phases.append(solve_model(m))
    u={i:float(pyo.value(m.u[i])) for i in m.I}
    return u, {'epsilon_target_aud':epsilon_star,'optimal_minimum_benefit_aud':floor,
               'tie_target':'equal benefit' if kind=='fair_least_core_maxmin' else 'M4 market',
               'L1_objective_aud':float(pyo.value(m.objective)),'solver_phases':phases,
               'remaining_ties':'canonical variable order and deterministic HiGHS simplex'}
