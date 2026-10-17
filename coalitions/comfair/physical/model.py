"""Internal Pyomo LP. No settlement variables or legacy model dependencies."""
import pyomo.environ as pyo


def build_model(members, config):
    p = config.parameters
    periods = len(config.demand_kw)
    columns = {i: config.member_ids.index(i) for i in members}
    m = pyo.ConcreteModel(name='ComFair implicit physical pool')
    m.T = pyo.RangeSet(0, periods - 1)
    m.K = pyo.RangeSet(0, periods)
    m.PV = pyo.Set(initialize=[i for i in members if config.pv_available_kw[:, columns[i]].any()], ordered=True)
    m.B = pyo.Set(initialize=[i for i in members if config.battery_modules[columns[i]]], ordered=True)
    capacity = {i: config.battery_modules[columns[i]] * p.battery_module_kwh for i in m.B}
    power = {i: config.battery_modules[columns[i]] * p.battery_module_kw for i in m.B}
    m.grid_import = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.grid_export = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.pv = pyo.Var(m.PV, m.T, bounds=lambda m, i, t: (0, config.pv_available_kw[t, columns[i]]))
    m.charge = pyo.Var(m.B, m.T, bounds=lambda m, i, t: (0, power[i]))
    m.discharge = pyo.Var(m.B, m.T, bounds=lambda m, i, t: (0, power[i]))
    m.soc = pyo.Var(m.B, m.K, bounds=lambda m, i, t: (
        capacity[i] * p.soc_min_fraction, capacity[i] * p.soc_max_fraction))
    for i in m.B:
        m.soc[i, 0].fix(capacity[i] * p.soc_initial_fraction)
        m.soc[i, periods].fix(capacity[i] * p.soc_initial_fraction)
    m.dynamics = pyo.Constraint(m.B, m.T, rule=lambda m, i, t:
        m.soc[i, t + 1] == m.soc[i, t] +
        (p.eta * m.charge[i, t] - m.discharge[i, t] / p.eta) * p.dt_hours)
    demand = config.demand_kw[:, list(columns.values())].sum(axis=1)
    m.balance = pyo.Constraint(m.T, rule=lambda m, t:
        m.grid_import[t] + sum(m.pv[i, t] for i in m.PV) + sum(m.discharge[i, t] for i in m.B)
        == m.grid_export[t] + float(demand[t]) + sum(m.charge[i, t] for i in m.B))
    fixed = len(members) * config.billing_days * p.daily_connection_fee_aud
    m.cost = pyo.Objective(expr=sum(
        float(config.import_aud_per_kwh[t]) * m.grid_import[t]
        - float(config.export_aud_per_kwh[t]) * m.grid_export[t] for t in m.T) * p.dt_hours + fixed)
    return m
