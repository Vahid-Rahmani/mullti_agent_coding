#!/usr/bin/env python3
"""
MultiAgentCoding — web app supervisor (self-restart).

Watches the ``scripts/web_app.py`` child process and relaunches it when a
restart marker appears at ``_logs/restart.ctl``:

  * spawn ``python scripts/web_app.py --port <p> --no-browser`` as a child,
  * poll every second until the child exits,
  * no marker -> exit cleanly (nothing to do),
  * marker present -> run ``SelfEvolveEngine.verify()``:
      - verify passes -> clear the marker and relaunch the child,
      - verify fails -> record a rollback decision in ``state.md`` and do NOT
        relaunch (a broken build must never come back up).

``--once`` performs a single restart cycle then exits; ``--watch`` keeps
supervising across restarts (still exits cleanly when a child exits with no
marker). The child command, working directory, and marker path are injectable
for tests.

Usage:
    python scripts/supervisor.py [--port 8501] [--once|--watch]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from functools import partial
from pathlib import Path

from self_evolve import RESTART_MARKER_NAME, SelfEvolveEngine

DEFAULT_PORT = 8501
POLL_INTERVAL = 1.0


def build_child_cmd(python: str, port: int) -> list[str]:
    """Default child argv: ``python scripts/web_app.py --port <p> --no-browser``."""
    return [python, "scripts/web_app.py", "--port", str(port), "--no-browser"]


def spawn_child(cmd: list[str], cwd: str | os.PathLike) -> subprocess.Popen:
    """Spawn the web_app child process (stdout/stderr inherited)."""
    return subprocess.Popen(cmd, cwd=str(cwd))


def wait_exit(child: subprocess.Popen, poll_interval: float) -> int:
    """Poll until the child exits; returns its return code."""
    while child.poll() is None:
        time.sleep(poll_interval)
    return child.returncode


def _clear_marker(marker_path: Path) -> None:
    try:
        marker_path.unlink()
    except FileNotFoundError:
        pass


def _rollback_text(marker: dict, result: dict) -> str:
    """Human-readable rollback decision recorded when verification fails."""
    prompt = marker.get("prompt", "")
    errors = "; ".join(result.get("errors") or []) or "verify failed"
    detail = f" (prompt={prompt!r})" if prompt else ""
    return f"rollback: self-evolve verify failed; not relaunching{detail}: {errors}"


def _decide_relaunch(engine: SelfEvolveEngine, marker_path: Path) -> bool:
    """Read the restart marker and decide whether to relaunch the child.

    No marker -> False (clean exit). Marker + verify ok -> clear the marker
    and return True (relaunch). Marker + verify fail -> record a rollback
    decision via ``engine.record_decision`` and return False (do NOT relaunch).
    """
    marker = engine.read_restart_marker(marker_path)
    if marker is None:
        return False
    result = engine.verify()
    if result["ok"]:
        _clear_marker(marker_path)
        return True
    if engine.record_decision is not None:
        engine.record_decision(_rollback_text(marker, result))
    return False


def append_state_decision(state_path: Path, text: str) -> None:
    """Append a ``- text`` bullet to the ``## Decisions`` section of state.md.

    Produces the same on-disk shape ``StateTracker.record_decision`` would, so
    web_app's loader picks the rollback decision up. Pure stdlib: the
    supervisor must not import web_app.
    """
    if state_path.exists():
        content = state_path.read_text(encoding="utf-8")
    else:
        content = "# State\n"
    lines = content.rstrip("\n").split("\n")
    header = None
    for i, line in enumerate(lines):
        if line.strip() == "## Decisions":
            header = i
            break
    if header is None:
        lines.append("")
        lines.append("## Decisions")
        lines.append(f"- {text}")
    else:
        end = header + 1
        for j in range(header + 1, len(lines)):
            if lines[j].strip().startswith("## "):
                end = j
                break
            if lines[j].strip():
                end = j + 1
        lines.insert(end, f"- {text}")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_supervisor(
    *,
    child_cmd: list[str],
    cwd: str | os.PathLike,
    marker_path: Path,
    engine: SelfEvolveEngine,
    poll_interval: float = POLL_INTERVAL,
    watch: bool = False,
    spawn=spawn_child,
    wait=wait_exit,
) -> int:
    """Run the supervision loop; returns the number of restarts performed.

    Starts ``child_cmd``, waits for it to exit, then reads the restart marker:
    no marker -> return; marker + verify ok -> clear marker and relaunch (return
    after the cycle unless ``watch``); marker + verify fail -> record rollback
    and return without relaunching.
    """
    restarts = 0
    while True:
        child = spawn(child_cmd, cwd)
        wait(child, poll_interval)
        if not _decide_relaunch(engine, marker_path):
            return restarts
        restarts += 1
        if not watch:
            return restarts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Supervisor for the MultiAgentCoding web app (self-restart)."
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"child web_app port (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="single restart cycle then exit (default)",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="keep supervising across restarts",
    )
    parser.add_argument(
        "--marker", default=None,
        help="restart marker path (default <cwd>/_logs/restart.ctl)",
    )
    parser.add_argument(
        "--cwd", default=str(Path.cwd()),
        help="project root; child working directory",
    )
    parser.add_argument(
        "--poll", type=float, default=POLL_INTERVAL,
        help=f"poll interval seconds (default {POLL_INTERVAL})",
    )
    parser.add_argument(
        "--child-cmd", default=None,
        help='child argv JSON override, e.g. ["python","x.py"]',
    )
    args = parser.parse_args(argv)

    cwd = Path(args.cwd).expanduser().resolve()
    marker_path = (
        Path(args.marker) if args.marker else cwd / "_logs" / RESTART_MARKER_NAME
    )
    child_cmd = (
        json.loads(args.child_cmd)
        if args.child_cmd
        else build_child_cmd(sys.executable, args.port)
    )
    engine = SelfEvolveEngine(
        project_root=cwd,
        record_decision=partial(append_state_decision, cwd / "state.md"),
    )
    return run_supervisor(
        child_cmd=child_cmd,
        cwd=cwd,
        marker_path=marker_path,
        engine=engine,
        poll_interval=args.poll,
        watch=args.watch,
    )


if __name__ == "__main__":
    sys.exit(main())