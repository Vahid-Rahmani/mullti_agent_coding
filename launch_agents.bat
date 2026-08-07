@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "AGENT[1]=system-architect"
set "AGENT[2]=analyst"
set "AGENT[3]=planner"
set "AGENT[4]=backend-dev"
set "AGENT[5]=frontend-dev"
set "AGENT[6]=tester"
set "AGENT[7]=reviewer"

set "ROLE[1]=System Architect"
set "ROLE[2]=Analyst"
set "ROLE[3]=Planner"
set "ROLE[4]=Backend Dev"
set "ROLE[5]=Frontend Dev"
set "ROLE[6]=Tester"
set "ROLE[7]=Reviewer"

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
    for /L %%i in (1,1,7) do (
        if not exist "_inbox\!AGENT[%%i]!.task" (
            echo Reply with exactly: SMOKE-OK> "_inbox\!AGENT[%%i]!.task"
        )
    )
    echo [launch_agents] Seeded 7 SMOKE tasks. Launching windows in -Smoke mode...
) else (
    echo [launch_agents] Launching 7 agent windows. Drop a task into _inbox\^<agent^>.task to run it.
)

for /L %%i in (1,1,7) do (
    set "extra="
    if defined SMOKE set "extra=-Smoke"
    if defined DRY (
        echo [dry] start "M%%i - !ROLE[%%i]!" powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\run_agent_worker.ps1" -Agent "!AGENT[%%i]!" -Title "M%%i - !ROLE[%%i]!" -Slot %%i !extra!
    ) else (
        start "M%%i - !ROLE[%%i]!" powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\run_agent_worker.ps1" -Agent "!AGENT[%%i]!" -Title "M%%i - !ROLE[%%i]!" -Slot %%i !extra!
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
