"""Unit tests for scripts/terminal_app.py (ZOVA retro terminal).

Covers the run machinery (command builder, sanitize, prune, hub wiring,
StateTracker), the retro chrome (banner, dir line, model bar, dashboard), and
the slash-command layer. The prompt_toolkit Application itself is only built
lazily (needs a real console); everything here runs headless.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import agent_logger
import obsidian_auditor
import prompt_logger
import terminal_app
from terminal_app import (
    AGENTS,
    AUTO_MODE,
    AUTO_MODEL,
    BANNER,
    IMMUTABLE_TAGS,
    M7_AUDIT_MODE,
    MODEL_OPTIONS,
    MODE_OPTIONS_BY_MODEL,
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
    _swarm_state,
    build_help_text,
    build_overrides_table,
    parse_command,
    prune_prompt,
    run_self_evolve,
    classify_intent,
    INTENT_TASK,
    INTENT_GREETING,
    INTENT_CASUAL,
    INTENT_QUESTION,
)


class ModelConstantsTestCase(unittest.TestCase):
    """Model/mode constants match the removed GUI's contract."""

    def test_auto_model_is_first_option(self):
        self.assertEqual(MODEL_OPTIONS[0], AUTO_MODEL)

    def test_model_options_include_free_models(self):
        self.assertIn("opencode/deepseek-v4-flash-free", MODEL_OPTIONS)
        self.assertIn("opencode/ling-3.0-tiny-free", MODEL_OPTIONS)
        self.assertIn("opencode/big-pickle", MODEL_OPTIONS)

    def test_model_options_include_ollama_local(self):
        self.assertIn("ollama/qwen2.5-coder:7b", MODEL_OPTIONS)

    def test_model_options_include_mulerouter(self):
        self.assertIn("mulerouter/gpt-5.5", MODEL_OPTIONS)
        self.assertIn("mulerouter/gpt-5.4-mini", MODEL_OPTIONS)
        self.assertIn("mulerouter/qwen3-max", MODEL_OPTIONS)
        self.assertIn("mulerouter/qwen3.7-max", MODEL_OPTIONS)

    def test_ollama_model_has_modes(self):
        modes = MODE_OPTIONS_BY_MODEL["ollama/qwen2.5-coder:7b"]
        self.assertIn("architect", modes)
        self.assertIn("build", modes)
        self.assertIn("test", modes)

    def test_mulerouter_models_have_modes(self):
        for model in ("mulerouter/gpt-5.5", "mulerouter/gpt-5.4-mini",
                      "mulerouter/qwen3-max", "mulerouter/qwen3.7-max"):
            modes = MODE_OPTIONS_BY_MODEL[model]
            self.assertIn("build", modes)
            self.assertIn("review", modes)

    def test_agents_are_seven(self):
        self.assertEqual(len(AGENTS), 7)
        tags = [tag for tag, _, _ in AGENTS]
        self.assertEqual(tags, [f"m{i}" for i in range(1, 8)])


class ModeConstantsTestCase(unittest.TestCase):

    def test_auto_mode_default(self):
        self.assertEqual(AUTO_MODE, "Auto (Default)")

    def test_auto_model_modes_only_auto(self):
        self.assertIn(AUTO_MODE, MODE_OPTIONS_BY_MODEL[AUTO_MODEL])

    def test_deepseek_model_modes(self):
        modes = MODE_OPTIONS_BY_MODEL["opencode/deepseek-v4-flash-free"]
        self.assertIn("architect", modes)
        self.assertIn("build", modes)
        self.assertIn("analyze", modes)
        self.assertIn("test", modes)
        self.assertIn("review", modes)

    def test_big_pickle_model_modes(self):
        modes = MODE_OPTIONS_BY_MODEL["opencode/big-pickle"]
        self.assertIn("analyze", modes)
        self.assertIn("plan", modes)
        self.assertIn("build", modes)
        self.assertIn("test", modes)
        self.assertIn("review", modes)
        self.assertIn("architect", modes)

    def test_ling_model_modes(self):
        modes = MODE_OPTIONS_BY_MODEL["opencode/ling-3.0-tiny-free"]
        self.assertIn("documentation-audit", modes)
        self.assertIn("review", modes)
        self.assertIn("compact", modes)
        self.assertIn("chloe", modes)
        self.assertIn("compaction", modes)


class BuildRunCommandTestCase(unittest.TestCase):
    """The opencode run argv builder (ported from the removed GUI)."""

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

    def test_mode_replaces_default_agent(self):
        self.assertEqual(
            _build_run_command("opencode", "max", "run tests", None, "architect"),
            ["opencode", "run", "--agent", "matthew", "--auto", "run tests"],
        )

    def test_auto_mode_keeps_default_agent(self):
        self.assertEqual(
            _build_run_command("opencode", "max", "run tests", None, AUTO_MODE),
            ["opencode", "run", "--agent", "max", "--auto", "run tests"],
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
    """RunHub.resolve mirrors the removed layers' override priority."""

    def setUp(self):
        self.hub = RunHub()

    def test_agent_override_wins_over_master(self):
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "review"},
            "m1": {"model": "opencode/deepseek-v4-flash-free", "mode": "architect"},
        }
        model, mode = self.hub.resolve("m1", overrides)
        self.assertEqual(model, "opencode/deepseek-v4-flash-free")
        self.assertEqual(mode, "architect")

    def test_master_override_when_agent_is_auto(self):
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "review"},
            "m1": {"model": AUTO_MODEL, "mode": AUTO_MODE},
        }
        model, mode = self.hub.resolve("m1", overrides)
        self.assertEqual(model, "opencode/big-pickle")
        self.assertEqual(mode, "review")

    def test_all_auto_resolves_none_and_auto_mode(self):
        overrides = {"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}}
        model, mode = self.hub.resolve("m1", overrides)
        self.assertIsNone(model)
        self.assertEqual(mode, AUTO_MODE)

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
        self._orig_state = terminal_app.STATE
        self._tmp = tempfile.TemporaryDirectory()
        terminal_app.STATE = StateTracker(path=Path(self._tmp.name) / "state.md")
        self.hub = RunHub()

    def tearDown(self):
        terminal_app.STATE = self._orig_state
        self._tmp.cleanup()

    def test_run_records_pruned_prompt_in_state(self):
        raw = "line one\n\n\n\nline two"
        pruned = prune_prompt(raw)
        self.assertNotEqual(pruned, raw)
        with mock.patch("terminal_app.threading.Thread") as thread_mock:
            self.hub.run(raw, {})
        data = terminal_app.STATE.load()
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"]["prompt"], pruned)
        self.assertTrue(thread_mock.called)

    def test_run_keeps_original_in_master_dispatches_pruned(self):
        raw = "line one\n\n\n\nline two"
        pruned = prune_prompt(raw)
        with mock.patch("terminal_app.threading.Thread") as thread_mock:
            self.hub.run(raw, {})
        self.assertTrue(any(f"▶ {raw}" in line for line in self.hub.buffers["master"]))
        for call in thread_mock.call_args_list:
            self.assertEqual(call.kwargs["args"][2], pruned)

    def test_run_agents_filter_restricts_dispatch(self):
        with mock.patch("terminal_app.threading.Thread") as thread_mock:
            self.hub.run("task", {}, agents=["m1", "m4"])
        tags = {call.kwargs["args"][0] for call in thread_mock.call_args_list}
        self.assertEqual(tags, {"m1", "m4"})
        self.assertEqual(self.hub.running, 2)

    def test_run_enabled_agents_is_a_second_dispatch_safety_boundary(self):
        with mock.patch("terminal_app.threading.Thread") as thread_mock:
            self.hub.run("task", {}, enabled_agents={"m1", "m4"})
        tags = {call.kwargs["args"][0] for call in thread_mock.call_args_list}
        self.assertEqual(tags, {"m1", "m4"})
        self.assertEqual(self.hub.running, 2)

    def test_run_resolves_per_tab_model_and_mode_for_threads(self):
        """Each worker thread receives its tab's resolved (model, mode):
        tab override > master override > auto."""
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "plan"},
            "m1": {"model": "opencode/deepseek-v4-flash-free", "mode": "architect"},
        }
        with mock.patch("terminal_app.threading.Thread") as thread_mock:
            self.hub.run("task", overrides, agents=["m1", "m4"])
        args_by_tag = {
            call.kwargs["args"][0]: call.kwargs["args"] for call in thread_mock.call_args_list
        }
        # m1 uses its own override; m4 inherits the master override
        self.assertEqual(args_by_tag["m1"][3], "opencode/deepseek-v4-flash-free")
        self.assertEqual(args_by_tag["m1"][4], "architect")
        self.assertEqual(args_by_tag["m4"][3], "opencode/big-pickle")
        self.assertEqual(args_by_tag["m4"][4], "plan")

    def test_run_empty_prompt_returns_error(self):
        self.assertEqual(self.hub.run("   ", {}), "Prompt must not be empty.")
        self.assertEqual(self.hub.running, 0)

    def test_run_no_matching_agents_returns_error(self):
        self.assertEqual(self.hub.run("task", {}, agents=["m9"]), "No agents matched the /agents filter.")

    def test_run_agent_records_finish_ok(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m1", "matthew", "prompt", None, None)
        data = terminal_app.STATE.load()
        self.assertIn("m1: ok", data["completed"])

    def test_run_agent_records_finish_failed(self):
        proc = _FakeProc(returncode=3)
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m1", "matthew", "prompt", None, None)
        data = terminal_app.STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_run_agent_records_finish_failed_on_exception(self):
        with mock.patch("terminal_app._opencode_command", return_value=None):
            self.hub._run_agent("m1", "matthew", "prompt", None, None)
        data = terminal_app.STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_run_agent_guards_option_like_prompt(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc) as popen:
            self.hub._run_agent(
                "m1", "matthew",
                "- Peer-Assistance handoff", None, None,
            )
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[-2:], ["--", "- Peer-Assistance handoff"])

    def test_cancelled_start_does_not_spawn_process(self):
        self.hub._cancelled_tags.add("m1")
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen") as popen:
            self.hub._run_agent("m1", "matthew", "prompt", None, None)
        popen.assert_not_called()
        self.assertNotIn("m1", self.hub.procs)

    def test_terminate_all_records_interruption(self):
        self.hub.terminate_all()
        data = terminal_app.STATE.load()
        self.assertTrue(any("interrupted" in entry for entry in data["restart_log"]))


# --------------------------------------------------------------------------- retro chrome


