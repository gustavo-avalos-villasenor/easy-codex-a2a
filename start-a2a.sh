#!/usr/bin/env bash
set -euo pipefail

thread_id="${1:?Uso: $0 THREAD_ID [PORT] [CONTEXT_ID]}"
port="${2:-8766}"
context_id="${3:-codex-${thread_id//-/}}"
tailscale_ip="$(tailscale ip -4 | head -n 1)"
base_url="http://${tailscale_ip}:${port}"

exec .venv/bin/python a2a_bridge.py \
  --host "${tailscale_ip}" \
  --port "${port}" \
  --base-url "${base_url}" \
  --thread-id "${thread_id}" \
  --context-id "${context_id}"
