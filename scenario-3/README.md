# Scenario 3 — Full governance gateway (`@corp`) for AI agents

> Part of the [agent-eval-poc](../README.md) repo. See also
> [scenario-1](../scenario-1/README.md) (open-source: Phoenix +
> DeepEval), [scenario-2](../scenario-2/README.md) (Foundry quality
> + safety evaluators), and [scenario-4](../scenario-4/README.md)
> (source-control attribution: agent vs. human in PRs).

**TL;DR.** This scenario is the one a CTO + CISO + FinOps team would
deploy together. It puts **every** AI agent — including GitHub Copilot
Chat in the IDE — behind a single governance gateway that emits:

* a parent `corp.case.run` span per request, so a multi-agent run is
  one click in App Insights;
* `gen_ai.usage.*` and `corp.cost_usd` per turn, priced from a YAML
  committed to the repo;
* `corp.team`, `corp.actor`, `corp.agent` dimensions on every span so
  cost & policy can be sliced by team, person, and agent;
* pre-call policy (token quota + content safety + jailbreak shield) at
  the APIM AI Gateway, before the model call;
* hourly pulls of GitHub Copilot enterprise audit events so seat usage
  and IDE chat are joined with the rest of the telemetry.

The full design is in
[docs/governance-architecture.md](./docs/governance-architecture.md).

## How this scenario differs from the other three

| Capability | Scenario 1 | Scenario 2 | **Scenario 3 (this one)** | Scenario 4 |
| --- | --- | --- | --- | --- |
| Layer governed | Runtime eval | Runtime eval + safety | Runtime gateway across agents | Source control |
| Trace backend | Arize Phoenix (self-hosted) | App Insights + Log Analytics | App Insights + Log Analytics + APIM AI Gateway metrics | Git history (no trace backend) |
| Quality + safety evaluators | DeepEval (OSS) | Foundry Quality + Risk & Safety | Same Foundry evaluators **plus** a deterministic governance judge (`run_judge.py`) | None — PR comment is descriptive, not a verdict |
| Parent span across multi-agent run | ✅ Phoenix project | ⚠️ App Insights operation_Id only | ✅ explicit `corp.case.run` | ❌ (out of scope) |
| Pre-call policy enforcement | ❌ | ❌ | ✅ APIM AI Gateway (`policies/aoai-policy.xml`) | ❌ |
| Per-team / per-agent cost from a priced YAML | ❌ | ⚠️ tag-based | ✅ [`src/pricing.yaml`](./src/pricing.yaml) | ❌ |
| Governed Copilot Chat in the IDE | ❌ | ❌ | ✅ VS Code extension (Layer 4) | ❌ |
| GitHub Copilot enterprise audit join | ❌ | ❌ | ✅ Layer 1 (`tools/copilot_audit_pull.py`) | ❌ |
| Per-PR % of lines by agent vs. human | ❌ | ❌ | ❌ | ✅ sticky PR comment |
| Continuous evaluation in CI | ✅ Pytest | ✅ Foundry SDK | ✅ Same, plus telemetry-aware judge | ✅ `pre-push` test gate + sticky comment |

## How this scenario maps to commercial gateways and policy tools

| Capability | Azure APIM AI Gateway | Portkey | Lakera Guard | Credal | Apex Security | **This scenario** |
| --- | --- | --- | --- | --- | --- | --- |
| Token-quota / rate-limit per team | ✅ | ✅ | ❌ | ⚠️ | ⚠️ | ✅ (uses APIM) |
| Jailbreak / prompt-injection shield (pre-call) | ✅ via Content Safety | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| Per-model load balancing + fallback | ✅ | ✅ | ❌ | ⚠️ | ⚠️ | ✅ |
| Per-turn cost emitted with custom dims (team, actor, agent) | ✅ via dims | ✅ | ❌ | ⚠️ | ⚠️ | ✅ |
| **Parent span across multi-agent run (single trace tree)** | ❌ | ✅ within Portkey | ❌ | ❌ | ❌ | ✅ `corp.case.run` |
| **Governed Copilot Chat in the IDE** (per-turn telemetry to *your* tenant) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ VS Code extension |
| **GitHub Copilot enterprise audit join** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Layer 1 |
| Single managed identity for gateway + evaluators + agent | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |

> The two rows in bold are the gap that no commercial product ships
> today. Scenario 3 closes them by combining APIM AI Gateway (Layer 2),
> a programmatic VS Code extension (Layer 4), and the GitHub Copilot
> audit-log puller (Layer 1) — all stitched together by `corp.py`
> (Layer 3).

