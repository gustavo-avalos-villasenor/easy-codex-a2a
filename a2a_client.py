"""Send one message and wait on one A2A SSE stream until it is complete.

Usage:
    python3 a2a_client.py "message" "http://TAILSCALE-IP:8766"

The client deliberately does not poll GetTask. It sends one
SendStreamingMessage request and keeps that HTTP connection open until the
bridge publishes a terminal task state. The wait therefore does not add a
second timeout to the Codex operation.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Iterator
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def read_agent_card(base_url: str) -> tuple[dict[str, Any], str, str]:
    card_url = base_url + "/.well-known/agent-card.json"
    try:
        with urlopen(card_url, timeout=10) as response:
            card = json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f"Could not read the Agent Card: {exc}") from exc

    description = card.get("description", "")
    marker = "contextId: "
    if marker not in description:
        raise SystemExit("The Agent Card does not announce its dedicated contextId.")
    context_id = description.split(marker, 1)[1].split(";", 1)[0].strip()

    interfaces = card.get("supportedInterfaces", [])
    if not interfaces or not interfaces[0].get("url"):
        raise SystemExit("The Agent Card does not announce a JSON-RPC endpoint.")
    endpoint = interfaces[0]["url"]

    if not card.get("capabilities", {}).get("streaming", False):
        raise SystemExit(
            "This bridge does not advertise streaming; use the async branch of the bridge."
        )
    return card, context_id, endpoint


def sse_events(stream: BinaryIO) -> Iterator[tuple[str, str]]:
    """Yield complete Server-Sent Events from an A2A response body."""

    event_name = "message"
    data_lines: list[str] = []
    for raw_line in stream:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)

    if data_lines:
        yield event_name, "\n".join(data_lines)


def get_field(mapping: dict[str, Any], camel: str, snake: str) -> Any:
    return mapping.get(camel, mapping.get(snake))


def message_text(message: dict[str, Any] | None) -> str:
    if not message:
        return ""
    parts = message.get("parts", message.get("content", []))
    return "\n".join(
        str(part["text"])
        for part in parts
        if isinstance(part, dict) and "text" in part
    )


def result_details(result: dict[str, Any]) -> tuple[str, str, bool]:
    """Return (state, latest text, terminal) from one streamed A2A result."""

    task = result.get("task")
    status_update = get_field(result, "statusUpdate", "status_update")
    artifact_update = get_field(result, "artifactUpdate", "artifact_update")

    status: dict[str, Any] | None = None
    text = ""
    if isinstance(task, dict):
        status = task.get("status")
    if isinstance(status_update, dict):
        status = status_update.get("status", {})
    if isinstance(status, dict):
        text = message_text(get_field(status, "message", "message"))
        state = str(status.get("state", ""))
    else:
        state = ""

    if isinstance(artifact_update, dict):
        artifact = artifact_update.get("artifact", {})
        artifact_parts = artifact.get("parts", []) if isinstance(artifact, dict) else []
        artifact_text = message_text({"parts": artifact_parts})
        if artifact_text:
            text = artifact_text

    normalized = state.upper()
    terminal = normalized in {
        "COMPLETED",
        "FAILED",
        "CANCELED",
        "CANCELLED",
        "REJECTED",
    } or any(
        normalized.endswith("_" + suffix)
        for suffix in ("COMPLETED", "FAILED", "CANCELED", "CANCELLED", "REJECTED")
    )
    return state, text, terminal


def send_and_wait(prompt: str, base_url: str) -> str:
    _, context_id, endpoint = read_agent_card(base_url)
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendStreamingMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "contextId": context_id,
                "parts": [{"text": prompt}],
            }
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
        },
        method="POST",
    )

    # timeout=None is intentional: this is one long-lived wait, not a series
    # of 20-minute status requests. The server's Codex subprocess also has no
    # limit by default, so a long task can finish naturally.
    try:
        with urlopen(request, timeout=None) as response:
            final_text = ""
            for event_name, data in sse_events(response):
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"The bridge sent invalid SSE JSON: {data}") from exc

                if event_name == "error" or "error" in payload:
                    raise SystemExit(
                        "A2A returned an error: "
                        + json.dumps(payload.get("error", payload), ensure_ascii=False)
                    )

                result = payload.get("result", {})
                if not isinstance(result, dict):
                    continue
                state, text, terminal = result_details(result)
                if text:
                    final_text = text
                if terminal:
                    if final_text:
                        print(final_text)
                    normalized_state = state.upper()
                    if any(
                        normalized_state.endswith("_" + suffix)
                        or normalized_state == suffix
                        for suffix in (
                            "FAILED",
                            "CANCELED",
                            "CANCELLED",
                            "REJECTED",
                        )
                    ):
                        raise SystemExit(1)
                    return final_text

            raise SystemExit(
                "The A2A stream closed before a terminal task state was received. "
                "Do not resend automatically; check the bridge before retrying."
            )
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(
            f"Could not complete the A2A streaming request: {exc}. "
            "Do not resend automatically until the task state is checked."
        ) from exc


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    send_and_wait(sys.argv[1], sys.argv[2].rstrip("/"))


if __name__ == "__main__":
    main()
