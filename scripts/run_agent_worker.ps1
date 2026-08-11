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

# --- Optional TLS bypass for opencode (strictly opt-in) ---
# Environments with self-signed or intercepting certificates (antivirus/EDR
# web filters, corporate proxies) can set ZOVA_ALLOW_INSECURE_TLS=1 to run
# opencode with NODE_TLS_REJECT_UNAUTHORIZED=0. Default keeps verification on.
if ($env:ZOVA_ALLOW_INSECURE_TLS -match '^(1|true|yes)$') {
    $env:NODE_TLS_REJECT_UNAUTHORIZED = '0'
    Write-Host "Insecure TLS : ON (ZOVA_ALLOW_INSECURE_TLS=$env:ZOVA_ALLOW_INSECURE_TLS) - opencode cert verification disabled"
}

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

# --- Resolve agent model from the canonical specs (unless overridden) ---
# scripts/core/agents/ is the single source of truth for the roster and each
# agent's configured model; opencode.json is no longer parsed by the launcher.
function Invoke-AgentsCli {
    param([string[]]$CliArgs)
    Push-Location $ProjectRoot
    try {
        & python -m scripts.core.agents @CliArgs 2>&1
    }
    finally {
        Pop-Location
    }
}
# Trim each captured line: Windows PowerShell keeps a trailing "\r" on
# native-command output, which would otherwise break -notcontains matching
# and leak into the model string passed to `opencode run -m`.
$validAgents = @((Invoke-AgentsCli @('list')) | ForEach-Object { $_.Trim() })
if ($validAgents -notcontains $Agent) {
    Write-Error "Unknown agent '$Agent'. Valid agents: $($validAgents -join ', ')"
    exit 1
}
function Get-AgentModel([string]$AgentName) {
    $m = (Invoke-AgentsCli @('model', $AgentName) | Select-Object -First 1).Trim()
    return $m
}
if (-not $ModelOverride) {
    $ModelOverride = Get-AgentModel $Agent
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

function ConvertTo-SafeTask {
    param([string]$Text)
    if (-not $Text) { return "" }
    # Never pass raw task text to a Windows shell: collapse to one line, strip
    # control characters, and replace embedded double quotes (PowerShell 5.1
    # does not escape them when forwarding native arguments, which causes
    # 'exit code 1' shell parsing errors).
    $Text = $Text -replace "`r`n", " " -replace "`r", " " -replace "`n", " "
    $Text = $Text -replace '"', [char]0x201D
    $Text = $Text -replace '[\x00-\x1F]', ' '
    return ($Text -replace ' {2,}', ' ').Trim()
}

function Invoke-AgentRun {
    param(
        [string]$TaskPath,
        [string]$ExecAgent,
        [string]$ExecLog,
        [string]$ExecModel
    )
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $task = (Get-Content -Raw $TaskPath).Trim()
    $header = "`n[$stamp] ===== TASK RECEIVED ($ExecAgent) =====" + "`n" + $task + "`n========== OUTPUT =========="
    Add-Content -Path $ExecLog -Value $header -Encoding UTF8
    Write-Host "[$stamp] Running task..."
    if ($Workspace) { Push-Location $Workspace }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $ok = $true
    try {
        $fullPrompt = ConvertTo-SafeTask $task
        # Direct invocation with array splatting (never a shell string) keeps
        # spaces and hyphens intact; `--` ends option parsing so a dash-leading
        # prompt is a message, not a flag (prevents exit code 1 parse errors);
        # ConvertTo-SafeTask strips embedded quotes/control chars.
        $opencodeArgs = @('run', '--agent', $ExecAgent, '--auto', '-m', $ExecModel)
        if ($fullPrompt.StartsWith('-')) { $opencodeArgs += '--' }
        $opencodeArgs += $fullPrompt
        if (-not $fullPrompt) {
            $ok = $false
            $msg = "ERROR: task empty after sanitization; skipping run."
            Add-Content -Path $ExecLog -Value $msg -Encoding UTF8
            Write-Host $msg
        }
        else {
            & opencode @opencodeArgs 2>&1 | ForEach-Object {
                Add-Content -Path $ExecLog -Value "$_" -Encoding UTF8
                Write-Host $_
            }
            if ($LASTEXITCODE -ne 0) {
                $ok = $false
                $err = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] opencode exit code $LASTEXITCODE (logged; loop continues)"
                Add-Content -Path $ExecLog -Value $err -Encoding UTF8
                Write-Host $err
            }
        }
    }
    catch {
        $ok = $false
        $msg = "ERROR: $($_.Exception.Message)"
        Add-Content -Path $ExecLog -Value $msg -Encoding UTF8
        Write-Host $msg
    }
    finally {
        if ($Workspace) { Pop-Location }
    }
    $sw.Stop()

    $doneStamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $ExecLog -Value "`n[$doneStamp] ==== TASK COMPLETE (ok=$ok) =====" -Encoding UTF8
    $doneName = "$ExecAgent-$(Get-Date -Format 'yyyyMMdd-HHmmss').task"
    if (Test-Path $TaskPath) { Move-Item $TaskPath (Join-Path $done $doneName) -Force }
    Write-Host "[$doneStamp] Task done -> _inbox\done\$doneName"
    return $ok
}

Write-Host "=== MultiAgentCoding: $Agent worker ==="
Write-Host "Model : $ModelOverride"
Write-Host "Inbox : $TaskFile"
Write-Host "Log   : $LogFile"
Write-Host ""

while ($true) {
    if (Test-Path $TaskFile) {
        $task = (Get-Content -Raw $TaskFile).Trim()
        if ($task) {
            if ($Title) { $host.UI.RawUI.WindowTitle = "$Title - working" }
            Invoke-AgentRun -TaskPath $TaskFile -ExecAgent $RunAgent -ExecLog $LogFile -ExecModel $ModelOverride
            if ($Title) { $host.UI.RawUI.WindowTitle = $Title }
            if ($Smoke) {
                Write-Host "SMOKE: Task processed. Exiting."
                [Environment]::Exit(0)
            }
        }
        else {
            Remove-Item $TaskFile -Force
        }
    }
    if (-not $idleShown) {
        $idleShown = $true
        Write-Host "Listening for tasks in $TaskFile ... (drop a file there to run)"
    }
    Start-Sleep -Seconds 3
}
