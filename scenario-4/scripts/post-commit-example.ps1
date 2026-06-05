<#
.SYNOPSIS
  Post-commit audit example: records the actor of every commit in
  .git/agent-audit/commits.log. Intended to be wired in as a post-commit hook.
#>
$ErrorActionPreference = 'Stop'

$dir = ".git/agent-audit"
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }

$commit = (git rev-parse HEAD).Trim()
$body = (git log -1 --pretty=%B) -join "`n"

$actor = ($body -split "`n" | Where-Object { $_ -match '^(Agent|Person):' } | Select-Object -First 1)

Add-Content -Path "$dir/commits.log" -Value "$commit|$actor"
