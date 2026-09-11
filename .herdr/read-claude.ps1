# Read the other Claude pane's recent output for this repo (excludes self).
param([int]$Lines = 150)
. "$PSScriptRoot\find-agents.ps1"
$target = Find-HerdrAgent -Kind claude -ExcludeSelf -RequireOne
herdr agent read $target.pane_id --source recent-unwrapped --lines $Lines
