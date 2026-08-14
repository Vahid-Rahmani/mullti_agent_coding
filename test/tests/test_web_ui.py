"""Web dashboard tests — temp-vault/TestClient fixtures, never the real vault.

Covers: WebState drain/sessions/prefs, VaultGraph building + relationships,
and the REST API surface (agents, dispatch validation, task assign/status
validation, task-dispatch argv, logs, static assets). Real agent dispatch and
task subprocesses are never executed — the hub is a fake and Popen is stubbed.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from scripts.web_ui import graph as vgraph  # noqa: E402
from scripts.web_ui.state import WebState  # noqa: E402

NODE_TEXT = (
    "---\ntype: {node_type}\nstatus: active\nowner: x\n"
    "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n"
    "# {name}\n\n{body}\n"
)

TASK_TEXT = """\
---
type: task
status: planned
owner: orchestrator
priority: high
assigned_agent: Agent_Matthew
related_component: Component_RunHub
dependencies: []
created: 2026-08-11
updated: 2026-08-11
---

# Task_Demo

## Title

Implement a demo feature.

## Description

Do the thing.

## Acceptance Criteria

- [ ] criterion one
- [ ] criterion two
"""


def make_node(name, node_type="system", body=""):
    return NODE_TEXT.format(node_type=node_type, name=name, body=body)


class LineStream:
    """Minimal iterable with the surface Popen.stdout is expected to have."""

    def __init__(self, lines):
        self._lines = list(lines)
        self._i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._lines):
            raise StopIteration
        line = self._lines[self._i]
        self._i += 1
        return line + "\n"


class FakeHub:
    """Stand-in for RunHub: records calls, exposes telemetry."""

    TAGS = ("m1", "m2", "m3", "m4", "m5", "m6", "m7")

    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.running = 0
        self.statuses = {t: "idle" for t in self.TAGS}
        self.progress = {t: 0 for t in self.TAGS}
        self.token_usage = {t: 0 for t in self.TAGS}
        self.prompts = {t: "" for t in self.TAGS}
        self.session_tags: set[str] = set()
        self.calls: list[tuple] = []

    def run(self, prompt, overrides=None, agents=None, system_prompts=None,
            enabled_agents=None):
        self.calls.append(("run", prompt, agents))
        return None if prompt.strip() else "Prompt must not be empty."

    def terminate_agent(self, tag):
        self.calls.append(("terminate_agent", tag))

    def terminate_all(self):
        self.calls.append(("terminate_all",))


class VaultTestCase(unittest.TestCase):
    """Temp vault fixture: 03-Tasks + task node + linked nodes + archives."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.tasks = self.vault / "03-Tasks"
        self.tasks.mkdir(parents=True)
        self.task_path = self.tasks / "Task_Demo.md"
        self.task_path.write_text(TASK_TEXT, encoding="utf-8")

        self.agents = self.vault / "02-Agents"
        self.agents.mkdir(parents=True)
        (self.agents / "Agent_Matthew.md").write_text(
            make_node("Agent_Matthew", "agent", ""), encoding="utf-8")

        self.system = self.vault / "00-System"
        self.system.mkdir(parents=True)
        (self.system / "System_Core.md").write_text(
            make_node("System_Core", "system", "[[Tasks_Home]]"), encoding="utf-8")
        (self.system / "Vault_Map.md").write_text(
            make_node("Vault_Map", "system", "[[System_Core]]"), encoding="utf-8")

        (self.vault / "03-Tasks" / "Tasks_Home.md").write_text(
            make_node("Tasks_Home", "task", ""), encoding="utf-8")

        # Archives and templates that must never appear in the graph.
        (self.vault / "prompts").mkdir(exist_ok=True)
        (self.vault / "prompts" / "P999.md").write_text("archive", encoding="utf-8")
        (self.tasks / "_TASK_TEMPLATE.md").write_text("tpl", encoding="utf-8")

        self.hub = FakeHub()
        self.state = WebState(hub=self.hub, session_tail=5)

    def tearDown(self):
        self.tmp.cleanup()


class WebStateTestCase(VaultTestCase):
    def test_drain_hub_and_own_events(self):
        self.hub.events.append({"seq": 1, "tag": "m4", "kind": "run", "text": "M4::hello"})
        self.hub.events.append({"seq": 2, "tag": "m4", "kind": "line", "text": "working"})
        self.state.push_task_line("Task_Demo", "dispatch output")
        drained = self.state.drain()
        self.assertEqual(len(drained), 3)
        sessions = self.state.sessions()
        self.assertIn("m4", sessions)
        self.assertEqual(sessions["m4"][0]["text"], "M4::hello")
        self.assertEqual(sessions["Task_Demo"][0]["text"], "dispatch output")

    def test_drain_cursor_is_sticky(self):
        self.hub.events.append({"seq": 1, "tag": "m1", "kind": "line", "text": "a"})
        self.assertEqual(len(self.state.drain()), 1)
        self.assertEqual(len(self.state.drain()), 0)
        self.hub.events.append({"seq": 2, "tag": "m1", "kind": "line", "text": "b"})
        self.assertEqual(len(self.state.drain()), 1)

    def test_session_tail_is_capped(self):
        for i in range(8):
            self.state.push_usermsg("m1", f"line {i}")
        self.state.drain()
        sess = self.state.sessions()["m1"]
        self.assertEqual(len(sess), 5)
        self.assertEqual(sess[0]["text"], "line 3")

    def test_prefs_max_six_and_valid_layout(self):
        prefs = self.state.update_prefs({
            "layout": "9",
            "agents_visible": ["m1", "m2", "m3", "m4", "m5", "m6", "m7"],
        })
        self.assertEqual(prefs["layout"], "4")
        self.assertEqual(len(prefs["agents_visible"]), 6)


class VaultGraphTestCase(VaultTestCase):
    def test_graph_excludes_archives_and_templates(self):
        graph = vgraph.build_graph(self.vault)
        names = [n["name"] for n in graph["nodes"]]
        self.assertIn("Task_Demo", names)
        self.assertNotIn("P999", names)
        self.assertNotIn("_TASK_TEMPLATE", names)
        self.assertTrue(any(n["name"] == "System_Core" and n["degree"] >= 1
                            for n in graph["nodes"]))

    def test_graph_includes_root_nodes(self):
        root = self.vault / "Dashboard.md"
        root.write_text(make_node("Dashboard", "system", "[[System_Core]]"),
                        encoding="utf-8")
        graph = vgraph.build_graph(self.vault)
        dash = next((n for n in graph["nodes"] if n["name"] == "Dashboard"), None)
        self.assertIsNotNone(dash)
        self.assertEqual(dash["folder"], "root")

    def test_node_relationships_links_and_backlinks(self):
        rel = vgraph.node_relationships(self.vault, "System_Core")
        self.assertIn("Tasks_Home", [x["name"] for x in rel["links"]])
        self.assertIn("Vault_Map", [x["name"] for x in rel["backlinks"]])

    def test_find_node_missing_returns_none(self):
        self.assertIsNone(vgraph.find_node(self.vault, "Nope_Nope"))


