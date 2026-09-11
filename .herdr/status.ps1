# List every Claude/Codex pane (including self) currently open on this repo.
. "$PSScriptRoot\find-agents.ps1"
Find-HerdrAgent | Select-Object pane_id, agent, agent_status, terminal_title_stripped | Format-Table -AutoSize
