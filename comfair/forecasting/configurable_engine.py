"""Configurable, versioned forecasting training and evaluation engine.

Provides real, dynamic training and evaluation for community-defined splits
(Training, Validation, Testing) without modifying frozen historical scientific
benchmarks (F0/F1).
"""

from dataclasses import asdict
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import numpy as np

from .baselines import forecast as baseline_forecast
from .calendar import (
    DATASET_EPOCH,
    date_to_origin_t,
    forecast_timestamps,
    origin_t_to_date,
    origin_t_to_timestamp,
)
from .data import History, load_forecasting_data
from .management import canonical_json as canonical_mgmt_json
from .models import Candidate, fit_candidate, FittedModel
from .schemas import MEMBERS, canonical_json
from .training import Rows, origin_rows

# Default / Reference splits (historical benchmark preset)
DEFAULT_SPLITS = {
    "train": {"start_date": "2025-01-01", "end_date": "2025-08-07"},
    "validation": {"start_date": "2025-08-08", "end_date": "2025-10-19"},
    "test": {"start_date": "2025-10-20", "end_date": "2025-12-31"},
}

DATASET_MIN_DATE = date(2025, 1, 1)
DATASET_MAX_DATE = date(2025, 12, 31)
MIN_TRAIN_DAYS = 8
ZERO_PV_MEMBERS = (2, 5, 7)
LOAD_MODEL_ID = "ridge_global_7b21fa54198f"
PV_MODEL_ID = "naive_24"


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Invalid date format: {value}")


def parse_and_validate_splits(
    splits: dict,
    dataset_min: date = DATASET_MIN_DATE,
    dataset_max: date = DATASET_MAX_DATE,
) -> dict:
    """Validate contiguous daily splits without gaps or overlaps.

    Enforces:
    - Train start >= dataset_min
    - Train start <= Train end
    - Train end + 1 day == Validation start
    - Validation start <= Validation end
    - Validation end + 1 day == Test start
    - Test start <= Test end <= dataset_max
    - Train duration >= MIN_TRAIN_DAYS (8 days = 192h, for 168h warmup + labels)
    - Validation duration >= 1 day
    - Test duration >= 1 day
    """
    if not isinstance(splits, dict):
        raise ValueError("splits must be a dictionary")

    for key in ("train", "validation", "test"):
        if key not in splits:
            raise ValueError(f"Missing required split '{key}'")
        if not isinstance(splits[key], dict):
            raise ValueError(f"Split '{key}' must be an object with start_date and end_date")
        if "start_date" not in splits[key] or "end_date" not in splits[key]:
            raise ValueError(f"Split '{key}' must include start_date and end_date")

    try:
        train_start = _as_date(splits["train"]["start_date"])
        train_end = _as_date(splits["train"]["end_date"])
        val_start = _as_date(splits["validation"]["start_date"])
        val_end = _as_date(splits["validation"]["end_date"])
        test_start = _as_date(splits["test"]["start_date"])
        test_end = _as_date(splits["test"]["end_date"])
    except ValueError as exc:
        raise ValueError(f"Invalid split date format (YYYY-MM-DD expected): {exc}") from exc

    if train_start > train_end:
        raise ValueError(f"Training start date ({train_start}) cannot succeed end date ({train_end})")
    if val_start > val_end:
        raise ValueError(f"Validation start date ({val_start}) cannot succeed end date ({val_end})")
    if test_start > test_end:
        raise ValueError(f"Testing start date ({test_start}) cannot succeed end date ({test_end})")

    if train_start < dataset_min:
        raise ValueError(f"Training start date ({train_start}) precedes dataset minimum ({dataset_min})")
    if test_end > dataset_max:
        raise ValueError(f"Testing end date ({test_end}) exceeds dataset maximum ({dataset_max})")

    # Contiguous boundary requirement
    expected_val_start = train_end + timedelta(days=1)
    if val_start != expected_val_start:
        raise ValueError(
            f"Validation must start immediately after training: expected {expected_val_start}, got {val_start}"
        )

    expected_test_start = val_end + timedelta(days=1)
    if test_start != expected_test_start:
        raise ValueError(
            f"Testing must start immediately after validation: expected {expected_test_start}, got {test_start}"
        )

    # Durations
    train_days = (train_end - train_start).days + 1
    if train_days < MIN_TRAIN_DAYS:
        raise ValueError(
            f"Training period requires at least {MIN_TRAIN_DAYS} days (192 hours) "
            f"to cover 168h feature lags and supervised labels; received {train_days} days"
        )

    val_days = (val_end - val_start).days + 1
    if val_days < 1:
        raise ValueError("Validation period requires at least 1 full day (24 hours)")

    test_days = (test_end - test_start).days + 1
    if test_days < 1:
        raise ValueError("Testing period requires at least 1 full day (24 hours)")

    return {
        "train": {
            "start_date": train_start.isoformat(),
            "end_date": train_end.isoformat(),
            "duration_days": train_days,
        },
        "validation": {
            "start_date": val_start.isoformat(),
            "end_date": val_end.isoformat(),
            "duration_days": val_days,
        },
        "test": {
            "start_date": test_start.isoformat(),
            "end_date": test_end.isoformat(),
            "duration_days": test_days,
        },
    }