class ApiTestCase(VaultTestCase):
    def setUp(self):
        super().setUp()
        from scripts.web_ui.server import create_app
        import scripts.web_ui.routes as routes_mod
        self.routes_mod = routes_mod
        self.real_hub = routes_mod.HUB
        # Point the routes module at the shared fake hub so dispatch/stop
        # never touch a real subprocess.
        self.orig_hub_attr = None
        routes_mod.HUB = self.hub
        self.app = create_app(vault=self.vault, state=self.state)
        self.ctx = TestClient(self.app)

    def tearDown(self):
        self.routes_mod.HUB = self.real_hub
        super().tearDown()

    def test_agents_endpoint(self):
        data = self.ctx.get("/api/agents").json()
        self.assertEqual(len(data["agents"]), 7)
        self.assertTrue(all(a["tag"] and a["name"] for a in data["agents"]))

    def test_dispatch_validates_prompt_and_target(self):
        r = self.ctx.post("/api/dispatch", json={"prompt": "", "agent": "m1"})
        self.assertEqual(r.status_code, 400)
        r = self.ctx.post("/api/dispatch", json={"prompt": "hi", "agent": "zzz"})
        self.assertEqual(r.status_code, 404)
        r = self.ctx.post("/api/dispatch", json={"prompt": "do it", "agent": "m4"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.hub.calls[-1], ("run", "do it", ["m4"]))

    def test_stop_endpoints(self):
        self.ctx.post("/api/stop/m4")
        self.assertIn(("terminate_agent", "m4"), self.hub.calls)
        self.ctx.post("/api/stop")
        self.assertIn(("terminate_all",), self.hub.calls)

    def test_tasks_list(self):
        tasks = self.ctx.get("/api/tasks").json()["tasks"]
        self.assertEqual([t["name"] for t in tasks], ["Task_Demo"])

    def test_assign_writes_frontmatter_and_status(self):
        res = self.ctx.post("/api/tasks/Task_Demo/assign", json={"agent": "matthew"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["assigned_agent"], "Agent_Matthew")
        raw = self.task_path.read_text(encoding="utf-8")
        self.assertIn("assigned_agent: Agent_Matthew", raw)
        self.assertIn("status: ready", raw)

    def test_assign_unknown_agent_404(self):
        r = self.ctx.post("/api/tasks/Task_Demo/assign", json={"agent": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_status_invalid_and_illegal_transition(self):
        r = self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "banana"})
        self.assertEqual(r.status_code, 400)
        r = self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "completed"})
        self.assertEqual(r.status_code, 409)
        r = self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "ready"})
        self.assertEqual(r.status_code, 200)
        raw = self.task_path.read_text(encoding="utf-8")
        self.assertIn("status: ready", raw)

    def test_task_dispatch_argv(self):
        self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "ready"})
        proc = mock.Mock()
        proc.pid = 4242
        proc.stdout = LineStream(["line one", "line two"])
        proc.wait.return_value = 0
        with mock.patch.object(self.routes_mod.subprocess, "Popen",
                               return_value=proc) as fake_popen:
            r = self.ctx.post("/api/tasks/Task_Demo/dispatch")
        self.assertEqual(r.status_code, 200)
        argv = fake_popen.call_args.args[0]
        self.assertEqual(argv[:2], [sys.executable, "-m"])
        self.assertIn("dispatch", argv)
        self.assertIn("--yes", argv)
        time.sleep(0.05)  # let the pump thread drain the fake stream
        proc.wait.assert_called_once()

    def test_task_dispatch_requires_ready(self):
        r = self.ctx.post("/api/tasks/Task_Demo/dispatch")
        self.assertEqual(r.status_code, 409)

    def test_vault_context(self):
        r = self.ctx.get("/api/vault/context/Task_Demo")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["root"], "Task_Demo")

    def test_logs_and_static_assets(self):
        self.assertEqual(self.ctx.get("/api/logs/orchestrator").status_code, 200)
        self.assertEqual(self.ctx.get("/api/logs/zzz").status_code, 404)
        index = self.ctx.get("/")
        self.assertIn(b"app.css", index.content)
        self.assertEqual(self.ctx.get("/static/app.css").status_code, 200)
        self.assertEqual(self.ctx.get("/static/app.js").status_code, 200)

    def test_prefs_roundtrip(self):
        data = self.ctx.post("/api/prefs", json={
            "layout": "6",
            "agents_visible": ["m1", "m2", "m3", "m4", "m5", "m6"],
        }).json()
        self.assertEqual(data["layout"], "6")
        self.assertEqual(self.ctx.get("/api/prefs").json()["layout"], "6")

    def test_events_endpoint(self):
        self.hub.events.append({"seq": 1, "tag": "m1", "kind": "line", "text": "x"})
        data = self.ctx.get("/api/events").json()
        self.assertEqual(len(data["events"]), 1)

    def test_settings_endpoints(self):
        meta = self.ctx.get("/api/settings").json()
        self.assertIn("connections", meta["sections"])
        self.assertTrue(any(p["id"] == "google" for p in meta["simple_providers"]))
        conns = self.ctx.get("/api/settings/connections").json()["providers"]
        self.assertTrue(any(c["id"] == "google" and "configured" in c for c in conns))
        self.assertTrue(all("key" not in c for c in conns), "keys must never leave the backend")

    def test_settings_endpoint_validation(self):
        r = self.ctx.post("/api/settings/connections/test", json={"provider": "zzz"})
        self.assertEqual(r.status_code, 404)
        # invalid inputs are rejected before any file write
        r = self.ctx.post("/api/settings/models", json={"agent": "zzz", "model": "opencode/x"})
        self.assertEqual(r.status_code, 409)
        r = self.ctx.post("/api/settings/models", json={"agent": "matthew", "model": "no-slash"})
        self.assertEqual(r.status_code, 409)
        r = self.ctx.post("/api/settings/agents/matthew/mode", json={"mode": "architect"})
        self.assertEqual(r.status_code, 409)

    def test_settings_roles_and_profile_endpoints(self):
        meta = self.ctx.get("/api/settings").json()
        self.assertIn("roles", meta["sections"])
        self.assertIn("profile", meta["sections"])
        roles_data = self.ctx.get("/api/settings/roles").json()
        self.assertIn("roles", roles_data)
        self.assertIn("assignments", roles_data)
        self.assertTrue(any(r["id"] == "python-developer" for r in roles_data["roles"]))
        agent_roles = self.ctx.get("/api/settings/agents/matthew/roles").json()
        self.assertIn("role_ids", agent_roles)
        profile = self.ctx.get("/api/settings/profile").json()
        self.assertIn("technologies", profile)
        self.assertIn("suggested_roles", profile)
        # each suggested role carries a reason (why it was suggested)
        for sr in profile["suggested_roles"]:
            self.assertIn("id", sr)
            self.assertIn("reason", sr)

    def test_settings_role_assignment_rejects_unknown(self):
        r = self.ctx.put("/api/settings/agents/matthew/roles",
                         json={"role_ids": ["does-not-exist"]})
        self.assertEqual(r.status_code, 409)

    def test_task_role_override_endpoint(self):
        # valid predefined role -> written to the temp task node frontmatter
        r = self.ctx.put("/api/tasks/Task_Demo/role",
                         json={"role": "python-developer"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "python-developer")
        raw = self.task_path.read_text(encoding="utf-8")
        self.assertIn("role: python-developer", raw)
        # unknown role -> 409, no write
        r = self.ctx.put("/api/tasks/Task_Demo/role", json={"role": "nope"})
        self.assertEqual(r.status_code, 409)
        # clear -> empty override
        r = self.ctx.put("/api/tasks/Task_Demo/role", json={"role": None})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "")


    # ---- prompt library endpoints -----------------------------------
    def test_prompts_endpoint_lists_all(self):
        data = self.ctx.get("/api/prompts").json()
        self.assertIn("prompts", data)
        self.assertEqual(len(data["prompts"]), 42)
        self.assertIn("roles", data)
        # list returns metadata only — never the prompt text
        first = data["prompts"][0]
        self.assertNotIn("prompt", first)
        for field in ("id", "name", "description", "role", "category",
                      "capabilities", "recommended_models", "tags", "version"):
            self.assertIn(field, first)

    def test_prompts_role_filter(self):
        # ?role=developer maps keywords to the software_engineer prompt role
        data = self.ctx.get("/api/prompts", params={"role": "developer"}).json()
        self.assertEqual({p["role"] for p in data["prompts"]}, {"software_engineer"})
        # ?role=security → security_engineer
        data = self.ctx.get("/api/prompts", params={"role": "security"}).json()
        self.assertEqual({p["role"] for p in data["prompts"]}, {"security_engineer"})
        # no match → empty list, still 200
        data = self.ctx.get("/api/prompts", params={"role": "zzz"}).json()
        self.assertEqual(data["prompts"], [])

    def test_prompts_detail_and_unknown(self):
        full = self.ctx.get("/api/prompts/software-engineer-expert").json()["prompt"]
        self.assertEqual(full["name"], "Expert Software Engineer")
        self.assertIn("prompt", full)
        self.assertTrue(full["prompt"])
        self.assertEqual(self.ctx.get("/api/prompts/nope").status_code, 404)

    def test_prompts_list_includes_model_preferences(self):
        first = self.ctx.get("/api/prompts").json()["prompts"][0]
        self.assertIn("model_preferences", first)
        prefs = first["model_preferences"]
        for key in ("reasoning", "coding", "context", "tool_use", "latency", "cost"):
            self.assertIn(key, prefs)

    def test_prompts_recommend_meta(self):
        data = self.ctx.get("/api/prompts/recommend").json()
        self.assertIn("categories", data)
        self.assertIn("roles", data)
        self.assertIn("examples", data)
        self.assertIn("security", data["categories"])
        self.assertTrue(any(e["prompt_id"] == "security-auditor"
                            for e in data["examples"]))

    def test_prompts_recommend_post(self):
        r = self.ctx.post("/api/prompts/recommend",
                          json={"task": "security audit"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("task", body)
        self.assertEqual(body["task"]["category"], "security")
        recs = body["recommendations"]
        self.assertTrue(recs)
        self.assertEqual(recs[0]["prompt_id"], "security-auditor")
        # each recommendation carries a deterministic score + reason
        for rec in recs:
            self.assertIn("prompt_id", rec)
            self.assertIn("score", rec)
            self.assertIn("reason", rec)
            self.assertTrue(0.0 <= rec["score"] <= 1.0)

    def test_models_capabilities_endpoint(self):
        models = self.ctx.get("/api/models/capabilities").json()["models"]
        self.assertTrue(models)
        for m in models:
            self.assertIn("id", m)
            self.assertIn("context_window", m)
            self.assertNotIn("/", m["id"])  # provider-neutral

    def test_models_recommend_requirements(self):
        r = self.ctx.post("/api/models/recommend",
                          json={"prompt_id": "software-engineer-expert"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("requirements", body)
        self.assertEqual(body["requirements"]["reasoning"], "high")
        # Phase 3: without supplied models the registry catalog is ranked
        # deterministically (the response shape is unchanged).
        self.assertIn("recommendations", body)
        self.assertTrue(body["recommendations"])
        for rec in body["recommendations"]:
            self.assertIn("model_id", rec)
            self.assertIn("score", rec)
            self.assertIn("reason", rec)
        scores = [rec["score"] for rec in body["recommendations"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_models_registry_endpoint(self):
        body = self.ctx.get("/api/models").json()
        models = body["models"]
        self.assertTrue(models)
        for m in models:
            self.assertIn("id", m)
            self.assertIn("provider", m)
            self.assertIn("capabilities", m)
            self.assertIn("context_window", m)
        self.assertIn("providers", body)
        self.assertIn("google", body["providers"])

    def test_models_registry_provider_filter(self):
        body = self.ctx.get("/api/models", params={"provider": "google"}).json()
        self.assertTrue(body["models"])
        self.assertTrue(all(m["provider"] == "google" for m in body["models"]))

    def test_models_registry_detail(self):
        r = self.ctx.get("/api/models/opencode/deepseek-v4-flash-free")
        self.assertEqual(r.status_code, 200)
        model = r.json()["model"]
        self.assertEqual(model["id"], "opencode/deepseek-v4-flash-free")
        self.assertEqual(model["capabilities"]["reasoning"], "high")

    def test_models_registry_detail_unknown_404(self):
        r = self.ctx.get("/api/models/does/not-exist")
        self.assertEqual(r.status_code, 404)

    def test_models_recommend_prompt_profile_alias(self):
        # Phase 3 payload uses ``prompt_profile``; the handler falls back to
        # Phase 2's ``prompt_id`` so old consumers keep working.
        r = self.ctx.post("/api/models/recommend", json={
            "prompt_profile": "software-engineer-expert"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["recommendations"])

    def test_models_recommend_explicit_model_preserved(self):
        r = self.ctx.post("/api/models/recommend", json={
            "prompt_profile": "software-engineer-expert",
            "explicit_model": "ollama/qwen2.5-coder:7b",
        })
        self.assertEqual(r.status_code, 200)
        recs = r.json()["recommendations"]
        self.assertEqual(recs[0]["model_id"], "ollama/qwen2.5-coder:7b")
        self.assertTrue(recs[0]["explicit"])

    def test_models_recommend_hard_requirements(self):
        r = self.ctx.post("/api/models/recommend", json={
            "prompt_profile": "software-engineer-expert",
            "hard_requirements": {"context_window": 100000},
        })
        self.assertEqual(r.status_code, 200)
        for rec in r.json()["recommendations"]:
            if rec["explicit"]:
                continue
            mid = rec["model_id"]
            self.assertGreaterEqual(
                self.ctx.get(f"/api/models/{mid}").json()["model"]["context_window"],
                100000)

    def test_models_recommend_provider_filter(self):
        r = self.ctx.post("/api/models/recommend", json={
            "prompt_profile": "software-engineer-expert",
            "provider": "google",
        })
        self.assertEqual(r.status_code, 200)
        recs = r.json()["recommendations"]
        self.assertTrue(recs)
        self.assertTrue(all(rec["model_id"].startswith("google/")
                            for rec in recs))

    def test_models_recommend_ranks(self):
        r = self.ctx.post("/api/models/recommend", json={
            "prompt_id": "software-engineer-expert",
            "available_models": [
                {"id": "fast", "name": "Fast", "reasoning": "low",
                 "coding": "medium", "context_window": 32000, "tool_use": "low",
                 "latency": "low", "cost": "low"},
                {"id": "strong", "name": "Strong", "reasoning": "high",
                 "coding": "high", "context_window": 200000, "tool_use": "high",
                 "latency": "medium", "cost": "medium"},
            ],
        })
        body = r.json()
        self.assertTrue(body["recommendations"])
        self.assertEqual(body["recommendations"][0]["model_id"], "strong")

    def test_models_recommend_unknown_prompt(self):
        r = self.ctx.post("/api/models/recommend", json={"prompt_id": "nope"})
        self.assertEqual(r.status_code, 404)


class WorkflowApiTestCase(VaultTestCase):
    """Workflow REST endpoints, isolated via $ZOVA_WORKFLOWS temp dir."""

    def setUp(self):
        super().setUp()
        self.wf_dir = Path(self.tmp.name) / "workflows"
        self.wf_dir.mkdir(parents=True)
        self._orig_zova_wf = os.environ.get("ZOVA_WORKFLOWS")
        os.environ["ZOVA_WORKFLOWS"] = str(self.wf_dir)
        from scripts.web_ui.server import create_app
        import scripts.web_ui.routes as routes_mod
        self.routes_mod = routes_mod
        self.real_hub = routes_mod.HUB
        routes_mod.HUB = self.hub
        self.app = create_app(vault=self.vault, state=self.state)
        self.ctx = TestClient(self.app)

    def tearDown(self):
        self.routes_mod.HUB = self.real_hub
        if self._orig_zova_wf is None:
            os.environ.pop("ZOVA_WORKFLOWS", None)
        else:
            os.environ["ZOVA_WORKFLOWS"] = self._orig_zova_wf
        super().tearDown()

    def _wf(self, **overrides):
        body = {
            "id": "test-wf", "name": "Test",
            "nodes": [{"id": "a", "agent": "matthew", "kind": "agent"},
                      {"id": "b", "agent": "alex", "kind": "agent"}],
            "edges": [{"source": "a", "target": "b"}],
            "entry": ["a"],
        }
        body.update(overrides)
        return body

    def test_workspace_route_served(self):
        r = self.ctx.get("/workspace")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Agent Workspace", r.content)
        self.assertIn(b"workspace.js", r.content)

    def test_agents_available_to_workspace(self):
        # the workspace's agent library is fed by the existing registry API
        r = self.ctx.get("/api/agents").json()
        self.assertEqual(len(r["agents"]), 7)
        for a in r["agents"]:
            self.assertIn("tag", a)
            self.assertIn("name", a)
            self.assertIn("agent", a)
            self.assertIn("model", a)
            self.assertTrue(a["agent"], "agent key must be non-empty")

    def test_add_agent_node_persists_after_save_reload(self):
        # simulate the full Add Agent → save → reload flow at the API boundary
        body = self._wf(nodes=[{
            "id": "n1", "label": "Matthew #1", "agent": "matthew",
            "kind": "agent", "model": "", "x": 120.0, "y": 140.0,
        }])
        self.ctx.put("/api/workflows/test-wf", json=body)
        got = self.ctx.get("/api/workflows/test-wf").json()["workflow"]
        self.assertEqual(len(got["nodes"]), 1)
        node = got["nodes"][0]
        self.assertEqual(node["agent"], "matthew")
        self.assertEqual(node["model"], "")
        self.assertEqual(node["x"], 120.0)
        self.assertEqual(node["y"], 140.0)

    def test_prompt_profile_persists_through_api(self):
        # a node's prompt_profile survives the full PUT → GET round trip, and a
        # workflow without it (backward compatible) still saves fine.
        body = self._wf(nodes=[{
            "id": "a", "agent": "matthew", "kind": "agent",
            "prompt_profile": "software-engineer-expert",
            "instructions": "My custom instruction",
        }], edges=[])
        r = self.ctx.put("/api/workflows/test-wf", json=body)
        self.assertEqual(r.status_code, 200)
        node = self.ctx.get("/api/workflows/test-wf").json()["workflow"]["nodes"][0]
        self.assertEqual(node["prompt_profile"], "software-engineer-expert")
        self.assertEqual(node["instructions"], "My custom instruction")

        # a workflow with no prompt_profile still validates and saves
        plain = self._wf(nodes=[{"id": "a", "agent": "matthew", "kind": "agent"}], edges=[])
        self.assertEqual(self.ctx.put("/api/workflows/test-wf", json=plain).status_code, 200)
        self.assertEqual(self.ctx.get("/api/workflows/test-wf/validate").json()["valid"], True)

    def test_workflow_crud(self):
        self.assertEqual(self.ctx.get("/api/workflows").json()["workflows"], [])
        r = self.ctx.put("/api/workflows/test-wf", json=self._wf())
        self.assertEqual(r.status_code, 200)
        got = self.ctx.get("/api/workflows/test-wf").json()["workflow"]
        self.assertEqual(got["id"], "test-wf")
        self.assertEqual(len(self.ctx.get("/api/workflows").json()["workflows"]), 1)
        self.assertTrue(self.ctx.delete("/api/workflows/test-wf").json()["deleted"])

    def test_workflow_save_rejects_invalid_id(self):
        # an unsafe/invalid id is rejected before any file write. (Traversal
        # forms like "../x", "a/b", "a\b" are covered directly in
        # test_workflows.TestIds against normalize_workflow_id, the boundary
        # the handler delegates to.)
        r = self.ctx.put("/api/workflows/-bad", json=self._wf(id="-bad"))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.ctx.get("/api/workflows").json()["workflows"], [])

    def test_workflow_validate(self):
        self.ctx.put("/api/workflows/test-wf", json=self._wf())
        r = self.ctx.get("/api/workflows/test-wf/validate").json()
        self.assertTrue(r["valid"])
        # invalid: unconditional cycle
        bad = self._wf(edges=[{"source": "a", "target": "b"},
                              {"source": "b", "target": "a"}])
        self.ctx.put("/api/workflows/test-wf", json=bad)
        r = self.ctx.get("/api/workflows/test-wf/validate").json()
        self.assertFalse(r["valid"])
        self.assertTrue(any("cycle" in e["message"] for e in r["errors"]))

    def test_workflow_templates_and_recommend(self):
        templates = self.ctx.get("/api/workflows/templates").json()["templates"]
        self.assertIn("sequential", templates)
        self.assertIn("parallel", templates)
        self.assertIn("reflection", templates)
        # POST instantiates a template in memory, returning
        # {workflow: ...} — the exact shape workspace.js loadTemplate() expects.
        seq = self.ctx.post("/api/workflows/from-template/sequential").json()["workflow"]
        self.assertEqual([n["id"] for n in seq["nodes"]],
                         ["architect", "developer", "tester", "reviewer"])
        self.assertEqual(len(seq["edges"]), 3)
        self.assertTrue(all(n["agent"] for n in seq["nodes"]),
                        "every sequential node references an agent")
        rec = self.ctx.get("/api/workflows/recommend?agents=4").json()
        self.assertIn("workflow", rec)
        self.assertIn("reasons", rec)
        self.assertEqual(self.ctx.post("/api/workflows/from-template/nope").status_code, 404)

    def test_workflow_templates_produce_real_graphs(self):
        # parallel: architect → {backend, frontend, security} → reviewer
        # (fan-out followed by a join) — a real multi-agent graph, not a list.
        par = self.ctx.post("/api/workflows/from-template/parallel").json()["workflow"]
        ids = {n["id"] for n in par["nodes"]}
        self.assertEqual(ids, {"architect", "backend", "frontend", "security", "reviewer"})
        self.assertEqual({e["source"] for e in par["edges"]},
                         {"architect", "backend", "frontend", "security"})
        self.assertEqual(sum(1 for e in par["edges"] if e["target"] == "reviewer"), 3,
                         "reviewer is a join node with three incoming edges")

        # reflection: conditional routing + a retry loop back to the developer.
        refl = self.ctx.post("/api/workflows/from-template/reflection").json()["workflow"]
        self.assertEqual(refl["entry"], ["developer"],
                         "a cyclic retry loop must declare an explicit entry node")
        conds = {(e["source"], e["target"], e["condition"]) for e in refl["edges"]}
        self.assertIn(("reviewer", "done", "success"), conds)
        self.assertIn(("reviewer", "developer", "failure"), conds)
        agents = [n for n in refl["nodes"] if n["kind"] == "agent"]
        self.assertTrue(all(n["agent"] for n in agents),
                        "every reflection agent node references an agent")
        self.assertEqual(sum(1 for n in refl["nodes"] if n["kind"] == "end"), 1)

        # Every predefined template (except the explicit "empty") yields a
        # non-empty graph with nodes, edges, and at least one agent reference.
        templates = self.ctx.get("/api/workflows/templates").json()["templates"]
        for slug in templates:
            wf = self.ctx.post(f"/api/workflows/from-template/{slug}").json()["workflow"]
            if slug == "empty":
                self.assertEqual(wf["nodes"], [])
                continue
            self.assertTrue(wf["nodes"], f"{slug}: template must produce nodes")
            self.assertTrue(wf["edges"], f"{slug}: template must produce edges")
            self.assertTrue(any(n["agent"] for n in wf["nodes"]),
                            f"{slug}: template must reference at least one agent")

    def test_workflow_run_validation_and_start(self):
        self.ctx.put("/api/workflows/test-wf", json=self._wf())
        # invalid graph -> 409 before any run
        bad = self._wf(edges=[{"source": "a", "target": "b"},
                              {"source": "b", "target": "a"}])
        self.ctx.put("/api/workflows/test-wf", json=bad)
        self.assertEqual(self.ctx.post("/api/workflows/test-wf/run",
                                       json={"initial_state": {}}).status_code, 409)
        # valid graph -> start_run is called (real dispatch stubbed out)
        self.ctx.put("/api/workflows/test-wf", json=self._wf())
        with mock.patch.object(self.routes_mod.workflow_engine, "start_run",
                               return_value="run-abc") as start:
            r = self.ctx.post("/api/workflows/test-wf/run",
                              json={"initial_state": {"x": 1}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["run_id"], "run-abc")
        start.assert_called_once()
        # run status endpoint 404 for an unknown run
        self.assertEqual(self.ctx.get("/api/workflows/runs/nope").status_code, 404)

    def test_workflow_dry_run_previews_without_dispatching(self):
        body = self._wf(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent"},
            {"id": "b", "agent": "alex", "kind": "agent"},
            {"id": "c", "agent": "sarah", "kind": "agent"},
        ], edges=[{"source": "a", "target": "b"}, {"source": "a", "target": "c"}],
            entry=["a"])
        with mock.patch.object(self.routes_mod.workflow_engine, "start_run") as start:
            r = self.ctx.post("/api/workflows/test-wf/dry-run", json=body)
        self.assertEqual(r.status_code, 200)
        plan = r.json()
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["waves"][0], ["a"])
        self.assertEqual(set(plan["waves"][1]), {"b", "c"})
        self.assertEqual(set(plan["statuses"].values()), {"completed"})
        start.assert_not_called()   # a dry-run never starts a real run

    def test_workflow_dry_run_rejects_invalid_graph(self):
        body = self._wf(edges=[{"source": "a", "target": "b"},
                               {"source": "b", "target": "a"}])
        r = self.ctx.post("/api/workflows/test-wf/dry-run", json=body)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(any("cycle" in e["message"] for e in r.json()["detail"]["errors"]))


class UiAssetsTestCase(unittest.TestCase):
    """Static-asset checks for the dashboard UI (index.html / app.css / app.js)."""

    STATIC = Path(REPO_ROOT) / "scripts" / "web_ui" / "static"

    @classmethod
    def setUpClass(cls):
        cls.index = (cls.STATIC / "index.html").read_text(encoding="utf-8")
        cls.css = (cls.STATIC / "app.css").read_text(encoding="utf-8")
        cls.js = (cls.STATIC / "app.js").read_text(encoding="utf-8")

    def test_prompt_box_below_workspace_grid(self):
        ws = self.index.index('<main id="workspace"')
        grid = self.index.index('id="workspace-grid"', ws)
        box = self.index.index('id="prompt-box"', ws)
        self.assertGreater(box, grid, "prompt box must sit below the workspace grid")

    def test_prompt_box_elements(self):
        self.assertIn('id="prompt-input"', self.index)
        self.assertIn('<textarea', self.index)
        self.assertIn('id="prompt-send"', self.index)
        self.assertIn('id="prompt-target"', self.index)

    def test_toolbar_dispatch_removed(self):
        self.assertNotIn('id="dispatch-form"', self.index)
        self.assertNotIn('id="dispatch-input"', self.index)
        self.assertNotIn('id="dispatch-run"', self.index)

    def test_graph_zoom_controls_present(self):
        self.assertIn('id="zoom-in"', self.index)

    # ── active workflow → Home projection (single source of truth) ──
    def test_home_consumes_active_workflow(self):
        # app.js loads the active workflow and renders its nodes as agent
        # windows (one panel per node, workflow edges as an SVG overlay).
        for token in ("refreshActiveWorkflow", "buildWorkflowWorkspace",
                      "homeNodes", "homeEdges", "resolved_model",
                      "/api/active-workflow", "workflow-mode",
                      "homeSignatureOf", "pollActiveRun"):
            self.assertIn(token, self.js)
        for token in (".home-edge", "#workspace-grid.workflow-mode"):
            self.assertIn(token, self.css)

    def test_home_uses_node_id_identity_not_agent_tag(self):
        # workflow windows are keyed by workflow node id, so two nodes using
        # the same agent stay independent (identity + sessions + consoles).
        for token in ("data-workflow-node-id", "workflowNodeId",
                      "nodeSessions", "nodeEvent", "setActiveNode",
                      "buildWorkflowWorkspace", "Ag.homeNodes"):
            self.assertIn(token, self.js)
        self.assertIn("card.dataset.workflowNodeId = opts.nodeId", self.js)

    def test_home_empty_state_when_no_workflow(self):
        # No active workflow → an empty workflow state, never the legacy
        # registry / agents_visible window layout.
        self.assertIn("No active workflow — Create or activate a workflow to start.",
                      self.js)
        self.assertIn("No active workflow — Create or activate a workflow to start.",
                      self.index)
        self.assertIn('if (!Ag.homeWorkflow)', self.js)
        # the legacy registry/prefs-driven window builder is gone
        self.assertNotIn("function visibleAgents", self.js)
        self.assertNotIn("function gridFor", self.js)

    def test_workflow_edges_reference_node_ids(self):
        # Home edges are built from WorkflowEdge and carry their node ids.
        self.assertIn('line.setAttribute("data-source", e.source)', self.js)
        self.assertIn('line.setAttribute("data-target", e.target)', self.js)

    def test_home_layout_system(self):
        # Home has an independent visual layout layer: a mode selector, zoom,
        # reset, and per-workflow layout persistence — never touching the graph.
        for token in ('id="home-layout-select"', 'id="home-zoom-in"',
                      'id="home-zoom-out"', 'id="home-layout-reset"',
                      'value="workflow"', 'value="grid"', 'value="horizontal"',
                      'value="vertical"', 'value="compact"', 'value="custom"'):
            self.assertIn(token, self.index)
        for token in ("setHomeLayout", "setHomeZoom", "resetHomeLayout",
                      "setCustomNode", "computeLayout", "workflowOrder",
                      "gridLayout", "horizontalLayout", "verticalLayout",
                      "customLayout", "zova-home-layouts", "homeLayouts",
                      "panelSizes", "cssSize"):
            self.assertIn(token, self.js)
        # custom drag/resize handle + layout state are separate from workflow JSON
        self.assertIn(".panel-resize", self.css)
        self.assertIn('localStorage.setItem(HOME_LAYOUT_KEY', self.js)
        # the panel sizing policy is centralized in CSS variables
        for var in ("--home-panel-min-w", "--home-panel-min-h",
                    "--home-panel-pref-w", "--home-panel-pref-h",
                    "--home-panel-compact-w", "--home-panel-compact-h"):
            self.assertIn(var, self.css)

    def test_home_panels_draggable_resizable(self):
        # Every Home panel is draggable (header) + resizable (corner handle) in
        # any mode; a manual gesture promotes the layout to Custom (visual layer
        # only — never touching the workflow graph).
        for token in ("switchToCustom", "bindPanelInteractions",
                      "clampToWorkspace", "bringToFront",
                      'card.classList.add("dragging")', "pointerdown",
                      'closest("button, input, select, textarea'):
            self.assertIn(token, self.js)
        for token in ("--home-panel-resize-min-w", "--home-panel-resize-min-h",
                      "cursor: grab", "cursor: grabbing", "nwse-resize"):
            self.assertIn(token, self.css)

    def test_active_workflow_api_wired(self):
        routes = (Path(REPO_ROOT) / "scripts" / "web_ui" / "routes.py").read_text(
            encoding="utf-8")
        for token in ('"/api/active-workflow"', "active_workflow_id",
                      "workflow_engine.start_run", "mode", "workflow"):
            self.assertIn(token, routes)
        self.assertIn('id="zoom-out"', self.index)
        self.assertIn('id="zoom-reset"', self.index)

    def test_js_binds_prompt_box_and_zoom(self):
        self.assertIn('$("#prompt-box")', self.js)
        self.assertIn('$("#prompt-input")', self.js)
        self.assertIn("requestSubmit", self.js)
        self.assertIn("zoomBy(", self.js)
        self.assertIn("resetGraphView", self.js)
        self.assertIn('key === "Enter" && !e.shiftKey', self.js)
        self.assertIn('"graph-world"', self.js)

    def test_js_workspace_builds_into_grid(self):
        self.assertIn('$("#workspace-grid")', self.js)
        self.assertIn("wg.style.gridTemplateColumns", self.js)

    # ── Phase 23B: compact auto-grow prompt textarea ────────────────
    def test_prompt_autogrow_compact_default(self):
        self.assertIn("min-height: 56px", self.css)
        self.assertIn("max-height: 240px", self.css)
        self.assertIn("resize: none", self.css)
        self.assertIn('rows="2"', self.index)
        # autosize clamps between min and max and only scrolls at the cap
        self.assertIn("Math.min(240, Math.max(56, input.scrollHeight))", self.js)
        self.assertIn('input.style.overflowY = h >= 240 ? "auto" : "hidden"', self.js)
        # Enter=send / Shift+Enter=newline preserved
        self.assertIn('key === "Enter" && !e.shiftKey', self.js)

    # ── Phase 23B: graph mouse/touch panning ────────────────────────
    def test_graph_pan_handlers(self):
        for token in ("pointerdown", "pointermove", "pointerup", "pointercancel"):
            self.assertIn(token, self.js)
        self.assertIn("setPointerCapture", self.js)
        self.assertIn("releasePointerCapture", self.js)
        # pan delta converted to viewBox units and divided by current zoom
        self.assertIn("/ GraphView.scale", self.js)
        # middle-mouse pan tolerated, node-drag excluded
        self.assertIn("e.button !== 0 && e.button !== 1", self.js)
        self.assertIn('closest(".g-node")', self.js)
        # touch drag enabled on the canvas
        self.assertIn("touch-action: none", self.css)
        self.assertIn("cursor: grabbing", self.css)

    def test_drag_vs_click_guard(self):
        self.assertIn("if (panState.moved) { panState.moved = false; return; }", self.js)
        self.assertIn("panState.active", self.js)
        # zoom still cursor-anchored
        self.assertIn("zoomBy(Math.pow(1.15, -e.deltaY / 100), p.x, p.y)", self.js)

    # ── Phase 23B: readable node labels ─────────────────────────────
    def test_readable_node_labels(self):
        # halo-backed label font (readable over the edges)
        self.assertIn("font-size: 14px", self.css)
        self.assertIn("paint-order: stroke", self.css)
        self.assertIn("stroke: var(--bg)", self.css)
        # label position driven by the band-based LOD helper + truncation
        self.assertIn('lbl.setAttribute("y", GP.labelYOffset(r, band))', self.js)
        self.assertIn('lbl.classList.toggle("hidden"', self.js)
        self.assertNotIn("r + 12", self.js)
        self.assertIn("raw.length > 18 ? raw.slice(0, 16) +", self.js)

    # ── Phase 23B: zoom controls remain functional ──────────────────
    def test_zoom_controls_still_bound(self):
        self.assertIn('$("#zoom-in").addEventListener("click", () => zoomBy(1.3))', self.js)
        self.assertIn('$("#zoom-out").addEventListener("click", () => zoomBy(1 / 1.3))', self.js)
        self.assertIn('$("#zoom-reset").addEventListener("click", resetGraphView)', self.js)
        # zoom clamping lives in the shared graph-math camera (GP.zoomAtPoint)
        self.assertIn("GP.zoomAtPoint(", self.js)
        self.assertIn("zoomBy(", self.js)

    # ── Phase 24B: graph rebuild (layout, LOD, filters, core view) ──
    def test_graph_stage_and_filters_present(self):
        self.assertIn('id="graph-stage"', self.index)
        self.assertIn('id="graph-filters"', self.index)
        self.assertIn("refreshGraphView", self.js)
        self.assertIn("buildGraphFilters", self.js)
        self.assertIn("GP.applySectionFilter", self.js)
        self.assertIn("GP.coreGraph", self.js)
        self.assertIn("GP.presentFolders", self.js)
        self.assertIn("f-chip", self.css)

    def test_graph_band_culling_and_layout_plane(self):
        # edge culling on band change, hiding whole edge groups
        self.assertIn("GP.edgeVisibleFor(p, band, graphEls.byName, graphEls.sectionHubs)", self.js)
        self.assertIn('grp.style.display = show ? "" : "none"', self.js)
        # zoomed-out band hides everything but the section-hub spine
        self.assertIn('(band === "out" && !graphEls.sectionHubs[nd.name]) ? "none" : ""', self.js)
        self.assertIn("GP.sectionHubNames(nodes)", self.js)
        # layout runs in the larger section-aware world plane
        self.assertIn("GP.runLayout(nodes, edges, { iterations: 500 })", self.js)
        # band-specific edge weight/opacity in CSS
        self.assertIn('data-band="out"', self.css)
        self.assertIn('stroke-width: .5', self.css)
        self.assertIn('stroke-width: 1.1', self.css)

    # ── Phase 24D: graph window resize / detach / fullscreen ───────
    def test_graph_window_controls_present(self):
        for ident in ("graph-detach", "graph-fullscreen", "graph-restore",
                      "graph-vsplit", "graph-float", "graph-fresize"):
            self.assertIn(f'id="{ident}"', self.index)
        # the splitter sits between the graph panel and the related panel
        gp = self.index.index('id="graph-panel"')
        vs = self.index.index('id="graph-vsplit"', gp)
        rp = self.index.index('id="related-panel"', vs)
        self.assertLess(gp, vs)
        self.assertLess(vs, rp)
        # detach/restore are title-row icon buttons, restore starts hidden
        self.assertIn('id="graph-restore" class="icon-btn hidden"', self.index)

    def test_graph_window_js_hooks(self):
        for fn in ("detachGraph", "restoreGraph", "fullscreenGraph",
                   "reflowGraph", "saveGraphWindowState", "loadGraphWindowState"):
            self.assertIn(fn, self.js)
        self.assertIn("requestFullscreen", self.js)
        self.assertIn("fullscreenchange", self.js)
        self.assertIn('"#graph-float"', self.js)
        self.assertIn("graphWin.detached", self.js)
        self.assertIn('ssSet("graph.h"', self.js)
        # docked graph height restored from session storage at init
        self.assertIn('setProperty("--graph-h", loadGraphH() + "px")', self.js)
        # same DOM node is moved, so graph state survives detach
        self.assertIn("float.appendChild(panel)", self.js)
        self.assertIn("vsplit.parentNode.insertBefore(panel, vsplit)", self.js)

    def test_graph_window_css(self):
        self.assertIn(":fullscreen", self.css)
        self.assertIn("--graph-h", self.css)
        self.assertIn("#graph-panel.detached", self.css)
        self.assertIn("#graph-fresize", self.css)
        self.assertIn("nwse-resize", self.css)
        self.assertIn("row-resize", self.css)
        self.assertIn("cursor: move", self.css)
        self.assertIn("pointer-events: none", self.css)

    # ── Phase 25: settings modal (AI connections, models, modes) ─────
    def test_settings_assets(self):
        self.assertIn('id="settings-btn"', self.index)
        for ident in ("settings-backdrop", "settings-modal", "settings-nav",
                      "settings-content", "settings-close"):
            self.assertIn(f'id="{ident}"', self.index)
        self.assertIn('<script src="/static/settings.js"></script>', self.index)
        self.assertIn("window.MACSettings", self.js)  # settings.js loaded before app.js

    def test_settings_modal_css(self):
        for cls in (".settings-modal", ".settings-nav", ".conn-wizard",
                    ".sec-table", ".model-chips", ".adv-fields", ".verify-badge"):
            self.assertIn(cls, self.css)

    def test_roles_and_profile_settings_assets(self):
        """Roles + Repository-analysis sections are wired in settings.js."""
        settings_js = (self.STATIC / "settings.js").read_text(encoding="utf-8")
        for token in ("viewRoles", "viewProfile", "Create custom role",
                      "Agent role assignment", "Suggested roles",
                      "/api/settings/roles", "/api/settings/profile"):
            self.assertIn(token, settings_js)
        # role-detail styling exists for the role cards
        self.assertIn(".role-details", self.css)
        self.assertIn(".role-sub", self.css)

    def test_task_role_override_assets(self):
        """The task detail exposes a temporary role override (app.js)."""
        self.assertIn("role override", self.js)
        self.assertIn("/api/tasks/", self.js)
        self.assertIn("Set role override", self.js)

    def test_model_header_sync_and_searchable_combo(self):
        """Model header derives from current UI state; selector is searchable."""
        settings_js = (self.STATIC / "settings.js").read_text(encoding="utf-8")
        for token in ("modelCombo", "combo-search", "type to filter",
                      "ArrowDown", "ArrowUp", "Escape", "custom provider / model",
                      "refreshAgentModels"):
            self.assertIn(token, settings_js)
        # app.js refreshes the p-model header from Ag.agents[].model
        self.assertIn('card.querySelector(".p-model")', self.js)
        self.assertIn("refreshAgentModels", self.js)
        self.assertIn(".combo", self.css)

    # ── Agent-output session persistence (regression) ────────────────
    def test_agent_event_persists_session_before_panel_render(self):
        """onAgentEvent must persist into Ag.sessions[tag] BEFORE any DOM lookup,
        so events for agents without a rendered panel are never dropped."""
        js = self.js
        self.assertIn("Ag.sessions[tag] = Ag.sessions[tag] || []", js)
        self.assertIn("const card = panelEl(tag);", js)
        self.assertLess(
            js.index("Ag.sessions[tag] = Ag.sessions[tag] || []"),
            js.index("const card = panelEl(tag);"),
            "session persistence must precede the panel lookup")
        self.assertIn("if (!card) return;", js)
        # no wrap-and-drop path may remain inside onAgentEvent itself
        start = js.index("function onAgentEvent")
        end = js.index("function buildStatusTable")  # next function after it
        self.assertNotIn("if (card) {", js[start:end])

    def test_status_events_persisted_but_never_console_rows(self):
        """status events are persisted (never lost) but rendered only as dots,
        both live and on replay — session and DOM never diverge."""
        js = self.js
        self.assertIn("const PANEL_KINDS = [\"run\", \"line\", \"error\", \"usermsg\", \"taskline\"];", js)
        self.assertIn("if (PANEL_KINDS.includes(ev.kind) && !seen) {", js)
        self.assertIn("if (PANEL_KINDS.includes(ev.kind)) {", js)

    def test_agent_event_dedupe_and_tail(self):
        """Live events are de-duplicated by backend seq and capped by tail."""
        self.assertIn("e.n !== undefined && e.n === ev.n", self.js)
        self.assertIn("const SESSION_TAIL = 800;", self.js)

    def test_load_sessions_merges_never_replaces(self):
        """loadSessions merges the init snapshot over live events (never reverts
        already-received output)."""
        js = self.js
        self.assertIn("Merge, never replace", js)
        self.assertIn("Ag.sessions[tag] = merged;", js)

    def test_window_macapp_test_hook(self):
        """The headless test hook mirrors window.MACSettings."""
        self.assertIn("window.MACApp", self.js)

    def test_backend_restart_detection(self):
        """A backend restart resets WebState's "n" sequence; the frontend must
        detect the regression and clear the stale session mirror so the n-dedup
        never swallows the new process's output."""
        js = self.js
        self.assertIn("let lastBackendN = 0;", js)
        self.assertIn("function checkBackendRestart(snapN)", js)
        self.assertIn("Ag.sessions = {};", js)
        # pollState drives the detection on every /api/state poll
        self.assertIn("checkBackendRestart(snap.n)", js)


class WorkspaceAssetsTestCase(unittest.TestCase):
    """Static-asset checks for the Agent Workspace / workflow designer."""

    STATIC = Path(REPO_ROOT) / "scripts" / "web_ui" / "static"

    @classmethod
    def setUpClass(cls):
        cls.html = (cls.STATIC / "workspace.html").read_text(encoding="utf-8")
        cls.js = (cls.STATIC / "workspace.js").read_text(encoding="utf-8")
        cls.css = (cls.STATIC / "app.css").read_text(encoding="utf-8")
        cls.index = (cls.STATIC / "index.html").read_text(encoding="utf-8")

    def test_workspace_page_served_and_linked(self):
        # the page is linked from the dashboard topbar
        self.assertIn('href="/workspace"', self.index)
        self.assertIn("Agent Workspace", self.html)

    def test_workspace_layout_regions(self):
        for ident in ("ws-topbar", "ws-library", "ws-library-list", "ws-canvas",
                      "ws-world", "ws-edges", "ws-nodes", "ws-props",
                      "ws-props-body", "ws-run-legend"):
            self.assertIn(f'id="{ident}"', self.html)

    def test_workspace_controls(self):
        for ident in ("ws-new", "ws-save", "ws-validate", "ws-run",
                      "ws-run-cancel", "ws-template-select", "ws-recommend",
                      "ws-duplicate", "ws-delete", "ws-zoom-in", "ws-zoom-out",
                      "ws-zoom-reset"):
            self.assertIn(f'id="{ident}"', self.html)

    def test_workspace_js_model_independence(self):
        # a node carries agent/model/roles overrides, never touching AgentSpec
        for token in ("agent", "model", "roles", "instructions", "enabled"):
            self.assertIn(token, self.js)
        self.assertIn("Auto / runtime default", self.js)

    def test_workspace_js_canvas(self):
        for token in ("addNode", "renderEdges", "renderNodes", "onNodePointerDown",
                      "edgeKey", "select", "markDirty", "runWorkflow", "pollRun",
                      "validateWorkflow", "loadTemplate", "recommend"):
            self.assertIn(token, self.js)

    def test_workspace_css(self):
        for cls in (".ws-body", ".ws-topbar", ".ws-library", ".ws-canvas",
                    ".wf-node", ".wf-in", ".wf-out", ".ws-edge", ".ws-props",
                    ".st-completed", ".st-running", ".st-failed", ".st-skipped"):
            self.assertIn(cls, self.css)

    # ── model picker: searchable + display sync ─────────────────────
    def test_workspace_model_picker_searchable(self):
        for token in ("modelCombo", "combo-search", "type to filter (provider / model)",
                      "ArrowDown", "ArrowUp", "Escape", "custom provider / model"):
            self.assertIn(token, self.js)

    def test_workspace_model_selection_updates_display(self):
        # choosing a model writes node.model, marks dirty, and re-renders the card
        self.assertIn("node.model = value", self.js)
        self.assertIn("renderNodes()", self.js)
        # the node card's model line reads the live node.model (Auto when empty)
        self.assertIn('sub.textContent = n.model || "Auto / runtime default"', self.js)

    def test_workspace_model_auto_vs_explicit(self):
        # Auto is a real, selectable option distinct from an explicit override,
        # and reopening a node re-reads its persisted model
        self.assertIn('let value = node.model || ""', self.js)
        self.assertIn("combo-auto", self.js)
        self.assertIn("Auto → resolves to", self.js)
        self.assertIn(".combo-value.combo-auto", self.css)

    # ── v2: visual builder (add-agent, node design, dry-run, validation) ─
    def test_workspace_add_agent_and_search(self):
        self.assertIn('id="ws-add-agent"', self.html)
        self.assertIn('id="ws-agent-search"', self.html)
        self.assertIn("type to filter agents", self.html)
        self.assertIn("matchingAgents", self.js)

    def test_workspace_add_agent_click_and_drag(self):
        # click-to-add and library→canvas drag/drop share the same addNode path
        for token in ("addNode", "nextId", "draggable", "dragstart", "dragover",
                      "drop", "dragend", "application/x-zova-agent", "bindDragDrop"):
            self.assertIn(token, self.js)
        self.assertIn('card.draggable = true', self.js)
        self.assertIn('e.dataTransfer.setData(AGENT_DRAG_TYPE, a.agent)', self.js)
        self.assertIn('canvasPos(e)', self.js)          # client → canvas coords
        self.assertIn("addNode(agent, { x: p.x, y: p.y })", self.js)
        # + Add Agent is a secondary entry point that focuses the search field
        self.assertIn('search.value = ""; S.agentFilter = ""; renderLibrary(); search.focus()', self.js)

    def test_workspace_restores_last_workflow_on_refresh(self):
        # a saved workflow is remembered and auto-loaded so refresh keeps nodes
        for token in ("rememberWorkflow", "lastWorkflow", "forgetWorkflow",
                      "zova-last-workflow"):
            self.assertIn(token, self.js)
        self.assertIn("if (last) loadWorkflow(last)", self.js)

    def test_workspace_canvas_fills_horizontal_space(self):
        # the canvas must stretch between the library/properties panels, and the
        # world/nodes layers must fill the canvas (regression: 75.6px collapse)
        self.assertIn('class="ws-page"', self.html)
        self.assertIn("html.ws-page", self.css)
        self.assertIn("body.ws-body", self.css)
        # html + body are forced to the full viewport so the workspace can never
        # shrink-to-fit its content (the old 585.6px collapse).
        self.assertIn("min-width: 100vw", self.css)
        self.assertIn("width: 100vw", self.css)
        # .ws-main stretches to the full body width
        self.assertIn(".ws-main { flex: 1 1 auto; align-self: stretch; display: flex; min-height: 0; min-width: 0; width: 100%; }", self.css)
        # the canvas column is the sole flex-grow item, so it takes ALL remaining
        # horizontal space between the 230px library and 280px properties panels
        self.assertIn(".ws-canvas-wrap { flex: 1 1 auto; position: relative; min-width: 0; width: 100%; display: flex; flex-direction: column; }", self.css)
        self.assertIn(".ws-canvas { flex: 1 1 0; position: relative; overflow: hidden; min-width: 0; width: 100%;", self.css)
        # the world/nodes layers fill the canvas
        self.assertIn(".ws-world { position: absolute; left: 0; top: 0; width: 100%; height: 100%; transform-origin: 0 0; }", self.css)
        self.assertIn(".ws-nodes { position: absolute; left: 0; top: 0; width: 100%; height: 100%; }", self.css)

    def test_workspace_outer_container_viewport_width(self):
        # regression: the workspace root (html/body) must be viewport-anchored
        # (vw units) so no outer wrapper can constrain it to its content width
        # (the reported 585.6px collapse).
        self.assertIn('class="ws-page"', self.html)
        self.assertIn("html.ws-page", self.css)
        self.assertIn("body.ws-body", self.css)
        self.assertIn("width: 100vw", self.css)
        self.assertIn("min-width: 100vw", self.css)
        self.assertIn("max-width: 100vw", self.css)
        self.assertIn("display: flex", self.css)
        self.assertIn("flex-direction: column", self.css)

    def test_workspace_node_design(self):
        for token in ("wf-node-dot", "wf-node-agent", "wf-node-state",
                      "STATE_LABEL", "nodeState"):
            self.assertIn(token, self.js)
        self.assertIn(".wf-node-dot", self.css)
        self.assertIn(".wf-node-state", self.css)
        self.assertIn(".wf-node-agent", self.css)

    def test_workspace_dry_run_and_fit(self):
        self.assertIn('id="ws-dry-run"', self.html)
        self.assertIn("dryRunWorkflow", self.js)
        self.assertIn("fitToScreen", self.js)
        self.assertIn("/dry-run", self.js)

    def test_workspace_validation_display(self):
        self.assertIn('id="ws-validation"', self.html)
        self.assertIn("showValidation", self.js)
        self.assertIn("formatErrors", self.js)
        self.assertIn(".ws-validation", self.css)

    def test_workspace_presets(self):
        for label in ("Planner / Workers / Reviewer", "Parallel Specialists",
                      "Research / Analysis / Writer", "Empty Workflow",
                      "Developer / Reviewer / Retry"):
            self.assertIn(label, self.js)

    # ── Activate Workflow (Designer → active_workflow_id) ─────────────
    def test_workspace_activate_button_exists(self):
        # A visible Activate button lives in the Designer toolbar.
        self.assertIn('id="ws-activate"', self.html)
        self.assertIn("Activate Workflow", self.html)

    def test_workspace_activate_uses_existing_api_contract(self):
        # The button wires into the existing PUT /api/active-workflow contract
        # (payload {workflow_id}) and verifies via GET — no new state system.
        for token in ("activateWorkflow", "refreshActiveIndicator",
                      "updateActivateButton", "activeWorkflowId"):
            self.assertIn(token, self.js)
        self.assertIn('put("/api/active-workflow", { workflow_id: id })', self.js)
        self.assertIn('api("/api/active-workflow")', self.js)
        # save-first when dirty OR untitled/id-less (never activate an outdated
        # or un-persisted version) — "untitled" is never a valid workflow id
        self.assertIn('S.workflow.id === "untitled"', self.js)
        self.assertIn("saveWorkflow", self.js)
        # success + failure UI states
        self.assertIn('"✓ Active"', self.js)
        self.assertIn('"save cancelled', self.js)
        # the active state is a button style, not a second state store
        self.assertIn(".btn.active", self.css)

    def test_workspace_activate_reflects_active_workflow(self):
        # workspace.js reads active_workflow_id and reflects it on the button
        self.assertIn('$("#ws-activate")', self.js)
        self.assertIn("S.activeWorkflowId === S.workflow.id", self.js)
        self.assertIn('btn.classList.toggle("active", isActive)', self.js)
        # the activate action is bound to the button
        self.assertIn('$("#ws-activate").addEventListener("click", activateWorkflow)', self.js)

    # ── Prompt Library (Prompt Profile → Instruction) ───────────────
    def test_workspace_prompt_profile_assets(self):
        # the properties panel adds a Prompt Profile selector + preview + apply
        for token in ("Prompt Profile", "ws-prompt-select", "ws-prompt-preview",
                      "Apply Prompt", "suggestPromptsForNode", "suggestPromptRole",
                      "onPromptSelected", "applyPromptToNode", "fetchPromptText",
                      "prompt_profile", "/api/prompts"):
            self.assertIn(token, self.js)
        # the preview + apply styles are present
        for cls in (".ws-prompt-select", ".ws-prompt-preview",
                    ".ws-prompt-preview-name", ".ws-prompt-preview-desc",
                    ".ws-prompt-preview-caps", ".ws-prompt-apply"):
            self.assertIn(cls, self.css)

    def test_workspace_prompt_safe_apply(self):
        # safe application: only auto-fill the Instruction when it is empty — a
        # custom instruction is never silently overwritten (Apply does that).
        self.assertIn('!(n.instructions || "").trim()', self.js)
        self.assertIn("n.prompt_profile = id", self.js)
        self.assertIn("n.instructions = text", self.js)
        # the prompt dropdown offers both a role-filtered group and all prompts
        self.assertIn('sg.label = "Suggested"', self.js)
        self.assertIn('all.label = "All Prompts"', self.js)

    def test_prompt_api_wired(self):
        routes = (Path(REPO_ROOT) / "scripts" / "web_ui" / "routes.py").read_text(
            encoding="utf-8")
        for token in ('"/api/prompts"', '"/api/prompts/{prompt_id}"',
                      "prompt_library.suggest_prompts_for_role",
                      "prompt_library.list_prompts",
                      "prompt_library.get_prompt"):
            self.assertIn(token, routes)

    # ── Phase 2: Task → Prompt recommendation + model capabilities ──
    def test_workspace_prompt_recommendation_assets(self):
        # Task / Purpose + Suggest Prompt + recommendation preview + model reqs
        for token in ("Task / Purpose", "Suggest Prompt", "Recommended Prompt",
                      "Model requirements", "suggestPrompt",
                      "nodeTaskDescription", "nodePromptRole",
                      "renderRecommendationPreview", "renderModelCapabilityPreview",
                      "taskRecs", "/api/prompts/recommend"):
            self.assertIn(token, self.js)
        for cls in (".ws-task-input", ".ws-suggest-prompt", ".ws-recs",
                    ".ws-rec-item", ".ws-rec-score", ".ws-recs-note",
                    ".ws-model-prefs", ".ws-model-prefs-table"):
            self.assertIn(cls, self.css)

    def test_phase2_api_wired(self):
        routes = (Path(REPO_ROOT) / "scripts" / "web_ui" / "routes.py").read_text(
            encoding="utf-8")
        for token in ('"/api/prompts/recommend"', '"/api/models/capabilities"',
                      '"/api/models/recommend"', "recommend_prompts",
                      "recommend_model_capabilities", "model_archetypes"):
            self.assertIn(token, routes)

    # ── Phase 3: Model Registry + model selection UI ────────────────
    def test_workspace_model_registry_assets(self):
        for token in ("Recommended Models", "loadModelCatalog",
                      "renderModelRecommendation", "renderModelDetails",
                      "modelProviderOptions", "ws-model-provider",
                      "ws-model-rec-item", "ws-model-rec-score",
                      "ws-model-rec-apply", "explicit selection",
                      "modelById", "/api/models"):
            self.assertIn(token, self.js)
        for cls in (".ws-model-recs", ".ws-model-recs-title",
                    ".ws-model-provider", ".ws-model-rec-item",
                    ".ws-model-rec-score", ".ws-model-rec-apply",
                    ".ws-model-details", ".ws-model-details-row"):
            self.assertIn(cls, self.css)

    def test_phase3_api_wired(self):
        routes = (Path(REPO_ROOT) / "scripts" / "web_ui" / "routes.py").read_text(
            encoding="utf-8")
        for token in ('"/api/models"', '"/api/models/{model_id:path}"',
                      "model_registry.select_models", "model_registry.list_models",
                      "model_registry.get_model", "explicit_model",
                      "hard_requirements", "prompt_profile"):
            self.assertIn(token, routes)


if __name__ == "__main__":
    unittest.main()