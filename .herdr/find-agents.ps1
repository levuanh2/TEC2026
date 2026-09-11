<#
Dynamic Herdr agent discovery for this repo.

Pane IDs are per-session and volatile (they change every time Herdr/agents
restart) — never hardcode one in a persistent file. Always discover by
repo cwd + agent kind at call time.

Usage as a script:  .\find-agents.ps1 [-Kind claude|codex] [-ExcludeSelf]
Usage as a library:  . .\find-agents.ps1 ; Find-HerdrAgent -Kind codex -RequireOne
#>
param(
    [ValidateSet('claude', 'codex')] [string]$Kind,
    [switch]$ExcludeSelf
)

function Find-HerdrAgent {
    param(
        [ValidateSet('claude', 'codex')] [string]$Kind,
        [switch]$ExcludeSelf,
        [switch]$RequireOne
    )
    $repoRoot = (git rev-parse --show-toplevel 2>$null)
    if (-not $repoRoot) { Write-Error "Not inside a git repository."; exit 1 }
    $repoRoot = ($repoRoot -replace '/', '\').TrimEnd('\')

    $raw = herdr agent list 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Error "herdr agent list failed: $raw"; exit 1 }
    $agents = ($raw | ConvertFrom-Json).result.agents |
        Where-Object { ($_.cwd.TrimEnd('\')) -ieq $repoRoot }
    if ($Kind) { $agents = $agents | Where-Object { $_.agent -eq $Kind } }
    if ($ExcludeSelf -and $env:HERDR_PANE_ID) {
        $agents = $agents | Where-Object { $_.pane_id -ne $env:HERDR_PANE_ID }
    }

    if ($RequireOne) {
        $count = @($agents).Count
        if ($count -eq 0) {
            Write-Error "No matching agent found for repo $repoRoot (kind=$Kind). Run 'herdr agent list' manually."
            exit 1
        }
        if ($count -gt 1) {
            Write-Error "Multiple matching agents for repo $repoRoot (kind=$Kind) - refusing to guess which pane."
            $agents | Format-Table pane_id, agent_status, terminal_title_stripped | Out-String | Write-Host
            Write-Error "Target one explicitly: herdr agent prompt <pane_id> `"...`""
            exit 1
        }
        return $agents[0]
    }
    return $agents
}

if ($MyInvocation.InvocationName -ne '.') {
    Find-HerdrAgent -Kind $Kind -ExcludeSelf:$ExcludeSelf |
        Select-Object pane_id, agent, agent_status, terminal_title_stripped |
        Format-Table -AutoSize
}
