#!/usr/bin/env bash
# MIXED commit: a single commit with contributions from several actors.
# Attribution is per FILE (each file belongs to one actor); computes the
# % of lines per actor, writes the breakdown into the commit body and
# sets the Author to the OWNER = actor with the highest share (ideally >50%).
#
# Usage:
#   scripts/mixed-commit.sh "<message>" "<Actor>=<pattern>" ["<Actor>=<pattern>" ...]
#
# Example:
#   scripts/mixed-commit.sh "Add power op with tests and docs" \
#     "Agent-Dev=calculator.py" \
#     "Agent-QA=test_calculator.py" \
#     "Person=README.md"
#
# Notes:
#   - Actors matching "Agent*" use the fake email <agent-x>@agents.local.
#   - Any other actor (e.g. "Person") uses the real repo identity.
#   - Use space-free tokens as actor names (Agent-Dev, Agent-QA, Person).
set -euo pipefail

MESSAGE="${1:?Missing commit message}"; shift
[ "$#" -ge 1 ] || { echo "Missing at least one Actor=pattern pair" >&2; exit 1; }

declare -A FILE_ACTOR
for pair in "$@"; do
  actor="${pair%%=*}"
  pattern="${pair#*=}"
  [ "$actor" = "$pair" ] && { echo "Invalid pair (missing '='): $pair" >&2; exit 1; }
  for f in $pattern; do
    [ -e "$f" ] || continue
    git add -- "$f"
    FILE_ACTOR["$f"]="$actor"
  done
done

declare -A ADD DEL CH
TADD=0; TDEL=0; TOTAL=0
UNASSIGNED=0
while IFS=$'\t' read -r a d path; do
  actor="${FILE_ACTOR[$path]:-Unassigned}"
  [ "$actor" = "Unassigned" ] && UNASSIGNED=1
  if [[ "$a" =~ ^[0-9]+$ ]]; then ADD[$actor]=$(( ${ADD[$actor]:-0} + a )); CH[$actor]=$(( ${CH[$actor]:-0} + a )); TADD=$((TADD+a)); TOTAL=$((TOTAL+a)); fi
  if [[ "$d" =~ ^[0-9]+$ ]]; then DEL[$actor]=$(( ${DEL[$actor]:-0} + d )); CH[$actor]=$(( ${CH[$actor]:-0} + d )); TDEL=$((TDEL+d)); TOTAL=$((TOTAL+d)); fi
done < <(git diff --cached --numstat)

[ "$TOTAL" -gt 0 ] || { echo "No staged changes to commit." >&2; exit 1; }
[ "$UNASSIGNED" -eq 1 ] && echo "⚠ Some staged files have no actor assigned (shown as 'Unassigned')." >&2

pct() { echo $(( (100 * $1 + TOTAL / 2) / TOTAL )); }

# Owner = actor with the highest churn (excluding 'Unassigned').
OWNER=""; OWNERCH=-1
for a in "${!CH[@]}"; do
  [ "$a" = "Unassigned" ] && continue
  if [ "${CH[$a]}" -gt "$OWNERCH" ]; then OWNERCH="${CH[$a]}"; OWNER="$a"; fi
done
POWNER=$(pct "$OWNERCH")

# Owner identity as Author + tag line for the commit-msg hook.
case "$OWNER" in
  Agent*|agent*)
    OEMAIL="$(echo "$OWNER" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')@agents.local"
    ONAME="$OWNER"
    TAGLINE="Agent: $OWNER"
    ;;
  *)
    ONAME="$(git config user.name)"
    OEMAIL="$(git config user.email)"
    TAGLINE="Person: $ONAME"
    ;;
esac

# Majority label.
if [ "$POWNER" -gt 50 ]; then MAJORITY="majority"; else MAJORITY="plurality, <50%"; fi

# Breakdown sorted by churn descending.
COMP="Composition (per file):"
while read -r ch a; do
  COMP+=$'\n'"  $a: +${ADD[$a]:-0} -${DEL[$a]:-0} churn:$ch ($(pct "$ch")%)"
done < <(for a in "${!CH[@]}"; do echo "${CH[$a]} $a"; done | sort -rn)

FULL="$MESSAGE

$TAGLINE
LoC: +$TADD -$TDEL net:$((TADD-TDEL))
$COMP
Owner: $OWNER ($POWNER% — $MAJORITY)"

git commit --author="$ONAME <$OEMAIL>" -m "$FULL"

echo "✓ Mixed commit. Owner: $OWNER ($POWNER%) → Author=$ONAME <$OEMAIL>"
