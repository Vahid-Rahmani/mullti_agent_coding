#!/usr/bin/env bash
set -u
set -o pipefail

usage() {
    cat <<'EOF'
run_agent_worker.sh - Git Bash worker for one MultiAgentCoding agent.

Usage:
  run_agent_worker.sh --agent <name> [options]

Required:
  --agent <name>        Agent name (e.g. matthew, alex)

Options:
  --title <text>        Terminal tab title (default: none)
  --slot <n>            Slot number 1-7 (default: 1)
  --smoke               Process one task then exit (for launcher smoke tests)
  --model-override <m>  Use <m> instead of the agent's configured model (scripts/core/agents specs)
  --workspace <dir>     Run opencode from <dir> instead of the project root
  --dry                 Print resolved configuration and exit (no polling)
  -h, --help            Show this help
EOF
}

ts() { date '+%Y-%m-%d %H:%M:%S'; }

winpath() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1" 2>/dev/null || echo "$1"
    else
        echo "$1"
    fi
}

find_python() {
    local c
    for c in python python3 py; do
        if command -v "$c" >/dev/null 2>&1; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

need_value() {
    if [ $# -lt 2 ]; then
        echo "run_agent_worker.sh: option $1 requires a value" >&2
        exit 2
    fi
}

AGENT=""
TITLE=""
SLOT=1
SMOKE=0
MODEL_OVERRIDE=""
WORKSPACE=""
DRY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --agent) need_value "$@"; AGENT="$2"; shift 2 ;;
        --agent=*) AGENT="${1#--agent=}"; shift ;;
        --title) need_value "$@"; TITLE="$2"; shift 2 ;;
        --title=*) TITLE="${1#--title=}"; shift ;;
        --slot) need_value "$@"; SLOT="$2"; shift 2 ;;
        --slot=*) SLOT="${1#--slot=}"; shift ;;
        --smoke) SMOKE=1; shift ;;
        --model-override) need_value "$@"; MODEL_OVERRIDE="$2"; shift 2 ;;
        --model-override=*) MODEL_OVERRIDE="${1#--model-override=}"; shift ;;
        --workspace) need_value "$@"; WORKSPACE="$2"; shift 2 ;;
        --workspace=*) WORKSPACE="${1#--workspace=}"; shift ;;
        --dry) DRY=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "run_agent_worker.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -z "$AGENT" ]; then
    echo "run_agent_worker.sh: --agent is required" >&2
    usage >&2
    exit 2
fi

case "$SLOT" in
    ''|*[!0-9]*)
        echo "run_agent_worker.sh: --slot must be a number (1-7)" >&2
        exit 2
        ;;
esac
if [ "$SLOT" -lt 1 ] || [ "$SLOT" -gt 7 ]; then
    echo "run_agent_worker.sh: --slot must be between 1 and 7" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"
if [ -z "$SCRIPT_DIR" ]; then
    SCRIPT_DIR="$(pwd)"
fi
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INBOX="$PROJECT_ROOT/_inbox"
DONE_DIR="$INBOX/done"
LOGS_DIR="$PROJECT_ROOT/_logs"
TASK_FILE="$INBOX/$AGENT.task"
LOG_FILE="$LOGS_DIR/$AGENT.log"

PY="$(find_python)"
if [ -z "$PY" ]; then
    echo "ERROR: python not found; cannot resolve agent model from scripts/core/agents specs" >&2
    exit 1
fi

# The canonical agent specs in scripts/core/agents/ are the single source of
# truth for each agent's model; opencode.json is no longer parsed here.
if [ -n "$MODEL_OVERRIDE" ]; then
    MODEL="$MODEL_OVERRIDE"
else
    MODEL_RESULT="$(cd "$PROJECT_ROOT" && "$PY" -m scripts.core.agents model "$AGENT" 2>&1)"
    RC=$?
    if [ "$RC" -ne 0 ] || [ -z "$MODEL_RESULT" ]; then
        echo "ERROR: $MODEL_RESULT" >&2
        exit 1
    fi
    MODEL="$MODEL_RESULT"
fi

mkdir -p "$DONE_DIR" "$LOGS_DIR"

# --- Optional TLS bypass for opencode (strictly opt-in) ---
# Environments with self-signed or intercepting certificates (antivirus/EDR
# web filters, corporate proxies) can set ZOVA_ALLOW_INSECURE_TLS=1 to run
# opencode with NODE_TLS_REJECT_UNAUTHORIZED=0. Default keeps verification on.
case "${ZOVA_ALLOW_INSECURE_TLS:-}" in
    1|true|TRUE|yes|YES)
        export NODE_TLS_REJECT_UNAUTHORIZED=0
        echo "Insecure TLS : ON (ZOVA_ALLOW_INSECURE_TLS=${ZOVA_ALLOW_INSECURE_TLS}) - opencode cert verification disabled"
        ;;
esac

if [ -n "$TITLE" ] && [ -t 1 ]; then
    printf '\033]0;%s\007' "$TITLE"
fi

echo "=== MultiAgentCoding: $AGENT worker (Git Bash) ==="
echo "Model : $MODEL"
echo "Inbox : $TASK_FILE"
echo "Log   : $LOG_FILE"

if [ "$DRY" -eq 1 ]; then
    echo "Dry run: configuration OK (agent=$AGENT model=$MODEL slot=$SLOT smoke=$SMOKE workspace=${WORKSPACE:-<project root>})"
    exit 0
fi

idle_shown=0
while true; do
    if [ -f "$TASK_FILE" ]; then
        task="$(<"$TASK_FILE")"
        task="${task//$'\r'/}"
        task="$(printf '%s' "$task" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        if [ -n "$task" ]; then
            stamp="$(ts)"
            echo ""
            echo "[$stamp] TASK RECEIVED ($AGENT)"
            echo "----------------------------------------"
            printf '%s\n' "$task"
            echo "----------------------------------------"
            {
                echo ""
                echo "[$stamp] TASK RECEIVED ($AGENT)"
                echo "$task"
            } >> "$LOG_FILE"

            cmd=(opencode run --agent "$AGENT" --auto -m "$MODEL")
            if [[ "$task" == -* ]]; then
                cmd+=(--)
            fi
            cmd+=("$task")

            start="$(date +%s)"
            if [ -n "$WORKSPACE" ]; then
                pushd "$WORKSPACE" >/dev/null 2>&1 || echo "WARNING: cannot enter workspace: $WORKSPACE" >&2
            fi
            "${cmd[@]}" 2>&1 | tee -a "$LOG_FILE"
            rc=${PIPESTATUS[0]}
            if [ -n "$WORKSPACE" ]; then
                popd >/dev/null 2>&1 || true
            fi
            end="$(date +%s)"
            duration=$(( end - start ))

            ok=0
            [ "$rc" -ne 0 ] && ok=1

            done_name="$AGENT-$(date +%Y%m%d-%H%M%S).task"
            mv "$TASK_FILE" "$DONE_DIR/$done_name"

            echo "[$(ts)] TASK COMPLETE (ok=$ok)"
            echo "[$(ts)] TASK COMPLETE (ok=$ok)" >> "$LOG_FILE"

            if [ "$SMOKE" -eq 1 ]; then
                echo "SMOKE: task processed. Exiting."
                exit 0
            fi
        else
            rm -f "$TASK_FILE"
        fi
    elif [ "$SMOKE" -eq 1 ]; then
        echo "SMOKE: no task present. Exiting."
        exit 0
    elif [ "$idle_shown" -eq 0 ]; then
        echo "Listening for tasks in $TASK_FILE ... (drop a file there to run)"
        idle_shown=1
    fi
    sleep 3
done
