"""Unit tests for scripts/terminal_app.py (ZOVA retro terminal).

Baseline-zero contract: plain dispatch. Covers the run machinery (command
builder, sanitize, prune, hub wiring, StateTracker), the retro chrome (banner,
dir line, model bar, dashboard), and the slash-command layer. The
prompt_toolkit Application itself is only built lazily (needs a real console);
everything here runs headless.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import terminal_app
import scripts.core.state_tracker  # noqa: F401 — for mock patching
from terminal_app import (
    AGENTS,
    BANNER,
    RetroTerminalApp,
    RunHub,
    StateTracker,
    _loading_bar_fragments,
    _weighted_progress,
    _build_run_command,
    _classify_block,
    _console_fragments,
    _panel_groups,
    _run_header,
    _dashboard_fragments,
    _dir_line,
    _model_bar,
    _model_bar_fragments,
    _progress_bar_fragments,
    _sanitize_prompt,
    _estimate_token_percent,
    _working_fragments,
    build_help_text,
    parse_command,
    prune_prompt,
)


class ModelConstantsTestCase(unittest.TestCase):
    """The roster is seven plain agents."""

    def test_agents_are_seven(self):
        self.assertEqual(len(AGENTS), 7)
        tags = [tag for tag, _, _ in AGENTS]
        self.assertEqual(tags, [f"m{i}" for i in range(1, 8)])

    def test_no_mode_or_override_machinery_reexported(self):
        self.assertFalse(hasattr(terminal_app, "MODE_OPTIONS_BY_MODEL"))
        self.assertFalse(hasattr(terminal_app, "MODE_TO_AGENT"))
        self.assertFalse(hasattr(terminal_app, "AUTO_MODE"))
        self.assertFalse(hasattr(terminal_app, "build_overrides_table"))


class BuildRunCommandTestCase(unittest.TestCase):
    """The opencode run argv builder (plain dispatch, no mode)."""

    def test_no_model_keeps_auto_command_shape(self):
        self.assertEqual(
            _build_run_command("opencode", "max", "run tests", None),
            ["opencode", "run", "--agent", "max", "--auto", "run tests"],
        )

    def test_model_appends_dash_m_before_prompt(self):
        self.assertEqual(
            _build_run_command("opencode", "max", "run tests", "opencode/big-pickle"),
            [
                "opencode",
                "run",
                "--agent",
                "max",
                "--auto",
                "-m",
                "opencode/big-pickle",
                "run tests",
            ],
        )

    def test_dash_leading_prompt_is_guarded_with_double_dash(self):
        self.assertEqual(
            _build_run_command("opencode", "max", "- Peer-Assistance review", None),
            ["opencode", "run", "--agent", "max", "--auto", "--", "- Peer-Assistance review"],
        )

    def test_dash_leading_prompt_with_model_guard(self):
        self.assertEqual(
            _build_run_command("opencode", "max", "- upgrade system", "opencode/big-pickle"),
            [
                "opencode",
                "run",
                "--agent",
                "max",
                "--auto",
                "-m",
                "opencode/big-pickle",
                "--",
                "- upgrade system",
            ],
        )

    def test_control_characters_stripped_from_prompt(self):
        self.assertEqual(
            _build_run_command("opencode", "max", "run\x00\x07 tests", None),
            ["opencode", "run", "--agent", "max", "--auto", "run tests"],
        )

    def test_spaces_and_hyphens_inside_prompt_stay_single_element(self):
        cmd = _build_run_command("opencode", "max", "Fix 'Peer-Assistance' & run tests", None)
        self.assertEqual(cmd[-1], "Fix 'Peer-Assistance' & run tests")


class SanitizePromptTestCase(unittest.TestCase):

    def test_removes_control_chars_keeps_newlines(self):
        self.assertEqual(_sanitize_prompt("a\x00b\nc\x1ft"), "ab\nct")

    def test_strips_leading_whitespace(self):
        self.assertEqual(_sanitize_prompt("   hello"), "hello")


class PrunePromptTestCase(unittest.TestCase):

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(prune_prompt(""), "")

    def test_strips_ansi_sequences(self):
        result = prune_prompt("\x1b[31mred\x1b[0m \x1b[1mbold\x1b[0m text")
        self.assertEqual(result, "red bold text")

    def test_collapses_three_plus_blank_lines_to_one(self):
        self.assertEqual(prune_prompt("a\n\n\n\nb"), "a\n\nb")

    def test_dedupes_consecutive_identical_lines(self):
        self.assertEqual(prune_prompt("foo\nfoo\nbar\nbar\nbar\nbaz"), "foo\nbar\nbaz")

    def test_truncates_head_and_tail_with_marker(self):
        marker = "… [truncated] …"
        result = prune_prompt("A" * 1000, max_chars=200)
        self.assertIn(marker, result)
        head, _, tail = result.partition(marker)
        self.assertEqual(head, "A" * int(200 * 0.4))
        self.assertEqual(tail, "A" * (200 - int(200 * 0.4) - len(marker)))


# --------------------------------------------------------------------------- StateTracker


class StateTrackerTestCase(unittest.TestCase):
    """StateTracker reads/writes workspace-root state.md (sections format)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "state.md"
        self.tracker = StateTracker(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.tracker.load())

    def test_load_corrupt_returns_none(self):
        self.path.write_text("no sections here\n", encoding="utf-8")
        self.assertIsNone(self.tracker.load())

    def test_update_roundtrip(self):
        self.tracker.update(phase="running", last_run={"prompt": "hello", "started": "now"})
        data = self.tracker.load()
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"], {"prompt": "hello", "started": "now"})

    def test_record_run_sets_phase_and_last_run(self):
        self.tracker.record_run("prompt text", "2026-01-01T00:00:00")
        data = self.tracker.load()
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"], {"prompt": "prompt text", "started": "2026-01-01T00:00:00"})

    def test_record_run_writes_no_analyzer_line(self):
        self.tracker.record_run("hello", "2026-01-01T00:00:00")
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("analyzer:", text)

    def test_record_finish_appends_completed(self):
        self.tracker.record_finish("m1", True)
        self.tracker.record_finish("m2", False)
        data = self.tracker.load()
        self.assertIn("m1: ok", data["completed"])
        self.assertIn("m2: failed", data["completed"])

    def test_compression_evicts_old_completed(self):
        for i in range(25):
            self.tracker.record_finish(f"m{i}", True)
        data = self.tracker.load()
        self.assertLessEqual(len(data["completed"]), StateTracker.MAX_COMPLETED + 1)
        self.assertTrue(any("compressed" in entry for entry in data["completed"]))
        self.assertIn("m24: ok", data["completed"])

    def test_write_is_atomic_leaves_no_temp_files(self):
        self.tracker.update(phase="idle")
        leftovers = list(Path(self._tmp.name).glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_path_defaults_to_workspace_root_state_md(self):
        tracker = StateTracker()
        self.assertEqual(tracker.path, Path(terminal_app.PROJECT_ROOT) / "state.md")


# --------------------------------------------------------------------------- RunHub


class HubResolveTestCase(unittest.TestCase):
    """RunHub.resolve returns each agent's configured spec model (no modes)."""

    def setUp(self):
        self.hub = RunHub()

    def test_resolve_uses_spec_model_ignoring_overrides(self):
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "review"},
            "m1": {"model": "opencode/deepseek-v4-flash-free", "mode": "architect"},
        }
        from scripts.core.agents import AGENT_SPEC_BY_TAG

        model, mode = self.hub.resolve("m1", overrides)
        self.assertEqual(model, AGENT_SPEC_BY_TAG["m1"].model)
        self.assertEqual(mode, "auto")

    def test_master_resolves_none(self):
        model, mode = self.hub.resolve("master", {})
        self.assertIsNone(model)
        self.assertEqual(mode, "auto")

    def test_events_are_ansi_stripped_and_sequenced(self):
        self.hub.append_line("m1", "\x1b[0mclean\x1b[91m")
        self.hub.set_status("m1", "active")
        with self.hub.lock:
            events = list(self.hub.events)
        self.assertEqual(events[0]["text"], "clean")
        self.assertEqual(events[1]["text"], "active")
        self.assertEqual(events[1]["seq"], events[0]["seq"] + 1)


