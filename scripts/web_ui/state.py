"""WebState — drains the shared RunHub into dashboard-friendly sessions.

The dashboard consumes ``scripts.core.run_hub.HUB`` exactly like the ZOVA
terminal does: a monotonically increasing ``seq`` cursor over ``HUB.events``.
WebState additionally tracks dashboard-local events (orchestrator task-run
output, user messages) and flattens both sources into one ordered stream for
the SSE endpoint. Per-agent sessions (the "conversation" of each panel) are
kept with a fixed tail size.

Thread-safety: all mutations happen under ``self.lock``; the hub lock is taken
in a consistent self->hub order so draining never races an append.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from scripts.core.agents import AGENTS, PROJECT_ROOT
from scripts.core.run_hub import HUB

_REPO_ROOT = PROJECT_ROOT
PREFS_PATH = Path("_logs") / "web_ui_prefs.json"

SESSION_TAIL = 800          # max events retained per agent session
AGENT_TAGS = tuple(tag for tag, _name, _agent in AGENTS)

DEFAULT_PREFS: dict = {
    "layout": "4",
    "agents_visible": ["m1", "m2", "m3", "m4", "m5", "m6"],
    "active_tag": "m1",
    "selected_node": None,
    "sidebar_w": 270,
    "bottom_h": 200,
    "graph_h": 300,      # graph canvas height (Settings → Graph)
    "minimap_on": True,  # graph minimap visible at start (Settings → Graph)
    "conn_status": {},   # provider -> "tested" | "validation_failed" (Settings)
    # The Workflow Designer's saved graph is the single source of truth for
    # the Home agent windows and the Home runtime path. None = the classic
    # registry/prefs-driven Home (all agents, no graph).
    "active_workflow_id": None,
}

_SESSION_KINDS = {"run", "line", "error", "status"}
_TASKLINE_KINDS = {"taskline", "usermsg"}


class WebState:
    """Flattens HUB + dashboard events into one ordered, drainable stream."""

    def __init__(self, hub: object = HUB, session_tail: int = SESSION_TAIL) -> None:
        self.hub = hub
        self.lock = threading.Lock()
        self.session_tail = session_tail

        self._hub_cursor = 0
        self._n = 0
        self._own_events: list[dict] = []
        self._own_cursor = 0
        self._sessions: dict[str, list[dict]] = {}
        self._prev_running = 0
        self._task_procs: dict[str, subprocess.Popen] = {}

        self.prefs: dict = dict(DEFAULT_PREFS)
        self.load_prefs()

    # ------------------------------------------------------------ pref helpers

    def load_prefs(self) -> None:
        """Restore persisted UI preferences (best-effort, never raises)."""
        try:
            path = _REPO_ROOT / PREFS_PATH
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                for key in DEFAULT_PREFS:
                    if key in data and data[key] is not None:
                        self.prefs[key] = data[key]
        except (OSError, ValueError, TypeError):
            pass
        self._sanitize_prefs()

    def _sanitize_prefs(self) -> None:
        valid = AGENT_TAGS
        visible = [t for t in self.prefs.get("agents_visible", []) if t in valid]
        self.prefs["agents_visible"] = visible[:6]  # max 6 visible panels
        if self.prefs.get("layout") not in ("1", "2", "3", "4", "6"):
            self.prefs["layout"] = "4"
        active = self.prefs.get("active_tag")
        if active not in valid:
            self.prefs["active_tag"] = visible[0] if visible else (valid[0] if valid else None)
        graph_h = self.prefs.get("graph_h")
        if not isinstance(graph_h, (int, float)) or not 140 <= graph_h <= 560:
            self.prefs["graph_h"] = 300
        if not isinstance(self.prefs.get("minimap_on"), bool):
            self.prefs["minimap_on"] = True
        conn_status = self.prefs.get("conn_status")
        if not isinstance(conn_status, dict):
            self.prefs["conn_status"] = {}
        else:
            self.prefs["conn_status"] = {
                k: v for k, v in conn_status.items()
                if isinstance(k, str) and v in ("tested", "validation_failed")
            }
        awid = self.prefs.get("active_workflow_id")
        self.prefs["active_workflow_id"] = (
            awid if isinstance(awid, str) and awid.strip() else None)

    def save_prefs(self) -> None:
        try:
            path = _REPO_ROOT / PREFS_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.prefs, indent=2), encoding="utf-8")
        except OSError:
            pass

    def update_prefs(self, patch: dict) -> dict:
        with self.lock:
            for key, value in patch.items():
                if key in DEFAULT_PREFS:
                    self.prefs[key] = value
            self._sanitize_prefs()
        self.save_prefs()
        return dict(self.prefs)

    # ------------------------------------------------------------ own events

    def _own(self, tag: str, kind: str, text: str) -> None:
        with self.lock:
            self._n += 1
            self._own_events.append({
                "n": self._n, "tag": tag, "kind": kind, "text": text, "source": "own",
            })

    def push_task_run(self, name: str, text: str) -> None:
        self._own(name, "run", text)

    def push_task_line(self, name: str, text: str) -> None:
        self._own(name, "taskline", text)

    def push_task_done(self, name: str, text: str) -> None:
        self._own(name, "status", text)

    def push_usermsg(self, tag: str, text: str) -> None:
        self._own(tag, "usermsg", text)

    def push_system(self, tag: str, text: str) -> None:
        self._own(tag, "status", text)

    # ------------------------------------------------------------ task procs

    def register_task_proc(self, name: str, proc: subprocess.Popen) -> None:
        with self.lock:
            self._task_procs[name] = proc

    def pop_task_proc(self, name: str) -> subprocess.Popen | None:
        with self.lock:
            return self._task_procs.pop(name, None)

    def task_running(self, name: str) -> bool:
        with self.lock:
            proc = self._task_procs.get(name)
            return proc is not None and proc.poll() is None

    # ------------------------------------------------------------ drain

    def drain(self) -> list[dict]:
        """Return newly available events (HUB + dashboard), oldest first."""
        out: list[dict] = []
        hub = self.hub
        with self.lock:
            with hub.lock:
                while self._hub_cursor < len(hub.events):
                    e = hub.events[self._hub_cursor]
                    self._hub_cursor += 1
                    self._n += 1
                    out.append({
                        "n": self._n,
                        "seq": e.get("seq"),
                        "tag": e.get("tag", "master"),
                        "kind": e.get("kind", "line"),
                        "text": e.get("text", ""),
                        "source": "hub",
                    })
                hub_running = hub.running
            while self._own_cursor < len(self._own_events):
                out.append(self._own_events[self._own_cursor])
                self._own_cursor += 1

            if hub_running > 0 and self._prev_running == 0:
                self._sessions = {}  # new dispatch batch → fresh conversations
            self._prev_running = hub_running

            for e in out:
                tag = e["tag"]
                if e["kind"] in (_SESSION_KINDS | _TASKLINE_KINDS):
                    bucket = self._sessions.setdefault(tag, [])
                    bucket.append(e)
                    if len(bucket) > self.session_tail:
                        del bucket[: len(bucket) - self.session_tail]
        return out

    # ------------------------------------------------------------ snapshots

    def snapshot(self) -> dict:
        """Serializable telemetry snapshot (no sessions — see ``sessions``)."""
        hub = self.hub
        with hub.lock:
            return {
                "statuses": dict(hub.statuses),
                "progress": dict(hub.progress),
                "token_usage": dict(hub.token_usage),
                "prompts": dict(hub.prompts),
                "running": hub.running,
                "session_tags": sorted(hub.session_tags),
                "n": self._n,
            }

    def sessions(self) -> dict[str, list[dict]]:
        """Per-tag session events (conversations) as serializable lists."""
        with self.lock:
            return {
                tag: [dict(e) for e in events]
                for tag, events in self._sessions.items()
            }