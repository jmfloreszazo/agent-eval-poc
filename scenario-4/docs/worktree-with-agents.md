# Worktrees for agent-based development

> Why and how to give each agent its own **git worktree** and identity.
> This is the operational form of **Model B** described in
> [Governance and metrics for agents and people](governance-agents-and-people.md).

## 1. What a worktree is (and why it fits agents)

A **git worktree** is an additional working directory linked to the **same
repository**. They share the object database (`.git`), but each one has its
own branch, its own file state and — crucially — can have its **own
configuration**, including identity (`user.name` / `user.email`).

```
repo/                 ← main worktree     (person,   main branch)
../wt-dev/            ← Agent-Dev's worktree (feat/dev branch)
../wt-qa/             ← Agent-QA's worktree  (feat/qa branch)
```

Why this matters with agents: it solves three problems at once.

1. **Conflict-free parallelism.** Two agents (or an agent and a person)
   can work simultaneously without stepping on each other's files: each
   one in its own directory and branch.
2. **Environment isolation.** Each agent has its own working state
   (half-finished files, dependencies, processes) without contaminating
   the others.
3. **Automatic identity.** Any commit made inside an agent's worktree is
   signed by that agent — no need to remember `--author` on each commit.

> Agent tooling fits naturally: for example, Claude Code subagents
> support `isolation: "worktree"`, which spins up a dedicated worktree
> for them to work in isolation.

## 2. Why worktrees and not something else

| Alternative | Problem vs. worktree |
|-------------|----------------------|
| **Same directory, one branch** (Model A) | Agents collide if they work at the same time; no isolation. |
| **Clone the repo N times** | Duplicates the object database (disk + sync); separate fetch/push. |
| **`git stash` to switch** | Serialises work and is fragile; no real parallelism. |
| **Branches + checkout in the same dir** | Switching branches wipes the other agent's working state. |

A worktree gives you **simultaneous branches in separate directories that
share a single `.git`**: the best of isolation without the cost of
cloning.

## 3. How to set it up

### 3.1. Enable per-worktree configuration

```bash
git config extensions.worktreeConfig true
```

Without this, `git config` is global to the repo and all worktrees share
the same identity.

### 3.2. Create one worktree per agent, each with its own identity

```bash
# Developer agent
git worktree add ../wt-dev -b feat/dev
git -C ../wt-dev config --worktree user.name  "Agent-Dev"
git -C ../wt-dev config --worktree user.email "agent-dev@agents.local"

# Tester agent
git worktree add ../wt-qa -b feat/qa
git -C ../wt-qa config --worktree user.name  "Agent-QA"
git -C ../wt-qa config --worktree user.email "agent-qa@agents.local"
```

From here on, **every commit made inside `../wt-dev` is by Agent-Dev**
and every commit in `../wt-qa` is by Agent-QA, automatically.

### 3.3. Verify

```bash
git worktree list
git -C ../wt-dev config user.email      # -> agent-dev@agents.local
```

## 4. Recommended workflow (Dev → QA → PR)

```
1. Agent-Dev in ../wt-dev (feat/dev):
   implements the feature and commits  → commits signed by Agent-Dev

2. Agent-QA in ../wt-qa (feat/qa):
   writes the tests (rebasing feat/dev or on the same base) → commits by Agent-QA

3. Integrate into a PR branch and open the Pull Request:
   - the workflow posts the per-author composition (90% Dev · 10% QA, etc.)
   - a PERSON reviews and approves the merge → that person is responsible for the change

4. Cleanup:
   git worktree remove ../wt-dev
   git worktree remove ../wt-qa
   git branch -d feat/dev feat/qa   # after the merge
```

**Human responsibility** lives here in the **merge / PR approval**: the
agent is the author of its branch, but nothing reaches `main` without a
person approving it.

## 5. Good practices and pitfalls

- **Enable `extensions.worktreeConfig` BEFORE** configuring per-worktree
  identities; otherwise you are changing the global identity.
- **Tooling/setup as Person.** Same as Model A: create hooks, scripts
  and configuration from the main worktree (person) so they are not
  attributed to an agent.
- **One branch per worktree.** Git does not allow the same branch in two
  worktrees at the same time; that is exactly what gives you isolation.
- **Clean up worktrees** when done (`git worktree remove`) and prune
  orphans with `git worktree prune`.
- **Fake, consistent emails** (`*@agents.local`) so author metrics
  aggregate well and are never confused with people.
- **Combine with Model A** inside each worktree (commits with the `LoC:`
  trailer and a tagged message) if you want fine granularity on top of
  isolation.

## 6. When NOT to use worktrees

- If the work is **always sequential** (never two agents at once), Model
  A alone — author identity per commit — gives you the metrics with much
  less plumbing.
- For teams that are still unsure about their PR/merge flow: introduce
  Model A first and graduate to worktrees when a real need for
  parallelism appears.

---

**In one sentence:** the worktree gives each agent its own place to work
and its own identity to sign with, while the person retains control at
the point that truly matters: PR approval.
