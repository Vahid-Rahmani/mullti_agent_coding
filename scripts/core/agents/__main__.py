"""Command-line access to the canonical agent specs.

Used by the 7-window launcher workers (``run_agent_worker.ps1`` / ``.sh``) to
resolve each agent's configured model from the specs instead of parsing
``opencode.json``, keeping the specs the single source of truth.

Usage:
    python -m scripts.core.agents list                 # agent keys, one per line
    python -m scripts.core.agents model <tag-or-key>   # configured default model
    python -m scripts.core.agents models <tag-or-key>  # models that can run it

``<tag-or-key>`` accepts either a tag (``m1``) or an agent key (``matthew``).
Exits 2 with an error on stderr for unknown agents or commands.
"""

from __future__ import annotations

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
        for _tag, _name, agent in AGENTS:
            if agent:
                print(agent)
        return 0
    if cmd in ("model", "models"):
        if len(argv) < 2:
            print(f"error: {cmd} requires an agent tag or key", file=sys.stderr)
            return 2
        spec = _resolve(argv[1])
        if spec is None:
            valid = ", ".join(sorted(AGENT_SPEC_BY_AGENT))
            print(f"error: unknown agent '{argv[1]}' (valid: {valid})", file=sys.stderr)
            return 2
        if cmd == "model":
            print(spec.model or "")
        else:
            print(" ".join(MODELS_BY_AGENT.get(spec.agent, ())))
        return 0
    print(f"error: unknown command '{cmd}' (try: list, model, models)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
