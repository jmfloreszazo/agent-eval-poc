# Governance Blueprints for AI Agents in the Enterprise

Four reference scenarios that show how to put **GitHub Copilot and
custom AI agents under the same controls you already apply to people,
endpoints, and applications**: identity, audit, cost, safety, quality,
and source-control attribution.

Built for engineering leaders, security/compliance officers, and FinOps.
Each scenario is small enough to deploy in a working session and large
enough to defend in a risk review.

> **Bottom line.** Together, these four scenarios + the Azure services
> they already use (**Azure AI Foundry**, **Application Insights /
> Log Analytics**, **APIM AI Gateway**, **Microsoft Entra Agent ID**,
> and the standard **GitHub** + **git** primitives) cover **the full
> governance surface** any auditor or risk team will ask about:
> identity, pre-call policy, per-turn telemetry, per-team cost,
> multi-agent correlation, IDE governance, GitHub Copilot audit
> ingestion and per-PR source-control attribution.
>
> **You do not need to buy a third-party LLM observability product, a
> separate AI gateway, an external prompt-firewall, an AI risk-policy
> SaaS, or a code-attribution analytics vendor.** Every gap that those
> tools claim to fill is closed by one of the four scenarios below
> using services you can already provision in your existing Azure
> subscription. The partner integrations Foundry advertises (Purview,
> Credo AI, Saidot, Entra Agent ID) are optional reporting / identity
> layers on top — they sit *above* or *below* this repo, never
> replace it.

---

## Why these scenarios exist

AI agents are now writing code, summarising contracts, querying
financial data, and acting on behalf of employees. Three problems show
up in every enterprise that adopts them at scale:

1. **The IDE does not ship governance.** GitHub Copilot Chat (and most
   commercial agent runtimes) do **not** export per-turn prompts, model
   IDs, token counts, or cost to the customer's tenant. If something
   leaks, the audit trail does not exist.
2. **Multi-agent runs are non-deterministic.** "The same case ran
   through fraud-analyst then legal-counsel" needs to be reconstructible
   end-to-end, with a single correlation ID, or compliance cannot sign
   off.
3. **Cost is invisible by default.** Tokens are billed at the platform
   level; teams discover the bill at the end of the month with no
   per-team / per-agent attribution.

Each scenario in this repo answers a different layer of that problem
with a small, deployable blueprint.

---

## The four blueprints

| | **Scenario 1** | **Scenario 2** | **Scenario 3** | **Scenario 4** |
| --- | --- | --- | --- | --- |
| **What it answers** | "Can my agent be evaluated like normal software?" | "Can the platform of record for AI also be the platform of record for compliance?" | "Can I put a governance gateway in front of every agent in the company?" | "Which lines in this Pull Request were written by an agent vs. a human, and who is responsible?" |
| **Audience** | Engineering Leader | Compliance Officer | CTO + FinOps + Security | Engineering Manager + Release Manager + Legal / IP |
| **Stack** | Open source: Arize Phoenix + DeepEval + .NET agent | Microsoft-native: Azure AI Foundry + Application Insights | All of the above + APIM AI Gateway + GitHub audit-log puller + VS Code extension | Pure git: `Author`/`Committer` split + `.githooks/` + GitHub Actions PR comment |
| **Deploys in** | ~5 min | ~10 min | ~30 min (full 4 layers) | <5 min (copy scripts + enable workflow) |
| **Cost** | $ | $$ | $$$ (only what you turn on) | $0 — no runtime infra |
| **CI gate** | ✅ Pytest fails the build | ✅ KQL/Foundry continuous eval | ✅ Same gates, plus per-team/per-agent cost & policy enforcement | ✅ Sticky PR comment + local `pre-push` test gate |

> Scenarios 1–3 use the same `.NET` cost agent in [agent/](agent/) as
> the *system under test* so runtime results are directly comparable.
> Scenario 4 operates at the source-control layer and is independent of
> the system under test — drop it into any repository.

---

## What each scenario answers, by role

### Scenario 1 — Phoenix + DeepEval (open source)

* **Engineering Leader.** "Can I treat my agent like a microservice?
  Pass/fail evaluations on every PR, traces in a self-hosted UI,
  no vendor lock-in." → Yes.
* **Compliance.** "We can re-run the trajectory and see the same
  judgement." → Yes (Phoenix datasets + experiments).
* **FinOps.** Out of scope (no centralised cost control here).

### Scenario 2 — Azure AI Foundry + Application Insights

* **Engineering Leader.** "Can I run the agent on a managed platform
  and still keep my CI gate?" → Yes (Foundry quality evaluators in
  CI).
