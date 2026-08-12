"""Settings facade — single backend for the Settings UI (Phase 25).

The facade never stores secrets itself: API keys live **exclusively** in the
OpenCode auth store (``~/.local/share/opencode/auth.json``), written via the
``opencode auth`` CLI with a format-preserving fallback write when the CLI
cannot log in non-interactively. No endpoint ever returns a key — the
frontend only ever sees ``configured: true|false``.

Configuration sources (never duplicated):
    * Agent registry (``scripts/core/agents``)  — identity + default model
    * ``opencode.json``                        — runtime agent config + providers
    * OpenCode auth store                      — credentials
    * opencode CLI / provider REST APIs        — model discovery

Two connection modes:
    * ``simple``   — known provider (Gemini/OpenAI/Anthropic/…): only provider
                     name + API key; the endpoint/auth shape is auto-determined.
    * ``advanced`` — custom / OpenCode-style provider: name, base URL, API key,
                     authentication method, default model, extra options.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.core import opencode_cfg
from scripts.core.agents import AGENT_SPECS, PROJECT_ROOT

TIMEOUT_SECONDS = 12

# ------------------------------------------------------------------ providers
# Connection metadata only — NEVER a model list. Model ids always come from
# live discovery (opencode CLI or the provider's REST model list).
SIMPLE_PROVIDERS: list[dict] = [
    {
        "id": "google",
        "name": "Gemini",
        "npm": "@ai-sdk/google",
        "probe": {"type": "gemini", "url": "https://generativelanguage.googleapis.com/v1beta/models"},
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "npm": "@ai-sdk/openai",
        "probe": {"type": "openai_compatible", "base": "https://api.openai.com/v1"},
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "npm": "@ai-sdk/anthropic",
        "probe": {"type": "anthropic", "url": "https://api.anthropic.com/v1/models"},
    },
]
SIMPLE_PROVIDER_BY_ID = {p["id"]: p for p in SIMPLE_PROVIDERS}


class SettingsError(RuntimeError):
    """Safe (non-secret) settings failure surfaced to the UI."""


# ------------------------------------------------------------------ auth store
# The OpenCode auth store is the ONLY secret store. Functions here either read
# masked status (provider id present/absent) or write/remove an API-key entry;
# the key value itself is never returned to callers.


def _default_auth_store() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _read_auth_store(path: Path) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def auth_status(auth_store: Path | None = None) -> set[str]:
    """Provider ids that currently have an API key stored (masked status only)."""
    data = _read_auth_store(Path(auth_store) if auth_store else _default_auth_store())
    return {k for k, v in data.items()
            if isinstance(v, dict) and v.get("type") == "api" and v.get("key")}


def _auth_login_cli(provider_id: str, key: str) -> bool:
    """Try ``opencode auth login <provider>`` with the key piped in."""
    exe = shutil.which("opencode")
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "auth", "login", provider_id],
            input=(key + "\n"), capture_output=True, text=True, timeout=30)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def save_key(provider_id: str, key: str, auth_store: Path | None = None) -> bool:
    """Persist an API key in the OpenCode auth store; never returns the key."""
    key = (key or "").strip()
    if not key:
        return False
    if _auth_login_cli(provider_id, key):
        return provider_id in auth_status(auth_store)
    # Format-preserving fallback write into the same store (api-key entry).
    path = Path(auth_store) if auth_store else _default_auth_store()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_auth_store(path)
    data[provider_id] = {"type": "api", "key": key}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return provider_id in auth_status(auth_store)


def remove_api_key(provider_id: str, auth_store: Path | None = None) -> bool:
    path = Path(auth_store) if auth_store else _default_auth_store()
    data = _read_auth_store(path)
    if provider_id not in data:
        return False
    del data[provider_id]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


# ------------------------------------------------------------------ http probe


def _http_json(url: str, headers: dict | None = None) -> tuple[dict | list, int]:
    """GET a JSON endpoint; returns (payload, latency_ms). Raises on failure."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        body = resp.read().decode("utf-8", "replace")
        latency = round((time.monotonic() - t0) * 1000)
        return json.loads(body), latency


