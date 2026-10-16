"""Bounded CPU model configurations and typed, origin-bounded inference."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version
from time import perf_counter
import warnings

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor
from statsmodels.tsa.ar_model import AutoReg
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from threadpoolctl import threadpool_limits

from .baselines import clip_predictions
from .data import History
from .schemas import ForecastResult, Prediction, MEMBERS, TARGETS, canonical_json
from .training import FEATURE_SET, design_matrix, origin_rows, supervised_rows

LIBRARIES = {'ridge': 'scikit-learn', 'random_forest': 'scikit-learn',
             'extra_trees': 'scikit-learn', 'autoreg': 'statsmodels',
             'lightgbm': 'lightgbm', 'xgboost': 'xgboost-cpu'}


@dataclass(frozen=True)
class Candidate:
    family: str
    mode: str
    parameters: dict

    @property
    def model_id(self):
        digest = sha256(canonical_json(asdict(self)).encode()).hexdigest()[:12]
        return f'{self.family}_{self.mode}_{digest}'

    def metadata(self):
        return {'model_id': self.model_id, 'model_family': self.family,
                'local_or_global': self.mode,
                'direct_or_recursive': 'recursive' if self.family == 'autoreg' else 'direct',
                'feature_set': 'autoregressive_dense_lags' if self.family == 'autoreg' else FEATURE_SET,
                'hyperparameters': self.parameters, 'seed': 0, 'threads': 1,
                'library': LIBRARIES[self.family], 'library_version': version(LIBRARIES[self.family]),
                'preprocessing': ('none' if self.family == 'autoreg' else
                    'train-only median imputer with missing indicators' +
                    ('; train-only StandardScaler' if self.family == 'ridge' else '') +
                    ('; fixed canonical member one-hot 1..9' if self.mode == 'global' else ''))}


def candidates():
    result = [Candidate('autoreg', 'local', {'lags': k, 'trend': 'c'}) for k in (24, 168)]
    for mode in ('local', 'global'):
        result += [Candidate('ridge', mode, {'alpha': a, 'solver': 'svd'}) for a in (.1, 1., 10.)]
        for family in ('random_forest', 'extra_trees'):
            result += [Candidate(family, mode, {'n_estimators': 64, 'max_depth': 12,
                       'min_samples_leaf': leaf, 'max_features': 1.0}) for leaf in (1, 4)]
        result += [Candidate('lightgbm', mode, {'n_estimators': 100, 'learning_rate': .05,
                   'num_leaves': leaves, 'min_child_samples': 20, 'max_depth': -1}) for leaves in (15, 31)]
        result += [Candidate('xgboost', mode, {'n_estimators': 100, 'learning_rate': .05,
                   'max_depth': depth, 'min_child_weight': 1, 'subsample': 1.,
                   'colsample_bytree': 1.}) for depth in (3, 6)]
    return tuple(result)


def estimator(candidate):
    p = candidate.parameters
    if candidate.family == 'ridge':
        model = Ridge(**p)
    elif candidate.family in ('random_forest', 'extra_trees'):
        cls = RandomForestRegressor if candidate.family == 'random_forest' else ExtraTreesRegressor
        model = cls(**p, random_state=0, n_jobs=1)
    elif candidate.family == 'lightgbm':
        model = LGBMRegressor(**p, random_state=0, n_jobs=1, deterministic=True,
                              force_col_wise=True, verbosity=-1)
    elif candidate.family == 'xgboost':
        model = XGBRegressor(**p, random_state=0, n_jobs=1, tree_method='hist', device='cpu',
                             objective='reg:squarederror')
    else:
        raise ValueError('Not a direct model')
    steps = [SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True)]
    if candidate.family == 'ridge':
        steps.append(StandardScaler())
    return make_pipeline(*steps, model)


@dataclass
class FittedModel:
    candidate: Candidate
    target: str
    zero_pv_members: tuple
    fit_stop: int
    models: dict
    training_runtime: float
    warnings: list

    def forecast(self, history: History, *, provenance=None):
        history.validate()
        if history.origin_t < self.fit_stop:
            raise ValueError('Model fitted beyond forecast origin')
        if self.target == 'pv_available_kw' and any(np.any(history.values[:, i-1]) for i in self.zero_pv_members):
            raise ValueError('PV ownership/history mismatch')
        raw = np.zeros((24, 9))
        with threadpool_limits(limits=1):
            if self.candidate.family == 'autoreg':
                lag = self.candidate.parameters['lags']
                for i, params in self.models.items():
                    past = list(history.values[-lag:, i-1])
                    for h in range(24):
                        # Recursive AR uses its own raw predictions, never future actuals.
                        value = float(params[0] + np.dot(params[1:], past[-lag:][::-1]))
                        raw[h, i-1] = value
                        past.append(value)
            else:
                rows = origin_rows(history)
                X = design_matrix(rows, self.candidate.mode)
                flat = raw.reshape(-1)
                for key, model in self.models.items():
                    mask = (np.isin(rows.member_id, self.active_members) if key == 'global'
                            else rows.member_id == key)
                    # sklearn emits this benign warning because LGBM generates its own
                    # names on ndarray fit; feature order is fixed by our schema.
                    with warnings.catch_warnings():
                        warnings.filterwarnings('ignore', message='X does not have valid feature names')
                        flat[mask] = model.predict(X[mask])
        clipped, diagnostics = clip_predictions(raw)
        diagnostics['deterministic_zero_pv_count'] = 24 * len(self.zero_pv_members) if self.target == 'pv_available_kw' else 0
        metadata = dict(provenance or {}, **self.candidate.metadata(), operationally_eligible=True,
                        scenario='operational', training_range={'start': 0, 'stop_exclusive': self.fit_stop},
                        observed_range={'start': 0, 'stop_exclusive': history.origin_t},
                        as_of_t=history.origin_t-1, refit_policy='fixed coefficients; expanding observed history')
        o = history.origin_t
        result = ForecastResult(1, self.candidate.model_id, self.target, o, 24, MEMBERS,
                 [Prediction(o, o+h, h+1, i, self.target, float(clipped[h, i-1]))
                  for h in range(24) for i in MEMBERS], metadata, diagnostics)
        result.validate()
        return result

    @property
    def active_members(self):
        return tuple(i for i in MEMBERS if self.target != 'pv_available_kw' or i not in self.zero_pv_members)


def fit_candidate(candidate, history, target, zero_pv_members=(), *, rows=None):
    """Fit only a bounded History; neither validation nor test arrays are accepted."""
    history.validate()
    if target not in TARGETS or candidate.mode not in ('local', 'global'):
        raise ValueError('Invalid target/strategy')
    if target == 'pv_available_kw' and any(np.any(history.values[:, i-1]) for i in zero_pv_members):
        raise ValueError('PV ownership/history mismatch')
    result = FittedModel(candidate, target, tuple(zero_pv_members), history.origin_t, {}, 0., [])
    start = perf_counter()
    with threadpool_limits(limits=1), warnings.catch_warnings(record=True) as caught:
        if candidate.family == 'autoreg':
            if candidate.mode != 'local':
                raise ValueError('AutoReg is local only')
            for i in result.active_members:
                fitted = AutoReg(history.values[:, i-1], **candidate.parameters, old_names=False).fit()
                result.models[i] = np.asarray(fitted.params)
        else:
            rows = supervised_rows(history) if rows is None else rows
            if (rows.y is None or np.any(rows.target_t >= history.origin_t)
                    or not np.array_equal(rows.y, history.values[rows.target_t, rows.member_id-1])):
                raise ValueError('Training labels cross history boundary or are misaligned')
            X = design_matrix(rows, candidate.mode)
            keys = ('global',) if candidate.mode == 'global' else result.active_members
            for key in keys:
                mask = np.isin(rows.member_id, result.active_members) if key == 'global' else rows.member_id == key
                result.models[key] = estimator(candidate).fit(X[mask], rows.y[mask])
        result.warnings = sorted(set(str(w.message) for w in caught))
    result.training_runtime = perf_counter() - start
    return result