* **Compliance.** "Can I prove the agent was screened for prompt
  injection, protected material, and harmful content on every run?"
  → Yes (Foundry Risk & Safety evaluators + Application Insights audit
  trail).
* **FinOps.** Token usage is captured per turn in App Insights but
  attribution to *teams* still depends on tagging discipline.

### Scenario 3 — Full governance gateway (the executive view)

* **CTO.** "I have a single chart that shows: who used which agent,
  with which model, on which case, for what cost, with what verdict —
  across IDE Copilot AND custom agents." → Yes.
* **Compliance.** "If a fraud-analyst run flags suspicious, the legal
  step that followed is in the same span tree, in the same workspace."
  → Yes (`corp.case.run` parent span).
* **Security.** "Prompt-injection / harmful-content / token-quota
  policies are enforced *before* the model call, not after." → Yes
  (APIM AI Gateway, Layer 2).
* **FinOps.** "Every turn carries `corp_team`, `corp_actor`,
  `corp_agent` dimensions priced from a single YAML." → Yes.
* **Procurement.** "GitHub Copilot enterprise audit events are pulled
  hourly and joined with the rest of the telemetry." → Yes (Layer 1).

### Scenario 4 — Source-control attribution (agent vs. human in PRs)

* **Engineering Manager.** "On any Pull Request, can I see at a
  glance what % of the diff each agent wrote and what % a human
  wrote, with the human still recorded as the responsible
  `Committer`?" → Yes (sticky PR comment generated by
  `pr-author-summary` + GitHub Actions).
* **Release Manager.** "Can I block a release if the local tests
  failed before the agent's branch was pushed?" → Yes
  (`.githooks/pre-push` runs the tests and the per-author summary as
  a gate, before the PR is even opened).
* **Legal / IP.** "Is there an unambiguous chain of custody — a
  named human who reviewed and integrated every line generated by
  an agent — that survives in the canonical git history without a
  parallel database?" → Yes (`Author = <agent identity>` /
  `Committer = <human>` on every commit; commits without those
  trailers are rejected by `commit-msg`).
* **Compliance.** "Does this work for any agent vendor, not just
  Copilot?" → Yes (the `agent-commit` script is vendor-neutral and
  works for Copilot, Claude Code, Cursor, custom agents).

---

## How this compares to commercial and open-source vendors

The market has good tools for *parts* of this problem. None ship the
full set of policy + audit + cost + IDE controls described above.

| Capability | Datadog LLM Obs | LangSmith | Helicone | Arize Phoenix (OSS) | Azure AI Foundry | Azure APIM AI Gateway | Portkey | Lakera Guard | Closest scenario | What's still missing in that vendor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Trace + replay agent runs | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ partial | ✅ | ❌ | 1, 2 | n/a (covered) |
| Pytest-style CI gate | ⚠️ | ✅ (LangSmith Evals) | ❌ | ✅ (DeepEval bridge) | ✅ (Foundry SDK) | ❌ | ❌ | ❌ | 1, 2 | n/a |
| Risk & safety evaluators (jailbreak, protected material) | ⚠️ | ⚠️ | ❌ | ❌ | ✅ | ⚠️ via Content Safety | ⚠️ | ✅ | 2, 3 | full evaluators tied to traces (Foundry) |
| **Pre-call** policy (token quota, content safety, jailbreak shield) | ❌ | ❌ | ⚠️ rate-limit only | ❌ | ❌ | ✅ | ✅ | ✅ | **3** | gateway in front of *every* model (3) |
| Per-team / per-agent cost attribution from a single price book | ⚠️ tag based | ⚠️ | ✅ | ❌ | ⚠️ | ✅ via dims | ✅ | ❌ | **3** | priced YAML committed to repo (3) |
| **Governed Copilot Chat in the IDE** (per-turn telemetry to *your* tenant) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | **3** | only scenario 3 closes this gap |
| GitHub Copilot enterprise audit events joined to agent telemetry | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | **3** | only scenario 3 closes this gap |
| Single correlation ID across multi-agent run | ⚠️ | ✅ within LC | ❌ | ✅ | ⚠️ | ❌ | ✅ | ❌ | **3** | parent `corp.case.run` span (3) |
| Per-PR % of lines by agent vs. human, with a named human as `Committer` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | **4** | only scenario 4 closes this gap |
| Per-commit attribution to a *named* agent (Copilot, Cursor, Claude Code, custom) | ❌ Copilot only at aggregate | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | **4** | only scenario 4 closes this gap |

