"""Focused dashboard-prompt -> existing FreeBuff PTY bridge tests."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from scripts.core.run_hub import HUB
from scripts.web_ui import routes
from scripts.web_ui.state import WebState


class FakePty:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.alive = True

    def poll(self):
        return None if self.alive else 1

    def write(self, text: str) -> None:
        self.writes.append(text)


def _endpoint():
    router = routes.create_router(Path.cwd(), WebState(hub=HUB))
    return next(r.endpoint for r in router.routes
                if getattr(r, "path", "") == "/api/agents/{tag}/freebuff/submit")


def test_dashboard_prompt_writes_exact_text_and_one_enter_to_existing_pty(monkeypatch):
    proc = FakePty()
    monkeypatch.setattr(routes, "process_for", lambda tag: proc)
    monkeypatch.setattr(routes, "write_input",
                        lambda tag, text: (proc.write(text) or True))
    monkeypatch.setattr(routes, "output_checkpoint", lambda tag, p: 0)
    monkeypatch.setattr(routes, "wait_for_output", lambda *args, **kwargs: True)
    monkeypatch.setattr(HUB, "run", lambda *args, **kwargs: pytest.fail("provider fallback"))

    result = asyncio.run(_endpoint()("m1", {"prompt": "Respond only with BRIDGE_ONE"}))

    assert result["session_id"] == "agent:m1:freebuff/auto"
    assert result["written"] is True
    assert result["echoed"] is True
    assert result["submitted"] is True
    assert proc.writes == ["Respond only with BRIDGE_ONE", "\r"]


def test_bridge_does_not_create_or_use_another_process(monkeypatch):
    proc = FakePty()
    calls = []
    monkeypatch.setattr(routes, "process_for", lambda tag: (calls.append(tag) or proc))
    monkeypatch.setattr(routes, "write_input",
                        lambda tag, text: (proc.write(text) or True))
    monkeypatch.setattr(routes, "output_checkpoint", lambda tag, p: 0)
    monkeypatch.setattr(routes, "wait_for_output", lambda *args, **kwargs: True)
    monkeypatch.setattr(routes, "launch_freebuff_cmd", lambda *a, **k: pytest.fail("new PTY"))

    asyncio.run(_endpoint()("m1", {"prompt": "BRIDGE_TWO"}))

    assert calls and all(tag == "m1" for tag in calls)
    assert proc.writes == ["BRIDGE_TWO", "\r"]


def test_missing_or_dead_pty_is_an_error_without_provider_fallback(monkeypatch):
    monkeypatch.setattr(routes, "process_for", lambda tag: None)
    with pytest.raises(Exception) as exc:
        asyncio.run(_endpoint()("m1", {"prompt": "no fallback"}))
    assert exc.value.detail == "FreeBuff PTY for 'm1' is not running"

    dead = FakePty(); dead.alive = False
    monkeypatch.setattr(routes, "process_for", lambda tag: dead)
    with pytest.raises(Exception) as exc:
        asyncio.run(_endpoint()("m1", {"prompt": "still no fallback"}))
    assert exc.value.detail == "FreeBuff PTY for 'm1' is not running"


def test_enter_waits_for_post_write_redraw_ack(monkeypatch):
    proc = FakePty()
    monkeypatch.setattr(routes, "process_for", lambda tag: proc)
    monkeypatch.setattr(routes, "output_checkpoint", lambda tag, p: 0)
    monkeypatch.setattr(routes, "write_input",
                        lambda tag, text: (proc.write(text) or True))
    monkeypatch.setattr(routes, "wait_for_output", lambda *args, **kwargs: False)

    with pytest.raises(Exception) as exc:
        asyncio.run(_endpoint()("m1", {"prompt": "WAIT_FOR_ECHO"}))

    assert "acknowledge" in exc.value.detail
    assert proc.writes == ["WAIT_FOR_ECHO"]


def test_empty_prompt_is_rejected(monkeypatch):
    monkeypatch.setattr(routes, "process_for", lambda tag: FakePty())
    with pytest.raises(Exception) as exc:
        asyncio.run(_endpoint()("m1", {"prompt": "  \n"}))
    assert exc.value.detail == "prompt must not be empty"
