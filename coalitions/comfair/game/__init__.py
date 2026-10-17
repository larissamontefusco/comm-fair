"""Exact cooperative game and core/least-core certificate (M5)."""
from .coalitions import mask_to_members, members_to_mask, member_universe
from .evaluator import (
    CoalitionCostEvaluator,
    CoalitionEvaluation,
)
from .results import CoalitionRecord, CoreCertificate

from .benchmark_context import BenchmarkContext, build_benchmark_context
from .benchmark_results import (
    BenchmarkEvaluationResponse,
    BenchmarkResultType,
    BenchmarkStatus,
    PartitionBlockResult,
    StabilityStatus,
)
from .benchmark_evaluator import (
    evaluate_coalition_partitions,
    evaluate_nine_member_benchmark,
)
from .precomputed import PrecomputedBenchmarkStore

__all__ = [
    'mask_to_members', 'members_to_mask', 'member_universe',
    'CoalitionCostEvaluator', 'CoalitionEvaluation',
    'CoalitionRecord', 'CoreCertificate',
    'allocation_diagnostics', 'solve_least_core',
    'BenchmarkContext', 'build_benchmark_context',
    'BenchmarkEvaluationResponse', 'BenchmarkResultType', 'BenchmarkStatus',
    'PartitionBlockResult', 'StabilityStatus',
    'evaluate_coalition_partitions', 'evaluate_nine_member_benchmark',
    'PrecomputedBenchmarkStore',
    'BatchPrecomputeConfig', 'BatchPrecomputeRunner', 'run_batch_precompute',
]


def __getattr__(name: str):
    if name in ('allocation_diagnostics', 'solve_least_core'):
        from . import stability
        return getattr(stability, name)
    if name in ('BatchPrecomputeConfig', 'BatchPrecomputeRunner', 'run_batch_precompute'):
        from . import batch_precompute
        return getattr(batch_precompute, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
