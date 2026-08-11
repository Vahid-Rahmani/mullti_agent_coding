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
    [string]$Workspace = "",
    # --- Dynamic Swarm Role-Swapping & Peer-Assistance protocol ---
    [int]$StaleSeconds = 20,       # peer task unclaimed this long => lagging
    [int]$MaxHelpers = 3,          # max helper takeovers per duty cycle
    [int]$HelpCoolDown = 15,       # seconds to wait before re-checking for lagging peers
    [switch]$NoSwarm,              # disable role rotation / helper mode
    [switch]$NoBrief              # disable inter-agent brief injection
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
$validAgents = @(Invoke-AgentsCli @('list'))
if ($validAgents -notcontains $Agent) {
    Write-Error "Unknown agent '$Agent'. Valid agents: $($validAgents -join ', ')"
    exit 1
}
function Get-AgentModel([string]$AgentName) {
    $m = @((Invoke-AgentsCli @('model', $AgentName) | Select-Object -First 1))
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
$swarmDir = Join-Path $logs 'swarm'
$feedbackFile = Join-Path $logs 'swarm_feedback.jsonl'
$swarmScript = Join-Path $ProjectRoot 'scripts\swarm.py'

$RunAgent = if ($AgentOverride) { $AgentOverride } else { $Agent }
$idleShown = $false

# ==================== swarm helpers ====================

function Set-TabTitle {
    param([string]$TitleText, [string]$Status, [int]$Target)
    # Dynamic tab renaming: the window title always reflects the current
    # cooperative role and assistance target in real time.
    $host.UI.RawUI.WindowTitle = $TitleText
    $payload = @{ status = $Status; title = $TitleText; target = $Target }
    $json = $payload | ConvertTo-Json -Compress
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    try { & python $swarmScript 'state' --swarm $swarmDir --slot $Slot --json-b64 $b64 | Out-Null } catch { }
}

function Add-Feedback {
    param([string]$Mode, [bool]$Ok, [double]$Duration, [string]$TaskText, [int]$Target = 0)
    $record = @{
        slot = $Slot; agent = $Agent
        mode = $Mode; ok = $Ok
        duration = $Duration; task = $TaskText
    }
    if ($Target -gt 0) { $record.target = $Target }
    $json = $record | ConvertTo-Json -Compress
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    try { & python $swarmScript 'feedback' '--file' $feedbackFile '--json-b64' $b64 | Out-Null } catch { }
}

function Get-SwarmBrief {
    param([string]$PeerAgent = "")
    if ($NoBrief) { return '' }
    $out = (& python $swarmScript 'brief' '--file' $feedbackFile '--swarm' $swarmDir '--own' $PeerAgent 2>&1)
    return ($out -join "`n")
}

function Invoke-AgentRun {
    param(
        [string]$TaskPath,
        [string]$ExecAgent,
        [string]$ExecLog,
        [string]$ExecModel,
        [string]$Mode,
        [int]$HelperTarget = 0,
        [string]$Brief = ""
    )
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $task = (Get-Content -Raw $TaskPath).Trim()
    $roleLine = if ($HelperTarget -gt 0) { "helper for M$HelperTarget" } else { "primary role" }
    $header = "`n[$stamp] ===== TASK RECEIVED ($ExecAgent / $roleLine) =====" + "`n" + $task + "`n========== OUTPUT =========="
    Add-Content -Path $ExecLog -Value $header -Encoding UTF8
    Write-Host "[$stamp] Running task ($Mode)..."
    if ($Workspace) { Push-Location $Workspace }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $ok = $true
    try {
        $fullPrompt = ConvertTo-SafeTask $task
        if ($Brief) {
            $briefLine = ConvertTo-SafeTask $Brief
            $fullPrompt = "SWARM CONTEXT (learn from recent cycles):`n$briefLine`n`n$fullPrompt"
        }
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
                $err = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] opencode exit code $LASTEXITCODE (logged; swarm loop continues)"
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

    Add-Feedback -Mode $Mode -Ok $ok -Duration $sw.Elapsed.TotalSeconds -TaskText $task -Target $HelperTarget

    $doneStamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $ExecLog -Value "`n[$doneStamp] ==== TASK COMPLETE (ok=$ok) =====" -Encoding UTF8
    $doneName = "$ExecAgent-$(Get-Date -Format 'yyyyMMdd-HHmmss').task"
    if (Test-Path $TaskPath) { Move-Item $TaskPath (Join-Path $done $doneName) -Force }
    Write-Host "[$doneStamp] Task done -> _inbox\done\$doneName"
    return $ok
}

# ==================== main loop ====================

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

Write-Host "=== MultiAgentCoding: $Agent worker ==="
Write-Host "Model : $ModelOverride"
Write-Host "Inbox : $TaskFile"
Write-Host "Log   : $LogFile"
if ($NoSwarm) {
    Write-Host "Swarm : OFF (helper rotation disabled)"
} else {
    Write-Host "Swarm : ON (stale=$StaleSeconds s, max=$MaxHelpers helpers, cooldown=$HelpCoolDown s)"
}
Write-Host ""

$nextSwarmCheck = (Get-Date).AddSeconds(-1)   # allow an immediate first check
$swarmDoneInCycle = 0

while ($true) {
    # ---------- 1. own task (primary role) ----------
    if (Test-Path $TaskFile) {
        $task = (Get-Content -Raw $TaskFile).Trim()
        if ($task) {
            Set-TabTitle -TitleText $Title -Status 'working' -Target 0
            $brief = Get-SwarmBrief -PeerAgent $Agent
            Invoke-AgentRun -TaskPath $TaskFile -ExecAgent $RunAgent -ExecLog $LogFile -ExecModel $ModelOverride -Mode 'own' -Brief $brief
            Set-TabTitle -TitleText $Title -Status 'idle' -Target 0
            $nextSwarmCheck = (Get-Date).AddSeconds(-1)   # freshen duty cycle
            $swarmDoneInCycle = 0
            if ($Smoke) {
                Write-Host "SMOKE: Task processed. Exiting."
                [Environment]::Exit(0)
            }
        }
        else {
            Remove-Item $TaskFile -Force
        }
    }
    # ---------- 2. SWARM HELPER: take over lagging peers ----------
    elseif (-not $NoSwarm -and -not $Smoke -and ((Get-Date) -gt $nextSwarmCheck)) {
        $staleJson = (& python $swarmScript 'find-stale' '--inbox' $inbox '--own' $Agent '--stale' [string]$StaleSeconds 2>&1) -join ''
        try { $staleList = $staleJson | ConvertFrom-Json } catch { $staleList = @() }
        if ($staleList -and $staleList.Count -gt 0 -and $swarmDoneInCycle -lt $MaxHelpers) {
            $peer = $staleList[0]
            $peerAgent = [string]$peer.agent
            $peerSlot = [int]$peer.slot

            # Role rotation on completion: this tab becomes a Swarm Helper -> M<peer>
            $helperTitle = "M$Slot-Helper->M$peerSlot"
            Set-TabTitle -TitleText $helperTitle -Status 'helper' -Target $peerSlot
            Write-Host ""
            Write-Host "[swarm] M$Slot => helper for lagging $peerAgent (stale $($peer.age)s) -> claiming"
            $b = [System.Text.StringBuilder]::new()
            (& python $swarmScript 'claim' '--inbox' $inbox '--agent' $peerAgent '--by' [string]$Slot 2>&1) | ForEach-Object { [void]$b.AppendLine("$_") }
            $claimed = $b.ToString().Trim()
            if ($claimed -and $claimed -ne 'NONE') {
                $peerModel = Get-AgentModel $peerAgent
                if (-not $peerModel) { $peerModel = $ModelOverride }
                $peerLog = Join-Path $logs "$peerAgent.log"
                $brief = Get-SwarmBrief -PeerAgent $peerAgent
                Invoke-AgentRun -TaskPath $claimed -ExecAgent $peerAgent -ExecLog $peerLog -ExecModel $peerModel -Mode 'helper' -HelperTarget $peerSlot -Brief $brief
                $swarmDoneInCycle++
                continue   # stay in helper duty cycle; grab the next lagging peer
            }
            else {
                Write-Host "[swarm] claim lost to another helper; retrying next cycle"
                $nextSwarmCheck = (Get-Date).AddSeconds($HelpCoolDown)
            }
        }
        else {
            $nextSwarmCheck = (Get-Date).AddSeconds($HelpCoolDown)
        }
    }

    if (-not $idleShown) {
        $idleShown = $true
        Set-TabTitle -TitleText $Title -Status 'idle' -Target 0 | Out-Null
        Write-Host "Listening for tasks in $TaskFile ... (drop a file there to run)"
    }
    Start-Sleep -Seconds 3
}