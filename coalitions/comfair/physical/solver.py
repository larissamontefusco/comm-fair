"""One physical solve entry point for empty, singleton and arbitrary coalitions."""
from collections.abc import Iterable
from time import perf_counter

import numpy as np

from .config import PhysicalConfig, load_baseline
from .results import MemberDispatch, PhysicalResult, audit_dispatch, validate_result


def solve_physical(S: Iterable[int], config: PhysicalConfig) -> PhysicalResult:
    """Solve the approved LP, returning only plain domain data.

    Invalid subsets/configurations raise ValueError. Nonoptimal solver termination
    raises RuntimeError. Invalid dispatch or simultaneous flows raise ValueError
    including offending period indices and magnitudes. No automatic MILP fallback.
    """
    config.validate()
    try:
        requested = tuple(S)
    except TypeError as exc:
        raise ValueError('Coalition must be an iterable of member IDs') from exc
    if (any(type(i) is not int or i not in config.member_ids for i in requested)
            or len(set(requested)) != len(requested)):
        raise ValueError('Coalition must contain distinct configured integer member IDs')
    members = tuple(sorted(requested))
    t_count = len(config.demand_kw)
    p = config.parameters
    provenance = config.result_provenance()
    started = perf_counter()
    if not members:
        zeros = [0.0] * t_count
        kpis, diagnostics = audit_dispatch(config, {}, zeros, zeros)
        return PhysicalResult((), 0.0, 0.0, 0.0, zeros.copy(), zeros.copy(), zeros.copy(), {},
                              kpis, diagnostics,
                              {'name': 'none', 'status': 'ok', 'termination_condition': 'empty_coalition',
                               'runtime_seconds': 0.0}, provenance)

    # Lazy imports guarantee that the empty coalition does not import/invoke Pyomo.
    import pyomo.environ as pyo
    from pyomo.opt import SolverStatus, TerminationCondition
    import highspy
    from pyomo import __version__ as pyomo_version
    from .model import build_model

    m = build_model(members, config)
    solver = pyo.SolverFactory('highs')
    if not solver.available(exception_flag=False):
        raise RuntimeError('HiGHS is unavailable')
    _, baseline_provenance = load_baseline()
    settings = baseline_provenance['solver_configuration']
    options = {'solver': settings['algorithm'], 'threads': settings['threads'],
               'random_seed': settings['random_seed'],
               'primal_feasibility_tolerance': settings['primal_feasibility_tolerance'],
               'dual_feasibility_tolerance': settings['dual_feasibility_tolerance']}
    # load_solutions=False allows a clear error before trying to read absent values.
    # HiGHS keeps a process-global scheduler even after another solver is deleted.
    # M3 is a serial API: release that pool before applying the explicit thread
    # count and afterwards so later callers can choose their own configuration.
    # Concurrent optimisation jobs must run in separate processes, not threads.
    highspy.Highs.resetGlobalScheduler(True)
    try:
        solved = solver.solve(m, options=options, tee=False, load_solutions=False)
    finally:
        highspy.Highs.resetGlobalScheduler(True)
    if solved.solver.status != SolverStatus.ok or solved.solver.termination_condition != TerminationCondition.optimal:
        raise RuntimeError(f'Physical solve failed: {solved.solver.status}, {solved.solver.termination_condition}')
    m.solutions.load_from(solved)
    imp = [float(pyo.value(m.grid_import[t])) for t in m.T]
    exp = [float(pyo.value(m.grid_export[t])) for t in m.T]
    dispatch = {}
    for i in members:
        j = config.member_ids.index(i)
        avail = config.pv_available_kw[:, j]
        used = [float(pyo.value(m.pv[i, t])) for t in m.T] if i in m.PV else [0.0] * t_count
        ch = [float(pyo.value(m.charge[i, t])) for t in m.T] if i in m.B else [0.0] * t_count
        dis = [float(pyo.value(m.discharge[i, t])) for t in m.T] if i in m.B else [0.0] * t_count
        soc = [float(pyo.value(m.soc[i, t])) for t in m.K] if i in m.B else [0.0] * (t_count + 1)
        dispatch[i] = MemberDispatch(config.demand_kw[:, j].tolist(), avail.tolist(), used,
                                     (avail - used).tolist(), ch, dis, soc)
    kpis, diagnostics = audit_dispatch(config, dispatch, imp, exp)
    variable = float(np.dot(config.import_aud_per_kwh, imp) -
                     np.dot(config.export_aud_per_kwh, exp)) * p.dt_hours
    fixed = len(members) * config.billing_days * p.daily_connection_fee_aud
    objective_residual = abs(variable + fixed - float(pyo.value(m.cost)))
    if objective_residual > p.cost_tolerance_aud:
        raise ValueError(f'Objective reconstruction residual: {objective_residual} AUD')
    diagnostics['objective_reconstruction_residual_aud'] = objective_residual
    solver_info = {'name': 'highs', 'version': highspy.Highs().version(), 'pyomo_version': pyomo_version,
                   'status': str(solved.solver.status),
                   'termination_condition': str(solved.solver.termination_condition),
                   'options': options, 'runtime_seconds': perf_counter() - started}
    provenance['solver_configuration_used'] = options
    result = PhysicalResult(members, variable + fixed, variable, fixed, imp, exp,
                            config.demand_kw[:, [config.member_ids.index(i) for i in members]].sum(axis=1).tolist(),
                            dispatch, kpis, diagnostics, solver_info, provenance)
    validate_result(result, p)
    return result