def compute_dataset_source_hash(source_hashes: dict) -> str:
    """Compute a deterministic SHA-256 hash of dataset source hashes."""
    return sha256(canonical_mgmt_json(source_hashes).encode("utf-8")).hexdigest()


def compute_split_config_sha256(splits: dict, dataset_source_hash: str) -> str:
    """Compute a deterministic hash for a validated split configuration."""
    canonical_splits = {
        key: {
            "start_date": splits[key]["start_date"],
            "end_date": splits[key]["end_date"],
        }
        for key in ("train", "validation", "test")
    }
    payload = {
        "dataset_source_hash": dataset_source_hash,
        "splits": canonical_splits,
    }
    return sha256(canonical_mgmt_json(payload).encode("utf-8")).hexdigest()


def supervised_rows_custom(history: History, train_start_t: int, train_stop_t: int) -> Rows:
    """Build supervised training rows for an arbitrary contiguous daily window.

    Ensures at least 168h of warm-up history precedes the first supervised origin,
    and all complete 24h windows strictly precede train_stop_t.
    """
    history.validate()
    first_origin = max(168, train_start_t)
    if first_origin % 24 != 0 or train_stop_t % 24 != 0:
        raise ValueError("Supervised training window bounds must be full daily midnight boundaries")

    blocks = []
    for o in range(first_origin, train_stop_t - 23, 24):
        block = origin_rows(History(o, history.values[:o]))
        block.y = history.values[block.target_t, block.member_id - 1].copy()
        blocks.append(block)

    if not blocks:
        raise ValueError(
            f"Insufficient complete training windows between origin {first_origin} and {train_stop_t}"
        )

    return Rows(
        **{
            key: np.concatenate([getattr(b, key) for b in blocks])
            for key in ("X", "origin_t", "target_t", "horizon_step", "member_id", "y")
        }
    )


