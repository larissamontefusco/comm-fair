"""Regression coverage for public coalition evaluation without private models."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from comfair.game.engine import enumerate_game
from comfair.game.evaluator import CoalitionEvaluation
from comfair.game.results import CoreCertificate
from comfair.game.run_game import build_artifacts


class TinyEvaluator:
    member_ids = (1, 2)
    cost_tolerance = 1e-7

    def __init__(self, community_model="cooperative_pool", price_metadata=None):
        self.community_model = community_model
        self.price_metadata = price_metadata or {}

    def cache_context(self):
        return {"source": "two-member-deterministic", "model": self.community_model}

    def standalone_evaluation(self, member_id):
        return CoalitionEvaluation(
            members=(member_id,),
            community_model="baseline",
            member_costs={member_id: float(member_id * 10)},
            total_final_member_cost=float(member_id * 10),
            solver={"name": "deterministic", "status": "ok"},
        )

    def coalition_evaluation(self, members):
        assert members == (1, 2)
        costs = {1: 10.0, 2: 20.0} if self.community_model == "baseline" else {1: 8.0, 2: 16.0}
        return CoalitionEvaluation(
            members=members,
            community_model=self.community_model,
            member_costs=costs,
            total_final_member_cost=sum(costs.values()),
            solver={"name": "deterministic", "status": "ok"},
            pricing_provenance=self.price_metadata,
        )


class TestPublicGameEvaluator(unittest.TestCase):
    def test_cooperative_pool_without_pricing_or_private_stages(self):
        evaluator = TinyEvaluator()
        records, runtime = enumerate_game(evaluator)
        self.assertEqual([r.mask for r in records], [0, 1, 2, 3])
        self.assertAlmostEqual(records[-1].value_aud, 6.0)
        self.assertEqual(records[-1].evaluation_stage, "external_evaluator")
        self.assertEqual(records[-1].pricing_provenance, {})
        self.assertEqual(runtime["new_coalition_record_count"], 3)
        self.assertEqual(records[-1].cost_source, "cooperative_pool")

    def test_baseline_has_no_cooperative_surplus(self):
        records, _ = enumerate_game(TinyEvaluator("baseline"))
        self.assertEqual(records[-1].value_aud, 0.0)
        self.assertEqual(records[-1].cost_source, "baseline_coalition")

    def test_new_artifact_metadata_uses_public_name(self):
        evaluator = TinyEvaluator()
        records, _ = enumerate_game(evaluator)
        certificate = CoreCertificate(
            core_nonempty=True,
            epsilon_star_aud=0.0,
            least_core_allocation_u_aud={1: 3.0, 2: 3.0},
            v_N_aud=6.0,
            diagnostics={},
            solver={"name": "test", "status": "ok"},
            core_tolerance_aud=1e-7,
        )
        with patch("comfair.game.run_game.solve_least_core", return_value=(certificate, 0.0)):
            coalitions, core, _ = build_artifacts(evaluator, records)
        self.assertEqual(coalitions["milestone"], "M5-coalition-game")
        self.assertEqual(core["milestone"], "M5-coalition-game")
        self.assertAlmostEqual(core["v_N"], 6.0)

    def test_optional_pricing_provenance_is_checked(self):
        valid = TinyEvaluator(price_metadata={"coalition_members": [1, 2], "source": "external"})
        records, _ = enumerate_game(valid)
        self.assertEqual(records[-1].pricing_provenance["source"], "external")
        invalid = TinyEvaluator(price_metadata={"coalition_members": [1], "source": "external"})
        with self.assertRaisesRegex(RuntimeError, "Pricing provenance coalition mismatch"):
            enumerate_game(invalid)

    def test_checkpoint_resume_preserves_records(self):
        with tempfile.TemporaryDirectory() as temp:
            checkpoint = Path(temp) / "checkpoint"
            first, initial_runtime = enumerate_game(TinyEvaluator(), checkpoint=checkpoint)
            second, resumed_runtime = enumerate_game(TinyEvaluator(), checkpoint=checkpoint, resume=True)
            self.assertEqual([r.to_dict() for r in first], [r.to_dict() for r in second])
            self.assertEqual(initial_runtime["new_coalition_record_count"], 3)
            self.assertEqual(resumed_runtime["new_coalition_record_count"], 0)
            self.assertEqual(resumed_runtime["checkpoint_reused_count"], 4)

    def test_wrong_coalition_model_is_rejected(self):
        class IncorrectModel(TinyEvaluator):
            def coalition_evaluation(self, members):
                from dataclasses import replace
                return replace(super().coalition_evaluation(members), community_model="baseline")
        with self.assertRaisesRegex(RuntimeError, "different community model"):
            enumerate_game(IncorrectModel())


if __name__ == "__main__":
    unittest.main()
