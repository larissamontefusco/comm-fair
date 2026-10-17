"""Evaluation engine for nine-member benchmarks and user-specified coalition partitions.

Provides:
1. Nine-member economic comparison (9 standalones + 1 grand coalition) with strict non-fabrication of stability certificates.
2. User-specified disjoint partition evaluation with precomputed cache reuse and additive cost aggregation.
3. Heterogeneous partitions with independently chosen governance models per block.
4. Cache-first and non-blocking default semantics.
5. Strict bounds preventing accidental exponential enumeration.
"""
import logging
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Union

from .benchmark_context import BenchmarkContext, CANONICAL_BENCHMARK_MEMBERS, build_benchmark_context
from .benchmark_results import (
    BenchmarkEvaluationResponse,
    BenchmarkResultType,
    BenchmarkStatus,
    PartitionBlockResult,
    StabilityStatus,
)
from .coalitions import members_to_mask
from .evaluator import CoalitionCostEvaluator, LegacyBilevelCoalitionEvaluator
from .precomputed import PrecomputedBenchmarkStore

logger = logging.getLogger(__name__)

MAX_INTERACTIVE_BLOCK_SIZE = 3


def _default_evaluator_factory(context: BenchmarkContext) -> CoalitionCostEvaluator:
    origin = context.forecast_origin_t if context.forecast_origin_t is not None else 7008
    return LegacyBilevelCoalitionEvaluator(
        forecast_origin_t=origin,
        community_model=context.community_model,
        solver_name=context.solver_name,
        member_ids=context.member_ids,
        optimizer_config={"simulated_assets_hash": context.simulated_assets_hash},
    )


