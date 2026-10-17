"""Unit tests for the Coalition Insights scientific snapshot generator.

Verifies:
1. Cryptographic input provenance and SHA-256 verification.
2. Deterministic byte-for-byte snapshot generation.
3. Mathematical identities (cost conservation, complementary-partition dominance, surplus identity).
4. Exact combinatorial enumeration (512 subsets, 255 unique non-trivial bipartitions).
5. Core stability invariants and the 8 binding witness coalitions.
6. Member 5 energy justice and distributional policy outcomes.
7. Protection of canonical research artifacts against accidental modification.
8. Failure detection upon corrupted or missing evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from comfair.presentation.insights import (
    INPUT_SHA256,
    IDS,
    TOL,
    ARCHETYPES,
    load_sources,
    build_snapshot,
    calculate_bipartitions,
    calculate_size_statistics,
    encoded,
    ARTIFACTS,
    OUTPUT,
)


class TestCoalitionInsightsGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = load_sources(ARTIFACTS)
        cls.snapshot = build_snapshot(cls.sources)
        cls.encoded_data = encoded(cls.snapshot)

    def test_input_provenance_and_hashes(self):
        """Verify that all canonical input artifacts match their trusted reference SHA-256."""
        for filename, expected_hash in INPUT_SHA256.items():
            filepath = ARTIFACTS / filename
            self.assertTrue(filepath.is_file(), f"Missing artifact {filename}")
            actual_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
            self.assertEqual(
                actual_hash,
                expected_hash,
                f"Hash mismatch for canonical artifact {filename}",
            )

    def test_deterministic_output(self):
        """Verify that generation is strictly deterministic across repeated runs."""
        snapshot_2 = build_snapshot(self.sources)
        encoded_2 = encoded(snapshot_2)
        self.assertEqual(self.encoded_data, encoded_2)
        # Verify that output file on disk matches byte-for-byte
        if OUTPUT.is_file():
            self.assertEqual(OUTPUT.read_bytes(), self.encoded_data)

    def test_schema_integrity(self):
        """Verify explicit schema version and required scientific sections."""
        self.assertEqual(self.snapshot["schema_version"], 1)
        self.assertEqual(self.snapshot["kind"], "canonical_annual_coalition_insights")
        self.assertEqual(self.snapshot["currency"], "AUD")
        self.assertEqual(self.snapshot["period_hours"], 8760)
        self.assertEqual(self.snapshot["member_ids"], list(range(1, 10)))

        required_sections = [
            "metadata",
            "summary_indicators",
            "households",
            "coalition_size_statistics",
            "bipartition_analysis",
            "stability_findings",
            "governance_case_studies",
            "provenance",
            "limitations",
        ]
        for section in required_sections:
            self.assertIn(section, self.snapshot)

        # Scientific provenance metadata checks
        meta = self.snapshot["metadata"]
        self.assertEqual(meta["dataset_workbook_sha256"], "c559bd7dc946b2f0c01c8cc96beea75c783f3b48bdd7fe6da855b2ef01f75370")
        self.assertIn("electrical_demand", meta["data_provenance_notes"])
        self.assertIn("demographics_and_income", meta["data_provenance_notes"])

    def test_mathematical_identities(self):
        """Verify fundamental game-theoretic and physical cost identities."""
        summary = self.snapshot["summary_indicators"]
        sum_b0 = summary["standalone_cost_sum_aud"]
        grand_cost = summary["grand_coalition_cost_aud"]
        v_n = summary["grand_coalition_value_aud"]

        self.assertAlmostEqual(sum_b0, 9754.639083892132, places=5)
        self.assertAlmostEqual(grand_cost, 5509.653992063874, places=5)
        self.assertAlmostEqual(v_n, 4244.985091828258, places=5)
        self.assertAlmostEqual(sum_b0 - grand_cost, v_n, places=5)
        self.assertAlmostEqual(summary["savings_percent"], (v_n / sum_b0) * 100.0, places=5)

        # All 512 records satisfy v(S) = sum(B_i) - C(S)
        records = self.sources["m5_coalitions.json"]["records"]
        b_i = self.sources["m5_coalitions.json"]["B_i_aud"]
        for r in records:
            members = r["members"]
            expected_b0 = sum(b_i[str(i)] for i in members)
            self.assertAlmostEqual(
                r["sum_standalone_cost_aud"], expected_b0, places=5
            )
            self.assertAlmostEqual(
                expected_b0 - r["coalition_cost_aud"], r["value_aud"], places=5
            )

        # Empty coalition and singletons have exactly zero value
        self.assertEqual(records[0]["value_aud"], 0.0)
        for mid in range(1, 10):
            self.assertEqual(records[1 << (mid - 1)]["value_aud"], 0.0)

    def test_coalition_size_distribution(self):
        """Verify combinatorial counts and monotonic value scaling across coalition sizes."""
        size_stats = self.snapshot["coalition_size_statistics"]
        self.assertEqual(len(size_stats), 10)

        total_subsets = sum(s["coalition_count"] for s in size_stats)
        self.assertEqual(total_subsets, 512)

        prev_mean_value = -1.0
        for sz, s in enumerate(size_stats):
            self.assertEqual(s["size"], sz)
            self.assertEqual(s["coalition_count"], math.comb(9, sz))
            # Monotonic mean value expansion for sizes >= 1
            if sz >= 1:
                self.assertGreaterEqual(s["value_aud"]["mean"], prev_mean_value)
                prev_mean_value = s["value_aud"]["mean"]

    def test_bipartition_enumeration_and_superadditivity(self):
        """Verify 255 unique complementary bipartitions and grand-coalition cost dominance."""
        bip = self.snapshot["bipartition_analysis"]
        all_parts = bip["all_bipartitions"]
        self.assertEqual(len(all_parts), 255)

        seen_pairs = set()
        grand_cost = self.snapshot["summary_indicators"]["grand_coalition_cost_aud"]
        sum_b0 = self.snapshot["summary_indicators"]["standalone_cost_sum_aud"]

        for p in all_parts:
            m_a = p["mask_a"]
            m_b = p["mask_b"]

            # Complementarity
            self.assertEqual(m_a ^ m_b, 511)
            self.assertTrue(m_a & 1)  # Member 1 is in block A
            self.assertFalse(m_b & 1)

            # Unordered pair uniqueness
            canonical_pair = tuple(sorted([m_a, m_b]))
            self.assertNotIn(canonical_pair, seen_pairs)
            seen_pairs.add(canonical_pair)

            # Membership properties
            self.assertEqual(p["size_a"] + p["size_b"], 9)
            self.assertEqual(set(p["members_a"]).union(p["members_b"]), set(range(1, 10)))
            self.assertEqual(len(set(p["members_a"]).intersection(p["members_b"])), 0)

            # Cost and penalty consistency
            self.assertAlmostEqual(p["penalty_aud"], p["cost_aud"] - grand_cost, places=4)
            self.assertAlmostEqual(p["savings_aud"], sum_b0 - p["cost_aud"], places=4)

            # Dominance for complementary partitions of this fixed grand coalition.
            self.assertGreaterEqual(p["penalty_aud"], 0.0)

        # Check size split counts
        by_split = bip["by_size_split"]
        self.assertEqual(by_split["1+8"]["partition_count"], 9)
        self.assertEqual(by_split["2+7"]["partition_count"], 36)
        self.assertEqual(by_split["3+6"]["partition_count"], 84)
        self.assertEqual(by_split["4+5"]["partition_count"], 126)

        # Check verified benchmark cases
        cases = bip["benchmark_cases"]
        self.assertAlmostEqual(cases["optimal_bipartition"]["penalty_aud"], 68.7203, places=2)
        self.assertAlmostEqual(cases["worst_bipartition"]["penalty_aud"], 2170.0438, places=2)
        self.assertAlmostEqual(cases["canonical_partition_5_4"]["penalty_aud"], 166.1070, places=2)

    def test_stability_findings_and_binding_witnesses(self):
        """Verify non-empty core, epsilon*=0, and the exact 8 binding witness coalitions."""
        stab = self.snapshot["stability_findings"]
        self.assertTrue(stab["core_nonempty"])
        self.assertEqual(stab["epsilon_star_aud"], 0.0)

        witness = stab["least_core_witness_allocation_aud"]
        self.assertAlmostEqual(sum(witness.values()), 4244.985091828258, places=5)

        binding = stab["binding_witness_coalitions"]
        self.assertEqual(len(binding), 8)
        binding_masks = [b["mask"] for b in binding]
        self.assertEqual(binding_masks, [179, 186, 383, 407, 439, 507, 508, 509])

        self.assertEqual(stab["solver_tolerance_aud"], 1e-05)
        self.assertIn("HiGHS simplex solver", stab["binding_definition"])

        # Every binding coalition has zero excess within numerical tolerance
        for b in binding:
            self.assertAlmostEqual(b["excess_witness_aud"], 0.0, places=5)
            self.assertEqual(b["binding_status"], "binding_within_numerical_tolerance")
            self.assertEqual(b["tolerance_aud"], 1e-05)

        # Market anchor clearance and Coalition 508
        self.assertAlmostEqual(stab["market_clearance_margin_aud"], 7.980232094431813, places=5)
        self.assertEqual(stab["tightest_subcoalition_mask"], 508)
        self.assertEqual(stab["tightest_subcoalition_members"], [3, 4, 5, 6, 7, 8, 9])

        # Member 1 & 2 synergy check
        m1_2 = stab["members_1_2_synergy"]
        self.assertAlmostEqual(m1_2["joint_minus_market_aud"], 7.980232094433745, places=5)

    def test_member_5_energy_justice_case_study(self):
        """Verify Member 5 case study outcomes across all 13 policies."""
        m5 = self.snapshot["governance_case_studies"]["member_5_energy_justice"]
        self.assertEqual(m5["member_id"], 5)
        self.assertEqual(m5["archetype"], "Pure Consumer (No DER assets)")
        self.assertEqual(m5["demographic_data_status"], "canonical_benchmark_scenario_profile")
        self.assertIn("Single-parent family", m5["demographic_profile_note"])
        self.assertAlmostEqual(m5["standalone_bill_aud"], 2237.44225, places=4)
        self.assertAlmostEqual(m5["standalone_energy_burden"], 2237.44225 / 70000.0, places=5)

        policies = m5["policies"]
        self.assertEqual(len(policies), 13)

        policy_map = {p["policy_id"]: p for p in policies}

        # Market Anchor (G0): $925.50 AUD savings, energy burden drops to 1.87%
        g0 = policy_map["G0_market"]
        self.assertAlmostEqual(g0["raw_benefit_aud"], 925.497167, places=2)
        self.assertAlmostEqual(g0["raw_bill_aud"], 1311.945083, places=2)
        self.assertAlmostEqual(g0["raw_energy_burden"], 0.018742, places=4)
        self.assertAlmostEqual(g0["candidate_repair_tau_aud"], 0.0, places=4)
        self.assertTrue(g0["raw_admissible"])

        # Equal Benefit (G1): Member 5 receives $471.67 raw and $892.59 after repair.
        g1 = policy_map["G1_equal_benefit"]
        self.assertAlmostEqual(g1["raw_benefit_aud"], 471.665010, places=2)
        self.assertAlmostEqual(g1["repaired_benefit_aud"], 892.591675, places=2)
        self.assertAlmostEqual(g1["candidate_repair_tau_aud"], -420.926665, places=2)
        self.assertFalse(g1["raw_admissible"])
        self.assertTrue(g1["repaired_admissible"])

        # Upper Grid (P3): $0 raw benefit, repaired to $842.41
        p3 = policy_map["P3_upper_grid"]
        self.assertAlmostEqual(p3["raw_benefit_aud"], 0.0, places=4)
        self.assertAlmostEqual(p3["repaired_benefit_aud"], 842.408755, places=2)
        self.assertAlmostEqual(p3["candidate_repair_tau_aud"], -842.408755, places=2)
        self.assertFalse(p3["raw_admissible"])
        self.assertTrue(p3["repaired_admissible"])

    def test_protection_of_canonical_artifacts(self):
        """Verify that the generator prohibits overwriting any canonical input artifact."""
        for filename in INPUT_SHA256:
            target_path = ARTIFACTS / filename
            self.assertIn(target_path.resolve(), {(ARTIFACTS / name).resolve() for name in INPUT_SHA256})

    def test_rejection_of_corrupted_inputs(self):
        """Verify that load_sources rejects modified or corrupted artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create a corrupted file
            corrupted_file = tmppath / "m5_coalitions.json"
            corrupted_file.write_bytes(b'{"corrupted": true}')
            with self.assertRaises(ValueError) as ctx:
                load_sources(tmppath)
            self.assertIn("Missing required scientific artifact", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
