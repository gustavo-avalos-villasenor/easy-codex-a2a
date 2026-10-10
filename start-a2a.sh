#!/usr/bin/env bash
set -euo pipefail

bridge_dir="$(cd -- "$(dirname -- "$0")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Uso: $0 THREAD_ID [PORT] [CONTEXT_ID]" >&2
  exit 64
fi

thread_id="$1"
port="${2:-8766}"
context_id="${3:-}"

if [[ -z "$context_id" ]]; then
  compact_id="${thread_id//-/}"
  context_id="codex-${compact_id:0:12}"
fi

tailscale_ip="$(tailscale ip -4 | head -n 1 | tr -d '[:space:]')"
if [[ -z "$tailscale_ip" ]]; then
  echo "ERROR: tailscale ip -4 did not return an IPv4 address." >&2
  exit 1
fi

base_url="http://${tailscale_ip}:${port}"

cd "$bridge_dir"
exec .venv/bin/python a2a_bridge.py \
  --host "${tailscale_ip}" \
  --port "${port}" \
  --base-url "${base_url}" \
  --thread-id "${thread_id}" \
  --context-id "${context_id}" \
  --timeout 0
