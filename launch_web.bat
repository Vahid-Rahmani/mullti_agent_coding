@echo off
setlocal
cd /d "%~dp0"

set "PORT=8501"
for %%A in (%*) do (
    if /i "%%~A"=="--help" goto :usage
    if /i "%%~A"=="-h" goto :usage
    if /i "%%~A"=="--no-browser" set "NOBROWSER=1"
    if /i "%%~A"=="--dry" set "DRY=1"
    if /i "%%~A"=="--smoke" set "SMOKE=1"
)

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
    echo [dry] start "MultiAgentCoding Web UI" python scripts/web_app.py --port %PORT% %NOBROWSER%
    exit /b 0
)

echo [launch_web] Starting MultiAgentCoding Web UI at http://localhost:%PORT%
if defined NOBROWSER (
    python scripts/web_app.py --port %PORT% --no-browser
) else (
    start "MultiAgentCoding Web UI" python scripts/web_app.py --port %PORT%
)
exit /b 0

:usage
echo Usage: launch_web.bat [--port N] [--no-browser] [--smoke^|--dry]
echo.
echo   (no args)     Start the web UI and open the default browser
echo   --port N      Listen on port N (default 8501)
echo   --no-browser  Do not open the browser
echo   --smoke       Start headless on :8501 and exit (verification)
echo   --dry         Print the launch command without running
exit /b 0