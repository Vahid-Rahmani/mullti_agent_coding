"""Command parser — slash command splitting and help/overrides text builders."""

from __future__ import annotations

from pathlib import Path

from .agents import PROJECT_ROOT


def parse_command(text: str) -> tuple[str, str] | None:
    """Split a slash command into (name, arg); None for non-commands."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped[1:].split(None, 1)
    name = (parts[0] if parts else "").lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return (name, arg)


def build_help_text() -> str:
    """Text for the '/help' command."""
    return (
        "ZOVA commands:\n"
        "  /tab [tag]       switch tab: master, m1..m7, 'next', 'prev'\n"
        "  /help            show this help\n"
        "  /cd <path>       change the agents' working directory\n"
        "  /model [t] [n]   show/set a tab's model override\n"
        "                   (t = active tab, m1..m7, master, all; '' -> auto)\n"
        "  /mode [t] [n]    show/set a tab's mode override (same target syntax)\n"
        "  /prompt [t] [x]  set/clear a specialized system prompt (off by default)\n"
        "  /prompts         list all specialized prompts and their status\n"
        "  /overrides       table of per-tab model/mode overrides\n"
        "  /agents [tags]   dispatch only to m2,m3 (comma list) or 'all'\n"
        "  /status          print current status line\n"
        "  /clear           clear the console\n"
        "  /stop            terminate all running agents\n"
        "  Esc (×2)         Master tab: abort all agents; agent tab: abort only\n"
        "                   the focused agent (other agents keep running)\n"
        "  Ctrl+G           same as Esc — abort active runs (reliable fallback)\n"
        "  Ctrl+C           when buffer is empty: abort all if running, else quit\n"
        "  /swarm           print live swarm helper state\n"
        "  /settings [info] open the settings modal (Ctrl+Shift+S; Ctrl+S fallback);\n"
        "                   'info' prints the current settings as text\n"
        "  Theme customizer: ↑/↓ navigate, Enter cycles a color, U undoes the last\n"
        "                   change, RESET TO DEFAULTS clears every custom color\n"
        "  /proposals       list detected optimization-loop proposals\n"
        "  /agents-log [t]  show recent run entries for an agent\n"
        "  /audit           run Chloe (M7) vault audit manually\n"
        "  /archive [text]  run the Architectural Obsidian Archivist (M7): filter,\n"
        "                   resolve project dir, refresh Mermaid map, lean Evolution\n"
        "  /evolve <prompt> run a self-evolve cycle (checkpoint + dispatch + verify)\n"
        "  /theme [name]    show current theme or switch: classic, opencode\n"
        "  /quit | /exit    leave the terminal\n"
        "\n"
        "Tabs: F1..F7 select an agent (M1..M7), F8 selects MASTER (all agents),"
        "Ctrl+T cycles. A task typed on an agent tab dispatches to that agent\n"
        "only; on MASTER it goes to all agents (or the /agents filter).\n"
        "Console: PgUp/PgDn scroll logs, Home/End jump to top/bottom,\n"
        "mouse wheel scrolls 3 lines at a time.\n"
        "Anything else is dispatched to the agent swarm:\n"
        "  opencode run --agent <a> --auto [-m <model>] \"<prompt>\"\n"
    )


def _swarm_state() -> str:
    """Live swarm helper state for the '/swarm' command (empty when absent)."""
    swarm_dir = PROJECT_ROOT / "_logs" / "swarm"
    if not swarm_dir.is_dir():
        return "no swarm state (_logs/swarm missing) — run launch_agents.bat first"
    try:
        from swarm import read_swarm_state

        state = read_swarm_state(swarm_dir)
    except Exception as exc:  # noqa: BLE001
        return f"swarm state unreadable: {exc}"
    if not state:
        return "swarm state is empty"
    rows = []
    for slot, data in sorted(state.items()):
        status = data.get("status", "?")
        target = data.get("target")
        title = data.get("title", "")
        rows.append(f"M{slot}: {status}" + (f" -> M{target}" if target else "") + (f" ({title})" if title else ""))
    return " | ".join(rows)
