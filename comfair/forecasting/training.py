"""Direct supervised rows, retaining the F0 origin information boundary."""
from dataclasses import dataclass
import numpy as np

from .data import History
from .features import LAGS, features_at
from .schemas import MEMBERS

FEATURE_NAMES = tuple(f'lag_{k}' for k in LAGS) + (
    'rolling_24_mean', 'rolling_24_std', 'rolling_24_min', 'rolling_24_max',
    'rolling_168_mean', 'rolling_168_std', 'hour_sin', 'hour_cos',
    'week_sin', 'week_cos', 'horizon_step')
FEATURE_SET = 'f0_all_lags_rolling_periodic_plus_horizon_v1'


@dataclass
class Rows:
    X: np.ndarray
    origin_t: np.ndarray
    target_t: np.ndarray
    horizon_step: np.ndarray
    member_id: np.ndarray
    y: np.ndarray | None = None


def origin_rows(history: History) -> Rows:
    """Vectorise horizons; reuse F0 rolling definitions once per member/origin.

    Input contains only t<origin. NaN means an unavailable lag, never a missing
    source target. Fixed one-hot member columns are added only for global models.
    """
    history.validate()
    o = history.origin_t
    target = np.arange(o, o + 24)
    X = np.empty((24, 9, len(FEATURE_NAMES)))
    for i in MEMBERS:
        base = features_at(history, o, i)
        for j, k in enumerate(LAGS):
            index = target - k
            valid = (index >= 0) & (index < o)
            X[:, i-1, j] = np.nan
            X[valid, i-1, j] = history.values[index[valid], i-1]
        for j, key in enumerate(FEATURE_NAMES[7:13], start=7):
            X[:, i-1, j] = np.nan if base[key] is None else base[key]
        for j, (period, fn) in enumerate(((24, np.sin), (24, np.cos),
                                         (168, np.sin), (168, np.cos)), start=13):
            X[:, i-1, j] = fn(2 * np.pi * (target % period) / period)
        X[:, i-1, 17] = np.arange(1, 25)
    return Rows(X.reshape(-1, len(FEATURE_NAMES)), np.full(216, o, dtype=int),
                np.repeat(target, 9), np.repeat(np.arange(1, 25), 9),
                np.tile(MEMBERS, 24))


def supervised_rows(history: History, *, first_origin=168) -> Rows:
    """Daily training examples whose complete label window precedes fit boundary.

    First 7 days are warm-up, not supervised labels. No training origin crosses
    the boundary; fitting on train+validation uses this identical policy.
    """
    history.validate()
    if first_origin < 168 or first_origin % 24 or history.origin_t % 24:
        raise ValueError('Training requires daily boundaries and at least 168h warm-up')
    blocks = []
    for o in range(first_origin, history.origin_t - 23, 24):
        block = origin_rows(History(o, history.values[:o]))
        block.y = history.values[block.target_t, block.member_id-1].copy()
        blocks.append(block)
    if not blocks:
        raise ValueError('Insufficient complete training windows')
    return Rows(**{key: np.concatenate([getattr(b, key) for b in blocks])
                   for key in ('X', 'origin_t', 'target_t', 'horizon_step', 'member_id', 'y')})


def design_matrix(rows: Rows, mode: str):
    if mode == 'local':
        return rows.X
    if mode != 'global':
        raise ValueError('Expected local/global strategy')
    # Categories are the canonical schema, not learned from evaluation data.
    return np.column_stack((rows.X, np.eye(9)[rows.member_id-1]))
