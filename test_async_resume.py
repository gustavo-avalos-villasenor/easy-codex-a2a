from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import a2a_client  # noqa: E402


THREAD_ID = "11111111-1111-4111-8111-111111111111"


class MockA2AHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/.well-known/agent-card.json":
            self.send_error(404)
            return
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        payload = {
            "name": "test bridge",
            "description": "contextId: test-context; transport: test",
            "capabilities": {"streaming": True},
            "supportedInterfaces": [{"url": base_url + "/"}],
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        method = request.get("method")
        self.server.calls.append(method)
        if method == "SendMessage":
            payload = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "task": {
                        "id": "task-async-test",
                        "contextId": "test-context",
                        "status": {"state": "TASK_STATE_SUBMITTED"},
                    }
                },
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if method == "SubscribeToTask":
            events = [
                {
                    "result": {
                        "task": {
                            "id": "task-async-test",
                            "contextId": "test-context",
                            "status": {"state": "TASK_STATE_SUBMITTED"},
                        }
                    }
                },
                {
                    "result": {
                        "statusUpdate": {
                            "taskId": "task-async-test",
                            "contextId": "test-context",
                            "status": {
                                "state": "TASK_STATE_COMPLETED",
                                "message": {"parts": [{"text": "worker done"}]},
                            },
                        }
                    }
                },
            ]
            body = "".join(
                f"data: {json.dumps(event)}\n\n" for event in events
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True
            return

        self.send_error(400, f"unexpected method: {method}")


class AsyncResumeTest(unittest.TestCase):
    def test_submit_starts_detached_watcher_and_resumes_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="a2a-test-") as temporary:
            temp_dir = Path(temporary)
            fake_bin = temp_dir / "bin"
            fake_bin.mkdir()
            fake_codex = fake_bin / "codex"
            fake_codex.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                "output = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
                "thread = sys.argv[-2]\n"
                "output.write_text('callback completed')\n"
                "print(json.dumps({'type': 'thread.started', 'thread_id': thread}))\n",
                encoding="utf-8",
            )
            fake_codex.chmod(
                fake_codex.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )

            previous_path = os.environ.get("PATH", "")
            previous_state_dir = os.environ.get("A2A_CLIENT_STATE_DIR")
            os.environ["PATH"] = f"{fake_bin}{os.pathsep}{previous_path}"
            os.environ["A2A_CLIENT_STATE_DIR"] = str(temp_dir / "state")
            try:
                server = ThreadingHTTPServer(("127.0.0.1", 0), MockA2AHandler)
                server.calls = []
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base_url = f"http://127.0.0.1:{server.server_port}"
                    a2a_client.submit(
                        "long work",
                        base_url,
                        resume_thread_id=THREAD_ID,
                        resume_cwd=str(temp_dir),
                    )

                    state_path = a2a_client.watcher_state_path("task-async-test")
                    deadline = time.monotonic() + 10
                    state: dict[str, object] = {}
                    while time.monotonic() < deadline:
                        if state_path.exists():
                            state = json.loads(state_path.read_text(encoding="utf-8"))
                            if state.get("status") in {"completed", "failed"}:
                                break
                        time.sleep(0.05)

                    self.assertEqual(state.get("status"), "completed", state)
                    self.assertEqual(state.get("taskState"), "TASK_STATE_COMPLETED", state)
                    self.assertEqual(state.get("result"), "worker done")
                    self.assertEqual(state.get("callbackResponse"), "callback completed")
                    self.assertEqual(server.calls.count("SubscribeToTask"), 1)
                    self.assertNotIn("GetTask", server.calls)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
            finally:
                if previous_state_dir is None:
                    os.environ.pop("A2A_CLIENT_STATE_DIR", None)
                else:
                    os.environ["A2A_CLIENT_STATE_DIR"] = previous_state_dir
                os.environ["PATH"] = previous_path


if __name__ == "__main__":
    unittest.main()
