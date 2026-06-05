<#
.SYNOPSIS
  MIXED commit: a single commit with contributions from several actors.
  Attribution is per FILE; computes the % of lines per actor, writes the
  breakdown into the commit body and sets the Author to the OWNER (highest %,
  ideally >50%).
.EXAMPLE
  scripts/mixed-commit.ps1 "Add power op with tests and docs" `
    "Agent-Dev=calculator.py" "Agent-QA=test_calculator.py" "Person=README.md"
.NOTES
  - Actors matching "Agent*" use the fake email <agent-x>@agents.local.
  - Any other actor (e.g. "Person") uses the real repo identity.
  - Use space-free tokens as actor names (Agent-Dev, Agent-QA, Person).
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Message,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Pairs
)
$ErrorActionPreference = 'Stop'
if (-not $Pairs -or $Pairs.Count -lt 1) { Write-Error "Missing at least one Actor=pattern pair"; exit 1 }

$actors = [ordered]@{}
foreach ($pair in $Pairs) {
    $i = $pair.IndexOf('=')
    if ($i -lt 1) { Write-Error "Invalid pair (missing '='): $pair"; exit 1 }
    $actor = $pair.Substring(0, $i)
    $pattern = $pair.Substring($i + 1)

    git add -- $pattern
    $add = 0; $del = 0
    git diff --cached --numstat -- $pattern | ForEach-Object {
        $c = $_ -split "`t"
        if ($c[0] -match '^\d+$') { $add += [int]$c[0] }
        if ($c[1] -match '^\d+$') { $del += [int]$c[1] }
    }
    if (-not $actors.Contains($actor)) { $actors[$actor] = [pscustomobject]@{ Added = 0; Deleted = 0; Ch = 0 } }
    $actors[$actor].Added += $add
    $actors[$actor].Deleted += $del
}

$total = 0; $tadd = 0; $tdel = 0
foreach ($a in $actors.Keys) {
    $actors[$a].Ch = $actors[$a].Added + $actors[$a].Deleted
    $total += $actors[$a].Ch; $tadd += $actors[$a].Added; $tdel += $actors[$a].Deleted
}
if ($total -eq 0) { Write-Error "No staged changes to commit."; exit 1 }

function Pct($n) { [math]::Round(100.0 * $n / $total) }

$ordered = $actors.GetEnumerator() | Sort-Object { $_.Value.Ch } -Descending
$owner = $ordered[0].Key
$pOwner = Pct $actors[$owner].Ch

if ($owner -match '^[Aa]gent') {
    $oemail = ($owner.ToLower() -replace ' ', '-') + '@agents.local'
    $oname = $owner
    $tagline = "Agent: $owner"
}
else {
    $oname = (git config user.name)
    $oemail = (git config user.email)
    $tagline = "Person: $oname"
}
$majority = if ($pOwner -gt 50) { "majority" } else { "plurality, <50%" }

$comp = "Composition (per file):"
foreach ($e in $ordered) {
    $a = $e.Key; $v = $e.Value
    $comp += "`n  ${a}: +$($v.Added) -$($v.Deleted) churn:$($v.Ch) ($(Pct $v.Ch)%)"
}

$net = $tadd - $tdel
$full = @"
$Message

$tagline
LoC: +$tadd -$tdel net:$net
$comp
Owner: $owner ($pOwner% — $majority)
"@

git commit --author="$oname <$oemail>" -m $full
Write-Host "✓ Mixed commit. Owner: $owner ($pOwner%) → Author=$oname <$oemail>"
