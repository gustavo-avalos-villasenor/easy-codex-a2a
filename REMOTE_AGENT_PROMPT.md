# Message to the Remote Agent

Send the following message to an agent that has no prior context:

~~~text
Clone and read this repository first:
https://github.com/gustavo-avalos-villasenor/easy-codex-a2a

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

Use the endpoint and contextId announced by that card. Send A2A 1.0
JSON-RPC requests with method SendMessage, one at a time. Use a new request
UUID and message UUID for every request. Wait up to 300 seconds. Inspect the
JSON-RPC body for an error even when HTTP status is 200. Do not retry blindly
after a timeout because Codex may already have processed the request.

The bridge is synchronous and does not stream tokens. The response text is
normally in result.message.parts[].text.
~~~

The server operator must replace TAILSCALE-IP with the IP printed by Tailscale.
