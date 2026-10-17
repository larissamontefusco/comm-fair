"""Small evaluator interface for optional, explicitly supplied calculations.

The standalone site serves the baseline and cooperative-pool artifacts. It deliberately
does not bundle the historical forecasting and bi-level optimisation platform.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Protocol
import math


COMMUNITY_MODELS = frozenset(("baseline", "cooperative_pool"))


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class CoalitionEvaluation:
    """Solver-independent economic result accepted by the game engine."""

    members: tuple[int, ...]
    community_model: str
    member_costs: Mapping[int, float]
    total_final_member_cost: float
    solver: Mapping
    pricing_provenance: Mapping = field(default_factory=dict)
    forecast_provenance: Mapping = field(default_factory=dict)
    evaluation_stage: str = "precomputed"
    ec_manager: Mapping = field(default_factory=dict)
    diagnostics: Mapping = field(default_factory=dict)
    currency: str = "AUD"

    def validate(self) -> None:
        if (
            not self.members
            or self.members != tuple(sorted(self.members))
            or self.community_model not in COMMUNITY_MODELS
        ):
            raise ValueError("Invalid coalition evaluation member/model mapping")
        costs = {
            int(member): float(value)
            for member, value in self.member_costs.items()
        }
        if set(costs) != set(self.members) or any(
            not math.isfinite(value) for value in costs.values()
        ):
            raise ValueError("Final member costs must cover exactly the coalition")
        if (
            not math.isfinite(self.total_final_member_cost)
            or abs(sum(costs.values()) - self.total_final_member_cost) > 1e-7
        ):
            raise ValueError("Coalition total does not equal final member costs")
        if self.solver.get("status") != "ok":
            raise ValueError("Coalition evaluation did not report solver status=ok")

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


class CoalitionCostEvaluator(Protocol):
    """Interface for callers that explicitly provide a calculation backend."""

    member_ids: tuple[int, ...]
    community_model: str
    cost_tolerance: float

    def cache_context(self) -> Mapping: ...

    def standalone_evaluation(
        self, member_id: int
    ) -> CoalitionEvaluation: ...

    def coalition_evaluation(
        self, members: tuple[int, ...]
    ) -> CoalitionEvaluation: ...
