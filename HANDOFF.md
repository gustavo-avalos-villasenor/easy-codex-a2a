# A2A Bridge Handoff: Existing Codex Conversation over Tailscale

This is the complete operational handoff for exposing one existing Codex conversation as a remote A2A agent.

The asynchronous callback implementation is the canonical version on `main`.
It is the version to use when long-running work must not keep the calling Codex
agent in a model turn while it waits. The older `async-resume-callback`,
`async-tasks`, and `durable-async-tasks` branches remain available as historical
rollback/reference points.

Clone the repository normally; GitHub's default branch already contains the
callback workflow:

~~~bash
git clone https://github.com/gustavo-avalos-villasenor/easy-codex-a2a.git
cd easy-codex-a2a
~~~

The remote agent can send messages to the existing Codex conversation and receive Codex replies directly. The user does not need to copy messages between agents after the bridge is running.

## 1. Architecture

~~~text
Remote agent
    |
    | A2A 1.0 JSON-RPC submission over a private Tailscale connection
    | returns a taskId immediately
    v
Detached watcher on the calling agent's host
    |
    | one SSE subscription, outside the model turn
    v
Python A2A bridge on the server Codex host
    |
    | Persistent A2A Task store + independent worker
    | codex --no-daemon exec resume THREAD_UUID
    v
The existing Codex conversation
~~~

The bridge:

- Publishes an A2A Agent Card.
- Accepts A2A SendMessage, SendStreamingMessage, SubscribeToTask, and GetTask
  JSON-RPC requests.
- Resumes one exact existing Codex conversation for every request.
- Publishes a submitted task immediately when the caller asks for
  `returnImmediately`, then runs the worker independently until it publishes a
  completed or failed task.
- Keeps task execution independent from the HTTP client connection. A client
  may disconnect after receiving a task ID without canceling the worker.
- Persists task state in SQLite so a later client can reattach by task ID.
- Supports one SSE subscription for waiting; it does not poll `GetTask`.
- Serializes requests so only one request writes to the conversation at a time.
- Listens only on the server's Tailscale IP.
- Runs in the foreground and stays waiting for requests.
- Stops with Ctrl+C in the terminal running the bridge.

The communication has two cooperating sides. The server/worker side owns the
existing Codex conversation and performs the requested work. The client side
submits the A2A task and, in the recommended callback mode, runs a detached
watcher that resumes the client's own Codex conversation once with the final
result. This is bidirectional request/result communication, but it is not a
fully symmetric peer chat: the worker does not spontaneously start a new client
conversation, and writes to the one exposed worker conversation are serialized.

The Codex subprocess timeout is unlimited by default. `--timeout 0` means no
limit; a positive value is an optional safety limit in seconds. In callback
mode, the calling agent submits and ends its model turn immediately. A
detached local process holds the SSE connection and makes one Codex resume only
after the task reaches a terminal state. The waiting process is not a model
turn and does not periodically ask for status.

Task metadata is stored in SQLite at `CODEX_HOME/a2a-bridge/tasks.sqlite3` by
default. Set `A2A_TASK_DB` or pass `--task-db` to select another path. A
completed task remains retrievable after a bridge restart. If the bridge is
stopped while a worker is active, the next startup marks that non-terminal task
failed with an explicit recovery message instead of leaving it hanging or
silently submitting it a second time. A client disconnect alone is safe and
does not cancel the worker.

The bridge can select the Codex model and reasoning effort for resumed turns
without changing the user's global Codex configuration. Pass `--model` and
`--reasoning-effort`, or set `A2A_CODEX_MODEL` and
`A2A_CODEX_REASONING_EFFORT`. The official GPT-5.6 Luna model ID is
`gpt-5.6-luna`; this CLI accepts reasoning efforts `none`, `low`, `medium`,
`high`, `xhigh`, and `max`. If someone says “Luna Light”, use
`gpt-5.6-luna` with `low`—there is no separate `luna-light` model ID.

Example for the recommended safe launcher:

~~~bash
A2A_CODEX_MODEL="gpt-5.6-luna" \
A2A_CODEX_REASONING_EFFORT="low" \
./start-a2a-after-exit.sh UUID-OF-THE-CURRENT-CONVERSATION 8766 codex-CONTEXT-ID
~~~

