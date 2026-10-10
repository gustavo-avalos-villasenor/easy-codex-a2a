# Easy Codex A2A

This repository exposes one existing Codex conversation as a durable A2A 1.0
agent over a private Tailscale connection. The default `main` branch includes
the asynchronous callback workflow for long-running tasks:

- `--submit-and-resume` returns immediately. A detached local watcher waits for
  the task outside the model turn and resumes the calling Codex conversation
  once when the result is ready. This is the recommended mode for long work.
- `--submit` still returns a task ID immediately, and `--wait TASK_ID` remains
  available for clients that cannot resume a Codex CLI conversation.
- The default client command sends one streaming request and keeps one SSE
  connection open until completion.

There is no periodic status polling. Completed tasks persist in SQLite across
bridge restarts. A task active during a bridge restart is marked failed on the
next startup rather than silently duplicated.

Use the repository's default `main` branch. The callback implementation was
promoted from `async-resume-callback` after the long-task test succeeded. The
older `async-resume-callback`, `async-tasks`, and `durable-async-tasks` branches
are historical rollback/reference points only.

~~~bash
git clone https://github.com/gustavo-avalos-villasenor/easy-codex-a2a.git
cd easy-codex-a2a
~~~

Repository used for the protocol and SDK:

https://github.com/a2aproject/a2a

This repository contains the custom bridge that connects that protocol to
Codex CLI. A new agent with no prior context should read HANDOFF.md
completely before running anything.

## Communication model

The server/worker agent owns the existing Codex conversation and runs the
foreground bridge. The remote/client agent sends A2A tasks and, for long work,
uses `--submit-and-resume`; a detached watcher waits outside the client model
turn and resumes that client conversation once with the final result.

This is asynchronous request/result communication, not two independent
Codex conversations writing to each other spontaneously. The server processes
one request at a time against its one exposed conversation. The client can
send more sequential requests after each result. `curl` and the `--submit` /
`--wait` commands remain portable fallbacks for clients that cannot resume a
Codex conversation.

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

For long or uncertain work, a remote Codex CLI agent should submit and let the
detached watcher resume its own conversation when the task completes:

~~~bash
python3 a2a_client.py --submit-and-resume \
  "Long task for the Codex agent" \
  "http://TAILSCALE-IP:8766" \
  "CLIENT-CODEX-CONVERSATION-UUID"
~~~

That command returns immediately. It starts a non-model watcher process, which
holds one SSE connection without consuming model tokens. When the task reaches
a terminal state, the watcher resumes `CLIENT-CODEX-CONVERSATION-UUID` once with
the result. The client conversation must be closed after submission so its
writer lock is available; if it is still open, the watcher retries every 30
seconds. Do not run `--wait` or submit the same message again.

If the remote agent cannot resume a Codex CLI conversation, use the portable
task-ID mode instead:

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
