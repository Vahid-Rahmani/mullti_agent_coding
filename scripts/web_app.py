#!/usr/bin/env python3
"""ZOVA WEB — MultiAgentCoding Control-Plane Web Dashboard.

A zero-dependency web UI for the agent swarm. Serves a single retro-style
dashboard that mirrors the live state the launcher/terminal already persists:

  * per-slot swarm state  ``_logs/swarm/m<slot>.json``  (idle / working / helper
    + dynamic title like ``M3-Helper->M1``),
  * per-agent run logs    ``_logs/<agent>.log``         (tail preview),
  * inbox queue           ``_inbox/<agent>.task``       (pending / done / claimed),
  * swarm feedback loop   ``_logs/swarm_feedback.jsonl`` + the swarm brief.

Pure stdlib (``http.server``) so it runs anywhere Python does — the same
zero-dependency rule as ``scripts/swarm.py``. The dashboard reuses
``swarm.SLOTS`` / ``swarm.read_swarm_state`` / ``swarm.load_feedback`` /
``swarm.build_brief`` so there is exactly one source of truth for role labels
and protocol state.

API:
    GET  /                    dashboard page (embedded HTML/CSS/JS)
    GET  /api/status          combined JSON: agents + inbox + feedback + brief
    GET  /api/swarm           swarm JSON: live helpers + recent feedback + brief
    GET  /api/logs/<agent>    tail of one agent's run log
    POST /api/tasks           queue a task: {"agent": "sarah", "prompt": "..."}
    GET  /healthz             {"ok": true}

Usage:
    python scripts/web_app.py [--workspace DIR] [--host 127.0.0.1] [--port 8787]
    python scripts/web_app.py --smoke     # headless build check, print SMOKE-OK
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The script's own directory is added so ``import swarm`` works both when run
# as ``python scripts/web_app.py`` and when imported from the test suite.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import swarm  # reuse SLOTS / AGENT_TO_SLOT / read_swarm_state / load_feedback / build_brief

PROJECT_ROOT = Path(os.getcwd())

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")

# Status tokens for the dashboard (mirror the terminal's four colors: white,
# orange, grey, neon-green on black).
STATUS_LABEL = {
    "idle": "● IDLE",
    "working": "● WORKING",
    "helper": "● HELPER",
    "error": "✕ ERROR",
}
STATUS_COLOR = {
    "idle": "grey",
    "working": "orange",
    "helper": "neon",
    "error": "orange",
}


def now_iso() -> str:
    """UTC ISO-8601 timestamp with second precision (delegates to swarm)."""
    return swarm.now_iso()


def sanitize_prompt(prompt: str) -> str:
    """Strip control characters and surrounding whitespace from a raw prompt.

    Mirrors the worker's ConvertTo-SafeTask philosophy: a task file must never
    carry control characters that could confuse a Windows shell downstream.
    """
    return _CONTROL_CHARS_RE.sub("", str(prompt or "")).strip()


def tail_log(path: Path, n: int = 12) -> list[str]:
    """Return the last ``n`` lines of a log file (missing file -> [])."""
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]


def collect_agents(workspace: Path) -> list[dict]:
    """One entry per slot: role metadata + live swarm state + log tail."""
    logs = workspace / "_logs"
    state = swarm.read_swarm_state(logs / "swarm")
    agents = []
    for slot in sorted(swarm.SLOTS):
        agent, label = swarm.SLOTS[slot]
        st = state.get(slot, {})
        status = st.get("status", "idle")
        agents.append(
            {
                "slot": slot,
                "agent": agent,
                "label": label,
                "status": status,
                "title": st.get("title", swarm.title(slot, label)),
                "target": st.get("target"),
                "updated": st.get("updated"),
                "has_log": (logs / f"{agent}.log").is_file(),
                "log_tail": tail_log(logs / f"{agent}.log"),
            }
        )
    return agents


def collect_inbox(workspace: Path) -> dict:
    """Pending/claimed/done task counts + the pending queue (age in seconds)."""
    inbox = workspace / "_inbox"

    def _count(sub: str) -> int:
        d = inbox / sub
        if not d.is_dir():
            return 0
        try:
            return sum(1 for p in d.iterdir() if p.suffix == ".task")
        except OSError:
            return 0

    pending = []
    if inbox.is_dir():
        for p in sorted(inbox.glob("*.task")):
            if p.stem not in swarm.AGENT_TO_SLOT:
                continue  # ignore foreign files
            try:
                age = round(time.time() - p.stat().st_mtime, 1)
            except OSError:
                age = 0.0
            pending.append({"agent": p.stem, "path": str(p), "age": age})
    return {"pending": pending, "done": _count("done"), "claimed": _count("claimed")}


def collect_feedback(workspace: Path, n: int = 10) -> list[dict]:
    """Last ``n`` swarm feedback records (uses swarm.load_feedback)."""
    return swarm.load_feedback(workspace / "_logs" / "swarm_feedback.jsonl", n=n)


def collect_status(workspace: Path) -> dict:
    """Combined dashboard payload: agents + inbox + feedback + brief."""
    logs = workspace / "_logs"
    feedback_path = logs / "swarm_feedback.jsonl"
    brief = (
        swarm.build_brief(feedback_path, logs / "swarm", n=6)
        if feedback_path.exists()
        else "No swarm activity recorded yet."
    )
    return {
        "workspace": str(workspace),
        "updated": now_iso(),
        "agents": collect_agents(workspace),
        "inbox": collect_inbox(workspace),
        "feedback": collect_feedback(workspace),
        "brief": brief,
    }


def collect_swarm(workspace: Path) -> dict:
    """Swarm-only payload: live helpers, recent feedback, and the brief."""
    logs = workspace / "_logs"
    swarm_dir = logs / "swarm"
    feedback_path = logs / "swarm_feedback.jsonl"
    state = swarm.read_swarm_state(swarm_dir)
    helpers = [
        {"slot": slot, "agent": str(data.get("agent") or ""), "target": data.get("target")}
        for slot, data in sorted(state.items())
        if data.get("status") == "helper"
    ]
    return {
        "workspace": str(workspace),
        "updated": now_iso(),
        "helpers": helpers,
        "feedback": swarm.load_feedback(feedback_path, n=10),
        "brief": (
            swarm.build_brief(feedback_path, swarm_dir, n=6)
            if feedback_path.exists()
            else "No swarm activity recorded yet."
        ),
    }


def submit_task(workspace: Path, agent: str, prompt: str) -> tuple[bool, str, Path | None]:
    """Queue a task by writing ``_inbox/<agent>.task``.

    Returns ``(ok, message, path)``. Validates the agent name against the slot
    table (also blocks path traversal) and sanitizes the prompt text.
    """
    agent = str(agent or "").strip()
    prompt = sanitize_prompt(prompt)
    if agent not in swarm.AGENT_TO_SLOT:
        return False, f"unknown agent '{agent}'", None
    if not prompt:
        return False, "empty prompt", None
    inbox = workspace / "_inbox"
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"{agent}.task"
        path.write_text(prompt, encoding="utf-8")
    except OSError as exc:
        return False, f"write failed: {exc}", None
    return True, "queued", path


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


class WebDashboard(ThreadingHTTPServer):
    """Threaded HTTP server hosting the dashboard and JSON API."""

    daemon_threads = True
    allow_reuse_address = True


class WebHandler(BaseHTTPRequestHandler):
    """Request handler bound to a workspace via the ``app`` class attribute."""

    app = None  # set per-instance by create_web_app()
    server_version = "ZOVA-WEB/1.0"

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        pass

    def _send(self, code: int, body: str, ctype: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        elif path == "/healthz":
            self._json(200, {"ok": True})
        elif path == "/api/status":
            self._json(200, collect_status(self.app.workspace))
        elif path == "/api/swarm":
            self._json(200, collect_swarm(self.app.workspace))
        elif path.startswith("/api/logs/"):
            agent = path[len("/api/logs/") :]
            if agent not in swarm.AGENT_TO_SLOT:
                self._json(404, {"error": f"unknown agent '{agent}'"})
                return
            log_path = self.app.workspace / "_logs" / f"{agent}.log"
            self._json(200, {"agent": agent, "lines": tail_log(log_path, n=40)})
        else:
            self._json(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.rstrip("/") != "/api/tasks":
            self._json(404, {"error": "not found", "path": parsed.path})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid JSON body"})
            return
        agent = str(payload.get("agent", "")).strip()
        prompt = str(payload.get("prompt", ""))
        ok, message, path = submit_task(self.app.workspace, agent, prompt)
        self._json(
            201 if ok else 400,
            {"ok": ok, "message": message, "path": str(path) if path else None},
        )


def create_web_app(workspace: Path) -> WebDashboard:
    """Build a server whose handler resolves the given workspace."""
    handler = type("BoundWebHandler", (WebHandler,), {})
    handler.app = type("App", (), {"workspace": Path(workspace)})()
    return WebDashboard((DEFAULT_HOST, 0), handler)  # port picked on bind


# ---------------------------------------------------------------------------
# Smoke check + CLI
# ---------------------------------------------------------------------------


def smoke(workspace: Path) -> int:
    """Headless check: serve the dashboard on an ephemeral port and hit it."""
    server = create_web_app(workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=10) as resp:
            status = json.loads(resp.read().decode("utf-8"))
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        agents = status.get("agents", [])
        assert len(agents) == len(swarm.SLOTS), f"expected {len(swarm.SLOTS)} agents, got {len(agents)}"
        assert "ZOVA" in html and "api/status" in html
        print(f"SMOKE-OK: web dashboard served {len(agents)} agents on 127.0.0.1:{port}")
        return 0
    finally:
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZOVA WEB — control-plane dashboard")
    parser.add_argument("--workspace", default=None, help="control-plane root (default: cwd)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="headless build check: serve on an ephemeral port and exit",
    )
    args = parser.parse_args(argv)

    workspace = Path(args.workspace) if args.workspace else PROJECT_ROOT
    if args.smoke:
        return smoke(workspace)

    handler = type("BoundWebHandler", (WebHandler,), {})
    handler.app = type("App", (), {"workspace": workspace})()
    server = WebDashboard((args.host, args.port), handler)
    print(f"ZOVA WEB -> http://{args.host}:{args.port}/  (workspace {workspace})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[web_app] shutting down")
    finally:
        server.server_close()
    return 0


# ---------------------------------------------------------------------------
# Dashboard page (embedded — one self-contained file)
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZOVA WEB — Control Plane</title>
<style>
:root{
  --bg:#000; --white:#e8e8e8; --grey:#8a8a8a; --orange:#ff8c00; --neon:#39ff14;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--white);font-family:"Cascadia Mono","Consolas","Courier New",monospace;font-size:14px;line-height:1.55;padding:18px}
.banner{color:var(--neon);font-weight:bold;font-size:20px;letter-spacing:3px;border-bottom:2px solid var(--neon);padding-bottom:8px}
.meta{color:var(--grey);font-size:12px;padding:6px 0 14px}
.panel{border:1px solid var(--grey);padding:12px;margin-bottom:16px}
.panel h2{font-size:13px;letter-spacing:2px;margin-bottom:8px}
.orange{color:var(--orange)} .grey{color:var(--grey)} .neon{color:var(--neon)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-bottom:16px}
.card{border:1px solid var(--grey);padding:10px}
.card .tag{color:var(--orange);font-weight:bold}
.card .label{color:var(--white)}
.card .title{color:var(--grey);font-size:12px;margin:2px 0 6px}
.dot{display:inline-block;font-size:12px;letter-spacing:1px}
.dot.grey{color:var(--grey)} .dot.orange{color:var(--orange)} .dot.neon{color:var(--neon)}
pre.log{background:#0a0a0a;color:var(--grey);font-size:11px;padding:6px;max-height:140px;overflow:auto;white-space:pre-wrap}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:3px 6px;border-bottom:1px solid #222}
th{color:var(--orange)}
form{margin-top:12px}
form label{color:var(--grey);font-size:12px}
select,textarea,button{background:#0a0a0a;color:var(--white);border:1px solid var(--grey);font-family:inherit;font-size:13px;padding:6px}
textarea{width:100%;margin:6px 0;resize:vertical}
button{cursor:pointer;color:var(--neon);border-color:var(--neon);font-weight:bold;letter-spacing:1px}
button:hover{background:#0f2b0a}
#form-msg{color:var(--orange);font-size:12px;margin-left:8px}
.fb{font-size:12px;padding:4px 0;border-bottom:1px solid #1a1a1a}
.fb.ok{color:var(--neon)} .fb.fail{color:var(--orange)}
#brief{white-space:pre-wrap;color:var(--grey);font-size:12px;padding:6px;background:#0a0a0a;margin-bottom:10px}
</style>
</head>
<body>
<header>
  <div class="banner">&#9617;&#9620;&#9617;&#9620;&#9617; ZOVA // CONTROL PLANE WEB &#9617;&#9620;&#9617;&#9620;&#9617;</div>
  <div id="meta" class="meta">connecting…</div>
</header>
<main>
  <section id="agents" class="grid"></section>
  <div class="cols">
    <section class="panel">
      <h2 class="orange">INBOX</h2>
      <div id="inbox"></div>
      <form id="task-form">
        <label>agent:</label>
        <select id="agent-select"></select>
        <label> task prompt:</label>
        <textarea id="prompt" rows="3" placeholder="e.g. fix the login redirect bug"></textarea>
        <button type="submit">QUEUE TASK</button>
        <span id="form-msg"></span>
      </form>
    </section>
    <section class="panel">
      <h2 class="neon">SWARM BRIEF</h2>
      <pre id="brief"></pre>
      <h2 class="grey">RECENT FEEDBACK</h2>
      <div id="feedback"></div>
    </section>
  </div>
</main>
<script>
const SLOTS={1:'matthew',2:'alex',3:'sarah',4:'david',5:'elena',6:'max',7:'chloe'};
const SEL=document.getElementById('agent-select');
Object.entries(SLOTS).forEach(([slot,agent])=>{
  const o=document.createElement('option');o.value=agent;o.textContent='M'+slot+' '+agent;SEL.appendChild(o);
});
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function dot(status){
  const cls={idle:'grey',working:'orange',helper:'neon',error:'orange'}[status]||'grey';
  const label={idle:'● IDLE',working:'● WORKING',helper:'● HELPER',error:'✕ ERROR'}[status]||status;
  return '<span class="dot '+cls+'">'+label+'</span>';
}
function render(status){
  document.getElementById('meta').textContent='workspace: '+status.workspace+'  ·  updated: '+status.updated+'  ·  inbox: '+status.inbox.pending.length+' pending / '+status.inbox.done+' done / '+status.inbox.claimed+' claimed';
  const grid=document.getElementById('agents');
  grid.innerHTML=status.agents.map(a=>{
    let title=a.title||('M'+a.slot+' - '+a.label);
    if(a.status==='helper'&&a.target){title='M'+a.slot+'-Helper->M'+a.target;}
    return '<div class="card"><div><span class="tag">M'+a.slot+'</span> <span class="label">'+esc(a.label)+'</span> '+
      '<span class="grey">('+esc(a.agent)+')</span></div>'+
      '<div class="title">'+esc(title)+'</div>'+dot(a.status)+
      '<pre class="log">'+esc((a.log_tail||[]).slice(-8).join('\\n')||'— no log lines —')+'</pre></div>';
  }).join('');
  const inbox=document.getElementById('inbox');
  if(status.inbox.pending.length===0){
    inbox.innerHTML='<div class="grey">no pending tasks</div>';
  }else{
    inbox.innerHTML='<table><tr><th>agent</th><th>queued (s)</th></tr>'+
      status.inbox.pending.map(p=>'<tr><td>'+esc(p.agent)+'</td><td>'+p.age+'</td></tr>').join('')+'</table>';
  }
  document.getElementById('brief').textContent=status.brief||'—';
  const fb=document.getElementById('feedback');
  if(!status.feedback.length){fb.innerHTML='<div class="grey">— no records yet —</div>';return;}
  fb.innerHTML=status.feedback.map(r=>{
    const who=r.agent||('M'+r.slot);
    const mode=r.mode==='helper'?(r.target?'helper->M'+r.target:'helper'):'own';
    const ok=r.ok?'ok':'FAILED';
    return '<div class="fb '+(r.ok?'ok':'fail')+'">'+esc(who)+' · '+mode+' · ['+ok+'] '+(r.duration??'')+'s · '+esc((r.task||'').slice(0,60))+'</div>';
  }).join('');
}
async function refresh(){
  try{
    const r=await fetch('/api/status');
    render(await r.json());
  }catch(e){
    document.getElementById('meta').textContent='connection lost: '+e;
  }
}
document.getElementById('task-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const msg=document.getElementById('form-msg');
  const prompt=document.getElementById('prompt').value;
  try{
    const r=await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({agent:SEL.value,prompt})});
    const j=await r.json();
    msg.textContent=r.ok?('✓ '+j.message):('✕ '+j.message);
    if(r.ok){document.getElementById('prompt').value='';refresh();}
  }catch(err){msg.textContent='✕ '+err;}
});
refresh();
setInterval(refresh,2500);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())