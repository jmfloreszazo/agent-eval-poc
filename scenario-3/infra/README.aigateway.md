# Capa 2 — APIM AI Gateway in front of Azure OpenAI

This module is **additive** to `main.bicep` (the existing Foundry stack).
It deploys an APIM AI Gateway that fronts the Azure OpenAI / Foundry
account from `main.bicep` and emits per-team, per-actor, per-agent token
metrics into the same Application Insights.

## Files

| File | Purpose |
|---|---|
| `aigateway.bicep` | APIM StandardV2 + Content Safety + backends + product + subscription + role assignments + diagnostic settings |
| `policies/aoai-policy.xml` | Inbound + outbound + on-error policy applied to the OpenAI API |
| `deploy_aigateway.ps1` | One-shot deployer (idempotent) |

## What it provisions

| Resource | Why |
|---|---|
| `apim-<base>` (StandardV2, system-assigned MI) | Hosts the gateway. StandardV2 is the minimum SKU with the GenAI policies (`azure-openai-emit-token-metric`, `azure-openai-token-limit`, `llm-content-safety`). |
| Backend `aoai-backend` | Points to the existing Foundry account. Auth via APIM's MI → `Cognitive Services User` on the AOAI resource. |
| Backend `contentsafety-backend` | Points to a new Content Safety account; used by `<llm-content-safety>`. |
| API `openai` | Imports the Azure OpenAI OpenAPI spec at `/openai`, so SDKs hit `https://<gateway>/openai/...` exactly like the native AOAI endpoint. |
| Product `corp-llm` + subscription `corp-llm-default` | Default subscription key the caller passes via `api-key` header. Add more subscriptions per team if needed. |
| Diagnostic settings → existing App Insights | Sends APIM request logs (incl. prompt/completion sizes) to the same workspace as `corp.agent.invocation`. |

## What it does NOT do (yet)

- **Semantic caching** — needs Azure Cache for Redis Enterprise with RediSearch. Cost ~€500/month; skipped for the POC.
- **Per-team subscriptions** — only `corp-llm-default` is created. Add more by repeating the `subscriptionTeam*` resource shape.
- **Wiring corp.py through APIM** — that is Sprint 3 in the roadmap. See "Next steps" below.

## Deploy

```powershell
# Reuse the env you already have (.env.scenario-3 in the repo root).
.\scenario-3\infra\deploy_aigateway.ps1
```

The script:

1. Reads subscription / RG / base name from `.env.scenario-3`.
2. Runs `az deployment group create` against `aigateway.bicep`.
3. Prints the gateway URL and the default subscription key.
4. Appends `AZURE_OPENAI_GATEWAY_*` lines to `.env.scenario-3` so the Python
   side can start using them.

⚠️ APIM StandardV2 takes **~15–25 minutes** the first time. Subsequent
deploys are < 2 min.

## Verify

```powershell
# Discover the gateway URL the script wrote into .env.scenario-3
$gw = (Get-Content .env.scenario-3 | Select-String '^AZURE_OPENAI_GATEWAY_ENDPOINT=').Line.Split('=',2)[1]
$key = (Get-Content .env.scenario-3 | Select-String '^AZURE_OPENAI_GATEWAY_SUBSCRIPTION_KEY=').Line.Split('=',2)[1]

curl.exe -X POST "$gw/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-10-21" `
  -H "Content-Type: application/json" `
  -H "api-key: $key" `
  -H "X-Corp-Team: governance" `
  -H "X-Corp-Actor: $env:USERNAME" `
  -H "X-Corp-Agent: smoke-test" `
  -H "X-Corp-Corr-Id: smoke-$(Get-Date -Format yyyyMMddHHmmss)" `
  -d '{"messages":[{"role":"user","content":"ping"}],"max_tokens":10}'
```

Then in App Insights:

```kusto
customMetrics
| where timestamp > ago(15m)
| where name in ("Total Tokens", "Prompt Tokens", "Completion Tokens")
| extend
    team   = tostring(customDimensions["CorpTeam"]),
    actor  = tostring(customDimensions["CorpActor"]),
    agent  = tostring(customDimensions["CorpAgent"]),
    corr   = tostring(customDimensions["CorpCorrId"]),
    model  = tostring(customDimensions["DeploymentName"])
| project timestamp, name, value, team, actor, agent, corr, model
| order by timestamp desc
```

## Next steps (Sprint 3 in the roadmap)

1. Add a `build_aoai_client()` helper in `scenario-3/src/` that returns an
   `AzureOpenAI` configured against the APIM gateway when
   `AZURE_OPENAI_GATEWAY_ENDPOINT` is set, with `default_headers` injecting
   `X-Corp-Team`, `X-Corp-Actor`, `X-Corp-Agent`, `X-Corp-Corr-Id`.
2. Refactor `corp.py` to use it. One-line swap.
3. Mirror in the VS Code extension (Capa 4) so the IDE also goes via APIM.