class _FakeProc:
    """Minimal stand-in for subprocess.Popen in _run_agent tests."""

    def __init__(self, lines=(), returncode=0):
        self.stdout = list(lines)
        self._rc = returncode

    def wait(self):
        return self._rc


class RunStateWiringTestCase(unittest.TestCase):
    """RunHub.run/_run_agent/terminate_all write state.md via STATE."""

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

    def test_run_records_pruned_prompt_in_state(self):
        raw = "line one\n\n\n\nline two"
        pruned = prune_prompt(raw)
        self.assertNotEqual(pruned, raw)
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run(raw, {})
        data = __import__("scripts.core.state_tracker", fromlist=["STATE"]).STATE.load()
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"]["prompt"], pruned)
        self.assertTrue(thread_mock.called)

    def test_run_keeps_original_in_master_dispatches_pruned(self):
        raw = "line one\n\n\n\nline two"
        pruned = prune_prompt(raw)
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run(raw, {})
        self.assertTrue(any(f"▶ {raw}" in line for line in self.hub.buffers["master"]))
        for call in thread_mock.call_args_list:
            self.assertEqual(call.kwargs["args"][2], pruned)

    def test_run_agents_filter_restricts_dispatch(self):
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run("task", {}, agents=["m1", "m4"])
        tags = {call.kwargs["args"][0] for call in thread_mock.call_args_list}
        self.assertEqual(tags, {"m1", "m4"})
        self.assertEqual(self.hub.running, 2)

    def test_run_enabled_agents_is_a_second_dispatch_safety_boundary(self):
        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run("task", {}, enabled_agents={"m1", "m4"})
        tags = {call.kwargs["args"][0] for call in thread_mock.call_args_list}
        self.assertEqual(tags, {"m1", "m4"})
        self.assertEqual(self.hub.running, 2)

    def test_run_resolves_per_tab_spec_model_for_threads(self):
        """Each worker thread receives its agent's configured spec model."""
        from scripts.core.agents import AGENT_SPEC_BY_AGENT

        with mock.patch("scripts.core.run_hub.threading.Thread") as thread_mock:
            self.hub.run("task", {}, agents=["m1", "m4"])
        args_by_tag = {
            call.kwargs["args"][0]: call.kwargs["args"] for call in thread_mock.call_args_list
        }
        self.assertEqual(args_by_tag["m1"][3], AGENT_SPEC_BY_AGENT["matthew"].model)
        self.assertEqual(args_by_tag["m4"][3], AGENT_SPEC_BY_AGENT["david"].model)

    def test_run_empty_prompt_returns_error(self):
        self.assertEqual(self.hub.run("   ", {}), "Prompt must not be empty.")
        self.assertEqual(self.hub.running, 0)

    def test_run_no_matching_agents_returns_error(self):
        self.assertEqual(self.hub.run("task", {}, agents=["m9"]), "No agents matched the /agents filter.")

    def test_run_agent_records_finish_ok(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch("scripts.core.run_hub.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m1", "matthew", "prompt", "opencode/deepseek-v4-flash-free")
        data = __import__("scripts.core.state_tracker", fromlist=["STATE"]).STATE.load()
        self.assertIn("m1: ok", data["completed"])

    def test_run_agent_records_finish_failed(self):
        proc = _FakeProc(returncode=3)
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch("scripts.core.run_hub.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m1", "matthew", "prompt", None)
        data = __import__("scripts.core.state_tracker", fromlist=["STATE"]).STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_run_agent_records_finish_failed_on_exception(self):
        with mock.patch("scripts.core.run_hub._opencode_command", return_value=None):
            self.hub._run_agent("m1", "matthew", "prompt", None)
        data = __import__("scripts.core.state_tracker", fromlist=["STATE"]).STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_run_agent_guards_option_like_prompt(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch("scripts.core.run_hub.subprocess.Popen", return_value=proc) as popen:
            self.hub._run_agent("m1", "matthew", "- Peer-Assistance handoff", None)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[-2:], ["--", "- Peer-Assistance handoff"])

    def test_cancelled_start_does_not_spawn_process(self):
        self.hub._cancelled_tags.add("m1")
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch("scripts.core.run_hub.subprocess.Popen") as popen:
            self.hub._run_agent("m1", "matthew", "prompt", None)
        popen.assert_not_called()
        self.assertNotIn("m1", self.hub.procs)

    def test_terminate_all_records_interruption(self):
        self.hub.terminate_all()
        data = __import__("scripts.core.state_tracker", fromlist=["STATE"]).STATE.load()
        self.assertTrue(any("interrupted" in entry for entry in data["restart_log"]))

    def test_insecure_tls_env_parsing(self):
        """ZOVA_ALLOW_INSECURE_TLS is strictly opt-in: only truthy values
        map to NODE_TLS_REJECT_UNAUTHORIZED=0 for the opencode subprocess."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(terminal_app._insecure_tls_env())
        for truthy in ("1", "TRUE", "Yes"):
            with mock.patch.dict(os.environ, {"ZOVA_ALLOW_INSECURE_TLS": truthy}, clear=True):
                env = terminal_app._insecure_tls_env()
                self.assertIsNotNone(env)
                self.assertEqual(env.get("NODE_TLS_REJECT_UNAUTHORIZED"), "0")
        with mock.patch.dict(os.environ, {"ZOVA_ALLOW_INSECURE_TLS": "0"}, clear=True):
            self.assertIsNone(terminal_app._insecure_tls_env())

    def test_run_agent_passes_tls_env_when_toggle_enabled(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch.dict(os.environ, {"ZOVA_ALLOW_INSECURE_TLS": "1"}), \
             mock.patch("scripts.core.run_hub.subprocess.Popen", return_value=proc) as popen:
            self.hub._run_agent("m1", "matthew", "prompt", None)
        env = popen.call_args.kwargs.get("env")
        self.assertIsNotNone(env)
        self.assertEqual(env.get("NODE_TLS_REJECT_UNAUTHORIZED"), "0")

    def test_run_agent_omits_tls_env_by_default(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("scripts.core.run_hub.subprocess.Popen", return_value=proc) as popen:
            self.hub._run_agent("m1", "matthew", "prompt", None)
        self.assertIsNone(popen.call_args.kwargs.get("env"))


# --------------------------------------------------------------------------- retro chrome


class BannerTestCase(unittest.TestCase):
    """The pixel-art banner spells ZOVA in block glyphs."""

    def test_banner_has_six_rows(self):
        self.assertEqual(len(BANNER), 6)

    def test_banner_rows_are_equal_width(self):
        self.assertEqual(len({len(row) for row in BANNER}), 1)

    def test_banner_spells_zova(self):
        self.assertEqual(BANNER[0],
                         "████████╗ ████████╗ ██╗   ██╗ ████████╗")
        self.assertEqual(BANNER[5],
                         "╚═══════╝ ╚═══════╝   ╚═══╝   ╚═╝   ╚═╝")


class StrictPaletteTestCase(unittest.TestCase):
    """The UI uses exactly the four spec colors (no rainbow themes)."""

    def test_palette_matches_git_inspired_spec(self):
        self.assertEqual(terminal_app.BLACK, "#0d1117")   # charcoal background
        self.assertEqual(terminal_app.GREY, "#c9d1d9")    # general text/logs
        self.assertEqual(terminal_app.WHITE, "#ffffff")   # panels and controls
        self.assertEqual(terminal_app.ORANGE, "#f85149")  # tab outlines
        self.assertNotIn("#39ff14", terminal_app.NEON)

    def test_no_legacy_rainbow_constants(self):
        for name in ("TAG_COLORS", "NEON_BRIGHT", "NEON_DIM", "AMBER", "RED", "BOX"):
            self.assertFalse(hasattr(terminal_app, name), f"legacy {name} must be gone")

    def test_status_symbols_use_only_git_palette_colors(self):
        allowed = {terminal_app.GREY, terminal_app.ORANGE, terminal_app.WHITE}
        for _symbol, color in terminal_app.STATUS_SYMBOL.values():
            self.assertIn(color, allowed)

    def test_tag_style_uses_live_header_accent_class(self):
        self.assertEqual(terminal_app._tag_style("m4"), f"bold {terminal_app.GREY}")

    def test_console_error_lines_keep_general_grey_and_panel_white(self):
        frags = terminal_app._console_fragments([("master", "ERROR: boom"), ("m4", "ok line")])
        styles = [style for style, _ in frags]
        self.assertTrue(any("retro.console" in s for s in styles))
        self.assertTrue(any("retro.panel.content" in s for s in styles))


class ProgressRenderTestCase(unittest.TestCase):
    """Per-agent progress bars, animation, token usage, and input styling."""

    def test_progress_bar_contains_percentage_inside_bar(self):
        joined = "".join(text for _style, text in _progress_bar_fragments(45))
        self.assertIn("45%", joined)
        self.assertTrue(joined.startswith("["))
        self.assertTrue(joined.endswith("]"))

    def test_working_label_chases_and_changes_with_time(self):
        first = _working_fragments(0.0)
        second = _working_fragments(0.1)
        self.assertEqual("".join(text for _style, text in first), "working...")
        self.assertEqual("".join(text for _style, text in second), "working...")
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len({style for style, _text in first}), 3)

    def test_active_agent_uses_one_unified_loading_bar(self):
        frags = _loading_bar_fragments(
            {"m4": terminal_app.STATUS_ACTIVE},
            {"m4": 45},
            {"m4": 32},
            current_tab="m4",
            now=0.0,
            width=100,
        )
        joined = "".join(text for _style, text, *rest in frags)
        self.assertIn("LOADING │ M4 David", joined)
        self.assertIn("45%", joined)
        self.assertIn("working...", joined)
        self.assertIn("Token: 32% Used", joined)
        self.assertEqual(joined.count("LOADING │"), 1)

    def test_master_loading_bar_aggregates_weighted_active_tasks(self):
        statuses = {"m1": terminal_app.STATUS_ACTIVE, "m4": terminal_app.STATUS_ACTIVE}
        progress = {"m1": 20, "m4": 80}
        weights = {"m1": 1.0, "m4": 3.0}
        self.assertEqual(_weighted_progress(statuses, progress, ["m1", "m4"], weights), 65)
        joined = "".join(
            text for _style, text, *rest in _loading_bar_fragments(
                statuses, progress, {"m1": 10, "m4": 50}, "master",
                session_tags={"m1", "m4"}, weights=weights, now=0.0, width=120,
            )
        )
        self.assertIn("MASTER / ALL AGENTS", joined)
        self.assertIn("65%", joined)
        self.assertIn("Token: 40% Used", joined)

    def test_token_estimate_is_bounded(self):
        self.assertEqual(_estimate_token_percent("a" * (8192 * 4 // 2), []), 50)
        self.assertEqual(_estimate_token_percent("a" * (8192 * 4 * 10), []), 100)
        self.assertEqual(_estimate_token_percent("", []), 0)

    def test_input_style_is_bright_white(self):
        app = RetroTerminalApp()
        style = app._style_dict["retro.input"]
        self.assertIn(f"fg:{terminal_app.WHITE}", style)
        self.assertIn("bold", style)

    def test_tabs_controls_and_framing_use_requested_colors(self):
        app = RetroTerminalApp()
        self.assertIn(f"fg:{terminal_app.WHITE}", app._style_dict["retro.box"])
        self.assertIn(f"fg:{terminal_app.ORANGE}", app._style_dict["retro.tab.active"])
        self.assertIn(f"fg:{terminal_app.WHITE}", app._style_dict["retro.control"])
        self.assertIn(f"fg:{terminal_app.WHITE}", app._style_dict["retro.panel.content"])

    def test_only_one_loading_window_is_constructed(self):
        app = RetroTerminalApp()
        self.assertTrue(hasattr(app, "loading_window"))
        self.assertFalse(hasattr(app, "progress_window"))
        children = app.layout_root.content.children
        self.assertIs(children[-1], app.prompt_box)
        self.assertIs(children[-3], app.loading_window)

    def test_layout_has_spacer_windows(self):
        app = RetroTerminalApp()
        children = app.layout_root.content.children
        self.assertEqual(len(children), 10)
        from prompt_toolkit.layout import Window
        spacer_count = sum(1 for c in children
                          if isinstance(c, Window) and c.height == 1)
        self.assertGreaterEqual(spacer_count, 3)

    def test_lower_panel_dimensions_are_expanded(self):
        self.assertGreaterEqual(terminal_app.INPUT_MIN_LINES, 2)
        self.assertGreater(terminal_app.INPUT_MAX_LINES, 8)
        self.assertGreaterEqual(terminal_app.CONSOLE_MIN_LINES, 4)
        self.assertGreater(terminal_app.CONSOLE_PREFERRED_LINES, terminal_app.CONSOLE_MIN_LINES)


class ChromeRenderTestCase(unittest.TestCase):
    """dir line, model bar, dashboard, console fragments."""

    def test_dir_line_contains_path(self):
        text = _dir_line(Path("tmp") / "workspace")
        self.assertIn("workspace", text)
        self.assertTrue(text.startswith("▶ DIR:"))

    def test_model_bar_reports_model_target_running(self):
        bar = _model_bar("master", ["m1", "m4"])
        self.assertIn("AI MODEL", bar)
        self.assertIn("TARGET m1,m4", bar)
        self.assertIn("RUN 0/7", bar)
        self.assertNotIn("▍MODE", bar)

    def test_model_bar_auto_target_all(self):
        bar = _model_bar("master", None)
        self.assertIn("AI MODEL auto", bar)
        self.assertIn("TARGET all", bar)

    def test_model_bar_controls_are_mouse_aware(self):
        controls = []
        fragments = _model_bar_fragments(
            "master", None,
            lambda kind, _event: controls.append(kind),
        )
        actionable = [fragment for fragment in fragments if len(fragment) == 3]
        self.assertEqual(len(actionable), 2)
        for fragment in actionable:
            fragment[2](mock.Mock())
        self.assertEqual(controls, ["tab", "target"])
        labels = "".join(fragment[1] for fragment in fragments)
        self.assertGreaterEqual(labels.count("⟦"), 2)
        self.assertGreaterEqual(labels.count("⟧"), 2)

    def test_dashboard_has_all_seven_agents(self):
        frags = _dashboard_fragments({})
        joined = "".join(text for _, text in frags)
        for tag, name, _ in AGENTS:
            self.assertIn(tag.upper(), joined)
            self.assertIn(name, joined)

    def test_dashboard_maps_statuses(self):
        frags = _dashboard_fragments({"m1": "thinking", "m2": "error", "m3": "active"})
        joined = "".join(text for _, text in frags)
        self.assertIn("✕", joined)
        self.assertIn("●", joined)

    def test_dashboard_renders_plain_label_without_role(self):
        frags = _dashboard_fragments({}, "m3")
        joined = "".join(text for _, text in frags)
        self.assertIn("⟦● M1: Matthew⟧", joined)
        self.assertNotIn("[Architect]", joined)
        self.assertIn("M3", joined)
        self.assertIn("class:retro.tab.active", " ".join(style for style, _text in frags))

    def test_dashboard_can_attach_mouse_handlers_to_each_tab(self):
        handlers = []
        frags = _dashboard_fragments({}, "master", lambda tag, event: handlers.append(tag))
        self.assertEqual(len(frags), 8)
        self.assertTrue(all(len(fragment) == 3 for fragment in frags))
        for fragment in frags:
            fragment[2](mock.Mock())
        self.assertEqual(handlers, ["master", "m1", "m2", "m3", "m4", "m5", "m6", "m7"])

    def test_console_fragments_include_tag_and_text(self):
        frags = _console_fragments([("m4", "hello retro")])
        joined = "".join(text for _, text in frags)
        self.assertIn("[m4]", joined)
        self.assertIn("hello retro", joined)

    def test_help_text_documents_plain_commands(self):
        help_text = build_help_text()
        for cmd in ("/help", "/cd", "/tab", "/status", "/clear", "/stop", "/theme", "/quit"):
            self.assertIn(cmd, help_text)
        # Removed machinery must not be advertised.
        for gone in ("/mode", "/settings", "/plan", "/swarm", "/evolve", "/archive", "/audit", "/prompt"):
            self.assertNotIn(gone, help_text)


# --------------------------------------------------------------------------- slash commands


class ParseCommandTestCase(unittest.TestCase):

    def test_plain_text_is_not_a_command(self):
        self.assertIsNone(parse_command("build me a thing"))

    def test_slash_command_splits_name_and_arg(self):
        self.assertEqual(parse_command("/cd /tmp/x"), ("cd", "/tmp/x"))

    def test_command_without_arg(self):
        self.assertEqual(parse_command("/status"), ("status", ""))

    def test_command_case_insensitive(self):
        self.assertEqual(parse_command("/HELP now"), ("help", "now"))


class SlashCommandTestCase(unittest.TestCase):
    """The command handlers behind the interactive prompt."""

    def setUp(self):
        self.app = RetroTerminalApp()

    def test_cd_shows_current_dir_without_arg(self):
        self.assertIn("DIR:", self.app._cmd_cd(""))

    def test_cd_rejects_missing_directory(self):
        reply = self.app._cmd_cd("/definitely/not/here/xyz")
        self.assertIn("ERROR", reply)

    def test_cd_changes_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            reply = self.app._cmd_cd(tmp)
        self.assertIn("DIR changed", reply)

    def test_status_reports_model_and_running(self):
        status = self.app._cmd_status("")
        self.assertIn("MODEL:", status)
        self.assertIn("RUN:", status)
        self.assertNotIn("MODE:", status)

    def test_clear_resets_console_and_hub(self):
        self.app._echo("some line")
        self.app._cmd_clear("")
        self.assertEqual(self.app.console_lines, [])
        self.assertEqual(self.hub_buffers_clear(), [])

    def hub_buffers_clear(self):
        return self.app.hub.buffers["master"]

    def test_stop_terminates_all(self):
        reply = self.app._cmd_stop("")
        self.assertIn("stopped", reply)
        self.assertEqual(self.app.hub.running, 0)

    def test_theme_shows_current(self):
        reply = self.app._cmd_theme("")
        self.assertIn("THEME:", reply)
        self.assertIn("classic", reply)

    def test_theme_switches_and_errors(self):
        self.assertIn("changed", self.app._cmd_theme("opencode"))
        self.assertEqual(self.app._active_theme_name, "opencode")
        self.assertIn("ERROR", self.app._cmd_theme("nope"))

    def test_unknown_command_is_reported(self):
        self.app._handle_input("/frobnicate")
        last = self.app.console_lines[-1][1]
        self.assertIn("unknown command", last)

    def test_removed_commands_are_unknown(self):
        for cmd in ("/mode", "/settings", "/plan", "/swarm", "/evolve", "/audit", "/archive"):
            self.app.console_lines = []
            self.app._handle_input(cmd)
            last = self.app.console_lines[-1][1]
            self.assertIn("unknown command", last, cmd)

    def test_plain_input_dispatches_to_hub(self):
        with mock.patch.object(self.app.hub, "run", return_value=None) as run:
            self.app._handle_input("do the thing")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "do the thing")

    def test_empty_input_is_ignored(self):
        with mock.patch.object(self.app.hub, "run") as run:
            self.app._handle_input("   ")
        run.assert_not_called()

    def test_all_agents_start_idle(self):
        self.assertEqual(
            {tag: self.app.hub.statuses[tag] for tag, _name, _agent in AGENTS},
            {tag: terminal_app.STATUS_IDLE for tag, _name, _agent in AGENTS},
        )

    def test_no_settings_modal_surface(self):
        self.assertFalse(hasattr(self.app, "settings"))
        self.assertFalse(hasattr(self.app, "overrides"))
        self.assertFalse(hasattr(self.app, "system_prompts"))
        self.assertFalse(hasattr(self.app, "agents_filter"))


class TabbedLayoutTestCase(unittest.TestCase):
    """The unified window has a MASTER tab + one tab per agent, and tasks
    dispatch to the active tab's agent only."""

    def setUp(self):
        self.app = RetroTerminalApp()

    def test_default_tab_is_master(self):
        self.assertEqual(self.app.current_tab, "master")

    def test_tab_lines_has_master_plus_seven_agents(self):
        self.assertEqual(
            list(self.app.tab_lines.keys()),
            ["master", "m1", "m2", "m3", "m4", "m5", "m6", "m7"],
        )

    def test_set_tab_switches_and_ignores_unknown(self):
        self.app.set_tab("m4")
        self.assertEqual(self.app.current_tab, "m4")
        self.app.set_tab("m9")  # unknown tag is ignored
        self.assertEqual(self.app.current_tab, "m4")

    def test_next_prev_tab_cycles(self):
        self.assertEqual(self.app._next_tab_tag(), "m1")
        self.app.set_tab("m7")
        self.assertEqual(self.app._next_tab_tag(), "master")
        self.assertEqual(self.app._prev_tab_tag(), "m6")

    def test_cmd_tab_shows_switches_and_errors(self):
        self.assertIn("TAB: master", self.app._cmd_tab(""))
        self.assertIn("TAB: m2", self.app._cmd_tab("m2"))
        self.assertEqual(self.app.current_tab, "m2")
        self.assertIn("TAB: m3", self.app._cmd_tab("next"))
        self.assertIn("TAB: m2", self.app._cmd_tab("prev"))
        self.assertIn("ERROR", self.app._cmd_tab("m9"))

    def test_task_on_agent_tab_dispatches_to_that_agent_only(self):
        self.app.set_tab("m4")
        with mock.patch.object(self.app.hub, "run", return_value=None) as run:
            self.app._handle_input("build the widget")
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs.get("agents"), ["m4"])

    def test_task_on_master_tab_dispatches_to_all(self):
        with mock.patch.object(self.app.hub, "run", return_value=None) as run:
            self.app._handle_input("build everything")
        run.assert_called_once()
        self.assertIsNone(run.call_args.kwargs.get("agents"))

    def test_drain_routes_lines_to_agent_tab_and_master(self):
        self.app.hub.append_line("m4", "backend says hi")
        self.app.hub.append_line("master", "master note")
        self.app._drain()
        texts = [text for _, text in self.app.console_lines]
        self.assertIn("backend says hi", texts)
        self.assertIn("master note", texts)
        tab_texts = [text for _, text in self.app.tab_lines["m4"]]
        self.assertIn("backend says hi", tab_texts)
        self.assertNotIn("master note", tab_texts)

    def test_active_tab_console_renders_own_lines(self):
        self.app.set_tab("m4")
        self.app.hub.append_line("m4", "only backend")
        self.app._drain()
        joined = "".join(text for _, text in self.app._console_fragments())
        self.assertIn("only backend", joined)

    def test_echo_lands_in_active_tab_and_master(self):
        self.app.set_tab("m1")
        self.app._echo("▸ hello")
        self.assertTrue(any("▸ hello" in text for _, text in self.app.console_lines))
        self.assertTrue(any("▸ hello" in text for _, text in self.app.tab_lines["m1"]))

    def test_model_bar_shows_active_tab(self):
        bar = _model_bar("m4")
        self.assertIn("TAB M4", bar)
        self.assertIn("TARGET m4", bar)

    def test_mouse_left_click_switches_tabs(self):
        from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType, Point

        event = MouseEvent(Point(x=0, y=0), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset())
        self.app._handle_tab_mouse("m4", event)
        self.assertEqual(self.app.current_tab, "m4")

    def test_mouse_non_left_click_does_not_switch_tabs(self):
        from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType, Point

        event = MouseEvent(Point(x=0, y=0), MouseEventType.MOUSE_UP, MouseButton.RIGHT, frozenset())
        self.app._handle_tab_mouse("m4", event)
        self.assertEqual(self.app.current_tab, "master")


