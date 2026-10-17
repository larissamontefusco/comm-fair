"""
Benchmark summary generation: produces reproducible summary artifact.

Can be invoked as:
    python -m comfair.data.summary
    or
    from comfair.data.summary import generate_summary
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any
from comfair.data import load_benchmark


def generate_summary(
    workbook_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate benchmark summary from official workbook.

    Args:
        workbook_path: Path to Excel file (default: backend/reader/ComErgy Benchmark Dataset 2026.xlsx)
        output_path: If provided, write JSON summary to this path

    Returns:
        Dictionary with complete benchmark summary
    """
    benchmark = load_benchmark(workbook_path, validate=True)
    summary = benchmark.summary()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2, allow_nan=False)

    return summary


def print_summary(summary: Dict[str, Any]) -> None:
    """
    Pretty-print benchmark summary to console.

    Args:
        summary: Dictionary from generate_summary()
    """
    print("\n" + "=" * 70)
    print("ComErgy 2026 Benchmark Summary")
    print("=" * 70)

    # Metadata
    meta = summary["metadata"]
    print(f"\nLocation: {meta['location']}")
    print(f"Price unit: {meta['price_unit']}")
    print(f"Daily connection fee: {meta['daily_connection_fee']} {meta.get('daily_connection_fee_unit', 'AUD')}")
    print(f"Workbook: {Path(meta['workbook']).name}")

    # Dimensions
    dims = summary["dimensions"]
    print(f"\nMembers: {dims['member_count']}")
    print(f"Periods: {dims['period_count']} hours (1 year)")

    # Demand
    demand = summary["demand"]
    print(f"\nDemand:")
    print(f"  Total annual: {demand['annual_sum_raw']:,.0f} raw units")
    print(f"  Average hourly: {demand['average_hourly_raw']:.2f} raw units")
    print(f"  Peak (aggregate): {demand['aggregate_peak_raw']:.2f} raw units")

    # Per-member demand
    print(f"\n  Per-member annual demand (raw sums):")
    per_member = demand["annual_demand_per_member"]
    for member_id in range(1, 10):
        val = per_member[member_id]
        print(f"    Member {member_id}: {val:>9,.0f}")

    # PV assets
    pv = summary["pv"]
    print(f"\nPV Assets:")
    print(f"  Total modules: {pv['total_modules']}")
    print(f"  Owners: {pv['owners']}")
    if pv["module_distribution"]:
        for member_id in sorted(pv["module_distribution"].keys()):
            count = pv["module_distribution"][member_id]
            print(f"    Member {member_id}: {count}")
    else:
        print(f"    (none)")

    # Battery assets
    bess = summary["bess"]
    print(f"\nBattery Assets:")
    print(f"  Total modules: {bess['total_modules']}")
    print(f"  Owners: {bess['owners']}")
    if bess["module_distribution"]:
        for member_id in sorted(bess["module_distribution"].keys()):
            count = bess["module_distribution"][member_id]
            print(f"    Member {member_id}: {count}")
    else:
        print(f"    (none)")

    # Tariffs
    tariffs = summary["tariffs"]
    print(f"\nTariffs (raw values; scale unresolved):")
    grid_import = tariffs["grid_import_raw"]
    feedin = tariffs["feedin_raw"]
    print(f"  Grid import: {grid_import['min']:.4f} - {grid_import['max']:.4f} "
          f"(constant: {grid_import['constant']})")
    print(f"  Feedin:      {feedin['min']:.4f} - {feedin['max']:.4f} "
          f"(constant: {feedin['constant']})")

    # Weather
    weather = summary["weather"]
    print(f"\nWeather:")
    temp = weather["temperature_c"]
    ghi = weather["ghi_w_per_m2"]
    print(f"  Temperature [°C]: {temp['min']:.1f} to {temp['max']:.1f} "
          f"(mean: {temp['mean']:.1f})")
    print(f"  GHI [W/m²]: {ghi['min']:.0f} to {ghi['max']:.0f} "
          f"(mean: {ghi['mean']:.0f})")

    # Members detail
    print(f"\nMember Demographics:")
    members = summary["members"]
    for member_id in range(1, 10):
        member = members[member_id]
        income = member["annual_income_aud"]
        occupants = member["occupant_count"]
        pv_mod = member["pv_modules"]
        bess_mod = member["battery_modules"]
        print(f"\n  Member {member_id}:")
        print(f"    Household: {member['household_type'][:50]}")
        print(f"    Occupants: {occupants}")
        print(f"    Income: ${income:,.0f} AUD")
        if pv_mod > 0 or bess_mod > 0:
            assets = []
            if pv_mod > 0:
                assets.append(f"{pv_mod} PV")
            if bess_mod > 0:
                assets.append(f"{bess_mod} battery")
            print(f"    Assets: {', '.join(assets)}")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", nargs="?")
    parser.add_argument("--output", help="Optional JSON artifact path")
    args = parser.parse_args()
    print_summary(generate_summary(args.workbook, args.output))