Original A2A repository:

~~~text
https://github.com/a2aproject/a2a
~~~

The upstream repository provides the A2A protocol and SDK. This repository
contains the custom Codex bridge files, so an agent can clone this repository
and mount the setup without needing another private code bundle.

Useful official Codex documentation:

- https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server
- https://developers.openai.com/blog/codex-as-a-platform
- https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle

## 2. Critical single-writer rule

Codex does not allow the interactive Codex application and the bridge to write to the same conversation simultaneously.

Before starting the bridge:

1. Open the target Codex conversation.
2. Type /exit.
3. Wait until Codex returns to a normal shell prompt.
4. Close Codex Desktop, VS Code/Codex, or any other process that still owns the conversation.
5. Start the bridge from the normal shell.

While the bridge is running:

- Do not type manually into the same conversation.
- Do not reopen the conversation in Codex Desktop or VS Code.
- Do not start another Codex process against the same conversation UUID.
- Do not send concurrent A2A requests.

To use the conversation manually again, stop the bridge first with Ctrl+C.

The bridge invokes Codex with --no-daemon. This avoids reusing an unrelated persistent app-server daemon, but the interactive owner of this exact conversation must still be closed.

## 3. Tested values

These values worked in the original test:

| Setting | Tested value |
|---|---|
| A2A repository | https://github.com/a2aproject/a2a |
| Server Tailscale IPv4 | TAILSCALE_SERVER_IP |
| TCP port | 8766 |
| Base URL | http://TAILSCALE_SERVER_IP:8766 |
| Agent Card | http://TAILSCALE_SERVER_IP:8766/.well-known/agent-card.json |
| JSON-RPC endpoint | http://TAILSCALE_SERVER_IP:8766/ |
| Existing Codex thread UUID | CURRENT_THREAD_UUID |
| A2A context ID | CURRENT_CONTEXT_ID |
| Codex working directory | SESSION_WORKING_DIRECTORY |
| CODEX_HOME on the tested host | ~/.codex |
| Tested Codex CLI | 0.162.0 |

These values are specific to that host and conversation. Another installation must replace the Tailscale IP, thread UUID, A2A context ID, working directory, operating-system user, and CODEX_HOME as necessary.

The remote agent does not need the Codex thread UUID. It needs only the Agent Card URL or base URL.

A UUID from another host is not enough. The session must exist on the same host, under the same user and CODEX_HOME that run the bridge.

The important identity rule is:

~~~text
The server bridge must resume the same Codex conversation in which the setup
is being performed. The repository is only the transport and launcher code.
It must not create a new conversation or select another session by name.
~~~

## 4. Required files

The working bridge directory should contain:

~~~text
a2a-bridge/
├── HANDOFF.md
├── README.md
├── requirements.txt
├── a2a_bridge.py
├── a2a_bridge_codex.py
├── a2a_client.py
├── test_async_resume.py
├── start-a2a.sh
├── start-a2a-after-exit.sh
├── start-a2a.ps1
└── REMOTE_AGENT_PROMPT.md
~~~

File roles:

- a2a_bridge_codex.py: actual A2A-to-Codex bridge.
- a2a_bridge.py: wrapper entry point. Its filename intentionally does not contain the word codex.
- a2a_client.py: standard-library client that reads the Agent Card and can
  submit immediately (`--submit`), submit and later resume the caller's Codex
  conversation from a detached watcher (`--submit-and-resume`), follow one
  task over SSE (`--wait`), or perform the original one-call streaming
  interaction.
- start-a2a-after-exit.sh: recommended safe foreground launcher on Linux.
- start-a2a.sh: simple direct launcher when the conversation is already cleanly closed.
- start-a2a.ps1: foreground launcher for Windows.
- requirements.txt: tested Python dependencies.
- README.md: short local README.
- HANDOFF.md: this complete operational document.
- REMOTE_AGENT_PROMPT.md: copy-paste message for an agent with no prior context.

The main branch uses the A2A SDK's streaming/task support and SQLite task store. The upstream
protocol repository used for this implementation is:

~~~text
https://github.com/a2aproject/a2a
~~~

The virtual environment does not need to be copied. Recreate it from requirements.txt.

This GitHub repository is the complete custom bundle. Clone it first:

