<#
.SYNOPSIS
  PR composition summary by git AUTHOR (agents and people), with line-of-code
  percentages. Based on git identity (Author field), not on message trailers.
.EXAMPLE
  scripts/pr-author-summary.ps1 main
#>
param([string]$Base = "main")
$ErrorActionPreference = 'Stop'
# Locale-independent numeric format (dot decimal, matching the .sh version).
[System.Threading.Thread]::CurrentThread.CurrentCulture = [System.Globalization.CultureInfo]::InvariantCulture

# Determine the PR commit range (base..HEAD).
$range = "HEAD"
git rev-parse --verify -q $Base *> $null
if ($LASTEXITCODE -eq 0) {
    $mb = (git merge-base $Base HEAD).Trim()
    $range = "$mb..HEAD"
}

$authors = [ordered]@{}
$current = $null
git log --no-merges --numstat --format='__C__%an' $range | ForEach-Object {
    $line = $_
    if ($line.StartsWith('__C__')) {
        $current = $line.Substring(5)
        if (-not $authors.Contains($current)) {
            $authors[$current] = [pscustomobject]@{ Commits = 0; Added = 0; Deleted = 0; Ch = 0 }
        }
        $authors[$current].Commits++
    }
    elseif ($line -and $current) {
        $c = $line -split "`t"
        if ($c.Count -ge 3) {
            if ($c[0] -match '^\d+$') { $authors[$current].Added += [int]$c[0]; $authors[$current].Ch += [int]$c[0] }
            if ($c[1] -match '^\d+$') { $authors[$current].Deleted += [int]$c[1]; $authors[$current].Ch += [int]$c[1] }
        }
    }
}

$grand = 0
foreach ($a in $authors.Keys) { $grand += $authors[$a].Ch }

$out = @('<!-- pr-author-summary -->', '## 🧮 PR composition by author', '')
if ($grand -eq 0) {
    $out += '_No line changes to measure._'
    $out -join "`n"
    return
}

$ordered = $authors.GetEnumerator() | Sort-Object { $_.Value.Ch } -Descending
$headline = ($ordered | ForEach-Object { "{0} · {1:N0}%" -f $_.Key, (100.0 * $_.Value.Ch / $grand) }) -join "  ·  "
$out += "**$headline**"
$out += ''
$out += '| Author | Commits | +Lines | -Lines | Churn | % |'
$out += '|--------|--------:|-------:|-------:|------:|--:|'

$tadd = 0; $tdel = 0; $tcom = 0
foreach ($e in $ordered) {
    $v = $e.Value; $tadd += $v.Added; $tdel += $v.Deleted; $tcom += $v.Commits
    $out += "| {0} | {1} | +{2} | -{3} | {4} | {5:N1}% |" -f $e.Key, $v.Commits, $v.Added, $v.Deleted, $v.Ch, (100.0 * $v.Ch / $grand)
}
$out += "| **Total** | {0} | +{1} | -{2} | {3} | 100% |" -f $tcom, $tadd, $tdel, $grand
$out += ''
$out += '> ℹ️ _Not a performance metric, not a humans-vs-agents comparison._'
$out += '> _It is traceability of **who wrote what and how** — like the usual Author/Committer fields on every commit and PR._'

$out -join "`n"