class BannerTestCase(unittest.TestCase):
    """The pixel-art banner spells ZOVA in block glyphs."""

    def test_banner_has_six_rows(self):
        self.assertEqual(len(BANNER), 6)

    def test_banner_rows_are_block_art(self):
        for row in BANNER:
            self.assertTrue(any(ch in row for ch in "█╗╝╔╚║═"))

    def test_banner_rows_are_equal_width(self):
        self.assertEqual(len({len(row) for row in BANNER}), 1)

    def test_banner_spells_zova(self):
        # The first row's column blocks spell ZOVA: Z(████████╗) O(████████╗) ...
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
        self.assertEqual(terminal_app._tag_style("m4"), "class:retro.header")

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

    def test_idle_active_tab_keeps_the_fixed_loading_slot_quiet(self):
        frags = _loading_bar_fragments(
            {tag: terminal_app.STATUS_IDLE for tag, _name, _agent in AGENTS},
            current_tab="m4",
            width=100,
        )
        joined = "".join(text for _style, text, *rest in frags)
        self.assertIn("LOADING │ M4 David", joined)
        self.assertIn("0%", joined)
        self.assertIn("idle", joined)
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

    def test_master_completion_retains_finished_task_weight(self):
        statuses = {"m1": terminal_app.STATUS_IDLE, "m4": terminal_app.STATUS_ACTIVE}
        progress = {"m1": 100, "m4": 50}
        self.assertEqual(_weighted_progress(statuses, progress, ["m1", "m4"]), 75)

    def test_completed_master_session_renders_inactive_zero_bar(self):
        statuses = {"m1": terminal_app.STATUS_IDLE, "m4": terminal_app.STATUS_IDLE}
        progress = {"m1": 100, "m4": 100}
        joined = "".join(
            text for _style, text, *rest in _loading_bar_fragments(
                statuses, progress, {}, "master", {"m1", "m4"}, now=0.0, width=100
            )
        )
        self.assertIn("0%", joined)
        self.assertIn("idle", joined)
        self.assertEqual(RunHub().aggregate_progress(), 0)

    def test_run_hub_exposes_thread_safe_master_aggregate(self):
        hub = RunHub()
        with hub.lock:
            hub.session_tags = {"m1", "m4"}
            hub.statuses["m1"] = terminal_app.STATUS_ACTIVE
            hub.statuses["m4"] = terminal_app.STATUS_ACTIVE
            hub.progress["m1"] = 25
            hub.progress["m4"] = 75
            hub.progress_weights = {"m1": 1.0, "m4": 3.0}
        self.assertEqual(hub.aggregate_progress(), 63)
        snapshot = hub.loading_snapshot("m4")
        self.assertEqual(snapshot["current_tab"], "m4")
        self.assertEqual(snapshot["session_tags"], {"m1", "m4"})

    def test_clear_drops_completed_session_telemetry(self):
        hub = RunHub()
        with hub.lock:
            hub.session_tags = {"m1"}
            hub.progress["m1"] = 100
        hub.clear()
        self.assertEqual(hub.session_tags, set())
        self.assertEqual(hub.aggregate_progress(), 0)
        self.assertTrue(all(hub.statuses[tag] == terminal_app.STATUS_IDLE for tag, _name, _agent in AGENTS))

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
        # Layout order: ... console, separator, loading, spacer, prompt_box.
        # prompt_box is last, loading_window is 3rd from last.
        self.assertIs(children[-1], app.prompt_box)
        self.assertIs(children[-3], app.loading_window)

    def test_layout_has_spacer_windows(self):
        """Spacer rows, separators, and viewport borders between layout sections."""
        app = RetroTerminalApp()
        children = app.layout_root.content.children
        # 12 children: banner, spacer, dir, spacer, tab, separator,
        # viewport_top, console, viewport_bottom, loading, spacer, prompt_box.
        self.assertEqual(len(children), 12)
        from prompt_toolkit.layout import Window
        spacer_count = sum(1 for c in children
                          if isinstance(c, Window) and c.height == 1)
        self.assertGreaterEqual(spacer_count, 7)  # 3 spacers + 2 separators + 2 viewport borders

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

    def test_model_bar_reports_model_mode_target_running(self):
        bar = _model_bar({"master": {"model": "opencode/big-pickle", "mode": "plan"}}, ["m1", "m4"])
        self.assertIn("AI MODEL opencode/big-pickle", bar)
        self.assertIn("MODE plan", bar)
        self.assertIn("TARGET m1,m4", bar)
        self.assertIn("RUN 0/7", bar)

    def test_model_bar_auto_target_all(self):
        bar = _model_bar({"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}}, None)
        self.assertIn("MODEL Auto", bar)
        self.assertIn("TARGET all", bar)

    def test_model_bar_controls_are_mouse_aware(self):
        controls = []
        fragments = _model_bar_fragments(
            {"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}},
            None,
            "master",
            lambda kind, _event: controls.append(kind),
        )
        actionable = [fragment for fragment in fragments if len(fragment) == 3]
        self.assertEqual(len(actionable), 4)
        for fragment in actionable:
            fragment[2](mock.Mock())
        self.assertEqual(controls, ["tab", "model", "mode", "target"])
        labels = "".join(fragment[1] for fragment in fragments)
        self.assertGreaterEqual(labels.count("⟦"), 4)
        self.assertGreaterEqual(labels.count("⟧"), 4)

    def test_dashboard_has_all_seven_agents(self):
        frags = _dashboard_fragments({})
        joined = "".join(text for _, text in frags)
        for tag, name, _ in AGENTS:
            self.assertIn(tag.upper(), joined)
            self.assertIn(name, joined)

    def test_dashboard_maps_statuses(self):
        frags = _dashboard_fragments({"m1": "thinking", "m2": "error", "m3": "active"})
        joined = "".join(text for _, text in frags)
        # activity is intentionally represented only by the unified bar;
        # tabs retain a neutral dot while error remains explicit.
        self.assertIn("✕", joined)
        self.assertIn("●", joined)

    def test_dashboard_renders_distinct_button_cells(self):
        frags = _dashboard_fragments({}, "m3")
        joined = "".join(text for _, text in frags)
        self.assertIn("⟦● M3: Sarah [Frontend]⟧", joined)
        self.assertIn("⟦● M1: Matthew [Architect]⟧", joined)
        self.assertIn("class:retro.tab.active", " ".join(style for style, _text in frags))

    def test_dashboard_can_attach_mouse_handlers_to_each_tab(self):
        handlers = []
        frags = _dashboard_fragments({}, "master", lambda tag, event: handlers.append(tag))
        self.assertEqual(len(frags), 8)
        self.assertTrue(all(len(fragment) == 3 for fragment in frags))
        for fragment in frags:
            fragment[2](mock.Mock())
        self.assertEqual(handlers, ["master", "m1", "m2", "m3", "m4", "m5", "m6", "m7"])

    def test_dashboard_identity_follows_mode_assignment(self):
        overrides = {
            "master": {"model": AUTO_MODEL, "mode": AUTO_MODE},
            "m1": {"model": AUTO_MODEL, "mode": "build"},
        }
        label = "".join(text for _style, text in _dashboard_fragments({}, overrides=overrides))
        self.assertIn("M1: Alex [Builder]", label)
        self.assertNotIn("M1: Matthew [Architect]", label)

    def test_console_fragments_include_tag_and_text(self):
        frags = _console_fragments([("m4", "hello retro")])
        joined = "".join(text for _, text in frags)
        self.assertIn("[m4]", joined)
        self.assertIn("hello retro", joined)

    def test_help_text_documents_commands(self):
        help_text = build_help_text()
        for cmd in ("/help", "/cd", "/model", "/mode", "/prompt", "/prompts",
                    "/agents", "/settings", "/clear", "/stop", "/swarm", "/evolve", "/quit"):
            self.assertIn(cmd, help_text)


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


class IntentClassifierTestCase(unittest.TestCase):
    """Non-task inputs are classified so Master handles them locally."""

    def test_greetings_detected(self):
        for text in ("hello", "hi", "Hey", "good morning", "hola"):
            self.assertEqual(classify_intent(text), INTENT_GREETING,
                             f"'{text}' should be greeting")

    def test_casual_detected(self):
        for text in ("thanks", "ok", "cool", "sure", "bye"):
            self.assertEqual(classify_intent(text), INTENT_CASUAL,
                             f"'{text}' should be casual")

    def test_questions_detected(self):
        for text in ("what can you do", "how does this work",
                      "who are you", "help"):
            self.assertEqual(classify_intent(text), INTENT_QUESTION,
                             f"'{text}' should be question")

    def test_coding_tasks_are_tasks(self):
        for text in ("refactor the auth module",
                      "fix bug in terminal_app.py",
                      "add unit tests for the router",
                      "implement a new REST endpoint"):
            self.assertEqual(classify_intent(text), INTENT_TASK,
                             f"'{text}' should be task")

    def test_short_single_word_is_casual(self):
        self.assertEqual(classify_intent("test"), INTENT_CASUAL)
        self.assertEqual(classify_intent("wow"), INTENT_CASUAL)

    def test_empty_input_is_casual(self):
        self.assertEqual(classify_intent(""), INTENT_CASUAL)
        self.assertEqual(classify_intent("  "), INTENT_CASUAL)


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

    def test_model_show_set_unknown(self):
        self.assertIn("MODEL:", self.app._cmd_model(""))
        self.assertEqual(self.app.menu_kind, "model")
        self.assertEqual(self.app.menu_options, MODEL_OPTIONS)
        self.assertIn("MODEL: opencode/big-pickle", self.app._cmd_model("opencode/big-pickle"))
        self.assertIn("ERROR", self.app._cmd_model("nope"))

    def test_mode_bare_opens_model_specific_menu(self):
        self.app._cmd_model("opencode/big-pickle")
        self.app._cmd_mode("")
        self.assertEqual(self.app.menu_kind, "mode")
        # Menu must contain the core modes for this model (expanded set).
        self.assertIn("plan", self.app.menu_options)
        self.assertIn("build", self.app.menu_options)
        self.assertIn("analyze", self.app.menu_options)
        self.assertIn("test", self.app.menu_options)

    def test_menu_selection_updates_model_mode_and_target(self):
        self.app.open_menu("model")
        self.app._select_menu_option("opencode/big-pickle")
        self.assertEqual(self.app.overrides["master"]["model"], "opencode/big-pickle")
        self.app.open_menu("mode")
        self.app._select_menu_option("plan")
        self.assertEqual(self.app.overrides["master"]["mode"], "plan")
        self.app.open_menu("target")
        self.app._select_menu_option("m4")
        self.assertEqual(self.app.agents_filter, ["m4"])
        self.app.open_menu("tab")
        self.app._select_menu_option("m3")
        self.assertEqual(self.app.current_tab, "m3")
        self.assertIsNone(self.app.menu_kind)

    def test_mouse_menu_is_anchored_and_clamped_to_trigger(self):
        from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType, Point

        self.app._screen_size = mock.Mock(return_value=(80, 24))
        event = MouseEvent(Point(x=70, y=20), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset())
        self.app._handle_control_mouse("model", event)
        self.assertEqual(self.app.menu_kind, "model")
        self.assertGreaterEqual(self.app.menu_left, 0)
        self.assertGreaterEqual(self.app.menu_top, 0)
        self.assertLessEqual(self.app.menu_left + self.app.menu_width, 80)
        self.assertLessEqual(self.app.menu_top + self.app.menu_height, 24)
        self.assertEqual(self.app.menu_float.left, self.app.menu_left)
        self.assertEqual(self.app.menu_float.top, self.app.menu_top)

    def test_clicking_outside_menu_closes_and_clears_options(self):
        from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType, Point

        self.app._screen_size = mock.Mock(return_value=(80, 24))
        self.app.open_menu("target", event=MouseEvent(
            Point(x=30, y=18), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset()
        ))
        self.assertEqual(self.app.menu_kind, "target")
        outside = MouseEvent(Point(x=0, y=0), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset())
        self.app._dismiss_mouse(outside)
        self.assertIsNone(self.app.menu_kind)
        self.assertEqual(self.app.menu_options, [])

    def test_menu_rows_are_closed_and_white_framed(self):
        self.app._screen_size = mock.Mock(return_value=(80, 24))
        self.app.open_menu("mode")
        rendered = "".join(text for _style, text, *rest in self.app._menu_fragments())
        rows = rendered.splitlines()
        self.assertTrue(rows[0].startswith("╭─"))
        self.assertTrue(rows[-1].startswith("╰"))
        self.assertTrue(all(len(row) == self.app.menu_width for row in rows))
        styles = [fragment[0] for fragment in self.app._menu_fragments()]
        self.assertTrue(any("retro.menu.border" in style for style in styles))

    def test_explicit_target_command_menu_applies_to_that_tab(self):
        self.app._cmd_model("m4")
        self.assertEqual(self.app.menu_target, "m4")
        self.app._select_menu_option("opencode/big-pickle")
        self.assertEqual(self.app.overrides["m4"]["model"], "opencode/big-pickle")
        self.assertEqual(self.app.overrides["master"]["model"], AUTO_MODEL)

    def test_mode_show_set_invalid(self):
        self.assertIn("MODE:", self.app._cmd_mode(""))
        self.app._cmd_model("opencode/big-pickle")
        self.assertIn("MODE: plan", self.app._cmd_mode("plan"))
        self.assertIn("ERROR", self.app._cmd_mode("zzz-invalid"))

    def test_agents_show_filter_all(self):
        self.assertIn("all", self.app._cmd_agents(""))
        self.assertIn("m1,m4", self.app._cmd_agents("m1,m4"))
        self.assertEqual(self.app.agents_filter, ["m1", "m4"])
        self.assertIn("all", self.app._cmd_agents("all"))
        self.assertIsNone(self.app.agents_filter)

    def test_agents_rejects_unknown_tags(self):
        self.assertIn("ERROR", self.app._cmd_agents("m9"))

    def test_status_reports_models_and_running(self):
        status = self.app._cmd_status("")
        self.assertIn("MODEL:", status)
        self.assertIn("RUN:", status)

    def test_all_agents_start_idle_and_prompts_off(self):
        self.assertEqual(
            {tag: self.app.hub.statuses[tag] for tag, _name, _agent in AGENTS},
            {tag: terminal_app.STATUS_IDLE for tag, _name, _agent in AGENTS},
        )
        self.assertTrue(all(not value for value in self.app.system_prompts.values()))

    def test_custom_specialized_prompt_lifecycle(self):
        self.assertIn("off", self.app._cmd_prompt("m4"))
        self.assertIn("configured", self.app._cmd_prompt("m4 review API contracts"))
        self.assertEqual(self.app.system_prompts["m4"], "review API contracts")
        self.assertIn("M4", self.app._cmd_prompts(""))
        self.assertIn("on", self.app._cmd_prompts(""))
        self.assertIn("cleared", self.app._cmd_prompt("m4 clear"))
        self.assertEqual(self.app.system_prompts["m4"], "")

    def test_swarm_command_handles_missing_state(self):
        reply = _swarm_state()
        self.assertIsInstance(reply, str)

    def test_unknown_command_is_reported(self):
        self.app._handle_input("/frobnicate")
        last = self.app.console_lines[-1][1]
        self.assertIn("unknown command", last)

    def test_plain_input_dispatches_to_hub(self):
        with mock.patch.object(self.app.hub, "run", return_value=None) as run:
            self.app._handle_input("do the thing")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "do the thing")

    def test_disabled_agent_is_not_used_by_manual_audit(self):
        self.app.enabled_agents.discard("m7")
        with mock.patch("terminal_app.threading.Thread") as thread_mock:
            reply = self.app._cmd_audit("")
        self.assertIn("disabled", reply)
        thread_mock.assert_not_called()

    def test_empty_input_is_ignored(self):
        with mock.patch.object(self.app.hub, "run") as run:
            self.app._handle_input("   ")
        run.assert_not_called()


class PerAgentOverrideTestCase(unittest.TestCase):
    """/model and /mode accept an optional per-tab target (default: the
    active tab), so each agent tab can carry its own model/mode override."""

    def setUp(self):
        self.app = RetroTerminalApp()

    def test_model_with_tab_target_sets_only_that_tab(self):
        self.app._cmd_model("m4 opencode/big-pickle")
        self.assertEqual(self.app.overrides["m4"]["model"], "opencode/big-pickle")
        # other tabs untouched -> inherit master (auto -> no model)
        model, _mode = self.app.hub.resolve("m1", self.app.overrides)
        self.assertIsNone(model)

    def test_model_bare_sets_active_tab(self):
        self.app.set_tab("m4")
        self.app._cmd_model("opencode/deepseek-v4-flash-free")
        self.assertEqual(
            self.app.overrides["m4"]["model"], "opencode/deepseek-v4-flash-free"
        )
        # master override untouched
        self.assertEqual(self.app.overrides["master"]["model"], AUTO_MODEL)

    def test_model_show_with_explicit_target(self):
        self.app._cmd_model("m4 opencode/big-pickle")
        reply = self.app._cmd_model("m4")
        self.assertIn("MODEL (m4)", reply)
        self.assertIn("opencode/big-pickle", reply)

    def test_model_all_sets_every_tab(self):
        self.app._cmd_model("all opencode/ling-3.0-tiny-free")
        for tag, _, _ in AGENTS:
            if tag in IMMUTABLE_TAGS:
                # M7 is immutable — _set_override skips it, so no override entry.
                self.assertNotIn(tag, self.app.overrides)
                continue
            self.assertEqual(
                self.app.overrides[tag]["model"], "opencode/ling-3.0-tiny-free"
            )
        self.assertEqual(self.app.overrides["master"]["model"], "opencode/ling-3.0-tiny-free")

    def test_model_auto_resets_tab_to_inherit_master(self):
        self.app._cmd_model("master opencode/big-pickle")
        self.app._cmd_model("m4 opencode/deepseek-v4-flash-free")
        self.app._cmd_model("m4 auto")
        model, _mode = self.app.hub.resolve("m4", self.app.overrides)
        self.assertEqual(model, "opencode/big-pickle")

    def test_model_unknown_errors(self):
        self.assertIn("ERROR", self.app._cmd_model("m4 nope"))

    def test_mode_validated_against_resolved_tab_model(self):
        self.app._cmd_model("m4 opencode/big-pickle")
        self.assertIn("MODE (m4)", self.app._cmd_mode("m4 plan"))
        self.assertEqual(self.app.overrides["m4"]["mode"], "plan")
        # 'zzz-invalid' is not a valid mode for any model -> rejected
        self.assertIn("ERROR", self.app._cmd_mode("m4 zzz-invalid"))

    def test_mode_allows_ling_modes_after_model_change(self):
        self.app._cmd_model("m4 opencode/ling-3.0-tiny-free")
        reply = self.app._cmd_mode("m4 review")
        self.assertNotIn("ERROR", reply)
        self.assertEqual(self.app.overrides["m4"]["mode"], "review")

    def test_mode_bare_uses_active_tab(self):
        self.app.set_tab("m4")
        self.app._cmd_model("opencode/big-pickle")
        self.app._cmd_mode("plan")
        self.assertEqual(self.app.overrides["m4"]["mode"], "plan")
        self.assertEqual(self.app.overrides["master"]["mode"], AUTO_MODE)

    def test_mode_auto_resets(self):
        self.app._cmd_model("m4 opencode/big-pickle")
        self.app._cmd_mode("m4 plan")
        self.app._cmd_mode("m4 auto")
        _model, mode = self.app.hub.resolve("m4", self.app.overrides)
        self.assertEqual(mode, AUTO_MODE)

    def test_status_shows_active_tab_model(self):
        self.app.set_tab("m4")
        self.app._cmd_model("opencode/big-pickle")
        self.app._cmd_mode("plan")
        status = self.app._cmd_status("")
        self.assertIn("TAB: m4", status)
        self.assertIn("MODEL: opencode/big-pickle", status)
        self.assertIn("MODE: plan", status)

    def test_model_bar_shows_active_tab_override(self):
        self.app._cmd_model("m4 opencode/big-pickle")
        self.app._cmd_model("master opencode/ling-3.0-tiny-free")
        bar_m4 = _model_bar(self.app.overrides, None, "m4")
        self.assertIn("MODEL opencode/big-pickle", bar_m4)
        bar_m1 = _model_bar(self.app.overrides, None, "m1")
        self.assertIn("MODEL opencode/ling-3.0-tiny-free", bar_m1)


class CleanLinePrefixTestCase(unittest.TestCase):
    """Log lines carry exactly one agent tag — no double prefixes."""

    def setUp(self):
        self._orig_state = terminal_app.STATE
        self._tmp = tempfile.TemporaryDirectory()
        terminal_app.STATE = StateTracker(path=Path(self._tmp.name) / "state.md")
        self.hub = RunHub()

    def tearDown(self):
        terminal_app.STATE = self._orig_state
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
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "prompt", None, None)
        # raw streamed lines, no embedded "[m4 David · QA & Max · DevOps & Automation]" prefix
        self.assertEqual(
            self.hub.buffers["m4"], ["hello from opencode", "second line"]
        )
        self.assertFalse(any("David · QA & Tester]" in line for line in self.hub.buffers["m4"]))

    def test_run_agent_error_has_no_embedded_tag(self):
        proc = _FakeProc(returncode=3)
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "prompt", None, None)
        err_lines = [e["text"] for e in self.hub.events if e["kind"] == "error"]
        self.assertIn("exit code 3", err_lines[-1])
        self.assertFalse(any("David · QA & Tester]" in text for text in err_lines))

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


