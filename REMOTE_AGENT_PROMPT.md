# Message to the Remote Agent

Send the following message to an agent that has no prior context:

~~~text
Clone and read this repository first:
https://github.com/gustavo-avalos-villasenor/easy-codex-a2a
After cloning, select the async-tasks branch:
git fetch origin async-tasks
git switch --track origin/async-tasks

It contains the complete A2A bridge for an existing Codex conversation,
including the upstream A2A repository reference, Python bridge, client,
Linux launchers, Windows launcher, and HANDOFF.md.

The server-side Codex agent must use the same conversation in which this
setup is being mounted. Do not create a new Codex conversation and do not
select a conversation by name or by most-recent-session. The server must
obtain its current conversation UUID from its runtime context and pass that
UUID to the launcher.

The server operator must first type /exit in the interactive Codex session,
close Codex Desktop or VS Code for that conversation, and run the foreground
launcher from the repository. The terminal must remain occupied while the
bridge is active.

After the server shares the Agent Card URL, read:
http://TAILSCALE-IP:8766/.well-known/agent-card.json

Use the endpoint and contextId announced by that card. Send one A2A 1.0
JSON-RPC request with method SendStreamingMessage, one message at a time. Use
a new request UUID and message UUID for every request. Keep the SSE connection
open until the stream reports a terminal task state. Do not poll GetTask: the
single stream is the wait mechanism, so long Codex work is not followed by a
second status timeout. Inspect every streamed JSON-RPC envelope for an error.
Do not retry automatically if the connection drops because Codex may already
have processed the request.

The included standard-library client performs this one streaming request:

python3 a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"

It prints the final answer and remains blocked in that one command while
Codex works. The final text is normally in
result.statusUpdate.status.message.parts[].text.
~~~

The server operator must replace TAILSCALE-IP with the IP printed by Tailscale.
