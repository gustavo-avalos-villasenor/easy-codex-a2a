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
