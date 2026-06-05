# Governance and metrics for agents and people in git

> How to attribute, measure and audit work when part of the code is written
> by an AI agent and part by a person — using git's native mechanisms,
> not a parallel spreadsheet.

## 1. The problem

In a team where **AI agents** (developer, tester, reviewer…) work alongside
**people**, the governance questions are no longer trivial:

- Who actually wrote this change: a person or an agent?
- How much code is each agent producing versus each person?
- If something breaks in production, who is the **responsible** party that
  approved the change?
- How do I audit this **without** building a parallel system that must be
  maintained?

The answer is that git already distinguishes **two roles** on every commit,
and almost nobody uses them:

| Role | Question it answers | In our model |
|------|---------------------|--------------|
| **Author** | Who *wrote* the change? | The **agent** (or the person who wrote it) |
| **Committer** | Who *applied/approved* it in the repo? | The **responsible person** |

This separation is not a trick: git created it for the email-patch workflow
(someone writes the patch, someone else integrates it). It fits agents
naturally: **the agent is the author of the work; the person is who
answers for it.**

We build two models on top of that.

---

## 2. Model A — Per-commit agent identity

**Idea:** every commit pins `Author` as the agent and leaves `Committer` as
the supervising person. Everything happens in the same working directory
and the same branch.

```
Author : Agent-Dev <agent-dev@agents.local>          ← wrote the code
Commit : Jose María Flores Zazo <jose@company.com>   ← responsible integrator

    Add calculator with basic operations and CLI

    Agent: Agent-Dev
    LoC: +65 -0 net:65
```

In this repo that is done by `scripts/agent-commit.sh` (and its `.ps1`
twin): it runs `git add`, computes the change's lines (LoC) and commits
with `--author="Agent-Dev <agent-dev@agents.local>"`.

### Why Model A

- **Native attribution, zero parsing.** No need to read the message body:
  ```bash
  git log --author="Agent-Dev"    # only the developer agent's work
  git shortlog -sne               # ranking by author (people and agents)
  ```
- **Responsibility intact.** The committer is still a person: there is
  always a human answering for every commit, even when the code was
  written by an agent.
- **Near-zero cost.** It is a single flag (`--author`) inside the commit
  script. It does not change how the team works or the repo's structure.
- **Platform-compatible.** GitHub/GitLab group contributions by author
  email; the agent shows up as just another collaborator on the graphs.

### Limits of Model A

- **Everyone shares directory and branch.** If a developer agent and a
  testing agent work **simultaneously**, they step on each other's files.
  This is a sequential model: first one, then the other.
- **It does not isolate the environment.** Dependencies, temp files or a
  half-finished test from one agent affect the other.

> Model A answers *"whose code is this?"* perfectly, but it does not
> solve *"how do several agents work in parallel without getting in each
> other's way?"*.

---

## 3. Model B — One worktree per agent

**Idea:** each agent works in its own **git worktree** (a separate working
directory of the same repo) on **its own branch**, and each worktree has
**its own git identity** configured.

```
repo/                 ← main worktree (person, main branch)
../wt-dev/            ← Agent-Dev's worktree (dev branch)
../wt-qa/             ← Agent-QA's worktree  (qa branch)
```

Enabled via git's per-worktree configuration:

```bash
git config extensions.worktreeConfig true

git worktree add ../wt-dev -b dev
git -C ../wt-dev config --worktree user.name  "Agent-Dev"
git -C ../wt-dev config --worktree user.email "agent-dev@agents.local"

git worktree add ../wt-qa -b qa
git -C ../wt-qa config --worktree user.name  "Agent-QA"
git -C ../wt-qa config --worktree user.email "agent-qa@agents.local"
```

From then on, **every** commit made inside `../wt-dev` is automatically
signed by Agent-Dev — no script and no `--author`. Identity lives in the
environment, not in each command.

### Why Model B

- **Real parallelism.** Dev writes the feature while QA prepares the
  tests, each in their own directory and branch, without file conflicts.
- **Isolation.** Each agent has its own working state (and even its own
  environment or dependencies) without contaminating the others.
- **Pull-request-style flow.** Each agent branch is integrated via PR /
  merge, with human review at the merge point. Governance happens at the
  merge — which is exactly where control belongs.
