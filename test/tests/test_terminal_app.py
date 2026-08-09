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
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import terminal_app
from terminal_app import (
    AGENTS,
    AUTO_MODE,
    AUTO_MODEL,
    BANNER,
    MODEL_OPTIONS,
    MODE_OPTIONS_BY_MODEL,
    RetroTerminalApp,
    RunHub,
    StateTracker,
    _agent_progress_fragments,
    _build_run_command,
    _classify_block,
    _console_fragments,
    _panel_groups,
    _run_header,
    _dashboard_fragments,
    _dir_line,
    _model_bar,
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
)


class ModelConstantsTestCase(unittest.TestCase):
    """Model/mode constants match the removed GUI's contract."""

    def test_auto_model_is_first_option(self):
        self.assertEqual(MODEL_OPTIONS[0], AUTO_MODEL)

    def test_model_options_include_free_models(self):
        self.assertIn("opencode/deepseek-v4-flash-free", MODEL_OPTIONS)
        self.assertIn("opencode/ling-3.0-tiny-free", MODEL_OPTIONS)
        self.assertIn("opencode/big-pickle", MODEL_OPTIONS)

    def test_agents_are_seven(self):
        self.assertEqual(len(AGENTS), 7)
        tags = [tag for tag, _, _ in AGENTS]
        self.assertEqual(tags, [f"m{i}" for i in range(1, 8)])


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


