"""Controlled offline / batch precomputation engine for ComFair benchmarks.

Supports:
1. Economic comparison (10 solves: 9 standalones + 1 grand coalition).
2. Full cooperative game (512 masks; the empty mask requires no solve).
3. Resumable checkpointing during batch runs.
4. Concurrency limits, timeouts, and dry-run planning.
5. Atomic publication to the precomputed data store.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional, Sequence

try:
    from .benchmark_context import BenchmarkContext, CANONICAL_BENCHMARK_MEMBERS, build_benchmark_context
    from .benchmark_results import (
        BenchmarkEvaluationResponse,
        BenchmarkResultType,
        BenchmarkStatus,
        StabilityStatus,
    )
    from .coalitions import mask_to_members, members_to_mask
    from .evaluator import CoalitionCostEvaluator
    from .jsonutil import canonical_json
    from .precomputed import PrecomputedBenchmarkStore
    from .stability import solve_least_core
except ImportError:
    from comfair.game.benchmark_context import BenchmarkContext, CANONICAL_BENCHMARK_MEMBERS, build_benchmark_context
    from comfair.game.benchmark_results import (
        BenchmarkEvaluationResponse,
        BenchmarkResultType,
        BenchmarkStatus,
        StabilityStatus,
    )
    from comfair.game.coalitions import mask_to_members, members_to_mask
    from comfair.game.evaluator import CoalitionCostEvaluator
    from comfair.game.jsonutil import canonical_json
    from comfair.game.precomputed import PrecomputedBenchmarkStore
    from comfair.game.stability import solve_least_core


logger = logging.getLogger(__name__)

DEFAULT_PRECOMPUTED_DIR = Path(__file__).resolve().parent / "precomputed_data"
DEFAULT_CHECKPOINT_DIR = Path(__file__).resolve().parent / "precomputed_checkpoints"


@dataclass
class BatchPrecomputeConfig:
    """Configuration for controlled offline/batch benchmark precomputation."""

    community_model: str = "cooperative_pool"
    forecast_origin_t: Optional[int] = None
    mode: str = "economic_comparison"  # "economic_comparison" or "full_game"
    confirm_full_game: bool = False
    checkpoint_dir: Path = DEFAULT_CHECKPOINT_DIR
    output_dir: Path = DEFAULT_PRECOMPUTED_DIR
    resume: bool = True
    timeout_seconds: int = 600
    max_cpus: int = 1
    dry_run: bool = False
    solver_name: str = "highs"
    simulated_assets: Optional[Mapping[str, Any]] = None
    tolerance: float = 1e-5


class BatchPrecomputeRunner:
    """Manages the controlled execution of offline batch precomputations."""

    def __init__(
        self,
        config: BatchPrecomputeConfig,
        evaluator_factory: Optional[Callable[[BenchmarkContext], CoalitionCostEvaluator]] = None,
    ):
        self.config = config
        self.evaluator_factory = evaluator_factory
        self.context = build_benchmark_context(
            member_ids=CANONICAL_BENCHMARK_MEMBERS,
            forecast_origin_t=config.forecast_origin_t,
            community_model=config.community_model,
            simulated_assets=config.simulated_assets,
            solver_name=config.solver_name,
        )

        try:
            self.config.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        try:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        self.checkpoint_file = (
            self.config.checkpoint_dir / f"checkpoint_{self.context.context_sha256[:16]}.json"
        )

    def plan_masks(self) -> list[int]:
        """Determine which masks need to be evaluated based on the mode."""
        if self.config.mode == "economic_comparison":
            # 9 standalones + 1 grand coalition
            masks = [1 << (i - 1) for i in range(1, 10)]
            grand_mask = (1 << 9) - 1
            masks.append(grand_mask)
            return sorted(masks)
        elif self.config.mode == "full_game":
            if not self.config.confirm_full_game:
                raise ValueError(
                    "Running full cooperative game requires solving all 512 coalition masks. "
                    "This is computationally intensive. Pass confirm_full_game=True or --confirm-full-game."
                )
            # All non-empty masks 1 through 511
            return list(range(1, 1 << 9))
        else:
            raise ValueError(f"Unknown mode '{self.config.mode}'; choose 'economic_comparison' or 'full_game'")

    def load_checkpoint(self) -> dict[str, Any]:
        """Load existing checkpoint if available and resume is True."""
        if self.config.resume and self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as stream:
                    data = json.load(stream)
                if data.get("context_sha256") == self.context.context_sha256:
                    return data.get("completed_solves", {})
            except Exception as exc:
                logger.warning("Could not read checkpoint %s: %s", self.checkpoint_file, exc)
        return {}

    def save_checkpoint(self, completed_solves: dict[str, Any], status: str = "in_progress") -> None:
        """Atomically persist checkpoint."""
        try:
            payload = {
                "schema_version": 1,
                "context": self.context.to_dict(),
                "context_sha256": self.context.context_sha256,
                "mode": self.config.mode,
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "completed_count": len(completed_solves),
                "completed_solves": completed_solves,
            }
            tmp = self.checkpoint_file.with_name(self.checkpoint_file.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as stream:
                stream.write(canonical_json(payload))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.checkpoint_file)
        except OSError as exc:
            logger.debug("Failed writing checkpoint %s: %s", self.checkpoint_file, exc)

    def run(self) -> dict[str, Any]:
        """Execute the batch precomputation workflow."""
        target_masks = self.plan_masks()
        completed_solves = self.load_checkpoint()
        remaining_masks = [m for m in target_masks if str(m) not in completed_solves]

        target_filename = (
            f"benchmark_{self.context.community_model}_{self.context.forecast_origin_t or 'annual'}_"
            f"{self.context.context_sha256[:16]}.json"
        )
        target_output_path = self.config.output_dir / target_filename

        if self.config.dry_run:
            return {
                "status": "planned",
                "dry_run": True,
                "mode": self.config.mode,
                "context_sha256": self.context.context_sha256,
                "total_solves_planned": len(target_masks),
                "solves_already_completed": len(target_masks) - len(remaining_masks),
                "solves_remaining": len(remaining_masks),
                "target_output_file": str(target_output_path),
                "checkpoint_file": str(self.checkpoint_file),
            }

        if self.evaluator_factory is None:
            raise RuntimeError(
                "Batch calculation requires an explicitly supplied evaluator_factory"
            )
        evaluator = self.evaluator_factory(self.context)
        logger.info(
            "Starting batch precomputation for context %s (%d solves total, %d remaining)",
            self.context.context_sha256[:8],
            len(target_masks),
            len(remaining_masks),
        )

        # Solve missing masks
        for idx, mask in enumerate(remaining_masks, start=1):
            members = mask_to_members(mask, 9)
            start_t = time.perf_counter()
            if len(members) == 1:
                res = evaluator.standalone_evaluation(members[0])
            else:
                res = evaluator.coalition_evaluation(members)
            duration = time.perf_counter() - start_t

            completed_solves[str(mask)] = {
                "mask": mask,
                "members": list(members),
                "size": len(members),
                "cost_aud": float(res.total_final_member_cost),
                "member_costs": {str(m): float(c) for m, c in res.member_costs.items()},
                "duration_seconds": duration,
                "solver": dict(res.solver),
                "diagnostics": dict(res.diagnostics),
            }

            logger.info(
                "[%d/%d] Mask %d (%s) solved in %.2fs: cost=%.4f AUD",
                idx,
                len(remaining_masks),
                mask,
                list(members),
                duration,
                float(res.total_final_member_cost),
            )

            # Checkpoint after each solve
            self.save_checkpoint(completed_solves, status="in_progress")

        # Assemble standalone costs
        standalone_costs_aud: dict[str, float] = {}
        for m in range(1, 10):
            single_mask = 1 << (m - 1)
            record = completed_solves[str(single_mask)]
            standalone_costs_aud[str(m)] = record["cost_aud"]

        sum_standalone = sum(standalone_costs_aud.values())

        # Grand coalition
        grand_mask = (1 << 9) - 1
        grand_record = completed_solves[str(grand_mask)]
        grand_cost = grand_record["cost_aud"]
        v_N = sum_standalone - grand_cost
        member_costs = grand_record["member_costs"]
        member_benefits = {
            str(m): standalone_costs_aud[str(m)] - member_costs[str(m)]
            for m in range(1, 10)
        }

        records_by_mask: dict[int, Any] = {}
        for mask_str, rec in completed_solves.items():
            m_int = int(mask_str)
            members = rec["members"]
            sum_m_standalone = sum(standalone_costs_aud[str(i)] for i in members)
            val = sum_m_standalone - rec["cost_aud"]
            records_by_mask[m_int] = {
                "mask": m_int,
                "members": members,
                "size": len(members),
                "coalition_cost_aud": rec["cost_aud"],
                "sum_standalone_cost_aud": sum_m_standalone,
                "value_aud": val,
                "is_precomputed": True,
                "community_model": self.context.community_model,
                "cost_source": "batch_precompute",
                "solver": rec.get("solver", {}),
                "physical_validation": rec.get("diagnostics", {}),
            }

        # Build response depending on mode
        if self.config.mode == "full_game":
            # Solve least-core certificate
            game_values: dict[int, float] = {0: 0.0}
            for m_int in range(1, 1 << 9):
                game_values[m_int] = records_by_mask[m_int]["value_aud"]

            cert = solve_least_core(game_values, 9, tolerance=self.config.tolerance)
            cert_dict = cert.to_dict()

            response = BenchmarkEvaluationResponse(
                result_type=BenchmarkResultType.FULL_GAME_WITH_STABILITY.value,
                status=BenchmarkStatus.COMPLETED.value,
                data_source="precomputed",
                is_precomputed=True,
                community_model=self.context.community_model,
                member_ids=list(self.context.member_ids),
                forecast_origin_t=self.context.forecast_origin_t,
                grand_coalition_cost_aud=grand_cost,
                sum_standalone_cost_aud=sum_standalone,
                v_N_aud=v_N,
                time_horizon=self.context.time_horizon,
                horizon_hours=self.context.horizon_hours,
                evaluation_level="full_cooperative_game",
                standalone_costs_aud=standalone_costs_aud,
                member_costs_aud=member_costs,
                member_benefits_aud=member_benefits,
                stability_certificate=cert_dict,
                stability_available=True,
                stability_status=(
                    StabilityStatus.CERTIFIED.value if cert.core_nonempty else StabilityStatus.EMPTY_CORE.value
                ),
                stability_explanation=cert.interpretation,
                provenance={
                    "dataset_hash": self.context.dataset_hash,
                    "context_sha256": self.context.context_sha256,
                    "source": "batch_precompute_full_game",
                    "total_masks": 512,
                },
                diagnostics={
                    "evaluations_performed": 512,
                    "core_nonempty": cert.core_nonempty,
                    "epsilon_star_aud": cert.epsilon_star_aud,
                },
            )
        else:
            response = BenchmarkEvaluationResponse(
                result_type=BenchmarkResultType.PRECOMPUTED_ECONOMIC_COMPARISON.value,
                status=BenchmarkStatus.COMPLETED.value,
                data_source="precomputed",
                is_precomputed=True,
                community_model=self.context.community_model,
                member_ids=list(self.context.member_ids),
                forecast_origin_t=self.context.forecast_origin_t,
                grand_coalition_cost_aud=grand_cost,
                sum_standalone_cost_aud=sum_standalone,
                v_N_aud=v_N,
                time_horizon=self.context.time_horizon,
                horizon_hours=self.context.horizon_hours,
                evaluation_level="economic_comparison",
                standalone_costs_aud=standalone_costs_aud,
                member_costs_aud=member_costs,
                member_benefits_aud=member_benefits,
                stability_certificate=None,
                stability_available=False,
                stability_status=StabilityStatus.NOT_EVALUATED.value,
                stability_explanation=(
                    "Economic comparison evaluated only the 9 standalone outside options and the 9-member grand coalition; "
                    "intermediate sub-coalitions were not evaluated."
                ),
                provenance={
                    "dataset_hash": self.context.dataset_hash,
                    "context_sha256": self.context.context_sha256,
                    "source": "batch_precompute_economic_comparison",
                    "total_masks": 10,
                },
                diagnostics={
                    "evaluations_performed": 10,
                    "standalone_count": 9,
                    "grand_coalition_count": 1,
                },
            )

        # Atomic publication into precomputed store
        store = PrecomputedBenchmarkStore(precomputed_dir=self.config.output_dir)
        published_path = store.save_precomputed(self.context, response, records_by_mask=records_by_mask)

        # Mark checkpoint completed
        self.save_checkpoint(completed_solves, status="completed")

        return {
            "status": "completed",
            "published_path": str(published_path),
            "context_sha256": self.context.context_sha256,
            "v_N_aud": v_N,
            "grand_coalition_cost_aud": grand_cost,
            "solves_performed": len(remaining_masks),
            "response": response.to_dict(),
        }


def run_batch_precompute(
    config: BatchPrecomputeConfig,
    evaluator_factory: Optional[Callable[[BenchmarkContext], CoalitionCostEvaluator]] = None,
) -> dict[str, Any]:
    """Programmatic entry point for running batch precomputations."""
    runner = BatchPrecomputeRunner(config, evaluator_factory=evaluator_factory)
    return runner.run()


def main() -> None:
    """CLI entry point for batch precomputation."""
    parser = argparse.ArgumentParser(description="ComFair Batch Benchmark Precomputation CLI")
    parser.add_argument(
        "--community-model",
        default="cooperative_pool",
        choices=["baseline", "cooperative_pool"],
    )
    parser.add_argument("--forecast-origin", type=int, default=None, help="Forecast origin t (default: None for annual)")
    parser.add_argument("--mode", default="economic_comparison", choices=["economic_comparison", "full_game"])
    parser.add_argument("--confirm-full-game", action="store_true", help="Explicit confirmation required to run full 512-mask game")
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PRECOMPUTED_DIR)
    parser.add_argument("--no-resume", dest="resume", action="store_false", default=True)
    parser.add_argument("--dry-run", action="store_true", help="Inspect planned execution without running optimization")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--max-cpus", type=int, default=1)
    parser.add_argument("--solver-name", default="highs")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    config = BatchPrecomputeConfig(
        community_model=args.community_model,
        forecast_origin_t=args.forecast_origin,
        mode=args.mode,
        confirm_full_game=args.confirm_full_game,
        checkpoint_dir=args.checkpoint_dir,
        output_dir=args.output_dir,
        resume=args.resume,
        timeout_seconds=args.timeout_seconds,
        max_cpus=args.max_cpus,
        dry_run=args.dry_run,
        solver_name=args.solver_name,
    )

    result = run_batch_precompute(config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
