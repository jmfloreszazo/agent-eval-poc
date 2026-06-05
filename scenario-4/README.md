# Scenario 4 — Source-control attribution (agent vs. human in commits & PRs)

> Part of the [agent-eval-poc](../README.md) repo. See also
> [scenario-1](../scenario-1/README.md) (Phoenix + DeepEval),
> [scenario-2](../scenario-2/README.md) (Foundry evaluators) and
> [scenario-3](../scenario-3/README.md) (full governance gateway).

**TL;DR.** Scenarios 1–3 govern what an agent **does at runtime** — prompts,
tokens, cost, verdicts. This scenario governs what an agent **leaves
behind in the repository**: every commit by an agent is recorded with the
agent as `Author` and the responsible human as `Committer`, and every Pull
Request gets an auto-generated comment showing the percentage of lines
written by each agent and each human. No new system, no parallel
database — just git's native author attribution plus a GitHub Actions
workflow.

> **Purpose disclaimer (please read).** This is **not** a performance
> metric or a "humans vs. agents" leaderboard. Lines of code are
> **traceability**, not productivity — more lines is not "better" and
> less is not "worse". The goal is to answer one question on every PR:
> *"who wrote what, and how was it integrated?"* — exactly the question
> code review has always answered for humans.
> The percentage is a **churn-based proxy** (lines added/deleted): a human
> reformatting or refactoring agent code, or a rename, will skew it. The
> solid part is the chain of custody (`Author`/`Committer`); the % is
> indicative, never evidence in an IP dispute.

## How this scenario differs from the other three

| Capability | Scenario 1 | Scenario 2 | Scenario 3 | **Scenario 4 (this one)** |
| --- | --- | --- | --- | --- |
| Layer | Runtime evaluation | Runtime evaluation + safety | Runtime gateway across agents | **Source control** |
| Source of truth | Trajectory JSON | Foundry traces | App Insights spans | **Git history** |
| Question answered | "Is the agent's answer correct?" | "Is it safe?" | "Who used which model, when, at what cost?" | **"Which lines in this PR are agent-written vs. human-written?"** |
| Required runtime infra | Phoenix container + Azure OpenAI | Foundry + App Insights | All of scenario 2 + APIM | **None — git + GitHub Actions** |
| Per-PR artefact | Pytest report | Foundry eval JSONL | KQL dashboard | **Sticky PR comment** |
| Deploys in | ~5 min | ~10 min | ~30 min | **<5 min (copy scripts + enable workflow)** |
| Best for | Engineering Leader | Compliance Officer | CTO + CISO + FinOps | **Engineering Manager + Release Manager + Legal/IP** |

## How this scenario maps to commercial and OSS tools

| Capability | GitHub Copilot Metrics API | GitHub Insights | Linear / Jira "AI Sessions" | Sourcegraph Cody Analytics | GitClear | Faros AI | LinearB / Gitential | **This scenario** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Daily aggregate of accepted suggestions | ✅ | ⚠️ | ❌ | ✅ | ❌ | ⚠️ | ⚠️ | ❌ (not the goal) |
| Per-commit attribution to a *named* agent | ❌ | ❌ | ❌ | ❌ | ⚠️ guesses | ⚠️ guesses | ⚠️ guesses | ✅ via `Author` field |
| Per-PR % of lines by agent vs. by human | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | ⚠️ | ✅ sticky PR comment |
| **Human always recorded as `Committer`** (legal responsibility chain) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ — defining feature |
| Works for **any** agent (Copilot, Cursor, Claude Code, custom) | ❌ Copilot only | ❌ | ❌ | ❌ Cody only | ⚠️ | ⚠️ | ⚠️ | ✅ via `agent-commit` script |
| Mixed-author commits (per-file breakdown) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ via `mixed-commit` script |
| Local pre-push gate (test + summary before push) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ `.githooks/pre-push` |
| Vendor lock-in | Copilot only | GitHub only | per-vendor | Cody only | SaaS | SaaS | SaaS | None — git + plain GitHub Actions |

> **Reading guide.** The four rows in bold are the gap that no
> commercial product ships today. Vendor analytics tools tell you "Copilot
> generated X suggestions this week"; they cannot tell you "this PR is
> 86 % Agent-Dev, 13 % Agent-QA, 1 % person, and these three commits
> are the human's responsibility under the corporate AI policy." That
> chain-of-custody is what makes this scenario auditable.