class BuildRunCommandTestCase(unittest.TestCase):
    """The opencode run argv builder (ported from the removed GUI)."""

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

    def test_auto_mode_keeps_default_agent(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "run tests", None, AUTO_MODE),
            ["opencode", "run", "--agent", "tester", "--auto", "run tests"],
        )

    def test_dash_leading_prompt_is_guarded_with_double_dash(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "- Peer-Assistance review", None),
            ["opencode", "run", "--agent", "tester", "--auto", "--", "- Peer-Assistance review"],
        )

    def test_dash_leading_prompt_with_model_guard(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "- upgrade system", "opencode/big-pickle"),
            [
                "opencode",
                "run",
                "--agent",
                "tester",
                "--auto",
                "-m",
                "opencode/big-pickle",
                "--",
                "- upgrade system",
            ],
        )

    def test_control_characters_stripped_from_prompt(self):
        self.assertEqual(
            _build_run_command("opencode", "tester", "run\x00\x07 tests", None),
            ["opencode", "run", "--agent", "tester", "--auto", "run tests"],
        )

    def test_spaces_and_hyphens_inside_prompt_stay_single_element(self):
        cmd = _build_run_command("opencode", "tester", "Fix 'Peer-Assistance' & run tests", None)
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
            self.hub._run_agent("m1", "system-architect", "prompt", None, None)
        data = terminal_app.STATE.load()
        self.assertIn("m1: ok", data["completed"])

    def test_run_agent_records_finish_failed(self):
        proc = _FakeProc(returncode=3)
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m1", "system-architect", "prompt", None, None)
        data = terminal_app.STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_run_agent_records_finish_failed_on_exception(self):
        with mock.patch("terminal_app._opencode_command", return_value=None):
            self.hub._run_agent("m1", "system-architect", "prompt", None, None)
        data = terminal_app.STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_run_agent_guards_option_like_prompt(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc) as popen:
            self.hub._run_agent(
                "m1", "system-architect",
                "- Peer-Assistance handoff", None, None,
            )
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[-2:], ["--", "- Peer-Assistance handoff"])

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

    def test_palette_constants_match_spec(self):
        self.assertEqual(terminal_app.WHITE, "#ffffff")   # standard text
        self.assertEqual(terminal_app.ORANGE, "#ff8c00")  # keywords/important
        self.assertEqual(terminal_app.GREY, "#c4c8cc")    # neutral highlights
        self.assertEqual(terminal_app.NEON, terminal_app.WHITE) # compatibility alias, no green
        self.assertNotIn("#33ff33", terminal_app.NEON)

    def test_no_legacy_rainbow_constants(self):
        for name in ("TAG_COLORS", "NEON_BRIGHT", "NEON_DIM", "AMBER", "RED", "BOX"):
            self.assertFalse(hasattr(terminal_app, name), f"legacy {name} must be gone")

    def test_status_symbols_use_only_spec_colors(self):
        allowed = {terminal_app.GREY, terminal_app.ORANGE, terminal_app.NEON}
        for _symbol, color in terminal_app.STATUS_SYMBOL.values():
            self.assertIn(color, allowed)

    def test_tag_style_is_orange(self):
        self.assertIn(terminal_app.ORANGE, terminal_app._tag_style("m4"))

    def test_console_error_lines_are_orange_regular_white(self):
        frags = terminal_app._console_fragments([("m4", "ERROR: boom"), ("m4", "ok line")])
        styles = [style for style, _ in frags]
        self.assertTrue(any(terminal_app.ORANGE in s for s in styles))
        self.assertTrue(any("retro.console" in s for s in styles))


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

    def test_active_agent_has_progress_working_and_token_line(self):
        frags = _agent_progress_fragments(
            {"m4": terminal_app.STATUS_ACTIVE},
            {"m4": 45},
            {"m4": 32},
            current_tab="m4",
        )
        joined = "".join(text for _style, text in frags)
        self.assertIn("M4 Backend Dev", joined)
        self.assertIn("45%", joined)
        self.assertIn("working...", joined)
        self.assertIn("Token: 32% Used", joined)
        self.assertIn("approx.", joined)

    def test_idle_agents_do_not_show_loading_rows(self):
        frags = _agent_progress_fragments({tag: terminal_app.STATUS_IDLE for tag, _name, _agent in AGENTS})
        self.assertEqual(frags, [])

    def test_token_estimate_is_bounded(self):
        self.assertEqual(_estimate_token_percent("a" * (8192 * 4 // 2), []), 50)
        self.assertEqual(_estimate_token_percent("a" * (8192 * 4 * 10), []), 100)
        self.assertEqual(_estimate_token_percent("", []), 0)

    def test_input_style_is_bright_white(self):
        app = RetroTerminalApp()
        style = app._style_dict["retro.input"]
        self.assertIn(f"fg:{terminal_app.WHITE}", style)
        self.assertIn("bold", style)


class ChromeRenderTestCase(unittest.TestCase):
    """dir line, model bar, dashboard, console fragments."""

    def test_dir_line_contains_path(self):
        text = _dir_line(Path("tmp") / "workspace")
        self.assertIn("workspace", text)
        self.assertTrue(text.startswith("▶ DIR:"))

    def test_model_bar_reports_model_mode_target_running(self):
        bar = _model_bar({"master": {"model": "opencode/big-pickle", "mode": "plan"}}, ["m1", "m4"])
        self.assertIn("MODEL opencode/big-pickle", bar)
        self.assertIn("MODE plan", bar)
        self.assertIn("TARGET m1,m4", bar)
        self.assertIn("RUN 0/7", bar)

    def test_model_bar_auto_target_all(self):
        bar = _model_bar({"master": {"model": AUTO_MODEL, "mode": AUTO_MODE}}, None)
        self.assertIn("MODEL Auto", bar)
        self.assertIn("TARGET all", bar)

    def test_dashboard_has_all_seven_agents(self):
        frags = _dashboard_fragments({})
        joined = "".join(text for _, text in frags)
        for tag, name, _ in AGENTS:
            self.assertIn(tag.upper(), joined)
            self.assertIn(name, joined)

    def test_dashboard_maps_statuses(self):
        frags = _dashboard_fragments({"m1": "thinking", "m2": "error", "m3": "active"})
        joined = "".join(text for _, text in frags)
        # status glyphs: thinking ◐, error ✕, active ● bright
        self.assertIn("◐", joined)
        self.assertIn("✕", joined)
        self.assertIn("●", joined)

    def test_console_fragments_include_tag_and_text(self):
        frags = _console_fragments([("m4", "hello retro")])
        joined = "".join(text for _, text in frags)
        self.assertIn("[m4]", joined)
        self.assertIn("hello retro", joined)

    def test_help_text_documents_commands(self):
        help_text = build_help_text()
        for cmd in ("/help", "/cd", "/model", "/mode", "/agents", "/clear",
                    "/stop", "/swarm", "/evolve", "/quit"):
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
        self.assertIn("MODEL: opencode/big-pickle", self.app._cmd_model("opencode/big-pickle"))
        self.assertIn("ERROR", self.app._cmd_model("nope"))

    def test_mode_show_set_invalid(self):
        self.assertIn("MODE:", self.app._cmd_mode(""))
        self.app._cmd_model("opencode/big-pickle")
        self.assertIn("MODE: plan", self.app._cmd_mode("plan"))
        self.assertIn("ERROR", self.app._cmd_mode("architect"))

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
        # 'review' is not a big-pickle mode -> rejected for this tab
        self.assertIn("ERROR", self.app._cmd_mode("m4 review"))

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
            self.hub._run_agent("m4", "backend-dev", "prompt", None, None)
        # raw streamed lines, no embedded "[m4 Backend Dev]" prefix
        self.assertEqual(
            self.hub.buffers["m4"], ["hello from opencode", "second line"]
        )
        self.assertFalse(any("Backend Dev]" in line for line in self.hub.buffers["m4"]))

    def test_run_agent_error_has_no_embedded_tag(self):
        proc = _FakeProc(returncode=3)
        with mock.patch("terminal_app._opencode_command", return_value="opencode"), \
             mock.patch("terminal_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m4", "backend-dev", "prompt", None, None)
        err_lines = [e["text"] for e in self.hub.events if e["kind"] == "error"]
        self.assertEqual(err_lines[-1], "exit code 3")
        self.assertFalse(any("Backend Dev]" in text for text in err_lines))

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
        self.assertIn("◐ M1", frame)
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

    def test_frame_contains_tab_bar(self):
        frame = self._render()
        self.assertIn("MASTER", frame)
        self.assertIn("System Architect", frame)
        self.assertIn("Reviewer", frame)

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
        self.assertIn("TARGET m4", bar)

    def test_dashboard_marks_active_tab(self):
        frags = _dashboard_fragments({}, "m3")
        joined = "".join(text for _, text in frags)
        self.assertIn("MASTER", joined)  # master tab present
        self.assertIn("m3".upper(), joined)
        # active tab rendered with bracket highlight
        self.assertIn("[● M3 Planner]", joined)
        # inactive tabs not bracketed
        self.assertNotIn("[● M1", joined)


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


if __name__ == "__main__":
    unittest.main()