def calculate_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Compute standard forecasting evaluation metrics (MAE, RMSE, WAPE)."""
    error = y_pred - y_true
    abs_error = np.abs(error)
    mae = float(np.mean(abs_error))
    rmse = float(np.sqrt(np.mean(error**2)))
    sum_true = float(np.sum(np.abs(y_true)))
    wape = float(np.sum(abs_error) / sum_true) if sum_true > 0 else 0.0
    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "wape": round(wape, 4),
    }


def execute_training_and_evaluation(validated_splits: dict) -> dict:
    """Fit Ridge Global on Train, evaluate on Validation, refit on Train+Val, evaluate on Test.

    Evaluates both Ridge Global (load_kw) and Naive 24 (pv_available_kw).
    Returns complete run results, metrics, parameters, and fingerprints.
    """
    train_start = _as_date(validated_splits["train"]["start_date"])
    train_end = _as_date(validated_splits["train"]["end_date"])
    val_start = _as_date(validated_splits["validation"]["start_date"])
    val_end = _as_date(validated_splits["validation"]["end_date"])
    test_start = _as_date(validated_splits["test"]["start_date"])
    test_end = _as_date(validated_splits["test"]["end_date"])

    train_start_t = date_to_origin_t(train_start)
    train_stop_t = date_to_origin_t(train_end) + 24
    val_start_t = date_to_origin_t(val_start)
    val_stop_t = date_to_origin_t(val_end) + 24
    test_start_t = date_to_origin_t(test_start)
    test_stop_t = date_to_origin_t(test_end) + 24

    dataset, audit = load_forecasting_data()
    source_hashes = {k: v["sha256"] for k, v in audit["sources"].items()}
    dataset_source_hash = compute_dataset_source_hash(source_hashes)
    config_hash = compute_split_config_sha256(validated_splits, dataset_source_hash)

    candidate = Candidate("ridge", "global", {"alpha": 0.1, "solver": "svd"})

    # --- Phase 1: Fit on Train ---
    hist_train = dataset.history("load_kw", train_stop_t)
    train_rows = supervised_rows_custom(hist_train, train_start_t, train_stop_t)
    fitted_train = fit_candidate(candidate, hist_train, "load_kw", ZERO_PV_MEMBERS, rows=train_rows)

    # --- Phase 2: Walk-forward evaluation on Validation ---
    val_load_preds, val_load_actuals = [], []
    val_pv_preds, val_pv_actuals = [], []

    for o in range(val_start_t, val_stop_t, 24):
        # Load forecast with model fitted strictly before validation
        res_load = fitted_train.forecast(dataset.history("load_kw", o))
        p_load = np.zeros((24, 9))
        for p in res_load.predictions:
            p_load[p.horizon_step - 1, p.member_id - 1] = p.y_pred
        val_load_preds.append(p_load)
        val_load_actuals.append(dataset.history("load_kw", o + 24).values[o : o + 24, :])

        # PV forecast with Naive 24 baseline
        res_pv = baseline_forecast(
            dataset.history("pv_available_kw", o),
            target="pv_available_kw",
            model_id=PV_MODEL_ID,
            zero_pv_members=ZERO_PV_MEMBERS,
        )
        p_pv = np.zeros((24, 9))
        for p in res_pv.predictions:
            p_pv[p.horizon_step - 1, p.member_id - 1] = p.y_pred
        val_pv_preds.append(p_pv)
        val_pv_actuals.append(dataset.history("pv_available_kw", o + 24).values[o : o + 24, :])

    val_metrics = {
        "load_kw": calculate_metrics(np.array(val_load_actuals), np.array(val_load_preds)),
        "pv_available_kw": calculate_metrics(np.array(val_pv_actuals), np.array(val_pv_preds)),
        "evaluation_days": (val_stop_t - val_start_t) // 24,
        "evaluation_origins": list(range(val_start_t, val_stop_t, 24)),
    }

    # --- Phase 3: Final Model Refit on Train + Validation ---
    hist_train_val = dataset.history("load_kw", val_stop_t)
    train_val_rows = supervised_rows_custom(hist_train_val, train_start_t, val_stop_t)
    fitted_final = fit_candidate(
        candidate, hist_train_val, "load_kw", ZERO_PV_MEMBERS, rows=train_val_rows
    )
    if fitted_final.fit_stop != test_start_t:
        raise ValueError(f"Final model fit boundary {fitted_final.fit_stop} != test start {test_start_t}")

    # --- Phase 4: Walk-forward evaluation on Testing (hold-out) ---
    test_load_preds, test_load_actuals = [], []
    test_pv_preds, test_pv_actuals = [], []

    for o in range(test_start_t, test_stop_t, 24):
        # Coefficients remain fixed at fitted_final; lags use observations up to o
        res_load = fitted_final.forecast(dataset.history("load_kw", o))
        p_load = np.zeros((24, 9))
        for p in res_load.predictions:
            p_load[p.horizon_step - 1, p.member_id - 1] = p.y_pred
        test_load_preds.append(p_load)
        test_load_actuals.append(dataset.history("load_kw", o + 24).values[o : o + 24, :])

        res_pv = baseline_forecast(
            dataset.history("pv_available_kw", o),
            target="pv_available_kw",
            model_id=PV_MODEL_ID,
            zero_pv_members=ZERO_PV_MEMBERS,
        )
        p_pv = np.zeros((24, 9))
        for p in res_pv.predictions:
            p_pv[p.horizon_step - 1, p.member_id - 1] = p.y_pred
        test_pv_preds.append(p_pv)
        test_pv_actuals.append(dataset.history("pv_available_kw", o + 24).values[o : o + 24, :])

    test_metrics = {
        "load_kw": calculate_metrics(np.array(test_load_actuals), np.array(test_load_preds)),
        "pv_available_kw": calculate_metrics(np.array(test_pv_actuals), np.array(test_pv_preds)),
        "evaluation_days": (test_stop_t - test_start_t) // 24,
        "evaluation_origins": list(range(test_start_t, test_stop_t, 24)),
    }

    # Extract model parameters and fingerprint
    model_sha256 = parameter_fingerprint(fitted_final)
    p_steps = fitted_final.models["global"].named_steps
    model_artifact_ref = {
        "simpleimputer": {
            "statistics_": np.asarray(p_steps["simpleimputer"].statistics_).tolist(),
            "indicator_features": p_steps["simpleimputer"].indicator_.features_.tolist(),
        },
        "standardscaler": {
            "mean_": np.asarray(p_steps["standardscaler"].mean_).tolist(),
            "scale_": np.asarray(p_steps["standardscaler"].scale_).tolist(),
            "var_": np.asarray(p_steps["standardscaler"].var_).tolist(),
        },
        "ridge": {
            "coef_": np.asarray(p_steps["ridge"].coef_).tolist(),
            "intercept_": float(p_steps["ridge"].intercept_),
        },
        "fit_stop": fitted_final.fit_stop,
        "train_start_t": train_start_t,
        "train_stop_t": train_stop_t,
        "val_stop_t": val_stop_t,
    }

    model_configs = {
        "load": {
            "model_id": candidate.model_id,
            "family": candidate.family,
            "mode": candidate.mode,
            "parameters": candidate.parameters,
            "fit_stop_t": fitted_final.fit_stop,
            "fit_stop_date": origin_t_to_date(fitted_final.fit_stop).isoformat(),
        },
        "pv": {
            "model_id": PV_MODEL_ID,
            "family": "naive",
            "mode": "local",
            "parameters": {"lag": 24},
        },
    }

    # Populate fitted model cache
    _FITTED_MODELS_CACHE[model_sha256] = fitted_final

    return {
        "config_sha256": config_hash,
        "dataset_source_hash": dataset_source_hash,
        "model_sha256": model_sha256,
        "model_configs": model_configs,
        "model_artifact_ref": model_artifact_ref,
        "validation_metrics": val_metrics,
        "test_metrics": test_metrics,
        "source_hashes": source_hashes,
        "eligible_test_start": test_start.isoformat(),
        "eligible_test_end": test_end.isoformat(),
        "train_days": validated_splits["train"]["duration_days"],
        "val_days": validated_splits["validation"]["duration_days"],
        "test_days": validated_splits["test"]["duration_days"],
    }


_FITTED_MODELS_CACHE: dict[str, FittedModel] = {}



def parameter_fingerprint(fitted: FittedModel) -> str:
    """Deterministic Ridge parameter fingerprint; standalone copy of original F3 helper."""
    params = fitted.models["global"].named_steps
    fields = {"simpleimputer": ("statistics_",),
              "standardscaler": ("mean_", "scale_", "var_"),
              "ridge": ("coef_", "intercept_")}
    values = {name: {key: np.asarray(getattr(params[name], key)).tolist() for key in keys}
              for name, keys in fields.items()}
    values["indicator_features"] = params["simpleimputer"].indicator_.features_.tolist()
    return sha256(canonical_json(values).encode()).hexdigest()
