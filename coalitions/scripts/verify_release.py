#!/usr/bin/env python3
"""Verify published evidence without solvers, datasets or platform imports.

Run from any directory. This command reads artifacts and the published snapshot;
it never regenerates or overwrites evidence.
"""
from pathlib import Path
import sys

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))

from comfair.presentation.insights import (
    IDS, TOL, build_snapshot, close, encoded, load_sources, require, vector,
)


def verify(directory=MODULE_ROOT):
    directory = Path(directory)
    sources = load_sources(directory / "comfair/artifacts")
    snapshot = build_snapshot(sources)
    published = directory / "results/coalition_insights_snapshot.json"
    require(published.read_bytes() == encoded(snapshot), "Published snapshot byte mismatch")
    game = sources["m5_coalitions.json"]
    records = game["records"]
    outside = vector(game["B_i_aud"])
    require([r["mask"] for r in records] == list(range(512)), "Unique ordered masks")
    for row in records:
        expected = [i for i in range(1, 10) if row["mask"] & (1 << (i - 1))]
        require(row["members"] == expected and row["size"] == len(expected), "Mask/member mapping")
        total = sum(outside[str(i)] for i in expected)
        close(total, row["sum_standalone_cost_aud"], "Standalone subtotal")
        close(total - row["coalition_cost_aud"], row["value_aud"], "Coalition value")
    grand_value = records[-1]["value_aud"]
    witness = vector(sources["m5_core.json"]["certificate"]["least_core_allocation_u_aud"])
    close(sum(witness.values()), grand_value, "Witness efficiency")
    require(min(witness.values()) >= -TOL, "Witness individual rationality")
    for row in records:
        require(row["value_aud"] - sum(witness[str(i)] for i in row["members"]) <= TOL,
                "Witness coalition inequality")
    policies = sources["m7_policy_comparison.json"]["policies"]
    require(len(policies) == 13 and len({p["policy_id"] for p in policies}) == 13,
            "13 distinct policies")
    for policy in policies:
        raw = policy["raw"]
        repaired = policy["repair_to_constitution"]["coalition"]["witness"]
        for benefits, bills in ((vector(raw["benefits_aud"]), vector(raw["bills_aud"])),
                                (vector(repaired["benefit_aud"]), vector(repaired["bill_aud"]))):
            close(sum(benefits.values()), grand_value, "Policy benefit conservation")
            close(sum(bills.values()), records[-1]["coalition_cost_aud"], "Policy bill conservation")
            for i in IDS:
                close(outside[i] - bills[i], benefits[i], "Member benefit identity")
        transfers = vector(repaired["tau_aud"])
        close(sum(transfers.values()), 0.0, "Repair budget balance")
        for i in IDS:
            close(raw["benefits_aud"][i] - transfers[i], repaired["benefit_aud"][i],
                  "Repair anchor identity")
    penalties = snapshot["bipartition_analysis"]["penalty_summary_aud"]
    print("PASS: five SHA-256 hashes; exact snapshot; 512 cost identities; all core inequalities;")
    print("      13 raw/repaired policy identities; zero-sum repair; 255 bipartitions.")
    print(f"Surplus: {grand_value:.9f} AUD")
    print(f"Fragmentation penalty min/max: {penalties['min']:.6f} / {penalties['max']:.6f} AUD")
    return snapshot


if __name__ == "__main__":
    verify()
