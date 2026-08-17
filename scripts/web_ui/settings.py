"""Settings facade — single backend for the Settings UI (Phase 25).

The facade never stores secrets itself: API keys live **exclusively** in the
OpenCode auth store (``~/.local/share/opencode/auth.json``), written via the
``opencode auth`` CLI with a format-preserving fallback write when the CLI
cannot log in non-interactively. No endpoint ever returns a key — the
frontend only ever sees ``configured: true|false``.

Configuration sources (never duplicated):
    * Agent registry (``scripts/core/agents``)  — identity only (tag/name/key)
    * ``opencode.json``                        — runtime model/mode/fallback + providers
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
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts.core import (
    agent_catalog,
    opencode_cfg,
    prompt_library,
    roles,
    runtime_context,
    skills,
)
from scripts.core.agents import AGENT_SPECS

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

# Name aliases: a model id may be prefixed by the provider's *name* as well as
# its id (e.g. ``gemini/gemini-2.x`` for the ``google`` provider) — both forms
# canonicalize to the same model and must never be treated as distinct.
_PROVIDER_NAME_ALIASES = {p["id"]: {p["name"].lower()} for p in SIMPLE_PROVIDERS}


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
            input=(key + "\n"), capture_output=True, text=True, timeout=30,
            check=False,
        )
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


_URL_QUERY_RE = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")


def _scrub(text: str, *secrets: str | None) -> str:
    """Remove secret material from a message before it leaves the backend.

    Replaces known secrets, then drops the query string of any URL in the
    text (query strings commonly carry API keys).
    """
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "***")
    return _URL_QUERY_RE.sub(r"\1", text)


def _validate_base_url(base_url: str | None) -> str:
    """Require a real http(s) Base URL for Advanced connections."""
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        raise opencode_cfg.ConfigError("a Base URL is required for Advanced connections")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise opencode_cfg.ConfigError(
            f"invalid Base URL {base_url!r} (expected http(s)://host[:port][/path])")
    return base_url


def test_connection(provider_id: str, key: str | None = None,
                    base_url: str | None = None, auth: str | None = None) -> dict:
    """Real connection validation — never a fake success.

    Advanced/custom providers must supply a valid http(s) Base URL and the
    probe must actually reach ``{base}/models`` (or the provider's known
    endpoint) and return 2xx before this reports success.
    """
    if provider_id not in SIMPLE_PROVIDER_BY_ID:
        try:
            base_url = _validate_base_url(base_url)
        except opencode_cfg.ConfigError as exc:
            return {"ok": False, "detail": str(exc)}
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
        return {"ok": False,
                "detail": _scrub(f"connection failed: {reason}", url, key, base_url)}
    except ValueError:
        return {"ok": False, "detail": "unexpected response from provider"}
    except OSError as exc:
        return {"ok": False,
                "detail": _scrub(f"connection failed: {exc}", url, key, base_url)}
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
                              capture_output=True, text=True, timeout=60,
                              check=False)
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
                   base_url: str | None, auth: str | None) -> tuple[list[str], bool, bool]:
    """Live model discovery; returns (ids, discovery_supported, ok)."""
    url, headers = _probe_request(provider_id, key, base_url, auth)
    if url:
        try:
            data, _lat = _http_json(url, headers=headers)
        except Exception:  # noqa: BLE001 — probe failure → discovery unavailable
            return [], False, False
        return _parse_model_list(data, provider_id), True, True
    return _cli_models(provider_id), True, True


def _configured_models(cfg: dict, provider_id: str) -> list[str]:
    """Models already declared in opencode.json for this provider."""
    out: set[str] = set()
    prov = opencode_cfg.get_provider(cfg, provider_id)
    if prov:
        out.update(prov.get("models") or {})
    prefix = provider_id + "/"
    agents_cfg = cfg.get("agent") or {}
    for spec in AGENT_SPECS:
        entry = agents_cfg.get(spec.agent) or {}
        model = entry.get("model")
        if model and model.startswith(prefix):
            out.add(model.split("/", 1)[1])
        for fb in entry.get("fallback_models") or []:
            if fb.startswith(prefix):
                out.add(fb.split("/", 1)[1])
    return sorted(out)


def discover_models(provider_id: str, key: str | None = None,
                    base_url: str | None = None, auth: str | None = None,
                    repo_root: Path | None = None) -> dict:
    cfg = opencode_cfg.load_config(repo_root)
    configured = _configured_models(cfg, provider_id)
    discovered, supported, ok = _discover_live(provider_id, key, base_url, auth)
    models = [{"id": m, "name": m, "source": "configured"} for m in configured]
    seen = set(configured)
    for mid in discovered:
        if mid not in seen:
            seen.add(mid)
            models.append({"id": mid, "name": mid, "source": "discovered"})
    return {"ok": ok, "discovery_supported": supported, "models": models}


# ------------------------------------------------------------------ connections


CONNECTION_STATUS = ("not_configured", "configured", "tested", "validation_failed")


def _connection_status(provider_id: str, configured: bool,
                       overrides: dict[str, str] | None) -> str:
    """Derive the persisted connection status (never key material)."""
    st = (overrides or {}).get(provider_id)
    if st == "validation_failed":
        return "validation_failed"
    if not configured:
        return "not_configured"
    if st == "tested":
        return "tested"
    return "configured"


def connections(repo_root: Path | None = None, auth_store: Path | None = None,
                status_overrides: dict[str, str] | None = None) -> list[dict]:
    """Provider list with masked status only (never keys)."""
    cfg = opencode_cfg.load_config(repo_root)
    keys = auth_status(auth_store)
    out: list[dict] = []
    for p in SIMPLE_PROVIDERS:
        out.append({"id": p["id"], "name": p["name"], "kind": "simple",
                    "configured": p["id"] in keys, "base_url": None,
                    "status": _connection_status(p["id"], p["id"] in keys,
                                                  status_overrides)})
    for pid, prov in (cfg.get("provider") or {}).items():
        if pid in SIMPLE_PROVIDER_BY_ID:
            continue
        out.append({
            "id": pid,
            "name": (prov.get("name") or pid),
            "kind": "advanced",
            "configured": pid in keys,
            "base_url": (prov.get("options") or {}).get("baseURL"),
            "status": _connection_status(pid, pid in keys, status_overrides),
        })
    return out


def provider_known(provider_id: str, repo_root: Path | None = None) -> bool:
    if provider_id in SIMPLE_PROVIDER_BY_ID:
        return True
    cfg = opencode_cfg.load_config(repo_root)
    return provider_id in (cfg.get("provider") or {})


def is_simple_provider(provider_id: str) -> bool:
    """True for the known Simple providers (google/openai/anthropic)."""
    return provider_id in SIMPLE_PROVIDER_BY_ID


def canonical_provider_block(provider_id: str,
                             models: list[str] | None = None) -> dict:
    """Canonical provider block for a known Simple provider.

    Always rebuilt from fixed metadata — an existing polluted block (wrong
    npm package, arbitrary baseURL/options from an old Advanced save) must
    never be merged into a Simple configuration.
    """
    meta = SIMPLE_PROVIDER_BY_ID.get(provider_id)
    if meta is None:
        raise opencode_cfg.ConfigError(
            f"{provider_id!r} is not a known Simple provider")
    block: dict = {"npm": meta["npm"], "name": meta["name"], "options": {}}
    if models:
        block["models"] = {m: {"name": m} for m in models}
    return block


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

    Selected models may be bare ids from discovery (``gemini-2.5-flash``) or
    full ids (``google/gemini-2.5-flash``); both are normalized to the bare
    form opencode.json provider blocks expect.
    """
    cfg = opencode_cfg.load_config(repo_root)
    model_ids = [normalize_model_id(provider_id, m, cfg) for m in (models or [])]
    changed = False

    if mode == "advanced":
        # Advanced mode is for custom providers only: a known Simple provider
        # (google/openai/anthropic) must never be saved as an Advanced block
        # with arbitrary npm/baseURL — that is how the google block became
        # polluted. Advanced connections are only valid with a real, reachable
        # Base URL.
        if is_simple_provider(provider_id):
            raise opencode_cfg.ConfigError(
                f"{provider_id!r} is a known Simple provider — use Simple mode")
        base_url = _validate_base_url(base_url)
        block = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider_id,
            "options": {"baseURL": base_url},
        }
        if model_ids:
            block["models"] = {m: {"name": m} for m in model_ids}
        opencode_cfg.upsert_provider(cfg, provider_id, block)
        changed = True
    elif is_simple_provider(provider_id):
        # Simple saves always rebuild the canonical block from fixed metadata:
        # a polluted block (wrong npm / arbitrary baseURL from an old Advanced
        # save) must never survive. Without models and without an existing
        # block there is nothing to write (built-in provider + auth store).
        if model_ids or opencode_cfg.get_provider(cfg, provider_id) is not None:
            opencode_cfg.upsert_provider(
                cfg, provider_id, canonical_provider_block(provider_id, model_ids))
            changed = True
    elif model_ids:
        block = dict(opencode_cfg.get_provider(cfg, provider_id) or {})
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