~~~bash
git clone https://github.com/gustavo-avalos-villasenor/easy-codex-a2a.git
cd easy-codex-a2a
~~~

The upstream A2A repository is a protocol and SDK reference. It is not a
replacement for this repository.

If the custom files must be transferred as an archive instead:

~~~bash
tar -czf a2a-bridge-bundle.tar.gz HANDOFF.md README.md REMOTE_AGENT_PROMPT.md requirements.txt a2a_bridge.py a2a_bridge_codex.py a2a_client.py test_async_resume.py start-a2a.sh start-a2a-after-exit.sh start-a2a.ps1
~~~

## 5. Server requirements

The host that owns the Codex conversation needs:

- Python 3.10 or newer.
- Codex CLI installed and authenticated.
- Tailscale connected to the same tailnet as the remote agent.
- curl.
- lsof on Linux.
- Permission to run Codex in the session's original working directory.
- The same user and CODEX_HOME that own the conversation.

Check the environment:

~~~bash
codex login status
codex --version
tailscale ip -4
python3 --version
command -v curl
command -v lsof
~~~

codex login status must report an authenticated session.

## 6. Install from scratch on Linux

Clone this repository, which contains the complete custom bridge bundle:

~~~bash
git clone https://github.com/gustavo-avalos-villasenor/easy-codex-a2a.git
cd easy-codex-a2a
~~~

The original A2A repository is optional. Clone it separately only if its source
or documentation is needed:

~~~bash
git clone --depth 1 https://github.com/a2aproject/a2a.git a2a-upstream
~~~

Create the virtual environment:

~~~bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
~~~

The tested requirements file is:

~~~text
a2a-sdk[sqlite]==1.2.2
fastapi==0.143.0
sse-starlette==3.5.0
uvicorn==0.54.0
~~~

Validate the files:

~~~bash
.venv/bin/python -m py_compile a2a_bridge.py a2a_bridge_codex.py a2a_client.py
bash -n start-a2a.sh
bash -n start-a2a-after-exit.sh
~~~

## 7. Conversation UUID and A2A context

The server agent must provide the UUID of the conversation it is serving.

Use the UUID supplied by the Codex runtime or task context. Do not select a conversation by filename timestamp, name, or “most recent” session unless the runtime explicitly confirms that it is the current conversation.

The bridge validates the UUID under:

~~~text
CODEX_HOME/sessions
~~~

If CODEX_HOME is unset, Codex normally uses the current user's ~/.codex/sessions directory.

For the tested conversation:

~~~bash
THREAD_ID="CURRENT_THREAD_UUID"
CONTEXT_ID="CURRENT_CONTEXT_ID"
~~~

For another conversation, use a dedicated context ID consisting of codex- followed by a short stable identifier derived from that UUID.

The A2A context ID is not the Codex UUID. It is the stable context identifier announced by the Agent Card. Every request to this bridge must use the exact context ID announced by that card.

## 8. Recommended Linux startup

First leave the interactive Codex conversation:

~~~text
/exit
~~~

Then run from a normal shell:

~~~bash
cd easy-codex-a2a
./start-a2a-after-exit.sh UUID-OF-THE-CURRENT-CONVERSATION 8766 codex-CONTEXT-ID
~~~

For another conversation, pass explicit values:

~~~bash
./start-a2a-after-exit.sh UUID-OF-THE-TARGET-CONVERSATION 8766 codex-CONTEXT-SUFFIX
~~~

The safe launcher:

1. Checks that codex, tailscale, and lsof exist.
2. Checks for a still-running interactive Codex process.
3. Refuses to continue if the interactive owner is still open.
4. Detects the local Tailscale IPv4 address.
5. Asks the Codex app-server daemon to stop gracefully.
6. Inspects the conversation writer lock with lsof.
7. Terminates a lock holder only when it is identified as the managed Codex app-server daemon.
8. Never deletes a lock file.
9. Checks that the A2A port is not already occupied.
10. Starts the Python bridge in the foreground.

Expected output:

~~~text
A2A bridge in foreground: http://TAILSCALE-IP:8766
The process will remain in standby waiting for requests.
Press Ctrl+C in this terminal to stop it.
~~~

The terminal must remain occupied. This is intentional: the bridge is alive and waiting.

