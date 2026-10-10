"""A2A 1.0 foreground bridge to an existing Codex CLI conversation."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import UUID

import uvicorn

from a2a.helpers.proto_helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill
from a2a.utils.errors import InvalidParamsError
from starlette.applications import Starlette


def session_metadata(thread_id: str) -> dict[str, str | None]:
    """Validate that this UUID exists in the current user's CODEX_HOME."""

    thread_id = str(UUID(thread_id))
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        raise FileNotFoundError(f"No existe el directorio de sesiones: {sessions}")

    for path in sessions.rglob(f"*{thread_id}.jsonl"):
        try:
            with path.open(encoding="utf-8") as stream:
                event = json.loads(stream.readline())
            payload = event.get("payload", {})
            event_id = payload.get("id", payload.get("session_id"))
            if event.get("type") == "session_meta" and event_id == thread_id:
                return {
                    "thread_id": thread_id,
                    "cwd": payload.get("cwd"),
                    "path": str(path),
                }
        except (OSError, ValueError, TypeError):
            continue

    raise FileNotFoundError(
        f"No se encontró la sesión {thread_id} en {sessions}; "
        "verifica UUID, usuario y CODEX_HOME."
    )


def codex_command() -> list[str]:
    """Find the Codex CLI executable for the current user."""

    configured_js = os.environ.get("CODEX_CLI_JS", "").strip()
    appdata = os.environ.get("APPDATA", "")
    candidates = [Path(configured_js)] if configured_js else []
    if os.name == "nt" and appdata:
        candidates.append(
            Path(appdata)
            / "npm"
            / "node_modules"
            / "@openai"
            / "codex"
            / "bin"
            / "codex.js"
        )
    for entry in candidates:
        if entry.is_file():
            return [shutil.which("node") or "node", str(entry)]

    executable = shutil.which("codex")
    if executable:
        return [executable]
    raise RuntimeError(
        "No encontré Codex CLI. Ajusta PATH o configura CODEX_CLI_JS con la ruta a codex.js."
    )


def ask_codex(prompt: str, thread_id: str, cwd: Path, timeout: int) -> str:
    """Resume exactly one existing thread and return its final response."""

    with tempfile.TemporaryDirectory(prefix="codex-a2a-") as temp_dir:
        output = Path(temp_dir) / "answer.txt"
        command = codex_command() + [
            "--no-daemon",
            "exec",
            "--sandbox",
            "workspace-write",
            "-C",
            str(cwd),
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            str(output),
            "resume",
            thread_id,
            "-",
        ]
        try:
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            logging.error("Codex excedió el límite de %s segundos.", timeout)
            raise RuntimeError(
                f"Codex excedió {timeout} segundos. Comprueba el estado antes de reintentar."
            ) from exc

        started_id = None
        event_errors: list[str] = []
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "thread.started":
                started_id = event.get("thread_id")
            if event.get("type") in {"error", "turn.failed"}:
                error = event.get("error")
                event_errors.append(
                    error.get("message", "")
                    if isinstance(error, dict)
                    else str(error or "")
                )

        if result.returncode:
            detail = "\n".join(
                filter(None, [result.stderr.strip(), *event_errors])
            ).strip()
            logging.error(
                "Codex CLI terminó con código %s: %s",
                result.returncode,
                detail[:2000] or "sin diagnóstico",
            )
            if "already has an active writer" in detail:
                raise RuntimeError(
                    "Esta conversación sigue abierta en otro proceso Codex. "
                    "Cierra por completo Codex Desktop/VS Code; si queda el daemon, "
                    "ejecuta `codex app-server daemon stop` y vuelve a enviar el mismo mensaje. "
                    "No borres el archivo de bloqueo."
                )
            raise RuntimeError(
                f"Codex CLI falló (código {result.returncode}); revisa el diagnóstico de esta terminal."
            )

        if started_id != thread_id:
            raise RuntimeError(
                "Codex no confirmó el UUID esperado; se rechaza una respuesta de otra conversación."
            )
        if not output.is_file():
            raise RuntimeError("Codex terminó sin escribir la respuesta final.")
        return output.read_text(encoding="utf-8")


class CodexExecutor(AgentExecutor):
    def __init__(
        self,
        thread_id: str,
        context_id: str,
        cwd: Path,
        timeout: int,
        demo: bool,
    ) -> None:
        self.thread_id = thread_id
        self.context_id = context_id
        self.cwd = cwd
        self.timeout = timeout
        self.demo = demo
        self.lock = asyncio.Lock()

    async def execute(self, context, event_queue) -> None:
        prompt = context.get_user_input()
        if not prompt.strip():
            raise ValueError("Envía un mensaje de texto no vacío.")

        requested_context = context.message.context_id if context.message else ""
        if requested_context != self.context_id:
            raise InvalidParamsError(
                message=f"Este puente está dedicado al contextId {self.context_id}"
            )

        async with self.lock:
            if self.demo:
                answer = "Demo A2A: " + prompt
            else:
                answer = await asyncio.to_thread(
                    ask_codex,
                    prompt,
                    self.thread_id,
                    self.cwd,
                    self.timeout,
                )

        await event_queue.enqueue_event(
            new_text_message(answer, context_id=self.context_id)
        )

    async def cancel(self, context, event_queue) -> None:
        raise NotImplementedError(
            "El puente procesa cada mensaje como una operación única."
        )


def create_app(
    base_url: str,
    thread_id: str,
    context_id: str,
    cwd: Path,
    timeout: int,
    demo: bool = False,
) -> Starlette:
    card = AgentCard(
        name="Codex A2A bridge" if not demo else "A2A transport demo",
        description=(
            f"Existing Codex conversation: {thread_id}; "
            f"contextId: {context_id}; transport: private Tailscale HTTP"
        ),
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=base_url.rstrip("/") + "/",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="codex-conversation",
                name="Existing Codex conversation",
                description=(
                    "Continues one existing Codex conversation, one message at a time."
                ),
                tags=["codex", "a2a"],
            )
        ],
    )
    executor = CodexExecutor(thread_id, context_id, cwd, timeout, demo)
    handler = DefaultRequestHandler(executor, InMemoryTaskStore(), card)
    return Starlette(
        routes=create_agent_card_routes(card)
        + create_jsonrpc_routes(handler, "/")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="IP Tailscale local")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--base-url", required=True, help="URL visible to the client")
    parser.add_argument("--thread-id", required=True, help="UUID de la conversación Codex")
    parser.add_argument("--context-id", required=True, help="contextId A2A dedicado")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--demo", action="store_true", help="echo sin llamar a Codex")
    args = parser.parse_args()

    thread_id = str(UUID(args.thread_id))
    metadata = session_metadata(thread_id)
    cwd = Path(
        os.environ.get("A2A_CODEX_CWD")
        or metadata.get("cwd")
        or Path.cwd()
    )
    if not cwd.is_dir():
        raise NotADirectoryError(
            f"No existe el directorio de trabajo de Codex: {cwd}"
        )

    base_url = args.base_url.rstrip("/")
    print(f"Codex conversation: {thread_id}", flush=True)
    print(f"A2A contextId:      {args.context_id}", flush=True)
    print(f"Working directory:   {cwd}", flush=True)
    print(
        f"Agent Card:          {base_url}/.well-known/agent-card.json",
        flush=True,
    )
    print(f"JSON-RPC endpoint:   {base_url}/", flush=True)
    print("Ctrl+C detiene el puente. Mantén esta terminal abierta.", flush=True)

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(
            base_url,
            thread_id,
            args.context_id,
            cwd,
            args.timeout,
            args.demo,
        ),
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
