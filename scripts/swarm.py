"""Swarm orchestration core for the 7-window ``opencode run`` launcher.

Implements the Dynamic Swarm Role-Swapping & Peer-Assistance protocol:

1. **Role rotation on completion** — when a worker finishes its own task it
   becomes a "Swarm Helper" and takes over stale (unclaimed) tasks from lagging
   peers instead of idling.
2. **Dynamic tab renaming** — the cooperative role and its assistance target are
   encoded in a real-time window title (``M3-Helper->M1``) and persisted in a
   per-slot state file so any UI can reflect it.
3. **Inter-agent learning & swarm feedback loop** — every run (own or assisted)
   appends a JSONL feedback record; workers inject a short "swarm brief" built
   from recent records + live swarm state into the next task prompt so agents
   share context across execution cycles.

Pure stdlib (no third-party deps) so the PowerShell worker can shell out to it
and the unittest suite can import the functions directly.

Usage (called from run_agent_worker.ps1):

    python scripts/swarm.py title    --slot 4 --label "David" --mode helper --target 1
    python scripts/swarm.py find-stale --inbox _inbox --own david --stale 30
    python scripts/swarm.py claim    --inbox _inbox --agent sarah --by 4
    python scripts/swarm.py feedback --file _logs/swarm_feedback.jsonl --slot 4 \
        --agent david --mode helper --target 1 --ok true --duration 12 --task "..."
    python scripts/swarm.py brief    --file _logs/swarm_feedback.jsonl --swarm _logs/swarm
    python scripts/swarm.py state    --swarm _logs/swarm --slot 4 --json '{"status":"helper"}'
    python scripts/swarm.py swarm    --swarm _logs/swarm
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Canonical slot table: slot -> (agent name, human label).
SLOTS: dict[int, tuple[str, str]] = {
    1: ("matthew", "Matthew"),
    2: ("alex", "Alex"),
    3: ("sarah", "Sarah"),
    4: ("david", "David"),
    5: ("elena", "Elena"),
    6: ("max", "Max"),
    7: ("chloe", "Chloe"),
}
AGENT_TO_SLOT: dict[str, int] = {name: slot for slot, (name, _) in SLOTS.items()}


def now_iso() -> str:
    """UTC ISO-8601 timestamp with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def title(slot: int, label: str, mode: str = "idle", target: int | None = None) -> str:
    """Build the dynamic tab/window title for a worker.

    Modes:
      idle    -> ``M3 - Sarah``
      working -> ``M3 - Sarah [working]``
      helper  -> ``M3-Helper->M1``            (target required)
    """
    base = f"M{slot} - {label}"
    if mode == "working":
        return f"{base} [working]"
    if mode == "helper":
        if target is None:
            raise ValueError("helper mode requires a target slot")
        return f"M{slot}-Helper->M{target}"
    return base


def iter_task_files(inbox_dir: Path) -> list[Path]:
    """Return ``*.task`` files directly inside the inbox (not subdirs)."""
    if not inbox_dir.is_dir():
        return []
    return sorted(p for p in inbox_dir.iterdir() if p.suffix == ".task" and p.is_file())


def find_stale_tasks(
    inbox_dir: Path, own_agent: str, stale_seconds: int, now: float | None = None
) -> list[dict]:
    """List lagging peers: task files not claimed within ``stale_seconds``.

    A task file that still sits in the inbox after ``stale_seconds`` means its
    owner has not picked it up (busy, crashed, or never launched) — it is a
    candidate for role rotation / peer assistance. The helper's own agent is
    always excluded.
    """
    now = now if now is not None else time.time()
    stale = []
    for task in iter_task_files(inbox_dir):
        agent = task.stem  # file name is "<agent>.task"
        if agent == own_agent or agent not in AGENT_TO_SLOT:
            continue
        age = now - task.stat().st_mtime
        if age >= stale_seconds:
            stale.append(
                {
                    "agent": agent,
                    "slot": AGENT_TO_SLOT[agent],
                    "path": str(task),
                    "age": round(age, 1),
                }
            )
    # Oldest first — the most-lagging peer gets helped first.
    stale.sort(key=lambda item: item["age"], reverse=True)
    return stale


