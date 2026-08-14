"""WorkflowNode.connection_id persistence tests (Phase 4).

connection_id round-trips through from_dict/to_dict, save/load, templates,
and old workflows without it stay valid. Secrets never enter workflow JSON.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.core import workflows

SECRET = "test-secret-value-abc123"


class WorkflowConnectionPersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._orig = os.environ.get("ZOVA_WORKFLOWS")
        os.environ["ZOVA_WORKFLOWS"] = str(self.root)

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("ZOVA_WORKFLOWS", None)
        else:
            os.environ["ZOVA_WORKFLOWS"] = self._orig
        self.tmp.cleanup()

    def _workflow(self, nodes, wf_id="wf"):
        return workflows.Workflow(
            id=wf_id, name=wf_id,
            nodes=[workflows.WorkflowNode.from_dict(n) for n in nodes])

    def test_from_to_dict_roundtrip(self):
        wf = self._workflow([{
            "id": "n1", "agent": "matthew", "kind": "agent",
            "model": "openai/gpt-5", "connection_id": "conn_openai_primary",
        }])
        data = wf.to_dict()
        self.assertEqual(data["nodes"][0]["connection_id"], "conn_openai_primary")
        again = workflows.Workflow.from_dict(data)
        self.assertEqual(again.nodes[0].connection_id, "conn_openai_primary")

    def test_save_load_preserves_connection_id(self):
        wf = self._workflow([{
            "id": "n1", "agent": "alex", "kind": "agent",
            "model": "anthropic/claude-sonnet-4-5",
            "connection_id": "conn_anthropic_1",
        }])
        workflows.save_workflow(wf, self.root)
        loaded = workflows.load_workflow("wf", self.root)
        self.assertEqual(loaded.nodes[0].connection_id, "conn_anthropic_1")

    def test_old_workflow_without_connection_id_valid(self):
        wf = self._workflow([{"id": "n1", "agent": "matthew", "kind": "agent"}])
        workflows.save_workflow(wf, self.root)
        loaded = workflows.load_workflow("wf", self.root)
        self.assertEqual(loaded.nodes[0].connection_id, "")
        self.assertEqual(workflows.validate_workflow(loaded), [])

    def test_template_preserves_connection_id(self):
        wf = self._workflow([{
            "id": "n1", "agent": "matthew", "kind": "agent",
            "model": "openai/gpt-5", "connection_id": "conn_openai_primary",
            "prompt_profile": "software-engineer-expert",
        }], wf_id="tpl")
        d = wf.to_dict()
        again = workflows.Workflow.from_dict(d)
        n = again.nodes[0]
        self.assertEqual(n.connection_id, "conn_openai_primary")
        self.assertEqual(n.prompt_profile, "software-engineer-expert")

    def test_validate_accepts_valid_connection_id(self):
        wf = self._workflow([{
            "id": "n1", "agent": "matthew", "kind": "agent",
            "connection_id": "conn_ok_1",
        }])
        self.assertEqual(workflows.validate_workflow(wf), [])

    def test_validate_rejects_whitespace_connection_id(self):
        wf = self._workflow([{
            "id": "n1", "agent": "matthew", "kind": "agent",
            "connection_id": "conn bad",
        }])
        self.assertTrue(workflows.validate_workflow(wf))

    def test_workflow_payload_never_contains_secret(self):
        wf = self._workflow([{
            "id": "n1", "agent": "matthew", "kind": "agent",
            "model": "openai/gpt-5", "connection_id": "conn_openai_primary",
        }])
        payload = json.dumps(wf.to_dict())
        self.assertNotIn(SECRET, payload)
        self.assertNotIn("api_key", payload)

    def test_two_workflows_keep_own_connection_ids(self):
        a = self._workflow([{"id": "n1", "agent": "matthew",
                             "connection_id": "conn_a"}], wf_id="a")
        b = self._workflow([{"id": "n1", "agent": "matthew",
                             "connection_id": "conn_b"}], wf_id="b")
        workflows.save_workflow(a, self.root)
        workflows.save_workflow(b, self.root)
        self.assertEqual(workflows.load_workflow("a", self.root).nodes[0].connection_id,
                         "conn_a")
        self.assertEqual(workflows.load_workflow("b", self.root).nodes[0].connection_id,
                         "conn_b")


if __name__ == "__main__":
    unittest.main()