---

## The model: agent is `Author`, human is `Committer`

Git stores **two** identities on every commit:

| Field | Meaning here |
| --- | --- |
| `Author` | Whoever wrote the code. For agent commits → `Agent-Dev <agent-dev@agents.local>` (or `Agent-QA`). |
| `Committer` | Whoever integrated the change. Always the real human running the agent. |

Result on `git log`:

```
Author: Agent-Dev <agent-dev@agents.local>         ← wrote the code
Commit: Jose María Flores Zazo <jose@example.com>  ← responsible human

    Add ticket creation

    Agent: Agent-Dev
    LoC: +28 -3 net:25
```

The `@agents.local` domain is **intentionally fake** so an agent
identity can never be confused with a real person.

## What ships in this scenario

| File | Purpose |
| --- | --- |
| [.githooks/commit-msg](.githooks/commit-msg) | Rejects commits without `Agent:` or `Person:` trailer (governance gate). |
| [.githooks/pre-push](.githooks/pre-push) | Before pushing or opening a PR: prints the per-author composition AND runs the tests as a local gate. |
| [scripts/agent-commit.sh](scripts/agent-commit.sh) · [.ps1](scripts/agent-commit.ps1) | The **only** way an agent should commit. Stages `git add -A`, computes LoC, builds the `Author=<agent>` / `Committer=<human>` commit. |
| [scripts/mixed-commit.sh](scripts/mixed-commit.sh) · [.ps1](scripts/mixed-commit.ps1) | When one commit must contain work from multiple actors: per-file breakdown, picks the majority-author as `Author`, records the split in the commit body. |
| [scripts/pr-author-summary.sh](scripts/pr-author-summary.sh) · [.ps1](scripts/pr-author-summary.ps1) | Renders the per-author Markdown table used in the PR sticky comment. |
| [scripts/pr-agent-summary.sh](scripts/pr-agent-summary.sh) · [.ps1](scripts/pr-agent-summary.ps1) | Legacy variant: same idea but based on the `Agent:` / `Person:` message trailers instead of the `Author` field. |
| [scripts/post-commit-example.sh](scripts/post-commit-example.sh) · [.ps1](scripts/post-commit-example.ps1) | Optional audit hook: appends the actor of every local commit to a logbook. |
| [.github/workflows/pr-author-summary.yml](.github/workflows/pr-author-summary.yml) | GitHub Actions: on PR open/synchronize/reopen, generates the summary and **upserts a sticky comment** identified by the HTML marker `<!-- pr-author-summary -->`. Permissions: `contents: read`, `pull-requests: write` — no secrets. |
| [.github/agents/developer.md](.github/agents/developer.md) · [tester.md](.github/agents/tester.md) | Two reference subagent definitions (compatible with Claude Code) that *always* commit through `agent-commit` so the chain-of-custody never breaks. |
| [docs/governance-agents-and-people.md](docs/governance-agents-and-people.md) | The Model A / Model B governance write-up — when to give the agent its own identity vs. its own worktree. |
| [docs/worktree-with-agents.md](docs/worktree-with-agents.md) | How to put each agent in its own `git worktree` with its own identity (the production-grade version of Model B). |
| [calculator.py](calculator.py) + [test_calculator.py](test_calculator.py) | Tiny demo code — gives the hooks and scripts something real to commit so a new contributor can see the workflow end-to-end. |

## How to read a generated PR comment

```
<!-- pr-author-summary -->
## 🧮 PR composition by author

**Agent-Dev · 86 %  ·  Agent-QA · 13 %  ·  Jose María Flores Zazo · 1 %**

| Author | Commits | +Lines | -Lines | Churn | % |
| ------ | ------: | -----: | -----: | ----: | --: |
| Agent-Dev | 8 | +312 | -41 | 353 | 86.0 % |
| Agent-QA  | 3 | +52  | -1  | 53  | 13.0 % |
| Jose María Flores Zazo | 1 | +4 | 0 | 4 | 1.0 % |
| **Total** | 12 | +368 | -42 | 410 | 100 % |

> ℹ️ Not a performance metric. Traceability of who wrote what, like
> the regular `Author`/`Committer` fields on every commit and PR.
```

The sticky comment is identified by the HTML marker on the first line,
so the workflow updates the same comment on every push instead of
spamming the PR.

