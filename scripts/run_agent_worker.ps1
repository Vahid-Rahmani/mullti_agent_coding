param(
    [Parameter(Mandatory = $true)]
    [string]$Agent,
    [string]$Title = "",
    [ValidateRange(1, 7)]
    [int]$Slot = 1,
    [switch]$Smoke,
    [string]$ModelOverride = "",
    [string]$AgentOverride = "",
    [string]$TaskFile = "",
    [string]$LogFile = "",
    [string]$Workspace = ""
)

$ErrorActionPreference = 'Continue'

$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ($Title) {
    $host.UI.RawUI.WindowTitle = $Title
    try { $host.UI.RawUI.ForegroundColor = 'White' } catch { }
}

# --- 4x2 grid window placement via user32 ---
Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class AgentWindowNative {
    [DllImport("kernel32.dll")]
    public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
}
"@

try {
    $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $margin = 8
    $gap = 8
    $cols = 4
    $rows = 2
    $winW = [int](($wa.Width - ($margin * 2) - ($gap * ($cols - 1))) / $cols)
    $winH = [int](($wa.Height - ($margin * 2) - ($gap * ($rows - 1))) / $rows)
    $col = ($Slot - 1) % $cols
    $row = [int](($Slot - 1) / $cols)
    $x = $margin + $col * ($winW + $gap)
    $y = $margin + $row * ($winH + $gap)
    $hwnd = [AgentWindowNative]::GetConsoleWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        [AgentWindowNative]::MoveWindow($hwnd, $x, $y, $winW, $winH, $true) | Out-Null
    }
}
catch {
    Write-Host "Warning: window placement skipped ($($_.Exception.Message))"
}

# --- Resolve agent model from opencode.json (unless overridden) ---
$configPath = Join-Path $ProjectRoot 'opencode.json'
if (-not (Test-Path $configPath)) {
    Write-Error "opencode.json not found at $configPath"
    exit 1
}
$config = Get-Content $configPath -Raw | ConvertFrom-Json
if (-not $config.agent.PSObject.Properties[$Agent]) {
    Write-Error "Unknown agent '$Agent'. Valid agents: $($config.agent.PSObject.Properties.Name -join ', ')"
    exit 1
}
if (-not $ModelOverride) {
    $ModelOverride = $config.agent.$Agent.model
}
if (-not $ModelOverride) {
    Write-Error "Agent '$Agent' has no model configured."
    exit 1
}

# --- Runtime dirs ---
$inbox = Join-Path $ProjectRoot '_inbox'
$done = Join-Path $inbox 'done'
$logs = Join-Path $ProjectRoot '_logs'
New-Item -ItemType Directory -Path $inbox, $done, $logs -Force | Out-Null

if (-not $TaskFile) { $TaskFile = Join-Path $inbox "$Agent.task" }
if (-not $LogFile) { $LogFile = Join-Path $logs "$Agent.log" }

$RunAgent = if ($AgentOverride) { $AgentOverride } else { $Agent }
$idleShown = $false

Write-Host "=== MultiAgentCoding: $($Agent) worker ==="
Write-Host "Model : $ModelOverride"
Write-Host "Inbox : $TaskFile"
Write-Host "Log   : $LogFile"
Write-Host ""

while ($true) {
    if (Test-Path $TaskFile) {
        $task = (Get-Content -Raw $TaskFile).Trim()
        if ($task) {
            $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            $header = "`n[$stamp] ===== TASK RECEIVED ($Agent) =====" + "`n" + $task + "`n========== OUTPUT =========="
            Add-Content -Path $LogFile -Value $header -Encoding UTF8
            Write-Host "[$stamp] Running task..."
            if ($Workspace) { Push-Location $Workspace }
            try {
                # Stream output line-by-line so the web UI can tail in real-time.
                & opencode run --agent $RunAgent --auto -m $ModelOverride $task 2>&1 | ForEach-Object {
                    Add-Content -Path $LogFile -Value "$_" -Encoding UTF8
                    Write-Host $_
                }
            }
            finally {
                if ($Workspace) { Pop-Location }
            }
            $doneName = "$Agent-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.task'
            Move-Item $TaskFile (Join-Path $done $doneName) -Force
            $doneStamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            Add-Content -Path $LogFile -Value "`n[$doneStamp] ===== TASK COMPLETE =====" -Encoding UTF8
            Write-Host "[$doneStamp] Task done -> _inbox\done\$doneName"
            if ($Smoke) {
                Write-Host "SMOKE: task processed. Exiting."
                [Environment]::Exit(0)
            }
        }
        else {
            Remove-Item $TaskFile -Force
        }
    }
    elseif ($Smoke) {
        Write-Host "SMOKE: no task present. Exiting."
        [Environment]::Exit(0)
    }
    elseif (-not $idleShown) {
        Write-Host "Listening for tasks in $TaskFile ... (drop a file there to run)"
        $idleShown = $true
    }
    Start-Sleep -Seconds 3
}