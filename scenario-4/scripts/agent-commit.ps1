<#
.SYNOPSIS
  Automatic commit with agent traceability and line-of-code (LoC) count.
.EXAMPLE
  scripts/agent-commit.ps1 -Agent "Agent-Dev" -Message "Implement ticket creation"
#>
param(
    [Parameter(Mandatory = $true)][string]$Agent,
    [Parameter(Mandatory = $true)][string]$Message
)
$ErrorActionPreference = 'Stop'

git add -A

# LoC count over the staged diff (ignores binaries flagged with '-')
$add = 0; $del = 0
git diff --cached --numstat | ForEach-Object {
    $cols = $_ -split "`t"
    if ($cols[0] -match '^\d+$') { $add += [int]$cols[0] }
    if ($cols[1] -match '^\d+$') { $del += [int]$cols[1] }
}

if ($add -eq 0 -and $del -eq 0) {
    Write-Error "No staged changes to commit."
    exit 1
}

$net = $add - $del

# Agent identity as the commit AUTHOR; the COMMITTER stays as the human
# configured in the repo (responsible/supervisor).
$email = "$($Agent.ToLower())@agents.local"

git commit --author="$Agent <$email>" -m $Message -m "Agent: $Agent" -m "LoC: +$add -$del net:$net"

Write-Host "✓ Commit by $Agent created (author=$Agent <$email>, +$add -$del net:$net)"
