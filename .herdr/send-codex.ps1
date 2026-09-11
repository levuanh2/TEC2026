# Send a prompt to the Codex pane for this repo.
param(
    [Parameter(Mandatory, Position = 0)] [string]$Message,
    [switch]$Wait,
    [int]$TimeoutMs = 120000
)
. "$PSScriptRoot\find-agents.ps1"
$target = Find-HerdrAgent -Kind codex -RequireOne
if ($Wait) {
    herdr agent prompt $target.pane_id $Message --wait --timeout $TimeoutMs
} else {
    herdr agent prompt $target.pane_id $Message
}
