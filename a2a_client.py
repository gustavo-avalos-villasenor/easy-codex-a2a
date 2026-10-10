"""Submit or follow one long-running A2A task without polling.

Usage:
    python3 a2a_client.py "message" "http://TAILSCALE-IP:8766"
    python3 a2a_client.py --submit "message" "http://TAILSCALE-IP:8766"
    python3 a2a_client.py --wait TASK_ID "http://TAILSCALE-IP:8766"

The default form follows the task on one SSE connection until completion.
Use --submit when the caller must return immediately: the bridge keeps the
task running after this process exits, and --wait can attach later by taskId.
Neither mode polls GetTask. GetTask is used only once as a race-safe fallback
when a task has already finished before a subscription is attached.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Iterator
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class A2AProtocolError(RuntimeError):
    """The server returned a JSON-RPC or task-stream error."""


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
            "This bridge does not advertise streaming; use the durable async branch."
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
    """Return (state, latest text, terminal) from one A2A result."""

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
        text = message_text(status.get("message"))
        state = str(status.get("state", ""))
    else:
        state = ""

    if isinstance(artifact_update, dict):
        artifact = artifact_update.get("artifact", {})
        artifact_parts = (
            artifact.get("parts", []) if isinstance(artifact, dict) else []
        )
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


def is_failure_state(state: str) -> bool:
    normalized = state.upper()
    return any(
        normalized == suffix or normalized.endswith("_" + suffix)
        for suffix in ("FAILED", "CANCELED", "CANCELLED", "REJECTED")
    )


def rpc_request(
    endpoint: str,
    method: str,
    params: dict[str, Any],
    timeout: float | None,
) -> dict[str, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    request = Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f"Could not complete A2A {method}: {exc}") from exc

    if "error" in payload:
        raise A2AProtocolError(
            json.dumps(payload["error"], ensure_ascii=False)
        )
    return payload


def message_params(prompt: str, context_id: str) -> dict[str, Any]:
    return {
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "contextId": context_id,
            "parts": [{"text": prompt}],
        }
    }


def submit(prompt: str, base_url: str) -> str:
    _, context_id, endpoint = read_agent_card(base_url)
    params = message_params(prompt, context_id)
    params["configuration"] = {"returnImmediately": True}
    try:
        payload = rpc_request(endpoint, "SendMessage", params, timeout=30)
    except A2AProtocolError as exc:
        raise SystemExit(f"A2A rejected the task: {exc}") from exc

    task = payload.get("result", {}).get("task")
    if not isinstance(task, dict) or not task.get("id"):
        raise SystemExit("The bridge did not return a taskId for the submitted work.")

    task_id = str(task["id"])
    result = {
        "taskId": task_id,
        "contextId": task.get("contextId", context_id),
        "state": task.get("status", {}).get("state", ""),
    }
    print(json.dumps(result, ensure_ascii=False))
    print(
        "Task accepted. To wait later without resubmitting it:",
        file=sys.stderr,
    )
    interpreter = "py" if sys.platform == "win32" else "python3"
    print(
        f'{interpreter} a2a_client.py --wait "{task_id}" "{base_url}"',
        file=sys.stderr,
    )
    return task_id


def consume_stream(stream: BinaryIO) -> tuple[str, str]:
    """Wait for one SSE stream and return its terminal state and text."""

    latest_text = ""
    for event_name, data in sse_events(stream):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise A2AProtocolError(f"The bridge sent invalid SSE JSON: {data}") from exc

        if event_name == "error" or "error" in payload:
            raise A2AProtocolError(
                json.dumps(payload.get("error", payload), ensure_ascii=False)
            )

        result = payload.get("result", {})
        if not isinstance(result, dict):
            continue
        state, text, terminal = result_details(result)
        if text:
            latest_text = text
        if terminal:
            return state, latest_text

    raise A2AProtocolError(
        "The A2A stream closed before a terminal task state was received."
    )


def print_terminal(state: str, text: str) -> str:
    if text:
        print(text)
    if is_failure_state(state):
        raise SystemExit(1)
    return text


def send_and_wait(prompt: str, base_url: str) -> str:
    _, context_id, endpoint = read_agent_card(base_url)
    params = message_params(prompt, context_id)
    params_body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendStreamingMessage",
        "params": params,
    }
    request = Request(
        endpoint,
        data=json.dumps(params_body).encode("utf-8"),
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
        },
        method="POST",
    )

    # This is one long-lived wait, not a series of status requests. The
    # timeout is intentionally unlimited after the stream is connected.
    try:
        with urlopen(request, timeout=None) as response:
            try:
                state, text = consume_stream(response)
            except A2AProtocolError as exc:
                raise SystemExit(
                    f"A2A streaming request failed: {exc}. "
                    "Do not resend automatically."
                ) from exc
            return print_terminal(state, text)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(
            f"Could not complete the A2A streaming request: {exc}. "
            "Do not resend automatically; the task may still be running."
        ) from exc


def get_task_once(task_id: str, endpoint: str) -> dict[str, Any]:
    try:
        payload = rpc_request(endpoint, "GetTask", {"id": task_id}, timeout=10)
    except A2AProtocolError as exc:
        raise SystemExit(f"Could not read task {task_id}: {exc}") from exc
    task = payload.get("result", {}).get("task") or payload.get("result")
    if not isinstance(task, dict):
        raise SystemExit(f"The bridge returned no task data for {task_id}.")
    return task


def wait_for_task(task_id: str, base_url: str) -> str:
    _, _, endpoint = read_agent_card(base_url)
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SubscribeToTask",
        "params": {"id": task_id},
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

    try:
        with urlopen(request, timeout=None) as response:
            try:
                state, text = consume_stream(response)
            except A2AProtocolError:
                # A task may have reached a terminal state in the small gap
                # between submission and subscription. Read it once instead
                # of starting a polling loop or submitting the work again.
                task = get_task_once(task_id, endpoint)
                state, text, terminal = result_details({"task": task})
                if terminal:
                    return print_terminal(state, text)
                raise
            return print_terminal(state, text)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(
            f"The task stream disconnected: {exc}. The taskId is {task_id}; "
            "reattach with --wait instead of resubmitting the message."
        ) from exc
    except A2AProtocolError as exc:
        raise SystemExit(
            f"Could not follow task {task_id}: {exc}. "
            "The task may still be running; do not resubmit it."
        ) from exc


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "--submit" and len(args) == 3:
        submit(args[1], args[2].rstrip("/"))
        return
    if args[0] == "--wait" and len(args) == 3:
        wait_for_task(args[1], args[2].rstrip("/"))
        return
    if len(args) == 2:
        send_and_wait(args[0], args[1].rstrip("/"))
        return
    raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
