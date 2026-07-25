from __future__ import annotations

import unittest

from scripts.studio_browser_smoke import build_smoke_contract


class StudioBrowserSmokeContractTests(unittest.TestCase):
    def test_contract_covers_alpha_viewports_and_core_scenarios(self):
        contract = build_smoke_contract()

        self.assertEqual(
            contract["viewports"],
            [
                {"name": "desktop", "width": 1440, "height": 900},
                {"name": "mobile", "width": 390, "height": 844},
            ],
        )
        self.assertEqual(
            [scenario["id"] for scenario in contract["scenarios"]],
            ["continue", "negative", "route", "correction"],
        )
        self.assertTrue(contract["scenarios"][0]["may_execute"])
        self.assertIn("禁止动作", contract["scenarios"][0]["source_map_includes"])
        self.assertFalse(contract["scenarios"][1]["may_execute"])
        self.assertTrue(contract["scenarios"][2]["may_execute"])
        self.assertTrue(contract["result_replaces_empty_state"])
        self.assertEqual(contract["generic_first_run_label"], "通用模式 · 无个人记忆")
        self.assertEqual(contract["required_public_terms"], [])


if __name__ == "__main__":
    unittest.main()