class OverridesTableTestCase(unittest.TestCase):
    """/overrides renders every tab's effective model/mode as a table."""

    def _rows(self, table: str) -> dict[str, list[str]]:
        """Skip the header/dashes; map TAB label -> [model, mode, src]."""
        out: dict[str, list[str]] = {}
        for line in table.splitlines()[2:]:
            parts = line.split()
            self.assertEqual(len(parts), 4, f"bad row: {line!r}")
            out[parts[0]] = parts[1:]
        return out

    def test_table_has_header_and_all_tabs(self):
        table = build_overrides_table({"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}})
        rows = self._rows(table)
        self.assertEqual(list(rows.keys()), ["MASTER"] + [f"M{i}" for i in range(1, 8)])
        self.assertIn("MODEL", table.splitlines()[0])
        self.assertIn("SRC", table.splitlines()[0])

    def test_auto_everywhere(self):
        table = build_overrides_table({"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}})
        rows = self._rows(table)
        for label, (model, mode, src) in rows.items():
            if label == "M7":
                # M7 is immutable — always shows its locked model/mode.
                self.assertEqual(model, "opencode/ling-3.0-tiny-free")
                self.assertEqual(mode, M7_AUDIT_MODE)
                self.assertIn(src, ("auto", "set"))
            else:
                self.assertEqual(model, "auto")
                self.assertEqual(mode, "auto")
                self.assertEqual(src, "auto")

    def test_explicit_tab_and_master_sources(self):
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "plan"},
            "m1": {"model": "opencode/deepseek-v4-flash-free", "mode": "architect"},
        }
        rows = self._rows(build_overrides_table(overrides))
        self.assertEqual(rows["M1"], ["opencode/deepseek-v4-flash-free", "architect", "set"])
        self.assertEqual(rows["M2"], ["opencode/big-pickle", "plan", "master"])
        self.assertEqual(rows["MASTER"], ["opencode/big-pickle", "plan", "set"])

    def test_mode_only_override_shows_set_source(self):
        overrides = {
            "master": {"model": AUTO_MODEL, "mode": AUTO_MODE},
            "m4": {"mode": "review"},
        }
        rows = self._rows(build_overrides_table(overrides))
        model, mode, src = rows["M4"]
        self.assertEqual(mode, "review")
        self.assertEqual(src, "set")
        self.assertIn("auto", model)

    def test_cmd_overrides_returns_table(self):
        self.app = RetroTerminalApp()
        self.app._cmd_model("m4 opencode/big-pickle")
        reply = self.app._cmd_overrides("")
        self.assertIn("M4", reply)
        self.assertIn("opencode/big-pickle", reply)
        self.assertIn("set", reply)


class StructuredPanelTestCase(unittest.TestCase):
    """Categorized panels are shared by MASTER and every M1..M7 tab."""

    def test_classifies_thinking_todo_and_execution(self):
        self.assertEqual(terminal_app._classify_block("Thinking:"), ("thinking", "thinking"))
        self.assertEqual(terminal_app._classify_block("- [ ] add tests"), ("todo", "todo"))
        self.assertEqual(terminal_app._classify_block("- [x] add tests"), ("todo", "todo"))
        self.assertEqual(terminal_app._classify_block("FILE: scripts/terminal_app.py"), ("execution", "execution"))

    def test_thinking_and_todo_states_are_scoped_per_agent(self):
        groups = _panel_groups([
            ("m1", "Thinking:"),
            ("m2", "ordinary output"),
            ("m1", "reasoning continues"),
            ("m1", "TODO:"),
            ("m1", "- [ ] write tests"),
        ])
        keys = [key for key, _lines in groups]
        # Adjacent lines in one category intentionally share a single panel.
        self.assertEqual(keys, ["m1:thinking", "m2:execution", "m1:thinking", "m1:todo"])

    def test_dynamic_panel_border_fits_requested_width(self):
        for width in (24, 40, 80):
            for kind in (terminal_app.BLOCK_THINKING, terminal_app.BLOCK_TODO, terminal_app.BLOCK_EXECUTION):
                _style, opening = terminal_app._panel_border(kind, True, width)
                _style, closing = terminal_app._panel_border(kind, False, width)
                self.assertEqual(len(opening.splitlines()[0]), width)
                self.assertEqual(len(closing.splitlines()[0]), width)

    def test_panel_content_wraps_inside_borders(self):
        long_text = "FILE: " + ("very-long-filename/" * 10)
        rendered = "".join(text for _style, text in terminal_app._console_fragments(
            [("m4", long_text)], prefix=False, width=40
        ))
        rows = rendered.splitlines()
        self.assertTrue(rows)
        self.assertTrue(all(len(row) <= 40 for row in rows))
        self.assertIn("╭─", rendered)
        self.assertIn("╯", rendered)

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


class RetroRenderTestCase(unittest.TestCase):
    """The prompt_toolkit layout draws real frames headlessly.

    Renders through a ``Vt100_Output`` backed by a StringIO (no TTY needed)
    and asserts the retro chrome appears in the captured frame: ZOVA
    banner rows, directory indicator, model status bar in the rounded box's
    top border, dashboard glyphs, console lines, and the rounded box corners.
    """

    def _render(self, width=110, height=40):
        import asyncio
        import io

        from prompt_toolkit.output.vt100 import Vt100_Output

        class FixedSize:
            def __init__(self, w, h):
                self.columns, self.rows = w, h

        async def main():
            app = RetroTerminalApp()
            # Seed display state without submitting a command so the initial
            # frame still exercises the visible ZOVA banner.
            app.overrides["master"]["model"] = "opencode/big-pickle"
            app.console_lines.append(("m4", "hello retro world"))
            app.hub.set_status("m1", "thinking")

            buf = io.StringIO()
            out = Vt100_Output(buf, get_size=lambda: FixedSize(width, height))
            inst = app._build_application(input=QueuedInput([]), output=out)

            async def exit_soon():
                await asyncio.sleep(0.3)
                app._drain()
                inst.exit()

            inst.create_background_task(exit_soon())
            await inst.run_async()
            return terminal_app._strip_ansi(buf.getvalue())

        return asyncio.run(main())

    def test_frame_contains_banner_before_first_submission(self):
        frame = self._render()
        self.assertIn("████████╗ ████████╗ ██╗   ██╗ ████████╗", frame)
        self.assertIn("╚═══════╝ ╚═══════╝", frame)

    def test_banner_hides_after_first_submission(self):
        app = RetroTerminalApp()
        self.assertTrue(app.banner_visible)
        app._handle_input("/status")
        self.assertFalse(app.banner_visible)
        self.assertEqual(terminal_app._banner_fragments(app.banner_visible), [])

    def test_frame_contains_dir_and_dashboard(self):
        frame = self._render()
        self.assertIn("▶ DIR:", frame)
        self.assertIn("● M1", frame)
        self.assertIn("M7", frame)

    def test_frame_contains_model_bar_and_console(self):
        frame = self._render()
        self.assertIn("MODEL opencode/big-pickle", frame)
        self.assertIn("hello retro world", frame)
        self.assertIn("[m4]", frame)

    def test_frame_contains_rounded_box(self):
        frame = self._render()
        self.assertIn("╭─", frame)
        self.assertIn("╯", frame)
        self.assertIn("│", frame)

    def test_frame_has_one_loading_row_immediately_above_prompt(self):
        frame = self._render()
        lines = frame.splitlines()
        loading = [index for index, line in enumerate(lines) if "LOADING │" in line]
        prompt = [index for index, line in enumerate(lines) if "TAB MASTER" in line or "TAB M4" in line]
        self.assertEqual(len(loading), 1)
        self.assertEqual(frame.count("working..."), 1)
        self.assertEqual(frame.count("Token:"), 1)
        self.assertTrue(prompt)
        self.assertLess(loading[0], prompt[-1])
        # Vt100_Output emits a cursor-padding blank row between fixed-height
        # windows; there must be no other visible content in that gap.
        self.assertTrue(all(not lines[index].strip() for index in range(loading[0] + 1, prompt[-1])))

    def test_frame_contains_tab_bar(self):
        frame = self._render()
        self.assertIn("MASTER", frame)
        self.assertIn("Matthew", frame)
        self.assertIn("Chloe", frame)

    def test_frame_shows_active_tab_in_model_bar(self):
        import asyncio
        import io

        from prompt_toolkit.output.vt100 import Vt100_Output

        class FixedSize:
            def __init__(self, w, h):
                self.columns, self.rows = w, h

        async def main():
            app = RetroTerminalApp()
            app.set_tab("m4")
            buf = io.StringIO()
            out = Vt100_Output(buf, get_size=lambda: FixedSize(110, 40))
            inst = app._build_application(input=QueuedInput([]), output=out)

            async def exit_soon():
                await asyncio.sleep(0.3)
                app._drain()
                inst.exit()

            inst.create_background_task(exit_soon())
            await inst.run_async()
            return terminal_app._strip_ansi(buf.getvalue())

        frame = asyncio.run(main())
        self.assertIn("TAB M4", frame)

    def test_narrow_terminal_still_draws(self):
        frame = self._render(width=80, height=24)
        self.assertIn("DIR:", frame)
        self.assertIn("MODEL", frame)


class PollerTestCase(unittest.TestCase):
    """The background poller drains events and refreshes without crashing."""

    def test_poller_drains_and_invalidates(self):
        """The poller runs, drains events, and refreshes when scheduled via
        ``pre_run`` (the exact pattern ``run()`` uses in production)."""
        import asyncio
        import io

        from prompt_toolkit.output.vt100 import Vt100_Output

        class FixedSize:
            def __init__(self, w, h):
                self.columns, self.rows = w, h

        async def main():
            app = RetroTerminalApp()
            app.hub.append_line("m1", "streamed line")
            buf = io.StringIO()
            out = Vt100_Output(buf, get_size=lambda: FixedSize(100, 30))
            inst = app._build_application(input=QueuedInput([]), output=out)

            def start_poller():
                # scheduled from pre_run, like RetroTerminalApp.run()
                inst.create_background_task(app._poller())

            async def stop():
                await asyncio.sleep(0.35)
                inst.exit()

            inst.create_background_task(stop())
            await inst.run_async(pre_run=start_poller)
            # _poller ran, drained the event, and invalidated without raising
            self.assertTrue(any("streamed line" in text for _, text in app.console_lines))

        asyncio.run(main())

    def test_run_schedules_poller_via_pre_run(self):
        """run() must defer background-task creation to pre_run so the app's
        event loop exists (regression: scheduling it before app.run() raised
        ``RuntimeError: no running event loop``)."""
        fake_app = mock.MagicMock()
        app = RetroTerminalApp()
        with mock.patch("prompt_toolkit.input.create_input"), \
             mock.patch("prompt_toolkit.output.create_output"), \
             mock.patch.object(app, "_build_application", return_value=fake_app):
            app.run()
        # the real app's run() is delegated to with a pre_run callback...
        self.assertTrue(fake_app.run.called)
        pre_run = fake_app.run.call_args.kwargs.get("pre_run")
        self.assertIsNotNone(pre_run)
        # ...and invoking that callback schedules the poller background task
        pre_run()
        fake_app.create_background_task.assert_called_once()
        # close the never-awaited poller coroutine (warning hygiene)
        fake_app.create_background_task.call_args.args[0].close()

    def test_create_background_task_outside_loop_raises(self):
        """Documents why run() uses pre_run: creating a background task before
        the event loop is running raises RuntimeError."""
        import io

        from prompt_toolkit.output.vt100 import Vt100_Output

        class FixedSize:
            def __init__(self, w, h):
                self.columns, self.rows = w, h

        app = RetroTerminalApp()
        buf = io.StringIO()
        out = Vt100_Output(buf, get_size=lambda: FixedSize(100, 30))
        inst = app._build_application(input=QueuedInput([]), output=out)
        # no running event loop here (the suite only ever uses
        # asyncio.run(), which closes its loop) -> cannot schedule
        coro = app._poller()
        with self.assertRaises(RuntimeError):
            inst.create_background_task(coro)
        coro.close()  # warning hygiene: never-created task coroutine

    def test_drain_preserves_manual_scroll_offset(self):
        app = RetroTerminalApp()
        for i in range(30):
            app.console_lines.append(("m4", f"line {i}"))
        app.tab_scroll["master"] = 5
        app.hub.append_line("m4", "new line")
        app._drain()
        # the user's scroll offset survives the drain (not yanked to bottom)
        self.assertEqual(app.tab_scroll["master"], 5)
        self.assertTrue(any("new line" in text for _, text in app.console_lines))


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
        self.assertEqual(run.call_args.args[2], ["m4"])

    def test_task_on_master_tab_dispatches_to_all(self):
        with mock.patch.object(self.app.hub, "run", return_value=None) as run:
            self.app._handle_input("build everything")
        run.assert_called_once()
        self.assertIsNone(run.call_args.args[2])

    def test_master_tab_respects_agents_filter(self):
        self.app.agents_filter = ["m1", "m4"]
        with mock.patch.object(self.app.hub, "run", return_value=None) as run:
            self.app._handle_input("targeted task")
        self.assertEqual(run.call_args.args[2], ["m1", "m4"])

    def test_drain_routes_lines_to_agent_tab_and_master(self):
        self.app.hub.append_line("m4", "backend says hi")
        self.app.hub.append_line("master", "master note")
        self.app._drain()
        # MASTER sees everything
        texts = [text for _, text in self.app.console_lines]
        self.assertIn("backend says hi", texts)
        self.assertIn("master note", texts)
        # agent tab sees only its own lines
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
        bar = _model_bar({"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}}, None, "m4")
        self.assertIn("TAB M4", bar)
        self.assertIn("AI MODEL Auto", bar)
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

    def test_dashboard_marks_active_tab(self):
        frags = _dashboard_fragments({}, "m3")
        joined = "".join(text for _, text in frags)
        self.assertIn("MASTER", joined)  # master tab present
        self.assertIn("m3".upper(), joined)
        # active and inactive tabs share the same crisp outlined geometry
        self.assertIn("⟦● M3: Sarah [Frontend]⟧", joined)
        self.assertIn("⟦● M1: Matthew [Architect]⟧", joined)


class QueuedInput:
    """Deterministic prompt_toolkit ``Input`` for tests.

    Returns the queued ``KeyPress`` objects on the first read, then blocks
    (``[]``) — never EOF, so the app loop runs until a background task calls
    ``exit()``. ``attach`` schedules the input-ready callback via
    ``loop.call_soon`` (mimicking ``loop.add_reader``) so the app loop wakes
    once to consume the queued keys. Unlike ``create_pipe_input`` this needs
    no OS pipes/threads, so it cannot hang after ``exit()`` on Windows.
    """

    def __init__(self, keys):
        self._keys = list(keys)
        self._closed = False

    @property
    def closed(self):
        return self._closed

    def read_keys(self):
        if self._keys:
            keys, self._keys = self._keys, []
            return keys
        return []

    def flush(self):
        pass

    def fileno(self):
        return -1

    def typeahead_hash(self):
        return "queued-test-input"

    def close(self):
        self._closed = True

    def attach(self, callback):
        import asyncio
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            asyncio.get_running_loop().call_soon(callback)
            yield

        return _cm()

    def detach(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()

    def raw_mode(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()

    def cooked_mode(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()


def _text_keys(text: str):
    """KeyPress list for typing ``text`` (single-char keys)."""
    from prompt_toolkit.key_binding import KeyPress
    from prompt_toolkit.keys import Keys

    return [KeyPress(ch) for ch in text] + [KeyPress(Keys.ControlM, "\r")]


class InteractiveInputTestCase(unittest.TestCase):
    """Typing into the prompt box submits tasks and slash commands."""

    def _run_with_keys(self, keys):
        import asyncio
        import io

        from prompt_toolkit.output.vt100 import Vt100_Output

        class FixedSize:
            def __init__(self, w, h):
                self.columns, self.rows = w, h

        async def main():
            app = RetroTerminalApp()
            with mock.patch.object(app.hub, "run", return_value=None) as run:
                buf = io.StringIO()
                out = Vt100_Output(buf, get_size=lambda: FixedSize(100, 30))
                inp = QueuedInput(keys)
                inst = app._build_application(input=inp, output=out)

                async def exit_soon():
                    await asyncio.sleep(0.3)
                    app._drain()
                    inst.exit()

                inst.create_background_task(exit_soon())
                await inst.run_async()
                return app, run

        return asyncio.run(main())

    def test_typing_task_and_enter_dispatches(self):
        app, run = self._run_with_keys(_text_keys("build me a widget"))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], "build me a widget")
        # the submitted prompt is echoed into the console
        self.assertTrue(any("▸ build me a widget" in text for _, text in app.console_lines))
        # the input buffer is cleared after submit
        self.assertEqual(app.buffer.text, "")

    def test_slash_command_via_input(self):
        app, _run = self._run_with_keys(_text_keys("/agents m1,m4"))
        self.assertEqual(app.agents_filter, ["m1", "m4"])
        self.assertTrue(any("TARGET agents: m1,m4" in text for _, text in app.console_lines))

    def test_per_tab_model_via_input(self):
        app, _run = self._run_with_keys(_text_keys("/model m4 opencode/big-pickle"))
        self.assertEqual(app.overrides["m4"]["model"], "opencode/big-pickle")
        # master override stays auto
        self.assertEqual(app.overrides["master"]["model"], AUTO_MODEL)

    def test_overrides_command_via_input(self):
        app, _run = self._run_with_keys(
            _text_keys("/model m4 opencode/big-pickle") + _text_keys("/overrides")
        )
        echoed = [text for _, text in app.console_lines]
        self.assertTrue(any("TAB" in line and "SRC" in line for line in echoed))
        self.assertTrue(any("M4" in line and "opencode/big-pickle" in line for line in echoed))

    def test_f_key_switches_to_agent_tab(self):
        from prompt_toolkit.key_binding import KeyPress
        from prompt_toolkit.keys import Keys

        app, _run = self._run_with_keys([KeyPress(Keys.F4)])
        self.assertEqual(app.current_tab, "m4")

    def test_f8_switches_to_master_tab(self):
        from prompt_toolkit.key_binding import KeyPress
        from prompt_toolkit.keys import Keys

        app, _run = self._run_with_keys([KeyPress(Keys.F4), KeyPress(Keys.F8)])
        self.assertEqual(app.current_tab, "master")

    def test_ctrl_t_cycles_tabs(self):
        from prompt_toolkit.key_binding import KeyPress
        from prompt_toolkit.keys import Keys

        app, _run = self._run_with_keys([KeyPress(Keys.ControlT)])
        self.assertEqual(app.current_tab, "m1")

    def test_settings_hotkey_opens_and_escape_restores_prompt(self):
        from prompt_toolkit.key_binding import KeyPress
        from prompt_toolkit.keys import Keys

        app, _run = self._run_with_keys([
            KeyPress(Keys.ControlS),
            KeyPress(Keys.Escape),
        ])
        self.assertFalse(app.settings_open)
        self.assertEqual(app.buffer.text, "")

    def test_task_on_agent_tab_via_f_key_dispatches_to_agent(self):
        from prompt_toolkit.key_binding import KeyPress
        from prompt_toolkit.keys import Keys

        app, run = self._run_with_keys(
            [KeyPress(Keys.F4)] + _text_keys("build the widget")
        )
        self.assertEqual(app.current_tab, "m4")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[2], ["m4"])


class SelfEvolveWiringTestCase(unittest.TestCase):
    """run_self_evolve checkpoints, dispatches, and schedules the watcher."""

    def setUp(self):
        self._orig_state = terminal_app.STATE
        self._orig_engine = terminal_app.SELF_EVOLVE_ENGINE
        self._tmp = tempfile.TemporaryDirectory()
        terminal_app.STATE = StateTracker(path=Path(self._tmp.name) / "state.md")
        self.engine = mock.MagicMock()
        terminal_app.SELF_EVOLVE_ENGINE = self.engine
        # Ensure no stale abort signal from other test classes suppresses
        # the watcher's verify + marker writes.
        terminal_app.HUB._abort_event.clear()

    def tearDown(self):
        terminal_app.STATE = self._orig_state
        terminal_app.SELF_EVOLVE_ENGINE = self._orig_engine
        self._tmp.cleanup()

    def test_run_self_evolve_empty_prompt_errors(self):
        self.assertIn("Usage", run_self_evolve("   ", {}))

    def test_run_self_evolve_dispatches_and_schedules_watcher(self):
        self.engine.checkpoint.return_value = {"prompt": "upgrade", "git_head": "abc123", "decision": "d"}
        with mock.patch.object(terminal_app.HUB, "run", return_value=None) as hub_run, \
             mock.patch.object(terminal_app, "_spawn_self_evolve_watcher") as spawn_mock:
            reply = run_self_evolve("upgrade the plane", {})
        self.assertIn("abc123", reply)
        self.engine.checkpoint.assert_called_once_with("upgrade the plane")
        hub_run.assert_called_once()
        spawn_mock.assert_called_once()
        self.assertEqual(spawn_mock.call_args.args[0], "upgrade the plane")

    def test_run_self_evolve_passes_enabled_agents_to_hub(self):
        self.engine.checkpoint.return_value = {"prompt": "upgrade", "git_head": "abc123", "decision": "d"}
        enabled = {"m1", "m4"}
        with mock.patch.object(terminal_app.HUB, "run", return_value=None) as hub_run, \
             mock.patch.object(terminal_app, "_spawn_self_evolve_watcher"):
            run_self_evolve("upgrade the plane", {}, enabled_agents=enabled)
        self.assertEqual(hub_run.call_args.kwargs["enabled_agents"], enabled)

    def test_watcher_records_failure_without_marker(self):
        terminal_app.HUB.running = 0
        self.engine.verify.return_value = {
            "ok": False, "stdout": "", "errors": ["py_compile scripts/terminal_app.py failed"]
        }
        terminal_app._after_self_evolve_run("upgrade", {})
        self.engine.write_restart_marker.assert_not_called()
        state = terminal_app.STATE.load()
        self.assertTrue(any("verify" in e and "py_compile" in e for e in state["restart_log"]))

    def test_watcher_records_exception_without_crashing(self):
        terminal_app.HUB.running = 0
        self.engine.verify.side_effect = RuntimeError("boom")
        terminal_app._after_self_evolve_run("upgrade", {})
        self.engine.write_restart_marker.assert_not_called()
        state = terminal_app.STATE.load()
        self.assertTrue(any("verify" in e and "exception" in e and "boom" in e for e in state["restart_log"]))


# --------------------------------------------------------------------------- PromptLogger


class PromptLoggerTestCase(unittest.TestCase):
    """prompt_logger generates sequentially-named Obsidian markdown files."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.prompts_dir = Path(self._tmp.name) / "prompts"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        # Reset the module-level counter so tests are independent.
        prompt_logger._next_index = None

    def tearDown(self):
        self._tmp.cleanup()

    def test_log_prompt_writes_sequentially_named_file(self):
        path = prompt_logger.log_prompt(
            "build the widget",
            target_agents=["m4"],
            prompts_dir=self.prompts_dir,
        )
        self.assertTrue(path.exists())
        self.assertRegex(path.name, r"^prompt-001\.md$")
        content = path.read_text(encoding="utf-8")
        self.assertIn("# Prompt Log — prompt-001", content)
        self.assertIn("build the widget", content)
        # Frontmatter stores the raw tag(s); check metadata presence.
        self.assertIn('target_agent: "m4"', content)

    def test_second_prompt_increments_sequence(self):
        prompt_logger.log_prompt("first", prompts_dir=self.prompts_dir)
        path = prompt_logger.log_prompt("second", prompts_dir=self.prompts_dir)
        self.assertRegex(path.name, r"^prompt-002\.md$")

    def test_log_prompt_all_agents_shows_master_label(self):
        path = prompt_logger.log_prompt(
            "global task",
            target_agents=None,
            active_tab="master",
            prompts_dir=self.prompts_dir,
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("MASTER (all agents)", content)

    def test_log_prompt_includes_wiki_links(self):
        # WikiLinks are rendered by the _TEMPLATE.md; provide one.
        template = self.prompts_dir / "_TEMPLATE.md"
        template.write_text(
            "---\ntimestamp: \"{{timestamp}}\"\n---\n\n"
            "## Links\n"
            "- Roadmap: [[../Roadmap]]\n"
            "- Logs: [[../agents_logs/]]\n"
            "## Prompt\n```\n{{prompt_content}}\n```\n"
            "### Agents\n{{agent_log_links}}\n",
            encoding="utf-8",
        )
        path = prompt_logger.log_prompt(
            "update Roadmap",
            target_agents=["m1", "m4"],
            prompts_dir=self.prompts_dir,
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("[[../Roadmap]]", content)
        self.assertIn("[[../agents_logs/]]", content)
        self.assertIn("[[../agents_logs/M1]]", content)
        self.assertIn("[[../agents_logs/M4]]", content)

    def test_log_prompt_uses_template_when_present(self):
        template = self.prompts_dir / "_TEMPLATE.md"
        template.write_text("CUSTOM: {{prompt_content}}", encoding="utf-8")
        path = prompt_logger.log_prompt(
            "custom task",
            prompts_dir=self.prompts_dir,
        )
        self.assertIn("CUSTOM:", path.read_text(encoding="utf-8"))

    def test_log_prompt_fallback_when_template_missing(self):
        # No _TEMPLATE.md in this directory → fallback content.
        path = prompt_logger.log_prompt(
            "fallback test",
            prompts_dir=self.prompts_dir,
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("## User Prompt", content)
        self.assertIn("fallback test", content)

    def test_run_logs_prompt_to_obsidian_vault(self):
        # Patch the default prompts_dir so the test never writes to the real vault.
        with mock.patch.object(prompt_logger, "DEFAULT_PROMPTS_DIR", self.prompts_dir):
            hub = RunHub()
            with mock.patch("terminal_app.threading.Thread"):
                hub.run("my coding task", {})
        generated = sorted(self.prompts_dir.glob("prompt-*.md"))
        self.assertTrue(generated, "at least one prompt log should be generated")
        self.assertTrue(
            any("my coding task" in f.read_text(encoding="utf-8")
                for f in generated),
            "prompt log should contain 'my coding task'",
        )

    def test_safe_filename_slugs_prompt_text(self):
        self.assertEqual(
            prompt_logger._safe_filename("Hello World!!!"), "Hello-World"
        )
        self.assertEqual(
            prompt_logger._safe_filename("  spaces   everywhere  "), "spaces-everywhere"
        )

    def test_wiki_link_formats_correctly(self):
        self.assertEqual(
            prompt_logger._wiki_link("agents_logs/M1"),
            "[[agents_logs/M1]]",
        )
        self.assertEqual(
            prompt_logger._wiki_link("Roadmap", "Phase-D"),
            "[[Roadmap#Phase-D]]",
        )


class AgentLoggerTestCase(unittest.TestCase):
    """agent_logger creates/maintains per-agent Obsidian markdown logs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.agents_dir = Path(self._tmp.name) / "agents_logs"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        # Reset the in-memory active-set cache between tests.
        agent_logger._ACTIVE_AGENT_CACHE.clear()

    def tearDown(self):
        self._tmp.cleanup()

    # ---------------------------------------------------------- ensure_agent_logs

    def test_ensure_creates_files_for_all_dispatched_agents(self):
        paths = agent_logger.ensure_agent_logs(
            ["m1", "m4"], agents_dir=self.agents_dir
        )
        self.assertEqual(len(paths), 2)
        filenames = {p.name for p in paths}
        self.assertIn("M1_Matthew.md", filenames)
        self.assertIn("M4_David.md", filenames)

    def test_ensure_is_idempotent(self):
        first = agent_logger.ensure_agent_logs(
            ["m1"], agents_dir=self.agents_dir
        )
        second = agent_logger.ensure_agent_logs(
            ["m1"], agents_dir=self.agents_dir
        )
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0], second[0])

    def test_ensure_only_creates_for_given_tags(self):
        agent_logger.ensure_agent_logs(
            ["m4"], agents_dir=self.agents_dir
        )
        all_files = set(self.agents_dir.iterdir())
        # Exclude _TEMPLATE.md if copied; only M4 should exist.
        agent_files = {f for f in all_files if f.name != "_TEMPLATE.md"}
        self.assertEqual(len(agent_files), 1)
        self.assertTrue(any("M4" in f.name for f in agent_files))

    # ---------------------------------------------------------- append_agent_run

    def test_append_adds_entry_to_active_agent(self):
        agent_logger.ensure_agent_logs(
            ["m4"], agents_dir=self.agents_dir
        )
        path = agent_logger.append_agent_run(
            "m4",
            "build the widget",
            "prompt-001",
            status="ok",
            duration_s=2.5,
            agents_dir=self.agents_dir,
        )
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("build the widget", content)
        self.assertIn("prompt-001", content)
        self.assertIn("✅", content)
        self.assertIn("2.5s", content)

    def test_append_creates_file_even_when_not_in_active_set(self):
        # Only m1 is in the active set, but m4 should still get a log entry
        # because we never want to lose agent run history.
        agent_logger.ensure_agent_logs(
            ["m1"], agents_dir=self.agents_dir
        )
        result = agent_logger.append_agent_run(
            "m4",
            "secret task",
            "prompt-001",
            agents_dir=self.agents_dir,
        )
        # File is created even though m4 was not in the original ensure call.
        self.assertIsNotNone(result)
        self.assertTrue(result.exists())
        content = result.read_text(encoding="utf-8")
        self.assertIn("secret task", content)

    def test_append_updates_last_updated_frontmatter(self):
        agent_logger.ensure_agent_logs(
            ["m4"], agents_dir=self.agents_dir
        )
        path = agent_logger.append_agent_run(
            "m4",
            "hello",
            "prompt-001",
            status="ok",
            agents_dir=self.agents_dir,
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn('last_updated: "', content)

    # ---------------------------------------------------------- active set tracking

    def test_active_agents_returns_on_disk_set(self):
        agent_logger.ensure_agent_logs(
            ["m1", "m4", "m7"], agents_dir=self.agents_dir
        )
        active = agent_logger.active_agents(agents_dir=self.agents_dir)
        self.assertEqual(active, {"m1", "m4", "m7"})

    def test_cached_active_agents_matches_last_ensure(self):
        agent_logger.ensure_agent_logs(
            ["m1", "m4"], agents_dir=self.agents_dir
        )
        self.assertEqual(agent_logger.cached_active_agents(), {"m1", "m4"})

    def test_scaling_down_does_not_delete_inactive_agent_files(self):
        # Scale up: create for 3 agents.
        agent_logger.ensure_agent_logs(
            ["m1", "m4", "m5"], agents_dir=self.agents_dir
        )
        # Scale down: only dispatch m1.
        agent_logger.ensure_agent_logs(
            ["m1"], agents_dir=self.agents_dir
        )
        all_files = list(self.agents_dir.glob("M*.md"))
        # All three files still exist (history preserved).
        self.assertGreaterEqual(len(all_files), 2)
        # But only m1 is in the active set.
        self.assertEqual(agent_logger.cached_active_agents(), {"m1"})

    # ---------------------------------------------------------- WikiLinks

    def test_log_content_has_wiki_links(self):
        template = self.agents_dir / "_TEMPLATE.md"
        template.write_text(
            "---\n"
            'agent_tag: "{{agent_tag}}"\n'
            'last_updated: "{{last_updated}}"\n'
            "---\n\n"
            "# {{agent_tag}}\n\n"
            "## Role\n{{role_description}}\n\n"
            "## Links\n"
            "- Dashboard: [[../Dashboard]]\n"
            "- Roadmap: [[../Roadmap]]\n"
            "- Prompts: [[../prompts/]]\n",
            encoding="utf-8",
        )
        paths = agent_logger.ensure_agent_logs(
            ["m4"], agents_dir=self.agents_dir
        )
        content = paths[0].read_text(encoding="utf-8")
        self.assertIn("[[../Dashboard]]", content)
        self.assertIn("[[../Roadmap]]", content)
        self.assertIn("[[../prompts/]]", content)

    def test_run_entry_links_to_prompt_log(self):
        agent_logger.ensure_agent_logs(
            ["m4"], agents_dir=self.agents_dir
        )
        path = agent_logger.append_agent_run(
            "m4",
            "task",
            "prompt-003",
            status="failed",
            agents_dir=self.agents_dir,
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("[[../prompts/prompt-003]]", content)
        self.assertIn("❌", content)

    # ---------------------------------------------------------- filename helper

    def test_safe_agent_filename_maps_tags_to_names(self):
        self.assertIn("M1_Matthew", agent_logger._safe_agent_filename("m1"))
        self.assertIn("M7_Chloe", agent_logger._safe_agent_filename("m7"))

    def test_safe_agent_filename_fallback_for_unknown_tag(self):
        self.assertEqual(
            agent_logger._safe_agent_filename("m9"),
            "M9.md",
        )


class M7AuditTestCase(unittest.TestCase):
    """M7 Chloe · Documentation & Knowledge immutability + obsidian_auditor vault auditing."""

    # -------------------------------------------------- immutability

    def test_m7_is_immutable(self):
        self.assertIn("m7", IMMUTABLE_TAGS)
        self.assertEqual(len(IMMUTABLE_TAGS), 1)

    def test_m7_audit_mode_exists(self):
        self.assertIn(
            M7_AUDIT_MODE,
            MODE_OPTIONS_BY_MODEL["opencode/ling-3.0-tiny-free"],
        )
        self.assertEqual(M7_AUDIT_MODE, "documentation-audit")

    def test_hub_resolve_locks_m7(self):
        hub = RunHub()
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "plan"},
            "m7": {"model": "opencode/deepseek-v4-flash-free", "mode": "architect"},
        }
        model, mode = hub.resolve("m7", overrides)
        self.assertEqual(model, "opencode/ling-3.0-tiny-free")
        self.assertEqual(mode, M7_AUDIT_MODE)

    def test_cmd_model_rejects_m7_change(self):
        app = RetroTerminalApp()
        reply = app._cmd_model("m7 opencode/big-pickle")
        self.assertIn("ERROR", reply)
        self.assertIn("immutable", reply.lower())

    def test_cmd_mode_rejects_m7_change(self):
        app = RetroTerminalApp()
        reply = app._cmd_mode("m7 review")
        self.assertIn("ERROR", reply)
        self.assertIn("immutable", reply.lower())

    # -------------------------------------------------- auditor

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name) / "obsidian_vault"
        self.vault.mkdir()
        (self.vault / "prompts").mkdir()
        (self.vault / "agents_logs").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_verify_vault_integrity_pass(self):
        (self.vault / "Dashboard.md").write_text("# Dash", encoding="utf-8")
        (self.vault / "Roadmap.md").write_text("# Road", encoding="utf-8")
        (self.vault / "prompts" / "prompt-001.md").write_text("p1", encoding="utf-8")
        (self.vault / "agents_logs" / "M1_Test.md").write_text("a1", encoding="utf-8")
        result = obsidian_auditor.verify_vault_integrity(vault_root=self.vault)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["issues"]), 0)

    def test_verify_vault_integrity_detects_missing_files(self):
        result = obsidian_auditor.verify_vault_integrity(vault_root=self.vault)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Dashboard.md" in i for i in result["issues"]))

    def test_cross_reference_detects_orphaned_prompts(self):
        (self.vault / "prompts" / "prompt-001.md").write_text("orphan", encoding="utf-8")
        (self.vault / "agents_logs" / "M4_David.md").write_text(
            "No links here", encoding="utf-8"
        )
        result = obsidian_auditor.cross_reference_prompts(vault_root=self.vault)
        self.assertFalse(result["ok"])
        self.assertIn("prompt-001", result["orphaned_prompts"])

    def test_cross_reference_pass_when_all_linked(self):
        (self.vault / "prompts" / "prompt-001.md").write_text("p1", encoding="utf-8")
        (self.vault / "agents_logs" / "M4_David.md").write_text(
            "[[../prompts/prompt-001]]", encoding="utf-8"
        )
        result = obsidian_auditor.cross_reference_prompts(vault_root=self.vault)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["orphaned_prompts"]), 0)

    def test_sync_roadmap_updates_timestamp_and_branch(self):
        (self.vault / "Roadmap.md").write_text(
            "> **Last updated:** old\n> **Current branch:** old-branch\n",
            encoding="utf-8",
        )
        result = obsidian_auditor.sync_roadmap(
            vault_root=self.vault, project_root=Path(self._tmp.name)
        )
        self.assertTrue(result["ok"])
        updated = (self.vault / "Roadmap.md").read_text(encoding="utf-8")
        self.assertNotIn("old", updated)
        self.assertIn("**Last updated:**", updated)
        self.assertIn("**Current branch:**", updated)

    def test_audit_run_integrates_all_checks(self):
        (self.vault / "Dashboard.md").write_text("# D", encoding="utf-8")
        (self.vault / "Roadmap.md").write_text("# R", encoding="utf-8")
        (self.vault / "prompts" / "prompt-001.md").write_text("p", encoding="utf-8")
        (self.vault / "agents_logs" / "M4_David.md").write_text(
            "[[../prompts/prompt-001]]", encoding="utf-8"
        )
        result = obsidian_auditor.audit_run(
            vault_root=self.vault, project_root=Path(self._tmp.name)
        )
        self.assertIn("integrity", result)
        self.assertIn("cross_ref", result)
        self.assertIn("roadmap", result)
        self.assertIn("M7 Audit complete", result["summary"])

    def test_run_hub_has_m7_audit_method(self):
        hub = RunHub()
        self.assertTrue(hasattr(hub, "_run_m7_audit"))
        self.assertTrue(callable(hub._run_m7_audit))

    # -------------------------------------------------- new phase 5 checks

    def test_verify_dashboard_wikilinks_valid(self):
        (self.vault / "Dashboard.md").write_text(
            "[[Roadmap]] [[prompts/]] [[agents_logs/]]", encoding="utf-8"
        )
        (self.vault / "Roadmap.md").write_text("# R", encoding="utf-8")
        result = obsidian_auditor.verify_dashboard_wikilinks(vault_root=self.vault)
        self.assertTrue(result["ok"])
        self.assertIn("PASS", result["summary"])

    def test_verify_dashboard_wikilinks_detects_broken(self):
        (self.vault / "Dashboard.md").write_text(
            "[[MissingPage]]", encoding="utf-8"
        )
        result = obsidian_auditor.verify_dashboard_wikilinks(vault_root=self.vault)
        self.assertFalse(result["ok"])
        self.assertTrue(any("MissingPage" in b for b in result["broken_links"]))

    def test_verify_roadmap_checkboxes_tracks_phases(self):
        (self.vault / "Roadmap.md").write_text(
            "## Phase A\n- [x] done task\n- [ ] pending task\n", encoding="utf-8"
        )
        result = obsidian_auditor.verify_roadmap_checkboxes(vault_root=self.vault)
        self.assertFalse(result["ok"])
        self.assertTrue(any("50%" in m for m in result["mismatches"]))


