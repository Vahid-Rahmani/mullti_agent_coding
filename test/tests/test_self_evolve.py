"""Unit tests for scripts/self_evolve.py (SelfEvolveEngine)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from self_evolve import (
    FAILURE_SIGNATURES,
    LOOP_THRESHOLD,
    Proposal,
    SelfEvolveEngine,
    detect_optimization_loops,
)


class FailureSignaturesTestCase(unittest.TestCase):
    """FAILURE_SIGNATURES contains the documented failure patterns."""

    def test_signatures_nonempty(self):
        self.assertGreater(len(FAILURE_SIGNATURES), 0)

    def test_contains_documented_patterns(self):
        sources = [p.pattern for p in FAILURE_SIGNATURES]
        for expected in ["exit code", "Error:", "Traceback", "ERROR:"]:
            self.assertTrue(
                any(expected in src for src in sources),
                f"missing pattern for {expected!r}",
            )


class DetectOptimizationLoopsTestCase(unittest.TestCase):
    """detect_optimization_loops scans _logs/*.log for repeated failures."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmp.name) / "_logs"

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_logs_returns_empty(self):
        self.assertEqual(detect_optimization_loops(self.log_dir), [])

    def test_missing_log_dir_returns_empty(self):
        missing = Path(self._tmp.name) / "does-not-exist"
        self.assertEqual(detect_optimization_loops(missing), [])

    def test_below_threshold_no_proposal(self):
        _init_log(self.log_dir, "david.log", ["Error: one", "Error: two"])
        self.assertEqual(detect_optimization_loops(self.log_dir), [])

    def test_threshold_met_creates_proposal(self):
        _init_log(
            self.log_dir,
            "david.log",
            ["Error: one", "Error: two", "Error: three"],
        )
        proposals = detect_optimization_loops(self.log_dir)
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.agent, "david")
        self.assertEqual(proposal.count, 3)
        self.assertGreaterEqual(proposal.count, LOOP_THRESHOLD)
        self.assertTrue(proposal.suggestion)

    def test_agent_name_from_filename(self):
        _init_log(
            self.log_dir,
            "alex.log",
            ["Error: a", "Error: b", "Error: c"],
        )
        proposals = detect_optimization_loops(self.log_dir)
        self.assertEqual(proposals[0].agent, "alex")

    def test_multiple_signatures_counted_separately(self):
        _init_log(
            self.log_dir,
            "max.log",
            [
                "Error: a",
                "Error: b",
                "Error: c",
                "Traceback (most recent call last):",
                "Traceback (most recent call last):",
                "Traceback (most recent call last):",
            ],
        )
        proposals = detect_optimization_loops(self.log_dir)
        signatures = {p.signature for p in proposals}
        self.assertIn("Error:", signatures)
        self.assertIn("Traceback", signatures)

    def test_multiple_agents_produce_separate_proposals(self):
        _init_log(
            self.log_dir,
            "david.log",
            ["Error: a", "Error: b", "Error: c"],
        )
        _init_log(
            self.log_dir,
            "elena.log",
            ["Error: x", "Error: y", "Error: z"],
        )
        proposals = detect_optimization_loops(self.log_dir)
        agents = {p.agent for p in proposals}
        self.assertEqual(agents, {"david", "elena"})

    def test_proposal_id_is_unique_per_agent_signature(self):
        _init_log(
            self.log_dir,
            "david.log",
            ["Error: a", "Error: b", "Error: c"],
        )
        proposals = detect_optimization_loops(self.log_dir)
        ids = [p.id for p in proposals]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(ids))


class AllowPathTestCase(unittest.TestCase):
    """allow_path restricts writes to PROJECT_ROOT."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.engine = SelfEvolveEngine(project_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_allow_inside_root(self):
        self.assertTrue(self.engine.allow_path(self.root / "scripts" / "terminal_app.py"))

    def test_allow_root_itself(self):
        self.assertTrue(self.engine.allow_path(self.root))

    def test_deny_outside_root(self):
        outside = Path(self._tmp.name) / ".." / "outside.txt"
        self.assertFalse(self.engine.allow_path(outside))

    def test_deny_sibling_directory(self):
        sibling = self.root.parent / "sibling.txt"
        self.assertFalse(self.engine.allow_path(sibling))

    def test_deny_traversal_escape(self):
        escape = self.root / ".." / "escape.txt"
        self.assertFalse(self.engine.allow_path(escape))


class CheckpointTestCase(unittest.TestCase):
    """checkpoint() records a decision plus the git HEAD."""

    def test_checkpoint_records_decision_and_git_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            decisions: list[str] = []
            engine = SelfEvolveEngine(
                project_root=root,
                record_decision=lambda text: decisions.append(text),
            )
            result = engine.checkpoint("upgrade everything")
            self.assertEqual(result["prompt"], "upgrade everything")
            self.assertTrue(result["git_head"])
            self.assertEqual(len(decisions), 1)
            self.assertIn("upgrade everything", decisions[0])
            self.assertIn(result["git_head"], decisions[0])

    def test_checkpoint_without_record_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_git_repo(root)
            engine = SelfEvolveEngine(project_root=root)
            result = engine.checkpoint("self-heal")
            self.assertEqual(result["prompt"], "self-heal")
            self.assertTrue(result["git_head"])

    def test_checkpoint_handles_non_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = SelfEvolveEngine(project_root=root)
            result = engine.checkpoint("upgrade")
            self.assertEqual(result["git_head"], "")


class RestartMarkerTestCase(unittest.TestCase):
    """write/read_restart_marker round-trips JSON at _logs/restart.ctl."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.engine = SelfEvolveEngine(project_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_marker_roundtrip(self):
        control = self.root / "_logs" / "restart.ctl"
        self.engine.write_restart_marker(
            control_path=control, payload={"reason": "upgrade", "ok": True}
        )
        data = self.engine.read_restart_marker(control_path=control)
        self.assertEqual(data["reason"], "upgrade")
        self.assertTrue(data["ok"])

    def test_read_missing_returns_none(self):
        control = self.root / "_logs" / "restart.ctl"
        self.assertIsNone(self.engine.read_restart_marker(control_path=control))

    def test_read_corrupt_returns_none(self):
        control = self.root / "_logs" / "restart.ctl"
        control.parent.mkdir(parents=True, exist_ok=True)
        control.write_text("{not json", encoding="utf-8")
        self.assertIsNone(self.engine.read_restart_marker(control_path=control))

    def test_write_creates_parent_directory(self):
        control = self.root / "nested" / "restart.ctl"
        self.engine.write_restart_marker(control_path=control, payload={"reason": "x"})
        self.assertTrue(control.exists())

    def test_default_path_is_logs_restart_ctl(self):
        self.engine.write_restart_marker(payload={"reason": "x"})
        default = self.root / "_logs" / "restart.ctl"
        self.assertTrue(default.exists())
        self.assertEqual(
            self.engine.read_restart_marker()["reason"], "x"
        )

    def test_write_is_atomic_leaves_no_temp_files(self):
        control = self.root / "_logs" / "restart.ctl"
        self.engine.write_restart_marker(control_path=control, payload={"reason": "x"})
        leftovers = list((self.root / "_logs").glob("*.tmp"))
        self.assertEqual(leftovers, [])


class VerifyTestCase(unittest.TestCase):
    """verify() py_compiles scripts, JSON-parses opencode.json, runs tests."""

    def _make_project(
        self, tmp: Path, scripts: dict, tests: dict, config: str = "{}"
    ) -> Path:
        root = Path(tmp)
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        for name, body in scripts.items():
            (root / "scripts" / name).write_text(body, encoding="utf-8")
        (root / "opencode.json").write_text(config, encoding="utf-8")
        (root / "test").mkdir(parents=True, exist_ok=True)
        (root / "test" / "__init__.py").write_text("", encoding="utf-8")
        (root / "test" / "tests").mkdir(parents=True, exist_ok=True)
        (root / "test" / "tests" / "__init__.py").write_text("", encoding="utf-8")
        for name, body in tests.items():
            (root / "test" / "tests" / name).write_text(body, encoding="utf-8")
        return root

    def test_verify_happy_path_on_temp_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(
                tmp,
                scripts={"sample.py": "def add(a, b):\n    return a + b\n"},
                config='{"default_agent": "build"}',
                tests={
                    "test_sample.py": (
                        "import unittest\n"
                        "class T(unittest.TestCase):\n"
                        "    def test_ok(self):\n"
                        "        self.assertEqual(1, 1)\n"
                    )
                },
            )
            engine = SelfEvolveEngine(project_root=root)
            result = engine.verify(root)
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["errors"], [])
            self.assertIn("OK", result["stdout"])

    def test_verify_reports_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(
                tmp,
                scripts={"broken.py": "def broken(:\n"},
                tests={},
            )
            engine = SelfEvolveEngine(project_root=root)
            result = engine.verify(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("broken.py" in e for e in result["errors"]))

    def test_verify_reports_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(
                tmp,
                scripts={"sample.py": "x = 1\n"},
                tests={},
                config="{not valid json",
            )
            engine = SelfEvolveEngine(project_root=root)
            result = engine.verify(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("opencode.json" in e for e in result["errors"]))

    def test_verify_reports_failing_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_project(
                tmp,
                scripts={"sample.py": "x = 1\n"},
                tests={
                    "test_fail.py": (
                        "import unittest\n"
                        "class T(unittest.TestCase):\n"
                        "    def test_fail(self):\n"
                        "        self.assertEqual(1, 2)\n"
                    )
                },
                config="{}",
            )
            engine = SelfEvolveEngine(project_root=root)
            result = engine.verify(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("unittest" in e for e in result["errors"]))


def _init_log(log_dir: Path, name: str, lines: list[str]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=str(root), check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    (root / "README.md").write_text("test", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(root), check=True)


if __name__ == "__main__":
    unittest.main()