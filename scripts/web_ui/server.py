"""Dashboard server — FastAPI app factory + uvicorn entry + smoke check.

Usage:
    python -m scripts.web_ui.server                # start + open browser
    python -m scripts.web_ui.server --no-browser   # start only
    python -m scripts.web_ui.server --smoke        # construct app, exit 0 (no bind)

The app reuses the global ``HUB``, the vault at ``obsidian_vault/`` (or
``--vault`` / ``$ZOVA_VAULT``), and serves a self-contained static frontend.
No backend code is modified.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scripts.core.orchestrator import resolve_vault
from scripts.web_ui.routes import create_router
from scripts.web_ui.state import WebState

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(vault: Path | None = None, state: WebState | None = None) -> FastAPI:
    """Build the dashboard app around an explicit vault + WebState."""
    resolved_vault = Path(vault or resolve_vault(None)).expanduser().resolve()
    web_state = state or WebState()
    web_state.load_prefs()

    app = FastAPI(title="MultiAgentCoding Dashboard", version="0.1.0")
    app.include_router(create_router(resolved_vault, web_state))

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.web_ui.server",
        description="Obsidian-inspired MultiAgentCoding dashboard.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--vault", default=None, help="vault path (default: repo obsidian_vault, or $ZOVA_VAULT)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--smoke", action="store_true",
                        help="construct the app and exit (no server bind)")
    args = parser.parse_args(argv)

    app = create_app(vault=args.vault)
    if args.smoke:
        print("SMOKE-OK: dashboard app constructed (FastAPI, routes, static)")
        return 0

    url = f"http://{args.host}:{args.port}"
    print(f"MultiAgentCoding dashboard → {url}")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    sys.exit(main())