class NewSlashCommandsTestCase(unittest.TestCase):
    """/agents-log and /audit commands."""

    def setUp(self):
        self.app = RetroTerminalApp()

    def test_agents_log_rejects_unknown_tag(self):
        reply = self.app._cmd_agents_log("m9")
        self.assertIn("ERROR", reply)

    def test_agents_log_reports_empty_or_missing(self):
        # Use a temp agents dir so the test is isolated from the real vault.
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp) / "agents_logs"
            agents_dir.mkdir()
            reply = self.app._cmd_agents_log("m1", _agents_dir_override=agents_dir)
            self.assertTrue(
                "No log file" in reply or "no run entries" in reply,
                f"Expected 'No log file' or 'no run entries', got: {reply}"
            )

    def test_audit_returns_string_when_idle(self):
        reply = self.app._cmd_audit("")
        self.assertIsInstance(reply, str)


class SubprocessErrorHandlingTestCase(unittest.TestCase):
    """Graceful subprocess error handling: exit codes, pipe breaks, external termination."""

    def setUp(self):
        self.hub = RunHub()

    def _make_proc(self, returncode=0, lines=None):
        """Build a mock Popen that yields lines then returns a given exit code."""
        proc = mock.MagicMock()
        proc.stdout = lines or []
        proc.wait.return_value = returncode
        return proc

    def test_exit_code_zero_sets_ok_and_idle(self):
        proc = self._make_proc(returncode=0, lines=["hello"])
        with mock.patch("terminal_app._opencode_command", return_value="fake.exe"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "test prompt", None, None)
        self.assertEqual(self.hub.statuses["m4"], terminal_app.STATUS_IDLE)
        self.assertIn("hello", self.hub.buffers["m4"])

    def test_exit_code_nonzero_shows_command_in_error(self):
        proc = self._make_proc(returncode=1, lines=["some output"])
        with mock.patch("terminal_app._opencode_command", return_value="fake.exe"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "test prompt", None, None)
        self.assertEqual(self.hub.statuses["m4"], terminal_app.STATUS_ERROR)
        err_lines = [e["text"] for e in self.hub.events if e["kind"] == "error"]
        self.assertTrue(err_lines)
        error_msg = err_lines[-1]
        self.assertIn("exit code 1", error_msg)
        self.assertIn("fake.exe", error_msg)  # command is included
        self.assertIn("david", error_msg)

    def test_external_termination_does_not_set_error(self):
        """When terminate_agent() kills the proc, _run_agent must not overwrite IDLE with ERROR."""
        proc = self._make_proc(returncode=1, lines=["working"])
        # Simulate external termination: proc.wait() pops the proc from the hub
        # before _run_agent's own pop, mimicking terminate_agent's cleanup.
        def _wait_side_effect():
            self.hub.procs.pop("m4", None)
            self.hub.statuses["m4"] = terminal_app.STATUS_IDLE
            return 1
        proc.wait.side_effect = _wait_side_effect
        with mock.patch("terminal_app._opencode_command", return_value="fake.exe"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "test prompt", None, None)
        # Status must remain IDLE — the external termination was intentional.
        self.assertEqual(self.hub.statuses["m4"], terminal_app.STATUS_IDLE)

    def test_pipe_broken_during_read_is_graceful(self):
        """BrokenPipeError during stdout read must not crash the thread."""
        proc = mock.MagicMock()
        # Make stdout raise BrokenPipeError after yielding one line.
        def _broken_stdout():
            yield "first line"
            raise BrokenPipeError()
        proc.stdout = _broken_stdout()
        proc.wait.return_value = -15  # SIGTERM-like
        # Don't mock procs.pop — it returns normally (not externally terminated).
        with mock.patch("terminal_app._opencode_command", return_value="fake.exe"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "test prompt", None, None)
        # Should have captured the first line before the pipe broke.
        self.assertIn("first line", self.hub.buffers["m4"])
        # Non-zero exit code from pipe break (proc was NOT popped => no external
        # termination detected) => ERROR.
        self.assertEqual(self.hub.statuses["m4"], terminal_app.STATUS_ERROR)

    def test_file_not_found_error_is_surfaced(self):
        with mock.patch("terminal_app._opencode_command", return_value=None):
            self.hub._run_agent("m4", "david", "test prompt", None, None)
        self.assertEqual(self.hub.statuses["m4"], terminal_app.STATUS_ERROR)
        err_lines = [e["text"] for e in self.hub.events if e["kind"] == "error"]
        self.assertTrue(any("not found" in e.lower() for e in err_lines))

    def test_running_decremented_on_error(self):
        self.hub.running = 2
        self.hub.session_tags.update(["m4", "m5"])
        proc = self._make_proc(returncode=1, lines=["failed"])
        with mock.patch("terminal_app._opencode_command", return_value="fake.exe"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "david", "test prompt", None, None)
        self.assertEqual(self.hub.running, 1)
        # session_tags only clears when running hits 0.
        self.assertIn("m5", self.hub.session_tags)
        self.assertIn("m4", self.hub.session_tags)

    def test_state_record_finish_skipped_when_killed(self):
        """When externally terminated, STATE.record_finish is NOT called by the thread."""
        proc = self._make_proc(returncode=1, lines=["working"])
        def _wait_side_effect():
            self.hub.procs.pop("m4", None)
            self.hub.statuses["m4"] = terminal_app.STATUS_IDLE
            return 1
        proc.wait.side_effect = _wait_side_effect
        with mock.patch("terminal_app._opencode_command", return_value="fake.exe"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc), \
             mock.patch.object(terminal_app.STATE, "record_finish") as mock_finish:
            self.hub._run_agent("m4", "david", "test prompt", None, None)
        mock_finish.assert_not_called()


