#!/usr/bin/env python3
"""Read a baseline or cooperative-pool coalition from published artifacts."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comfair.game import PrecomputedBenchmarkStore, build_benchmark_context
from comfair.game.benchmark_context import CANONICAL_BENCHMARK_MEMBERS
from comfair.game.coalitions import members_to_mask


def _members(value: str) -> tuple[int, ...]:
    try:
        members = tuple(sorted(int(item.strip()) for item in value.split(",")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "members must be comma-separated integers"
        ) from exc
    if not members or len(set(members)) != len(members):
        raise argparse.ArgumentTypeError("members must be non-empty and unique")
    if any(member not in CANONICAL_BENCHMARK_MEMBERS for member in members):
        raise argparse.ArgumentTypeError("members must be between 1 and 9")
    return members


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members", required=True, type=_members)
    parser.add_argument(
        "--model",
        choices=("baseline", "cooperative_pool"),
        default="cooperative_pool",
    )
    args = parser.parse_args()

    mask = members_to_mask(args.members, CANONICAL_BENCHMARK_MEMBERS)
    context = build_benchmark_context(
        community_model=args.model,
        solver_name="highs",
    )
    result = PrecomputedBenchmarkStore().lookup_coalition_mask(
        context,
        mask,
        args.members,
    )
    if result is None:
        raise SystemExit("Coalition is not available in the precomputed store")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