def add_manual_model(provider_id: str, model_id: str,
                     repo_root: Path | None = None) -> dict:
    """Add a manually specified model to a provider.

    Known Simple providers get their canonical block rebuilt, so a polluted
    block can never be resurrected by a manual add; Advanced providers keep
    their existing block. Raises ConfigError for invalid model ids.
    """
    bare = normalize_model_id(provider_id, model_id)
    cfg = opencode_cfg.load_config(repo_root)
    if is_simple_provider(provider_id):
        block = canonical_provider_block(provider_id)
    else:
        block = dict(opencode_cfg.get_provider(cfg, provider_id) or {})
    block.setdefault("models", {})[bare] = {"name": bare}
    opencode_cfg.upsert_provider(cfg, provider_id, block)
    opencode_cfg.save_config(cfg, repo_root)
    return {"ok": True, "models": sorted(block["models"])}


# ------------------------------------------------------------------ agent views


def agent_config(repo_root: Path | None = None) -> list[dict]:
    """Per-agent runtime config resolved from ``opencode.json`` (the single
    source of truth for models/modes/fallback). AgentSpec carries identity
    only, so there is no spec↔config model drift by design (``drift`` is kept
    for API compatibility and always ``False``)."""
    cfg = opencode_cfg.load_config(repo_root)
    agents: list[dict] = []
    for spec in AGENT_SPECS:
        entry = (cfg.get("agent") or {}).get(spec.agent) or {}
        model = entry.get("model") or cfg.get("model") or None
        agents.append({
            "tag": spec.tag,
            "name": spec.name,
            "agent": spec.agent,
            "model": model,
            "fallback_models": entry.get("fallback_models") or [],
            "mode": entry.get("mode") or "all",
            "description": entry.get("description") or "",
            "drift": False,
        })
    return agents


