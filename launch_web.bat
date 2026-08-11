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
echo [launch_web] ZOVA_ALLOW_INSECURE_TLS=%ZOVA_ALLOW_INSECURE_TLS% - opencode cert verification DISABLED
set "NODE_TLS_REJECT_UNAUTHORIZED=0"
:tls_skip

set "WORKSPACE="
set "HOST="
set "PORT="
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
if /i "%~1"=="--host" (
    set "HOST=--host %~2"
    shift
)
if /i "%~1"=="--port" (
    set "PORT=--port %~2"
    shift
)
shift
goto :parse
:parsed

if defined SMOKE (
    echo [launch_web] SMOKE: headless build check of the web dashboard, then exiting.
    python scripts\web_app.py --smoke
    exit /b 0
)

echo [launch_web] Starting ZOVA WEB dashboard...
start "ZOVA WEB - Dashboard" python scripts\web_app.py %WORKSPACE% %HOST% %PORT%
exit /b 0

:usage
echo Usage: launch_web.bat [--workspace DIR] [--host HOST] [--port N] [--smoke]
echo.
echo   (no args)          Launch the ZOVA WEB dashboard in a new window
echo   --workspace DIR    Control-plane root to monitor (default: repo root)
echo   --host HOST        Bind address (default: 127.0.0.1)
echo   --port N           Listen port (default: 8787)
echo   --smoke            Headless build check of the app, then exit
exit /b 0