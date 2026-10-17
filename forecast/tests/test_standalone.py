from datetime import date
from pathlib import Path
import numpy as np
import pytest

from comfair.forecasting.configurable_engine import DEFAULT_SPLITS, parse_and_validate_splits
from comfair.forecasting.data import load_forecasting_csv_data
from comfair.forecasting.baselines import forecast
from comfair.forecasting.models import Candidate
from comfair.forecasting.schemas import MEMBERS


ROOT = Path(__file__).resolve().parents[2]
COMERGY = ROOT / "examples" / "data" / "comergy"


def load_test_data():
    return load_forecasting_csv_data(
        COMERGY / "com_energy_consumption.csv",
        COMERGY / "com_energy_production.csv",
    )


def test_default_splits():
    splits = parse_and_validate_splits(DEFAULT_SPLITS)
    assert splits["train"]["duration_days"] == 219
    assert splits["test"]["duration_days"] == 73

def test_invalid_gap_rejected():
    copy = {k: dict(v) for k, v in DEFAULT_SPLITS.items()}
    copy["validation"]["start_date"] = "2025-08-09"
    with pytest.raises(ValueError, match="immediately"):
        parse_and_validate_splits(copy)

def test_champion_configuration_identity():
    c = Candidate("ridge", "global", {"alpha": 0.1, "solver": "svd"})
    assert c.model_id == "ridge_global_7b21fa54198f"

def test_dataset_and_zero_pv():
    dataset, audit = load_test_data()
    assert audit["status"] == "PASS"
    assert dataset.zero_pv_members == (2, 5, 7)
    assert dataset.load_kw.shape == (8760, 9)
    assert np.all(dataset.pv_available_kw[:, [1, 4, 6]] == 0)

def test_forecast_grid_and_history():
    dataset, _ = load_test_data()
    result = forecast(dataset.history("pv_available_kw", 7008),
                      target="pv_available_kw", model_id="naive_24",
                      zero_pv_members=dataset.zero_pv_members)
    assert len(result.predictions) == 24 * len(MEMBERS)
    assert result.predictions[0].target_t == 7008
    assert max(p.target_t for p in result.predictions) == 7031
