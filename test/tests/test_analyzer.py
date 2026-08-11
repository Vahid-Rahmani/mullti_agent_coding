"""Unit tests for scripts/core/analyzer.py — the Analyzer Core enforcer.

Covers the mandatory three-phase pipeline (requirements gathering, modular
decoupling, one-component-per-agent assignment), the derived category->agent
routing, the CLI contract, and the RunHub pre-dispatch injection.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import analyzer  # noqa: E402
from scripts.core.agents import MODE_TO_AGENT  # noqa: E402
from scripts.core.archivist import archivist_run  # noqa: E402
from scripts.core.run_hub import RunHub  # noqa: E402
from scripts.core.state_tracker import StateTracker  # noqa: E402


class CategoryAgentMappingTestCase(unittest.TestCase):
    """Phase 3 — assignment flows through the canonical routing matrix."""

    def test_every_category_routes_to_a_known_specialist(self):
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["architecture"], "matthew")
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["backend"], "alex")
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["frontend"], "sarah")
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["qa"], "david")
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["security"], "elena")
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["devops"], "max")
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["documentation"], "chloe")

    def test_mapping_derives_from_mode_routing(self):
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["backend"], MODE_TO_AGENT["backend"])
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["frontend"], MODE_TO_AGENT["frontend"])
        self.assertEqual(analyzer.CATEGORY_TO_AGENT["qa"], MODE_TO_AGENT["qa"])


class BuildMasterPlanTestCase(unittest.TestCase):
    """The three-phase pipeline."""

    def test_feature_prompt_is_applicable_and_assigns_agents(self):
        plan = analyzer.build_master_plan(
            "implement login auth backend api with frontend ui and unit tests"
        )
        self.assertTrue(plan.applicable)
        agents = set(plan.agents)
        self.assertIn("alex", agents)   # backend
        self.assertIn("sarah", agents)  # frontend
        self.assertIn("david", agents)  # qa

    def test_conversational_prompt_is_not_applicable(self):
        plan = analyzer.build_master_plan("hello there, thanks for your help")
        self.assertFalse(plan.applicable)
        self.assertEqual(plan.modules, [])
        self.assertFalse(plan.agents)
        self.assertEqual(plan.gaps, [])

    def test_one_module_per_agent(self):
        plan = analyzer.build_master_plan("refactor backend api and add tests")
        self.assertTrue(plan.applicable)
        self.assertEqual(len(plan.modules), len({m.agent for m in plan.modules}))

    def test_explicit_path_used_instead_of_suggestion(self):
        plan = analyzer.build_master_plan(
            "implement a backend api in scripts/core/auth.py and add tests"
        )
        self.assertTrue(plan.applicable)
        module = next(m for m in plan.modules if m.category == "backend")
        self.assertEqual(module.path, "scripts/core/auth.py")

    def test_suggested_paths_are_decoupled_by_concern(self):
        plan = analyzer.build_master_plan("implement login backend and frontend ui")
        by_category = {m.category: m.path for m in plan.modules}
        self.assertTrue(by_category["backend"].startswith("core/"))
        self.assertTrue(by_category["frontend"].startswith("ui/"))

    def test_gaps_reported_for_ambiguous_prompt(self):
        plan = analyzer.build_master_plan("build it")
        self.assertTrue(plan.applicable)  # "build" -> devops signal
        self.assertTrue(plan.gaps)
        self.assertTrue(any("terse" in gap for gap in plan.gaps))

    def test_to_text_contains_phases_and_assignments(self):
        plan = analyzer.build_master_plan("implement login backend and frontend ui")
        text = plan.to_text()
        self.assertIn("PHASE 1", text)
        self.assertIn("PHASE 2", text)
        self.assertIn("PHASE 3", text)
        self.assertIn("alex", text)
        self.assertIn("sarah", text)

    def test_archivist_entries_are_module_mappings(self):
        plan = analyzer.build_master_plan("implement login backend api")
        entries = plan.archivist_entries()
        self.assertTrue(entries)
        self.assertTrue(all("module " in e and " -> " in e for e in entries))

    def test_summary_line_reports_modules(self):
        plan = analyzer.build_master_plan("implement login backend and frontend")
        self.assertIn("[ANALYZER] master plan:", plan.summary_line())
        idle = analyzer.build_master_plan("hi")
        self.assertIn("no structural signal", idle.summary_line())

    def test_as_dict_serializes(self):
        plan = analyzer.build_master_plan("implement login backend api")
        data = plan.as_dict()
        self.assertEqual(data["applicable"], True)
        self.assertTrue(data["modules"])
        self.assertIn("agent", data["modules"][0])

    def test_short_keywords_do_not_fire_inside_unrelated_words(self):
        # "rapid" contains "api", "capital" contains "api", "build" contains
        # "ui" — word-boundary anchoring must keep these out of the plan.
        for prompt in ("make it rapid", "discuss the capital budget"):
            plan = analyzer.build_master_plan(prompt)
            self.assertFalse(plan.applicable, prompt)

    def test_plural_forms_still_match(self):
        plan = analyzer.build_master_plan("expose rest apis and run the tests")
        self.assertTrue(plan.applicable)
        self.assertIn("alex", set(plan.agents))    # "apis" -> backend
        self.assertIn("david", set(plan.agents))   # "tests" -> qa

    def test_version_tokens_are_not_treated_as_paths(self):
        plan = analyzer.build_master_plan("upgrade to python 3.12 and run tests")
        self.assertTrue(plan.applicable)
        self.assertTrue(plan.modules)
        self.assertTrue(all("/" in m.path for m in plan.modules))
        self.assertTrue(all(not m.path.endswith("3.12") for m in plan.modules))

    def test_missing_workspace_is_reported_as_gap(self):
        plan = analyzer.build_master_plan(
            "implement login backend api",
            workspace=Path(tempfile.mkdtemp()) / "does-not-exist",
        )
        self.assertTrue(plan.applicable)
        self.assertTrue(any("workspace" in gap for gap in plan.gaps))

    def test_absolute_path_is_reported_as_gap(self):
        plan = analyzer.build_master_plan(
            "implement backend api at C:/Users/me/app/main.py and add tests",
        )
        self.assertTrue(plan.applicable)
        self.assertTrue(any("absolute" in gap for gap in plan.gaps))

    def test_component_labels_strip_category_noise(self):
        plan = analyzer.build_master_plan("implement login backend api")
        backend = next(m for m in plan.modules if m.category == "backend")
        self.assertEqual(backend.component, "login backend")
        self.assertNotIn("api", backend.component)

    def test_category_only_prompt_gets_clean_label(self):
        # "implement backend" must yield "backend", never "backend backend".
        plan = analyzer.build_master_plan("implement backend")
        self.assertEqual(plan.modules[0].component, "backend")
        docs = analyzer.build_master_plan("implement docs")
        self.assertEqual(docs.modules[0].component, "docs")

    def test_version_like_filename_is_kept(self):
        plan = analyzer.build_master_plan("refactor 2.5_api.py and add tests")
        self.assertTrue(plan.applicable)
        self.assertEqual(plan.modules[0].path, "2.5_api.py")

    def test_url_is_not_treated_as_file_path(self):
        plan = analyzer.build_master_plan("fetch data from http://example.com/app.py")
        self.assertTrue(plan.applicable)
        self.assertTrue(all(not m.path.startswith("http") for m in plan.modules))

    def test_ci_does_not_fire_inside_city(self):
        plan = analyzer.build_master_plan("implement the city council backend")
        self.assertTrue(plan.applicable)
        self.assertIn("alex", set(plan.agents))  # "backend" signal intact
        self.assertNotIn("max", set(plan.agents))  # "ci" inside "city" must not fire


class ArchivistHandoffTestCase(unittest.TestCase):
    """Phase 4 — the module map is dispatched to the Obsidian Archivist."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name)

    def test_plan_module_map_is_persisted_by_archivist(self):
        plan = analyzer.build_master_plan(
            "implement login backend api and frontend ui",
        )
        self.assertTrue(plan.applicable)
        result = archivist_run(
            prompt=plan.prompt, workspace=self.workspace, plan=plan,
        )
        self.assertTrue(result["ok"])
        self.assertIn("analyzer plan", result["summary"])
        note = Path(result["sync"]["note_path"])
        self.assertTrue(note.exists())
        body = note.read_text(encoding="utf-8", errors="replace")
        for module in plan.modules:
            self.assertIn(module.component, body)
        self.assertIn(" -> ", body)  # module -> agent mapping

    def test_no_plan_means_no_module_entries(self):
        result = archivist_run(
            prompt="just chatting about the weather", workspace=self.workspace,
        )
        self.assertTrue(result["ok"])
        self.assertNotIn("analyzer plan", result["summary"])
        note = Path(result["sync"]["note_path"])
        body = note.read_text(encoding="utf-8", errors="replace")
        self.assertNotIn("module ", body)


