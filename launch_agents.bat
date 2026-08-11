@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem --- Optional TLS bypass for opencode (strictly opt-in): environments with
rem --- self-signed or intercepting certificates set ZOVA_ALLOW_INSECURE_TLS=1
rem --- (also accepts true/yes, case-insensitive). Children inherit the var.
if /i "%ZOVA_ALLOW_INSECURE_TLS%"=="1" goto :tls_on
if /i "%ZOVA_ALLOW_INSECURE_TLS%"=="true" goto :tls_on
if /i "%ZOVA_ALLOW_INSECURE_TLS%"=="yes" goto :tls_on
goto :tls_skip
:tls_on
echo [launch_agents] ZOVA_ALLOW_INSECURE_TLS=%ZOVA_ALLOW_INSECURE_TLS% - opencode cert verification DISABLED
set "NODE_TLS_REJECT_UNAUTHORIZED=0"
:tls_skip

rem --- -h/--help must work even without Python on PATH, so scan args first ---
for %%A in (%*) do (
    if /i "%%~A"=="--help" goto :usage
    if /i "%%~A"=="-h" goto :usage
)

rem --- Roster loaded from the canonical specs (scripts/core/agents) ---
rem One line per agent from `python -m scripts.core.agents roster`:
rem   <tag> <agent-key> <name> <model>
set /a AGENT_COUNT=0
for /f "usebackq tokens=1-4" %%L in (`python -m scripts.core.agents roster`) do (
    set /a AGENT_COUNT+=1
    set "TAG[!AGENT_COUNT!]=%%L"
    set "AGENT[!AGENT_COUNT!]=%%M"
    set "NAME[!AGENT_COUNT!]=%%N"
)
if not defined AGENT[1] (
    echo [launch_agents] ERROR: could not load the agent roster from "python -m scripts.core.agents roster".
    echo [launch_agents] Is Python on PATH? The 7-agent launcher reads scripts/core/agents specs via Python.
    exit /b 1
)
echo [launch_agents] Roster: %AGENT_COUNT% agents loaded from scripts/core/agents specs.

set "SMOKE="
set "DRY="
for %%A in (%*) do (
    if /i "%%~A"=="--help" goto :usage
    if /i "%%~A"=="-h" goto :usage
    if /i "%%~A"=="--smoke" set "SMOKE=1"
    if /i "%%~A"=="--dry" set "DRY=1"
)

if defined SMOKE (
    if not exist "_inbox" mkdir "_inbox"
    for /L %%i in (1,1,%AGENT_COUNT%) do (
        if not exist "_inbox\!AGENT[%%i]!.task" (
            echo Reply with exactly: SMOKE-OK> "_inbox\!AGENT[%%i]!.task"
        )
    )
    echo [launch_agents] Seeded %AGENT_COUNT% SMOKE tasks. Launching windows in -Smoke mode...
) else (
    echo [launch_agents] Launching %AGENT_COUNT% agent windows. Drop a task into _inbox\^<agent^>.task to run it.
)

for /L %%i in (1,1,%AGENT_COUNT%) do (
    set "extra="
    if defined SMOKE set "extra=-Smoke"
    if defined DRY (
        echo [dry] start "M%%i - !NAME[%%i]!" powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\run_agent_worker.ps1" -Agent "!AGENT[%%i]!" -Title "M%%i - !NAME[%%i]!" -Slot %%i !extra!
    ) else (
        start "M%%i - !NAME[%%i]!" powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\run_agent_worker.ps1" -Agent "!AGENT[%%i]!" -Title "M%%i - !NAME[%%i]!" -Slot %%i !extra!
    )
)
echo [launch_agents] Done. Windows auto-position in a 4x2 grid (M1-M4 top, M5-M7 bottom).
exit /b 0

:usage
echo Usage: launch_agents.bat [--smoke^|--dry]
echo.
echo   (no args)   Launch 7 agent windows (M1-M7) that poll _inbox\^<agent^>.task
echo   --smoke     Seed 7 SMOKE tasks, launch windows in -Smoke mode (each runs one task, then exits)
echo   --dry       Print the start commands without launching windows
exit /b 0
