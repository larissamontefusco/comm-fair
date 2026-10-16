"""Native-unit and percentage diagnostics with explicit denominator exclusions."""
import numpy as np

EPSILON_KW = 1e-9


def metrics(actual, predicted):
    y, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if y.shape != p.shape or not y.size or not np.isfinite(y).all() or not np.isfinite(p).all():
        raise ValueError('Metrics require equal nonempty finite arrays')
    error = np.abs(y - p)
    denominator = np.abs(y).sum()
    pair_denominator = np.abs(y) + np.abs(p)
    valid = pair_denominator > EPSILON_KW
    return {'n': int(y.size), 'mae_kw': float(error.mean()),
            'rmse_kw': float(np.sqrt(np.mean((y-p)**2))),
            'wape': float(error.sum()/denominator) if denominator > EPSILON_KW * y.size else None,
            'smape': float(np.mean(2*error[valid]/pair_denominator[valid])) if valid.any() else None,
            'wape_status': 'defined' if denominator > EPSILON_KW * y.size else 'undefined_near_zero_actual',
            'smape_valid_pairs': int(valid.sum()), 'smape_excluded_pairs': int((~valid).sum())}


def aggregate_metrics(actual, predicted, *, percentage_members):
    """Arrays (origins,24,9); percentages exclude zero-capacity PV members.

    Relative metrics are ratios (multiply by 100 for percent). Macro is the mean
    of member metrics, not a pooled sample-weighted score. Native metrics retain
    all nine members; relative scores use only eligible valid member denominators.
    """
    y, p = np.asarray(actual), np.asarray(predicted)
    if y.ndim != 3 or y.shape[1:] != (24, 9) or y.shape != p.shape:
        raise ValueError('Expected evaluation arrays (origins,24,9)')
    eligible = [i-1 for i in percentage_members]
    per_member = {str(i): metrics(y[:,:,i-1], p[:,:,i-1]) for i in range(1,10)}
    def pooled(a, b):
        result = metrics(a, b)
        relative = metrics(a[...,eligible], b[...,eligible]) if eligible else None
        for key in ('wape', 'smape', 'wape_status', 'smape_valid_pairs', 'smape_excluded_pairs'):
            result[key] = relative[key] if relative else None
        result['percentage_member_ids'] = list(percentage_members)
        return result
    macro = {}
    for key in ('mae_kw', 'rmse_kw', 'wape', 'smape'):
        ids = range(1,10) if key.endswith('_kw') else percentage_members
        values = [per_member[str(i)][key] for i in ids if per_member[str(i)][key] is not None]
        macro[key] = float(np.mean(values)) if values else None
        macro[key + '_member_count'] = len(values)
    return {'per_member': per_member, 'micro': pooled(y, p), 'member_macro': macro,
            'per_horizon_step': {str(h+1): pooled(y[:,h,:], p[:,h,:]) for h in range(24)}}
