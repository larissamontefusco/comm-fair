"""Cryptographic context binding and fingerprinting for nine-member benchmarks.

Every precomputed result and evaluation request is bound to an immutable context
covering: dataset hash, canonical member IDs, forecast origin/horizon, model,
simulated assets hash, solver name/config, and code schema version.
"""
from dataclasses import dataclass
import hashlib
from typing import Any, Optional, Sequence, Tuple

from .jsonutil import canonical_json

WORKBOOK_SHA256 = "c559bd7dc946b2f0c01c8cc96beea75c783f3b48bdd7fe6da855b2ef01f75370"
CANONICAL_BENCHMARK_MEMBERS: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9)
SUPPORTED_COMMUNITY_MODELS = ("baseline", "cooperative_pool")
SCHEMA_VERSION = 1


def _simulated_assets_hash(value: Any) -> str:
    """Fingerprint optional scenario data without a platform helper module."""
    normalized = {} if value is None else value
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BenchmarkContext:
    dataset_hash: str
    member_ids: Tuple[int, ...]
    forecast_origin_t: Optional[int]
    community_model: str
    simulated_assets_hash: str
    solver_name: str
    schema_version: int = SCHEMA_VERSION

    @property
    def time_horizon(self) -> str:
        return "annual" if self.forecast_origin_t is None else "daily"

    @property
    def horizon_hours(self) -> int:
        return 8760 if self.forecast_origin_t is None else 24

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_hash": self.dataset_hash,
            "member_ids": list(self.member_ids),
            "forecast_origin_t": self.forecast_origin_t,
            "time_horizon": self.time_horizon,
            "horizon_hours": self.horizon_hours,
            "community_model": self.community_model,
            "simulated_assets_hash": self.simulated_assets_hash,
            "solver_name": self.solver_name,
            "schema_version": self.schema_version,
        }

    @property
    def context_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def is_canonical_annual_cooperative_pool(self) -> bool:
        """True for the official annual M5 cooperative-pool benchmark."""
        return (
            self.dataset_hash == WORKBOOK_SHA256
            and self.member_ids == CANONICAL_BENCHMARK_MEMBERS
            and self.forecast_origin_t is None
            and self.community_model == "cooperative_pool"
            and self.simulated_assets_hash == _simulated_assets_hash(None)
            and self.solver_name == "highs"
        )

    def is_canonical_annual_baseline(self) -> bool:
        """True for the official annual M3 standalone baseline."""
        return (
            self.dataset_hash == WORKBOOK_SHA256
            and self.member_ids == CANONICAL_BENCHMARK_MEMBERS
            and self.forecast_origin_t is None
            and self.community_model == "baseline"
            and self.simulated_assets_hash == _simulated_assets_hash(None)
            and self.solver_name == "highs"
        )


def build_benchmark_context(
    *,
    member_ids: Optional[Sequence[int]] = None,
    forecast_origin_t: Optional[int] = None,
    community_model: str = "cooperative_pool",
    simulated_assets: Any = None,
    solver_name: str = "highs",
    dataset_hash: str = WORKBOOK_SHA256,
) -> BenchmarkContext:
    """Build and validate a cryptographic benchmark context."""
    if member_ids is None:
        members = CANONICAL_BENCHMARK_MEMBERS
    else:
        try:
            members = tuple(sorted(int(m) for m in member_ids))
        except (TypeError, ValueError) as exc:
            raise ValueError("member_ids must be an iterable of integers") from exc
        if not members:
            raise ValueError("member_ids cannot be empty")
        if any(m <= 0 for m in members):
            raise ValueError("member_ids must be positive integers")
        if len(set(members)) != len(members):
            raise ValueError("member_ids must be unique")

    if community_model not in SUPPORTED_COMMUNITY_MODELS:
        raise ValueError(
            f"Unsupported community_model '{community_model}'; must be one of {SUPPORTED_COMMUNITY_MODELS}"
        )

    if forecast_origin_t is not None:
        if not isinstance(forecast_origin_t, int) or forecast_origin_t < 1 or forecast_origin_t > 8760:
            raise ValueError(f"forecast_origin_t must be an integer in 1..8760, got {forecast_origin_t}")

    if isinstance(simulated_assets, str) and len(simulated_assets) == 64 and all(c in "0123456789abcdefABCDEF" for c in simulated_assets):
        assets_hash = simulated_assets.lower()
    else:
        assets_hash = _simulated_assets_hash(simulated_assets)

    return BenchmarkContext(
        dataset_hash=str(dataset_hash),
        member_ids=members,
        forecast_origin_t=forecast_origin_t,
        community_model=community_model,
        simulated_assets_hash=assets_hash,
        solver_name=str(solver_name).lower(),
    )