def claim_task(
    inbox_dir: Path,
    peer_agent: str,
    claimer_slot: int,
    claimed_dir: Path | None = None,
) -> Path | None:
    """Atomically claim a peer's task file by renaming it into ``claimed/``.

    Rename on the same volume is atomic on Windows: exactly one worker wins the
    race, the others see the source disappear and back off. Returns the claimed
    path, or ``None`` when the file was already gone.
    """
    if claimed_dir is None:
        claimed_dir = inbox_dir / "claimed"
    claimed_dir.mkdir(parents=True, exist_ok=True)
    src = inbox_dir / f"{peer_agent}.task"
    if not src.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = claimed_dir / f"{peer_agent}-claimed-by-m{claimer_slot}-{stamp}.task"
    try:
        os.rename(str(src), str(dst))
    except OSError:
        return None  # lost the race; someone else claimed it
    return dst


def _str2bool(value: str) -> bool:
    """Parse 'true'/'false'/'1'/'0' (PowerShell-friendly) into a bool."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def append_feedback(feedback_path: Path, **fields) -> dict:
    """Append one JSONL feedback record and return the stored dict."""
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), **fields}
    with feedback_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_feedback(feedback_path: Path, n: int = 10) -> list[dict]:
    """Return the last ``n`` feedback records (oldest->newest order)."""
    if not feedback_path.exists():
        return []
    lines = [ln for ln in feedback_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    records = []
    for ln in lines[-n:]:
        try:
            records.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return records


def write_slot_state(swarm_dir: Path, slot: int, **fields) -> Path:
    """Persist one slot's live role/title state as ``m{slot}.json``.

    Writes to a temp file then renames so readers never observe a partial write.
    """
    swarm_dir.mkdir(parents=True, exist_ok=True)
    path = swarm_dir / f"m{slot}.json"
    payload = {"slot": slot, "updated": now_iso(), **fields}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return path


def read_swarm_state(swarm_dir: Path) -> dict:
    """Merge all per-slot state files into ``{slot: {...}}``."""
    if not swarm_dir.is_dir():
        return {}
    state: dict[int, dict] = {}
    for f in sorted(swarm_dir.glob("m*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if "slot" in data:
            state[int(data["slot"])] = data
    return state


def build_brief(
    feedback_path: Path,
    swarm_dir: Path | None = None,
    n: int = 6,
    own_agent: str | None = None,
) -> str:
    """Build a short inter-agent learning brief for injection into a prompt.

    Summarises recent feedback records (who ran what, ok/failed, duration) plus
    the live swarm state (which slots are helpers, what they target). Rendered
    as plain text the worker prepends to the task before calling opencode run.
    """
    lines: list[str] = []
    records = load_feedback(feedback_path, n=n)
    if records:
        lines.append("Recent swarm activity (feedback loop):")
        for r in records:
            who = r.get("agent") or f"M{r.get('slot', '?')}"
            mode = r.get("mode", "own")
            if mode == "helper":
                target = r.get("target")
                who = f"{who} (helper->M{target})" if target is not None else f"{who} (helper)"
            ok = "ok" if r.get("ok") else "FAILED"
            dur = r.get("duration")
            task = (r.get("task") or "")[:48]
            tail = f" [{ok}] {dur}s {task}".rstrip()
            lines.append(f"- {who}{tail}")
    state = read_swarm_state(swarm_dir) if swarm_dir else {}
    helpers = [
        f"M{slot}->M{data.get('target')}"
        for slot, data in sorted(state.items())
        if data.get("status") == "helper" and data.get("target") is not None
    ]
    if helpers:
        lines.append("Live helpers: " + ", ".join(helpers))
    if own_agent and not lines:
        lines.append("No prior swarm activity recorded yet.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _cmd_title(args: argparse.Namespace) -> int:
    print(title(args.slot, args.label, args.mode, args.target))
    return 0


def _cmd_find_stale(args: argparse.Namespace) -> int:
    stale = find_stale_tasks(Path(args.inbox), args.own, args.stale)
    print(json.dumps(stale))
    return 0


def _cmd_claim(args: argparse.Namespace) -> int:
    claimed = claim_task(Path(args.inbox), args.agent, args.by)
    print(str(claimed) if claimed else "NONE")
    return 0


def _cmd_feedback(args: argparse.Namespace) -> int:
    if args.json_b64:
        record = json.loads(base64.b64decode(args.json_b64).decode("utf-8"))
        record = append_feedback(Path(args.file), **record)
        print(json.dumps(record))
        return 0
    fields = {
        "slot": args.slot,
        "agent": args.agent,
        "mode": args.mode,
        "ok": _str2bool(args.ok),
        "duration": args.duration,
        "task": args.task,
    }
    if args.target:
        fields["target"] = args.target
    record = append_feedback(Path(args.file), **fields)
    print(json.dumps(record))
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    print(build_brief(Path(args.file), Path(args.swarm) if args.swarm else None, args.n, args.own))
    return 0


def _cmd_state(args: argparse.Namespace) -> int:
    payload = args.json
    if args.json_b64:
        payload = base64.b64decode(args.json_b64).decode("utf-8")
    if payload and args.slot:
        fields = json.loads(payload)
        path = write_slot_state(Path(args.swarm), args.slot, **fields)
        print(str(path))
    else:
        print(json.dumps(read_swarm_state(Path(args.swarm))))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Swarm orchestration core (see module docstring).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_title = sub.add_parser("title", help="Build a dynamic tab title.")
    p_title.add_argument("--slot", type=int, required=True)
    p_title.add_argument("--label", required=True)
    p_title.add_argument("--mode", default="idle", choices=["idle", "working", "helper"])
    p_title.add_argument("--target", type=int, default=None)
    p_title.set_defaults(func=_cmd_title)

    p_stale = sub.add_parser("find-stale", help="List stale unclaimed peer tasks.")
    p_stale.add_argument("--inbox", required=True)
    p_stale.add_argument("--own", required=True)
    p_stale.add_argument("--stale", type=int, default=30)
    p_stale.set_defaults(func=_cmd_find_stale)

    p_claim = sub.add_parser("claim", help="Atomically claim a peer task file.")
    p_claim.add_argument("--inbox", required=True)
    p_claim.add_argument("--agent", required=True)
    p_claim.add_argument("--by", type=int, required=True)
    p_claim.set_defaults(func=_cmd_claim)

    p_fb = sub.add_parser("feedback", help="Append a swarm feedback record.")
    p_fb.add_argument("--file", required=True)
    p_fb.add_argument("--slot", type=int, default=None)
    p_fb.add_argument("--agent", default="")
    p_fb.add_argument("--mode", default="own", choices=["own", "helper"])
    p_fb.add_argument("--target", type=int, default=None)
    p_fb.add_argument("--ok", type=str, default="true", help="true/false (PowerShell-friendly string)")
    p_fb.add_argument("--duration", type=float, default=0.0)
    p_fb.add_argument("--task", default="")
    p_fb.add_argument("--json-b64", default=None, help="base64-encoded full record (PowerShell-safe quoting)")
    p_fb.set_defaults(func=_cmd_feedback)

    p_brief = sub.add_parser("brief", help="Build an inter-agent learning brief.")
    p_brief.add_argument("--file", required=True)
    p_brief.add_argument("--swarm", default=None)
    p_brief.add_argument("--n", type=int, default=6)
    p_brief.add_argument("--own", default=None)
    p_brief.set_defaults(func=_cmd_brief)

    p_state = sub.add_parser("state", help="Read/write per-slot swarm state.")
    p_state.add_argument("--swarm", required=True)
    p_state.add_argument("--slot", type=int, default=None)
    p_state.add_argument("--json", default=None)
    p_state.add_argument("--json-b64", default=None, help="base64-encoded --json (PowerShell-safe quoting)")
    p_state.set_defaults(func=_cmd_state)

    p_swarm = sub.add_parser("swarm", help="Dump merged swarm state.")
    p_swarm.add_argument("--swarm", required=True)
    p_swarm.set_defaults(func=lambda a: (print(json.dumps(read_swarm_state(Path(a.swarm)))), 0)[1])

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
