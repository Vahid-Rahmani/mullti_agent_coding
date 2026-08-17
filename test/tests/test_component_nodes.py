"""O2 Component-node contract tests against the repository Vault."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import vault_validate
from scripts.core import knowledge_sync

VAULT = REPO_ROOT / "obsidian_vault"
ARCH = VAULT / "01-Architecture"

REQUIRED = {
    "Component_Orchestrator": "orchestrator.py",
    "Component_VaultBridge": "vault_bridge.py",
    "Component_ContextResolver": "context_resolver.py",
    "Component_ChangeDetector": "change_detector.py",
    "Component_KnowledgeSync": "knowledge_sync.py",
}

DEFERRED = {
    "Component_AgentCatalog", "Component_Evaluation", "Component_HealthCheck",
    "Component_OpencodeCfg", "Component_ProjectProfile", "Component_Roles",
    "Component_RuntimeContext", "Component_Skills", "Component_WorkflowEngine",
    "Component_Workflows",
}

REMOVED = {
    "Component_Swarm", "Component_SelfEvolve", "Component_Archivist",
    "Component_LegacyWebApp", "Component_DesktopGUI",
}


class ComponentNodeContractTestCase(unittest.TestCase):
    def test_required_component_files_exist_with_valid_frontmatter(self):
        for component, module in REQUIRED.items():
            path = ARCH / f"{component}.md"
            self.assertTrue(path.is_file(), component)
            text = path.read_text(encoding="utf-8")
            fields, error = vault_validate.parse_frontmatter(text)
            self.assertIsNone(error, component)
            self.assertEqual(fields["type"], "architecture")
            self.assertEqual(fields["status"], "active")
            self.assertEqual(fields["owner"], "architect")
            self.assertEqual(fields["created"], "2026-08-17")
            self.assertEqual(fields["updated"], "2026-08-17")
            self.assertIn(f"# {component}", text)
            self.assertIn(f"`scripts/core/{module}`", text)
            self.assertIn("↑ Parent: [[System_Architecture]]", text)

    def test_architecture_indexes_reference_every_required_component(self):
        for filename in ("Architecture_Home.md", "System_Architecture.md",
                         "Architecture_Overview.md"):
            text = (ARCH / filename).read_text(encoding="utf-8")
            for component in REQUIRED:
                self.assertIn(f"[[{component}]]", text, filename)

    def test_component_ids_are_unique(self):
        stems = [path.stem for path in ARCH.glob("Component_*.md")]
        self.assertEqual(len(stems), len(set(stems)))

    def test_deferred_and_removed_component_nodes_do_not_exist(self):
        existing = {path.stem for path in ARCH.glob("Component_*.md")}
        self.assertFalse(existing & DEFERRED)
        self.assertFalse(existing & REMOVED)

    def test_knowledge_sync_accepts_required_components(self):
        conflicts = knowledge_sync.check_conflicts(VAULT)
        for component, module in REQUIRED.items():
            self.assertFalse(
                any(message.startswith(f"{module}:") for message in conflicts),
                component,
            )
        # The implementation must not hide the explicitly deferred heuristic
        # candidates by weakening KnowledgeSync/Health Check.
        self.assertTrue(any(message.startswith("agent_catalog.py:")
                            for message in conflicts))

    def test_repository_vault_validates(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = vault_validate.main(["--vault", str(VAULT)])
        self.assertEqual(result, 0, output.getvalue())
        self.assertIn("45 node(s)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
