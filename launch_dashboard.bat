@echo off
rem ───────────────────────────────────────────────────────────────────
rem  MultiAgentCoding — Agent Dashboard launcher
rem  Starts the Obsidian-inspired web dashboard (primary interface) and
rem  opens the default browser. The ZOVA retro terminal remains available
rem  as a fallback (run: python scripts/terminal_app.py).
rem ───────────────────────────────────────────────────────────────────
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
python -m scripts.web_ui.server