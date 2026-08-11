"""Unit tests for scripts/core/archivist.py (Architectural Obsidian Archivist).

Covers the five strict rules:
1. Intelligent Filtering — conversational text is ignored; architectural
   decisions, system mappings, and milestones are captured.
2. Context-Aware Storage — notes land in the resolved task project's
   ``docs/architecture/``, never the agent's own agent-log directory.
3. Graph Mapping — every note embeds a deterministic Mermaid.js map.
4. Maintenance Duty — refactors regenerate the project's architecture map.
5. Optimization — repetitive logs are summarized into one lean Evolution.md.
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import archivist
from scripts.core.agent_definitions import (
    ARCHIVIST_MODE,
    MODE_OPTIONS_BY_MODEL,
    MODE_TO_AGENT,
)


# --------------------------------------------------------------------------- Rule 1: filtering


class FilterArchivalContentTestCase(unittest.TestCase):
    """Rule 1 — ignore conversation, keep architecture decisions/mappings/milestones."""

    def test_conversational_text_is_ignored(self):
        for text in ("thanks!", "hello there", "great work", "cool", "hi"):
            result = archivist.filter_archival_content(text)
            self.assertFalse(result["archived"], text)
            self.assertEqual(result["entries"], [])

    def test_architectural_decision_is_captured(self):
        result = archivist.filter_archival_content(
            "Decision: switch prompt logs to JSONL with atomic writes."
        )
        self.assertTrue(result["archived"])
        self.assertEqual(len(result["entries"]), 1)
        self.assertIn("JSONL", result["entries"][0])

    def test_system_mapping_is_captured(self):
        result = archivist.filter_archival_content(
            "Map the agent routing: matthew -> alex -> sarah -> david."
        )
        self.assertTrue(result["archived"])
        self.assertIn("routing", result["entries"][0].lower())

    def test_milestone_is_captured(self):
        result = archivist.filter_archival_content("Milestone: v1.0 released")
        self.assertTrue(result["archived"])
        self.assertEqual(len(result["entries"]), 1)

    def test_strong_signal_fallback_on_multi_line_prompt(self):
        result = archivist.filter_archival_content(
            "We decided to refactor the run hub into core/ modules."
        )
        self.assertTrue(result["archived"])
        self.assertTrue(any("refactor" in e.lower() for e in result["entries"]))

    def test_empty_prompt_not_archived(self):
        result = archivist.filter_archival_content("   ")
        self.assertFalse(result["archived"])
        self.assertIn("empty", result["reason"])

    def test_entries_are_deduplicated(self):
        result = archivist.filter_archival_content(
            "Decision: A\nDecision: A\nDecision: B"
        )
        self.assertEqual(len(result["entries"]), 2)


# --------------------------------------------------------------------------- Rule 2: storage


class ResolveProjectDirTestCase(unittest.TestCase):
    """Rule 2 — resolve the task's project dir; never the agent's own dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        (self.workspace / "projects").mkdir()
        self.demo = self.workspace / "projects" / "demo"
        self.demo.mkdir()
        (self.demo / "app.py").write_text("x = 1\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_projects_registry_match_by_name(self):
        project = archivist.resolve_project_dir(
            "Update the demo project", self.workspace
        )
        self.assertEqual(project, self.demo)

    def test_path_hint_in_prompt(self):
        project = archivist.resolve_project_dir(
            f"refactor the project at {self.demo}", self.workspace
        )
        self.assertEqual(project, self.demo)

    def test_fallback_to_workspace(self):
        project = archivist.resolve_project_dir("hello", self.workspace)
        self.assertEqual(project.resolve(), self.workspace.resolve())

    def test_never_resolves_into_agent_logs(self):
        own_logs = self.workspace / "obsidian_vault" / "agents_logs"
        own_logs.mkdir(parents=True)
        project = archivist.resolve_project_dir(
            f"work in {own_logs}", self.workspace
        )
        self.assertEqual(project.resolve(), self.workspace.resolve())

    def test_docs_dir_is_inside_project(self):
        project_dir = self.workspace / "projects" / "demo"
        docs = archivist.docs_dir(project_dir)
        self.assertEqual(docs, project_dir / "docs" / "architecture")


# --------------------------------------------------------------------------- Rule 3: mermaid map


class GenerateMermaidMapTestCase(unittest.TestCase):
    """Rule 3 — deterministic Mermaid flowchart of the code structure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "demo"
        self.project.mkdir()
        (self.project / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        (self.project / "core").mkdir()
        (self.project / "core" / "__init__.py").write_text("", encoding="utf-8")
        (self.project / "core" / "hub.py").write_text("class Hub: pass\n", encoding="utf-8")
        (self.project / "tests").mkdir()
        (self.project / "tests" / "test_hub.py").write_text("def test(): pass\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_map_is_mermaid_fenced(self):
        mermaid = archivist.generate_mermaid_map(self.project)
        self.assertTrue(mermaid.startswith("```mermaid\nflowchart TD"))
        self.assertTrue(mermaid.endswith("```"))

    def test_map_includes_root_and_modules(self):
        mermaid = archivist.generate_mermaid_map(self.project)
        self.assertIn('ROOT["demo"]', mermaid)
        self.assertIn("main.py", mermaid)
        self.assertIn("core/hub.py", mermaid)
        self.assertIn("tests/test_hub.py", mermaid)

    def test_map_is_deterministic(self):
        first = archivist.generate_mermaid_map(self.project)
        second = archivist.generate_mermaid_map(self.project)
        self.assertEqual(first, second)

    def test_map_skips_archivist_output_dir(self):
        docs = self.project / "docs" / "architecture"
        docs.mkdir(parents=True)
        (docs / "Architecture.md").write_text("note", encoding="utf-8")
        mermaid = archivist.generate_mermaid_map(self.project)
        self.assertNotIn("docs/architecture", mermaid)

    def test_fingerprint_changes_with_structure(self):
        before = archivist.structure_fingerprint(self.project)
        (self.project / "extra.py").write_text("y = 2\n", encoding="utf-8")
        after = archivist.structure_fingerprint(self.project)
        self.assertNotEqual(before, after)


# --------------------------------------------------------------------------- Rules 4 & 5: sync + evolution


class SyncAndEvolutionTestCase(unittest.TestCase):
    """Rules 4 & 5 — maintenance duty and lean per-project Evolution file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "demo"
        self.project.mkdir()
        (self.project / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        self.docs = self.project / "docs" / "architecture"

    def tearDown(self):
        self._tmp.cleanup()

    def test_sync_creates_note_with_map_and_fingerprint(self):
        result = archivist.sync_architecture_docs(
            self.project, entries=["Decision: JSONL"], prompt="Decision: JSONL"
        )
        self.assertTrue(result["map_regenerated"])
        note = self.docs / "Architecture.md"
        self.assertTrue(note.is_file())
        text = note.read_text(encoding="utf-8")
        self.assertIn("```mermaid", text)
        self.assertIn(f"<!-- fingerprint: {result['fingerprint']} -->", text)
        self.assertIn("Decision: JSONL", text)

    def test_refactor_detected_regenerates_map(self):
        archivist.sync_architecture_docs(self.project, prompt="first")
        first = archivist.structure_fingerprint(self.project)
        # Refactor: add a module.
        (self.project / "core").mkdir()
        (self.project / "core" / "__init__.py").write_text("", encoding="utf-8")
        second = archivist.structure_fingerprint(self.project)
        self.assertNotEqual(first, second)
        result = archivist.sync_architecture_docs(self.project, prompt="refactor")
        self.assertTrue(result["map_regenerated"])
        note = self.docs / "Architecture.md"
        text = note.read_text(encoding="utf-8")
        self.assertIn("core/__init__.py", text)

    def test_sync_is_idempotent_when_structure_unchanged(self):
        archivist.sync_architecture_docs(self.project, prompt="first")
        result = archivist.sync_architecture_docs(self.project, prompt="again")
        self.assertFalse(result["map_regenerated"])

    def test_evolution_is_deduplicated_and_lean(self):
        for _ in range(3):
            archivist.consolidate_evolution(self.project, ["repeat"], prompt="repeat")
        text = (self.docs / "Evolution.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("repeat"), 1)

    def test_evolution_caps_entries(self):
        for i in range(archivist.MAX_EVOLUTION_ENTRIES + 5):
            archivist.consolidate_evolution(self.project, [f"milestone {i}"])
        text = (self.docs / "Evolution.md").read_text(encoding="utf-8")
        self.assertIn("summarized", text)
        entries = [line for line in text.splitlines() if line.startswith("- ")]
        self.assertLessEqual(len(entries), archivist.MAX_EVOLUTION_ENTRIES + 1)


# --------------------------------------------------------------------------- master entry


class ArchivistRunTestCase(unittest.TestCase):
    """archivist_run ties rules 1-5 together for a dispatch or /archive."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        (self.workspace / "projects").mkdir()
        self.project = self.workspace / "projects" / "demo"
        self.project.mkdir()
        (self.project / "main.py").write_text("def main(): pass\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_conversational_prompt_writes_nothing_new(self):
        result = archivist.archivist_run("thanks!", workspace=self.workspace)
        self.assertFalse(result["archived"])
        self.assertEqual(result["filter"]["entries"], [])
        # No decisions/milestones may be archived from conversation.
        note = self.project / "docs" / "architecture" / "Architecture.md"
        if note.is_file():
            self.assertNotIn("thanks", note.read_text(encoding="utf-8"))

    def test_architectural_prompt_writes_project_notes(self):
        result = archivist.archivist_run(
            "Decision: use Mermaid for architecture maps in the demo project",
            workspace=self.workspace,
        )
        self.assertTrue(result["archived"])
        note = self.project / "docs" / "architecture" / "Architecture.md"
        evolution = self.project / "docs" / "architecture" / "Evolution.md"
        self.assertTrue(note.is_file())
        self.assertTrue(evolution.is_file())
        self.assertIn("Archivist (M7)", result["summary"])

    def test_explicit_project_dir_wins(self):
        other = self.workspace / "projects" / "other"
        other.mkdir()
        (other / "app.py").write_text("x = 1\n", encoding="utf-8")
        result = archivist.archivist_run(
            "Decision: keep it simple", workspace=self.workspace, project_dir=other
        )
        self.assertTrue(result["archived"])
        self.assertTrue((other / "docs" / "architecture" / "Architecture.md").is_file())
        self.assertFalse((self.project / "docs" / "architecture" / "Architecture.md").exists())

    def test_explicit_project_dir_cannot_be_agent_logs(self):
        own_logs = self.workspace / "obsidian_vault" / "agents_logs"
        own_logs.mkdir(parents=True)
        result = archivist.archivist_run(
            "Decision: keep it simple", workspace=self.workspace, project_dir=own_logs
        )
        # Guard redirects back to the workspace root; nothing written in agent logs.
        self.assertTrue(result["project_dir"] != str(own_logs))
        self.assertFalse((own_logs / "docs" / "architecture" / "Architecture.md").exists())

    def test_docs_dir_refuses_agents_logs_path(self):
        own_logs = self.workspace / "obsidian_vault" / "agents_logs"
        own_logs.mkdir(parents=True)
        with self.assertRaises(ValueError):
            archivist.docs_dir(own_logs)


# --------------------------------------------------------------------------- mode registration


class ArchivistModeTestCase(unittest.TestCase):
    """ARCHIVIST_MODE is registered as a Chloe operational mode."""

    def test_mode_constant_exists(self):
        self.assertEqual(ARCHIVIST_MODE, "archivist")

    def test_mode_maps_to_chloe(self):
        self.assertEqual(MODE_TO_AGENT[ARCHIVIST_MODE], "chloe")

    def test_mode_is_available_on_docs_models(self):
        self.assertIn(ARCHIVIST_MODE, MODE_OPTIONS_BY_MODEL["opencode/big-pickle"])
        self.assertIn(ARCHIVIST_MODE, MODE_OPTIONS_BY_MODEL["opencode/ling-3.0-tiny-free"])


if __name__ == "__main__":
    unittest.main()
