@echo off
setlocal
cd /d "%~dp0"

set "PORT=8501"
set "NOBROWSER="
set "DRY="
set "SMOKE="
set "NOBROWSER_SPACE="

:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--no-browser" (
    set "NOBROWSER=--no-browser"
    set "NOBROWSER_SPACE= "
)
if /i "%~1"=="--dry" set "DRY=1"
if /i "%~1"=="--smoke" set "SMOKE=1"
if /i "%~1"=="--port" (
    set "PORT=%~2"
    if not defined PORT goto :usage
    shift
)
shift
goto :parse
:parsed

if defined SMOKE (
    echo [launch_web] SMOKE: starting web UI headless on port %PORT%, verifying, then exiting.
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$p = Start-Process -FilePath python -ArgumentList 'scripts/web_app.py','--port','%PORT%','--no-browser' -PassThru; " ^
      "Start-Sleep -Seconds 5; " ^
      "try { $r = Invoke-WebRequest -Uri ('http://127.0.0.1:%PORT%/') -UseBasicParsing -TimeoutSec 5; " ^
      "  if ($r.StatusCode -eq 200) { Write-Output ('SMOKE-OK index ' + $r.StatusCode) } else { Write-Output ('SMOKE-FAIL ' + $r.StatusCode) } } " ^
      "catch { Write-Output ('SMOKE-FAIL ' + $_.Exception.Message) } " ^
      "finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }"
    exit /b 0
)

if defined DRY (
    echo [dry] start "MultiAgentCoding Web UI" python scripts/supervisor.py --port %PORT% %NOBROWSER%%NOBROWSER_SPACE%--watch
    exit /b 0
)

echo [launch_web] Starting supervised MultiAgentCoding Web UI at http://localhost:%PORT%
echo [launch_web] Restart via POST /api/restart or scripts\restart_web.ps1
start "MultiAgentCoding Web UI" python scripts/supervisor.py --port %PORT% %NOBROWSER% --watch
exit /b 0

:usage
echo Usage: launch_web.bat [--port N] [--no-browser] [--smoke^|--dry]
echo.
echo   (no args)     Start the supervised web UI (supervisor keeps it alive)
echo   --port N      Listen on port N (default 8501)
echo   --no-browser  Accepted for compatibility (supervisor runs the child headless)
echo   --smoke       Start headless on :8501 and exit (verification)
echo   --dry         Print the launch command without running
exit /b 0