---

## The two specialist agents `@corp` orchestrates

- **`@fraud-analyst`** — forensic accounting analyst. Decides if a
  case is `fraud`, `clean` or `suspicious`.
- **`@legal-counsel`** — corporate counsel. Reads the case + the
  analyst verdict and proposes legal actions.

Both are gated by the **`@corp`** governance agent, which is the only
permitted entry point. `@corp` configures telemetry, opens the parent
span, dispatches the two specialists, and produces per-turn cost &
token spans in Application Insights.

```
            ┌──────────────────────────────────────────────┐
            │             user / CI / Copilot Chat         │
            └───────────────────────┬──────────────────────┘
                                    │  case JSON / case id
                                    ▼
                            ┌────────────────┐
                            │     @corp      │  ← governance gateway
                            │  (corp.py)     │  ← opens corp.case.run span
                            └───┬────────┬───┘
            corp.agent.invocation │        │ corp.agent.invocation
                                  ▼        ▼
                       @fraud-analyst   @legal-counsel
                                  │        │
                                  └────┬───┘
                                       ▼
                          Application Insights (exp-2)
                                       │
                                       ▼
                evals/ (judge · quality · safety)
```

## RULE 0 — `@corp` first, always

GitHub Copilot Chat in the IDE does not export tokens/cost/prompt to
your tenant. The **only** way to govern these agents is to broker
every run through `@corp`, which runs
[`scenario-3/src/corp.py`](./src/corp.py) and emits:

- `corp.case.run` (parent span, per case)
- `corp.agent.invocation` × 2 (child spans, one per agent turn) with
  `gen_ai.usage.input_tokens / output_tokens / total_tokens`,
  `gen_ai.usage.source` (`official` | `estimated:tiktoken:o200k_base`
  | `estimated:anthropic-sdk`), `corp.cost_usd`,
  `corp.pricing.date`, `corp.agent_name`, `corp.verdict`,
  `corp.actor`, `corp.team`, `corp.repo`, `corp.case_id`,
  `corp.ground_truth`, `corp.stage`, `corp.latency_ms`,
  `corp.orchestrator="corp"`.

Calling `@fraud-analyst` or `@legal-counsel` directly is a governance
violation — no telemetry will be emitted.

## Layout

```
scenario-3/
├── README.md                    ← this file
├── requirements.txt
├── data/
│   └── cases.jsonl              ← 10 synthetic accounting cases (labelled)
├── src/
│   ├── corp.py                  ← THE orchestrator (governance + telemetry)
│   ├── pipeline.py              ← thin shim re-exporting from corp.py
│   ├── telemetry.py             ← OTel → App Insights wiring
│   ├── tokens.py                ← official + estimated token counting
│   ├── pricing.py               ← per-model USD cost lookup
│   └── pricing.yaml             ← daily-effective prices
├── evals/
│   ├── run_judge.py             ← deterministic accuracy + cost report
│   ├── run_quality.py           ← Foundry quality evaluators
│   └── run_safety.py            ← Foundry safety evaluators
└── observability/kql/           ← App Insights queries
    ├── cost_by_agent.kql
    ├── cost_by_actor.kql
    ├── coverage_official_vs_estimated.kql
    └── fraud_accuracy_by_case.kql
```

The chat-mode prompts themselves live at the repo root in
[`.github/chatmodes/`](../.github/chatmodes/) so VS Code Copilot
discovers them. `corp.py` reads those `.md` files at runtime and uses
the body as the agent's system prompt — **never** copy a prompt into
Python.

## Prerequisites

- Application Insights — **reuses the resource from scenario-2**.
  The connection string is read from
  [`../scenario-2/.env.scenario-2`](../scenario-2/.env.scenario-2)
  (`APPLICATIONINSIGHTS_CONNECTION_STRING`).
- Python 3.13 venv at `.venv/Scripts/python.exe`.
- `GITHUB_MODELS_TOKEN` (fine-grained PAT, scope `models:read`).
  `GITHUB_TOKEN` / `GH_TOKEN` are accepted as fallbacks.
- (Optional, only if you run `run_safety.py` / `run_quality.py`) Azure
  CLI login: `az login` and the same Foundry project from exp-2.

## Environment variables

`.env.scenario-3` is generated by `infra/deploy.ps1` at the repo root
and is **gitignored**. A safe template lives at
[`../.env.scenario-3.example`](../.env.scenario-3.example) — copy it
to `.env.scenario-3`, fill in the placeholders, and the deploy script
will keep it in sync. The template covers:

