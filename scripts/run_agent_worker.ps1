param(
    [Parameter(Mandatory = $true)]
    [string]$Agent,
    [string]$Title = "",
    [ValidateRange(1, 7)]
    [int]$Slot = 1,
    [switch]$Smoke
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

# --- Resolve agent model from opencode.json ---
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
$Model = $config.agent.$Agent.model
if (-not $Model) {
    Write-Error "Agent '$Agent' has no model configured."
    exit 1
}

# --- Runtime dirs ---
$inbox = Join-Path $ProjectRoot '_inbox'
$done = Join-Path $inbox 'done'
$logs = Join-Path $ProjectRoot '_logs'
New-Item -ItemType Directory -Path $inbox, $done, $logs -Force | Out-Null

$taskFile = Join-Path $inbox "$Agent.task"
$logFile = Join-Path $logs "$Agent.log"
$idleShown = $false

Write-Host "=== MultiAgentCoding: $($Agent) worker ==="
Write-Host "Model : $Model"
Write-Host "Inbox : _inbox\$Agent.task"
Write-Host "Log   : _logs\$Agent.log"
Write-Host ""

while ($true) {
    if (Test-Path $taskFile) {
        $task = (Get-Content -Raw $taskFile).Trim()
        if ($task) {
            $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            $header = "`n[$stamp] ===== TASK RECEIVED ($Agent) =====" + "`n" + $task + "`n========== OUTPUT =========="
            Add-Content -Path $logFile -Value $header -Encoding UTF8
            Write-Host "[$stamp] Running task..."
            $output = & opencode run --agent $Agent -m $Model $task 2>&1 | Out-String
            Add-Content -Path $logFile -Value $output -Encoding UTF8
            $doneName = "$Agent-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.task'
            Move-Item $taskFile (Join-Path $done $doneName) -Force
            $doneStamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
            Add-Content -Path $logFile -Value "`n[$doneStamp] ===== TASK COMPLETE =====`n" -Encoding UTF8
            Write-Host "[$doneStamp] Task done -> _inbox\done\$doneName"
            if ($Smoke) {
                Write-Host "SMOKE: task processed. Exiting."
                [Environment]::Exit(0)
            }
        }
        else {
            Remove-Item $taskFile -Force
        }
    }
    elseif ($Smoke) {
        Write-Host "SMOKE: no task present. Exiting."
        [Environment]::Exit(0)
    }
    elseif (-not $idleShown) {
        Write-Host "Listening for tasks in _inbox\$Agent.task ... (drop a file there to run)"
        $idleShown = $true
    }
    Start-Sleep -Seconds 3
}
