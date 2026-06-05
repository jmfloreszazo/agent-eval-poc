#!/usr/bin/env bash
# PR composition summary by git AUTHOR (agents and people), with
# line-of-code percentages. Based on git identity (Author field), not
# on message trailers.
#
# Usage: scripts/pr-author-summary.sh [base-branch]   (default: main)
# Output: Markdown ready to post as the PR summary.
set -euo pipefail

BASE="${1:-main}"

# Determine the PR commit range (base..HEAD).
if git rev-parse --verify -q "$BASE" >/dev/null; then
  MB="$(git merge-base "$BASE" HEAD)"
  RANGE="$MB..HEAD"
else
  # No valid base branch: summarise the whole reachable history.
  RANGE="HEAD"
fi

git log --no-merges --numstat --format='__C__%an' $RANGE | awk '
  /^__C__/ { author = substr($0, 6); commits[author]++; seen[author]=1; next }
  NF >= 3 {
    if ($1 ~ /^[0-9]+$/) { add[author] += $1; ch[author] += $1 }
    if ($2 ~ /^[0-9]+$/) { del[author] += $2; ch[author] += $2 }
  }
  END {
    print "<!-- pr-author-summary -->"
    print "## 🧮 PR composition by author"
    print ""

    grand = 0; tadd = 0; tdel = 0; tcom = 0
    for (a in seen) { grand += ch[a]; tadd += add[a]; tdel += del[a]; tcom += commits[a] }

    if (grand == 0) { print "_No line changes to measure._"; exit }

    # Sort by churn descending (insertion sort on the keys).
    n = 0
    for (a in seen) { order[n++] = a }
    for (i = 0; i < n; i++)
      for (j = i + 1; j < n; j++)
        if (ch[order[j]] > ch[order[i]]) { t = order[i]; order[i] = order[j]; order[j] = t }

    # Headline: "Agent-Dev · 90%  ·  Person · 10%"
    headline = ""
    for (i = 0; i < n; i++) {
      a = order[i]
      headline = headline sprintf("%s%s · %.0f%%", (i ? "  ·  " : ""), a, 100 * ch[a] / grand)
    }
    print "**" headline "**"
    print ""

    print "| Author | Commits | +Lines | -Lines | Churn | % |"
    print "|--------|--------:|-------:|-------:|------:|--:|"
    for (i = 0; i < n; i++) {
      a = order[i]
      printf "| %s | %d | +%d | -%d | %d | %.1f%% |\n", a, commits[a], add[a]+0, del[a]+0, ch[a], 100 * ch[a] / grand
    }
    printf "| **Total** | %d | +%d | -%d | %d | 100%% |\n", tcom, tadd, tdel, grand
    print ""
    print "> ℹ️ _Not a performance metric, not a humans-vs-agents comparison._"
    print "> _It is traceability of **who wrote what and how** — like the usual Author/Committer fields on every commit and PR._"
  }
'
