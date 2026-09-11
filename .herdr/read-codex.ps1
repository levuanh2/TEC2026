# Read the Codex pane's recent output for this repo.
param([int]$Lines = 150)
. "$PSScriptRoot\find-agents.ps1"
$target = Find-HerdrAgent -Kind codex -RequireOne
herdr agent read $target.pane_id --source recent-unwrapped --lines $Lines
