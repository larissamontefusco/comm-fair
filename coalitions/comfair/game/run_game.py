"""Coalition game backed by the forecast/pricing/legacy bi-level pipeline."""

import argparse
from collections import Counter
from pathlib import Path
from time import perf_counter

from comfair.physical.config import canonical_json
from .checkpoint import atomic_json
from .engine import enumerate_game
from .evaluator import LegacyBilevelCoalitionEvaluator
from .provenance import digest
from .stability import solve_least_core


def build_artifacts(evaluator, records):
    """Build game/core artifacts without changing the core mathematics."""
    member_ids = evaluator.member_ids
    n = len(member_ids)
    if len(records) != 2 ** n or [record.mask for record in records] != list(range(2 ** n)):
        raise ValueError("Expected complete canonical coalition order")
    standalone = {
        record.members[0]: record.coalition_cost_aud
        for record in records
        if record.size == 1
    }
    for record in records:
        record.validate(
            standalone,
            evaluator.cost_tolerance,
            member_ids=member_ids,
        )

    import math
    values = {record.mask: record.value_aud for record in records}
    certificate, core_seconds = solve_least_core(
        values, n, evaluator.cost_tolerance
    )
    # When infeasible_hard_no_harm the allocation values are NaN; represent as None/null.
    def _clean_alloc(v):
        return None if isinstance(v, float) and math.isnan(v) else v
    mapped_allocation = {
        str(member_ids[position - 1]): _clean_alloc(value)
        for position, value in certificate.least_core_allocation_u_aud.items()
    }
    counts = Counter(record.cost_source for record in records)
    shared = {
        "schema_version": 2,
        "milestone": "M5-bilevel",
        "currency": records[-1].currency,
        "member_ids": list(member_ids),
        "community_model": evaluator.community_model,
        "evaluator_context": dict(evaluator.cache_context()),
        "core_tolerance": evaluator.cost_tolerance,
    }
    coalitions = shared | {
        "standalone_c0_cost": {
            str(member): cost for member, cost in standalone.items()
        },
        "records": [record.to_dict() for record in records],
        "diagnostics": {
            "coalition_count": len(records),
            "empty_count": counts["empty"],
            "standalone_c0_count": counts["c0_singleton"],
            "bilevel_household2_count": counts["bilevel_household2"],
            "c0_coalition_count": counts["c0_coalition"],
        },
    }
    core = shared | {
        "v_N": values[2 ** n - 1],
        "certificate": certificate.to_dict()
        | {"least_core_allocation_by_member": mapped_allocation},
    }
    return coalitions, core, core_seconds



def run_game(
    output_dir,
    checkpoint,
    *,
    evaluator=None,
    forecast_origin_t=None,
    community_model="c2",
    solver_name="scip",
    member_ids=(1, 2, 3, 4, 5, 6, 7, 8, 9),
    resume=False,
    jobs=1,
    simulated_data_scenario=None,
    simulated_assets=None,
):
    started = perf_counter()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_names = ("m5_coalitions.json", "m5_core.json")
    if any((output_dir / name).exists() for name in canonical_names):
        raise ValueError(
            "Use a fresh output directory; existing canonical M5 results are preserved"
        )
    if evaluator is None:
        if forecast_origin_t is None:
            raise ValueError("forecast_origin_t is required")
        evaluator = LegacyBilevelCoalitionEvaluator(
            forecast_origin_t=forecast_origin_t,
            community_model=community_model,
            solver_name=solver_name,
            member_ids=member_ids,
            optimizer_config={"simulated_data_scenario": simulated_data_scenario, "simulated_assets": simulated_assets},
        )
    try:
        def progress(done, total, mask, source):
            print(f"{done}/{total} mask={mask} source={source}", flush=True)

        records, runtime = enumerate_game(
            evaluator,
            {"runner": "comfair.game.run_game", "schema_version": 2},
            checkpoint=checkpoint,
            resume=resume,
            jobs=jobs,
            progress=progress,
        )
        coalitions, core, core_seconds = build_artifacts(evaluator, records)
        atomic_json(output_dir / "m5_coalitions.json", coalitions)
        atomic_json(output_dir / "m5_core.json", core)
        runtime.update(
            least_core_seconds=core_seconds,
            total_seconds=perf_counter() - started,
            artifact_hashes={
                name: digest(output_dir / name) for name in canonical_names
            },
            checkpoint_directory=str(checkpoint),
        )
        atomic_json(output_dir / "m5.runtime.json", runtime)
        print(
            canonical_json(
                {
                    "status": "DONE",
                    "community_model": evaluator.community_model,
                    "certificate": core["certificate"],
                    "runtime": {
                        key: value
                        for key, value in runtime.items()
                        if key != "solve_seconds_by_mask"
                    },
                }
            )
        )
        return coalitions, core, runtime
    except Exception as exc:
        atomic_json(
            output_dir / "m5_failure.json",
            {
                "status": "BLOCKED",
                "exception_type": type(exc).__name__,
                "reason": str(exc),
                "checkpoint_directory": str(checkpoint),
            },
        )
        raise


def _members(value):
    try:
        return tuple(sorted(int(item) for item in value.split(",") if item))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "members must be comma-separated integer owner IDs"
        ) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--forecast-origin", type=int, required=True)
    parser.add_argument(
        "--community-model",
        choices=("c0", "c2", "c3", "c4", "c5"),
        default="c2",
    )
    parser.add_argument("--solver", default="scip")
    parser.add_argument("--members", type=_members, default=tuple(range(1, 10)))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--simulated-data-scenario", type=str, default=None)
    args = parser.parse_args()
    run_game(
        args.output_dir,
        args.checkpoint,
        forecast_origin_t=args.forecast_origin,
        community_model=args.community_model,
        solver_name=args.solver,
        member_ids=args.members,
        resume=args.resume,
        jobs=args.jobs,
        simulated_data_scenario=args.simulated_data_scenario,
    )
