"""Command-line access to the agent roster and runtime model resolution.

Used by the 7-window launcher (``run_agent_worker.ps1`` / ``.sh`` /
``launch_agents.bat``) to resolve each agent's roster and runtime model from
``opencode.json`` (the single source of truth). The AgentSpec modules carry
identity only and are never parsed for a model.

Usage:
    python -m scripts.core.agents list                 # agent keys, one per line
    python -m scripts.core.agents roster               # slot table: tag agent name model
    python -m scripts.core.agents model <tag-or-key>   # runtime model from opencode.json
    python -m scripts.core.agents verify               # drift-check specs vs opencode.json

``<tag-or-key>`` accepts either a tag (``m1``) or an agent key (``matthew``).
Exits 2 with an error on stderr for unknown agents or commands; ``verify``
exits 1 when the runtime config violates an invariant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repo root importable so this works both as
# ``python -m scripts.core.agents`` (cwd on sys.path) and when executed
# directly as a script from any working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.core import opencode_cfg
from scripts.core.agents import (
    AGENT_SPEC_BY_AGENT,
    AGENT_SPEC_BY_TAG,
    AGENT_SPECS,
    AGENTS,
)


def _resolve(name: str):
    """Return the AgentSpec for a tag (``m1``) or agent key (``matthew``)."""
    if name in AGENT_SPEC_BY_TAG:
        return AGENT_SPEC_BY_TAG[name]
    if name in AGENT_SPEC_BY_AGENT:
        return AGENT_SPEC_BY_AGENT[name]
    return None


def _cmd_list() -> int:
    for _tag, _name, agent in AGENTS:
        if agent:
            print(agent)
    return 0


def _cmd_roster() -> int:
    """Print one slot-aligned line per agent: tag agent name model.

    ``launch_agents.bat`` parses this with ``for /f "tokens=1-4"`` to build
    the 7-window launcher arrays instead of hardcoding the roster.
    """
    for spec in AGENT_SPECS:
        model = opencode_cfg.resolve_model(spec.agent) or ""
        print(f"{spec.tag} {spec.agent} {spec.name} {model}")
    return 0


def _cmd_model(name: str) -> int:
    spec = _resolve(name)
    if spec is None:
        valid = ", ".join(sorted(AGENT_SPEC_BY_AGENT))
        print(f"error: unknown agent '{name}' (valid: {valid})", file=sys.stderr)
        return 2
    print(opencode_cfg.resolve_model(spec.agent) or "")
    return 0


def _cmd_verify() -> int:
    """Drift-check the specs against opencode.json (the OpenCode runtime config).

    Beyond model sync, this guards the two invariants that break plain
    dispatch if violated:
      * every roster agent must be primary-capable (``mode: subagent`` makes
        ``opencode run --agent <a>`` silently fall back to the default agent);
      * no ``fallback_models`` chain may contain the agent's own primary model
        (a wasted retry of a just-failed model — with ``cooldown_seconds: 0``
        nothing stays in cooldown, so it is retried immediately).
    """
    cfg_path = _REPO_ROOT / "opencode.json"
    if not cfg_path.exists():
        print(f"error: {cfg_path} not found; nothing to verify against", file=sys.stderr)
        return 2
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot parse {cfg_path}: {exc}", file=sys.stderr)
        return 2
    runtime = config.get("agent", {})
    issues: list[str] = []
    for spec in AGENT_SPECS:
        entry = runtime.get(spec.agent)
        if entry is None:
            issues.append(f"{spec.agent}: missing from opencode.json agent config")
            continue
        if entry.get("mode") == "subagent":
            issues.append(
                f"{spec.agent}: mode 'subagent' is not primary-capable — "
                "'opencode run --agent' would silently fall back to the default agent; "
                "use 'all' or 'primary'"
            )
        primary = entry.get("model") or config.get("model")
        chain = entry.get("fallback_models") or []
        if primary and primary in chain:
            issues.append(
                f"{spec.agent}: fallback_models contains its own primary model "
                f"{primary!r} — retries a just-failed model"
            )
    # Flag opencode agents that are not part of the roster. "compaction" is an
    # internal OpenCode agent (context compaction) and is intentionally exempt.
    for key in runtime:
        if key != "compaction" and key not in AGENT_SPEC_BY_AGENT:
            issues.append(f"{key}: in opencode.json but not in scripts/core/agents specs")
    if issues:
        for issue in issues:
            print(f"DRIFT: {issue}")
        return 1
    print(f"OK: {len(AGENT_SPECS)} agent specs in sync with opencode.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd = argv[0]
    if cmd == "list":
        return _cmd_list()
    if cmd == "roster":
        return _cmd_roster()
    if cmd == "verify":
        return _cmd_verify()
    if cmd == "model":
        if len(argv) < 2:
            print("error: model requires an agent tag or key", file=sys.stderr)
            return 2
        return _cmd_model(argv[1])
    print(f"error: unknown command '{cmd}' (try: list, roster, model, verify)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