> **Reading guide.** ✅ = covered out of the box. ⚠️ = covered with
> custom configuration or only in part. ❌ = not in the product. The
> four highlighted rows (governed Copilot in the IDE + GitHub Copilot
> audit join, per-PR agent/human line split + chain-of-custody) are
> **the gap that no commercial product ships today**, which is why
> scenarios 3 and 4 exist.

### How the Microsoft Foundry governance partners fit in

Microsoft Foundry advertises a "governance-first" panel with four
partner integrations: **Microsoft Purview Compliance Manager**,
**Credo AI** (preview), **Saidot**, and **Microsoft Entra Agent ID**.
These are *complementary* to the four scenarios above — none of them
replaces a scenario, and Foundry itself does not claim they do. The
matrix below shows exactly what each one covers and what is still left
to scenarios 2, 3 and 4.

| Capability | Microsoft Purview Compliance Manager | Credo AI *(preview)* | Saidot | Microsoft Entra Agent ID | Closest scenario | What is still missing in that partner |
| --- | --- | --- | --- | --- | --- | --- |
| Map regulation (EU AI Act, NIST AI RMF, ISO 42001, SOX) to a control checklist | ✅ | ✅ | ✅ | ❌ | reporting layer on top of **2 / 3** | does **not** emit telemetry — it stores evidence you produce |
| Turn risk requirements into runnable Foundry evaluators | ❌ | ✅ (closed loop) | ✅ (eval plan generation) | ❌ | **2** | the evaluators they trigger are the same Foundry evaluators scenario-2 already runs |
| Risk-based red-teaming / synthetic datasets | ❌ | ⚠️ via partners | ✅ | ❌ | **2** | red-team output still needs scenario-2's run_safety to assert pass/fail in CI |
| Managed identity for each agent (auto-tagged in Entra, Conditional Access ready) | ❌ | ❌ | ❌ | ✅ | identity layer **under 2 / 3** | does not emit cost/usage spans or apply content safety |
| Pre-call policy (token quota, jailbreak shield, content safety) | ❌ | ❌ | ❌ | ❌ | **3** | only the APIM AI Gateway in scenario-3 does this |
| Per-turn telemetry from **GitHub Copilot Chat in the IDE** to your tenant | ❌ | ❌ | ❌ | ❌ | **3** | only the VS Code extension in scenario-3 (Layer 4) does this |
| Hourly pull of GitHub Copilot enterprise **audit log** events | ❌ | ❌ | ❌ | ❌ | **3** | only `copilot_audit_pull.py` in scenario-3 (Layer 1) does this |
| Parent `corp.case.run` span across a multi-agent run | ❌ | ❌ | ❌ | ❌ | **3** | only `corp.py` in scenario-3 (Layer 3) does this |
| Per-team / per-agent cost from a priced YAML | ❌ | ❌ | ❌ | ❌ | **3** | only `pricing.yaml` in scenario-3 does this |
| Per-PR % of lines by agent vs. human, with the human as `Committer` | ❌ | ❌ | ❌ | ❌ | **4** | only scenario-4 does this |
| Auditor-ready evidence pack (upload scores + control mapping) | ✅ | ✅ | ✅ | ❌ | reporting on top of **2 / 3** | needs scenarios 2/3 to generate the actual evidence first |

> **Reading guide.** Purview / Credo / Saidot are the place auditors
> *consume* the evidence; scenarios 2 and 3 are the place the evidence
> is *produced*. Entra Agent ID is the identity primitive that should
> sit underneath both. Enable Entra Agent ID immediately — it is free
> and integrates with no code change. Adopt Purview if your Compliance
> team already lives there; Credo / Saidot only if Compliance has a
> subscription, otherwise the Foundry evaluators in scenario-2 cover
> the same ~80% at the cost of a Python script.

### What this means in practice: no extra tooling required

The matrices above are designed to be read in one direction: **every
row that a commercial product *does not* cover (❌) is covered by one
of the four scenarios in this repo using a service that already exists
in your Azure subscription.** Concretely:

