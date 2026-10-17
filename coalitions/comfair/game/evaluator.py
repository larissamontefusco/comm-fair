"""Compact coalition-cost adapter around the existing legacy bi-level path."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping, Protocol
import math

import numpy as np

from comfair.forecasting.adapters.bundle import ForecastBundle
from comfair.physical.config import canonical_json
from .coalitions import member_universe


BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_GRID_PRICES = BACKEND / "inputs" / "prices.csv"
COMMUNITY_MODELS = {"c0", "c2", "c3", "c4", "c5"}
MARKET_STAGES = (
    "C0 Household",
    "C0 EC",
    "pricing",
    "C1",
    "community",
    "Household-2",
)


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _fingerprint(value) -> str:
    return sha256(canonical_json(_jsonable(value)).encode()).hexdigest()


@dataclass(frozen=True)
class BilevelRunRequest:
    """One coalition request that always retains the full issued forecast."""

    members: tuple[int, ...]
    community_model: str
    forecast_bundle: ForecastBundle
    solver_name: str
    pricing_config: Mapping = field(default_factory=dict)
    optimizer_config: Mapping = field(default_factory=dict)

    @property
    def forecast_columns(self) -> tuple[int, ...]:
        positions = {
            member: column
            for column, member in enumerate(self.forecast_bundle.member_ids)
        }
        return tuple(positions[member] for member in self.members)

    @property
    def load_kw(self) -> np.ndarray:
        return self.forecast_bundle.load_kw[:, self.forecast_columns]

    @property
    def pv_available_kw(self) -> np.ndarray:
        return self.forecast_bundle.pv_available_kw[:, self.forecast_columns]


@dataclass(frozen=True)
class CoalitionEvaluation:
    """Solver-independent economic result returned to the game engine."""

    members: tuple[int, ...]
    community_model: str
    member_costs: Mapping[int, float]
    total_final_member_cost: float
    solver: Mapping
    pricing_provenance: Mapping
    forecast_provenance: Mapping
    evaluation_stage: str
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
            raise ValueError("Coalition pipeline did not report solver status=ok")
        if self.community_model == "c0":
            if self.evaluation_stage != "C0":
                raise ValueError("C0 coalition cost must come directly from C0")
        else:
            if self.evaluation_stage != "Household-2":
                raise ValueError(
                    "Market coalition cost must use Household-2 outcomes"
                )
            priced_members = tuple(
                self.pricing_provenance.get("coalition_members", ())
            )
            if priced_members != self.members:
                raise ValueError(
                    "EC pricing provenance is not coalition-specific"
                )
            if (
                self.pricing_provenance.get("source")
                != "pricing_model_v1.price_arrays"
            ):
                raise ValueError("Unexpected coalition EC-price source")

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


class CoalitionCostEvaluator(Protocol):
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


def _member_id(key) -> int:
    if type(key) is int:
        return key
    text = str(key).strip()
    if text.lower().startswith("member "):
        text = text.split()[-1]
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"Unrecognised member-cost key {key!r}") from exc


def _operational_member_costs(
    stage: Mapping, members: tuple[int, ...]
) -> dict[int, float]:
    try:
        raw = stage["kpis_per_member"]["Operational Cost"]["value"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            "Legacy result has no per-member Operational Cost KPI"
        ) from exc
    costs = {_member_id(key): float(value) for key, value in raw.items()}
    if set(costs) != set(members):
        raise ValueError(
            "Legacy final-cost owners mismatch: "
            f"expected {members}, got {tuple(sorted(costs))}"
        )
    return costs


class LegacyBilevelCoalitionEvaluator:
    """Evaluate coalitions with one immutable forecast and the legacy pipeline.

    ``pipeline_runner`` is injectable for focused tests. In production it is a
    thin call to ``CentralizedMethod``; the game engine never imports Pyomo
    variables from C1-C5.
    """

    def __init__(
        self,
        *,
        forecast_origin_t: int,
        community_model: str = "c2",
        solver_name: str = "scip",
        member_ids=(1, 2, 3, 4, 5, 6, 7, 8, 9),
        forecast_bundle: ForecastBundle | None = None,
        grid_prices_path: str | Path = DEFAULT_GRID_PRICES,
        pricing_config: Mapping | None = None,
        optimizer_config: Mapping | None = None,
        pipeline_runner: Callable[
            [BilevelRunRequest], Mapping | CoalitionEvaluation
        ]
        | None = None,
        cost_tolerance: float = 1e-5,
    ):
        self.member_ids = member_universe(member_ids)
        if community_model not in COMMUNITY_MODELS:
            raise ValueError(
                f"community_model must be one of {sorted(COMMUNITY_MODELS)}"
            )
        if (
            not isinstance(cost_tolerance, (int, float))
            or not math.isfinite(cost_tolerance)
            or cost_tolerance <= 0
        ):
            raise ValueError("cost_tolerance must be positive and finite")
        if forecast_bundle is None:
            from comfair.forecasting.rolling.forecasting import (
                build_operational_forecast_bundle,
            )

            forecast_bundle = build_operational_forecast_bundle(
                forecast_origin_t
            )
        if forecast_bundle.origin_t != forecast_origin_t:
            raise ValueError(
                "Pre-issued forecast origin does not match evaluator origin"
            )
        missing = sorted(
            set(self.member_ids) - set(forecast_bundle.member_ids)
        )
        if missing:
            raise ValueError(
                f"Coalition members absent from forecast bundle: {missing}"
            )

        grid_prices_path = Path(grid_prices_path)
        self.forecast_origin_t = forecast_origin_t
        self.community_model = community_model
        self.solver_name = solver_name
        self.forecast_bundle = forecast_bundle
        self.grid_prices_path = grid_prices_path
        self.pricing_config = dict(pricing_config or {})
        self.optimizer_config = dict(optimizer_config or {})
        self.cost_tolerance = float(cost_tolerance)
        self._pipeline_runner = (
            pipeline_runner or self._run_legacy_pipeline
        )
        self._evaluations: dict[
            tuple[str, tuple[int, ...]], CoalitionEvaluation
        ] = {}
        self._forecast_sha256 = sha256(
            forecast_bundle.to_json().encode()
        ).hexdigest()
        self._grid_tariff_sha256 = sha256(
            grid_prices_path.read_bytes()
        ).hexdigest()

    def cache_context(self) -> Mapping:
        return {
            "schema_version": 1,
            "evaluator": "legacy_bilevel",
            "member_ids": list(self.member_ids),
            "community_model": self.community_model,
            "forecast_origin_t": self.forecast_origin_t,
            "forecast_sha256": self._forecast_sha256,
            "grid_tariff_sha256": self._grid_tariff_sha256,
            "pricing_configuration": _jsonable(self.pricing_config),
            "optimizer_configuration": _jsonable(self.optimizer_config),
            "solver_name": self.solver_name,
        }

    def _request(
        self, members: tuple[int, ...], community_model: str
    ) -> BilevelRunRequest:
        members = tuple(sorted(members))
        if not members or any(
            member not in self.member_ids for member in members
        ):
            raise ValueError("Coalition contains an invalid evaluator member")
        return BilevelRunRequest(
            members=members,
            community_model=community_model,
            forecast_bundle=self.forecast_bundle,
            solver_name=self.solver_name,
            pricing_config=self.pricing_config,
            optimizer_config=self.optimizer_config,
        )

    def _run_legacy_pipeline(self, request: BilevelRunRequest):
        from methods.bi_level_method import CentralizedMethod

        options = dict(request.optimizer_config)
        weights = options.pop(
            "weights",
            [[0, 1, 0, 0, 0, 0, 0] for _ in request.members],
        )
        return CentralizedMethod().run_centralized_method(
            number_of_residences=len(request.members),
            opt_timestep=60,
            weights=weights,
            sharing_method=options.pop("sharing_method", None),
            data_type="ComFair Forecast",
            selected_solver=request.solver_name,
            selected_houses=list(request.members),
            num_days=1,
            community_model=request.community_model,
            forecast_origin_t=request.forecast_bundle.origin_t,
            forecast_bundle=request.forecast_bundle,
            **options,
        )

    def _normalise(
        self, raw, request: BilevelRunRequest
    ) -> CoalitionEvaluation:
        if isinstance(raw, CoalitionEvaluation):
            evaluation = raw
        else:
            if not isinstance(raw, Mapping):
                raise TypeError(
                    "Bi-level runner must return a mapping or CoalitionEvaluation"
                )
            if request.community_model == "c0":
                stage = raw.get("centralized_results")
                evaluation_stage = "C0"
            else:
                stage = raw.get("second_centralized_results")
                evaluation_stage = "Household-2"
            if not isinstance(stage, Mapping):
                raise ValueError(
                    f"Legacy result is missing {evaluation_stage} results"
                )
            costs = _operational_member_costs(stage, request.members)

            trace = raw.get("execution_trace", raw.get("trace", {}))
            stages = (
                tuple(trace.get("stages", ()))
                if isinstance(trace, Mapping)
                else ()
            )
            if request.community_model != "c0" and not all(
                name in stages for name in MARKET_STAGES
            ):
                raise ValueError(
                    "Bi-level result does not prove C0 Household -> C0 EC -> "
                    "pricing -> C1 -> community -> Household-2 execution"
                )
            pricing = raw.get(
                "pricing_provenance",
                trace.get("pricing", {})
                if isinstance(trace, Mapping)
                else {},
            )
            if request.community_model == "c0":
                pricing = {
                    "mode": "not_applicable_c0",
                    "coalition_members": list(request.members),
                }
            solver = raw.get(
                "solver",
                {
                    "name": request.solver_name,
                    "status": "ok",
                    "termination_condition": "completed",
                },
            )
            evaluation = CoalitionEvaluation(
                members=request.members,
                community_model=request.community_model,
                member_costs=costs,
                total_final_member_cost=float(sum(costs.values())),
                solver=solver,
                pricing_provenance=pricing,
                forecast_provenance={
                    "origin_t": self.forecast_origin_t,
                    "forecast_sha256": self._forecast_sha256,
                    "source": self.forecast_bundle.forecast_provenance,
                },
                evaluation_stage=evaluation_stage,
                ec_manager=raw.get("ec_manager", {}),
                diagnostics={"execution_stages": list(stages)},
            )
        if (
            evaluation.members != request.members
            or evaluation.community_model != request.community_model
        ):
            raise ValueError(
                "Runner returned a result for a different coalition/model"
            )
        evaluation.validate()
        return evaluation

    def _evaluate(
        self, members: tuple[int, ...], community_model: str
    ) -> CoalitionEvaluation:
        request = self._request(members, community_model)
        key = (community_model, request.members)
        if key not in self._evaluations:
            raw = self._pipeline_runner(request)
            self._evaluations[key] = self._normalise(raw, request)
        return self._evaluations[key]

    def standalone_evaluation(
        self, member_id: int
    ) -> CoalitionEvaluation:
        if member_id not in self.member_ids:
            raise ValueError(f"Unknown standalone member {member_id}")
        return self._evaluate((member_id,), "c0")

    def coalition_evaluation(
        self, members: tuple[int, ...]
    ) -> CoalitionEvaluation:
        members = tuple(sorted(members))
        if len(members) == 1:
            return self.standalone_evaluation(members[0])
        return self._evaluate(members, self.community_model)