def available_models(repo_root: Path | None = None) -> list[dict]:
    """Models selectable for agents (configured providers + assigned models)."""
    cfg = opencode_cfg.load_config(repo_root)
    by_id: dict[str, dict] = {}
    for pid, prov in (cfg.get("provider") or {}).items():
        for mid in (prov.get("models") or {}):
            full = f"{pid}/{mid}"
            by_id.setdefault(full, {"id": full, "name": mid, "source": "configured"})
    for spec in AGENT_SPECS:
        model = (cfg.get("agent") or {}).get(spec.agent, {}).get("model")
        if model:
            by_id.setdefault(model, {"id": model, "name": model,
                                      "source": "configured"})
    return sorted(by_id.values(), key=lambda m: m["id"])


# ------------------------------------------------------------------ model catalog


def _stored_key(provider_id: str, auth_store: Path | None = None) -> str | None:
    """Read a stored key for backend-side discovery. Never returned or logged."""
    data = _read_auth_store(Path(auth_store) if auth_store else _default_auth_store())
    entry = data.get(provider_id)
    if isinstance(entry, dict) and entry.get("type") == "api":
        return entry.get("key") or None
    return None


def normalize_model_id(provider_id: str, model_id: str,
                       cfg: dict | None = None) -> str:
    """Bare model id from either input form, name-alias aware.

    For provider ``google`` (name ``Gemini``), all of ``gemini-2.x``,
    ``google/gemini-2.x`` and ``gemini/gemini-2.x`` normalize to
    ``gemini-2.x`` so they are never treated as distinct models.
    """
    aliases = set(_PROVIDER_NAME_ALIASES.get(provider_id, ()))
    aliases.add(provider_id)
    if cfg is not None:
        prov = (cfg.get("provider") or {}).get(provider_id) or {}
        name = str(prov.get("name") or "").strip().lower()
        if name and name != provider_id:
            aliases.add(name)
    return opencode_cfg.validate_bare_model_id(model_id, provider_id, tuple(aliases))