class AnalyzerCliTestCase(unittest.TestCase):
    """python -m scripts.core.analyzer contract."""

    def _capture(self, argv):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = analyzer._cli(argv)
        return code, buf.getvalue(), err.getvalue()

    def test_cli_prints_plan(self):
        code, out, _ = self._capture(["implement login backend api and tests"])
        self.assertEqual(code, 0)
        self.assertIn("MASTER PLAN", out)
        self.assertIn("alex", out)

    def test_cli_json(self):
        code, out, _ = self._capture(["--json", "implement login backend"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["applicable"])
        self.assertTrue(data["modules"])

    def test_cli_requires_prompt(self):
        code, _out, _err = self._capture([])
        self.assertEqual(code, 2)

    def test_cli_conversational_prompt(self):
        code, out, _ = self._capture(["hi there"])
        self.assertEqual(code, 0)
        self.assertIn("no structural signal", out)


class RunHubAnalyzerTestCase(unittest.TestCase):
    """The analyzer is wired into RunHub.run as the pre-dispatch phase."""

    def setUp(self):
        import scripts.core.state_tracker

        self._orig_state = scripts.core.state_tracker.STATE
        self._tmp = tempfile.TemporaryDirectory()
        scripts.core.state_tracker.STATE = StateTracker(path=Path(self._tmp.name) / "state.md")
        self.hub = RunHub()

    def tearDown(self):
        import scripts.core.state_tracker

        scripts.core.state_tracker.STATE = self._orig_state
        self._tmp.cleanup()

    def test_structural_prompt_injects_master_plan_into_dispatch(self):
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run("implement login backend api and add unit tests", {})
        self.assertTrue(thread_mock.called)
        for call in thread_mock.call_args_list:
            prompt = call.kwargs["args"][2]
            self.assertIn("MASTER PLAN — Analyzer Core", prompt)
            self.assertIn("[USER TASK]", prompt)
        self.assertIsNotNone(self.hub.last_plan)
        self.assertTrue(self.hub.last_plan.applicable)

    def test_conversational_prompt_dispatched_unchanged(self):
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run("hello there", {})
        for call in thread_mock.call_args_list:
            self.assertEqual(call.kwargs["args"][2], "hello there")
        self.assertIsNotNone(self.hub.last_plan)
        self.assertFalse(self.hub.last_plan.applicable)

    def test_analyze_param_can_disable_injection(self):
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run("implement login backend api", {}, analyze=False)
        for call in thread_mock.call_args_list:
            self.assertEqual(call.kwargs["args"][2], "implement login backend api")

    def test_specialized_prompt_keeps_plan_between_headers(self):
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run(
                "implement login backend api",
                {},
                system_prompts={"master": "act as a security reviewer"},
            )
        for call in thread_mock.call_args_list:
            prompt = call.kwargs["args"][2]
            self.assertIn("[SPECIALIZED SYSTEM PROMPT]", prompt)
            self.assertIn("MASTER PLAN — Analyzer Core", prompt)
            self.assertIn("[USER TASK]", prompt)

    def test_master_console_shows_analyzer_summary(self):
        with mock.patch("scripts.core.run_hub.threading.Thread"):
            self.hub.run("implement login backend api", {})
        joined = "\n".join(self.hub.buffers["master"])
        self.assertIn("[ANALYZER] master plan:", joined)

    def _state_data(self):
        import scripts.core.state_tracker

        return scripts.core.state_tracker.STATE.load()

    def test_structural_run_records_analyzer_telemetry_in_state(self):
        with mock.patch("scripts.core.run_hub.threading.Thread"):
            self.hub.run("implement login backend api and add unit tests", {})
        analyzer = self._state_data()["last_run"]["analyzer"]
        self.assertEqual(analyzer["modules"], 2)
        self.assertEqual(sorted(analyzer["agents"]), ["alex", "david"])

    def test_conversational_run_records_no_analyzer_telemetry(self):
        with mock.patch("scripts.core.run_hub.threading.Thread"):
            self.hub.run("hello there", {})
        self.assertNotIn("analyzer", self._state_data()["last_run"])

    def test_analyze_false_records_no_analyzer_telemetry(self):
        with mock.patch("scripts.core.run_hub.threading.Thread"):
            self.hub.run("implement login backend api", {}, analyze=False)
        self.assertNotIn("analyzer", self._state_data()["last_run"])


if __name__ == "__main__":
    unittest.main()