The launcher prints a copy-ready connection block before entering standby. It
includes the repository URL, Agent Card URL, JSON-RPC URL, context ID, and a
message that can be forwarded to the remote agent.

Share the following with the remote agent:

~~~text
Base URL:      http://TAILSCALE-IP:8766
Agent Card:    http://TAILSCALE-IP:8766/.well-known/agent-card.json
JSON-RPC URL:  http://TAILSCALE-IP:8766/
Context ID:    the contextId announced by the Agent Card
~~~

The server must pass the UUID of the current conversation, not a UUID copied
from this document. The tested UUID is shown only as a reference.

## 9. Direct Linux startup

If the conversation is already closed and there is no old daemon or lock, the bridge can be started directly:

~~~bash
cd easy-codex-a2a
TAILSCALE_IP="$(tailscale ip -4 | head -n 1)"
.venv/bin/python a2a_bridge.py --host "$TAILSCALE_IP" --port 8766 --base-url "http://$TAILSCALE_IP:8766" --thread-id "CURRENT_THREAD_UUID" --context-id "CURRENT_CONTEXT_ID" --timeout 0
~~~

To select a model for this direct launch, append for example:

~~~bash
--model gpt-5.6-luna --reasoning-effort low
~~~

Use start-a2a-after-exit.sh when there is any chance that Codex Desktop, VS Code, an old bridge, or an app-server daemon still owns the conversation.

## 10. Agent Card and A2A protocol

Once the bridge is running, the remote agent should first request:

~~~text
http://TAILSCALE-IP:8766/.well-known/agent-card.json
~~~

The card contains:

- The JSON-RPC endpoint.
- The fixed A2A context ID in its description.
- JSONRPC protocol binding.
- Protocol version 1.0.
- streaming true. The bridge supports A2A task streaming over SSE.
- Supported text input and output modes.

There are three supported client modes:

1. For long, uncertain, or disconnect-prone work from another Codex CLI
   conversation, send `SendMessage` with
   `configuration.returnImmediately: true` through
   `--submit-and-resume`. The client starts a detached local watcher, returns
   immediately, and the watcher resumes the caller's Codex conversation once
   after the task reaches `COMPLETED`, `FAILED`, `CANCELED`, or `REJECTED`.
2. For long work from a client that cannot resume a Codex conversation, use
   `--submit` and later `SubscribeToTask` with `--wait`. The bridge returns a
   task ID and keeps the worker running after the submitting process exits.
3. For a short task or a caller that can keep a connection open, send one
   `SendStreamingMessage` request. The response is a Server-Sent Events stream
   that remains open while the task is queued and processed by Codex.

The included client uses `--submit-and-resume` for the first mode, `--submit`
and `--wait` for the second mode, and its default two-argument form for the
third mode.

There is no status polling. In particular, do not implement a loop such as
"wait 20 minutes, call GetTask, wait 20 minutes again". That pattern can make
one 21-minute task look like a 40-minute operation. Use one long-lived SSE
subscription instead. The detached watcher uses one SSE subscription and
reconnects only after a network/stream failure; it never polls `GetTask`.
`--wait` uses `GetTask` only once if the task completed in the small race window
before the subscription was attached; it never loops.

Callback mode removes the model-turn wait from the calling agent, but it cannot
override a firewall or an OS/network failure. Its watcher must remain alive and
the remote agent's host must keep the same user, `CODEX_HOME`, Codex login, and
Codex CLI available until completion. A detached watcher can reconnect without
creating another A2A task.

An HTTP 200 response can still contain a JSON-RPC error. Always inspect the JSON body.

## 11. Remote agent instructions

The remote agent must:

1. Be connected to the same Tailscale tailnet.
2. Read the Agent Card.
3. Use the endpoint announced by the card.
4. Use the context ID announced by the card.
5. Generate a new JSON-RPC request ID for every request.
6. Generate a new A2A message ID for every message.
7. Send only one request at a time.
8. For long or uncertain work from a Codex CLI conversation, prefer
   `--submit-and-resume` with this agent's own current conversation UUID. It
   returns immediately and a detached watcher resumes the same conversation
   once with the terminal result.
