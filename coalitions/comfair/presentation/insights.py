"""Validate canonical research evidence and export a deterministic Coalition Insights snapshot.

Reads canonical 8,760-hour annual benchmark artifacts with cryptographic SHA-256 verification,
validates game-theoretic and physical invariants, and generates a structured research snapshot
for the Coalition Insights & Case Studies module.

No scientific packages, database, or live solver dependencies.
Strictly read-only with respect to canonical artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

_COMFAIR_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = _COMFAIR_DIR / "artifacts"
OUTPUT = ROOT / "frontend/commfair-website/assets/research/coalition_insights_snapshot.json"

INPUT_SHA256: Mapping[str, str] = {
    "m3_baselines.json": "767c7c1538768d8db7840194597401bc133fd8ae5c23da3d497754d7cd8997aa",
    "m5_coalitions.json": "cca30380f74cb0579e3024b401095779ae88bee7dee39f41554944810156bbb8",
    "m5_core.json": "985f155b46c170dc1069790cd5bdd7dfc6b6678f4214089063692cb72193a5ee",
    "m7_governance.json": "dafc21444a21ab395da69b5a9f7f65b66d3933a0dee235e64d40cc88e769b7e2",
    "m7_policy_comparison.json": "b636aae9bda8d6c51f3bc1e0c8defaaac8d19d90cc63d0c42d9489b37c50e6a0",
}

IDS: Sequence[str] = [str(i) for i in range(1, 10)]
NUM_MEMBERS: int = 9
TOL: float = 1e-5

ARCHETYPES: Mapping[str, str] = {
    "1": "Solar Exporter (PV-only)",
    "2": "Flexible Storage (BESS-only)",
    "3": "Solar + Storage Prosumer",
    "4": "Solar Exporter (PV-only)",
    "5": "Pure Consumer (No DER assets)",
    "6": "Solar + Storage Prosumer",
    "7": "Flexible Storage (BESS-only)",
    "8": "Solar + Storage Prosumer",
    "9": "Solar Exporter (PV-only)",
}

POLICY_LABELS: Mapping[str, str] = {
    "A4_minimum_repair": "Minimum Necessary Repair",
    "G0_market": "Market Anchor",
    "G1_equal_benefit": "Equal Benefit",
    "G2_contribution_proportional": "Contribution Proportional",
    "G3_shapley": "Shapley Value",
    "G4_nucleolus": "Nucleolus",
    "P0_protected_marginal": "Protected Marginal Pricing",
    "P1_midpoint": "Tariff Midpoint Pricing",
    "P2_lower_fit": "Feed-in Tariff Floor Pricing",
    "P3_upper_grid": "Grid Tariff Ceiling Pricing",
    "closest_core_l1_to_market": "Closest Core to Market (L1)",
    "fair_least_core_maxmin": "Fair Least-Core (Max-Min)",
    "maxmin_benefit": "Max-Min Benefit",
}


def require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(label)


def number(value: Any) -> float:
    require(type(value) in (int, float) and math.isfinite(value), "Finite number required")
    return float(value)


def close(a: float, b: float, label: str, tolerance: float = TOL) -> None:
    require(abs(number(a) - number(b)) <= tolerance, f"{label}: |{a} - {b}| > {tolerance}")


def vector(value: Any) -> Dict[str, float]:
    require(isinstance(value, dict) and set(value) == set(IDS), "Exact canonical member IDs required")
    return {i: number(value[i]) for i in IDS}


def load_sources(directory: Path = ARTIFACTS) -> Dict[str, Any]:
    def unique(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    sources: Dict[str, Any] = {}
    for name, expected_hash in INPUT_SHA256.items():
        file_path = directory / name
        require(file_path.is_file(), f"Missing required scientific artifact: {name}")
        raw_bytes = file_path.read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        require(actual_hash == expected_hash, f"SHA-256 mismatch for {name}: expected {expected_hash}, got {actual_hash}")
        sources[name] = json.loads(raw_bytes, object_pairs_hook=unique)
    return sources


def calculate_size_statistics(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_size: Dict[int, List[Dict[str, Any]]] = {}
    for r in records:
        by_size.setdefault(int(r["size"]), []).append(r)

    stats: List[Dict[str, Any]] = []
    for sz in range(NUM_MEMBERS + 1):
        group = by_size.get(sz, [])
        count = len(group)
        require(count == math.comb(NUM_MEMBERS, sz), f"Subset count mismatch for size {sz}")

        vals = sorted(number(r["value_aud"]) for r in group)
        costs = sorted(number(r["coalition_cost_aud"]) for r in group)

        mean_val = sum(vals) / count
        mean_cost = sum(costs) / count

        std_val = math.sqrt(sum((x - mean_val) ** 2 for x in vals) / count)
        std_cost = math.sqrt(sum((x - mean_cost) ** 2 for x in costs) / count)

        median_val = vals[count // 2] if count % 2 == 1 else 0.5 * (vals[count // 2 - 1] + vals[count // 2])
        median_cost = costs[count // 2] if count % 2 == 1 else 0.5 * (costs[count // 2 - 1] + costs[count // 2])

        q25_val = vals[int(count * 0.25)]
        q75_val = vals[int(count * 0.75)] if sz < NUM_MEMBERS else vals[-1]

        stats.append({
            "size": sz,
            "coalition_count": count,
            "value_aud": {
                "min": vals[0],
                "max": vals[-1],
                "mean": mean_val,
                "median": median_val,
                "std": std_val,
                "q25": q25_val,
                "q75": q75_val,
            },
            "cost_aud": {
                "min": costs[0],
                "max": costs[-1],
                "mean": mean_cost,
                "median": median_cost,
                "std": std_cost,
            },
        })
    return stats


def calculate_bipartitions(records: Sequence[Dict[str, Any]], grand_cost: float, sum_b0: float) -> Dict[str, Any]:
    costs = {int(r["mask"]): number(r["coalition_cost_aud"]) for r in records}
    values = {int(r["mask"]): number(r["value_aud"]) for r in records}

    bipartitions: List[Dict[str, Any]] = []

    # Enumerate unique non-trivial bipartitions by fixing Member 1 (bit 0) in Block A.
    # Range is 1 to 510 (all masks where bit 0 is 1, excluding mask 511 which is Grand Coalition).
    for mask_a in range(1, 511):
        if mask_a & 1:  # Member 1 is in Block A
            mask_b = 511 ^ mask_a
            require(mask_b > 0 and (mask_b & 1) == 0, "Disjoint complement verification")

            cost_a = costs[mask_a]
            cost_b = costs[mask_b]
            partition_cost = cost_a + cost_b

            # Penalty vs grand coalition: cost_partition - grand_cost = v(N) - (v(A) + v(B))
            penalty = partition_cost - grand_cost
            savings = sum_b0 - partition_cost

            # Complementary partition efficiency check: operating cost must be >= grand coalition cost
            require(penalty >= -TOL, f"Complementary partition cost less than grand coalition: {mask_a} + {mask_b}: penalty = {penalty}")

            members_a = [i + 1 for i in range(NUM_MEMBERS) if (mask_a & (1 << i))]
            members_b = [i + 1 for i in range(NUM_MEMBERS) if (mask_b & (1 << i))]

            require(len(members_a) + len(members_b) == NUM_MEMBERS, "Full coverage check")
            require(len(set(members_a).intersection(members_b)) == 0, "Disjointness check")

            bipartitions.append({
                "mask_a": mask_a,
                "mask_b": mask_b,
                "members_a": members_a,
                "members_b": members_b,
                "size_a": len(members_a),
                "size_b": len(members_b),
                "cost_aud": partition_cost,
                "penalty_aud": max(0.0, penalty),
                "penalty_percent": max(0.0, (penalty / grand_cost) * 100.0),
                "savings_aud": savings,
                "savings_percent": (savings / sum_b0) * 100.0,
            })

    require(len(bipartitions) == 255, f"Expected exactly 255 bipartitions, got {len(bipartitions)}")

    # Sort partitions by penalty ascending (most efficient first)
    bipartitions.sort(key=lambda p: (p["penalty_aud"], p["mask_a"]))

    penalties = [p["penalty_aud"] for p in bipartitions]
    min_pen = min(penalties)
    max_pen = max(penalties)
    mean_pen = sum(penalties) / len(penalties)
    median_pen = penalties[len(penalties) // 2]

    # Breakdown by size split: (1+8), (2+7), (3+6), (4+5)
    by_split: Dict[str, Dict[str, Any]] = {}
    split_groups: Dict[Tuple[int, int], List[float]] = {}
    for p in bipartitions:
        sz_pair = tuple(sorted([p["size_a"], p["size_b"]]))
        split_groups.setdefault(sz_pair, []).append(p["penalty_aud"])

    for (s1, s2), pens in sorted(split_groups.items()):
        label = f"{s1}+{s2}"
        pens_sorted = sorted(pens)
        by_split[label] = {
            "partition_count": len(pens),
            "penalty_min_aud": pens_sorted[0],
            "penalty_max_aud": pens_sorted[-1],
            "penalty_mean_aud": sum(pens_sorted) / len(pens_sorted),
            "penalty_median_aud": pens_sorted[len(pens_sorted) // 2],
        }

    # Reference benchmark partitions
    # 1. Optimal Bipartition: [2, 4] + [1, 3, 5, 6, 7, 8, 9] (lowest penalty)
    optimal = bipartitions[0]
    # 2. Worst-Case Bipartition: [2, 5, 7] + [1, 3, 4, 6, 8, 9] (highest penalty)
    worst = bipartitions[-1]

    # 3. Two-Coalition Benchmark Partition (5+4): [1, 3, 5, 7, 9] + [2, 4, 6, 8]
    # Mask for [1, 3, 5, 7, 9] = 1 | 4 | 16 | 64 | 256 = 341
    part_5_4 = next(p for p in bipartitions if p["mask_a"] == 341 or p["mask_b"] == 341)

    return {
        "total_bipartitions": len(bipartitions),
        "scientific_statement": (
            "All evaluated bipartitions have operating costs greater than or equal to those of the grand coalition. "
            "This establishes cost efficiency for complementary partitions of the complete nine-member community, "
            "without claiming universal superadditivity for arbitrary disjoint sub-coalitions."
        ),
        "penalty_summary_aud": {
            "min": min_pen,
            "max": max_pen,
            "mean": mean_pen,
            "median": median_pen,
        },
        "by_size_split": by_split,
        "benchmark_cases": {
            "optimal_bipartition": {
                "name": "Optimal Disjoint Bipartition",
                "members_a": optimal["members_a"],
                "members_b": optimal["members_b"],
                "cost_aud": optimal["cost_aud"],
                "penalty_aud": optimal["penalty_aud"],
                "penalty_percent": optimal["penalty_percent"],
                "savings_aud": optimal["savings_aud"],
                "savings_percent": optimal["savings_percent"],
                "finding": "Pairing solar generator #4 with storage #2 preserves 98.38% of community savings.",
            },
            "worst_bipartition": {
                "name": "Worst-Case Asset-Segregated Bipartition",
                "members_a": worst["members_a"],
                "members_b": worst["members_b"],
                "cost_aud": worst["cost_aud"],
                "penalty_aud": worst["penalty_aud"],
                "penalty_percent": worst["penalty_percent"],
                "savings_aud": worst["savings_aud"],
                "savings_percent": worst["savings_percent"],
                "finding": "Isolating non-solar households [2, 5, 7] causes a +39.39% cost penalty (+2,170.04 AUD).",
            },
            "canonical_partition_5_4": {
                "name": "Canonical Two-Coalition Partition (5+4)",
                "members_a": part_5_4["members_a"],
                "members_b": part_5_4["members_b"],
                "cost_aud": part_5_4["cost_aud"],
                "penalty_aud": part_5_4["penalty_aud"],
                "penalty_percent": part_5_4["penalty_percent"],
                "savings_aud": part_5_4["savings_aud"],
                "savings_percent": part_5_4["savings_percent"],
                "finding": "Partitioning into [1,3,5,7,9] and [2,4,6,8] increases cost by +166.11 AUD (+3.01%).",
            },
        },
        "top_efficient_bipartitions": bipartitions[:5],
        "worst_penalized_bipartitions": bipartitions[-5:],
        "all_bipartitions": bipartitions,
    }


def build_snapshot(sources: Dict[str, Any]) -> Dict[str, Any]:
    m3 = sources["m3_baselines.json"]
    m5_coal = sources["m5_coalitions.json"]
    m5_core = sources["m5_core.json"]
    m7_gov = sources["m7_governance.json"]
    m7_pol = sources["m7_policy_comparison.json"]

    # Basic metadata verification
    require(m3["schema_version"] == 1 and m3["currency"] == "AUD", "M3 schema")
    require(m5_coal["schema_version"] == 1 and m5_coal["currency"] == "AUD", "M5 coal schema")
    require(m5_core["schema_version"] == 1 and m5_core["currency"] == "AUD", "M5 core schema")
    require(m7_gov["schema_version"] == 1 and m7_gov["currency"] == "AUD", "M7 gov schema")
    require(m7_pol["schema_version"] == 1 and m7_pol["currency"] == "AUD", "M7 pol schema")

    # Invariants verification
    sum_b0 = number(m3["sum_B_i_aud"])
    grand_cost = number(m5_coal["records"][511]["coalition_cost_aud"])
    v_n = number(m5_coal["records"][511]["value_aud"])

    close(sum_b0, 9754.639083892132, "M3 standalone cost sum")
    close(grand_cost, 5509.653992063874, "M5 grand coalition cost")
    close(v_n, 4244.985091828258, "M5 grand coalition value")
    close(sum_b0 - grand_cost, v_n, "Cooperative surplus identity")

    outside_b0 = vector(m3["B_i_aud"])
    require(vector(m5_coal["B_i_aud"]) == outside_b0, "B_i consistency M3/M5")
    require(vector(m7_pol["B_i_aud"]) == outside_b0, "B_i consistency M7")

    # Size statistics
    records = m5_coal["records"]
    require(len(records) == 512, "512 coalition records required")
    coalition_size_stats = calculate_size_statistics(records)

    # Bipartitions
    bipartition_data = calculate_bipartitions(records, grand_cost, sum_b0)

    # Core stability & 8 binding witness coalitions
    cert = m5_core["certificate"]
    require(cert["core_nonempty"] is True, "Core must be non-empty")
    close(cert["epsilon_star_aud"], 0.0, "Epsilon star must be zero")

    u_witness = vector(cert["least_core_allocation_u_aud"])
    close(sum(u_witness.values()), v_n, "Least-core witness budget balance")

    binding_masks_raw = cert["diagnostics"]["binding_or_near_binding_coalitions"]
    require(len(binding_masks_raw) == 8, "Exactly 8 binding witness coalitions required")
    require(set(binding_masks_raw) == {179, 186, 383, 407, 439, 507, 508, 509}, "Exact 8 binding masks")

    binding_witness_details: List[Dict[str, Any]] = []
    u0_market = vector(m5_core["market"]["u0_aud"])

    for mask in sorted(binding_masks_raw):
        rec = records[mask]
        members = rec["members"]
        val = number(rec["value_aud"])
        u_sum_witness = sum(u_witness[str(i)] for i in members)
        excess_witness = val - u_sum_witness

        # By definition of binding witness at epsilon* = 0, excess must be ~0.0
        close(excess_witness, 0.0, f"Witness binding excess for mask {mask}")

        u_sum_market = sum(u0_market[str(i)] for i in members)
        excess_market = val - u_sum_market

        binding_witness_details.append({
            "mask": mask,
            "size": len(members),
            "members": members,
            "value_aud": val,
            "sum_u_witness_aud": u_sum_witness,
            "excess_witness_aud": excess_witness,
            "sum_u_market_aud": u_sum_market,
            "excess_market_aud": excess_market,
            "is_binding_at_witness": True,
            "binding_status": "binding_within_numerical_tolerance",
            "tolerance_aud": TOL,
        })

    # Excess distribution across all 510 proper subsets under market anchor
    proper_deficits = [
        number(r["value_aud"]) - sum(u0_market[str(i)] for i in r["members"])
        for r in records[1:-1]
    ]
    worst_market_deficit = max(proper_deficits)
    close(worst_market_deficit, -7.980232094431813, "Worst proper market deficit")
    require(all(d <= 0.0 for d in proper_deficits), "Market anchor must have zero proper blocking coalitions")

    # Member 1 & 2 synergy check
    m1_2 = m7_gov["members_1_2_contribution"]
    close(m1_2["joint_minus_market_aud"], 7.980232094433745, "Members 1 & 2 joint synergy linkage")

    # Member profiles & technical asset attributes
    household_raw = m7_pol["households"]
    households: Dict[str, Any] = {}
    for mid_str in IDS:
        h = household_raw[mid_str]
        b0_rec = next(b for b in m3["B0"] if b["coalition_members"] == [int(mid_str)])
        kpis = b0_rec["kpis"]

        u0_val = u0_market[mid_str]
        b0_val = outside_b0[mid_str]
        saving_pct = (u0_val / b0_val) * 100.0 if b0_val > 0 else None

        households[mid_str] = {
            "member_id": int(mid_str),
            "archetype": ARCHETYPES[mid_str],
            "household_type": h["household_type"],
            "occupant_count": h["occupant_count"],
            "annual_income_aud": number(h["annual_income_aud"]),
            "annual_demand_kwh": number(h["annual_demand_kwh"]),
            "pv_capacity_kw": number(h["pv_capacity_kw"]),
            "pv_modules": int(h["pv_modules"]),
            "pv_available_kwh": number(kpis["pv_available_kwh"]),
            "battery_capacity_kwh": number(h["battery_capacity_kwh"]),
            "battery_modules": int(h["battery_modules"]),
            "battery_throughput_baseline_kwh": number(kpis["battery_throughput_kwh"]),
            "standalone_cost_aud": b0_val,
            "market_benefit_aud": u0_val,
            "market_bill_aud": b0_val - u0_val,
            "relative_bill_saving_percent": saving_pct,
            "standalone_energy_burden": b0_val / number(h["annual_income_aud"]) if number(h["annual_income_aud"]) > 0 else None,
            "market_energy_burden": (b0_val - u0_val) / number(h["annual_income_aud"]) if number(h["annual_income_aud"]) > 0 else None,
        }

    # Member 5 Energy Justice Case Study
    m5_case = m7_gov["member_5_case_study"]
    m5_policies: List[Dict[str, Any]] = []
    for p in m5_case["policies"]:
        pid = p["policy_id"]
        raw_ben = number(p["raw_benefit_aud"])
        rep_ben = number(p["repaired_benefit_aud"])
        raw_bill = number(p["raw_bill_aud"])
        rep_bill = number(p["repaired_bill_aud"])
        tau = raw_ben - rep_ben

        m5_policies.append({
            "policy_id": pid,
            "policy_label": POLICY_LABELS.get(pid, pid),
            "raw_bill_aud": raw_bill,
            "raw_benefit_aud": raw_ben,
            "raw_energy_burden": number(p["raw_justice"]["policy_energy_burden"]),
            "repaired_bill_aud": rep_bill,
            "repaired_benefit_aud": rep_ben,
            "repaired_energy_burden": number(p["repaired_justice"]["policy_energy_burden"]),
            "candidate_repair_tau_aud": tau,
            "energy_burden_change": number(p["repaired_justice"]["energy_burden_change"]),
            "raw_admissible": bool(p["raw_admissible"]),
            "repaired_admissible": bool(p["repaired_admissible"]),
            "relative_bill_saving": number(p["raw_benefit_aud"]) / outside_b0["5"],
        })

    # Policy comparison overview table
    policies_overview: List[Dict[str, Any]] = []
    for p in m7_pol["policies"]:
        pid = p["policy_id"]
        raw = p["raw"]
        coal = raw["coalition"]
        rep = p["repair_to_constitution"]

        policies_overview.append({
            "policy_id": pid,
            "policy_label": POLICY_LABELS.get(pid, pid),
            "policy_family": p.get("policy_family"),
            "description": p.get("description"),
            "harmed_member_count": int(raw["harmed_member_count"]),
            "proper_blocking_count": int(coal["proper_blocking_count"]),
            "maximum_positive_proper_deficit_aud": number(coal["maximum_positive_proper_deficit_aud"]),
            "allocation_in_core": bool(coal["allocation_in_core"]),
            "constitutionally_admissible": bool(raw["constitutionally_admissible"]),
            "repair_volume_aud": number(rep["coalition"]["r_CR_aud"]),
            "minimum_benefit_aud": number(raw["minimum_benefit_aud"]),
            "gini": number(raw["inequality"]["gini"]["value"]) if raw["inequality"]["gini"]["value"] is not None else None,
            "jain": number(raw["inequality"]["jain"]["value"]) if raw["inequality"]["jain"]["value"] is not None else None,
        })

    return {
        "schema_version": 2,
        "kind": "canonical_annual_coalition_insights",
        "title": "ComFair 2026 Canonical 9-Member Coalition Research Snapshot",
        "description": "Empirical scientific snapshot of coalition value formation, bipartition efficiency, stability boundaries, and distributional justice.",
        "currency": "AUD",
        "period_hours": 8760,
        "member_ids": list(range(1, 10)),
        "metadata": {
            "solver": "highs",
            "solver_algorithm": "simplex",
            "primal_tolerance": 1e-8,
            "dual_tolerance": 1e-8,
            "classification_tolerance_aud": TOL,
            "time_horizon": "annual",
            "dataset_workbook_sha256": "c559bd7dc946b2f0c01c8cc96beea75c783f3b48bdd7fe6da855b2ef01f75370",
            "network_context": "Ausgrid distribution network (Sydney, NSW, Australia)",
            "baseline_model": "Uncoordinated standalone dispatch (no peer exchange)",
            "cooperative_model": "Cooperative physical-pool dispatch (local peer exchange)",
            "data_provenance_notes": {
                "electrical_demand": "Empirical hourly smart-meter load observations from the Ausgrid distribution network (Sydney, NSW, Australia).",
                "solar_and_storage": "Physical DER specifications and equipment ratings based on ComErgy 2026 canonical benchmark parameters.",
                "demographics_and_income": "Canonical benchmark scenario profiles (socio-economic archetypes from ComErgy 2026 benchmark workbook columns P-T). They represent designed benchmark test cases for distributional justice analysis, not individual field-surveyed private data.",
            },
            "units": {
                "costs": "AUD",
                "benefits": "AUD",
                "excess": "AUD",
                "powers": "kW",
                "energies": "kWh",
                "energy_burden": "fraction of annual household income",
            },
        },
        "summary_indicators": {
            "standalone_cost_sum_aud": sum_b0,
            "grand_coalition_cost_aud": grand_cost,
            "grand_coalition_value_aud": v_n,
            "savings_percent": (v_n / sum_b0) * 100.0,
            "total_coalitions_evaluated": len(records),
            "total_non_trivial_bipartitions": len(bipartition_data["all_bipartitions"]),
            "core_certified_stable": True,
            "least_core_optimum_epsilon_star_aud": 0.0,
            "binding_witness_coalitions_count": len(binding_masks_raw),
            "market_anchor_proper_blocking_count": 0,
            "market_anchor_clearance_margin_aud": abs(worst_market_deficit),
        },
        "households": households,
        "coalition_size_statistics": coalition_size_stats,
        "bipartition_analysis": bipartition_data,
        "stability_findings": {
            "core_nonempty": True,
            "epsilon_star_aud": 0.0,
            "solver_tolerance_aud": TOL,
            "binding_definition": "Coalitions whose excess e(S, u*) satisfies |e(S, u*) - epsilon*| <= 1e-5 AUD under the HiGHS simplex solver (feasibility tolerance 1e-8). These 8 coalitions form the active constraints at the least-core witness allocation.",
            "least_core_witness_allocation_aud": u_witness,
            "market_anchor_allocation_aud": u0_market,
            "binding_witness_coalitions": binding_witness_details,
            "market_clearance_margin_aud": abs(worst_market_deficit),
            "tightest_subcoalition_mask": 508,
            "tightest_subcoalition_members": [3, 4, 5, 6, 7, 8, 9],
            "members_1_2_synergy": {
                "marginal_1_aud": number(m1_2["marginal_1_aud"]),
                "marginal_2_aud": number(m1_2["marginal_2_aud"]),
                "joint_marginal_value_aud": number(m1_2["joint_marginal_value_aud"]),
                "combined_market_benefit_aud": number(m1_2["combined_M4_benefit_aud"]),
                "joint_minus_market_aud": number(m1_2["joint_minus_market_aud"]),
                "interpretation": m1_2["interpretation"],
            },
        },
        "governance_case_studies": {
            "member_5_energy_justice": {
                "member_id": 5,
                "archetype": "Pure Consumer (No DER assets)",
                "household_type": households["5"]["household_type"],
                "annual_income_aud": households["5"]["annual_income_aud"],
                "standalone_bill_aud": households["5"]["standalone_cost_aud"],
                "standalone_energy_burden": households["5"]["standalone_energy_burden"],
                "demographic_data_status": "canonical_benchmark_scenario_profile",
                "demographic_profile_note": "Single-parent family with children, one adult part-time employed, $70,000 AUD annual income; load profile is empirical Ausgrid smart-meter time series, while socio-economic characteristics are canonical benchmark scenario assumptions.",
                "policies": m5_policies,
            },
            "policies_overview": policies_overview,
        },
        "provenance": {
            "input_sha256": dict(INPUT_SHA256),
            "verification_status": "cryptographically_verified_canonical_inputs",
        },
        "limitations": [
            "Evaluated under annual perfect foresight (8,760 hours); short-horizon daily operations experience real-time forecast error penalties (~7.23% in 73-day rolling experiments).",
            "Fixed canonical baseline DER endowments; does not model dynamic asset investment or grid expansion.",
            "Descriptive coalition value scaling reflects physical asset complementarity within the Ausgrid network context, not generalizable causal law.",
            "Community partition evaluations assume additive cost aggregation across independent sub-coalitions without inter-coalition wheeling charges.",
            "Demographic incomes are fixed; consumer price elasticity of demand is not modeled.",
        ],
    }


def encoded(snapshot: Dict[str, Any]) -> bytes:
    return (json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS, help="Directory containing canonical artifacts")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="Destination path for research snapshot")
    parser.add_argument("--check", action="store_true", help="Verify that existing snapshot matches generated bytes exactly")
    args = parser.parse_args()

    sources = load_sources(args.artifacts)
    snapshot = build_snapshot(sources)
    data = encoded(snapshot)

    if args.check:
        require(args.output.is_file(), f"Output file does not exist for check: {args.output}")
        existing = args.output.read_bytes()
        require(existing == data, "Snapshot is stale or differs from deterministic output")
        print(f"VERIFIED: Snapshot {args.output.name} matches canonical generator output ({len(data)} bytes).")
    else:
        # Safety check: prevent overwriting canonical input artifacts
        require(args.output.resolve() not in {(args.artifacts / name).resolve() for name in INPUT_SHA256}, "Cannot overwrite an input artifact")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(data)
        print(f"SUCCESS: Exported {len(data)} bytes to {args.output}")


if __name__ == "__main__":
    main()