- **Automatic identity.** Authorship is no longer tied to remembering
  `--author` in a script: the environment guarantees it.

### Limits of Model B

- **More operational complexity.** You have to create, sync and clean up
  worktrees and branches; the "human responsible" committer is best
  materialised at the **merge** rather than on each individual commit.
- **Overkill if everything is sequential.** When there are never two
  agents at once, isolation buys you nothing and only adds friction.

> Agent tooling (e.g. the `worktree` isolation mode of Claude Code
> subagents) plugs into this model naturally.

---

## 4. Comparison

| Criterion | Model A (Author per commit) | Model B (worktree per agent) |
|-----------|----------------------------|------------------------------|
| Git attribution | ✅ Author = agent | ✅ Author = agent |
| Responsible human | Committer of each commit | Whoever merges / approves the PR |
| Parallel work | ❌ sequential | ✅ simultaneous |
| Environment isolation | ❌ | ✅ |
| Setup cost | Very low (one flag) | Medium (worktrees + branches) |
| Natural flow | Commits on one branch | Pull Requests per agent |
| Best for | Getting started, small teams, sequential work | Multiple agents at once, Dev→QA pipelines |

**They are not mutually exclusive.** The usual setup is **A inside B**:
each agent in its own worktree (B) and, additionally, commits with
`--author` and LoC trailers (A) so metrics stay fine-grained within each
branch.

---

## 5. The metrics this enables

Since authorship is native, the metrics fall out of standard commands —
nothing extra to maintain:

```bash
# Lines and commits per actor (people and agents)
git shortlog -sne

# Only the work of one specific agent
git log --author="Agent-Dev" --oneline

# Per-actor contribution across a PR range (script in this repo)
scripts/pr-agent-summary.sh main
```

And because every commit carries the trailer `LoC: +A -B net:N`, you can
build dashboards: % of code generated by agents vs. people, evolution by
sprint, ratio of test lines (Agent-QA) vs. production lines (Agent-Dev),
etc.

Metrics worth watching:

- **Agent/person split**: how much of the code originates with agents and
  how much with people.
- **Relative coverage**: test LoC versus production LoC.
- **Rework**: changes by a person on top of code just generated by an
  agent (a signal of generation quality).

> ⚠️ LoC measures **volume, not value**. Useful to understand the work
> split and detect anomalies, never to "rank" quality. A good change can
> be −200 lines.

### Disclaimer: what this is NOT

It is worth stating explicitly because percentages are easy to misread:

- It is **not** a **performance** or productivity metric.
- It does **not** serve to compare **"people vs. agents"** or to decide
  who "produces more" or "works better".
- It is **not** a ranking or a performance evaluation of anyone, human or
  agent.

What it **is**: **traceability** — knowing **who did what and how**,
exactly like the authorship every team already uses on commits and Pull
Requests every day. The goal is transparency and governance (where did
this code come from? who answers for it?), not scoring people or agents.

---

## 6. Governance: why it matters

1. **Real traceability.** Knowing what an agent wrote vs. what a person
   wrote stops being a fragile convention in the message body and
   becomes first-class data in git.
2. **Clear responsibility.** An agent being the *author* does not dilute
   accountability: there is always a person as the *committer* (Model A)
   or as the *merge* approver (Model B). The agent produces; the person
   answers.
3. **Audit without parallel systems.** The `commit-msg` hook forces
   every commit to be labelled (`Agent:` or `Person:`); git history is
   the source of truth.
4. **Identity hygiene.** The `*@agents.local` emails are deliberately
   fake so an agent can **never** be confused with a real person or with
   a platform account.

---

## 7. Recommendation

- **Start with Model A.** It delivers 90% of the value (attribution +
  metrics) at minimal cost and without changing how the team works.
- **Move to Model B when parallelism appears**: several agents working
  at once, or a clear Dev→QA pipeline where you want isolation and a
  per-agent PR flow. Keep Model A inside each worktree so granularity is
  preserved.
- **Cross-cutting rules either way:** clearly fake agent identities, a
  person always responsible, and `commit-msg` as the gate that blocks
  commits with no attribution.

In one sentence: **the agent produces and is recorded as the author; the
person approves and answers; and git — not a spreadsheet — holds the
truth.**
