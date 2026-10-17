"""Exact coalition enumeration using an explicitly supplied evaluator."""

from contextlib import nullcontext
import math
from time import perf_counter

from .checkpoint import Checkpoint
from .coalitions import mask_to_members, members_to_mask, member_universe
from .provenance import fingerprint
from .results import CoalitionRecord


def game_context(evaluator, standalone, provenance=None):
    """Build the checkpoint identity from every result-changing input."""
    member_ids = member_universe(evaluator.member_ids)
    if set(standalone) != set(member_ids):
        raise ValueError("Standalone costs must cover the evaluator universe")
    return {
        "schema_version": 2,
        "provenance": dict(provenance or {}),
        "evaluator": dict(evaluator.cache_context()),
        "standalone": {
            str(member): float(standalone[member]) for member in member_ids
        },
    }


def _record_from_evaluation(mask, evaluation, standalone, key, member_ids):
    members = mask_to_members(mask, member_ids)
    evaluation.validate()
    if evaluation.members != members:
        raise ValueError("Solved coalition/member mapping mismatch")
    total = float(sum(standalone[member] for member in members))
    coalition_cost = float(evaluation.total_final_member_cost)
    source = (
        "baseline_singleton"
        if len(members) == 1
        else "baseline_coalition"
        if evaluation.community_model == "baseline"
        else "cooperative_pool"
    )
    diagnostics = dict(evaluation.diagnostics)
    diagnostics["optimal"] = True
    return CoalitionRecord(
        mask=mask,
        members=members,
        size=len(members),
        sum_standalone_cost_aud=total,
        coalition_cost_aud=coalition_cost,
        value_aud=total - coalition_cost,
        cost_source=source,
        solver=dict(evaluation.solver),
        physical_validation=diagnostics,
        provenance_sha256=key,
        community_model=evaluation.community_model,
        member_costs={
            int(member): float(value)
            for member, value in evaluation.member_costs.items()
        },
        ec_manager=dict(evaluation.ec_manager),
        pricing_provenance=dict(evaluation.pricing_provenance),
        forecast_provenance=dict(evaluation.forecast_provenance),
        evaluation_stage=evaluation.evaluation_stage,
        currency=evaluation.currency,
    )


def _empty_record(key, community_model):
    return CoalitionRecord(
        mask=0,
        members=(),
        size=0,
        sum_standalone_cost_aud=0.0,
        coalition_cost_aud=0.0,
        value_aud=0.0,
        cost_source="empty",
        solver={
            "name": "none",
            "status": "ok",
            "termination_condition": "empty_coalition",
        },
        physical_validation={"not_applicable": "empty coalition; no solve"},
        provenance_sha256=key,
        community_model=community_model,
        evaluation_stage="not_applicable",
    )


def validate_record(record, evaluator, standalone, key):
    record.validate(
        standalone,
        evaluator.cost_tolerance,
        member_ids=evaluator.member_ids,
    )
    if record.provenance_sha256 != key:
        raise ValueError("Coalition provenance mismatch")
    if record.mask == 0:
        expected_solver = {
            "name": "none",
            "status": "ok",
            "termination_condition": "empty_coalition",
        }
        if record.solver != expected_solver:
            raise ValueError("Invalid empty coalition metadata")


def enumerate_game(
    evaluator,
    provenance=None,
    *,
    checkpoint=None,
    resume=False,
    jobs=1,
    progress=None,
):
    """Evaluate all coalitions serially using an explicitly supplied backend.

    Parallel evaluation is not supported. The empty coalition never calls
    the evaluator and no private optimisation backend is imported.
    """
    member_ids = member_universe(evaluator.member_ids)
    if evaluator.community_model not in {"baseline", "cooperative_pool"}:
        raise ValueError("Unsupported community model")
    if jobs != 1:
        raise ValueError("Coalition enumeration currently requires jobs=1")

    standalone_evaluations = {
        member: evaluator.standalone_evaluation(member)
        for member in member_ids
    }
    for member, evaluation in standalone_evaluations.items():
        evaluation.validate()
        if evaluation.members != (member,) or evaluation.community_model != "baseline":
            raise ValueError("Standalone evaluation must use the requested member and baseline")
    standalone = {
        member: float(evaluation.total_final_member_cost)
        for member, evaluation in standalone_evaluations.items()
    }
    if any(not math.isfinite(value) for value in standalone.values()):
        raise ValueError("Invalid standalone baseline costs")

    context = game_context(evaluator, standalone, provenance)
    key = fingerprint(context)
    validate = lambda record: validate_record(
        record, evaluator, standalone, key
    )
    started = perf_counter()
    runtime = {
        "new_coalition_record_count": 0,
        "checkpoint_reused_count": 0,
        "processing_seconds_by_mask": {},
        "jobs": 1,
    }
    guard = (
        Checkpoint(checkpoint, context, resume=resume)
        if checkpoint
        else nullcontext(None)
    )
    with guard as cache:
        records = cache.load(validate) if cache else {}
        runtime["checkpoint_reused_count"] = len(records)

        def accept(record, elapsed=None):
            validate(record)
            records[record.mask] = record
            if cache:
                cache.save(record)
            if elapsed is not None:
                runtime["new_coalition_record_count"] += 1
                runtime["processing_seconds_by_mask"][str(record.mask)] = elapsed
            if progress:
                progress(
                    len(records),
                    2 ** len(member_ids),
                    record.mask,
                    record.cost_source,
                )

        if 0 not in records:
            accept(_empty_record(key, evaluator.community_model))

        for member, evaluation in standalone_evaluations.items():
            mask = members_to_mask((member,), member_ids)
            if mask not in records:
                started_solve = perf_counter()
                record = _record_from_evaluation(
                    mask, evaluation, standalone, key, member_ids
                )
                accept(record, perf_counter() - started_solve)

        for mask in range(1, 2 ** len(member_ids)):
            if mask in records or mask & (mask - 1) == 0:
                continue
            members = mask_to_members(mask, member_ids)
            started_solve = perf_counter()
            try:
                evaluation = evaluator.coalition_evaluation(members)
                if evaluation.community_model != evaluator.community_model:
                    raise ValueError("Coalition evaluator returned a different community model")
                record = _record_from_evaluation(
                    mask, evaluation, standalone, key, member_ids
                )
                accept(record, perf_counter() - started_solve)
            except Exception as exc:
                raise RuntimeError(
                    f"Coalition failed mask={mask}, members={members}: {exc}"
                ) from exc

        expected_masks = set(range(2 ** len(member_ids)))
        if set(records) != expected_masks:
            raise ValueError("Incomplete/duplicate coalition game")

    runtime.update(
        coalition_wall_seconds=perf_counter() - started,
        summed_new_processing_seconds=sum(
            runtime["processing_seconds_by_mask"].values()
        ),
        standalone_costs={str(k): v for k, v in standalone.items()},
    )
    return [records[mask] for mask in sorted(records)], runtime
