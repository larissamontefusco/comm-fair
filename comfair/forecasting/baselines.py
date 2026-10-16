"""Only F0 persistence and seasonal naive baselines; no fitting/selection."""
import numpy as np

from .schemas import ForecastResult, Prediction, MEMBERS, TARGETS

MODELS = ('persistence', 'naive_24', 'naive_168')


def clip_predictions(raw):
    raw = np.asarray(raw, dtype=float)
    if not np.isfinite(raw).all():
        raise ValueError('Nonfinite predictions cannot be clipped to valid forecasts')
    negative = raw < 0
    return np.maximum(raw, 0), {'clipping_count': int(negative.sum()),
                              'clipping_magnitude_kw_sum': float(-raw[negative].sum())}


def forecast(history, *, target, model_id, members=MEMBERS, zero_pv_members=(), provenance=None):
    history.validate()
    if target not in TARGETS or model_id not in MODELS:
        raise ValueError('Invalid F0 target/model')
    if (not members or any(type(i) is not int or i not in MEMBERS for i in members)
            or tuple(sorted(set(members))) != tuple(members)):
        raise ValueError('Invalid member order')
    if any(type(i) is not int or i not in MEMBERS for i in zero_pv_members):
        raise ValueError('Invalid zero-PV metadata')
    o = history.origin_t
    raw = np.zeros((24, len(members)))
    fallback = cold = zero_count = 0
    season = {'naive_24': 24, 'naive_168': 168}.get(model_id)
    for j, i in enumerate(members):
        if target == 'pv_available_kw' and i in zero_pv_members:
            if np.any(history.values[:, i - 1] != 0):
                raise ValueError('PV ownership/history mismatch')
            zero_count += 24
            continue
        for h in range(24):
            index = o - 1 if season is None else o + h - season
            if 0 <= index < o:
                raw[h, j] = history.values[index, i - 1]
            else:
                fallback += 1
                if o:
                    raw[h, j] = history.values[o - 1, i - 1]
                else:
                    cold += 1  # No history: explicit zero cold-start forecast.
    clipped, diagnostics = clip_predictions(raw)
    diagnostics.update(fallback_count=fallback, cold_start_zero_count=cold, deterministic_zero_pv_count=zero_count)
    metadata = dict(provenance or {}, model_family='naive', model_version='F0-v1',
                    random_seed=0, refit_policy='none; no fitted parameters',
                    observed_range={'start': 0, 'stop_exclusive': o}, as_of_t=o - 1,
                    operationally_eligible=True, scenario='operational',
                    fallback_policy='unavailable seasonal lag -> persistence; empty history -> zero',
                    feature_set='historical target only; no weather, calendar or fitted preprocessing')
    result = ForecastResult(1, model_id, target, o, 24, tuple(members),
                            [Prediction(o, o+h, h+1, i, target, float(clipped[h,j]))
                             for h in range(24) for j,i in enumerate(members)], metadata, diagnostics)
    result.validate()
    return result
