#!/usr/bin/env bash
# Legacy variant: per-actor line summary in a PR using the message TRAILERS
# (Agent:/Person:) instead of the git Author field used by pr-author-summary.
BASE=${1:-main}
range=$(git merge-base $BASE HEAD)..HEAD
declare -A added
declare -A deleted
for commit in $(git rev-list $range)
do
  body=$(git log -1 --pretty=%B $commit)
  actor=$(echo "$body" | grep "^Agent:" | cut -d':' -f2- | xargs)
  if [ -z "$actor" ]; then
      actor=$(echo "$body" | grep "^Person:" | cut -d':' -f2- | xargs)
  fi
  [ -z "$actor" ] && actor="Unknown"
  read a d < <(
    git show --numstat --format="" $commit |
    awk '$1 ~ /^[0-9]+$/ {add += $1} $2 ~ /^[0-9]+$/ {del += $2} END {print add+0, del+0}'
  )
  added["$actor"]=$(( ${added["$actor"]:-0} + a ))
  deleted["$actor"]=$(( ${deleted["$actor"]:-0} + d ))
done
echo "# Contribution"
for actor in "${!added[@]}"; do
  total=$(( ${added[$actor]} + ${deleted[$actor]} ))
  echo "$actor +${added[$actor]} -${deleted[$actor]} total:$total"
done
