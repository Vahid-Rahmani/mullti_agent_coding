"""Execution planner tests (Phase 5).

Proves plan_node resolves model / connection / prompt / adapter deterministically:

* explicit node.model always wins; otherwise the agent's runtime model is used
* explicit connection_id always wins (and never silently replaced)
* implicit connection resolution degrades to the local OpenCode runtime
* the canonical prompt builder composes user_prompt + roles + instruction /
  prompt-profile + workflow state
* the default adapter is OpenCode

Isolated via ZOVA_CONNECTIONS / ZOVA_AUTH_STORE (temp dirs); opencode.json is
read from a temp repo_root when testing agent-model fallback. Never executes
anything and never touches credentials.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import model_connections as MC
from scripts.core.execution import planner as P
from scripts.core.execution.errors import PlanError
from scripts.core.workflows import WorkflowNode


class PlannerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._conn_env = os.environ.get("ZOVA_CONNECTIONS")
        self._auth_env = os.environ.get("ZOVA_AUTH_STORE")
        os.environ["ZOVA_CONNECTIONS"] = str(Path(self.tmp.name) / "connections.json")
        os.environ["ZOVA_AUTH_STORE"] = str(Path(self.tmp.name) / "auth.json")

    def tearDown(self):
        if self._conn_env is None:
            os.environ.pop("ZOVA_CONNECTIONS", None)
        else:
            os.environ["ZOVA_CONNECTIONS"] = self._conn_env
        if self._auth_env is None:
            os.environ.pop("ZOVA_AUTH_STORE", None)
        else:
            os.environ["ZOVA_AUTH_STORE"] = self._auth_env
        self.tmp.cleanup()

    def _repo(self, model=None):
        """A temp repo root with an opencode.json (agent model fallback) and a
        minimal roles.json so role context renders deterministically."""
        root = Path(self.tmp.name) / "repo"
        root.mkdir(exist_ok=True)
        cfg = {}
        if model:
            cfg = {"agent": {"matthew": {"model": model}}}
        (root / "opencode.json").write_text(json.dumps(cfg), encoding="utf-8")
        roles = {
            "roles": {
                "python-developer": {
                    "name": "Python Developer",
                    "description": "Implements Python code",
                    "responsibilities": ["write code"],
                    "tools": [],
                    "permissions": [],
                    "rules": [],
                    "expected_outputs": [],
                }
            },
            "assignments": {"matthew": ["python-developer"]},
        }
        (root / "roles.json").write_text(json.dumps(roles), encoding="utf-8")
        return root

    def _node(self, **kw):
        base = dict(id="n1", label="Dev", agent="matthew", kind="agent")
        base.update(kw)
        return WorkflowNode.from_dict(base)


class TestModelResolution(PlannerTestCase):
    def test_explicit_node_model_wins(self):
        repo = self._repo(model="google/gemini-3.6-flash")
        plan = P.plan_node(self._node(model="opencode/big-pickle"), {},
                           repo_root=repo)
        self.assertEqual(plan.model, "opencode/big-pickle")

    def test_agent_model_fallback(self):
        repo = self._repo(model="google/gemini-3.6-flash")
        plan = P.plan_node(self._node(), {}, repo_root=repo)
        self.assertEqual(plan.model, "google/gemini-3.6-flash")

    def test_defaults_to_local_open_code_runtime(self):
        plan = P.plan_node(self._node(), {})
        self.assertEqual(plan.provider, "opencode")
        self.assertEqual(plan.adapter_id, "opencode")
        self.assertTrue(plan.connection.local)


class TestConnectionResolution(PlannerTestCase):
    def test_explicit_connection_wins(self):
        conn = MC.create_connection(
            "openai", "OpenAI Primary", api_key="sk-test-not-real",
            connection_id="conn_openai_1")
        plan = P.plan_node(
            self._node(model="openai/gpt-test", connection_id=conn.connection_id), {})
        self.assertEqual(plan.connection.connection_id, "conn_openai_1")
        self.assertEqual(plan.connection.provider, "openai")
        self.assertFalse(plan.connection.local)
        # the planner never resolves the secret
        self.assertFalse(plan.connection.has_credential())
        self.assertNotIn("sk-test-not-real", repr(plan.to_dict()))
        self.assertNotIn("credential", plan.to_dict())

    def test_missing_explicit_connection_is_a_plan_error(self):
        with self.assertRaises(PlanError):
            P.plan_node(self._node(model="openai/gpt-test",
                                   connection_id="conn_ghost"), {})

    def test_implicit_missing_provider_degrades_to_local(self):
        # no google connection configured: implicit resolution degrades and is
        # reported as safe plan metadata instead of failing execution.
        plan = P.plan_node(self._node(model="google/gemini-3.6-flash"), {})
        self.assertTrue(plan.connection.local)
        self.assertEqual(plan.provider, "opencode")
        self.assertTrue(plan.connection_error)


class TestPromptConstruction(PlannerTestCase):
    def test_canonical_prompt_composes_all_layers(self):
        repo = self._repo(model="opencode/big-pickle")
        node = self._node(roles=("python-developer",),
                          instructions="Write the code now")
        plan = P.plan_node(node, {"user_prompt": "implement feature X"}, repo_root=repo)
        prompt = plan.prompt
        self.assertIn("implement feature X", prompt)          # user prompt
        self.assertIn("Write the code now", prompt)           # node instruction
        self.assertIn("## Workflow state", prompt)            # state JSON
        self.assertIn("Python Developer", prompt)             # role context name

    def test_prompt_profile_is_instruction_fallback(self):
        node = self._node(prompt_profile="software-engineer-expert",
                          instructions="")
        plan = P.plan_node(node, {})
        profile = __import__("scripts.core.prompt_library", fromlist=["get_prompt"])
        expected = profile.get_prompt("software-engineer-expert").prompt.strip()
        self.assertIn(expected[:80], plan.prompt)

    def test_custom_instruction_beats_profile(self):
        node = self._node(prompt_profile="software-engineer-expert",
                          instructions="My own instruction")
        plan = P.plan_node(node, {})
        self.assertIn("My own instruction", plan.prompt)
        profile = __import__("scripts.core.prompt_library", fromlist=["get_prompt"])
        self.assertNotIn(profile.get_prompt("software-engineer-expert").prompt[:60],
                         plan.prompt)

    def test_request_metadata(self):
        plan = P.plan_node(self._node(), {}, execution_id="run-abc")
        self.assertEqual(plan.request.metadata["node_id"], "n1")
        self.assertEqual(plan.request.metadata["agent"], "matthew")
        self.assertEqual(plan.request.metadata["execution_id"], "run-abc")
        self.assertEqual(plan.request.model, plan.model)


class TestAdapterSelection(PlannerTestCase):
    def test_default_adapter_is_opencode(self):
        plan = P.plan_node(self._node(), {})
        self.assertEqual(plan.adapter_id, "opencode")
        self.assertEqual(plan.provider, "opencode")

    def test_plan_to_dict_is_safe_metadata(self):
        plan = P.plan_node(self._node(prompt_profile="software-engineer-expert",
                                      task={"description": "audit"}),
                           {})
        d = plan.to_dict()
        self.assertEqual(d["node_id"], "n1")
        self.assertEqual(d["model"], plan.model)
        self.assertEqual(d["adapter"], "opencode")
        self.assertEqual(d["prompt_profile"], "software-engineer-expert")
        self.assertEqual(d["task"], {"description": "audit"})
        self.assertGreater(d["prompt_len"], 0)


if __name__ == "__main__":
    unittest.main()