9. If the client cannot provide a Codex conversation UUID, use `SendMessage`
   with `configuration.returnImmediately: true`, save the returned task ID,
   and later use `SubscribeToTask` for one SSE wait.
10. For short work, `SendStreamingMessage` is also valid; keep that SSE
   connection open until a terminal task state arrives.
11. Inspect each JSON-RPC/SSE envelope for an `error` object, even when HTTP
    status is 200.
12. Avoid automatic retries or resubmission if a connection disconnects; the
    Codex request may already have been accepted and may still be running.

The remote agent does not need the server's Codex credentials or thread UUID.

### Recommended Python client

Copy a2a_client.py to the remote machine. It uses only Python's standard library:

~~~bash
# Preferred for long-running work from another Codex CLI conversation.
# Use this agent's own current conversation UUID, not the server UUID.
python3 a2a_client.py --submit-and-resume \
  "Long task for the Codex agent" \
  "http://TAILSCALE-IP:8766" \
  "THIS-AGENT-CODEX-CONVERSATION-UUID"

# Portable fallback when this client cannot resume a Codex conversation:
python3 a2a_client.py --submit "Long task for the Codex agent" "http://TAILSCALE-IP:8766"
python3 a2a_client.py --wait "TASK-ID-FROM-SUBMIT" "http://TAILSCALE-IP:8766"

# Convenient one-connection mode for a short request:
python3 a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"
~~~

On Windows:

~~~powershell
py a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"
~~~

`--submit-and-resume` exits after the bridge accepts the task. The detached
watcher waits outside the model runtime and later invokes `codex exec resume`
once on this same client conversation. The returned JSON includes the task ID,
watcher PID, state file, and log file. Let the current Codex turn finish and do
not reopen this conversation in another UI while the callback may still arrive.

`--submit` exits without starting a callback. `--wait` later occupies one SSE
connection; it avoids status polling but may still cause the calling agent's
runtime to re-enter its model turn when its own tool timeout expires. The
default one-connection form remains occupied until completion.

### Callback mode contract

`--submit-and-resume` requires the caller to be a Codex CLI conversation on the
same machine where the command runs. `CLIENT-CODEX-CONVERSATION-UUID` is the
caller's UUID, not the server's UUID. The watcher discovers that conversation's
original working directory from its local `CODEX_HOME`; an optional fourth
argument can override it:

~~~bash
python3 a2a_client.py --submit-and-resume \
  "Long task" "http://TAILSCALE-IP:8766" \
  "CLIENT-CODEX-CONVERSATION-UUID" \
  "/the/caller/working/directory"
~~~

The command writes a private state JSON and log under
`~/.a2a-client/tasks/` (or `A2A_CLIENT_STATE_DIR`). The state file records the
task ID, watcher PID, terminal result, callback attempts, and final callback
status. The watcher is intentionally a separate process, so closing the shell
that launched the short submission command does not cancel it. The client host
must remain powered on, keep the same `CODEX_HOME`, and keep Codex CLI
authenticated until the task completes.

The watcher never re-submits the original A2A message. If the callback's Codex
conversation is still owned by the original turn or an interactive UI, it
waits 30 seconds and retries the single callback. Close the conversation's
interactive owner. If the watcher host is shut down, inspect the task ID and
state before deciding whether to restart a watcher; never blindly submit the
original message again.

### cURL fallback

If `a2a_client.py` is not available, prefer this detached submission for long
work. Generate fresh UUIDs for `REQUEST-UUID` and `MESSAGE-UUID`:

~~~bash
curl -sS -X POST "http://TAILSCALE-IP:8766/" \
  -H "Content-Type: application/json" -H "A2A-Version: 1.0" \
  --data-raw '{"jsonrpc":"2.0","id":"REQUEST-UUID","method":"SendMessage","params":{"message":{"messageId":"MESSAGE-UUID","role":"ROLE_USER","contextId":"CONTEXT-ID-FROM-AGENT-CARD","parts":[{"text":"Long task for the Codex agent"}]},"configuration":{"returnImmediately":true}}}'
~~~

Save the returned `result.task.id` as `TASK-ID`. Later, attach once without
resubmitting the message:

~~~bash
curl -N -sS -X POST "http://TAILSCALE-IP:8766/" \
  -H "Accept: text/event-stream" -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  --data-raw '{"jsonrpc":"2.0","id":"NEW-REQUEST-UUID","method":"SubscribeToTask","params":{"id":"TASK-ID"}}'
