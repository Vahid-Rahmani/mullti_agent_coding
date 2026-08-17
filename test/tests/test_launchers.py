"""Launcher environment-isolation regression tests.

The dashboard launcher (``launch_dashboard.bat``) must pin the project's own
virtual environment (``.venv\\Scripts\\python.exe``) and never resolve a bare
``python``/``py``/``uvicorn`` through PATH, so it cannot accidentally inherit a
global/Hermes/OpenCode Python environment.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DASHBOARD_LAUNCHER = REPO_ROOT / "launch_dashboard.bat"


def _command_lines(lines):
    """Executable lines only: drop blank lines, ``rem``/``::`` comments, labels,
    and the leading ``@`` (``@echo off``)."""
    out = []
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith(("rem", "::", ":", "@")):
            continue
        out.append(s)
    return out


class TestDashboardLauncherIsolation(unittest.TestCase):
    """The dashboard launcher must be pinned to the project-local interpreter."""

    @classmethod
    def setUpClass(cls):
        if not DASHBOARD_LAUNCHER.exists():
            raise unittest.SkipTest("launch_dashboard.bat not present in checkout")
        cls.content = DASHBOARD_LAUNCHER.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_pins_project_venv_interpreter(self):
        self.assertIn(r".venv\Scripts\python.exe", self.content)

    def test_root_resolved_relative_to_bat(self):
        # %~dp0 resolves the repo root relative to the .bat, never hardcoded.
        self.assertIn("%~dp0", self.content)

    def test_no_absolute_developer_path(self):
        # Never hard-code a developer's absolute path or the Hermes env.
        self.assertNotIn("AppData", self.content)
        self.assertNotRegex(self.content, r"[A-Za-z]:\\Users\\")

    def test_launch_uses_pinned_interpreter(self):
        # The line that starts the server must reference the pinned %PYTHON%.
        launch = [ln for ln in _command_lines(self.lines)
                  if "scripts.web_ui.server" in ln]
        self.assertTrue(launch, "no `scripts.web_ui.server` launch command found")
        for ln in launch:
            self.assertIn("%PYTHON%", ln)

    def test_no_bare_python_or_uvicorn_invocation(self):
        # No executable line may invoke python/py/python3/uvicorn through PATH.
        for ln in _command_lines(self.lines):
            self.assertNotRegex(
                ln,
                r"^\s*(python(\.exe)?|python3|py|uvicorn)(\s|$)",
                ln,
            )


if __name__ == "__main__":
    unittest.main()
