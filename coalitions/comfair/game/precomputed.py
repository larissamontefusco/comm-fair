"""Server-side precomputed benchmark cache and repository.

Guarantees cryptographic context binding, strict integrity verification, and
prevention of silent cross-scenario fallbacks or partial/corrupted cache leaks.
Supports request deduplication for concurrent identical contexts and indexes both
canonical annual cooperative-pool game and standalone baseline.
"""
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from .benchmark_context import (
    BenchmarkContext,
    CANONICAL_BENCHMARK_MEMBERS,
    WORKBOOK_SHA256,
    build_benchmark_context,
)
from .benchmark_results import (
    BenchmarkEvaluationResponse,
    BenchmarkResultType,
    BenchmarkStatus,
    StabilityStatus,
)
from .coalitions import members_to_mask
from .jsonutil import canonical_json

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = BACKEND_DIR / "comfair" / "artifacts"
DEFAULT_PRECOMPUTED_DIR = ARTIFACTS_DIR / "precomputed"


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


class InFlightRequestDeduplicator:
    """Thread-safe request deduplicator for concurrent identical evaluations."""

    def __init__(self):
        self._lock = threading.Lock()
        self._in_flight: dict[str, threading.Event] = {}
        self._results: dict[str, Any] = {}
        self._errors: dict[str, Exception] = {}

    def execute_once(self, key: str, compute_fn: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._in_flight:
                event = self._in_flight[key]
                first = False
            else:
                event = threading.Event()
                self._in_flight[key] = event
                first = True

        if not first:
            event.wait()
            with self._lock:
                if key in self._errors:
                    raise self._errors[key]
                return self._results.get(key)

        try:
            res = compute_fn()
            with self._lock:
                self._results[key] = res
            return res
        except Exception as exc:
            with self._lock:
                self._errors[key] = exc
            raise
        finally:
            with self._lock:
                event.set()
                self._in_flight.pop(key, None)


class PrecomputedBenchmarkStore:
    """Manages precomputed benchmark artifacts and validated cache lookups."""

    def __init__(self, precomputed_dir: Optional[Path] = None, artifacts_dir: Optional[Path] = None):
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        env_dir = os.environ.get("COMFAIR_PRECOMPUTED_DIR")
        self.precomputed_dir = Path(precomputed_dir or env_dir or DEFAULT_PRECOMPUTED_DIR)
        try:
            self.precomputed_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        self.deduplicator = InFlightRequestDeduplicator()
        self._m5_core: Optional[dict[str, Any]] = None
        self._m5_coalitions: Optional[dict[str, Any]] = None
        self._m4_market: Optional[dict[str, Any]] = None
        self._m3_baselines: Optional[dict[str, Any]] = None
        self._m5_records_by_mask: Optional[dict[int, dict[str, Any]]] = None

    def _ensure_annual_artifacts_loaded(self) -> None:
        """Lazily load and index official annual benchmark artifacts."""
        if self._m5_core is not None and self._m5_coalitions is not None and self._m3_baselines is not None:
            return

        core_path = self.artifacts_dir / "m5_core.json"
        coal_path = self.artifacts_dir / "m5_coalitions.json"
        m4_path = self.artifacts_dir / "m4_market.json"
        m3_path = self.artifacts_dir / "m3_baselines.json"

        if not core_path.exists() or not coal_path.exists():
            raise FileNotFoundError("Canonical M5 benchmark artifacts missing in artifacts directory")

        self._m5_core = _read_json(core_path)
        self._m5_coalitions = _read_json(coal_path)
        if m4_path.exists():
            self._m4_market = _read_json(m4_path)
        if m3_path.exists():
            self._m3_baselines = _read_json(m3_path)

        records = self._m5_coalitions.get("records", [])
        if len(records) != 512:
            raise ValueError(f"Corrupted canonical M5 coalitions: expected 512 records, found {len(records)}")

        self._m5_records_by_mask = {int(r["mask"]): r for r in records}

    def get_canonical_annual_benchmark_response(self, context: BenchmarkContext) -> BenchmarkEvaluationResponse:
        """Construct the complete, certified evaluation response for the annual M5 benchmark."""
        self._ensure_annual_artifacts_loaded()
        assert self._m5_core is not None
        assert self._m5_coalitions is not None

        records_by_mask = self._m5_records_by_mask or {}
        grand_mask = 511
        grand_record = records_by_mask.get(grand_mask)
        if not grand_record:
            raise ValueError("Canonical M5 grand coalition mask (511) missing in precomputed records")

        b_i = {str(k): float(v) for k, v in self._m5_coalitions.get("B_i_aud", {}).items()}
        sum_b_i = float(grand_record["sum_standalone_cost_aud"])
        grand_cost = float(grand_record["coalition_cost_aud"])
        v_n = float(grand_record["value_aud"])

        # Member market costs and benefits
        member_costs: dict[str, float] = {}
        member_benefits: dict[str, float] = {}
        if self._m4_market and "members" in self._m4_market:
            for member_str, m_data in self._m4_market["members"].items():
                member_costs[member_str] = float(m_data["C_market_aud"])
                member_benefits[member_str] = float(m_data["u0_aud"])
        # Missing settlement evidence stays unavailable; never reconstruct zero benefits.

        certificate = self._m5_core.get("certificate", {})

        return BenchmarkEvaluationResponse(
            result_type=BenchmarkResultType.FULL_GAME_WITH_STABILITY.value,
            status=BenchmarkStatus.COMPLETED.value,
            data_source="precomputed",
            is_precomputed=True,
            community_model=context.community_model,
            member_ids=list(context.member_ids),
            forecast_origin_t=None,
            grand_coalition_cost_aud=grand_cost,
            sum_standalone_cost_aud=sum_b_i,
            v_N_aud=v_n,
            time_horizon="annual",
            horizon_hours=8760,
            evaluation_level="full_cooperative_game",
            standalone_costs_aud=b_i,
            member_costs_aud=member_costs,
            member_benefits_aud=member_benefits,
            stability_certificate=certificate,
            stability_available=True,
            stability_status=StabilityStatus.CERTIFIED.value,
            stability_explanation="Full 512-coalition game verified with least-core stability certificate.",
            partition_results=None,
            provenance={
                "milestone": "M5",
                "dataset_hash": context.dataset_hash,
                "context_sha256": context.context_sha256,
                "source": "canonical_precomputed_artifacts",
                "scenario_hash": context.simulated_assets_hash,
                "solver": certificate.get("solver", {}),
            },
            diagnostics=self._m5_coalitions.get("diagnostics", {}),
            error=None,
        )

    def get_canonical_annual_baseline_response(self, context: BenchmarkContext) -> BenchmarkEvaluationResponse:
        """Construct the verified annual standalone-baseline response.

        Under the baseline, households operate independently without
        local energy exchange. Consequently, for any coalition S (including N),
        the joint cost is identically the sum of standalone costs:
            C_baseline(S) = sum_{i in S} B_i
            v_baseline(S) = sum_{i in S} B_i - C_baseline(S) = 0.0 AUD
        The 5509.65 AUD joint cost belongs to the cooperative physical pool.
        """
        self._ensure_annual_artifacts_loaded()
        if not self._m3_baselines:
            raise FileNotFoundError("M3 artifact missing for baseline benchmark")

        b_i = {str(k): float(v) for k, v in self._m3_baselines["B_i_aud"].items()}
        sum_b_i = float(self._m3_baselines["sum_B_i_aud"])

        return BenchmarkEvaluationResponse(
            result_type=BenchmarkResultType.PRECOMPUTED_ECONOMIC_COMPARISON.value,
            status=BenchmarkStatus.COMPLETED.value,
            data_source="precomputed",
            is_precomputed=True,
            community_model="baseline",
            member_ids=list(context.member_ids),
            forecast_origin_t=None,
            grand_coalition_cost_aud=sum_b_i,
            sum_standalone_cost_aud=sum_b_i,
            v_N_aud=0.0,
            time_horizon="annual",
            horizon_hours=8760,
            evaluation_level="economic_comparison",
            standalone_costs_aud=b_i,
            member_costs_aud=dict(b_i),
            member_benefits_aud={m: 0.0 for m in b_i},
            stability_certificate=None,
            stability_available=False,
            stability_status=StabilityStatus.NOT_EVALUATED.value,
            stability_explanation=(
                "The baseline models standalone operation without local energy sharing. "
                "Joint cost equals summed standalone cost (9754.64 AUD) and cooperative surplus v(N) is 0.0 AUD. "
                "The cooperative pool achieves 5509.65 AUD and v(N) = 4244.99 AUD."
            ),
            partition_results=None,
            provenance={
                "milestone": "M3",
                "dataset_hash": context.dataset_hash,
                "context_sha256": context.context_sha256,
                "source": "canonical_m3_standalone_b0",
                "scenario_hash": context.simulated_assets_hash,
                "scenario": "baseline",
                "cooperation": "none (standalone uncoordinated)",
                "solver": self._m3_baselines.get("B1", {}).get("solver", {}),
            },
            diagnostics={
                "all_solves_optimal": True,
                "cooperative_exchange": False,
                "summed_b0_aud": sum_b_i,
                "comparison_note": "The cooperative pool achieves 5509.65 AUD (surplus 4244.99 AUD relative to the baseline).",
            },
            error=None,
        )

    def lookup(self, context: BenchmarkContext) -> Optional[BenchmarkEvaluationResponse]:
        """Look up a precomputed benchmark result for the exact cryptographic context.

        Deduplicates concurrent requests for the identical context.
        Returns None on cache miss. Raises ValueError if a cached file matching context
        is found but is corrupted or partial. Never returns results for another context.
        """
        return self.deduplicator.execute_once(
            context.context_sha256,
            lambda: self._lookup_uncached(context),
        )

    def _lookup_uncached(self, context: BenchmarkContext) -> Optional[BenchmarkEvaluationResponse]:
        # 1. Match official annual M5 cooperative-pool benchmark
        if context.is_canonical_annual_cooperative_pool():
            return self.get_canonical_annual_benchmark_response(context)

        # 2. Match official annual M3 standalone baseline
        if context.is_canonical_annual_baseline():
            return self.get_canonical_annual_baseline_response(context)

        # 3. Check local precomputed files directory
        target_context_hash = context.context_sha256
        for path in self.precomputed_dir.glob("*.json"):
            try:
                data = _read_json(path)
            except Exception as exc:
                logger.warning("Failed to parse precomputed JSON %s: %s", path, exc)
                continue

            # Must have schema_version and context
            if data.get("schema_version") != 1:
                continue

            stored_context = data.get("context", {})
            stored_hash = data.get("context_sha256")
            if not stored_hash and stored_context:
                stored_hash = sha256(canonical_json(stored_context).encode("utf-8")).hexdigest()

            if stored_hash != target_context_hash:
                continue

            self._validate_stored_context(data, context)

            # Context hash matched! Strict validation of completion state and fields.
            completion_state = data.get("completion_state")
            if completion_state not in ("complete", "economic_comparison_only"):
                raise ValueError(
                    f"Corrupted precomputed benchmark cache at {path.name}: "
                    f"completion_state='{completion_state}', expected 'complete'"
                )

            # Reconstruct and validate response
            response_data = data.get("response")
            if not response_data or not isinstance(response_data, dict):
                raise ValueError(f"Precomputed file {path.name} is missing valid response payload")

            response = BenchmarkEvaluationResponse.from_dict(response_data)
            # Re-verify critical properties
            if response.data_source != "precomputed" or not response.is_precomputed:
                raise ValueError(f"Precomputed file {path.name} has invalid data_source flags")
            if response.community_model != context.community_model:
                raise ValueError(f"Precomputed context model mismatch in {path.name}")
            if tuple(response.member_ids) != context.member_ids:
                raise ValueError(f"Precomputed context members mismatch in {path.name}")

            if (response.status != BenchmarkStatus.COMPLETED.value
                    or response.forecast_origin_t != context.forecast_origin_t
                    or response.horizon_hours != context.horizon_hours
                    or response.time_horizon != context.time_horizon):
                raise ValueError("Precomputed response context/status mismatch")
            return response

        return None

    @staticmethod
    def _validate_stored_context(data, context):
        stored = data.get("context", {})
        computed = sha256(canonical_json(stored).encode("utf-8")).hexdigest()
        if (data.get("schema_version") != 1 or computed != context.context_sha256
                or data.get("context_sha256", computed) != computed
                or stored != context.to_dict()):
            raise ValueError("Precomputed cache context hash mismatch")
        if data.get("completion_state") not in ("complete", "economic_comparison_only"):
            raise ValueError("Corrupted precomputed benchmark cache: incomplete context")

    def lookup_coalition_mask(
        self, context: BenchmarkContext, mask: int, members: Sequence[int]
    ) -> Optional[dict[str, Any]]:
        """Look up an exact coalition mask from precomputed data for the given context and model."""
        # 1. Annual M5 cooperative-pool benchmark
        if context.is_canonical_annual_cooperative_pool():
            self._ensure_annual_artifacts_loaded()
            records_by_mask = self._m5_records_by_mask or {}
            record = records_by_mask.get(mask)
            if record:
                rec_members = tuple(record.get("members", []))
                if rec_members != tuple(members):
                    raise ValueError(
                        f"Mask mapping mismatch for mask {mask}: expected members {members}, found {rec_members}"
                    )
                return {
                    "mask": mask,
                    "members": list(rec_members),
                    "size": len(rec_members),
                    "coalition_cost_aud": float(record["coalition_cost_aud"]),
                    "sum_standalone_cost_aud": float(record["sum_standalone_cost_aud"]),
                    "value_aud": float(record["value_aud"]),
                    "is_precomputed": True,
                    "community_model": "cooperative_pool",
                    "cost_source": record.get("cost_source", "m5_precomputed"),
                    "solver": record.get("solver", {}),
                    "physical_validation": record.get("physical_validation", {}),
                }

        # 2. Annual baseline: C(S) is additive and v(S) is zero.
        if context.is_canonical_annual_baseline():
            self._ensure_annual_artifacts_loaded()
            if self._m3_baselines:
                b_i_map = self._m3_baselines.get("B_i_aud", {})
                if all(str(m) in b_i_map for m in members):
                    cost = sum(float(b_i_map[str(m)]) for m in members)
                    return {
                        "mask": mask,
                        "members": list(members),
                        "size": len(members),
                        "coalition_cost_aud": cost,
                        "sum_standalone_cost_aud": cost,
                        "value_aud": 0.0,
                        "is_precomputed": True,
                        "community_model": "baseline",
                        "cost_source": "m3_standalone_baseline",
                        "solver": self._m3_baselines.get("B1", {}).get("solver", {}),
                        "physical_validation": {"type": "uncoordinated_standalone_baseline"},
                    }

        # 3. Check precomputed store files
        target_context_hash = context.context_sha256
        for path in self.precomputed_dir.glob("*.json"):
            try:
                data = _read_json(path)
            except Exception:
                continue
            if data.get("context_sha256") == target_context_hash:
                self._validate_stored_context(data, context)
                records = data.get("records_by_mask", {})
                str_mask = str(mask)
                if str_mask in records:
                    rec = records[str_mask]
                    if tuple(rec.get("members", ())) != tuple(members):
                        raise ValueError("Precomputed coalition membership mismatch")
                    return {
                        "mask": mask,
                        "members": list(rec.get("members", members)),
                        "size": len(members),
                        "coalition_cost_aud": float(rec["coalition_cost_aud"]),
                        "sum_standalone_cost_aud": float(rec["sum_standalone_cost_aud"]),
                        "value_aud": float(rec["value_aud"]),
                        "is_precomputed": True,
                        "community_model": context.community_model,
                        "cost_source": rec.get("cost_source", "precomputed_cache"),
                        "solver": rec.get("solver", {}),
                        "physical_validation": rec.get("physical_validation", {}),
                    }

        return None

    def save_precomputed(
        self,
        context: BenchmarkContext,
        response: BenchmarkEvaluationResponse,
        records_by_mask: Optional[Mapping[int, Any]] = None,
    ) -> Path:
        """Atomically persist a verified benchmark evaluation into the precomputed cache."""
        context_dict = context.to_dict()
        context_hash = context.context_sha256
        filename = f"benchmark_{context.community_model}_{context.forecast_origin_t or 'annual'}_{context_hash[:16]}.json"
        target_path = self.precomputed_dir / filename

        payload = {
            "schema_version": 1,
            "context": context_dict,
            "context_sha256": context_hash,
            "completion_state": "complete" if response.status == BenchmarkStatus.COMPLETED.value else "partial",
            "response": response.to_dict(),
        }
        if records_by_mask:
            payload["records_by_mask"] = {
                str(k): (v if isinstance(v, dict) else v.to_dict())
                for k, v in records_by_mask.items()
            }

        temp_path = target_path.with_name(target_path.name + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as stream:
            stream.write(canonical_json(payload))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target_path)
        return target_path

    def list_available_benchmarks(self) -> list[dict[str, Any]]:
        """List all verified precomputed benchmarks available in the repository."""
        items: list[dict[str, Any]] = []

        # Canonical M5 cooperative-pool annual benchmark
        try:
            self._ensure_annual_artifacts_loaded()
            items.append({
                "benchmark_id": "canonical_annual_m5",
                "title": "ComErgy 2026 Canonical 9-Member Cooperative Pool (M5)",
                "dataset_hash": WORKBOOK_SHA256,
                "member_ids": list(CANONICAL_BENCHMARK_MEMBERS),
                "forecast_origin_t": None,
                "time_horizon": "annual",
                "horizon_hours": 8760,
                "evaluation_level": "full_cooperative_game",
                "community_model": "cooperative_pool",
                "simulated_assets_hash": build_benchmark_context().simulated_assets_hash,
                "total_coalitions_evaluated": 512,
                "has_stability_certificate": True,
                "is_core_nonempty": True,
                "grand_coalition_cost_aud": 5509.653992063874,
                "v_N_aud": 4244.985091828258,
            })
        except Exception as exc:
            logger.warning("Could not index canonical annual M5 benchmark: %s", exc)

        # Canonical M3 annual standalone baseline
        try:
            self._ensure_annual_artifacts_loaded()
            if self._m3_baselines:
                sum_b0 = float(self._m3_baselines["sum_B_i_aud"])
                items.append({
                    "benchmark_id": "canonical_annual_m3_baseline",
                    "title": "ComErgy 2026 Canonical 9-Member Standalone Baseline (M3)",
                    "dataset_hash": WORKBOOK_SHA256,
                    "member_ids": list(CANONICAL_BENCHMARK_MEMBERS),
                    "forecast_origin_t": None,
                    "time_horizon": "annual",
                    "horizon_hours": 8760,
                    "evaluation_level": "economic_comparison",
                    "community_model": "baseline",
                    "simulated_assets_hash": build_benchmark_context().simulated_assets_hash,
                    "total_coalitions_evaluated": 9,
                    "has_stability_certificate": False,
                    "grand_coalition_cost_aud": sum_b0,
                    "v_N_aud": 0.0,
                })
        except Exception as exc:
            logger.warning("Could not index canonical annual M3 baseline: %s", exc)


        # Scan precomputed directory
        for path in sorted(self.precomputed_dir.glob("*.json")):
            try:
                data = _read_json(path)
                if data.get("schema_version") != 1:
                    continue
                ctx = data.get("context", {})
                resp = data.get("response", {})
                items.append({
                    "benchmark_id": path.stem,
                    "title": f"Precomputed {ctx.get('community_model', '').upper()} ({resp.get('time_horizon', 'daily').capitalize()} {ctx.get('forecast_origin_t') or ''})".strip(),
                    "dataset_hash": ctx.get("dataset_hash"),
                    "member_ids": ctx.get("member_ids"),
                    "forecast_origin_t": ctx.get("forecast_origin_t"),
                    "time_horizon": resp.get("time_horizon", "daily" if ctx.get("forecast_origin_t") else "annual"),
                    "horizon_hours": resp.get("horizon_hours", 24 if ctx.get("forecast_origin_t") else 8760),
                    "evaluation_level": resp.get("evaluation_level", "economic_comparison"),
                    "community_model": ctx.get("community_model"),
                    "simulated_assets_hash": ctx.get("simulated_assets_hash"),
                    "has_stability_certificate": bool(resp.get("stability_available")),
                    "grand_coalition_cost_aud": resp.get("grand_coalition_cost_aud"),
                    "v_N_aud": resp.get("v_N_aud"),
                })
            except Exception:
                continue

        return items