def canonical_model_id(provider_id: str, model_id: str) -> str:
    """Canonical internal model id ``provider/bare`` for either input form.

    ``gemini/gemini-2.x`` and ``gemini-2.x`` both canonicalize to
    ``gemini/gemini-2.x`` so they are never treated as distinct models.
    """
    return f"{provider_id}/{normalize_model_id(provider_id, model_id)}"


def _catalog_model(provider_id: str, bare: str, source: str, enabled: bool) -> dict:
    return {
        "provider": provider_id,
        "model_id": canonical_model_id(provider_id, bare),
        "display_name": bare,
        "source": source,
        "enabled": enabled,
    }


def _safe_error(exc: Exception) -> str:
    return str(exc)[:200] or exc.__class__.__name__


def model_catalog(repo_root: Path | None = None,
                  auth_store: Path | None = None) -> dict:
    """Per-connection model catalog: enabled (configured) + live-discovered.

    Saved connections feed discovery using their stored key; a failing
    provider is reported as unavailable and never breaks the rest of the
    catalog. Model ids are deduplicated on the canonical ``provider/bare``
    form. Never includes key material.
    """
    cfg = opencode_cfg.load_config(repo_root)
    providers: list[dict] = []
    for conn in connections(repo_root, auth_store):
        pid, name, kind, base_url, configured = (
            conn["id"], conn["name"], conn["kind"], conn["base_url"], conn["configured"])
        entry: dict = {"provider": pid, "name": name, "kind": kind,
                       "configured": configured, "available": None,
                       "error": None, "models": []}
        providers.append(entry)
        if not configured:
            continue
        prov = opencode_cfg.get_provider(cfg, pid) or {}
        enabled = set(prov.get("models") or {})
        merged: dict[str, dict] = {}
        for bare in enabled:
            merged[canonical_model_id(pid, bare)] = _catalog_model(pid, bare, "configured", True)
        try:
            disc = discover_models(pid, key=_stored_key(pid, auth_store),
                                   base_url=base_url, repo_root=repo_root)
            if disc.get("ok"):
                entry["available"] = True
                for m in disc["models"]:
                    if m["source"] == "discovered":
                        merged.setdefault(
                            canonical_model_id(pid, m["id"]),
                            _catalog_model(pid, m["id"], "discovered", False))
            else:
                entry["available"] = False
                entry["error"] = "model discovery failed for this provider"
        except Exception as exc:  # noqa: BLE001 — isolation per provider
            entry["available"] = False
            entry["error"] = _safe_error(exc)
        entry["models"] = sorted(merged.values(), key=lambda m: m["display_name"])
    return {"providers": providers}


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


# ------------------------------------------------------------------ roles


def list_roles(repo_root: Path | None = None) -> list[dict]:
    """All role definitions (predefined + custom) as dicts."""
    return [{"id": r.id, **r.to_dict()} for r in roles.list_roles(repo_root)]


def role_assignments(repo_root: Path | None = None) -> dict:
    """Agent key -> ordered role ids (the many-to-many assignment map)."""
    return {spec.agent: roles.roles_for_agent(spec.agent, repo_root)
            for spec in AGENT_SPECS}


def assign_roles(agent: str, role_ids: list[str],
                 repo_root: Path | None = None) -> list[str]:
    """Set an agent's role list (many-to-many). Raises RoleError for bad ids."""
    return roles.assign_roles(agent, role_ids, repo_root)


def create_role(role_id: str, *, name: str | None = None, description: str = "",
                responsibilities: list[str] | None = None,
                tools: list[str] | None = None,
                permissions: list[str] | None = None,
                rules: list[str] | None = None,
                expected_outputs: list[str] | None = None,
                repo_root: Path | None = None) -> dict:
    """Create (or overwrite) a custom role. Returns the stored role dict."""
    role = roles.create_role(
        role_id, name=name, description=description,
        responsibilities=responsibilities or [], tools=tools or [],
        permissions=permissions or [], rules=rules or [],
        expected_outputs=expected_outputs or [], repo_root=repo_root)
    return {"id": role.id, **role.to_dict()}


# ------------------------------------------- agent context (skills / profiles)


def list_skills(repo_root: Path | None = None) -> list[dict]:
    """All built-in skills as dicts (id + procedure metadata, no prompt text)."""
    return [{"id": s.id, "name": s.name, "category": s.category,
             "description": s.description, "source": s.source,
             "license": s.license, "origin": s.origin} for s in skills.list_skills()]


