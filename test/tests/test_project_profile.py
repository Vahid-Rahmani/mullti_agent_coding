"""Unit tests for scripts/core/project_profile.py — repository analysis.

Encodes the intended architecture: a repository is analyzed read-only into a
``ProjectProfile`` (technologies, manifests, instructions, suggested roles).
Suggestions are *never* auto-applied — they are suggested until the user
approves by assigning the role in ``roles.json``.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import project_profile  # noqa: E402
from scripts.core import roles  # noqa: E402


def _seed(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class AnalyzeRepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_repo_still_suggests_universal_roles(self):
        profile = project_profile.analyze_repository(self.root)
        self.assertIn("code-reviewer", profile.suggested_roles)
        self.assertIn("software-architect", profile.suggested_roles)
        self.assertEqual(profile.technologies, ())

    def test_python_requirements_detected(self):
        _seed(self.root, {"requirements.txt": "fastapi\nuvicorn\n"})
        profile = project_profile.analyze_repository(self.root)
        self.assertIn("python", profile.technologies)
        self.assertIn("fastapi", profile.technologies)
        self.assertIn("python-developer", profile.suggested_roles)
        self.assertIn("fastapi-developer", profile.suggested_roles)

    def test_ai_agents_signal_from_opencode_json(self):
        _seed(self.root, {"opencode.json": "{}"})
        profile = project_profile.analyze_repository(self.root)
        self.assertIn("ai-agents", profile.technologies)
        self.assertIn("ai-agent-engineer", profile.suggested_roles)

    def test_docker_ci_signals(self):
        _seed(self.root, {
            "Dockerfile": "FROM python:3.11",
            ".github/workflows/ci.yml": "name: ci",
        })
        profile = project_profile.analyze_repository(self.root)
        self.assertIn("docker", profile.technologies)
        self.assertIn("ci", profile.technologies)
        self.assertIn("devops-engineer", profile.suggested_roles)

    def test_instructions_captured(self):
        _seed(self.root, {"AGENTS.md": "# Agents"})
        profile = project_profile.analyze_repository(self.root)
        self.assertIn("AGENTS.md", profile.instructions)

    def test_analysis_is_read_only(self):
        _seed(self.root, {"requirements.txt": "fastapi\n"})
        before = {p.name: p.read_text(encoding="utf-8")
                  for p in self.root.rglob("*") if p.is_file()}
        project_profile.analyze_repository(self.root)
        after = {p.name: p.read_text(encoding="utf-8")
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class SuggestRolesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _seed(self.root, {"requirements.txt": "fastapi\n"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_approved_roles_excluded_from_suggestions(self):
        profile = project_profile.analyze_repository(self.root)
        self.assertIn("python-developer", project_profile.suggest_roles(profile))
        # Approving a suggestion = defining + assigning the role (never auto).
        roles.create_role("python-developer", repo_root=self.root)
        roles.assign_roles("matthew", ["python-developer"], self.root)
        profile = project_profile.analyze_repository(self.root)
        self.assertNotIn("python-developer", project_profile.suggest_roles(profile))
        self.assertIn("python-developer", profile.approved_roles)


class RenderContextTestCase(unittest.TestCase):
    def test_render_project_context_technologies(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        _seed(root, {"requirements.txt": "fastapi\n", "AGENTS.md": "# Agents"})
        ctx = project_profile.render_project_context(repo_root=root)
        self.assertIn("## Project Profile", ctx)
        self.assertIn("fastapi", ctx)
        self.assertIn("## Repository Instructions (AGENTS.md)", ctx)


if __name__ == "__main__":
    unittest.main()