| Block | Variables | Used by |
| --- | --- | --- |
| Foundry (account + project + gpt-4o-mini) | `AZURE_AI_FOUNDRY_*`, `AZURE_AI_PROJECT_*`, `AZURE_OPENAI_*` | `src/corp.py`, `evals/run_quality.py`, `evals/run_safety.py` |
| Observability | `APPLICATIONINSIGHTS_CONNECTION_STRING`, `LOG_ANALYTICS_*`, `APP_INSIGHTS_RESOURCE_ID` | `src/telemetry.py`, `tools/copilot_audit_pull.py` |
| Azure scope | `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` | all deploy scripts and the Foundry evaluators |
| Layer 2 — APIM AI Gateway *(optional)* | `AZURE_OPENAI_GATEWAY_*`, `AZURE_CONTENT_SAFETY_ENDPOINT` | filled by `infra/deploy_aigateway.ps1` |
| Layer 1 — GitHub audit pull *(optional)* | `GITHUB_TOKEN`, `GITHUB_ENTERPRISE`, `GITHUB_ORG` | `tools/copilot_audit_pull.py`, CI workflow |

> **Before committing anything.** If `.env.scenario-3` is ever staged
> by accident, rotate the Foundry key before pushing:
>
> ```powershell
> az cognitiveservices account keys regenerate `
>     --name <foundry-account> --resource-group <rg> --key-name Key1
> ```
>
> The `.gitignore` rule `.env.*` with `!.env.*.example` keeps the
> templates tracked and the real env files out of git.

## Install

```powershell
.\.venv\Scripts\python.exe -m pip install -r scenario-3\requirements.txt
```

## Run the corp gateway

```powershell
# environment
$env:GITHUB_MODELS_TOKEN = "github_pat_xxx"   # scope: models:read

# single case
.\.venv\Scripts\python.exe scenario-3\src\corp.py --case case-001

# whole dataset
.\.venv\Scripts\python.exe scenario-3\src\corp.py --all

# raw case from file
.\.venv\Scripts\python.exe scenario-3\src\corp.py --case-file my_case.json
```

`corp.py` writes one row per agent turn to
`scenario-3/data/traces.jsonl` and emits spans to App Insights.

The deprecated entry `python scenario-3\src\pipeline.py --all` still
works — it is now a thin shim that calls `corp.main()`.

## Evaluate

Once you have `traces.jsonl`:

```powershell
# deterministic: accuracy, schema parse rate, statute citation, cost
.\.venv\Scripts\python.exe scenario-3\evals\run_judge.py

# Foundry quality (coherence, fluency, groundedness, relevance, similarity)
.\.venv\Scripts\python.exe scenario-3\evals\run_quality.py

# Foundry safety (content safety, indirect attack, protected material)
.\.venv\Scripts\python.exe scenario-3\evals\run_safety.py
```

Outputs land in `scenario-3/data/`:

- `judge.jsonl` + `judge_summary.json`
- `quality.jsonl`
- `safety.jsonl`

Sample judge summary:

```json
{
  "fraud_accuracy": 0.80,
  "fraud_json_parse_rate": 1.00,
  "legal_json_parse_rate": 1.00,
  "legal_consistency_rate": 0.90,
  "legal_statute_citation_rate": 0.70,
  "cost_usd": {"fraud": 0.0034, "legal": 0.0061, "total": 0.0095},
  "confusion_matrix": {
    "fraud":      {"fraud": 4, "clean": 0, "suspicious": 0},
    "clean":      {"fraud": 0, "clean": 3, "suspicious": 1},
    "suspicious": {"fraud": 0, "clean": 1, "suspicious": 1}
  }
}
```

## App Insights queries

See [observability/kql/](./observability/kql/). All four queries
filter on `customDimensions.["corp.orchestrator"] == "corp"` so
ungoverned calls never show up in your dashboards.

## Editing the agents

Edit the chat-mode file at the repo root:

- [`.github/chatmodes/corp.chatmode.md`](../.github/chatmodes/corp.chatmode.md)
- [`.github/chatmodes/fraud-analyst.chatmode.md`](../.github/chatmodes/fraud-analyst.chatmode.md)
- [`.github/chatmodes/legal-counsel.chatmode.md`](../.github/chatmodes/legal-counsel.chatmode.md)

Both the IDE and the batch evals pick up the change on the next run.
