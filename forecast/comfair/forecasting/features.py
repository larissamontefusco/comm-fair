"""Origin-bounded lag and rolling features; ordinal periodicity only."""
import math
import numpy as np

LAGS = (1, 2, 3, 24, 48, 72, 168)


def features_at(history, target_t, member_id):
    history.validate()
    o = history.origin_t
    if type(target_t) is not int or target_t < o or type(member_id) is not int or member_id not in range(1, 10):
        raise ValueError('Invalid feature target/member')
    y = history.values[:, member_id - 1]
    result = {f'lag_{k}': float(y[target_t - k]) if 0 <= target_t - k < o else None for k in LAGS}
    for window, stats in ((24, ('mean', 'std', 'min', 'max')), (168, ('mean', 'std'))):
        for name in stats:
            result[f'rolling_{window}_{name}'] = (float(getattr(np, name)(y[o-window:o]))
                                                 if o >= window else None)
    for name, period in (('hour', 24), ('week', 168)):
        phase = target_t % period
        result[name + '_phase'] = phase
        result[name + '_sin'] = math.sin(2 * math.pi * phase / period)
        result[name + '_cos'] = math.cos(2 * math.pi * phase / period)
    return result


def observed_weather(values, observation_t, origin_t, *, scenario='operational'):
    """Optional historical weather boundary. F0 has no oracle implementation."""
    values = np.asarray(values, dtype=float)
    times = np.asarray(observation_t)
    if scenario != 'operational':
        raise ValueError('Oracle/external-weather forecasting is not implemented in F0')
    if (times.ndim != 1 or times.dtype.kind not in 'iu' or values.shape[0] != len(times)
            or (times < 0).any() or (times >= origin_t).any() or not np.isfinite(values).all()):
        raise ValueError('Future realised weather or invalid historical weather requested')
    return values.copy()
