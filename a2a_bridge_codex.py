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
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import create_async_engine
import uvicorn

from a2a.helpers.proto_helpers import new_text_message, new_text_status_update_event
from a2a.server.agent_execution import AgentExecutor
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import DatabaseTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill
from a2a.types.a2a_pb2 import ListTasksRequest, Task, TaskState, TaskStatus
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
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


def ask_codex(
    prompt: str,
    thread_id: str,
    cwd: Path,
    timeout: int | None,
    model: str | None,
    reasoning_effort: str | None,
) -> str:
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
        ]
        if model:
            command.extend(["--model", model])
        if reasoning_effort:
            command.extend(["--config", f'model_reasoning_effort="{reasoning_effort}"'])
        command.extend([thread_id, "-"])
        process_timeout = None if timeout is None or timeout <= 0 else timeout
        try:
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=process_timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            logging.error(
                "Codex exceeded the configured limit of %s seconds.",
                process_timeout,
            )
            raise RuntimeError(
                f"Codex exceeded {process_timeout} seconds. Check the state before retrying."
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
        timeout: int | None,
        demo: bool,
        model: str | None,
        reasoning_effort: str | None,
    ) -> None:
        self.thread_id = thread_id
        self.context_id = context_id
        self.cwd = cwd
        self.timeout = timeout
        self.demo = demo
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.lock = asyncio.Lock()

    async def execute(self, context, event_queue) -> None:
        prompt = context.get_user_input()
        if not prompt.strip():
            raise ValueError("Envía un mensaje de texto no vacío.")

        task_id = context.task_id
        if not task_id or not context.context_id:
            raise InvalidParamsError(
                message="A2A did not provide a taskId and contextId for this request."
            )

        requested_context = context.message.context_id if context.message else ""
        if requested_context != self.context_id:
            raise InvalidParamsError(
                message=f"Este puente está dedicado al contextId {self.context_id}"
            )

        # Enter task mode immediately. The streaming endpoint can therefore
        # return a Task while another request is still using the Codex writer.
        # The lock serializes actual writes to the one existing conversation.
        initial_task = Task(
            id=task_id,
            context_id=self.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
        )
        if context.message:
            initial_task.history.append(context.message)
        await event_queue.enqueue_event(initial_task)

        try:
            async with self.lock:
                await event_queue.enqueue_event(
                    new_text_status_update_event(
                        task_id=task_id,
                        context_id=self.context_id,
                        state=TaskState.TASK_STATE_WORKING,
                        text="Codex is processing this request.",
                    )
                )

                if self.demo:
                    answer = "Demo A2A: " + prompt
                else:
                    answer = await asyncio.to_thread(
                        ask_codex,
                        prompt,
                        self.thread_id,
                        self.cwd,
                        self.timeout,
                        self.model,
                        self.reasoning_effort,
                    )

            completed = new_text_status_update_event(
                task_id=task_id,
                context_id=self.context_id,
                state=TaskState.TASK_STATE_COMPLETED,
                text=answer,
            )
            await event_queue.enqueue_event(completed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logging.exception("A2A task %s failed", task_id)
            failed = new_text_status_update_event(
                task_id=task_id,
                context_id=self.context_id,
                state=TaskState.TASK_STATE_FAILED,
                text=f"Codex request failed: {exc}",
            )
            await event_queue.enqueue_event(failed)

    async def cancel(self, context, event_queue) -> None:
        raise UnsupportedOperationError(
            "Individual task cancellation is not implemented; stop the foreground bridge with Ctrl+C."
        )


TERMINAL_TASK_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
    }
)


async def recover_incomplete_tasks(
    task_store: DatabaseTaskStore, context_id: str
) -> int:
    """Fail tasks left non-terminal by a previous bridge process.

    A Codex turn cannot be resumed safely from the A2A task record alone:
    resubmitting it could duplicate file changes or other side effects. Marking
    it failed makes the interrupted state visible and prevents a reconnect
    from hanging forever while pretending that an old worker still exists.
    """

    context = ServerCallContext()
    page_token = ""
    recovered = 0
    while True:
        params = ListTasksRequest(
            context_id=context_id,
            page_size=100,
            page_token=page_token,
        )
        page = await task_store.list(params, context)
        for task in page.tasks:
            if task.status.state in TERMINAL_TASK_STATES:
                continue

            task.status.state = TaskState.TASK_STATE_FAILED
            task.status.message.CopyFrom(
                new_text_message(
                    "The bridge restarted while this task was active. "
                    "It was not resumed automatically. Inspect the Codex "
                    "conversation before submitting the work again; do not "
                    "duplicate a task that may already have caused side effects.",
                    context_id=task.context_id,
                    task_id=task.id,
                )
            )
            await task_store.save(task, context)
            recovered += 1

        if not page.next_page_token:
            break
        page_token = page.next_page_token

    return recovered


def create_app(
    base_url: str,
    thread_id: str,
    context_id: str,
    cwd: Path,
    timeout: int | None,
    task_db: Path,
    model: str | None,
    reasoning_effort: str | None,
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
        capabilities=AgentCapabilities(streaming=True),
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
    executor = CodexExecutor(
        thread_id,
        context_id,
        cwd,
        timeout,
        demo,
        model,
        reasoning_effort,
    )
    database_url = f"sqlite+aiosqlite:///{task_db.as_posix()}"
    engine = create_async_engine(database_url)
    task_store = DatabaseTaskStore(engine)
    handler = DefaultRequestHandler(executor, task_store, card)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        await task_store.initialize()
        recovered = await recover_incomplete_tasks(task_store, context_id)
        if recovered:
            logging.warning(
                "Marked %s task(s) failed because the previous bridge process stopped.",
                recovered,
            )
        try:
            yield
        finally:
            await handler.aclose()
            await engine.dispose()

    return Starlette(
        routes=create_agent_card_routes(card)
        + create_jsonrpc_routes(handler, "/"),
        lifespan=lifespan,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="IP Tailscale local")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--base-url", required=True, help="URL visible to the client")
    parser.add_argument("--thread-id", required=True, help="UUID de la conversación Codex")
    parser.add_argument("--context-id", required=True, help="contextId A2A dedicado")
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Maximum Codex runtime in seconds; 0 means no limit (default).",
    )
    parser.add_argument(
        "--task-db",
        type=Path,
        default=None,
        help="SQLite task database; defaults to CODEX_HOME/a2a-bridge/tasks.sqlite3.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("A2A_CODEX_MODEL") or None,
        help="Optional Codex model for resumed turns (for example gpt-5.6-luna).",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh", "max"),
        default=os.environ.get("A2A_CODEX_REASONING_EFFORT") or None,
        help="Optional Codex reasoning effort for resumed turns.",
    )
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

    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    task_db = Path(
        os.environ.get("A2A_TASK_DB")
        or args.task_db
        or (codex_home / "a2a-bridge" / "tasks.sqlite3")
    )
    task_db.parent.mkdir(parents=True, exist_ok=True)

    base_url = args.base_url.rstrip("/")
    print(f"Codex conversation: {thread_id}", flush=True)
    print(f"A2A contextId:      {args.context_id}", flush=True)
    print(f"Working directory:   {cwd}", flush=True)
    print(f"Task database:       {task_db}", flush=True)
    if args.model:
        print(f"Codex model:         {args.model}", flush=True)
    if args.reasoning_effort:
        print(f"Reasoning effort:    {args.reasoning_effort}", flush=True)
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
            task_db,
            args.model,
            args.reasoning_effort,
            args.demo,
        ),
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