def evaluate_nine_member_benchmark(
    context: BenchmarkContext,
    precomputed_store: Optional[PrecomputedBenchmarkStore] = None,
    evaluator_factory: Optional[Callable[[BenchmarkContext], CoalitionCostEvaluator]] = None,
    allow_calculation: bool = False,
) -> BenchmarkEvaluationResponse:
    """Evaluate 9-member community benchmark or economic comparison.

    Cache-first and non-blocking by default (allow_calculation=False).
    1. Checks precomputed cache first for exact context match.
    2. If cache hit, returns precomputed results immediately (full game if all 512 evaluated, or precomputed comparison).
    3. If cache miss and allow_calculation=False, returns 'unavailable' immediately without blocking.
    4. If cache miss and allow_calculation=True, evaluates ONLY 9 standalones + 1 grand coalition (10 solves).
    5. Strict Non-Fabrication: explicitly DOES NOT fabricate stability certificates when intermediate sub-coalitions are not evaluated.
    """
    store = precomputed_store or PrecomputedBenchmarkStore()

    # Step 1: Precomputed cache check (deduplicated)
    cached = store.lookup(context)
    if cached is not None:
        return cached

    # Step 2: Cache miss handling (non-blocking by default)
    if not allow_calculation:
        return BenchmarkEvaluationResponse(
            result_type=BenchmarkResultType.PARTIAL_OR_UNAVAILABLE.value,
            status=BenchmarkStatus.UNAVAILABLE.value,
            data_source="none",
            is_precomputed=False,
            community_model=context.community_model,
            member_ids=list(context.member_ids),
            forecast_origin_t=context.forecast_origin_t,
            grand_coalition_cost_aud=None,
            sum_standalone_cost_aud=None,
            v_N_aud=None,
            time_horizon=context.time_horizon,
            horizon_hours=context.horizon_hours,
            evaluation_level="economic_comparison",
            stability_certificate=None,
            stability_available=False,
            stability_status=StabilityStatus.NOT_EVALUATED.value,
            stability_explanation="Benchmark results not precomputed for this context and synchronous calculation is disabled by default to prevent blocking.",
            error={
                "code": "not_precomputed",
                "detail": (
                    "Requested benchmark scenario is not in the precomputed cache. "
                    "Interactive 9-member requests are non-blocking by default. "
                    "Run offline batch precomputation or enable explicit controlled calculation."
                ),
            },
            provenance={
                "dataset_hash": context.dataset_hash,
                "context_sha256": context.context_sha256,
            },
        )

    # Step 3: Controlled 10-solve economic comparison (9 standalones + 1 grand coalition)
    factory = evaluator_factory or _default_evaluator_factory
    try:
        evaluator = factory(context)
    except Exception as exc:
        logger.error("Failed to initialize evaluator for context %s: %s", context.context_sha256, exc)
        return BenchmarkEvaluationResponse(
            result_type=BenchmarkResultType.OPTIMIZATION_FAILURE.value,
            status=BenchmarkStatus.FAILED.value,
            data_source="calculated",
            is_precomputed=False,
            community_model=context.community_model,
            member_ids=list(context.member_ids),
            forecast_origin_t=context.forecast_origin_t,
            grand_coalition_cost_aud=None,
            sum_standalone_cost_aud=None,
            v_N_aud=None,
            time_horizon=context.time_horizon,
            horizon_hours=context.horizon_hours,
            evaluation_level="economic_comparison",
            stability_certificate=None,
            stability_available=False,
            stability_status=StabilityStatus.NOT_EVALUATED.value,
            stability_explanation="Evaluator initialization failed.",
            error={"code": "evaluator_init_failed", "detail": str(exc)},
            provenance={
                "dataset_hash": context.dataset_hash,
                "context_sha256": context.context_sha256,
            },
        )

    # Solve 9 standalones
    standalone_costs: dict[str, float] = {}
    try:
        for member in context.member_ids:
            ev = evaluator.standalone_evaluation(member)
            standalone_costs[str(member)] = float(ev.total_final_member_cost)
    except Exception as exc:
        return BenchmarkEvaluationResponse(
            result_type=BenchmarkResultType.OPTIMIZATION_FAILURE.value,
            status=BenchmarkStatus.FAILED.value,
            data_source="calculated",
            is_precomputed=False,
            community_model=context.community_model,
            member_ids=list(context.member_ids),
            forecast_origin_t=context.forecast_origin_t,
            grand_coalition_cost_aud=None,
            sum_standalone_cost_aud=None,
            v_N_aud=None,
            time_horizon=context.time_horizon,
            horizon_hours=context.horizon_hours,
            evaluation_level="economic_comparison",
            stability_certificate=None,
            stability_available=False,
            stability_status=StabilityStatus.NOT_EVALUATED.value,
            stability_explanation="Standalone outside option evaluation failed.",
            error={"code": "standalone_solve_failed", "detail": str(exc)},
            provenance={
                "dataset_hash": context.dataset_hash,
                "context_sha256": context.context_sha256,
            },
        )

    # Solve 1 grand coalition
    try:
        grand_eval = evaluator.coalition_evaluation(context.member_ids)
        grand_cost = float(grand_eval.total_final_member_cost)
        member_costs = {str(m): float(c) for m, c in grand_eval.member_costs.items()}
    except Exception as exc:
        return BenchmarkEvaluationResponse(
            result_type=BenchmarkResultType.OPTIMIZATION_FAILURE.value,
            status=BenchmarkStatus.FAILED.value,
            data_source="calculated",
            is_precomputed=False,
            community_model=context.community_model,
            member_ids=list(context.member_ids),
            forecast_origin_t=context.forecast_origin_t,
            grand_coalition_cost_aud=None,
            sum_standalone_cost_aud=sum(standalone_costs.values()),
            v_N_aud=None,
            time_horizon=context.time_horizon,
            horizon_hours=context.horizon_hours,
            evaluation_level="economic_comparison",
            standalone_costs_aud=standalone_costs,
            stability_certificate=None,
            stability_available=False,
            stability_status=StabilityStatus.NOT_EVALUATED.value,
            stability_explanation="Grand-coalition evaluation failed.",
            error={"code": "grand_coalition_solve_failed", "detail": str(exc)},
            provenance={
                "dataset_hash": context.dataset_hash,
                "context_sha256": context.context_sha256,
            },
        )

    sum_standalone = sum(standalone_costs.values())
    v_n = sum_standalone - grand_cost
    member_benefits = {
        str(m): standalone_costs[str(m)] - member_costs[str(m)]
        for m in context.member_ids
    }

    # Strict invariant: Sub-coalitions were NOT evaluated, so stability certificate is explicitly null
    response = BenchmarkEvaluationResponse(
        result_type=BenchmarkResultType.CALCULATED_ECONOMIC_COMPARISON.value,
        status=BenchmarkStatus.COMPLETED.value,
        data_source="calculated",
        is_precomputed=False,
        community_model=context.community_model,
        member_ids=list(context.member_ids),
        forecast_origin_t=context.forecast_origin_t,
        grand_coalition_cost_aud=grand_cost,
        sum_standalone_cost_aud=sum_standalone,
        v_N_aud=v_n,
        time_horizon=context.time_horizon,
        horizon_hours=context.horizon_hours,
        evaluation_level="economic_comparison",
        standalone_costs_aud=standalone_costs,
        member_costs_aud=member_costs,
        member_benefits_aud=member_benefits,
        stability_certificate=None,
        stability_available=False,
        stability_status=StabilityStatus.NOT_EVALUATED.value,
        stability_explanation=(
            "Exact least-core stability analysis requires full 512-coalition enumeration. "
            "This economic comparison evaluated only the 9 standalone outside options and the 9-member grand coalition; "
            "intermediate sub-coalitions were not evaluated."
        ),
        partition_results=None,
        provenance={
            "dataset_hash": context.dataset_hash,
            "context_sha256": context.context_sha256,
            "evaluation_stage": grand_eval.evaluation_stage,
            "solver": grand_eval.solver,
            "pricing_provenance": grand_eval.pricing_provenance,
            "forecast_provenance": grand_eval.forecast_provenance,
        },
        diagnostics={
            "evaluations_performed": 10,
            "standalone_count": 9,
            "grand_coalition_count": 1,
            "sub_coalitions_evaluated": 0,
        },
    )

    # Optionally persist calculated economic comparison to precomputed store
    try:
        store.save_precomputed(context, response)
    except Exception as exc:
        logger.debug("Could not cache calculated benchmark response: %s", exc)

    return response