class EscAbortTestCase(unittest.TestCase):
    """Two-step Esc abort mechanism: context-aware scoping (Master vs Agent tab)."""

    def setUp(self):
        self.app = RetroTerminalApp()
        self.hub = self.app.hub

    def tearDown(self):
        # Ensure any mock patching is cleaned up
        self.hub.terminate_all()

    # -------------------------------------------------- state management

    def test_clear_esc_state_resets_pending(self):
        self.app._esc_pending_tag = "m1"
        self.app._esc_pending_time = 999.0
        self.app._clear_esc_state()
        self.assertIsNone(self.app._esc_pending_tag)
        self.assertEqual(self.app._esc_pending_time, 0.0)

    def test_set_tab_clears_pending_esc(self):
        self.app._esc_pending_tag = "m1"
        self.app._esc_pending_time = 999.0
        self.app.set_tab("m4")
        self.assertIsNone(self.app._esc_pending_tag)
        self.assertEqual(self.app._esc_pending_time, 0.0)

    def test_close_menu_clears_pending_esc(self):
        self.app._esc_pending_tag = "m1"
        self.app._esc_pending_time = 999.0
        self.app.close_menu()
        self.assertIsNone(self.app._esc_pending_tag)
        self.assertEqual(self.app._esc_pending_time, 0.0)

    # -------------------------------------------------- warning messages

    def test_show_esc_warning_master_tab(self):
        self.app.current_tab = "master"
        self.app._show_esc_warning()
        # The warning is echoed via _echo => console_lines; verify the message.
        warnings = [
            text for _tag, text in self.app.console_lines
            if "ESC" in text
        ]
        self.assertTrue(warnings, f"Expected an Esc warning in console_lines, got: {self.app.console_lines}")
        warning = warnings[-1]
        self.assertIn("ALL AGENTS", warning)
        self.assertIn("global cascade", warning.lower())

    def test_show_esc_warning_agent_tab(self):
        self.app.current_tab = "m4"
        self.app._show_esc_warning()
        warnings = [
            text for _tag, text in self.app.console_lines
            if "ESC" in text
        ]
        self.assertTrue(warnings, f"Expected an Esc warning in console_lines, got: {self.app.console_lines}")
        warning = warnings[-1]
        self.assertIn("M4", warning)
        self.assertIn("only", warning.lower())
        self.assertIn("David", warning)

    # -------------------------------------------------- abort execution

    def test_execute_escapbort_master_calls_terminate_all(self):
        self.app.current_tab = "master"
        with mock.patch.object(self.hub, "terminate_all") as mock_term:
            self.app._execute_esc_abort()
            mock_term.assert_called_once()

    def test_execute_esc_abort_agent_calls_terminate_agent(self):
        self.app.current_tab = "m4"
        # Simulate an active process so terminate_agent returns True.
        with self.hub.lock:
            self.hub.statuses["m4"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 1
            self.hub.session_tags.add("m4")
        self.hub.procs["m4"] = mock.MagicMock()
        try:
            self.app._execute_esc_abort()
            # Verify the agent was marked idle
            self.assertEqual(self.hub.statuses["m4"], terminal_app.STATUS_IDLE)
        finally:
            self.hub.procs.pop("m4", None)
            with self.hub.lock:
                self.hub.statuses["m4"] = terminal_app.STATUS_IDLE
                self.hub.running = 0
                self.hub.session_tags.clear()

    def test_execute_esc_abort_agent_not_running_noop(self):
        self.app.current_tab = "m5"
        with self.hub.lock:
            self.hub.statuses["m5"] = terminal_app.STATUS_IDLE
        result = self.hub.terminate_agent("m5")
        self.assertFalse(result)

    # -------------------------------------------------- terminate_agent

    def test_terminate_agent_resets_state(self):
        with self.hub.lock:
            self.hub.statuses["m3"] = terminal_app.STATUS_ACTIVE
            self.hub.progress["m3"] = 42
            self.hub.token_usage["m3"] = 55
            self.hub.running = 2
            self.hub.session_tags.add("m3")
            self.hub.session_tags.add("m6")
        self.hub.procs["m3"] = mock.MagicMock()
        try:
            result = self.hub.terminate_agent("m3")
            self.assertTrue(result)
            self.assertEqual(self.hub.statuses["m3"], terminal_app.STATUS_IDLE)
            self.assertEqual(self.hub.progress["m3"], 0)
            self.assertEqual(self.hub.token_usage["m3"], 0)
            # running is NOT decremented in terminate_agent — the thread's
            # finally block handles it to avoid double-counting.
            self.assertEqual(self.hub.running, 2)
            self.assertNotIn("m3", self.hub.session_tags)
        finally:
            self.hub.procs.pop("m3", None)
            with self.hub.lock:
                self.hub.statuses["m3"] = terminal_app.STATUS_IDLE
                self.hub.running = 0
                self.hub.session_tags.clear()

    def test_terminate_agent_clears_session_when_last(self):
        with self.hub.lock:
            self.hub.statuses["m3"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 1
            self.hub.session_tags.add("m3")
        self.hub.procs["m3"] = mock.MagicMock()
        try:
            self.hub.terminate_agent("m3")
            # running is NOT decremented — the thread's finally block handles it.
            self.assertEqual(self.hub.running, 1)
            # session_tags discards the tag but won't clear since running != 0.
            self.assertNotIn("m3", self.hub.session_tags)
        finally:
            self.hub.procs.pop("m3", None)
            with self.hub.lock:
                self.hub.statuses["m3"] = terminal_app.STATUS_IDLE
                self.hub.running = 0
                self.hub.session_tags.clear()

    def test_terminate_agent_kills_subprocess(self):
        mock_proc = mock.MagicMock()
        with self.hub.lock:
            self.hub.statuses["m2"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 1
            self.hub.session_tags.add("m2")
        self.hub.procs["m2"] = mock_proc
        try:
            self.hub.terminate_agent("m2")
            mock_proc.terminate.assert_called_once()
        finally:
            self.hub.procs.pop("m2", None)
            with self.hub.lock:
                self.hub.statuses["m2"] = terminal_app.STATUS_IDLE
                self.hub.running = 0
                self.hub.session_tags.clear()

    def test_terminate_all_still_works(self):
        with self.hub.lock:
            self.hub.statuses["m1"] = terminal_app.STATUS_ACTIVE
            self.hub.statuses["m2"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 2
            self.hub.session_tags.update(["m1", "m2"])
        try:
            self.hub.terminate_all()
            self.assertEqual(self.hub.running, 0)
            self.assertEqual(len(self.hub.session_tags), 0)
            self.assertEqual(self.hub.statuses["m1"], terminal_app.STATUS_IDLE)
            self.assertEqual(self.hub.statuses["m2"], terminal_app.STATUS_IDLE)
        finally:
            with self.hub.lock:
                self.hub.running = 0
                self.hub.session_tags.clear()
                for t, _, _ in AGENTS:
                    self.hub.statuses[t] = terminal_app.STATUS_IDLE

    # -------------------------------------------------- full two-step flow

    def test_full_two_step_master_global_abort(self):
        """Simulate full two-step flow on Master: first Esc warns, second aborts all."""
        self.app.current_tab = "master"
        with self.hub.lock:
            self.hub.statuses["m1"] = terminal_app.STATUS_ACTIVE
            self.hub.statuses["m2"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 2
            self.hub.session_tags.update(["m1", "m2"])
        try:
            # Step 1: first Esc press => sets pending, shows warning.
            self.app._handle_esc()
            self.assertEqual(self.app._esc_pending_tag, "master")
            self.assertGreater(self.app._esc_pending_time, 0)
            warnings = [
                text for _tag, text in self.app.console_lines
                if "ESC" in text and "ALL AGENTS" in text
            ]
            self.assertTrue(warnings, "Expected global abort warning")

            # Step 2: second Esc press (within timeout) => executes abort.
            self.app._handle_esc()
            # After abort, pending state is cleared.
            self.assertIsNone(self.app._esc_pending_tag)
            self.assertEqual(self.app._esc_pending_time, 0.0)
            # All agents should be idle after the global cascade.
            self.assertEqual(self.hub.statuses["m1"], terminal_app.STATUS_IDLE)
            self.assertEqual(self.hub.statuses["m2"], terminal_app.STATUS_IDLE)
            self.assertEqual(self.hub.running, 0)
        finally:
            with self.hub.lock:
                self.hub.running = 0
                self.hub.session_tags.clear()
                for t, _, _ in AGENTS:
                    self.hub.statuses[t] = terminal_app.STATUS_IDLE

    def test_full_two_step_agent_isolated_abort(self):
        """Simulate full two-step flow on M4: first Esc warns, second aborts only M4."""
        self.app.current_tab = "m4"
        mock_proc = mock.MagicMock()
        with self.hub.lock:
            self.hub.statuses["m4"] = terminal_app.STATUS_ACTIVE
            self.hub.statuses["m5"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 2
            self.hub.session_tags.update(["m4", "m5"])
        self.hub.procs["m4"] = mock_proc
        try:
            # Step 1: first Esc press => sets pending, shows isolated warning.
            self.app._handle_esc()
            self.assertEqual(self.app._esc_pending_tag, "m4")
            warnings = [
                text for _tag, text in self.app.console_lines
                if "ESC" in text and "M4" in text and "only" in text.lower()
            ]
            self.assertTrue(warnings, "Expected M4-only abort warning")

            # Step 2: second Esc press => aborts only M4.
            self.app._handle_esc()
            self.assertIsNone(self.app._esc_pending_tag)
            # M4 should be terminated, M5 still running.
            self.assertEqual(self.hub.statuses["m4"], terminal_app.STATUS_IDLE)
            self.assertEqual(self.hub.statuses["m5"], terminal_app.STATUS_ACTIVE)
            # M4's proc was terminated.
            mock_proc.terminate.assert_called_once()
            # session_tags discarded m4 but kept m5.
            self.assertNotIn("m4", self.hub.session_tags)
            self.assertIn("m5", self.hub.session_tags)
        finally:
            self.hub.procs.pop("m4", None)
            with self.hub.lock:
                self.hub.running = 0
                self.hub.session_tags.clear()
                for t, _, _ in AGENTS:
                    self.hub.statuses[t] = terminal_app.STATUS_IDLE

    def test_esc_timeout_resets_to_fresh_first_press(self):
        """When the timeout expires, Esc acts as a fresh first press, not an abort."""
        self.app.current_tab = "master"
        with self.hub.lock:
            self.hub.statuses["m1"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 1
            self.hub.session_tags.add("m1")
        try:
            # Set pending state with an expired timestamp.
            self.app._esc_pending_tag = "master"
            self.app._esc_pending_time = time.monotonic() - 10.0  # well past 3s timeout

            # Call handle_esc — should re-arm as a fresh first press.
            with mock.patch.object(self.app, "_execute_esc_abort") as mock_abort:
                self.app._handle_esc()
                # Should NOT have executed abort (timeout expired).
                mock_abort.assert_not_called()
            # Should have re-set pending state.
            self.assertEqual(self.app._esc_pending_tag, "master")
            self.assertGreater(self.app._esc_pending_time, 0)
        finally:
            with self.hub.lock:
                self.hub.running = 0
                self.hub.session_tags.clear()
                for t, _, _ in AGENTS:
                    self.hub.statuses[t] = terminal_app.STATUS_IDLE

    def test_esc_noop_when_no_agents_running(self):
        """Esc does nothing (and clears state) when no agents are running."""
        self.app.current_tab = "m4"
        self.app._esc_pending_tag = "m4"
        self.app._esc_pending_time = time.monotonic()
        self.hub.running = 0

        with mock.patch.object(self.app, "_execute_esc_abort") as mock_abort:
            with mock.patch.object(self.app, "_show_esc_warning") as mock_warn:
                self.app._handle_esc()
                mock_abort.assert_not_called()
                mock_warn.assert_not_called()
        # Pending state is cleared.
        self.assertIsNone(self.app._esc_pending_tag)
        self.assertEqual(self.app._esc_pending_time, 0.0)

    def test_esc_closes_menu_without_abort(self):
        """Esc closes an open dropdown menu without triggering abort logic."""
        self.app.current_tab = "master"
        self.app.menu_kind = "model"
        self.app.menu_target = "m1"
        self.app.menu_options = ["auto", "opencode/big-pickle"]

        with mock.patch.object(self.app, "_execute_esc_abort") as mock_abort:
            with mock.patch.object(self.app, "_show_esc_warning") as mock_warn:
                self.app._handle_esc()
                mock_abort.assert_not_called()
                mock_warn.assert_not_called()
        # Menu should be closed.
        self.assertIsNone(self.app.menu_kind)
        self.assertIsNone(self.app.menu_target)
        self.assertEqual(self.app.menu_options, [])

    def test_esc_when_running_and_not_pending_shows_warning_only(self):
        """First Esc press on a running agent tab shows warning, no abort."""
        self.app.current_tab = "m3"
        with self.hub.lock:
            self.hub.statuses["m3"] = terminal_app.STATUS_ACTIVE
            self.hub.running = 1
            self.hub.session_tags.add("m3")
        try:
            with mock.patch.object(self.app, "_execute_esc_abort") as mock_abort:
                self.app._handle_esc()
                mock_abort.assert_not_called()
            # Pending state is set.
            self.assertEqual(self.app._esc_pending_tag, "m3")
            self.assertGreater(self.app._esc_pending_time, 0)
            # Warning was shown.
            warnings = [
                text for _tag, text in self.app.console_lines
                if "ESC" in text and "M3" in text
            ]
            self.assertTrue(warnings, "Expected M3 warning")
        finally:
            with self.hub.lock:
                self.hub.running = 0
                self.hub.session_tags.clear()
                for t, _, _ in AGENTS:
                    self.hub.statuses[t] = terminal_app.STATUS_IDLE

    # -------------------------------------------------- idempotency

    def test_clear_esc_state_is_idempotent(self):
        self.app._clear_esc_state()
        self.assertIsNone(self.app._esc_pending_tag)
        # Calling again is safe.
        self.app._clear_esc_state()
        self.assertIsNone(self.app._esc_pending_tag)

    def test_help_text_references_esc(self):
        text = terminal_app.build_help_text()
        self.assertIn("Esc", text)
        self.assertIn("abort", text.lower())

    # -------------------------------------------------- Esc in model bar

    def test_model_bar_shows_esc_pending_master(self):
        """When Esc is pending on master, RUN block shows 'abort ALL'."""
        with self.hub.lock:
            self.hub.running = 3
        fragments = _model_bar_fragments(
            {"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}},
            None,
            "master",
            esc_pending_tag="master",
        )
        text = "".join(fragment[1] for fragment in fragments)
        self.assertIn("ESC", text)
        self.assertIn("abort ALL", text)
        with self.hub.lock:
            self.hub.running = 0

    def test_model_bar_shows_esc_pending_agent(self):
        """When Esc is pending on M4, RUN block shows 'abort M4'."""
        with self.hub.lock:
            self.hub.running = 2
        fragments = _model_bar_fragments(
            {"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}},
            None,
            "m4",
            esc_pending_tag="m4",
        )
        text = "".join(fragment[1] for fragment in fragments)
        self.assertIn("ESC", text)
        self.assertIn("abort M4", text)
        self.assertNotIn("abort ALL", text)
        with self.hub.lock:
            self.hub.running = 0

    def test_model_bar_no_esc_when_idle(self):
        """No Esc indicator when running is 0 (nothing to abort)."""
        fragments = _model_bar_fragments(
            {"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}},
            None,
            "master",
            esc_pending_tag="master",
        )
        text = "".join(fragment[1] for fragment in fragments)
        self.assertNotIn("ESC", text)

    def test_model_bar_no_esc_when_none(self):
        """No Esc indicator when esc_pending_tag is None."""
        with self.hub.lock:
            self.hub.running = 1
        fragments = _model_bar_fragments(
            {"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}},
            None,
            "master",
            esc_pending_tag=None,
        )
        text = "".join(fragment[1] for fragment in fragments)
        self.assertNotIn("ESC", text)
        with self.hub.lock:
            self.hub.running = 0


class AbortStateResetTestCase(unittest.TestCase):
    """Bulletproof UI state reset after abort: no stuck progress bars or
    stale status indicators survive termination."""

    def setUp(self):
        self.hub = terminal_app.RunHub()

    def test_force_ui_idle_resets_all_seven_agents(self):
        """force_ui_idle() sets every agent to IDLE with 0 progress & tokens."""
        with self.hub.lock:
            # Dirty the state: set every agent to something non-idle.
            for tag, _name, _agent in terminal_app.AGENTS:
                self.hub.statuses[tag] = terminal_app.STATUS_ACTIVE
                self.hub.progress[tag] = 77
                self.hub.token_usage[tag] = 88
            self.hub.running = 7
            self.hub.session_tags = {"m1", "m2", "m3", "m4", "m5", "m6", "m7"}
        self.hub.force_ui_idle()
        self.assertEqual(self.hub.running, 0)
        self.assertEqual(self.hub.session_tags, set())
        for tag, _name, _agent in terminal_app.AGENTS:
            self.assertEqual(self.hub.statuses[tag], terminal_app.STATUS_IDLE,
                             f"{tag} status not IDLE")
            self.assertEqual(self.hub.progress[tag], 0,
                             f"{tag} progress not 0")
            self.assertEqual(self.hub.token_usage[tag], 0,
                             f"{tag} token_usage not 0")

    def test_terminate_agent_resets_progress_when_no_proc(self):
        """Even when no subprocess is running, terminate_agent resets
        stale progress to 0 so the loading bar never shows old values."""
        with self.hub.lock:
            self.hub.statuses["m4"] = terminal_app.STATUS_IDLE
            self.hub.progress["m4"] = 100  # stale from a previous finished run
        # No proc present — terminate_agent should still reset progress.
        result = self.hub.terminate_agent("m4")
        self.assertFalse(result)  # no process was killed
        self.assertEqual(self.hub.progress["m4"], 0,
                         "stale progress must be reset even when no proc")

    def test_terminate_all_resets_non_active_agents_too(self):
        """terminate_all() resets ALL seven agents — not only the currently
        active ones — so no stale values from previously completed runs stick."""
        with self.hub.lock:
            # M1 is active, M2 is idle with stale progress from a prior run.
            self.hub.statuses["m1"] = terminal_app.STATUS_ACTIVE
            self.hub.progress["m1"] = 50
            self.hub.statuses["m2"] = terminal_app.STATUS_IDLE
            self.hub.progress["m2"] = 100  # stale
            self.hub.token_usage["m2"] = 99  # stale
            self.hub.procs["m1"] = mock.MagicMock()
            self.hub.running = 1
        self.hub.terminate_all()
        # Both agents must be reset regardless of prior status.
        self.assertEqual(self.hub.statuses["m1"], terminal_app.STATUS_IDLE)
        self.assertEqual(self.hub.progress["m1"], 0)
        self.assertEqual(self.hub.statuses["m2"], terminal_app.STATUS_IDLE)
        self.assertEqual(self.hub.progress["m2"], 0)
        self.assertEqual(self.hub.token_usage["m2"], 0)

    def test_cmd_stop_clears_esc_pending_state(self):
        """The /stop command clears any pending Esc abort state so the RUN
        block immediately reverts to a clean display."""
        app = terminal_app.RetroTerminalApp()
        app._esc_pending_tag = "master"
        app._esc_pending_time = time.monotonic()
        with app.hub.lock:
            app.hub.statuses["m1"] = terminal_app.STATUS_ACTIVE
            app.hub.procs["m1"] = mock.MagicMock()
            app.hub.running = 1
        result = app._cmd_stop("")
        self.assertIn("stopped", result)
        self.assertIsNone(app._esc_pending_tag)
        self.assertEqual(app._esc_pending_time, 0.0)

    def test_force_ui_idle_signals_audit_thread_to_suppress_output(self):
        """force_ui_idle() sets _abort_event so a still-running M7 audit
        thread discards its log lines instead of streaming into a dead hub."""
        # Simulate an in-flight audit thread.
        self.hub._abort_event.clear()
        self.hub._audit_thread = threading.Thread(target=lambda: None)
        self.hub.force_ui_idle()
        self.assertTrue(self.hub._abort_event.is_set(),
                        "_abort_event must be set so audit output is suppressed")
        self.assertIsNone(self.hub._audit_thread,
                          "_audit_thread reference cleared on abort")

    def test_new_dispatch_clears_abort_event(self):
        """Starting a new dispatch resets _abort_event so subsequent M7
        audit results ARE logged normally."""
        self.hub._abort_event.set()  # dirty from a prior abort
        # Simulate a minimal dispatch: set running > 0 and a targets list.
        with self.hub.lock:
            self.hub.running = 0  # will trigger _abort_event.clear() below
        # Call run with a dummy prompt — it will try to spawn opencode which
        # won't exist, but we only care about the _abort_event.clear() side
        # effect which happens before subprocess creation.
        try:
            self.hub.run("test prompt", {}, agents=["m7"])
        except Exception:
            pass  # expected — opencode not on test PATH
        # The _abort_event should be cleared because running was 0 at dispatch.
        self.assertFalse(self.hub._abort_event.is_set(),
                         "_abort_event must be cleared on new session dispatch")
        # Clean up: force_ui_idle to reset the hub after the failed dispatch.
        self.hub.force_ui_idle()
        with self.hub.lock:
            self.hub.running = 0
            self.hub.session_tags.clear()
            self.hub.procs.clear()


class SettingsModalTestCase(unittest.TestCase):
    """Headless coverage for the settings modal state and persistence contract."""

    def setUp(self):
        self._orig_state = terminal_app.STATE
        self._tmp = tempfile.TemporaryDirectory()
        terminal_app.STATE = StateTracker(path=Path(self._tmp.name) / "state.md")

    def tearDown(self):
        terminal_app.STATE = self._orig_state
        self._tmp.cleanup()

    def test_modal_opens_renders_sections_and_can_cancel(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        rendered = "".join(fragment[1] for fragment in app._settings_fragments())
        self.assertTrue(app.settings_open)
        for label in ("AGENT MAPPING", "AI MODEL", "OPERATING MODE", "COLOR THEME", "LAYOUT DENSITY", "AGENT TOGGLES", "SAVE & APPLY", "CANCEL"):
            self.assertIn(label, rendered)
        self.assertIn("ENTER TO CUSTOMIZE", rendered)
        for tag, name, _agent in AGENTS:
            self.assertNotIn(f"{tag.upper()} {name}", rendered)
        self.assertTrue(any(len(fragment) == 3 for fragment in app._settings_fragments()))
        app.close_settings(save=False)
        self.assertFalse(app.settings_open)
        self.assertIsNone(terminal_app.STATE.load())

    def test_agent_toggle_submenu_lists_all_agents_without_inline_rows(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        main = "".join(fragment[1] for fragment in app._settings_fragments())
        self.assertIn("AGENT TOGGLES", main)
        self.assertIn("ENTER TO CUSTOMIZE", main)
        self.assertNotIn("M1: Matthew", main)

        app.open_agent_menu()
        submenu = "".join(fragment[1] for fragment in app._settings_fragments())
        self.assertTrue(app.agent_menu_open)
        self.assertEqual(submenu.count("[ ON ]"), 7)
        for index, (_tag, name, _agent) in enumerate(AGENTS):
            self.assertIn(f"M{index + 1}: {name}", submenu)
        app.close_settings(save=False)

    def test_agent_toggle_draft_save_persists_and_hides_tab(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        app.settings_focus = app._settings_fields().index("agent_toggles")
        app._settings_cycle(1)  # open dedicated submenu
        self.assertTrue(app.agent_menu_open)
        field = "agent_toggle_m3"
        app.agent_focus = app._agent_toggle_fields().index(field)
        app._agent_cycle(1)  # ON -> OFF
        self.assertIn("m3", app.enabled_agents)
        self.assertNotIn("m3", app.settings_draft["enabled_agents"])
        # The committed app remains unchanged until Save & Apply.
        app.close_settings(save=False)
        self.assertIn("m3", app.enabled_agents)

        app.toggle_settings()
        app.settings_focus = app._settings_fields().index("agent_toggles")
        app.open_agent_menu()
        app.agent_focus = app._agent_toggle_fields().index(field)
        app._agent_cycle(1)
        app.close_settings(save=True)
        self.assertNotIn("m3", app.enabled_agents)
        self.assertNotIn("m3", app._tab_order())
        dashboard = "".join(text for _style, text in terminal_app._dashboard_fragments({}, enabled_agents=app.enabled_agents))
        self.assertNotIn("M3 Sarah", dashboard)
        self.assertNotIn("m3", terminal_app.STATE.load()["settings"]["enabled_agents"])

        reloaded = RetroTerminalApp()
        self.assertNotIn("m3", reloaded.enabled_agents)

    def test_save_applies_mapping_and_terminal_settings_and_roundtrips(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        app.settings_draft["target"] = "m4"
        app._settings_set_mapping("model", "opencode/big-pickle")
        app._settings_set_mapping("mode", "build")
        app.settings_draft["theme"] = "amber"
        app.settings_draft["font_size"] = "large"
        app.settings_draft["density"] = "spacious"
        app.settings_draft["panel_borders"] = False
        app.close_settings(save=True)

        self.assertFalse(app.settings_open)
        self.assertEqual(app.overrides["m4"]["model"], "opencode/big-pickle")
        self.assertEqual(app.overrides["m4"]["mode"], "build")
        self.assertEqual(app.terminal_settings["theme"], "amber")
        self.assertFalse(app.terminal_settings["panel_borders"])
        persisted = terminal_app.STATE.load()["settings"]
        self.assertEqual(persisted["overrides"]["m4"]["mode"], "build")

        reloaded = RetroTerminalApp()
        self.assertEqual(reloaded.overrides["m4"]["model"], "opencode/big-pickle")
        self.assertEqual(reloaded.terminal_settings["theme"], "amber")
        self.assertEqual(reloaded.terminal_settings["font_size"], "large")
        self.assertFalse(reloaded.terminal_settings["panel_borders"])

    def test_m7_mapping_is_locked_in_modal_and_resolver(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        app.settings_draft["target"] = "m7"
        app._settings_set_mapping("model", "opencode/big-pickle")
        app._settings_set_mapping("mode", "build")
        self.assertEqual(app._settings_value("model"), "opencode/ling-3.0-tiny-free")
        self.assertEqual(app._settings_value("mode"), M7_AUDIT_MODE)
        app.close_settings(save=True)
        self.assertEqual(app.hub.resolve("m7", app.overrides), ("opencode/ling-3.0-tiny-free", M7_AUDIT_MODE))

    def test_headless_theme_entry_and_escape_key_sequence(self):
        import asyncio
        import io
        from prompt_toolkit.key_binding import KeyPress
        from prompt_toolkit.keys import Keys
        from prompt_toolkit.output.vt100 import Vt100_Output

        class FixedSize:
            columns = 110
            rows = 40

        async def run_keys():
            app = RetroTerminalApp()
            app.toggle_settings()
            app.settings_focus = app._settings_fields().index("theme")
            output = Vt100_Output(io.StringIO(), get_size=lambda: FixedSize())
            instance = app._build_application(
                input=QueuedInput([
                    KeyPress(Keys.Enter),   # main COLOR THEME -> submenu
                    KeyPress(Keys.Escape),  # submenu -> main settings
                    KeyPress(Keys.Escape),  # main settings -> cancel/close
                ]),
                output=output,
            )

            async def stop():
                await asyncio.sleep(0.3)
                instance.exit()

            instance.create_background_task(stop())
            await instance.run_async()
            return app

        app = asyncio.run(run_keys())
        self.assertFalse(app.settings_open)
        self.assertFalse(app.theme_menu_open)
        self.assertEqual(app.buffer.text, "")

    def test_theme_submenu_slices_rows_on_short_terminals_and_keeps_actions(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        app.open_theme_menu()
        fields = app._theme_fields()
        app.settings_height = 10
        app.theme_focus = fields.index("active_tabs")
        visible = app._theme_visible_indices(fields)
        visible_fields = [fields[i] for i in visible]
        self.assertIn("save", visible_fields)
        self.assertIn("back", visible_fields)
        self.assertIn(app.theme_focus, visible)

        app.settings_height = 5
        rendered = "".join(fragment[1] for fragment in app._settings_fragments())
        self.assertLessEqual(len(rendered.splitlines()), 5)
        self.assertIn("SAVE & APPLY", rendered)
        app.close_settings(save=False)

    def test_theme_submenu_renders_categories_and_component_rows(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        app.settings_focus = app._settings_fields().index("theme")
        app.open_theme_menu()
        rendered = "".join(fragment[1] for fragment in app._settings_fragments())

        self.assertTrue(app.theme_menu_open)
        for category in (
            "CODE & TEXT STREAMS",
            "HEADERS & TABS",
            "WINDOWS & PANEL BORDERS",
            "INPUT & ACTION BOXES",
        ):
            self.assertIn(category, rendered)
        for _key, label, _category in terminal_app.COLOR_COMPONENTS:
            self.assertIn(label, rendered)
        self.assertIn("BACK TO SETTINGS", rendered)
        app.close_settings(save=False)

    def test_theme_arrow_preview_is_live_but_cancel_rolls_back(self):
        app = RetroTerminalApp()
        original_style = dict(app._style_dict)
        original_color = terminal_app._DEFAULT_COMPONENT_COLORS["zova"]["execution_logs"]
        app.toggle_settings()
        app.open_theme_menu()
        app.theme_focus = app._theme_fields().index("execution_logs")
        app._theme_cycle(1)

        preview_color = app._theme_value("execution_logs")
        self.assertNotEqual(preview_color, original_color)
        self.assertIn(preview_color, app._style_dict["retro.panel.execution"])
        self.assertIsNone(terminal_app.STATE.load())

        app.close_settings(save=False)
        self.assertFalse(app.settings_open)
        self.assertEqual(app.terminal_settings["theme_colors"], {})
        self.assertEqual(app._style_dict, original_style)

    def test_theme_component_save_persists_and_roundtrips(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        app.open_theme_menu()
        app.theme_focus = app._theme_fields().index("active_tabs")
        app._theme_cycle(1)
        saved_color = app._theme_value("active_tabs")
        app.close_settings(save=True)

        self.assertEqual(app.terminal_settings["theme_colors"]["zova"]["active_tabs"], saved_color)
        persisted = terminal_app.STATE.load()["settings"]["terminal"]
        self.assertEqual(persisted["theme_colors"]["zova"]["active_tabs"], saved_color)

        reloaded = RetroTerminalApp()
        self.assertEqual(
            reloaded._style_dict["retro.tab.active"],
            f"bold bg:{terminal_app.GREY_BG} fg:{saved_color}",
        )

    def test_component_streams_use_granular_style_classes(self):
        for kind, style_name in (
            (terminal_app.BLOCK_EXECUTION, "retro.panel.execution"),
            (terminal_app.BLOCK_THINKING, "retro.panel.thinking"),
            (terminal_app.BLOCK_TODO, "retro.panel.todo"),
        ):
            style = terminal_app._content_style(kind, "sample")
            self.assertIn("retro.panel.content", style)
            self.assertIn(style_name, style)

    def test_theme_row_click_opens_customizer(self):
        app = RetroTerminalApp()
        app.toggle_settings()
        theme_index = app._settings_fields().index("theme")
        fragments = app._settings_fragments()
        # The theme row is the first clickable row after the three header rows.
        theme_fragment = fragments[3 + theme_index]
        self.assertEqual(len(theme_fragment), 3)
        theme_fragment[2](None)
        self.assertTrue(app.theme_menu_open)
        app.close_settings(save=False)

    def test_settings_command_and_hotkey_handler_toggle_same_modal(self):
        app = RetroTerminalApp()
        self.assertIn("modal opened", app._cmd_settings(""))
        self.assertTrue(app.settings_open)
        app.toggle_settings()
        self.assertFalse(app.settings_open)


if __name__ == "__main__":
    unittest.main()
