# Easy Codex A2A

This repository exposes one existing Codex conversation as an A2A 1.0 agent
over a private Tailscale connection.

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

The remote agent can use:

~~~bash
python3 a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"
~~~

The Agent Card is:

~~~text
http://TAILSCALE-IP:8766/.well-known/agent-card.json
~~~

## Full documentation

See HANDOFF.md for installation, protocol details, context and thread rules,
Windows instructions, troubleshooting, security, and shutdown.
