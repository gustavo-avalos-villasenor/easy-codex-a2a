# Message to the Remote Agent

Send the following message to an agent that has no prior context:

~~~text
Clone and read this repository first:
https://github.com/gustavo-avalos-villasenor/easy-codex-a2a
After cloning, select the durable-async-tasks branch:
git fetch origin durable-async-tasks
git switch --track origin/durable-async-tasks

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

Use the endpoint and contextId announced by that card. For a long or uncertain
request, use the included standard-library client in two phases:

python3 a2a_client.py --submit "Your request" "http://TAILSCALE-IP:8766"
python3 a2a_client.py --wait "TASK-ID-RETURNED-BY-SUBMIT" "http://TAILSCALE-IP:8766"

--submit sends SendMessage with returnImmediately=true. Save the returned
taskId. The bridge keeps processing after this client process exits. --wait
uses one SubscribeToTask SSE connection later; it does not poll GetTask. This
is the preferred mode when the work can outlive the calling agent's tool
timeout.

For a short request, the one-connection form is also valid:

python3 a2a_client.py "Hello. Please confirm that you received this message." "http://TAILSCALE-IP:8766"

Use a new request UUID and message UUID for every new submission. Inspect every
JSON-RPC/SSE envelope for an error. If a connection drops, do not submit the
same message again: reattach with the existing taskId, because Codex may
already have processed the request.

The final text is normally in
result.statusUpdate.status.message.parts[].text. The server operator must
replace TAILSCALE-IP with the IP printed by Tailscale.
~~~
