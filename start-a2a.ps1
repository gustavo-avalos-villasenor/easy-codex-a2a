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
$cardUrl = $baseUrl + "/.well-known/agent-card.json"
$arguments = @(
    (Join-Path $PSScriptRoot "a2a_bridge.py"),
    "--host", $tailscaleIp,
    "--port", "$Port",
    "--base-url", $baseUrl,
    "--thread-id", $ThreadId,
    "--context-id", $ContextId,
    "--timeout", "0"
)

Write-Host ""
Write-Host "================ A2A connection instructions ================"
Write-Host "Repository:      https://github.com/gustavo-avalos-villasenor/easy-codex-a2a"
Write-Host "Branch:          main (asynchronous callback workflow)"
Write-Host "Agent Card:      $cardUrl"
Write-Host "JSON-RPC URL:    $baseUrl/"
Write-Host "A2A context ID:  $ContextId"
Write-Host ""
Write-Host "Copy this message to the remote agent:"
Write-Host @"
Clone and read this repository:
https://github.com/gustavo-avalos-villasenor/easy-codex-a2a
The default main branch already contains the asynchronous callback workflow.

Read the Agent Card first:
$cardUrl

Use the announced contextId. For long tasks, obtain this agent's own current
Codex conversation UUID and run:
python a2a_client.py --submit-and-resume "Long task" "$baseUrl" "CLIENT-CODEX-CONVERSATION-UUID"

This returns immediately and starts a detached watcher outside the model turn.
The watcher uses one SubscribeToTask connection, does not poll GetTask, and
resumes the client Codex conversation once when the task finishes. Do not run
--wait or resend the request. Close the client conversation after submission;
the watcher retries if its writer lock is still active.

If the client cannot provide a Codex conversation UUID, use:
python a2a_client.py --submit "Long task" "$baseUrl"
python a2a_client.py --wait "TASK-ID-FROM-SUBMIT" "$baseUrl"

Test command from the cloned repository:
python a2a_client.py "Hello. Please confirm that you received this message." "$baseUrl"
"@
Write-Host "=============================================================="
Write-Host ""
Write-Host "A2A bridge in foreground: $baseUrl"
Write-Host "The process will remain in standby waiting for requests."
Write-Host "Press Ctrl+C in this terminal to stop it."
Write-Host ""

& $python @arguments
exit $LASTEXITCODE
