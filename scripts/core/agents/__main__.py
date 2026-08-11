"""Command-line access to the canonical agent specs.

Used by the 7-window launcher (``run_agent_worker.ps1`` / ``.sh`` /
``launch_agents.bat``) to resolve each agent's configured model and roster from
the specs instead of parsing ``opencode.json``, keeping the specs the single
source of truth.

Usage:
    python -m scripts.core.agents list                 # agent keys, one per line
    python -m scripts.core.agents roster               # slot table: tag agent name role model
    python -m scripts.core.agents model <tag-or-key>   # configured default model
    python -m scripts.core.agents models <tag-or-key>  # models that can run it
    python -m scripts.core.agents verify               # drift-check specs vs opencode.json

``<tag-or-key>`` accepts either a tag (``m1``) or an agent key (``matthew``).
Exits 2 with an error on stderr for unknown agents or commands; ``verify``
exits 1 when specs and ``opencode.json`` disagree.
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

from scripts.core.agents import (  # noqa: E402
    AGENT_SPEC_BY_AGENT,
    AGENT_SPEC_BY_TAG,
    AGENT_SPECS,
    AGENTS,
    MODELS_BY_AGENT,
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
    """Print one slot-aligned line per specialist: tag agent name role model.

    ``launch_agents.bat`` parses this with ``for /f "tokens=1-5"`` to build
    the 7-window launcher arrays instead of hardcoding the roster.
    """
    for spec in AGENT_SPECS:
        print(f"{spec.tag} {spec.agent} {spec.name} {spec.role} {spec.model or ''}")
    return 0


def _cmd_model(name: str) -> int:
    spec = _resolve(name)
    if spec is None:
        valid = ", ".join(sorted(AGENT_SPEC_BY_AGENT))
        print(f"error: unknown agent '{name}' (valid: {valid})", file=sys.stderr)
        return 2
    print(spec.model or "")
    return 0


def _cmd_models(name: str) -> int:
    spec = _resolve(name)
    if spec is None:
        valid = ", ".join(sorted(AGENT_SPEC_BY_AGENT))
        print(f"error: unknown agent '{name}' (valid: {valid})", file=sys.stderr)
        return 2
    print(" ".join(MODELS_BY_AGENT.get(spec.agent, ())))
    return 0


def _cmd_verify() -> int:
    """Drift-check the specs against opencode.json (the OpenCode runtime config)."""
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
        elif entry.get("model") != spec.model:
            issues.append(
                f"{spec.agent}: spec model {spec.model!r} != opencode.json {entry.get('model')!r}"
            )
    # Flag opencode agents that are not part of the roster. "compaction" is an
    # internal OpenCode agent (context compaction) routed to Chloe in MODE_TO_AGENT,
    # so it is intentionally exempt.
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
    if cmd in ("model", "models"):
        if len(argv) < 2:
            print(f"error: {cmd} requires an agent tag or key", file=sys.stderr)
            return 2
        return _cmd_model(argv[1]) if cmd == "model" else _cmd_models(argv[1])
    print(f"error: unknown command '{cmd}' (try: list, roster, model, models, verify)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