~~~

For a short direct request, cURL can use `SendStreamingMessage` instead:

~~~bash
curl -N -sS -X POST "http://TAILSCALE-IP:8766/" \
  -H "Accept: text/event-stream" -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  --data-raw '{"jsonrpc":"2.0","id":"NEW-REQUEST-UUID","method":"SendStreamingMessage","params":{"message":{"messageId":"NEW-MESSAGE-UUID","role":"ROLE_USER","contextId":"CONTEXT-ID-FROM-AGENT-CARD","parts":[{"text":"Hello. Please confirm that you received this message."}]}}}'
~~~

The final answer normally appears in the `statusUpdate.status.message.parts`
field of the final SSE envelope. A JSON-RPC response can contain an `error`
object even when HTTP status is 200:

~~~text
result.statusUpdate.status.message.parts[].text
~~~

The context ID must be copied exactly from the Agent Card.

## 12. Direct message for the remote agent

After the bridge is running, the server operator can send this to the remote agent:

~~~text
The A2A bridge for my existing Codex conversation is now running over Tailscale.

Read the Agent Card first:
http://TAILSCALE-IP:8766/.well-known/agent-card.json

Use the endpoint and contextId announced by that card. If you are running as a
Codex CLI agent, obtain your own current conversation UUID and use the callback
mode for a long or uncertain request:

python3 a2a_client.py --submit-and-resume "Your long request" "http://TAILSCALE-IP:8766" "YOUR-CODEX-CONVERSATION-UUID"

The command returns immediately. A detached watcher waits outside the model
turn and resumes this same conversation once with the task result. Do not run
`--wait` or send the request again. Close the client conversation after the
submission so its writer lock is available.

If you cannot provide a Codex conversation UUID, use the portable task-ID mode:

python3 a2a_client.py --submit "Your long request" "http://TAILSCALE-IP:8766"
python3 a2a_client.py --wait "TASK-ID" "http://TAILSCALE-IP:8766"

For a short request, `SendStreamingMessage` is also valid. In either case do
not poll `GetTask` between waits and do not submit the same message again after
a disconnect; one SSE subscription is the wait mechanism.

Inspect every SSE JSON-RPC envelope for an error object. If the connection
drops, do not resend automatically because Codex may already have processed
the request.
~~~

For the tested server, replace TAILSCALE-IP with:

~~~text
TAILSCALE_SERVER_IP
~~~

## 13. Exact instructions for the server user

Give the server user these instructions:

~~~text
1. Open the target Codex conversation.
2. Type /exit.
3. Close Codex Desktop, VS Code, or any other application that has that chat open.
4. Open a normal shell.
5. Run:
   cd easy-codex-a2a
   ./start-a2a-after-exit.sh UUID-OF-THE-CURRENT-CONVERSATION 8766 codex-CONTEXT-ID
6. Leave that terminal open. It is intentionally occupied in standby.
7. Give the remote agent the complete connection block printed by the bridge,
   including the Agent Card URL and the repository URL.
8. Do not write manually in the same Codex conversation while the bridge is active.
9. When communication is finished, press Ctrl+C in the bridge terminal.
10. Only after Ctrl+C should the conversation be opened interactively again.
~~~

Do not use Ctrl+Z to stop the bridge. Ctrl+Z suspends a process instead of shutting it down cleanly.

Do not use:

~~~bash
sudo pkill -9 -f codex
~~~

That command can kill the bridge or an active request.

## 14. Stopping and restarting

### Normal stop

The preferred stop is to wait for active work to finish and press Ctrl+C in the
terminal running the bridge. A client process can exit safely after
`--submit-and-resume`; that does not stop the bridge worker or its detached
watcher.

Stopping the server bridge does not automatically stop a callback watcher on
the client host. If a callback watcher is still active, let it finish or stop
that client-side process using the PID and log path printed by
`--submit-and-resume`. Stopping the watcher does not cancel the server task;
keep the task ID and do not submit the same request again.

If the bridge must be stopped while a worker is active, press Ctrl+C once and
allow the process to shut down. Do not resubmit that task immediately. On the
next startup, the durable task store marks any task left non-terminal as
failed, with a message telling the operator to inspect the Codex conversation
before deciding whether the work needs to be submitted again.

