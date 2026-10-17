"""Typed result contracts and schemas for nine-member benchmark and partition evaluations."""
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class BenchmarkResultType(str, Enum):
    CALCULATED_ECONOMIC_COMPARISON = "calculated_economic_comparison"
    PRECOMPUTED_ECONOMIC_COMPARISON = "precomputed_economic_comparison"
    FULL_GAME_WITH_STABILITY = "full_game_with_stability"
    PARTIAL_OR_UNAVAILABLE = "partial_or_unavailable"
    OPTIMIZATION_FAILURE = "optimization_failure"


class BenchmarkStatus(str, Enum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class StabilityStatus(str, Enum):
    CERTIFIED = "certified"
    NOT_EVALUATED = "not_evaluated"
    INFEASIBLE_HARD_NO_HARM = "infeasible_hard_no_harm"


@dataclass(frozen=True)
class PartitionBlockResult:
    block_index: int
    members: list[int]
    size: int
    mask: int
    cost_aud: float
    standalone_cost_aud: float
    value_aud: float
    is_precomputed: bool
    community_model: str = "c2"
    member_costs_aud: dict[str, float] = field(default_factory=dict)
    member_benefits_aud: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkEvaluationResponse:
    result_type: str
    status: str
    data_source: str
    is_precomputed: bool
    community_model: str
    member_ids: list[int]
    forecast_origin_t: Optional[int]
    grand_coalition_cost_aud: Optional[float]
    sum_standalone_cost_aud: Optional[float]
    v_N_aud: Optional[float]
    time_horizon: str = "annual"
    horizon_hours: int = 8760
    evaluation_level: str = "economic_comparison"
    standalone_costs_aud: dict[str, float] = field(default_factory=dict)
    member_costs_aud: dict[str, float] = field(default_factory=dict)
    member_benefits_aud: dict[str, float] = field(default_factory=dict)
    stability_certificate: Optional[dict[str, Any]] = None
    stability_available: bool = False
    stability_status: str = StabilityStatus.NOT_EVALUATED.value
    stability_explanation: Optional[str] = None
    partition_results: Optional[list[dict[str, Any]]] = None
    provenance: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkEvaluationResponse":
        return cls(**dict(data))
