@echo off
setlocal
rem ───────────────────────────────────────────────────────────────────
rem  MultiAgentCoding — Agent Dashboard launcher
rem  Starts the Obsidian-inspired web dashboard (primary interface) and
rem  opens the default browser. The ZOVA retro terminal remains available
rem  as a fallback (run: python scripts/terminal_app.py).
rem ───────────────────────────────────────────────────────────────────
rem  The dashboard must run on the project's own interpreter (.venv),
rem  never a global/Hermes/OpenCode Python resolved through PATH.
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo ERROR: Project virtual environment not found:
    echo   %PYTHON%
    exit /b 1
)

cd /d "%ROOT%"
echo [launch_dashboard] interpreter: %PYTHON%
"%PYTHON%" -m scripts.web_ui.server %*

set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%