class CleanLinePrefixTestCase(unittest.TestCase):
    """Log lines carry exactly one agent tag — no double prefixes."""

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

    def test_console_fragments_single_agent_tag(self):
        joined = "".join(text for _, text in _console_fragments([("m4", "hello retro")]))
        self.assertIn("[m4] hello retro", joined)
        self.assertNotIn("[m4] [m4", joined)

    def test_master_chrome_lines_have_no_prefix(self):
        joined = "".join(
            text for _, text in _console_fragments([("master", "▸ build a widget")])
        )
        self.assertNotIn("[master]", joined)
        self.assertTrue(joined.startswith("▸"))

    def test_error_line_keeps_single_tag_and_marker(self):
        joined = "".join(
            text for _, text in _console_fragments([("m4", "ERROR: boom")])
        )
        self.assertIn("[m4] ERROR: boom", joined)
        self.assertNotIn("[m4] [m4", joined)

    def test_run_agent_streams_lines_without_embedded_tag(self):
        proc = _FakeProc(lines=["hello from opencode", "second line"], returncode=0)
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch("scripts.core.run_hub.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "prompt", None)
        self.assertEqual(
            self.hub.buffers["m4"], ["hello from opencode", "second line"]
        )

    def test_run_agent_error_has_no_embedded_tag(self):
        proc = _FakeProc(returncode=3)
        with mock.patch("scripts.core.run_hub._opencode_command", return_value="opencode"), \
             mock.patch("scripts.core.run_hub.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "prompt", None)
        err_lines = [e["text"] for e in self.hub.events if e["kind"] == "error"]
        self.assertIn("exit code 3", err_lines[-1])

    def test_drain_renders_clean_prefixed_lines(self):
        app = RetroTerminalApp()
        app.hub.append_line("m4", "backend says hi")
        app.hub.append_line("master", "▶ prompt")
        app._drain()
        joined = "".join(text for _, text in app._console_fragments())
        self.assertIn("[m4] backend says hi", joined)
        self.assertNotIn("[m4] [m4", joined)
        self.assertIn("▶ prompt", joined)
        self.assertNotIn("[master]", joined)


class StructuredPanelTestCase(unittest.TestCase):
    """Categorized panels are shared by MASTER and every M1..M7 tab."""

    def test_classifies_thinking_todo_and_execution(self):
        self.assertEqual(_classify_block("Thinking:"), ("thinking", "thinking"))
        self.assertEqual(_classify_block("- [ ] add tests"), ("todo", "todo"))
        self.assertEqual(_classify_block("- [x] add tests"), ("todo", "todo"))
        self.assertEqual(_classify_block("FILE: scripts/terminal_app.py"), ("execution", "execution"))

    def test_thinking_and_todo_states_are_scoped_per_agent(self):
        groups = _panel_groups([
            ("m1", "Thinking:"),
            ("m2", "ordinary output"),
            ("m1", "reasoning continues"),
            ("m1", "TODO:"),
            ("m1", "- [ ] write tests"),
        ])
        keys = [key for key, _lines in groups]
        self.assertEqual(keys, ["m1:thinking", "m2:execution", "m1:thinking", "m1:todo"])

    def test_dynamic_panel_border_fits_requested_width(self):
        for width in (24, 40, 80):
            for kind in (terminal_app.BLOCK_THINKING, terminal_app.BLOCK_TODO, terminal_app.BLOCK_EXECUTION):
                _style, opening = terminal_app._panel_border(kind, True, width)
                _style, closing = terminal_app._panel_border(kind, False, width)
                self.assertEqual(len(opening.splitlines()[0]), width)
                self.assertEqual(len(closing.splitlines()[0]), width)

    def test_each_panel_has_category_border_and_content(self):
        frags = _console_fragments([
            ("m1", "Thinking:"),
            ("m1", "TODO:"),
            ("m1", "COMMAND: pytest"),
        ])
        joined = "".join(text for _style, text in frags)
        for label in ("THINKING", "TODO / TASKS", "EXECUTION / CODE"):
            self.assertIn(label, joined)
        self.assertGreaterEqual(joined.count("╭─"), 3)
        self.assertGreaterEqual(joined.count("╯"), 3)

    def test_run_header_is_a_visible_boundary(self):
        header = _run_header("edit the widget", "M4")
        self.assertTrue(header.startswith("──── RUN M4:"))
        self.assertIn(header, "".join(text for _style, text in _console_fragments([("m4", header)])))

    def test_scrolled_rendering_inherits_hidden_block_state(self):
        history = [("m4", "Thinking:"), ("m4", "reasoning continues"), ("m4", "final visible thought")]
        visible = history[-1:]
        initial = terminal_app._block_states(history[:-1])
        joined = "".join(text for _style, text in _console_fragments(visible, prefix=False, initial_states=initial))
        self.assertIn("THINKING", joined)
        self.assertNotIn("EXECUTION / CODE", joined)

    def test_all_agent_tabs_use_the_same_panel_markup(self):
        source = [("m4", "TODO:"), ("m4", "- [ ] change file")]
        expected = "".join(text for _style, text in _console_fragments(source, prefix=False))
        app = RetroTerminalApp()
        app.hub.events.clear()
        for tag, _name, _agent in AGENTS:
            app.tab_lines[tag] = [(tag, "TODO:"), (tag, "- [ ] change file")]
            app.set_tab(tag)
            rendered = "".join(text for _style, text in app._console_fragments())
            self.assertEqual(rendered, expected)


class EscAbortTestCase(unittest.TestCase):
    """Esc/Ctrl+G abort flow (per-tab and master cascade)."""

    def setUp(self):
        self.app = RetroTerminalApp()

    def test_esc_when_nothing_running_is_quiet(self):
        self.app.hub.running = 0
        self.app._handle_esc()
        last = self.app.console_lines[-1][1]
        self.assertIn("No agents are currently running", last)

    def test_first_esc_shows_warning_second_aborts(self):
        self.app.hub.running = 2
        self.app.set_tab("m4")
        self.app._handle_esc()
        self.assertIsNotNone(self.app._esc_pending_tag)
        self.assertTrue(any("ABORT M4" in text for _, text in self.app.console_lines))
        with mock.patch.object(self.app.hub, "terminate_agent", return_value=True):
            self.app._handle_esc()
        self.assertIsNone(self.app._esc_pending_tag)
        self.assertTrue(any("ABORTED: David" in text for _, text in self.app.console_lines))

    def test_master_esc_warning_mentions_all(self):
        self.app.hub.running = 2
        self.app.set_tab("master")
        self.app._handle_esc()
        self.assertTrue(any("ABORT ALL AGENTS" in text for _, text in self.app.console_lines))

    def test_master_double_esc_terminates_all(self):
        self.app.hub.running = 2
        self.app.set_tab("master")
        with mock.patch.object(self.app.hub, "terminate_all") as terminate_all:
            self.app._handle_esc()
            self.app._handle_esc()
        terminate_all.assert_called_once()

    def test_timeout_expires_pending_confirm(self):
        self.app.hub.running = 1
        self.app.set_tab("m4")  # per-tab abort path (master would call terminate_all)
        self.app._handle_esc()
        self.app._esc_pending_time = time.monotonic() - 10
        with mock.patch.object(self.app.hub, "terminate_agent", return_value=True) as ta:
            self.app._handle_esc()
        ta.assert_not_called()
        self.assertIsNotNone(self.app._esc_pending_tag)


if __name__ == "__main__":
    unittest.main()