---

## Quick start

### 1. Enable the git hooks (one-off per clone)

```powershell
cd scenario-4
git config core.hooksPath .githooks
```

This activates the `commit-msg` and `pre-push` gates locally. They are
shipped under `.githooks/` (not `.git/hooks/`) so they live in the
repository and travel with every clone.

### 2. Commit as an agent

```powershell
# Windows
.\scripts\agent-commit.ps1 -Agent "Agent-Dev" -Message "Add ticket creation"

# Linux / Mac / git-bash
./scripts/agent-commit.sh "Agent-Dev" "Add ticket creation"
```

The script does `git add -A`, computes added / deleted lines, and emits
the commit with `Author=Agent-Dev`, `Committer=<you>` and the trailers
`Agent:` and `LoC:`.

> ⚠️ Commit your own *tooling / setup* changes as a **human** before
> handing the worktree over to the agent. `agent-commit` does
> `git add -A`, so anything staged or untracked at that moment is
> attributed to the agent.

### 3. Mixed commits (when unavoidable)

```powershell
./scripts/mixed-commit.sh "Add square root with its test and note" `
  "Agent-Dev=calculator.py" `
  "Agent-QA=test_calculator.py" `
  "Person=README.md"
```

The script computes the per-file split, sets `Author = majority owner`,
and writes the full breakdown into the commit body. For line-level
attribution prefer **separate commits per actor** plus `git blame`;
`mixed-commit` is the fallback when separating is impractical.

### 4. Preview the PR comment locally

```powershell
./scripts/pr-author-summary.sh main
```

Outputs the exact Markdown the GitHub Actions workflow will post.

### 5. Enable the PR workflow in your repo

Copy [.github/workflows/pr-author-summary.yml](.github/workflows/pr-author-summary.yml)
to the **target repo's** `.github/workflows/` folder. No secrets, no
service accounts — it uses the built-in `github.token` with
`pull-requests: write`.

---

## Environment variables

This scenario is unique among the four in that **it has no runtime
secrets**: no API keys, no connection strings, no service principals.
Everything runs on the developer's machine and on GitHub's standard
runner. The only configuration the user controls is git itself.

| `git config` key | Required by | Notes |
| --- | --- | --- |
| `user.name` / `user.email` | every commit | The **human's** identity. Becomes `Committer` on agent commits. |
| `core.hooksPath = .githooks` | `commit-msg`, `pre-push` | One-off setup per clone (see Quick start). |
| `agent.devName` / `agent.devEmail` *(optional override)* | `agent-commit.sh` / `.ps1` | If you want a different agent identity than the default `Agent-Dev <agent-dev@agents.local>`. |
| `agent.qaName` / `agent.qaEmail` *(optional override)* | `agent-commit.sh` / `.ps1` | Same, for `Agent-QA`. |

The `@agents.local` domain is reserved (RFC 6761 reserves `.local`
for local-only use): mail will never deliver to it, and it cannot
collide with a real corporate identity.

> **Before publishing this repository to GitHub.** Nothing here leaks
> secrets — but two cosmetic checks:
>
> 1. Replace the sample human email `jose@example.com` shown in this
>    README and in `.github/agents/*.md` with whatever your team uses.
> 2. The audit log produced by `scripts/post-commit-example.{sh,ps1}`
>    is local-only (writes to `.git/agent-audit.log`, gitignored). If
>    you redirect it to a tracked file, redact author emails before
>    pushing.

---

## When to combine this scenario with the other three

* **Scenario 4 + Scenario 1.** Engineering manager view: *"this PR is
  86 % Agent-Dev — and the DeepEval suite is still green."* You see
  who wrote the code AND whether the agent's quality regressed.
* **Scenario 4 + Scenario 2.** Compliance view: *"the Agent-Dev
  commits in this PR were produced by sessions whose prompts were
  screened by Foundry's ContentSafety + IndirectAttack evaluators."*
  Source-control attribution + runtime safety attestation.
* **Scenario 4 + Scenario 3.** Full chain-of-custody: *every*
  IDE turn that produced a line in this PR has a `corp.agent.invocation`
  span in App Insights with `corp.actor` = the same human who appears
  as `Committer` in git. Auditor can pivot from the PR to the
  per-turn cost, model id, and policy verdicts.
