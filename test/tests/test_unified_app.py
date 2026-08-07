"""Unit tests for scripts/unified_app.py model override logic."""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from unified_app import (
    AUTO_MODE,
    AUTO_MODEL,
    MODEL_OPTIONS,
    MODE_OPTIONS_BY_MODEL,
    UnifiedApp,
    _build_run_command,
)


class ModelConstantsTestCase(unittest.TestCase):

    def test_auto_model_is_first_option(self):
        self.assertEqual(MODEL_OPTIONS[0], AUTO_MODEL)

    def test_model_options_include_free_models(self):
        self.assertIn("opencode/deepseek-v4-flash-free", MODEL_OPTIONS)
        self.assertIn("opencode/ling-3.0-tiny-free", MODEL_OPTIONS)
        self.assertIn("opencode/big-pickle", MODEL_OPTIONS)


class ModeConstantsTestCase(unittest.TestCase):

    def test_auto_mode_default(self):
        self.assertEqual(AUTO_MODE, "Auto (Default)")

    def test_auto_model_modes_only_auto(self):
        self.assertEqual(MODE_OPTIONS_BY_MODEL[AUTO_MODEL], [AUTO_MODE])

    def test_deepseek_model_modes(self):
        self.assertEqual(
            MODE_OPTIONS_BY_MODEL["opencode/deepseek-v4-flash-free"],
            ["architect", "build", "analyze"],
        )

    def test_big_pickle_model_modes(self):
        self.assertEqual(
            MODE_OPTIONS_BY_MODEL["opencode/big-pickle"],
            ["plan", "build", "analyze"],
        )

    def test_ling_model_modes(self):
        self.assertEqual(
            MODE_OPTIONS_BY_MODEL["opencode/ling-3.0-tiny-free"],
            ["review", "compact"],
        )


class ResolveModeTestCase(unittest.TestCase):

    def setUp(self):
        self.app = UnifiedApp()

    def tearDown(self):
        self.app.destroy()

    def test_agent_mode_wins_over_master(self):
        self.app.mode_vars["m1"].set("architect")
        self.app.mode_vars["master"].set("compact")
        self.assertEqual(self.app._resolve_mode("m1"), "architect")

    def test_master_mode_when_agent_is_auto(self):
        self.app.mode_vars["master"].set("compact")
        self.assertEqual(self.app._resolve_mode("m1"), "compact")

    def test_returns_auto_mode_when_all_auto(self):
        self.assertEqual(self.app._resolve_mode("m1"), AUTO_MODE)

    def test_master_resolves_to_its_own_value(self):
        self.app.mode_vars["master"].set("review")
        self.assertEqual(self.app._resolve_mode("master"), "review")


class OnModelChangedTestCase(unittest.TestCase):

    def setUp(self):
        self.app = UnifiedApp()

    def tearDown(self):
        self.app.destroy()

    def test_default_mode_options_for_auto_model(self):
        self.assertEqual(
            tuple(self.app.mode_combos["m1"].cget("values")),
            (AUTO_MODE,),
        )

    def test_selecting_model_updates_mode_options_and_selection(self):
        self.app.model_vars["m1"].set("opencode/deepseek-v4-flash-free")
        self.app._on_model_changed("m1")
        self.assertEqual(
            tuple(self.app.mode_combos["m1"].cget("values")),
            ("architect", "build", "analyze"),
        )
        self.assertEqual(self.app.mode_vars["m1"].get(), "architect")


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

    def test_mode_replaces_default_agent(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "run tests", None, "architect"),
            ["opencode", "run", "--agent", "architect", "--auto", "run tests"],
        )

    def test_mode_replaces_agent_and_model_appended(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "run tests", "opencode/big-pickle", "architect"),
            [
                "opencode",
                "run",
                "--agent",
                "architect",
                "--auto",
                "-m",
                "opencode/big-pickle",
                "run tests",
            ],
        )

    def test_auto_mode_keeps_default_agent(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "run tests", None, AUTO_MODE),
            ["opencode", "run", "--agent", "tester", "--auto", "run tests"],
        )


if __name__ == "__main__":
    unittest.main()
