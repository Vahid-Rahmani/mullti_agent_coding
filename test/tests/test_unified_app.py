"""Unit tests for scripts/unified_app.py model override logic."""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from unified_app import AUTO_MODEL, MODEL_OPTIONS, UnifiedApp, _build_run_command


class ModelConstantsTestCase(unittest.TestCase):

    def test_auto_model_is_first_option(self):
        self.assertEqual(MODEL_OPTIONS[0], AUTO_MODEL)

    def test_model_options_include_free_models(self):
        self.assertIn("opencode/deepseek-v4-flash-free", MODEL_OPTIONS)
        self.assertIn("opencode/ling-3.0-tiny-free", MODEL_OPTIONS)
        self.assertIn("opencode/big-pickle", MODEL_OPTIONS)


class ResolveModelTestCase(unittest.TestCase):

    def setUp(self):
        self.app = UnifiedApp()

    def tearDown(self):
        self.app.destroy()

    def test_agent_override_wins_over_master(self):
        self.app.model_vars["m1"].set("opencode/big-pickle")
        self.app.model_vars["master"].set("opencode/ling-3.0-tiny-free")
        self.assertEqual(self.app._resolve_model("m1"), "opencode/big-pickle")

    def test_master_override_when_agent_is_auto(self):
        self.app.model_vars["master"].set("opencode/ling-3.0-tiny-free")
        self.assertEqual(self.app._resolve_model("m1"), "opencode/ling-3.0-tiny-free")

    def test_returns_none_when_all_auto(self):
        self.assertEqual(self.app._resolve_model("m1"), None)

    def test_master_resolves_to_its_own_value(self):
        self.app.model_vars["master"].set("opencode/deepseek-v4-flash-free")
        self.assertEqual(self.app._resolve_model("master"), "opencode/deepseek-v4-flash-free")


class BuildRunCommandTestCase(unittest.TestCase):

    def test_no_model_keeps_auto_command_shape(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "run tests", None),
            ["opencode", "run", "--agent", "tester", "--auto", "run tests"],
        )

    def test_model_appends_dash_m_before_prompt(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "run tests", "opencode/big-pickle"),
            [
                "opencode",
                "run",
                "--agent",
                "tester",
                "--auto",
                "-m",
                "opencode/big-pickle",
                "run tests",
            ],
        )


if __name__ == "__main__":
    unittest.main()