def list_prompt_profiles(repo_root: Path | None = None) -> list[dict]:
    """Prompt-profile metadata (id/name/role only — never the prompt text)."""
    return [{"id": p.id, "name": p.name, "role": p.role,
             "category": p.category, "origin": p.origin}
            for p in prompt_library.list_prompts()]


def skill_assignments(repo_root: Path | None = None) -> dict:
    """Agent key -> ordered skill ids."""
    return {spec.agent: runtime_context.skills_for_agent(spec.agent, repo_root)
            for spec in AGENT_SPECS}


def prompt_assignments(repo_root: Path | None = None) -> dict:
    """Agent key -> ordered prompt-profile ids."""
    return {spec.agent: runtime_context.prompt_profiles_for_agent(spec.agent, repo_root)
            for spec in AGENT_SPECS}


def role_derived_skills(agent: str, repo_root: Path | None = None) -> list[str]:
    """Skill ids automatically implied by the agent's assigned roles."""
    return runtime_context.role_derived_skill_ids_for_agent(agent, repo_root)


def role_derived_prompt_profiles(agent: str,
                                 repo_root: Path | None = None) -> list[str]:
    """Prompt-profile ids automatically implied by the agent's assigned roles."""
    return runtime_context.role_derived_profile_ids_for_agent(agent, repo_root)


def assign_skills(agent: str, skill_ids: list[str],
                  repo_root: Path | None = None) -> list[str]:
    """Set an agent's skill list. Raises SkillError for unknown ids."""
    return runtime_context.assign_skills(agent, skill_ids, repo_root)


def assign_prompt_profiles(agent: str, profile_ids: list[str],
                           repo_root: Path | None = None) -> list[str]:
    """Set an agent's prompt-profile list. Raises PromptError for unknown ids."""
    return runtime_context.assign_prompt_profiles(agent, profile_ids, repo_root)


# ------------------------------------------- agent catalog (categories/presets)


def agent_catalog_data(repo_root: Path | None = None) -> dict:
    """The Agent Catalog for the sidebar: Empty Agent + categories → presets.

    Each preset is fully resolved (model/mode/role/skills/prompt profiles), so
    selecting a preset populates the complete configuration deterministically.
    """
    empty = agent_catalog.resolve_preset_config(agent_catalog.empty_agent())
    categories: list[dict] = []
    for cat in agent_catalog.list_categories(repo_root):
        presets = [agent_catalog.resolve_preset_config(p, repo_root)
                   for p in agent_catalog.presets_for_category(cat.id, repo_root)]
        categories.append({**cat.to_dict(), "presets": presets})
    return {"empty_agent": empty, "categories": categories}


def role_categories(repo_root: Path | None = None) -> list[dict]:
    """Role categories (two-level selector): category → roles.

    Derived from the catalog's role → category taxonomy over the live role
    registry; custom roles not in the taxonomy appear under ``Uncategorized``.
    """
    known = {role_id for category in agent_catalog.role_categories(repo_root)
             for role_id in agent_catalog.roles_in_category(category.id, repo_root)}
    roles_by_id = {r.id: r for r in roles.list_roles(repo_root)}
    out: list[dict] = []
    for cat in agent_catalog.role_categories(repo_root):
        items = []
        for rid in agent_catalog.roles_in_category(cat.id, repo_root):
            r = roles_by_id.get(rid)
            if r:
                items.append({"id": r.id, "name": r.name})
        out.append({"id": cat.id, "name": cat.name, "roles": items})
    uncategorized = [{"id": r.id, "name": r.name}
                     for r in roles.list_roles(repo_root) if r.id not in known]
    if uncategorized:
        out.append({"id": "", "name": "Uncategorized", "roles": uncategorized})
    return out


def prompt_categories() -> list[dict]:
    """Prompt categories (two-level selector): category → prompt profiles.

    Only profiles belonging to a category appear under it; the full flat list
    is never returned by this facade.
    """
    out: list[dict] = []
    for cat in prompt_library.CATEGORIES:
        profiles = prompt_library.list_prompts_by_category(cat)
        out.append({
            "id": cat,
            "name": cat.replace("_", " ").title(),
            "profiles": [{"id": p.id, "name": p.name} for p in profiles],
        })
    return out
