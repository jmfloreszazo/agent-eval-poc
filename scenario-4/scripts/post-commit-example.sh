#!/usr/bin/env bash
# Post-commit audit example: records the actor of every commit in
# .git/agent-audit/commits.log. Intended to be wired in as a post-commit hook.
mkdir -p .git/agent-audit
commit=$(git rev-parse HEAD)
body=$(git log -1 --pretty=%B)
actor=$(echo "$body" | grep -E "^(Agent|Person):" | head -1)
echo "$commit|$actor" >> .git/agent-audit/commits.log
