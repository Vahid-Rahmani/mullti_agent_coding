"""Initial browser-grid to FreeBuff PTY synchronization tests."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.core import freebuff_launcher
from scripts.core.providers.terminal import TerminalProcess


class _RecordingPty:
    spawned: ClassVar[list[tuple[tuple, dict]]] = []

    @classmethod
    def spawn(cls, *args, **kwargs):
        cls.spawned.append((args, kwargs))
        return types.SimpleNamespace(pid=123, isalive=lambda: False)


class _RecordingProcess:
    events: ClassVar[list[tuple]] = []

    def __init__(self, command, cwd, **kwargs):
        self.pid = 321
        self.events.append(("spawn", command, cwd, kwargs))

    def poll(self):
        return 1

    def write(self, text):
        self.events.append(("write", text))

    def resize(self, cols, rows):
        self.events.append(("resize", cols, rows))


class _LiveProcess(_RecordingProcess):
    def poll(self):
        return None


class InitialSyncTests(unittest.TestCase):
    def setUp(self):
        _RecordingProcess.events.clear()

    def test_terminal_process_passes_measured_dimensions_to_pywinpty(self):
        fake_winpty = types.SimpleNamespace(PtyProcess=_RecordingPty)
        _RecordingPty.spawned.clear()
        with mock.patch.dict(sys.modules, {"winpty": fake_winpty}):
            TerminalProcess("cmd.exe", REPO_ROOT, cols=133, rows=37)
        self.assertEqual(_RecordingPty.spawned[0][1]["dimensions"], (37, 133))

    def test_freebuff_writes_only_after_sized_process_creation(self):
        _RecordingProcess.events.clear()
        with mock.patch.object(freebuff_launcher, "_freebuff_executable", return_value="freebuff.CMD"), \
                mock.patch.object(freebuff_launcher, "TerminalProcess", _RecordingProcess):
            result = freebuff_launcher.launch_freebuff_cmd(
                "m1", REPO_ROOT, cols=133, rows=37,
            )
        self.assertEqual(result["cols"], 133)
        self.assertEqual(result["rows"], 37)
        self.assertEqual(_RecordingProcess.events[0],
                         ("spawn", "cmd.exe", REPO_ROOT, {"cols": 133, "rows": 37}))
        self.assertEqual([event[1] for event in _RecordingProcess.events[1:]], [
            f'cd /d "{REPO_ROOT}"\r', "freebuff\r",
        ])
        self.assertNotIn(("resize", 133, 37), _RecordingProcess.events)

    def test_freebuff_launch_rejects_missing_measured_dimensions(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            freebuff_launcher.launch_freebuff_cmd("m1", REPO_ROOT)

    def test_cmd_output_does_not_trigger_second_enter(self):
        proc = _RecordingProcess("cmd.exe", REPO_ROOT)
        tail, done = freebuff_launcher._observe_tui_bootstrap(
            proc, "Microsoft Windows [Version]\r\nC:>", "", False,
        )
        self.assertFalse(done)
        self.assertEqual(tail, "Microsoft Windows [Version]\r\nC:>"[-len(freebuff_launcher._READY_MARKER) + 1:])
        self.assertNotIn(("write", "\r"), proc.events)

    def test_alt_screen_alone_does_not_send_enter_before_ready_marker(self):
        proc = _RecordingProcess("cmd.exe", REPO_ROOT)
        tail, done = freebuff_launcher._observe_tui_bootstrap(
            proc, "before\x1b[?1049hafter", "", False,
        )
        tail, done = freebuff_launcher._observe_tui_bootstrap(
            proc, "redraw\x1b[?1049h", tail, done,
        )
        self.assertFalse(done)
        self.assertNotIn(("write", "\r"), proc.events)

    def test_ready_marker_in_one_chunk_sends_one_enter(self):
        proc = _RecordingProcess("cmd.exe", REPO_ROOT)
        _tail, done = freebuff_launcher._observe_tui_bootstrap(
            proc, "prefixStart coding for free", "", False,
        )
        self.assertTrue(done)
        self.assertEqual(proc.events.count(("write", "\r")), 1)

    def test_ready_marker_split_across_chunks_sends_one_enter(self):
        proc = _RecordingProcess("cmd.exe", REPO_ROOT)
        tail, done = freebuff_launcher._observe_tui_bootstrap(
            proc, "prefixStart coding ", "", False,
        )
        self.assertFalse(done)
        _tail, done = freebuff_launcher._observe_tui_bootstrap(
            proc, "for free and later redraw", tail, done,
        )
        self.assertTrue(done)
        self.assertEqual(proc.events.count(("write", "\r")), 1)

    def test_compact_input_marker_also_sends_one_enter(self):
        proc = _RecordingProcess("cmd.exe", REPO_ROOT)
        _tail, done = freebuff_launcher._observe_tui_bootstrap(
            proc, "header Enter a coding task or / for command", "", False,
        )
        self.assertTrue(done)
        self.assertEqual(proc.events.count(("write", "\r")), 1)

    def test_resize_and_user_input_do_not_trigger_bootstrap(self):
        proc = _LiveProcess("cmd.exe", REPO_ROOT)
        old = dict(freebuff_launcher._PROCESSES)
        try:
            freebuff_launcher._PROCESSES.clear()
            freebuff_launcher._PROCESSES["m1"] = proc
            self.assertTrue(freebuff_launcher.resize_input("m1", 100, 30))
            self.assertTrue(freebuff_launcher.write_input("m1", "\x1b[A"))
            self.assertEqual(proc.events[-2:], [("resize", 100, 30), ("write", "\x1b[A")])
            self.assertNotIn(("write", "\r"), proc.events)
        finally:
            freebuff_launcher._PROCESSES.clear()
            freebuff_launcher._PROCESSES.update(old)

    def test_reused_live_process_does_not_restart_bootstrap(self):
        proc = _LiveProcess("cmd.exe", REPO_ROOT)
        old = dict(freebuff_launcher._PROCESSES)
        try:
            freebuff_launcher._PROCESSES.clear()
            freebuff_launcher._PROCESSES["m1"] = proc
            with mock.patch.object(freebuff_launcher, "_freebuff_executable", return_value="freebuff.CMD"):
                result = freebuff_launcher.launch_freebuff_cmd(
                    "m1", REPO_ROOT, cols=100, rows=30,
                )
            self.assertEqual(result["state"], "reused")
            self.assertNotIn(("write", "\r"), proc.events)
            self.assertNotIn(("write", "freebuff\r"), proc.events)
        finally:
            freebuff_launcher._PROCESSES.clear()
            freebuff_launcher._PROCESSES.update(old)

    def test_local_terminal_assets_are_pinned_and_offline(self):
        index = (REPO_ROOT / "scripts/web_ui/static/index.html").read_text(encoding="utf-8")
        self.assertNotIn("cdn.jsdelivr.net", index)
        self.assertIn("/static/vendor/xterm/xterm.js", index)
        self.assertIn("/static/vendor/xterm-addon-fit/xterm-addon-fit.js", index)
        self.assertTrue((REPO_ROOT / "scripts/web_ui/static/vendor/xterm/xterm.js").is_file())
        self.assertTrue((REPO_ROOT / "scripts/web_ui/static/vendor/xterm-addon-fit/xterm-addon-fit.js").is_file())


if __name__ == "__main__":
    unittest.main()
