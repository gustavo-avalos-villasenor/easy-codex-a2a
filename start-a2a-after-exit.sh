#!/usr/bin/env bash
set -euo pipefail

# Run this from a normal shell after exiting the interactive Codex session.
# The thread UUID is intentionally required so this script cannot silently
# attach to a different conversation.

BRIDGE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 THREAD_ID [PORT] [CONTEXT_ID]" >&2
    echo "Pass the UUID of the current Codex conversation explicitly." >&2
    exit 64
fi

THREAD_ID="$1"
PORT="8766"
if [[ $# -ge 2 ]]; then
    PORT="$2"
fi

CONTEXT_ID=""
if [[ $# -ge 3 ]]; then
    CONTEXT_ID="$3"
fi
if [[ -z "$CONTEXT_ID" ]]; then
    compact_id="$(printf '%s' "$THREAD_ID" | tr -d '-')"
    CONTEXT_ID="codex-$(printf '%s' "$compact_id" | cut -c1-12)"
fi

if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: codex is not in PATH." >&2
    exit 1
fi
if ! command -v tailscale >/dev/null 2>&1; then
    echo "ERROR: tailscale is not in PATH." >&2
    exit 1
fi
if ! command -v lsof >/dev/null 2>&1; then
    echo "ERROR: lsof is required to inspect the lock safely." >&2
    exit 1
fi

codex_home="$(printenv CODEX_HOME 2>/dev/null || true)"
if [[ -z "$codex_home" ]]; then
    codex_home="$HOME/.codex"
fi
lock_path="$codex_home/thread-writer-locks/$THREAD_ID.lock"

interactive="$(ps -u "$(id -u)" -o pid=,args= | awk '
    $0 ~ /(^| )node \/usr\/bin\/codex$/ ||
    $0 ~ /(^| )\/usr\/bin\/node \/usr\/bin\/codex$/ {print}
')"
if [[ -n "$interactive" ]]; then
    echo "ERROR: an interactive Codex process is still open:" >&2
    echo "$interactive" >&2
    echo "Type /exit in that interface and run this script again." >&2
    exit 2
fi

tailscale_ip="$(tailscale ip -4 | head -n 1 | tr -d '[:space:]')"
if [[ -z "$tailscale_ip" ]]; then
    echo "ERROR: Tailscale did not return an IPv4 address." >&2
    exit 1
fi

echo "Thread:     $THREAD_ID"
echo "Tailscale:  $tailscale_ip"
echo "Context ID: $CONTEXT_ID"

if command -v timeout >/dev/null 2>&1; then
    timeout 12s codex app-server daemon stop >/dev/null 2>&1 || true
else
    codex app-server daemon stop >/dev/null 2>&1 || true
fi

holders="$(lsof -t -- "$lock_path" 2>/dev/null || true)"
if [[ -n "$holders" ]]; then
    while read -r pid; do
        [[ "$pid" =~ ^[0-9]+$ ]] || continue
        args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
        case "$args" in
            *"codex app-server --"*"--managed-daemon"*|*"codex app-server daemon pid-update-loop"*)
                echo "Requesting graceful shutdown of app-server PID $pid..."
                kill -TERM "$pid" 2>/dev/null || true
                ;;
            *)
                echo "ERROR: the lock is held by an unrecognized process:" >&2
                echo "  PID $pid: $args" >&2
                echo "The process was not stopped and the lock was not deleted." >&2
                exit 3
                ;;
        esac
    done <<< "$holders"
fi

for _ in $(seq 1 40); do
    current="$(lsof -t -- "$lock_path" 2>/dev/null || true)"
    if [[ -z "$current" ]]; then
        break
    fi
    sleep 0.25
done

current="$(lsof -t -- "$lock_path" 2>/dev/null || true)"
if [[ -n "$current" ]]; then
    echo "ERROR: the lock is still held by PID(s): $current" >&2
    echo "Do not delete the lock file; inspect those processes first." >&2
    exit 4
fi

base_url="http://$tailscale_ip:$PORT"
card_url="$base_url/.well-known/agent-card.json"

if curl --fail --max-time 3 -sS "$card_url" >/dev/null 2>&1; then
    echo "ERROR: a bridge is already listening at $base_url." >&2
    echo "Stop that process before starting another bridge." >&2
    exit 5
fi

echo
echo "================ A2A connection instructions ================"
echo "Repository:      https://github.com/gustavo-avalos-villasenor/easy-codex-a2a"
echo "Agent Card:      $card_url"
echo "JSON-RPC URL:    $base_url/"
echo "A2A context ID:  $CONTEXT_ID"
echo
echo "Copy the following message to the remote agent:"
cat <<EOF
Clone and read this repository:
https://github.com/gustavo-avalos-villasenor/easy-codex-a2a
The default main branch already contains the asynchronous callback workflow.

The bridge is serving the existing Codex conversation. Do not create a new
conversation. First read this Agent Card:
$card_url

Use the endpoint and contextId announced by the Agent Card. For work that may
take a long time, obtain the remote agent's own current Codex conversation UUID
and use callback mode:
python3 a2a_client.py --submit-and-resume "Long task" "$base_url" "CLIENT-CODEX-CONVERSATION-UUID"

This sends SendMessage(returnImmediately=true), starts a detached watcher, and
returns immediately. The watcher uses one SubscribeToTask connection outside
the model turn, then resumes the remote Codex conversation once when the task
finishes. It does not poll GetTask. Do not run --wait or resubmit the same
message. The remote conversation must be closed after submission so its writer
lock is available; the watcher retries if it is still active.

If the remote agent cannot resume its own Codex conversation, use the portable
task-ID mode instead:
python3 a2a_client.py --submit "Long task" "$base_url"
python3 a2a_client.py --wait "TASK-ID-FROM-SUBMIT" "$base_url"

For a normal one-connection request:
python3 a2a_client.py "Hello. Please confirm that you received this message." "$base_url"
EOF
echo "=============================================================="
echo
echo "A2A bridge in foreground: $base_url"
echo "The process will remain in standby waiting for requests."
echo "Press Ctrl+C in this terminal to stop it."
echo

cd "$BRIDGE_DIR"
exec .venv/bin/python a2a_bridge.py --host "$tailscale_ip" --port "$PORT" --base-url "$base_url" --thread-id "$THREAD_ID" --context-id "$CONTEXT_ID" --timeout 0
