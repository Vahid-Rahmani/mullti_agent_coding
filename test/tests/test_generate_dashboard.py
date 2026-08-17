"""generate_dashboard tests — temp vaults, never the real one.

Covers: generated-marker-only writes, human-section preservation, WikiLink
resolution against the vault, section presence, and schema-valid frontmatter.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_dashboard as gd

NODE = ("---\ntype: {t}\nstatus: active\nowner: test\ncreated: 2026-08-11\n"
        "updated: 2026-08-11\n---\n\n# {name}\n")


class DashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        for sec in gd.TASK_SECTIONS:
            (self.vault / sec).mkdir(parents=True)
        # Minimal nodes the dashboard links to.
        self.vault.joinpath("00-System/System_Core.md").write_text(
            NODE.format(t="system", name="System_Core"), encoding="utf-8")
        self.vault.joinpath("03-Tasks/Tasks_Home.md").write_text(
            NODE.format(t="task", name="Tasks_Home"), encoding="utf-8")
        self.vault.joinpath("03-Tasks/Task_Backlog.md").write_text(
            NODE.format(t="task", name="Task_Backlog"), encoding="utf-8")
        self.vault.joinpath("03-Tasks/Task_Alpha.md").write_text(
            "---\ntype: task\nstatus: in_progress\nowner: o\n"
            "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n# Task_Alpha\n",
            encoding="utf-8")
        self.vault.joinpath("02-Agents/Agents_Home.md").write_text(
            NODE.format(t="agent", name="Agents_Home"), encoding="utf-8")
        self.vault.joinpath("02-Agents/Agent_Matthew.md").write_text(
            NODE.format(t="agent", name="Agent_Matthew"), encoding="utf-8")
        self.vault.joinpath("01-Architecture/Architecture_Home.md").write_text(
            NODE.format(t="architecture", name="Architecture_Home"), encoding="utf-8")
        self.vault.joinpath("01-Architecture/System_Architecture.md").write_text(
            NODE.format(t="architecture", name="System_Architecture"), encoding="utf-8")
        for _module, component in gd.O2_COMPONENTS:
            self.vault.joinpath(f"01-Architecture/{component}.md").write_text(
                NODE.format(t="architecture", name=component), encoding="utf-8")
        self.vault.joinpath("04-Decisions/Decisions_Home.md").write_text(
            NODE.format(t="decision", name="Decisions_Home"), encoding="utf-8")
        self.vault.joinpath("05-Documentation/Documentation_Home.md").write_text(
            NODE.format(t="documentation", name="Documentation_Home"), encoding="utf-8")
        self.vault.joinpath("06-Testing/Testing_Home.md").write_text(
            NODE.format(t="test", name="Testing_Home"), encoding="utf-8")
        self.vault.joinpath("06-Testing/Test_Report_Suite.md").write_text(
            NODE.format(t="test", name="Test_Report_Suite"), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def dashboard_path(self):
        return self.vault / "Dashboard.md"


class TestGeneration(DashboardTestCase):
    def test_all_sections_present(self):
        content = gd.render_dashboard(self.vault)
        for heading in ("Project Status", "Active / In-Progress Tasks",
                        "Active Agents", "Recent Executions", "Recent Changes",
                        "Testing Status", "Architecture Status",
                        "Blocked / Needs Attention"):
            self.assertIn(f"## {heading}", content)

    def test_task_link_appears(self):
        content = gd.render_dashboard(self.vault)
        self.assertIn("[[Task_Alpha]]", content)

    def test_agent_link_appears(self):
        content = gd.render_dashboard(self.vault)
        self.assertIn("[[Agent_Matthew]]", content)

    def test_complete_o2_component_map_has_no_gap(self):
        content = gd.render_dashboard(self.vault)
        self.assertIn("O2 component gaps:** _None", content)
        for module, component in gd.O2_COMPONENTS:
            self.assertIn(f"[[{component}]]", content)
            self.assertNotIn(f"`{module}` — missing", content)

    def test_missing_o2_component_is_reported(self):
        module, component = gd.O2_COMPONENTS[0]
        self.vault.joinpath(f"01-Architecture/{component}.md").unlink()
        content = gd.render_dashboard(self.vault)
        self.assertIn("Unresolved O2 component gaps", content)
        self.assertIn(f"`{module}` — missing [[{component}]]", content)


class TestWikiLinksResolve(DashboardTestCase):
    def test_all_dashboard_links_resolve(self):
        gd.write_dashboard(self.vault, gd.render_dashboard(self.vault))
        text = self.dashboard_path().read_text(encoding="utf-8")
        names = set()
        for sec in gd.TASK_SECTIONS:
            names |= {p.stem for p in (self.vault / sec).glob("*.md")}
        bad = []
        for m in re.finditer(r"\[\[([^|\]]+)\]\]", text):
            if m.group(1) not in names:
                bad.append(m.group(1))
        self.assertEqual(bad, [])


class TestHumanPreservation(DashboardTestCase):
    def test_human_section_preserved(self):
        self.dashboard_path().write_text(
            "# My Dashboard\n\nMy personal notes here.\n\n"
            + f"{gd.OPEN_MARKER}\nstale generated\n{gd.CLOSE_MARKER}\n",
            encoding="utf-8")
        gd.write_dashboard(self.vault, gd.render_dashboard(self.vault))
        text = self.dashboard_path().read_text(encoding="utf-8")
        self.assertIn("# My Dashboard\n\nMy personal notes here.", text)
        self.assertNotIn("stale generated", text)

    def test_frontmatter_schema_valid(self):
        content = gd.render_dashboard(self.vault)
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        self.assertIsNotNone(m, "missing frontmatter")
        for key in ("type", "status", "owner", "created", "updated", "related"):
            self.assertIn(f"{key}:", m.group(1), key)
        self.assertIn("type: system", m.group(1))

    def test_check_flag_detects_stale(self):
        gd.write_dashboard(self.vault, gd.render_dashboard(self.vault))
        self.assertEqual(gd.main(["--vault", str(self.vault), "--check"]), 0)
        # Tamper -> stale.
        self.dashboard_path().write_text("changed", encoding="utf-8")
        self.assertEqual(gd.main(["--vault", str(self.vault), "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
