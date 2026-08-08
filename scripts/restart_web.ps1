<#
.SYNOPSIS
    One-shot manual restart request for the supervised MultiAgentCoding web UI.

.DESCRIPTION
    Restarts the running web app (scripts/web_app.py) under its supervisor
    (scripts/supervisor.py):

      1. Writes a restart marker (_logs/restart.ctl) so the supervisor knows a
         restart is requested.
      2. Calls POST /api/restart on the running web app, which records the
         restart in state.md and schedules a clean exit.
      3. If a supervisor is already running (e.g. started by launch_web.bat) it
         picks up the marker itself and this script does nothing more. If no
         supervisor is running, one is started detached (--watch) so the app
         comes back up verified and stays supervised; the script itself returns
         immediately.

.PARAMETER Port
    Port the web UI listens on (default 8501).

.PARAMETER Reason
    Reason recorded in the restart marker (default "operator request").

.PARAMETER Root
    Project root to operate on (default: repo root = parent of scripts/).
    Overridable so operators/tests can target another checkout.
#>
param(
    [int]$Port = 8501,
    [string]$Reason = "operator request",
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"

# 1. Write the restart marker the supervisor watches.
$markerDir = Join-Path $Root "_logs"
New-Item -ItemType Directory -Force -Path $markerDir | Out-Null
$marker = Join-Path $markerDir "restart.ctl"
$payload = @{
    source = "manual"
    reason = $Reason
    ok     = $true
    ts     = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
# UTF-8 WITHOUT BOM: PowerShell 5.1 Set-Content -Encoding utf8 would add a BOM
# that makes SelfEvolveEngine.verify() fail to parse the marker JSON.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($marker, $payload, $utf8NoBom)
Write-Output "restart_web: wrote restart marker $marker"

# 2. Ask the running web app to exit (best-effort). POST /api/restart records
#    the restart in state.md and schedules a clean exit; the supervisor then
#    picks up the marker.
try {
    $body = @{ reason = $Reason } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/restart" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 5
    Write-Output "restart_web: web app on :$Port accepted restart ($($resp.restart))"
} catch {
    Write-Output "restart_web: no running web app on :$Port (marker written; will start supervisor)"
}

# 3. If a supervisor is already watching the web app it will verify + relaunch.
#    Otherwise start a detached supervisor (--watch) that verifies and relaunches
#    the child. Running it detached means the app stays supervised while this
#    operator script returns immediately instead of blocking on the child.
$supervisorRunning = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*supervisor.py*" })
if ($supervisorRunning.Count -gt 0) {
    Write-Output "restart_web: supervisor already running; it will verify + relaunch"
} else {
    Write-Output "restart_web: starting detached supervisor (verify + relaunch)"
    $supervisorPy = Join-Path $Root "scripts\supervisor.py"
    Start-Process -FilePath "python" -ArgumentList @($supervisorPy, "--port", "$Port", "--watch") -WindowStyle Hidden
}
}