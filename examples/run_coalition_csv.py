#!/usr/bin/env python3
"""Run a bounded physical coalition comparison using the example CSV files."""
import argparse
import csv
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "coalitions"))

from comfair.physical import PhysicalConfig, load_baseline, solve_physical

MEMBERS = tuple(range(1, 10))
DEFAULT_DATA = Path(__file__).resolve().parent / "data" / "comergy"


def _read_table(path, expected_header):
    path = Path(path)
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    if not rows or rows[0] != expected_header or len(rows) != 8761:
        raise ValueError(f"Unexpected annual CSV layout: {path}")
    stamps = [row[0] for row in rows[1:]]
    parsed = [datetime.fromisoformat(value) for value in stamps]
    if any(b - a != timedelta(hours=1) for a, b in zip(parsed, parsed[1:])):
        raise ValueError(f"Timestamps are not consecutive hourly values: {path}")
    try:
        values = np.asarray([[float(value) for value in row[1:]] for row in rows[1:]])
    except ValueError as exc:
        raise ValueError(f"Nonnumeric value in {path}") from exc
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError(f"Negative or nonfinite value in {path}")
    return stamps, values


def load_example(consumption, production, prices):
    member_header = ["timestamp"] + [f"member_{i}" for i in MEMBERS]
    load_t, demand = _read_table(consumption, member_header)
    pv_t, pv = _read_table(production, member_header)
    price_t, tariffs = _read_table(
        prices, ["timestamp", "electricity_price", "feedin_tariff"]
    )
    if not load_t == pv_t == price_t:
        raise ValueError("Consumption, production and price timestamps are not identical")
    if not ((tariffs[:, 0] > tariffs[:, 1]) & (tariffs[:, 1] > 0)).all():
        raise ValueError("Every electricity price must be greater than a positive feed-in tariff")
    paths = [Path(consumption), Path(production), Path(prices)]
    hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in paths}
    return load_t, demand, pv, tariffs, hashes


def parse_members(value):
    try:
        result = tuple(sorted({int(item.strip()) for item in value.split(",")}))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Members must be comma-separated integers") from exc
    if not result or any(member not in MEMBERS for member in result):
        raise argparse.ArgumentTypeError("Members must be a nonempty subset of 1..9")
    return result


def run(consumption, production, prices, members=(1, 3, 8), start=7008, hours=24):
    stamps, demand, pv, tariffs, hashes = load_example(consumption, production, prices)
    if start < 0 or hours < 1 or start + hours > len(stamps):
        raise ValueError("Use start >= 0, hours >= 1 and start + hours <= 8760")
    parameters, provenance = load_baseline()
    provenance = {
        **provenance,
        "source_kind": "standalone_csv_example",
        "source_sha256": hashes,
        "asset_assumption": "No battery metadata is present; all members use zero battery modules.",
    }
    stop = start + hours
    config = PhysicalConfig(
        member_ids=MEMBERS,
        demand_kw=demand[start:stop],
        pv_available_kw=pv[start:stop],
        battery_modules=(0,) * len(MEMBERS),
        import_aud_per_kwh=tariffs[start:stop, 0],
        export_aud_per_kwh=tariffs[start:stop, 1],
        billing_days=hours / 24,
        parameters=parameters,
        provenance=provenance,
    )
    baseline = {member: solve_physical((member,), config) for member in members}
    cooperative_pool = solve_physical(members, config)
    baseline_cost = sum(item.total_cost_aud for item in baseline.values())
    cooperative_cost = cooperative_pool.total_cost_aud
    if cooperative_cost > baseline_cost + parameters.cost_tolerance_aud:
        raise ValueError("Cooperative-pool cost exceeds the sum of standalone baseline costs")
    return {
        "kind": "standalone_csv_coalition_example",
        "members": list(members),
        "period": {
            "start_t": start,
            "hours": hours,
            "first_timestamp": stamps[start],
            "last_timestamp": stamps[stop - 1],
        },
        "assumptions": {
            "battery_modules_per_member": [0] * len(MEMBERS),
            "billing_days": hours / 24,
            "production_role": "available PV power in kW",
            "electricity_price_role": "grid import price in AUD/kWh",
            "feedin_tariff_role": "grid export price in AUD/kWh",
        },
        "source_sha256": hashes,
        "baseline": {
            "individual_cost_aud": {
                str(member): baseline[member].total_cost_aud for member in members
            },
            "total_cost_aud": baseline_cost,
        },
        "cooperative_pool": {
            "total_cost_aud": cooperative_cost,
            "value_aud": baseline_cost - cooperative_cost,
            "kpis": cooperative_pool.kpis,
        },
        "solver": cooperative_pool.solver,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumption", type=Path,
                        default=DEFAULT_DATA / "com_energy_consumption.csv")
    parser.add_argument("--production", type=Path,
                        default=DEFAULT_DATA / "com_energy_production.csv")
    parser.add_argument("--prices", type=Path, default=DEFAULT_DATA / "prices.csv")
    parser.add_argument("--members", type=parse_members, default=parse_members("1,3,8"))
    parser.add_argument("--start", type=int, default=7008)
    parser.add_argument("--hours", type=int, default=24,
                        help="Bounded horizon; use 8760 only for an intentional annual solve")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.consumption, args.production, args.prices,
                 args.members, args.start, args.hours)
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
        print(json.dumps({"output": str(args.output), "members": list(args.members)}))
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