This stops the HTTP listener and preserves the Codex conversation history.

### Restart

1. Stop the bridge with Ctrl+C.
2. Do not reopen the interactive conversation while the old bridge is still running.
3. If the conversation was reopened, type /exit again.
4. Run:

~~~bash
cd easy-codex-a2a
./start-a2a-after-exit.sh UUID-OF-THE-CURRENT-CONVERSATION 8766 codex-CONTEXT-ID
~~~

### Old detached screen bridge

The current recommended implementation is foreground-only and does not need screen. If an earlier experiment left a detached screen session:

~~~bash
screen -ls
screen -S a2a-bridge -X quit
~~~

Use this only for the old session named a2a-bridge.

## 15. Active-writer troubleshooting

If Codex reports that the conversation already has an active writer:

1. Close Codex Desktop.
2. Close VS Code/Codex.
3. Exit any interactive Codex process with /exit.
4. Stop the Codex daemon gracefully:

~~~bash
codex app-server daemon stop
~~~

5. Run the safe launcher again.

Inspect the lock without deleting it:

~~~bash
THREAD_ID="CURRENT_THREAD_UUID"
lsof "$HOME/.codex/thread-writer-locks/$THREAD_ID.lock"
~~~

Replace THREAD_ID in the path with the actual UUID. Never delete the lock file as a workaround.

## 16. Other troubleshooting

### Connection refused

On the server:

~~~bash
tailscale ip -4
ss -ltnp | grep 8766
~~~

On the remote machine:

~~~bash
tailscale ping TAILSCALE-IP
curl --max-time 10 http://TAILSCALE-IP:8766/.well-known/agent-card.json
~~~

### Agent Card unavailable

Check that:

- The foreground bridge terminal is still open.
- The remote machine is on the same tailnet.
- The address is the Tailscale IP.
- TCP port 8766 is allowed by Tailscale ACLs and the host firewall.
- No other process has changed the port.

### Session not found

Check:

~~~bash
echo "$CODEX_HOME"
codex login status
~~~

If CODEX_HOME is empty, Codex normally uses the current user's ~/.codex directory.

The UUID must exist under that user's session directory. A UUID from another host or user cannot be resumed here.

### Wrong context ID

Always read the context ID from the Agent Card. Do not invent a new context ID for each message.

### Long task or disconnected client

The default Codex timeout is unlimited. For a task that may outlive the
calling agent's tool timeout, use `--submit-and-resume` with the caller's own
Codex conversation UUID. The submitting command exits, and a detached watcher
later resumes that conversation once. The watcher does not issue periodic
status requests; it reconnects only after a broken SSE connection. If the
watcher reports an error, inspect its state JSON and log before deciding what
to do. Never resubmit automatically.

If the caller cannot resume a Codex conversation, use `--submit`, save the task
ID, and later use `--wait` to open one SSE subscription. This still avoids a
polling loop, but the calling agent may consume tokens if its own runtime
re-enters the model while waiting.

If the bridge itself restarts, completed tasks remain in SQLite. An active task
from the previous process is deliberately marked failed on startup because a
task record cannot prove whether Codex already performed side effects; inspect
the conversation before resubmitting anything.

## 17. Security and scope

This setup is private at the network layer:

- The server binds only to the Tailscale IP.
- It does not bind to 0.0.0.0.
- It does not use Tailscale Serve.
- It does not use Tailscale Funnel.
- It is not intentionally published to the public Internet.
- Tailscale encrypts traffic between tailnet nodes.

The bridge currently has no application-level authentication token. Any tailnet peer that can reach the port may be able to submit instructions. Use Tailscale ACLs or add an authentication layer if the tailnet contains untrusted devices.

The remote agent's messages are passed to Codex. Codex runs with:

~~~text
--sandbox workspace-write
~~~

A trusted remote agent may therefore cause Codex to read or modify files in the original working directory and use the tools available to that conversation. Do not expose the endpoint to an untrusted agent.

## 18. Windows server notes

On Windows, install Python 3.10 or newer, Node.js, Codex CLI, and Tailscale. Authenticate Codex as the same Windows user that owns the conversation:

