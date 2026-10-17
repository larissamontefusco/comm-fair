"""Minimum individual repair, checked against the independent analytical identity."""
import pyomo.environ as pyo
from .model import build_model, extract, solve_model
from .results import IndividualRepairResult


def solve_individual_repair(problem):
    m = build_model(problem)
    m.objective = pyo.Objective(expr=m.R)
    witness = extract(m, problem, solve_model(m))
    analytical = sum(max(0., -problem.u0[i]) for i in problem.members)
    residual = witness.repair_volume_aud - analytical
    if abs(residual) > problem.tolerance:
        raise ValueError('Optimised/analytical r_IR identity failed')
    return IndividualRepairResult(witness.repair_volume_aud, analytical, residual, witness)
