"""Typed financial inputs/results. No dispatch arrays or Pyomo objects."""
from dataclasses import asdict, dataclass
import math
from comfair.game.stability import validate_game
from comfair.physical.config import canonical_json


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


@dataclass(frozen=True)
class RepairProblem:
    standalone: dict[int, float]
    market_bills: dict[int, float]
    u0: dict[int, float]
    values: dict[int, float]
    tolerance: float

    def validate(self):
        n = len(self.u0)
        if not finite(self.tolerance) or self.tolerance <= 0:
            raise ValueError('Positive finite monetary tolerance required')
        validate_game(self.values, n, self.tolerance)
        for mapping in (self.standalone, self.market_bills, self.u0):
            if (set(mapping) != set(range(1, n + 1)) or any(type(i) is not int for i in mapping)
                    or not all(finite(x) for x in mapping.values())):
                raise ValueError('Invalid financial member mapping or amount')
        if any(abs(self.standalone[i] - self.market_bills[i] - self.u0[i]) > self.tolerance for i in self.u0):
            raise ValueError('Market benefit/bill reconstruction mismatch')
        if abs(sum(self.u0.values()) - self.values[2**n - 1]) > self.tolerance:
            raise ValueError('Market anchor is not efficient for this game')

    @property
    def members(self):
        return tuple(sorted(self.u0))


class Serializable:
    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return canonical_json(self.to_dict())


@dataclass(frozen=True)
class RepairWitness(Serializable):
    tau_aud: dict[int, float]
    benefit_aud: dict[int, float]
    bill_aud: dict[int, float]
    absolute_transfer_aud: dict[int, float]
    repair_volume_aud: float
    diagnostics: dict
    solver: dict
    epsilon_aud: float | None = None
    repair_budget_aud: float | None = None


@dataclass(frozen=True)
class IndividualRepairResult(Serializable):
    r_IR_aud: float
    r_IR_analytical_aud: float
    identity_residual_aud: float
    witness: RepairWitness


@dataclass(frozen=True)
class CoalitionRepairResult(Serializable):
    epsilon_IR_aud: float
    epsilon_star_aud: float
    epsilon_star_m5_aud: float
    epsilon_star_validation_residual_aud: float
    epsilon_target_aud: float
    stability_tolerance_aud: float
    r_CR_aud: float
    epsilon_at_r_CR_aud: float
    CRP_aud: float
    RSG_aud: float
    epsilon_IR_witness: RepairWitness
    witness: RepairWitness
    epsilon_at_r_CR_witness: RepairWitness
    least_core_check_solver: dict


@dataclass(frozen=True)
class RepairCurve(Serializable):
    degenerate_curve: bool
    points: list[dict]
    diagnostics: dict
