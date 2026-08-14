"""Workflow persistence tests for the Phase 3 ``model`` field.

Guards the full round-trip (from_dict → to_dict → save → load) for
``model`` together with Phase 2's ``prompt_profile`` and ``task``, and proves
old workflows / templates without any of these fields stay valid.
"""

import os
import tempfile
import unittest
from pathlib import Path

from scripts.core import workflows


def node_data(**overrides) -> dict:
    data = {"id": "n1", "agent": "developer", "kind": "agent",
            "x": 10.0, "y": 20.0}
    data.update(overrides)
    return data


class WorkflowModelPersistenceTestCase(unittest.TestCase):
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

    def _workflow(self, nodes, edges=None, wf_id="wf"):
        return workflows.Workflow(
            id=wf_id, name=wf_id,
            nodes=[workflows.WorkflowNode.from_dict(n) for n in nodes],
            edges=[workflows.WorkflowEdge.from_dict(e) for e in (edges or [])])

    def test_roundtrip_preserves_model_prompt_task(self):
        wf = self._workflow([node_data(
            prompt_profile="software-engineer-expert",
            task={"category": "development", "capabilities": ["coding"]},
            model="opencode/deepseek-v4-flash-free")])
        data = wf.to_dict()
        n = data["nodes"][0]
        self.assertEqual(n["prompt_profile"], "software-engineer-expert")
        self.assertEqual(n["task"]["category"], "development")
        self.assertEqual(n["model"], "opencode/deepseek-v4-flash-free")

        saved = workflows.save_workflow(wf, self.root)
        loaded = workflows.load_workflow("wf", self.root)
        self.assertIsNotNone(loaded)
        ln = loaded.nodes[0]
        self.assertEqual(ln.model, "opencode/deepseek-v4-flash-free")
        self.assertEqual(ln.prompt_profile, "software-engineer-expert")
        self.assertEqual(ln.task["capabilities"], ["coding"])

    def test_old_workflow_without_model_remains_valid(self):
        wf = self._workflow([node_data()])
        saved = workflows.save_workflow(wf, self.root)
        loaded = workflows.load_workflow("wf", self.root)
        n = loaded.nodes[0]
        self.assertEqual(n.model, "")
        self.assertEqual(n.prompt_profile, "")
        self.assertEqual(n.task, {})

    def test_validate_accepts_registry_model_ids(self):
        wf = self._workflow([node_data(agent="matthew",
                                       model="google/gemini-3.6-flash")])
        errors = workflows.validate_workflow(wf)
        self.assertEqual(errors, [])

    def test_validate_rejects_malformed_model(self):
        wf = self._workflow([node_data(model="not-a-model-id")])
        errors = workflows.validate_workflow(wf)
        self.assertTrue(errors)

    def test_template_with_model_prompt_task_loads(self):
        # a template authored with all three metadata fields round-trips
        wf = self._workflow([node_data(
            prompt_profile="ai-engineer", model="opencode/big-pickle",
            task={"category": "ai", "capabilities": ["agents"]})],
            wf_id="template-wf")
        d = wf.to_dict()
        again = workflows.Workflow.from_dict(d)
        n = again.nodes[0]
        self.assertEqual(n.model, "opencode/big-pickle")
        self.assertEqual(n.prompt_profile, "ai-engineer")
        self.assertEqual(n.task["category"], "ai")

    def test_loading_one_template_does_not_merge_metadata(self):
        # two workflows with different model metadata never bleed into each other
        wf_a = self._workflow([node_data(model="opencode/big-pickle")],
                              wf_id="a")
        wf_b = self._workflow([node_data(model="google/gemini-3.6-flash")],
                              wf_id="b")
        workflows.save_workflow(wf_a, self.root)
        workflows.save_workflow(wf_b, self.root)
        a = workflows.load_workflow("a", self.root)
        b = workflows.load_workflow("b", self.root)
        self.assertEqual(a.nodes[0].model, "opencode/big-pickle")
        self.assertEqual(b.nodes[0].model, "google/gemini-3.6-flash")


if __name__ == "__main__":
    unittest.main()
