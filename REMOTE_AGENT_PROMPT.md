# Message to the Remote Agent

Send the following message to an agent that has no prior context:

~~~text
Clone and read this repository first:
https://github.com/gustavo-avalos-villasenor/easy-codex-a2a
The default main branch is the canonical version and already includes the
asynchronous callback workflow. Do not switch to an older branch.

It contains the complete A2A bridge for an existing Codex conversation,
including the upstream A2A repository reference, Python bridge, client,
Linux launchers, Windows launcher, and HANDOFF.md.

There are two cooperating sides. The server/worker agent owns one existing
Codex conversation and runs the foreground bridge. This client agent submits
tasks and, for long work, uses a detached watcher that resumes this client
conversation once with the final result. The workflow is asynchronous
request/result communication; it is not a fully symmetric peer chat.

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
request, use callback mode if this is a Codex CLI conversation. First obtain
this agent's own current conversation UUID from the runtime context, then run:

python3 a2a_client.py --submit-and-resume "Your request" \
  "http://TAILSCALE-IP:8766" "THIS-AGENT-CODEX-CONVERSATION-UUID"

--submit-and-resume sends SendMessage with returnImmediately=true and exits
immediately. It starts a detached watcher outside the model turn. The watcher
uses one SubscribeToTask SSE connection, does not poll GetTask, and resumes this
same Codex conversation once when the remote result is terminal. After the
command returns, let this conversation turn finish and do not run --wait or
resubmit the request. The watcher state and log paths are printed in its JSON
response. The watcher uses the same user, CODEX_HOME, Codex login, and working
directory as this agent.

The callback conversation must not remain open in Codex Desktop or VS Code.
If its writer lock is still held when the remote task finishes, the watcher
waits and retries; close the interactive owner rather than starting another
submission.

If this agent is not a Codex CLI conversation or cannot provide its own UUID,
use the portable task-ID mode instead:

python3 a2a_client.py --submit "Your request" "http://TAILSCALE-IP:8766"
python3 a2a_client.py --wait "TASK-ID-RETURNED-BY-SUBMIT" "http://TAILSCALE-IP:8766"

--wait uses one SubscribeToTask SSE connection later; it does not poll
GetTask, but the calling agent may still consume tokens if its runtime has to
re-enter the model repeatedly while waiting. Prefer --submit-and-resume for
long work.

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