def _probe_request(provider_id: str, key: str | None = None,
                   base_url: str | None = None, auth: str | None = None,
                   ) -> tuple[str | None, dict]:
    """Resolve (url, headers) for a connection probe — keys never logged."""
    meta = SIMPLE_PROVIDER_BY_ID.get(provider_id)
    if meta:
        probe = meta["probe"]
        if probe["type"] == "gemini":
            url = probe["url"] + "?" + urllib.parse.urlencode({"key": key or ""})
            return url, {}
        if probe["type"] == "anthropic":
            return probe["url"], {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
        base = (base_url or probe["base"]).rstrip("/")
        return base + "/models", {"Authorization": "Bearer " + (key or "")}
    if base_url:
        base = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if key:
            method = (auth or "").strip().lower()
            if method in ("", "bearer"):
                headers["Authorization"] = "Bearer " + key
            elif method == "x-api-key":
                headers["x-api-key"] = key
        return base + "/models", headers
    return None, {}


def _safe_http_error(exc: urllib.error.HTTPError) -> str:
    return f"provider returned HTTP {exc.code}"


def test_connection(provider_id: str, key: str | None = None,
                    base_url: str | None = None, auth: str | None = None) -> dict:
    url, headers = _probe_request(provider_id, key, base_url, auth)
    if not url:
        return {"ok": False,
                "detail": "no endpoint known for this provider — use Advanced mode with a Base URL"}
    try:
        _payload, latency = _http_json(url, headers=headers)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detail": _safe_http_error(exc)}
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return {"ok": False, "detail": f"connection failed: {reason}"}
    except ValueError:
        return {"ok": False, "detail": "unexpected response from provider"}
    except OSError as exc:
        return {"ok": False, "detail": f"connection failed: {exc}"}
    return {"ok": True, "detail": "connection successful", "latency_ms": latency}


# ------------------------------------------------------------------ discovery


def _parse_model_list(data, provider_id: str) -> list[str]:
    """Parse a provider model list into bare model ids (no provider prefix)."""
    ids: list[str] = []
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        for m in data["models"]:
            name = str(m.get("name") or m.get("id") or "").strip()
            if name.startswith("models/"):
                name = name.split("/", 1)[1]
            if name:
                ids.append(name)
    elif isinstance(data, dict) and isinstance(data.get("data"), list):
        for m in data["data"]:
            mid = str(m.get("id") or "").strip()
            if mid:
                ids.append(mid)
    return ids


def _cli_models(provider_id: str) -> list[str]:
    """Discover models via the installed opencode CLI (models.dev catalog)."""
    exe = shutil.which("opencode")
    if not exe:
        return []
    try:
        proc = subprocess.run([exe, "models", provider_id],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    ids: list[str] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith(("┃", "│", "┃", "#", "Provider", "MODEL")):
            continue
        token = line.split()[-1]
        if "/" in token and not token.startswith("("):
            ids.append(token)
    return ids


def _discover_live(provider_id: str, key: str | None,
                   base_url: str | None, auth: str | None) -> tuple[list[str], bool]:
    """Live model discovery; returns (ids, discovery_supported)."""
    url, headers = _probe_request(provider_id, key, base_url, auth)
    if url:
        try:
            data, _lat = _http_json(url, headers=headers)
        except Exception:  # noqa: BLE001 — probe failure just disables discovery
            return [], False
        return _parse_model_list(data, provider_id), True
    return _cli_models(provider_id), True


def _configured_models(cfg: dict, provider_id: str) -> list[str]:
    """Models already declared in opencode.json for this provider."""
    out: set[str] = set()
    prov = opencode_cfg.get_provider(cfg, provider_id)
    if prov:
        out.update(prov.get("models") or {})
    prefix = provider_id + "/"
    for spec in AGENT_SPECS:
        if spec.model and spec.model.startswith(prefix):
            out.add(spec.model.split("/", 1)[1])
        entry = (cfg.get("agent") or {}).get(spec.agent) or {}
        for fb in entry.get("fallback_models") or []:
            if fb.startswith(prefix):
                out.add(fb.split("/", 1)[1])
    return sorted(out)


def discover_models(provider_id: str, key: str | None = None,
                    base_url: str | None = None, auth: str | None = None,
                    repo_root: Path | None = None) -> dict:
    cfg = opencode_cfg.load_config(repo_root)
    configured = _configured_models(cfg, provider_id)
    discovered, supported = _discover_live(provider_id, key, base_url, auth)
    models = [{"id": m, "name": m, "source": "configured"} for m in configured]
    seen = set(configured)
    for mid in discovered:
        if mid not in seen:
            seen.add(mid)
            models.append({"id": mid, "name": mid, "source": "discovered"})
    return {"ok": True, "discovery_supported": supported, "models": models}


# ------------------------------------------------------------------ connections


def connections(repo_root: Path | None = None, auth_store: Path | None = None) -> list[dict]:
    """Provider list with masked status only (never keys)."""
    cfg = opencode_cfg.load_config(repo_root)
    keys = auth_status(auth_store)
    out: list[dict] = []
    for p in SIMPLE_PROVIDERS:
        out.append({"id": p["id"], "name": p["name"], "kind": "simple",
                    "configured": p["id"] in keys, "base_url": None})
    for pid, prov in (cfg.get("provider") or {}).items():
        if pid in SIMPLE_PROVIDER_BY_ID:
            continue
        out.append({
            "id": pid,
            "name": (prov.get("name") or pid),
            "kind": "advanced",
            "configured": pid in keys,
            "base_url": (prov.get("options") or {}).get("baseURL"),
        })
    return out


def provider_known(provider_id: str, repo_root: Path | None = None) -> bool:
    if provider_id in SIMPLE_PROVIDER_BY_ID:
        return True
    cfg = opencode_cfg.load_config(repo_root)
    return provider_id in (cfg.get("provider") or {})


def save_connection(
    provider_id: str,
    *,
    mode: str = "simple",
    key: str | None = None,
    base_url: str | None = None,
    auth: str | None = None,
    models: list[str] | None = None,
    repo_root: Path | None = None,
    auth_store: Path | None = None,
) -> dict:
    """Save a connection: provider block (opencode.json) + key (auth store).

    The returned dict contains masked status only — never a key.
    """
    model_ids = [opencode_cfg.validate_model_id(m) for m in (models or [])]
    cfg = opencode_cfg.load_config(repo_root)
    changed = False

    if mode == "advanced" and base_url:
        block = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider_id,
            "options": {"baseURL": base_url},
        }
        if model_ids:
            block["models"] = {m: {"name": m} for m in model_ids}
        opencode_cfg.upsert_provider(cfg, provider_id, block)
        changed = True
    elif model_ids:
        block = dict(opencode_cfg.get_provider(cfg, provider_id) or {})
        if not block and provider_id in SIMPLE_PROVIDER_BY_ID:
            meta = SIMPLE_PROVIDER_BY_ID[provider_id]
            block = {"npm": meta["npm"], "name": meta["name"], "options": {}}
        block["models"] = {m: {"name": m} for m in model_ids}
        opencode_cfg.upsert_provider(cfg, provider_id, block)
        changed = True

    if changed:
        opencode_cfg.save_config(cfg, repo_root)

    if key:
        configured = save_key(provider_id, key, auth_store)
        key_pending = not configured
        command = f"opencode auth login {provider_id}" if key_pending else None
    else:
        configured = provider_id in auth_status(auth_store)
        key_pending = False
        command = None

    return {"ok": True, "provider": provider_id, "configured": configured,
            "key_pending": key_pending, "command": command}


# ------------------------------------------------------------------ agent views


def agent_config(repo_root: Path | None = None) -> list[dict]:
    """Cross-checked per-agent runtime config (spec ↔ opencode.json)."""
    cfg = opencode_cfg.load_config(repo_root)
    agents: list[dict] = []
    for spec in AGENT_SPECS:
        entry = (cfg.get("agent") or {}).get(spec.agent) or {}
        model = spec.model
        agents.append({
            "tag": spec.tag,
            "name": spec.name,
            "agent": spec.agent,
            "model": model,
            "fallback_models": entry.get("fallback_models") or [],
            "mode": entry.get("mode") or "all",
            "description": entry.get("description") or "",
            "drift": bool(entry.get("model") is not None and entry.get("model") != model),
        })
    return agents


def available_models(repo_root: Path | None = None) -> list[dict]:
    """Models selectable for agents (configured providers + spec models)."""
    cfg = opencode_cfg.load_config(repo_root)
    by_id: dict[str, dict] = {}
    for pid, prov in (cfg.get("provider") or {}).items():
        for mid in (prov.get("models") or {}):
            full = f"{pid}/{mid}"
            by_id.setdefault(full, {"id": full, "name": mid, "source": "configured"})
    for spec in AGENT_SPECS:
        if spec.model:
            by_id.setdefault(spec.model, {"id": spec.model, "name": spec.model,
                                          "source": "configured"})
    return sorted(by_id.values(), key=lambda m: m["id"])


def apply_model(agent: str, model: str, repo_root: Path | None = None,
                verify_cmd: list[str] | None = None) -> dict:
    return opencode_cfg.apply_agent_config(agent, model=model,
                                           repo_root=repo_root, verify_cmd=verify_cmd)


def apply_mode(agent: str, mode: str, description: str | None = None,
               repo_root: Path | None = None, verify_cmd: list[str] | None = None) -> dict:
    return opencode_cfg.apply_agent_config(agent, mode=mode, description=description,
                                           repo_root=repo_root, verify_cmd=verify_cmd)


def apply_fallback(agent: str, fallback_models: list[str],
                   repo_root: Path | None = None, verify_cmd: list[str] | None = None) -> dict:
    return opencode_cfg.apply_agent_config(agent, fallback_models=fallback_models,
                                           repo_root=repo_root, verify_cmd=verify_cmd)