~~~powershell
codex login status
tailscale ip -4
~~~

Create the environment:

~~~powershell
py -3.10 -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
.venv/Scripts/python.exe -m pip install -r requirements.txt
~~~

Optional model selection in PowerShell:

~~~powershell
$env:A2A_CODEX_MODEL = "gpt-5.6-luna"
$env:A2A_CODEX_REASONING_EFFORT = "low"
~~~

Use the PowerShell launcher already included in the repository:

~~~powershell
.\start-a2a.ps1 -ThreadId "UUID-OF-THE-TARGET-CONVERSATION" -ContextId "codex-CONTEXT-SUFFIX"
~~~

It discovers the Tailscale IPv4 address, passes `--timeout 0` to the bridge,
and prints the Agent Card URL plus copy-ready instructions before entering
standby. For long work from a Codex CLI client, use callback mode with that
client's own conversation UUID:

~~~powershell
py a2a_client.py --submit-and-resume "Long task for the Codex agent" "http://TAILSCALE-IP:8766" "CLIENT-CODEX-CONVERSATION-UUID"
~~~

This returns immediately and starts a detached watcher. It later resumes the
client conversation once, outside the model turn. Do not run `--wait` or
resubmit the same request. If the client cannot provide a Codex conversation
UUID, use the portable `--submit` plus `--wait` mode instead.

~~~powershell
.\start-a2a.ps1 -ThreadId "UUID-OF-THE-TARGET-CONVERSATION" -ContextId "codex-CONTEXT-SUFFIX"
~~~

The PowerShell terminal remains occupied while the bridge is active. Stop it with Ctrl+C in that terminal.

The Windows bridge can locate Codex through codex on PATH or through:

~~~text
%APPDATA%/npm/node_modules/@openai/codex/bin/codex.js
~~~

If necessary:

~~~powershell
$env:CODEX_CLI_JS = "C:/path/to/codex.js"
~~~

The same single-writer rule applies on Windows.

## 19. Verification checklist

Before declaring the bridge ready:

- [ ] codex login status is authenticated.
- [ ] tailscale ip -4 returns the server IP.
- [ ] The target thread UUID belongs to this host and user.
- [ ] The interactive Codex conversation was exited with /exit.
- [ ] Codex Desktop and VS Code are closed for this conversation.
- [ ] The bridge terminal remains occupied in the foreground.
- [ ] The Agent Card returns HTTP 200.
- [ ] The Agent Card announces the expected endpoint.
- [ ] The Agent Card announces the expected context ID.
- [ ] The remote agent can send one test message.
- [ ] The stream reaches a terminal task state and contains the final text in
      result.statusUpdate.status.message.parts[].text.
- [ ] Requests are sent sequentially.
- [ ] The bridge is stopped with Ctrl+C when finished.

Optional transport-only test:

~~~bash
.venv/bin/python a2a_bridge.py --host TAILSCALE_SERVER_IP --port 8766 --base-url http://TAILSCALE_SERVER_IP:8766 --thread-id CURRENT_THREAD_UUID --context-id CURRENT_CONTEXT_ID --demo
~~~

Demo mode replies with Demo A2A: ... and does not call Codex. Do not use demo mode for the real conversation.

## 20. Quick operational summary

Server user:

~~~bash
/exit
cd easy-codex-a2a
./start-a2a-after-exit.sh UUID-OF-THE-CURRENT-CONVERSATION 8766 codex-CONTEXT-ID
~~~

Remote agent:

~~~bash
curl http://TAILSCALE-IP:8766/.well-known/agent-card.json
python3 a2a_client.py --submit-and-resume \
  "Message for the Codex conversation" \
  "http://TAILSCALE-IP:8766" \
  "THIS-AGENT-CODEX-CONVERSATION-UUID"
~~~

The callback command returns immediately; its detached watcher resumes the
client conversation once when the result is ready. For a client without a Codex
conversation UUID, use `--submit` followed later by `--wait`. For short work,
the two-argument form blocks on one SSE connection until the final answer.
None of these modes runs a periodic status-polling loop.

Stop:

~~~text
Ctrl+C in the bridge terminal
~~~

The bridge is active while that terminal is occupied. It is stopped when Ctrl+C returns the shell prompt.
