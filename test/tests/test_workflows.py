"""Workflow model tests — data model, persistence, validation, templates, recs.

Uses temp directories for persistence; never touches the repo ``workflows/``
dir, ``roles.json``, or ``opencode.json``.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import workflows as W


def make_workflow(nodes=None, edges=None, entry=None):
    nodes = nodes or [
        {"id": "a", "label": "A", "agent": "matthew", "kind": "agent"},
        {"id": "b", "label": "B", "agent": "alex", "kind": "agent"},
    ]
    return W.Workflow.from_dict({
        "id": "test-wf", "name": "Test", "nodes": nodes,
        "edges": edges or [],
        "entry": entry if entry is not None else ["a"],
    })


class TestIds(unittest.TestCase):
    def test_normalize_lowercases_and_spaces(self):
        self.assertEqual(W.normalize_workflow_id("My Pipeline"), "my-pipeline")

    def test_normalize_rejects_traversal(self):
        for bad in ("../etc", "a/b", "a\\b", "..", "a..b/", "/abs", "a:b"):
            with self.assertRaises(W.WorkflowError):
                W.normalize_workflow_id(bad)

    def test_normalize_accepts_safe_slug(self):
        self.assertEqual(W.normalize_workflow_id("project_backend.pipeline-2"),
                         "project_backend.pipeline-2")


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load_roundtrip(self):
        wf = make_workflow(edges=[{"source": "a", "target": "b", "condition": "success"}])
        W.save_workflow(wf, self.root)
        loaded = W.load_workflow("test-wf", self.root)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.edges[0].condition, "success")
        self.assertEqual(loaded.entry, ["a"])

    def test_save_rejects_untitled_placeholder(self):
        # "untitled" must NEVER be persisted as a workflow id — the designer's
        # in-memory placeholder is rejected at the save boundary.
        wf = W.Workflow.from_dict({
            "id": "untitled", "name": "",
            "nodes": [{"id": "a", "agent": "matthew", "kind": "agent"}],
            "edges": [], "entry": ["a"],
        })
        with self.assertRaises(W.WorkflowError):
            W.save_workflow(wf, self.root)
        self.assertIsNone(W.load_workflow("untitled", self.root))

    def test_existing_valid_workflows_still_save_and_load(self):
        # regression guard: valid ids (the pre-existing behavior) are untouched
        wf = make_workflow(edges=[{"source": "a", "target": "b"}])
        saved = W.save_workflow(wf, self.root)
        self.assertEqual(saved.id, "test-wf")
        self.assertEqual(W.load_workflow("test-wf", self.root).id, "test-wf")

    def test_list_and_delete(self):
        W.save_workflow(make_workflow(), self.root)
        W.save_workflow(W.Workflow(id="other", name="Other"), self.root)
        self.assertEqual({w.id for w in W.list_workflows(self.root)},
                         {"test-wf", "other"})
        self.assertTrue(W.delete_workflow("test-wf", self.root))
        self.assertFalse(W.delete_workflow("test-wf", self.root))
        self.assertEqual({w.id for w in W.list_workflows(self.root)}, {"other"})

    def test_duplicate_makes_copy(self):
        W.save_workflow(make_workflow(), self.root)
        dup = W.duplicate_workflow("test-wf", self.root)
        self.assertEqual(dup.id, "test-wf-copy2")
        W.save_workflow(dup, self.root)
        dup2 = W.duplicate_workflow("test-wf", self.root)
        self.assertEqual(dup2.id, "test-wf-copy3")

    def test_import_export(self):
        wf = make_workflow()
        W.save_workflow(wf, self.root)
        exported = W.export_workflow("test-wf", self.root)
        self.assertEqual(exported["id"], "test-wf")
        imported = W.import_workflow(exported, self.root, workflow_id="imported-wf")
        self.assertEqual(imported.id, "imported-wf")
        self.assertIsNotNone(W.load_workflow("imported-wf", self.root))

    def test_import_rejects_non_object(self):
        with self.assertRaises(W.WorkflowError):
            W.import_workflow(["not", "a", "dict"], self.root)


class TestValidation(unittest.TestCase):
    def test_valid_workflow_no_errors(self):
        wf = make_workflow(edges=[{"source": "a", "target": "b"}])
        self.assertEqual(W.validate_workflow(wf), [])

    def test_missing_agent(self):
        wf = make_workflow(nodes=[{"id": "a", "label": "A", "kind": "agent"}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("missing Agent" in e["message"] for e in errs))

    def test_unknown_agent(self):
        wf = make_workflow(nodes=[{"id": "a", "agent": "nobody", "kind": "agent"}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("does not exist" in e["message"] for e in errs))

    def test_unknown_role(self):
        wf = make_workflow(nodes=[{"id": "a", "agent": "matthew", "kind": "agent",
                                   "roles": ["no-such-role"]}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("Role" in e["message"] and "does not exist" in e["message"]
                            for e in errs))

    def test_invalid_model(self):
        wf = make_workflow(nodes=[{"id": "a", "agent": "matthew", "kind": "agent",
                                   "model": "no slash here"}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("Model" in e["message"] for e in errs))

    def test_invalid_edge_reference(self):
        wf = make_workflow(edges=[{"source": "a", "target": "ghost"}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("missing node" in e["message"] for e in errs))

    def test_self_loop_rejected(self):
        wf = make_workflow(edges=[{"source": "a", "target": "a"}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("self-loop" in e["message"] for e in errs))

    def test_bad_condition_rejected(self):
        wf = make_workflow(edges=[{"source": "a", "target": "b", "condition": "banana"}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("routing condition" in e["message"] for e in errs))

    def test_disconnected_node(self):
        wf = make_workflow(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent"},
            {"id": "b", "agent": "alex", "kind": "agent"},
            {"id": "c", "agent": "sarah", "kind": "agent"},
        ], edges=[{"source": "a", "target": "b"}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("disconnected" in e["message"] for e in errs))

    def test_unconditional_cycle_flagged(self):
        wf = make_workflow(edges=[
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("cycle" in e["message"] for e in errs))

    def test_conditional_cycle_allowed(self):
        # a -> b, b -failure-> a is a controlled retry loop (no unconditional cycle)
        wf = make_workflow(edges=[
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a", "condition": "failure"},
        ])
        errs = W.validate_workflow(wf)
        self.assertFalse(any("cycle" in e["message"] for e in errs))

    def test_missing_start_node(self):
        # every node has an incoming edge (the c->a edge is conditional so it is
        # not an unconditional cycle), and no explicit entry -> no start node
        wf = make_workflow(
            nodes=[{"id": "a", "agent": "matthew", "kind": "agent"},
                   {"id": "b", "agent": "alex", "kind": "agent"},
                   {"id": "c", "agent": "sarah", "kind": "agent"}],
            edges=[{"source": "a", "target": "b"},
                   {"source": "b", "target": "c"},
                   {"source": "c", "target": "a", "condition": "success"}],
            entry=[])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("start node" in e["message"] for e in errs))
        self.assertFalse(any("cycle" in e["message"] for e in errs))

    def test_all_disabled(self):
        wf = make_workflow(nodes=[{"id": "a", "agent": "matthew", "kind": "agent",
                                   "enabled": False}])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("disabled" in e["message"] for e in errs))


class TestNodeModelOverride(unittest.TestCase):
    """Per-node model overrides: an instance-level runtime concern that must
    round-trip through persistence and never couple an agent to a model."""

    def test_two_nodes_same_agent_different_models(self):
        wf = make_workflow(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent",
             "model": "opencode/deepseek-v4-flash-free"},
            {"id": "b", "agent": "matthew", "kind": "agent",
             "model": "google/gemini-3.5-flash-lite"},
        ], edges=[{"source": "a", "target": "b"}])
        self.assertEqual(W.validate_workflow(wf), [])
        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            W.save_workflow(wf, root)
            loaded = W.load_workflow("test-wf", root)
            self.assertIsNotNone(loaded)
            by_id = {n.id: n.model for n in loaded.nodes}
            self.assertEqual(by_id["a"], "opencode/deepseek-v4-flash-free")
            self.assertEqual(by_id["b"], "google/gemini-3.5-flash-lite")
        finally:
            tmp.cleanup()

    def test_model_roundtrips_through_dict_payload(self):
        wf = make_workflow(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent",
             "model": "opencode/big-pickle"},
        ])
        payload = wf.to_dict()
        self.assertEqual(payload["nodes"][0]["model"], "opencode/big-pickle")
        rebuilt = W.Workflow.from_dict(payload)
        self.assertEqual(rebuilt.nodes[0].model, "opencode/big-pickle")

    def test_auto_empty_model_validates_without_model_error(self):
        # Auto (empty model) is accepted — it is never flagged as an invalid model
        wf = make_workflow(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent", "model": ""},
        ])
        errs = W.validate_workflow(wf)
        self.assertFalse(any("Model" in e["message"] for e in errs))

    def test_invalid_model_still_rejected(self):
        # validation remains strict: a bare id without a provider is rejected
        wf = make_workflow(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent", "model": "gemini-flash"},
        ])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("Model" in e["message"] and "invalid" in e["message"]
                            for e in errs))

    def test_node_position_persists_through_roundtrip(self):
        wf = make_workflow(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent", "x": 320.0, "y": 140.0},
        ])
        tmp = tempfile.TemporaryDirectory()
        try:
            W.save_workflow(wf, Path(tmp.name))
            loaded = W.load_workflow("test-wf", Path(tmp.name))
            self.assertEqual((loaded.nodes[0].x, loaded.nodes[0].y), (320.0, 140.0))
        finally:
            tmp.cleanup()

    def test_duplicate_node_id_rejected(self):
        wf = make_workflow(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent"},
            {"id": "a", "agent": "alex", "kind": "agent"},
        ])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("duplicate node id" in e["message"] for e in errs))


class TestNewPresets(unittest.TestCase):
    def test_new_presets_listed(self):
        templates = W.list_templates()
        for name in ("parallel-specialists", "planner-workers-reviewer",
                     "research-analysis-writer", "empty"):
            self.assertIn(name, templates)
            self.assertIsNotNone(W.get_template(name), name)

    def test_planner_workers_reviewer_fan_in(self):
        wf = W.get_template("planner-workers-reviewer")
        workers = {e.target for e in wf.edges if e.source == "planner"}
        self.assertEqual(workers, {"worker_1", "worker_2", "worker_3"})
        rev_in = {e.source for e in wf.edges if e.target == "reviewer"}
        self.assertEqual(rev_in, {"worker_1", "worker_2", "worker_3"})
        # all three workers reference the same role (reusable, not duplicated)
        worker_nodes = [n for n in wf.nodes if n.id.startswith("worker")]
        self.assertEqual({n.roles for n in worker_nodes}, {("python-developer",)})

    def test_parallel_specialists_structure(self):
        wf = W.get_template("parallel-specialists")
        fan = {e.target for e in wf.edges if e.source == "planner"}
        self.assertEqual(fan, {"researcher", "developer", "analyst"})
        agg_in = {e.source for e in wf.edges if e.target == "aggregator"}
        self.assertEqual(agg_in, {"researcher", "developer", "analyst"})

    def test_research_analysis_writer_sequential(self):
        wf = W.get_template("research-analysis-writer")
        self.assertEqual([n.id for n in wf.nodes],
                         ["researcher", "analyst", "writer"])
        self.assertEqual([(e.source, e.target) for e in wf.edges],
                         [("researcher", "analyst"), ("analyst", "writer")])

    def test_empty_preset_is_blank(self):
        wf = W.get_template("empty")
        self.assertEqual(wf.nodes, [])
        self.assertEqual(wf.edges, [])


class TestTemplateNormalization(unittest.TestCase):
    """Bug 3 regression — every built-in template must validate + dry-run.

    The ``reflection`` template's terminal ``end`` node used to carry an empty
    role string (``roles=[""]``), which made ``validate_workflow`` fail with
    ``Role '' does not exist`` — so Dry Run / Run returned an error for that
    template while others worked. Templates must never persist placeholder
    roles, and legacy data with empty roles must normalize on load.
    """

    def test_reflection_end_node_has_no_roles(self):
        wf = W.get_template("reflection")
        done = next(n for n in wf.nodes if n.id == "done")
        self.assertEqual(done.kind, "end")
        self.assertEqual(done.roles, (), "an end node must never carry an empty role")

    def test_reflection_validates_and_dry_runs(self):
        wf = W.get_template("reflection")
        self.assertEqual(W.validate_workflow(wf), [], "reflection must be valid")
        from scripts.core import workflow_engine
        plan = workflow_engine.simulate_workflow(wf)
        self.assertIn(["done"], plan["waves"], "the end node is reached on success")

    def test_every_builtin_template_validates(self):
        for name in W.list_templates():
            wf = W.get_template(name)
            if name == "empty":
                continue  # the blank preset intentionally has no nodes
            self.assertEqual(W.validate_workflow(wf), [], f"template {name} must validate")

    def test_legacy_empty_roles_are_normalized_on_load(self):
        data = {"id": "wf", "nodes": [
            {"id": "n1", "agent": "matthew", "roles": ["", "python-developer", " "]},
        ], "edges": []}
        wf = W.Workflow.from_dict(data)
        self.assertEqual(wf.nodes[0].roles, ("python-developer",),
                         "empty/whitespace role entries are dropped by from_dict")
        self.assertEqual(W.validate_workflow(wf), [],
                         "the normalized workflow validates cleanly (no 'Role \'\' does not exist')")


class TestNodeTitleSync(unittest.TestCase):
    """Bug 1 regression — label provenance must round-trip.

    ``label_auto`` marks whether the node title is auto-derived (follows the
    selected Prompt Profile) or user-customized (never overwritten). It must
    survive save/load so a customized name is not clobbered after a reload.
    """

    def test_label_auto_defaults_true(self):
        n = W.WorkflowNode(id="n1", agent="matthew")
        self.assertTrue(n.label_auto)

    def test_label_auto_round_trips(self):
        n = W.WorkflowNode.from_dict({"id": "n1", "agent": "matthew",
                                      "label": "Keep me", "label_auto": False})
        self.assertFalse(n.label_auto)
        back = W.WorkflowNode.from_dict(n.to_dict())
        self.assertFalse(back.label_auto, "customized flag survives to_dict/from_dict")
        self.assertEqual(back.label, "Keep me")

    def test_label_auto_missing_means_auto(self):
        n = W.WorkflowNode.from_dict({"id": "n1", "agent": "matthew"})
        self.assertTrue(n.label_auto, "old data without label_auto is treated as auto-derived")


class TestTemplates(unittest.TestCase):
    def test_all_templates_exist(self):
        templates = W.list_templates()
        for name in ("sequential", "parallel", "supervisor", "router",
                     "hierarchical", "reflection", "parallel-specialists",
                     "planner-workers-reviewer", "research-analysis-writer", "empty"):
            self.assertIn(name, templates, name)
        for name in templates:
            self.assertIsNotNone(W.get_template(name), name)

    def test_sequential_chain(self):
        wf = W.get_template("sequential")
        ids = [n.id for n in wf.nodes]
        self.assertEqual(ids, ["architect", "developer", "tester", "reviewer"])
        self.assertEqual([(e.source, e.target) for e in wf.edges],
                         [("architect", "developer"), ("developer", "tester"),
                          ("tester", "reviewer")])

    def test_parallel_fanout_and_fanin(self):
        wf = W.get_template("parallel")
        # architect fans out to backend/frontend/security, all fan in to reviewer
        targets = [e.target for e in wf.edges if e.source == "architect"]
        self.assertEqual(set(targets), {"backend", "frontend", "security"})
        rev_in = [e.source for e in wf.edges if e.target == "reviewer"]
        self.assertEqual(set(rev_in), {"backend", "frontend", "security"})

    def test_reflection_has_conditional_loop_and_entry(self):
        wf = W.get_template("reflection")
        self.assertEqual(wf.entry, ["developer"])
        conds = {(e.source, e.target): e.condition for e in wf.edges}
        self.assertEqual(conds[("reviewer", "done")], "success")
        self.assertEqual(conds[("reviewer", "developer")], "failure")

    def test_supervisor_has_two_instances_of_same_agent(self):
        wf = W.get_template("supervisor")
        sups = [n for n in wf.nodes if "supervisor" in n.id]
        self.assertEqual(len(sups), 2)
        self.assertEqual(sups[0].agent, sups[1].agent)


class TestRecommend(unittest.TestCase):
    def test_recommend_returns_workflow_and_reasons(self):
        rec = W.recommend_workflow(n_agents=4)
        self.assertIn("workflow", rec)
        self.assertIn("reasons", rec)
        self.assertIn("composition", rec)
        self.assertIn("technologies", rec)
        wf = W.Workflow.from_dict(rec["workflow"])
        self.assertTrue(wf.nodes)
        self.assertEqual(wf.entry, ["node_0"] if wf.nodes else [])
        # python is detected in this repo -> python-developer should be suggested
        self.assertIn("python", rec["technologies"])
        self.assertTrue(any("python-developer" in r for r in rec["reasons"]))


if __name__ == "__main__":
    unittest.main()
