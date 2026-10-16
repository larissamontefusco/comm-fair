"""Validation-only champion selection. This module has no dataset/artifact access."""
from dataclasses import dataclass
import math

MAE_TOLERANCE_KW = 1e-12
RUNTIME_TOLERANCE_SECONDS = 1e-6


@dataclass(frozen=True, slots=True)
class ValidationScore:
    model_id: str
    wape_macro: float
    mae_kw: float
    runtime_seconds: float
    complexity: int
    split: str = 'validation'
    operationally_eligible: bool = True


def select_champion(scores):
    """Anchor 1% band at the minimum WAPE (avoids non-transitive pairwise ties).

    MAE ties use absolute tolerance 1e-12 kW. Runtime ties use 1 microsecond;
    remaining ties prefer fewer fitted models then lexical model ID. No weighted
    objective. Typed input deliberately contains no test metric or data field.
    """
    if not scores or any(type(s) is not ValidationScore or s.split != 'validation' for s in scores):
        raise ValueError('Only typed validation scores are accepted')
    if len({s.model_id for s in scores}) != len(scores):
        raise ValueError('Duplicate model IDs')
    for s in scores:
        if any(not math.isfinite(x) or x < 0 for x in (s.wape_macro, s.mae_kw, s.runtime_seconds)):
            raise ValueError('Selection scores must be finite and nonnegative')
    eligible = [s for s in scores if s.operationally_eligible]
    if not eligible:
        raise ValueError('No operationally eligible candidates')
    best = min(s.wape_macro for s in eligible)
    band = [s for s in eligible if s.wape_macro <= best * 1.01]
    best_mae = min(s.mae_kw for s in band)
    mae_band = [s for s in band if s.mae_kw <= best_mae + MAE_TOLERANCE_KW]
    runtime_used = len(mae_band) > 1
    runtime_best = min(s.runtime_seconds for s in mae_band)
    finalists = [s for s in mae_band if s.runtime_seconds <= runtime_best + RUNTIME_TOLERANCE_SECONDS]
    selected = min(finalists, key=lambda s: (s.complexity, s.model_id))
    trace = {'selection_dataset': 'validation', 'primary': 'member_macro.wape',
             'minimum_wape': best, 'relative_wape_tolerance': .01,
             'mae_tolerance_kw': MAE_TOLERANCE_KW,
             'runtime_tolerance_seconds': RUNTIME_TOLERANCE_SECONDS,
             'tie_rule_applied': len(band) > 1, 'runtime_comparison_used': runtime_used,
             'complexity_comparison_used': len(finalists) > 1,
             'selected_model_id': selected.model_id,
             'scores': [{'model_id': s.model_id, 'wape_macro': s.wape_macro, 'mae_kw': s.mae_kw,
                        'relative_difference_from_best': (s.wape_macro-best)/best if best else (0. if s.wape_macro==0 else None),
                        'in_one_percent_band': s in band, 'in_mae_tie': s in mae_band,
                        'fitted_model_count': s.complexity,
                        'runtime_reference': f'f1.runtime.json#validation/{s.model_id}'}
                        for s in sorted(eligible, key=lambda s: (s.wape_macro, s.model_id))]}
    return selected.model_id, trace


def improvements(score, references):
    """Positive absolute/relative values mean a reduction in macro WAPE."""
    best = min(references, key=lambda name: (references[name], name))
    refs = dict(references, best_simple_baseline=references[best])
    return {'metric': 'member_macro.wape', 'best_simple_baseline_id': best,
            'comparisons': {name: {'baseline_wape': value, 'absolute_wape_reduction': value-score,
                           'relative_wape_improvement': (value-score)/value if value else None}
                            for name, value in refs.items()}}
