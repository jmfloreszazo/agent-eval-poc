#!/usr/bin/env bash
# Automatic commit with agent traceability and line-of-code (LoC) count.
# Usage: scripts/agent-commit.sh "<Agent>" "<commit message>"
#
# Stages everything, computes added/deleted lines from the staged diff and
# creates the commit with the trailers:
#   Agent: <name>
#   LoC: +A -B net:N
set -euo pipefail

AGENT="${1:?Missing agent name (e.g. Agent-Dev)}"
MSG="${2:?Missing commit message}"

git add -A

# LoC count over the staged diff (ignores binaries flagged with '-')
read -r ADD DEL < <(
  git diff --cached --numstat |
  awk '$1 ~ /^[0-9]+$/ { a += $1 } $2 ~ /^[0-9]+$/ { d += $2 } END { print a+0, d+0 }'
)

if [ "$ADD" -eq 0 ] && [ "$DEL" -eq 0 ]; then
  echo "No staged changes to commit." >&2
  exit 1
fi

NET=$(( ADD - DEL ))

# Agent identity as the commit AUTHOR; the COMMITTER stays as the human
# configured in the repo (responsible/supervisor).
EMAIL="$(echo "$AGENT" | tr '[:upper:]' '[:lower:]')@agents.local"

git commit \
  --author="$AGENT <$EMAIL>" \
  -m "$MSG" \
  -m "Agent: $AGENT" \
  -m "LoC: +$ADD -$DEL net:$NET"

echo "✓ Commit by $AGENT created (author=$AGENT <$EMAIL>, +$ADD -$DEL net:$NET)"