def evaluate_coalition_partitions(
    partitions: Sequence[Any],
    context: BenchmarkContext,
    precomputed_store: Optional[PrecomputedBenchmarkStore] = None,
    evaluator_factory: Optional[Callable[[BenchmarkContext], CoalitionCostEvaluator]] = None,
    allow_calculation: bool = False,
    max_interactive_block_size: int = MAX_INTERACTIVE_BLOCK_SIZE,
) -> BenchmarkEvaluationResponse:
    """Evaluate a user-specified disjoint partition of the community into coalition blocks.

    Supports heterogeneous partitions where each block may specify an independent
    governance model (e.g. Block 1 under C2, Block 2 under C0).

    Validates:
    - Non-empty blocks
    - Pairwise disjointness (no duplicate members)
    - Full coverage of context members

    For each block:
    - Reuses precomputed coalition results if available for (block_members, block_model)
    - Calculates missing blocks only if allow_calculation=True and size <= max_interactive_block_size
    - Aggregates costs and benefits additively without double-counting
    """
    store = precomputed_store or PrecomputedBenchmarkStore()

    if not partitions:
        raise ValueError("Partitions list cannot be empty")

    seen_members: set[int] = set()
    cleaned_blocks: list[Tuple[Tuple[int, ...], str]] = []

    for idx, item in enumerate(partitions):
        block_model = context.community_model
        if isinstance(item, Mapping):
            raw_members = item.get("members", [])
            block_model = item.get("community_model") or context.community_model
        elif hasattr(item, "members"):
            raw_members = getattr(item, "members")
            block_model = getattr(item, "community_model", None) or context.community_model
        else:
            raw_members = item

        if not raw_members:
            raise ValueError(f"Partition block at index {idx} is empty")

        try:
            b_tuple = tuple(sorted(int(m) for m in raw_members))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Partition block {idx} contains non-integer member IDs") from exc

        if any(m not in context.member_ids for m in b_tuple):
            raise ValueError(f"Partition block {idx} contains members outside community {list(context.member_ids)}")

        overlap = seen_members.intersection(b_tuple)
        if overlap:
            raise ValueError(
                f"Partition blocks must be mutually disjoint; members {sorted(overlap)} appear in multiple blocks"
            )
        seen_members.update(b_tuple)
        cleaned_blocks.append((b_tuple, block_model))

    if seen_members != set(context.member_ids):
        missing = sorted(set(context.member_ids) - seen_members)
        raise ValueError(f"Partition must cover all members {list(context.member_ids)}; missing {missing}")

    # Step 2: Evaluate each block under its designated governance model
    block_results: list[PartitionBlockResult] = []
    all_precomputed = True
    evaluators_by_model: dict[str, CoalitionCostEvaluator] = {}

    for idx, (block_members, b_model) in enumerate(cleaned_blocks):
        size = len(block_members)
        mask = members_to_mask(block_members, CANONICAL_BENCHMARK_MEMBERS)

        block_context = build_benchmark_context(
            member_ids=CANONICAL_BENCHMARK_MEMBERS,
            community_model=b_model,
            forecast_origin_t=context.forecast_origin_t,
            simulated_assets=context.simulated_assets_hash,
            solver_name=context.solver_name,
            dataset_hash=context.dataset_hash,
        )

        # Check precomputed cache first
        cached = store.lookup_coalition_mask(block_context, mask, block_members)
        if cached is not None:
            block_results.append(
                PartitionBlockResult(
                    block_index=idx,
                    members=list(block_members),
                    size=size,
                    mask=mask,
                    cost_aud=cached["coalition_cost_aud"],
                    standalone_cost_aud=cached["sum_standalone_cost_aud"],
                    value_aud=cached["value_aud"],
                    is_precomputed=True,
                    community_model=b_model,
                    diagnostics=cached.get("physical_validation", {}),
                )
            )
            continue

        # Cache miss
        all_precomputed = False

        if size > max_interactive_block_size:
            return BenchmarkEvaluationResponse(
                result_type=BenchmarkResultType.PARTIAL_OR_UNAVAILABLE.value,
                status=BenchmarkStatus.UNAVAILABLE.value,
                data_source="partial",
                is_precomputed=False,
                community_model=context.community_model,
                member_ids=list(context.member_ids),
                forecast_origin_t=context.forecast_origin_t,
                grand_coalition_cost_aud=None,
                sum_standalone_cost_aud=None,
                v_N_aud=None,
                time_horizon=context.time_horizon,
                horizon_hours=context.horizon_hours,
                evaluation_level="partition_comparison",
                stability_certificate=None,
                stability_available=False,
                stability_status=StabilityStatus.NOT_EVALUATED.value,
                stability_explanation=f"Block {list(block_members)} (model {b_model}) has size {size} > {max_interactive_block_size} and is not precomputed.",
                error={
                    "code": "block_size_exceeded",
                    "detail": (
                        f"Partition block {list(block_members)} under model {b_model} has size {size} > {max_interactive_block_size} "
                        "and is not in the precomputed cache. Large blocks cannot be evaluated interactively; "
                        "run offline batch computation to precompute this structure."
                    ),
                    "block_members": list(block_members),
                    "block_size": size,
                    "community_model": b_model,
                },
                provenance={
                    "dataset_hash": context.dataset_hash,
                    "context_sha256": context.context_sha256,
                },
            )

        if not allow_calculation:
            return BenchmarkEvaluationResponse(
                result_type=BenchmarkResultType.PARTIAL_OR_UNAVAILABLE.value,
                status=BenchmarkStatus.UNAVAILABLE.value,
                data_source="partial",
                is_precomputed=False,
                community_model=context.community_model,
                member_ids=list(context.member_ids),
                forecast_origin_t=context.forecast_origin_t,
                grand_coalition_cost_aud=None,
                sum_standalone_cost_aud=None,
                v_N_aud=None,
                time_horizon=context.time_horizon,
                horizon_hours=context.horizon_hours,
                evaluation_level="partition_comparison",
                stability_certificate=None,
                stability_available=False,
                stability_status=StabilityStatus.NOT_EVALUATED.value,
                stability_explanation="Block is not precomputed and calculation is disabled to prevent blocking.",
                error={
                    "code": "not_precomputed",
                    "detail": f"Partition block {list(block_members)} under model {b_model} is not precomputed and interactive calculation is disabled.",
                },
                provenance={
                    "dataset_hash": context.dataset_hash,
                    "context_sha256": context.context_sha256,
                },
            )

        # Compute block live if permitted
        if b_model not in evaluators_by_model:
            factory = evaluator_factory or _default_evaluator_factory
            evaluators_by_model[b_model] = factory(block_context)
        evaluator = evaluators_by_model[b_model]

        # Standalone costs for block
        block_standalone: dict[str, float] = {}
        for m in block_members:
            cached_single = store.lookup_coalition_mask(
                block_context, members_to_mask((m,), CANONICAL_BENCHMARK_MEMBERS), (m,)
            )
            if cached_single is not None:
                block_standalone[str(m)] = cached_single["coalition_cost_aud"]
            else:
                ev_single = evaluator.standalone_evaluation(m)
                block_standalone[str(m)] = float(ev_single.total_final_member_cost)

        sum_block_standalone = sum(block_standalone.values())

        if size == 1:
            m = block_members[0]
            cost_aud = block_standalone[str(m)]
            val_aud = 0.0
            member_costs_aud = {str(m): cost_aud}
            member_benefits_aud = {str(m): 0.0}
            diag = {"type": "singleton", "model": b_model}
        else:
            ev_coal = evaluator.coalition_evaluation(block_members)
            cost_aud = float(ev_coal.total_final_member_cost)
            val_aud = sum_block_standalone - cost_aud
            member_costs_aud = {str(m): float(c) for m, c in ev_coal.member_costs.items()}
            member_benefits_aud = {
                str(m): block_standalone[str(m)] - member_costs_aud[str(m)]
                for m in block_members
            }
            diag = dict(ev_coal.diagnostics) | {"model": b_model}

        block_results.append(
            PartitionBlockResult(
                block_index=idx,
                members=list(block_members),
                size=size,
                mask=mask,
                cost_aud=cost_aud,
                standalone_cost_aud=sum_block_standalone,
                value_aud=val_aud,
                is_precomputed=False,
                community_model=b_model,
                member_costs_aud=member_costs_aud,
                member_benefits_aud=member_benefits_aud,
                diagnostics=diag,
            )
        )

    # Step 3: Additive cost aggregation
    total_partition_cost = sum(b.cost_aud for b in block_results)
    total_standalone_cost = sum(b.standalone_cost_aud for b in block_results)
    total_surplus = sum(b.value_aud for b in block_results)

    aggregated_standalone: dict[str, float] = {}
    aggregated_member_costs: dict[str, float] = {}
    aggregated_member_benefits: dict[str, float] = {}
    for b in block_results:
        for m, c in b.member_costs_aud.items():
            aggregated_member_costs[m] = c
        for m, ben in b.member_benefits_aud.items():
            aggregated_member_benefits[m] = ben

    res_type = (
        BenchmarkResultType.PRECOMPUTED_ECONOMIC_COMPARISON.value
        if all_precomputed
        else BenchmarkResultType.CALCULATED_ECONOMIC_COMPARISON.value
    )

    return BenchmarkEvaluationResponse(
        result_type=res_type,
        status=BenchmarkStatus.COMPLETED.value,
        data_source="precomputed" if all_precomputed else "calculated",
        is_precomputed=all_precomputed,
        community_model=context.community_model,
        member_ids=list(context.member_ids),
        forecast_origin_t=context.forecast_origin_t,
        grand_coalition_cost_aud=total_partition_cost,
        sum_standalone_cost_aud=total_standalone_cost,
        v_N_aud=total_surplus,
        time_horizon=context.time_horizon,
        horizon_hours=context.horizon_hours,
        evaluation_level="partition_comparison",
        standalone_costs_aud=aggregated_standalone,
        member_costs_aud=aggregated_member_costs,
        member_benefits_aud=aggregated_member_benefits,
        stability_certificate=None,
        stability_available=False,
        stability_status=StabilityStatus.NOT_EVALUATED.value,
        stability_explanation=(
            "Partition evaluation measures economic outcomes of specified disjoint sub-coalition structures. "
            "Stability certificates (core / least-core) apply only to cooperative grand-coalition games."
        ),
        partition_results=[b.to_dict() for b in block_results],
        provenance={
            "dataset_hash": context.dataset_hash,
            "context_sha256": context.context_sha256,
            "partition_count": len(block_results),
            "all_blocks_precomputed": all_precomputed,
            "block_governance_models": {str(b.block_index): b.community_model for b in block_results},
        },
        diagnostics={
            "block_count": len(block_results),
            "block_sizes": [b.size for b in block_results],
            "total_surplus_aud": total_surplus,
        },
    )