| Governance need | Covered by | Azure / GitHub service used |
| --- | --- | --- |
| Quality evaluation tied to traces, with CI gate | Scenario 1 (OSS path) **or** Scenario 2 (Azure-native path) | Azure OpenAI + (Phoenix self-host) **or** Foundry SDK + Application Insights |
| Risk & safety evaluators (jailbreak, protected material, harmful content) | Scenario 2 | Azure AI Foundry Risk & Safety evaluators + Application Insights |
| Pre-call policy (token quota, content safety, jailbreak shield) at runtime | Scenario 3, Layer 2 | Azure APIM AI Gateway + Azure AI Content Safety |
| Per-team / per-agent cost attribution from a single price book | Scenario 3, Layer 3 | App Insights custom dimensions priced from `pricing.yaml` |
| Parent span across multi-agent runs (single correlation ID) | Scenario 3, Layer 3 | `corp.case.run` span in Application Insights |
| Per-turn telemetry from **GitHub Copilot Chat in the IDE** to your tenant | Scenario 3, Layer 4 | VS Code Chat Participant API + Application Insights |
| GitHub Copilot **enterprise audit-log** events joined with agent telemetry | Scenario 3, Layer 1 | GitHub REST `/enterprises/{ent}/audit-log` + Application Insights |
| Identity for each agent (Conditional Access, Entra audit, token policies) | All scenarios | **Microsoft Entra Agent ID** (turn on, no code) |
| Per-PR % of lines by agent vs. human, with human as `Committer` | Scenario 4 | Git `Author`/`Committer` + GitHub Actions sticky comment |
| Auditor-ready evidence pack (regulation → control → evidence) | Optional, on top of 2/3 | **Microsoft Purview Compliance Manager** (consumes the JSON / Markdown the scenarios already produce) |

If an Azure customer asks *"what else do we need to buy?"* — the
answer is **nothing**. The same subscription that hosts the workload
already hosts every service required to operate, govern and audit it.

---

## Repository layout

```
agent-eval-poc/
├── agent/             # Shared .NET cost agent — the "system under test" for scenarios 1–3
├── scenario-1/        # Open-source: Phoenix + DeepEval
├── scenario-2/        # Microsoft-native: Foundry + App Insights
├── scenario-3/        # Full governance gateway (4 layers)
├── scenario-4/        # Source-control attribution (git Author/Committer + PR comment)
├── vscode-ext/        # Programmatic Copilot governance extension (scenario 3, layer 4)
└── .github/           # Chat modes, agent contracts, hooks, CI workflows
```

Detailed technical walkthroughs live in each scenario's own README:

* [scenario-1/README.md](scenario-1/README.md) — Phoenix + DeepEval
* [scenario-2/README.md](scenario-2/README.md) — Azure AI Foundry
* [scenario-3/README.md](scenario-3/README.md) — Full governance gateway
* [scenario-3/docs/governance-architecture.md](scenario-3/docs/governance-architecture.md) — 4-layer architecture deep dive
* [scenario-4/README.md](scenario-4/README.md) — Source-control attribution

---

## Environment files & secrets (read this before publishing)

This repository uses one `.env` per scenario, all **gitignored**. Real
keys are never committed; templates with placeholders are. Copy the
template, fill in your values, and the deploy scripts will keep them in
sync.

| File on disk (gitignored) | Template (committed) | Used by |
| --- | --- | --- |
| `.env` | [`.env.scenario-1.example`](.env.scenario-1.example) | scenario 1 (Azure OpenAI for agent + LLM-as-judge) |
| `.env.scenario-2` | [`.env.scenario-2.example`](.env.scenario-2.example) | scenario 2 (Foundry account, project, App Insights, Log Analytics) |
| `.env.scenario-3` | [`.env.scenario-3.example`](.env.scenario-3.example) | scenario 3 (dedicated Foundry stack + optional APIM gateway + optional GitHub audit) |
| *(none)* | *(none — `git config` only)* | scenario 4 (no runtime secrets — see [scenario-4/README.md](scenario-4/README.md) §Environment variables) |

**Before pushing this repository to GitHub:**

1. `git status --short` must show **no** `.env*` line that is *not*
   `.env.*.example`.
2. If you have ever staged a real key, rotate it before publishing:
   ```powershell
   az cognitiveservices account keys regenerate `
       --name <foundry-or-aoai-account> `
       --resource-group <rg> `
       --key-name Key1
   ```
3. The `.gitignore` rule `.env.*` with `!.env.*.example` is what
   guarantees the templates stay in and the real files stay out.

---

## How to read this repo

1. **Start at scenario 1** if you only want to see "what good
   evaluation looks like" — it is fast, open source, and runs on a
   laptop.
2. **Move to scenario 2** if your organisation has standardised on
   Azure and you need a managed audit trail.
3. **Open scenario 3** when the conversation moves to "we have many
   agents, in many teams, with many models, and the security and
   finance teams want a single source of truth". That is the
   governance gateway scenario.
4. **Drop scenario 4 into *any* repository** the moment your
   engineers start committing AI-generated code. It costs nothing,
   has no runtime infrastructure, and gives Engineering, Release
   Management and Legal a defensible chain of custody on every PR
   — independent of which agent vendor produced the code.

Each scenario stands alone; you do not have to deploy them in order.
