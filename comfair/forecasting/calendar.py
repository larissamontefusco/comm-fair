"""Dataset-calendar conversions shared by forecasting and optimisation inputs.

The timestamps in the current forecasting dataset are a synthetic display
calendar.  They are deliberately kept separate from wall-clock/live time.
"""

from datetime import date, datetime, timedelta

from .data import load_forecasting_data
FIT_BOUNDARY_T = 7008  # Reference F1 fit boundary (test begins here)
LAST_24H_ORIGIN_T = 8736  # Last complete 24-hour window in 8760-hour dataset


DATASET_EPOCH = date(2025, 1, 1)
FORECAST_HORIZON_HOURS = 24
RESOLUTION_MINUTES = 60


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("target_date must use YYYY-MM-DD") from exc
    raise ValueError("target_date must be a date or YYYY-MM-DD string")


def date_to_origin_t(value: date | str) -> int:
    """Convert a dataset date to its midnight ordinal hour."""
    target_date = _as_date(value)
    return (target_date - DATASET_EPOCH).days * 24


def origin_t_to_date(origin_t: int) -> date:
    """Convert a midnight ordinal hour to its dataset date."""
    if type(origin_t) is not int or origin_t < 0 or origin_t % 24:
        raise ValueError("origin_t must be a non-negative dataset midnight hour")
    return DATASET_EPOCH + timedelta(hours=origin_t)


def origin_t_to_timestamp(origin_t: int) -> str:
    """Return the synthetic dataset timestamp for an arbitrary hourly ordinal."""
    if type(origin_t) is not int or origin_t < 0:
        raise ValueError("origin_t must be a non-negative integer")
    return (datetime.combine(DATASET_EPOCH, datetime.min.time()) + timedelta(hours=origin_t)).isoformat()


def operational_calendar_metadata() -> dict:
    """Derive the supported daily window from constants and dataset metadata."""
    _, audit = load_forecasting_data()
    time_contract = audit["time_contract"]
    first_timestamp = datetime.fromisoformat(time_contract["synthetic_first"])
    last_timestamp = datetime.fromisoformat(time_contract["synthetic_last"])
    dataset_steps = audit["shapes"]["each_target"][0]

    dataset_first_origin = int(
        (first_timestamp.date() - DATASET_EPOCH).days * 24
    )
    dataset_last_complete_origin = dataset_first_origin + dataset_steps - FORECAST_HORIZON_HOURS
    minimum_origin = dataset_first_origin
    maximum_origin = min(LAST_24H_ORIGIN_T, dataset_last_complete_origin)

    if minimum_origin % 24 or maximum_origin % 24 or minimum_origin > maximum_origin:
        raise ValueError("Forecast constants do not define a supported daily dataset window")
    if last_timestamp < first_timestamp + timedelta(hours=dataset_steps - 1):
        raise ValueError("Dataset timestamp metadata does not cover the declared shape")

    return {
        "kind": "dataset_calendar",
        "label": "Synthetic dataset calendar (not live time)",
        "epoch_date": DATASET_EPOCH.isoformat(),
        "dataset_first_timestamp": first_timestamp.isoformat(),
        "dataset_last_timestamp": last_timestamp.isoformat(),
        "minimum_origin_t": minimum_origin,
        "maximum_origin_t": maximum_origin,
        "minimum_date": origin_t_to_date(minimum_origin).isoformat(),
        "maximum_date": origin_t_to_date(maximum_origin).isoformat(),
        "reference_test_start_date": "2025-10-20",
        "warning": "Dates identify the 2025 dataset horizon; they are not live forecasts.",
    }


def validated_observed_date(value: date | str) -> tuple[date, int, dict]:
    """Validate any *observed* date with a complete 24-hour dataset window.

    Unlike forecast evaluation, observed replay can deliberately select training
    data; callers must label these results as historical/in-sample.
    """
    target_date = _as_date(value)
    metadata = operational_calendar_metadata()
    _, audit = load_forecasting_data()
    first = datetime.fromisoformat(audit["time_contract"]["synthetic_first"]).date()
    steps = int(audit["shapes"]["each_target"][0])
    last_complete = DATASET_EPOCH + timedelta(days=(steps // 24) - 1)
    if not first <= target_date <= last_complete:
        raise ValueError(
            "observed target_date is outside the available full-day dataset window "
            f"[{first.isoformat()}, {last_complete.isoformat()}]"
        )
    return target_date, date_to_origin_t(target_date), {
        **metadata,
        "minimum_date": first.isoformat(),
        "maximum_date": last_complete.isoformat(),
        # This flag refers to the frozen reference model, not a custom training run.
        "historical_in_sample": target_date < date.fromisoformat(metadata["reference_test_start_date"]),
    }


def validated_target_date(
    value: date | str, eligible_range: tuple[date, date] | None = None
) -> tuple[date, int, dict]:
    """Parse a target date and validate it against the operational daily window or eligible range."""
    target_date = _as_date(value)
    origin_t = date_to_origin_t(target_date)
    metadata = operational_calendar_metadata()
    if not metadata["minimum_origin_t"] <= origin_t <= metadata["maximum_origin_t"]:
        raise ValueError(
            "target_date is outside the supported dataset window "
            f"[{metadata['minimum_date']}, {metadata['maximum_date']}]"
        )
    if eligible_range is not None:
        start_date, end_date = eligible_range
        if not start_date <= target_date <= end_date:
            raise ValueError(
                f"target_date is outside the eligible evaluation window "
                f"[{start_date.isoformat()}, {end_date.isoformat()}]"
            )
    return target_date, origin_t, metadata


def forecast_timestamps(origin_t: int, horizon_hours: int = FORECAST_HORIZON_HOURS) -> list[str]:
    if type(horizon_hours) is not int or horizon_hours <= 0:
        raise ValueError("horizon_hours must be a positive integer")
    return [origin_t_to_timestamp(origin_t + step) for step in range(horizon_hours)]
