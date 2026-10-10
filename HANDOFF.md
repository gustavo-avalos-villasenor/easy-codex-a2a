# A2A Bridge Handoff: Existing Codex Conversation over Tailscale

This is the complete operational handoff for exposing one existing Codex conversation as a remote A2A agent.

The remote agent can send messages to the existing Codex conversation and receive Codex replies directly. The user does not need to copy messages between agents after the bridge is running.

## 1. Architecture

~~~text
Remote agent
    |
    | A2A 1.0 JSON-RPC over private Tailscale networking
    v
Python A2A bridge on the Codex host
    |
    | codex --no-daemon exec resume THREAD_UUID
    v
The existing Codex conversation
~~~

The bridge:

- Publishes an A2A Agent Card.
- Accepts A2A SendMessage JSON-RPC requests.
- Resumes one exact existing Codex conversation for every request.
- Returns the final Codex answer synchronously.
- Serializes requests so only one request writes to the conversation at a time.
- Listens only on the server's Tailscale IP.
- Runs in the foreground and stays waiting for requests.
- Stops with Ctrl+C in the terminal running the bridge.

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
├── start-a2a.sh
├── start-a2a-after-exit.sh
├── start-a2a.ps1
└── REMOTE_AGENT_PROMPT.md
~~~

File roles:

- a2a_bridge_codex.py: actual A2A-to-Codex bridge.
- a2a_bridge.py: wrapper entry point. Its filename intentionally does not contain the word codex.
- a2a_client.py: standard-library client that reads the Agent Card and sends a message.
- start-a2a-after-exit.sh: recommended safe foreground launcher on Linux.
- start-a2a.sh: simple direct launcher when the conversation is already cleanly closed.
- start-a2a.ps1: foreground launcher for Windows.
- requirements.txt: tested Python dependencies.
- README.md: short local README.
- HANDOFF.md: this complete operational document.
- REMOTE_AGENT_PROMPT.md: copy-paste message for an agent with no prior context.

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
tar -czf a2a-bridge-bundle.tar.gz HANDOFF.md README.md REMOTE_AGENT_PROMPT.md requirements.txt a2a_bridge.py a2a_bridge_codex.py a2a_client.py start-a2a.sh start-a2a-after-exit.sh start-a2a.ps1
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
a2a-sdk==1.2.2
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
Puente A2A en primer plano: http://TAILSCALE-IP:8766
El proceso quedará en standby esperando peticiones.
Pulsa Ctrl+C en esta terminal para detenerlo.
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
.venv/bin/python a2a_bridge.py --host "$TAILSCALE_IP" --port 8766 --base-url "http://$TAILSCALE_IP:8766" --thread-id "CURRENT_THREAD_UUID" --context-id "CURRENT_CONTEXT_ID" --timeout 240
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
- streaming false.
- Supported text input and output modes.

The bridge is synchronous. The HTTP request remains open until Codex finishes or the timeout occurs. The client should wait at least five minutes.

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
8. Wait up to 300 seconds.
9. Inspect the complete JSON-RPC response.
10. Avoid automatic retries after a timeout.

The remote agent does not need the server's Codex credentials or thread UUID.

### Recommended Python client

Copy a2a_client.py to the remote machine. It uses only Python's standard library:

~~~bash
python3 a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"
~~~

On Windows:

~~~powershell
py a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"
~~~

### cURL fallback

If a2a_client.py is not available, use cURL:

~~~bash
curl --max-time 300 -sS -X POST "http://TAILSCALE-IP:8766/" -H "Content-Type: application/json" -H "A2A-Version: 1.0" --data-raw '{"jsonrpc":"2.0","id":"NEW-REQUEST-UUID","method":"SendMessage","params":{"message":{"messageId":"NEW-MESSAGE-UUID","role":"ROLE_USER","contextId":"CONTEXT-ID-FROM-AGENT-CARD","parts":[{"text":"Hello. Please confirm that you received this message."}]}}}'
~~~

The answer normally appears at:

~~~text
result.message.parts[].text
~~~

The context ID must be copied exactly from the Agent Card.

## 12. Direct message for the remote agent

After the bridge is running, the server operator can send this to the remote agent:

~~~text
The A2A bridge for my existing Codex conversation is now running over Tailscale.

Read the Agent Card first:
http://TAILSCALE-IP:8766/.well-known/agent-card.json

Use the endpoint and contextId announced by that card. Send A2A 1.0
JSON-RPC requests with method SendMessage, one at a time. Wait up to
300 seconds for each response and inspect the JSON-RPC body for an error
even when the HTTP status is 200.

The bridge is synchronous and does not stream tokens. Do not retry blindly
after a timeout because Codex may already have processed the request.
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
7. Give the remote agent the Agent Card URL printed by the bridge.
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

Wait for the current response to finish and press Ctrl+C in the terminal running the bridge.

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

### Timeout

The bridge uses a Codex timeout of 240 seconds and the standard client waits 300 seconds.

If a request times out:

1. Inspect the bridge terminal.
2. Check whether Codex is still running.
3. Do not immediately resend the same message.
4. Confirm whether the original request was already appended to the conversation.

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

Use the PowerShell launcher start-a2a.ps1:

If start-a2a.ps1 is not already present in the bundle, create it next to
a2a_bridge.py with this content:

~~~powershell
param(
    [Parameter(Mandatory = $true)]
    [string]$ThreadId,
    [string]$ContextId = "",
    [int]$Port = 8766
)

$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing virtual-environment Python: $python"
}

$tailscaleIp = (& tailscale ip -4 | Select-Object -First 1).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($tailscaleIp)) {
    throw "Tailscale did not return an IPv4 address."
}

if ([string]::IsNullOrWhiteSpace($ContextId)) {
    $compactId = $ThreadId.Replace("-", "")
    if ($compactId.Length -lt 12) {
        throw "ThreadId does not look like a UUID."
    }
    $ContextId = "codex-" + $compactId.Substring(0, 12)
}

$baseUrl = "http://" + $tailscaleIp + ":" + $Port
$arguments = @(
    (Join-Path $PSScriptRoot "a2a_bridge.py"),
    "--host", $tailscaleIp,
    "--port", "$Port",
    "--base-url", $baseUrl,
    "--thread-id", $ThreadId,
    "--context-id", $ContextId,
    "--timeout", "240"
)

Write-Host "A2A bridge in foreground: $baseUrl"
Write-Host "Press Ctrl+C in this terminal to stop it."

& $python @arguments
exit $LASTEXITCODE
~~~

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
- [ ] The response contains result.message.parts[].text.
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
python3 a2a_client.py "Message for the Codex conversation" "http://TAILSCALE-IP:8766"
~~~

Stop:

~~~text
Ctrl+C in the bridge terminal
~~~

The bridge is active while that terminal is occupied. It is stopped when Ctrl+C returns the shell prompt.
