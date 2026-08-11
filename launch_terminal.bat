@echo off
setlocal
cd /d "%~dp0"

rem --- Optional TLS bypass for opencode (strictly opt-in): environments with
rem --- self-signed or intercepting certificates set ZOVA_ALLOW_INSECURE_TLS=1
rem --- (also accepts true/yes, case-insensitive). Children inherit the var.
if /i "%ZOVA_ALLOW_INSECURE_TLS%"=="1" goto :tls_on
if /i "%ZOVA_ALLOW_INSECURE_TLS%"=="true" goto :tls_on
if /i "%ZOVA_ALLOW_INSECURE_TLS%"=="yes" goto :tls_on
goto :tls_skip
:tls_on
echo [launch_terminal] ZOVA_ALLOW_INSECURE_TLS=%ZOVA_ALLOW_INSECURE_TLS% - opencode cert verification DISABLED
set "NODE_TLS_REJECT_UNAUTHORIZED=0"
:tls_skip

set "WORKSPACE="
set "SMOKE="

:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--smoke" set "SMOKE=1"
if /i "%~1"=="--workspace" (
    set "WORKSPACE=--workspace %~2"
    shift
)
shift
goto :parse
:parsed

if defined SMOKE (
    echo [launch_terminal] SMOKE: headless build check of the retro terminal, then exiting.
    python scripts\terminal_app.py --smoke
    exit /b 0
)

echo [launch_terminal] Starting ZOVA retro terminal...
start "ZOVA - Retro Terminal" python scripts\terminal_app.py %WORKSPACE%
exit /b 0

:usage
echo Usage: launch_terminal.bat [--workspace DIR] [--smoke]
echo.
echo   (no args)          Launch the ZOVA retro terminal in a new window
echo   --workspace DIR    Agents work in DIR (default: the repo root)
echo   --smoke            Headless build check of the app, then exit
exit /b 0
