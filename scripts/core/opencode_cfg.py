"""opencode_cfg — safe read/write of ``opencode.json`` + atomic agent config.

Single writer for the runtime OpenCode configuration. The ``AgentSpec``
modules (``scripts/core/agents/``) remain the control-plane source of truth
for identity and the default model; ``opencode.json`` mirrors that model and
owns the runtime-only fields (``fallback_models``, ``mode``, ``description``)
plus ``provider`` blocks.

Model edits update **both** the spec module and ``opencode.json`` atomically
and re-run ``python -m scripts.core.agents verify``; any drift restores the
previous bytes of both files so the launcher, terminal, and dispatch never see
a half-applied change.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from scripts.core.agents import AGENT_SPEC_BY_AGENT, AGENT_SPEC_BY_TAG, PROJECT_ROOT

AGENT_MODES = ("primary", "subagent", "all")
MAX_FALLBACK_MODELS = 5

# provider/model — letters, digits, . _ - : / + @ (no whitespace or quotes,
# which keeps ids safe to embed in Python string literals and JSON).
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9_.\-:/+@]+/[A-Za-z0-9_.\-:/+@]+$")
_SPEC_MODEL_RE = re.compile(r'^(\s*model\s*=\s*)"[^"]*"(,?)$', re.MULTILINE)


class ConfigError(ValueError):
    """Raised for invalid settings writes (mapped to HTTP 409 by routes)."""


# ---------------------------------------------------------------- file I/O


def cfg_path(repo_root: Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    return root / "opencode.json"


def load_config(repo_root: Path | None = None) -> dict:
    """Load ``opencode.json`` (empty dict when missing/corrupt — never raises)."""
    path = cfg_path(repo_root)
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {}


def save_config(cfg: dict, repo_root: Path | None = None) -> None:
    cfg_path(repo_root).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- providers


def get_provider(cfg: dict, provider_id: str) -> dict | None:
    return (cfg.get("provider") or {}).get(provider_id)


def upsert_provider(cfg: dict, provider_id: str, block: dict) -> None:
    cfg.setdefault("provider", {})[provider_id] = block


def remove_provider(cfg: dict, provider_id: str) -> bool:
    providers = cfg.get("provider")
    if not providers or provider_id not in providers:
        return False
    del providers[provider_id]
    return True


# ---------------------------------------------------------------- validation


def validate_model_id(model: str) -> str:
    model = (model or "").strip()
    if not _MODEL_ID_RE.match(model):
        raise ConfigError(f"invalid model id {model!r} (expected provider/model)")
    return model


def validate_mode(mode: str) -> str:
    if mode not in AGENT_MODES:
        raise ConfigError(f"invalid mode {mode!r}; allowed: {', '.join(AGENT_MODES)}")
    return mode


def validate_fallback_chain(fallback_models: list[str] | None) -> list[str]:
    chain = [validate_model_id(m) for m in (fallback_models or [])]
    if len(chain) > MAX_FALLBACK_MODELS:
        raise ConfigError(f"fallback chain may contain at most {MAX_FALLBACK_MODELS} models")
    return chain


# ---------------------------------------------------------------- agent config


def _resolve_agent(name: str):
    """Resolve a tag (``m1``) or agent key (``matthew``) to its AgentSpec."""
    spec = AGENT_SPEC_BY_TAG.get(name) or AGENT_SPEC_BY_AGENT.get(name)
    if spec is None or spec.agent is None:
        raise ConfigError(f"unknown agent {name!r}")
    return spec


def _spec_path(repo_root: Path | None) -> Path:
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    return root / "scripts" / "core" / "agents"


def _write_spec_model(spec, model: str, repo_root: Path | None) -> None:
    """Rewrite only the ``model="..."`` line of an AgentSpec module."""
    path = _spec_path(repo_root) / f"{spec.agent}.py"
    text = path.read_text(encoding="utf-8")

    def _sub(m: re.Match) -> str:
        return f'{m.group(1)}"{model}"{m.group(2)}'

    new_text, n = _SPEC_MODEL_RE.subn(_sub, text, count=1)
    if n != 1:
        raise ConfigError(f"could not locate model= in {path.name}")
    path.write_text(new_text, encoding="utf-8")


def apply_agent_config(
    name: str,
    *,
    model: str | None = None,
    fallback_models: list[str] | None = None,
    mode: str | None = None,
    description: str | None = None,
    repo_root: Path | None = None,
    verify_cmd: list[str] | None = None,
) -> dict:
    """Atomically apply runtime agent config; rolls back on verify drift.

    ``model`` edits rewrite both the spec module and the ``opencode.json``
    agent entry; ``fallback_models`` / ``mode`` / ``description`` edit
    ``opencode.json`` only (they live nowhere else). Every write is followed
    by ``python -m scripts.core.agents verify``; on failure both files are
    restored and a :class:`ConfigError` is raised.
    """
    spec = _resolve_agent(name)
    cfg = load_config(repo_root)
    entry = dict((cfg.get("agent") or {}).get(spec.agent) or {})

    if model is not None:
        entry["model"] = validate_model_id(model)
    if fallback_models is not None:
        entry["fallback_models"] = validate_fallback_chain(fallback_models)
    if mode is not None:
        entry["mode"] = validate_mode(mode)
    if description is not None:
        entry["description"] = description

    cfg_path_ = cfg_path(repo_root)
    spec_file = _spec_path(repo_root) / f"{spec.agent}.py"
    before_cfg = cfg_path_.read_bytes() if cfg_path_.is_file() else None
    before_spec = spec_file.read_bytes() if spec_file.is_file() else None

    cfg.setdefault("agent", {})[spec.agent] = entry
    save_config(cfg, repo_root)
    if model is not None:
        _write_spec_model(spec, model, repo_root)

    cmd = verify_cmd if verify_cmd is not None else \
        [sys.executable, "-m", "scripts.core.agents", "verify"]
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=60)
        ok = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False

    if not ok:
        if before_cfg is not None:
            cfg_path_.write_bytes(before_cfg)
        if before_spec is not None:
            spec_file.write_bytes(before_spec)
        raise ConfigError(
            "agent config rejected by verify (specs vs opencode.json drift) — change rolled back")

    return {
        "agent": spec.agent,
        "model": entry.get("model"),
        "mode": entry.get("mode"),
        "fallback_models": entry.get("fallback_models"),
        "description": entry.get("description"),
    }
