<#
.SYNOPSIS
  Legacy variant: per-actor line summary in a PR using the message TRAILERS
  (Agent:/Person:) instead of the git Author field used by pr-author-summary.ps1.
.EXAMPLE
  scripts/pr-agent-summary.ps1 main
#>
param([string]$Base = "main")
$ErrorActionPreference = 'Stop'

$mb = (git merge-base $Base HEAD).Trim()
$range = "$mb..HEAD"

$added = @{}; $deleted = @{}
foreach ($commit in (git rev-list $range)) {
    $body = (git log -1 --pretty=%B $commit) -join "`n"

    $actor = $null
    $m = [regex]::Match($body, '(?m)^Agent:\s*(.+)$')
    if ($m.Success) { $actor = $m.Groups[1].Value.Trim() }
    else {
        $m = [regex]::Match($body, '(?m)^Person:\s*(.+)$')
        if ($m.Success) { $actor = $m.Groups[1].Value.Trim() }
    }
    if (-not $actor) { $actor = 'Unknown' }

    $a = 0; $d = 0
    git show --numstat --format="" $commit | ForEach-Object {
        $c = $_ -split "`t"
        if ($c.Count -ge 2) {
            if ($c[0] -match '^\d+$') { $a += [int]$c[0] }
            if ($c[1] -match '^\d+$') { $d += [int]$c[1] }
        }
    }

    if (-not $added.ContainsKey($actor)) { $added[$actor] = 0; $deleted[$actor] = 0 }
    $added[$actor] += $a; $deleted[$actor] += $d
}

Write-Output "# Contribution"
foreach ($actor in $added.Keys) {
    $total = $added[$actor] + $deleted[$actor]
    Write-Output ("{0} +{1} -{2} total:{3}" -f $actor, $added[$actor], $deleted[$actor], $total)
}
