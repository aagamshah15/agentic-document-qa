"""
Unit & Integration Test Suite for Phase 6: Ground-Truth Evaluation Harness & Hardening.
Verifies the automated evaluation suite against shop_messy benchmark fixture,
scoring FK inference recall, trap avoidance, hygiene detection, and prompt injection immunity.
"""

import unittest
import tempfile
from experiments.evaluate_studio import run_studio_evaluations


class TestPhase6EvaluationHarness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_studio_ground_truth_benchmark_run(self):
        eval_report = run_studio_evaluations(target_dir=self.temp_dir.name)

        self.assertEqual(eval_report["benchmark"], "shop_messy")
        self.assertTrue(eval_report["all_passed"], f"Evaluation failed: {eval_report['suites']}")

        suites = eval_report["suites"]

        # 1. Cartography
        self.assertTrue(suites["cartography"]["passed"])
        self.assertEqual(suites["cartography"]["true_fks_found"], "3/3")
        self.assertEqual(suites["cartography"]["recall"], 1.0)
        self.assertTrue(suites["cartography"]["traps_avoided"])

        # 2. Hygiene
        self.assertTrue(suites["hygiene"]["passed"])
        self.assertTrue(suites["hygiene"]["orphans_detected"])
        self.assertTrue(suites["hygiene"]["mixed_dates_detected"])
        self.assertTrue(suites["hygiene"]["sentinels_detected"])

        # 3. Safety & Injection Defense
        self.assertTrue(suites["safety_injection"]["passed"])
        self.assertTrue(suites["safety_injection"]["raw_injection_blocked"])
        self.assertTrue(suites["safety_injection"]["cte_injection_blocked"])
        self.assertEqual(suites["safety_injection"]["unauthorized_writes"], 0)

        # 4. Shadow Migrations
        self.assertTrue(suites["shadow_migrations"]["passed"])
        self.assertEqual(suites["shadow_migrations"]["status"], "verified")
        self.assertTrue(suites["shadow_migrations"]["rollback_clean"])


if __name__ == "__main__":
    unittest.main()
