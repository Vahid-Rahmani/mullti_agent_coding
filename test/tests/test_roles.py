"""Unit tests for scripts/core/roles.py — reusable, model-independent roles.

Encodes the intended architecture:
  * one agent may have many roles,
  * many agents may share one role,
  * roles are editable/reusable without touching AgentSpec modules,
  * a role is never tied to a model (assigning a role never changes a model).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import roles  # noqa: E402


class RoleRegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        data = {
            "roles": {
                "python-developer": {"name": "Python Developer",
                                     "responsibilities": ["Write Python"]},
                "code-reviewer": {"name": "Code Reviewer",
                                  "rules": ["Report, don't fix"]},
            },
            "assignments": {},
        }
        roles.save_roles(data, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_roles_sorted_and_loaded(self):
        ids = [r.id for r in roles.list_roles(self.root)]
        self.assertEqual(ids, ["code-reviewer", "python-developer"])

    def test_role_has_no_model_field(self):
        role = roles.get_role("python-developer", self.root)
        self.assertIsNotNone(role)
        self.assertFalse(hasattr(role, "model"))
        self.assertFalse(hasattr(role, "provider"))


class AssignmentTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        data = {
            "roles": {
                "python-developer": {"name": "Python Developer"},
                "code-reviewer": {"name": "Code Reviewer"},
                "security-engineer": {"name": "Security Engineer"},
            },
            "assignments": {},
        }
        roles.save_roles(data, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_agent_many_roles(self):
        roles.assign_roles("matthew", ["python-developer", "code-reviewer"], self.root)
        self.assertEqual(
            roles.roles_for_agent("matthew", self.root),
            ["python-developer", "code-reviewer"],
        )

    def test_many_agents_share_one_role(self):
        for agent in ("matthew", "alex", "sarah"):
            roles.assign_roles(agent, ["python-developer"], self.root)
        for agent in ("matthew", "alex", "sarah"):
            self.assertEqual(roles.roles_for_agent(agent, self.root),
                             ["python-developer"])

    def test_reassign_swaps_roles_without_duplication(self):
        roles.assign_roles("matthew", ["python-developer", "code-reviewer"], self.root)
        roles.assign_roles("matthew", ["security-engineer"], self.root)
        self.assertEqual(roles.roles_for_agent("matthew", self.root),
                         ["security-engineer"])

    def test_unknown_role_rejected(self):
        with self.assertRaises(roles.RoleError):
            roles.assign_roles("matthew", ["nope"], self.root)

    def test_invalid_role_id_rejected(self):
        with self.assertRaises(roles.RoleError):
            roles.assign_roles("matthew", ["../escape"], self.root)

    def test_unassign_all(self):
        roles.assign_roles("matthew", ["python-developer"], self.root)
        roles.unassign_all("matthew", self.root)
        self.assertEqual(roles.roles_for_agent("matthew", self.root), [])


class RoleCreateDeleteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        roles.save_roles({"roles": {}, "assignments": {}}, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_custom_role_created_and_persisted(self):
        role = roles.create_role(
            "azure-ai-engineer", name="Azure AI Engineer",
            description="Azure AI Foundry + RAG",
            responsibilities=["Azure AI Foundry", "RAG"],
            tools=["Python", "Azure CLI"],
            rules=["No production changes without approval"],
            repo_root=self.root,
        )
        self.assertEqual(role.name, "Azure AI Engineer")
        reloaded = roles.get_role("azure-ai-engineer", self.root)
        self.assertEqual(reloaded.responsibilities, ("Azure AI Foundry", "RAG"))
        self.assertEqual(reloaded.rules, ("No production changes without approval",))

    def test_delete_role_drops_from_assignments(self):
        roles.create_role("x", repo_root=self.root)
        roles.assign_roles("matthew", ["x"], self.root)
        self.assertTrue(roles.delete_role("x", self.root))
        self.assertEqual(roles.roles_for_agent("matthew", self.root), [])
        self.assertIsNone(roles.get_role("x", self.root))

    def test_delete_missing_role_returns_false(self):
        self.assertFalse(roles.delete_role("x", self.root))


class RenderingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        roles.save_roles({
            "roles": {
                "python-developer": {
                    "name": "Python Developer",
                    "description": "Writes Python",
                    "responsibilities": ["Implement features"],
                    "tools": ["Python", "unittest"],
                    "rules": ["Run tests before done"],
                    "expected_outputs": ["Passing tests"],
                },
            },
            "assignments": {"matthew": ["python-developer"]},
        }, self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_includes_all_sections(self):
        ctx = roles.render_role_context("matthew", repo_root=self.root)
        self.assertIn("## Roles (matthew)", ctx)
        self.assertIn("### Python Developer", ctx)
        self.assertIn("Responsibilities:", ctx)
        self.assertIn("Tools:", ctx)
        self.assertIn("Rules:", ctx)
        self.assertIn("Expected outputs:", ctx)

    def test_agent_context_empty_when_no_roles(self):
        self.assertEqual(roles.agent_context("alex", repo_root=self.root), "")

    def test_render_deterministic(self):
        a = roles.render_role_context("matthew", repo_root=self.root)
        b = roles.render_role_context("matthew", repo_root=self.root)
        self.assertEqual(a, b)


class PrecedenceTestCase(unittest.TestCase):
    def test_precedence_order_is_explicit(self):
        self.assertEqual(
            roles.PRECEDENCE,
            ("user_instruction", "user_role", "repository_instruction",
             "role_default", "agent_default"),
        )


class EnvPathTestCase(unittest.TestCase):
    def test_zova_roles_env_override(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "custom.json"
            path.write_text('{"roles": {}, "assignments": {}}', encoding="utf-8")
            with mock.patch.dict(os.environ, {"ZOVA_ROLES": str(path)}):
                self.assertEqual(roles.roles_path(), path)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
