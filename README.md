# Easy Codex A2A

This repository exposes one existing Codex conversation as a durable A2A 1.0
agent over a private Tailscale connection. The `durable-async-tasks` branch
supports two safe waiting modes:

- `--submit` returns a task ID immediately. The bridge continues the Codex
  work after the remote client exits; `--wait TASK_ID` attaches later over one
  SSE connection.
- The default client command sends one streaming request and keeps one SSE
  connection open until completion.

There is no periodic status polling. Completed tasks persist in SQLite across
bridge restarts. A task active during a bridge restart is marked failed on the
next startup rather than silently duplicated.

Use branch `durable-async-tasks`; `main` remains the original rollback version
and `async-tasks` is the earlier streaming-only version:

~~~bash
git clone https://github.com/gustavo-avalos-villasenor/easy-codex-a2a.git
cd easy-codex-a2a
git fetch origin durable-async-tasks
git switch --track origin/durable-async-tasks
~~~

Repository used for the protocol and SDK:

https://github.com/a2aproject/a2a

This repository contains the custom bridge that connects that protocol to
Codex CLI. A new agent with no prior context should read HANDOFF.md
completely before running anything.

## Quick start for the server user

The bridge must resume the same Codex conversation in which this setup is
being performed. It must not create a new conversation.

1. In the target Codex conversation, type /exit.
2. Close Codex Desktop, VS Code/Codex, or any other process that owns that chat.
3. Install the dependencies once:

~~~bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
~~~

4. Run the foreground launcher with the UUID of the current conversation:

~~~bash
./start-a2a-after-exit.sh UUID-OF-THE-CURRENT-CONVERSATION 8766 codex-CONTEXT-ID
~~~

5. Keep that terminal open. It is intentionally occupied in standby.
6. Copy the connection instructions printed by the launcher and send them to the remote agent.
7. When finished, press Ctrl+C in the bridge terminal.

For the current conversation, use the UUID supplied by the Codex runtime. The
tested installation used this form:

~~~bash
./start-a2a-after-exit.sh UUID-OF-THE-CURRENT-CONVERSATION 8766 codex-CONTEXT-ID
~~~

Do not use Ctrl+Z or pkill -f codex.

## Remote agent

Send the remote agent the contents of REMOTE_AGENT_PROMPT.md, together with
the Tailscale IP printed by the server launcher.

For long or uncertain work, the remote agent should detach submission from
waiting:

~~~bash
python3 a2a_client.py --submit "Long task for the Codex agent" "http://TAILSCALE-IP:8766"
python3 a2a_client.py --wait "TASK-ID-FROM-SUBMIT" "http://TAILSCALE-IP:8766"
~~~

For a short request that can keep one connection open, use:

~~~bash
python3 a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"
~~~

Neither mode runs a status-polling loop. The Agent Card is:

~~~text
http://TAILSCALE-IP:8766/.well-known/agent-card.json
~~~

To run resumed turns with GPT-5.6 Luna at low reasoning effort, set these
variables before launching the bridge:

~~~bash
export A2A_CODEX_MODEL="gpt-5.6-luna"
export A2A_CODEX_REASONING_EFFORT="low"
~~~

On Windows, use `$env:A2A_CODEX_MODEL = "gpt-5.6-luna"` and
`$env:A2A_CODEX_REASONING_EFFORT = "low"`. `gpt-5.6-luna` is the official
model ID; `luna-light` is not a separate model ID.

## Full documentation

See HANDOFF.md for installation, protocol details, context and thread rules,
Windows instructions, troubleshooting, security, and shutdown.
