"""Command parser — slash command splitting and help text builder."""

from __future__ import annotations


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
        "  /status          print current status line\n"
        "  /clear           clear the console\n"
        "  /stop            terminate all running agents\n"
        "  Esc (×2)         Master tab: abort all agents; agent tab: abort only\n"
        "                   the focused agent (other agents keep running)\n"
        "  Ctrl+G           same as Esc — abort active runs (reliable fallback)\n"
        "  Ctrl+C           when buffer is empty: abort all if running, else quit\n"
        "  /theme [name]    show current theme or switch: classic, opencode\n"
        "  /quit | /exit    leave the terminal\n"
        "\n"
        "Tabs: F1..F7 select an agent (M1..M7), F8 selects MASTER (all agents),\n"
        "Ctrl+T cycles. A task typed on an agent tab dispatches to that agent\n"
        "only; on MASTER it goes to all agents.\n"
        "Console: PgUp/PgDn scroll logs, Home/End jump to top/bottom,\n"
        "mouse wheel scrolls 3 lines at a time.\n"
        "Anything else is dispatched to the agents:\n"
        "  opencode run --agent <a> --auto [-m <model>] \"<prompt>\"\n"
    )
