#!/usr/bin/env python3
"""Generate hourly 2025 PV production profiles for the nine EC members."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


# Paths are kept at the top so they can be changed easily.
READER_DIR = Path(__file__).resolve().parent
INPUT_EXCEL = READER_DIR / "ComErgy Benchmark Dataset 2026.xlsx"
INPUTS_DIR = READER_DIR.parent / "inputs"
OUTPUT_CSV = INPUTS_DIR / "com_energy_production.csv"

WORKSHEET_NAME = "ComErgy Benchmark Dataset 2026"
TEMPERATURE_COLUMN = "Dry Bulb Temperature [C]"
GHI_COLUMN = "GHI (W/m²)"
EXPECTED_HOURS = 8760
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"

PV_MODULES = {
    "member_1": 15,
    "member_2": 0,
    "member_3": 30,
    "member_4": 22,
    "member_5": 0,
    "member_6": 20,
    "member_7": 0,
    "member_8": 15,
    "member_9": 10,
}

MODULE_POWER_KW = 0.440
NMOT_C = 44.0
GAMMA_PMAX = -0.0033


def _normalize_header(header: object) -> str:
    """Normalize spacing and accept temperature units written as C or °C."""
    return " ".join(str(header).strip().replace("°", "").split()).casefold()


def _find_column(dataframe: pd.DataFrame, required_name: str) -> object:
    normalized_required = _normalize_header(required_name)
    matches = [
        column
        for column in dataframe.columns
        if _normalize_header(column) == normalized_required
    ]
    if len(matches) != 1:
        available = ", ".join(str(column) for column in dataframe.columns)
        raise ValueError(
            f"Expected exactly one column matching {required_name!r}, "
            f"but found {len(matches)}. Available columns: {available}"
        )
    return matches[0]


def load_weather(input_excel: Path) -> pd.DataFrame:
    """Load and validate the two required hourly weather series."""
    if not input_excel.is_file():
        raise FileNotFoundError(f"Input Excel file not found: {input_excel}")

    raw_data = pd.read_excel(
        input_excel,
        sheet_name=WORKSHEET_NAME,
        engine="openpyxl",
    )
    temperature_source = _find_column(raw_data, TEMPERATURE_COLUMN)
    ghi_source = _find_column(raw_data, GHI_COLUMN)

    weather = raw_data[[temperature_source, ghi_source]].copy()
    weather.columns = [TEMPERATURE_COLUMN, GHI_COLUMN]

    # The benchmark sheet has a secondary header row for unrelated columns.
    # Remove rows that are completely empty in the two weather fields, while
    # retaining partially empty rows so that they fail validation below.
    weather = weather.dropna(how="all").reset_index(drop=True)

    if len(weather) != EXPECTED_HOURS:
        raise ValueError(
            f"Expected exactly {EXPECTED_HOURS} hourly weather rows, "
            f"but found {len(weather)}."
        )

    numeric_weather = weather.apply(pd.to_numeric, errors="coerce")
    invalid_mask = numeric_weather.isna()
    if invalid_mask.any().any():
        invalid_positions = [
            f"hour {row_index + 1}, {column}"
            for row_index, column_index in zip(*invalid_mask.to_numpy().nonzero())
            for column in [numeric_weather.columns[column_index]]
        ]
        preview = "; ".join(invalid_positions[:10])
        raise ValueError(
            "Weather data contains missing or non-numeric values at "
            f"{preview}."
        )

    return numeric_weather


def create_timestamps() -> pd.DatetimeIndex:
    """Create the independent hourly timestamp index required for 2025."""
    timestamps = pd.date_range(
        start="2025-01-01 00:00:00",
        end="2025-12-31 23:00:00",
        freq="1h",
    )
    if len(timestamps) != EXPECTED_HOURS:
        raise ValueError(
            f"Expected exactly {EXPECTED_HOURS} timestamps, "
            f"but generated {len(timestamps)}."
        )
    return timestamps


def calculate_pv_production(
    weather: pd.DataFrame, timestamps: pd.DatetimeIndex
) -> pd.DataFrame:
    """Calculate hourly PV production in kW for every community member."""
    if len(weather) != len(timestamps):
        raise ValueError(
            "Weather and timestamp lengths differ: "
            f"{len(weather)} weather rows and {len(timestamps)} timestamps."
        )

    ambient_temperature = weather[TEMPERATURE_COLUMN]
    ghi = weather[GHI_COLUMN]
    module_temperature = ambient_temperature + ((NMOT_C - 20.0) / 800.0) * ghi

    output = pd.DataFrame({"timestamp": timestamps.strftime(TIMESTAMP_FORMAT)})

    # GHI is used as an approximation of irradiance on the PV modules.
    # Ideally, POA irradiance should be used if tilt/azimuth information
    # becomes available.
    for member, number_of_modules in PV_MODULES.items():
        installed_power_kw = number_of_modules * MODULE_POWER_KW

        if number_of_modules == 0:
            production = pd.Series(0.0, index=weather.index)
        else:
            production = (
                installed_power_kw
                * (ghi / 1000.0)
                * (1.0 + GAMMA_PMAX * (module_temperature - 25.0))
            )
            production = production.where(ghi > 0.0, 0.0).clip(lower=0.0)

        output[member] = production.round(3)

    return output


def print_summary(production: pd.DataFrame, output_csv: Path) -> None:
    """Print row count, installed capacities, peaks, energy, and output path."""
    print(f"Number of rows: {len(production)}")

    print("Installed PV capacity of each member:")
    for member, number_of_modules in PV_MODULES.items():
        installed_power_kw = number_of_modules * MODULE_POWER_KW
        print(f"  {member}: {installed_power_kw:.3f} kW")

    print("Maximum PV power of each member:")
    for member in PV_MODULES:
        print(f"  {member}: {production[member].max():.6f} kW")

    # Each sample represents one hour, so summing kW values yields kWh.
    print("Annual PV energy of each member:")
    for member in PV_MODULES:
        print(f"  {member}: {production[member].sum():.6f} kWh")

    print(f"Output file path: {output_csv.resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create hourly PV production profiles for the EC members."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_EXCEL,
        help=f"Source XLSX file (default: {INPUT_EXCEL})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_CSV,
        help=f"Destination CSV file (default: {OUTPUT_CSV})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weather = load_weather(args.input)
    timestamps = create_timestamps()
    production = calculate_pv_production(weather, timestamps)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    production.to_csv(
        args.output,
        index=False,
        float_format="%.3f",
        encoding="utf-8",
    )
    print_summary(production, args.output)


if __name__ == "__main__":
    main()
