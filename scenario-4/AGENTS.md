# Repository agents

This repo ships **three** custom GitHub Copilot chat modes. They live
under [.github/chatmodes/](./.github/chatmodes/) so VS Code Copilot
picks them up automatically.

| Agent | Chat mode file | Purpose |
| --- | --- | --- |
| **`@corp`** | [.github/chatmodes/corp.chatmode.md](./.github/chatmodes/corp.chatmode.md) | **Governance gateway. The only agent you may invoke directly.** Configures App Insights telemetry, opens the parent `corp.case.run` span, and dispatches to the two specialists. |
| `@fraud-analyst` | [.github/chatmodes/fraud-analyst.chatmode.md](./.github/chatmodes/fraud-analyst.chatmode.md) | Forensic accounting analyst. Reads an accounting case and emits a strict-JSON verdict (`fraud / clean / suspicious`). |
| `@legal-counsel` | [.github/chatmodes/legal-counsel.chatmode.md](./.github/chatmodes/legal-counsel.chatmode.md) | Corporate counsel. Reads the case + the analyst verdict and emits a strict-JSON list of recommended legal actions. |

## RULE 0 — never bypass `@corp`

GitHub Copilot Chat in the IDE does **not** export per-turn tokens,
prompts, model id or cost to your tenant. The only way for Compliance
and FinOps to see what an agent did is for **every** agent run to be
brokered by `@corp`, which:

1. Configures OpenTelemetry → Application Insights.
2. Opens a parent span `corp.case.run` with `case_id`, `ground_truth`,
   `actor`, `repo`, `run_id`.
3. Calls `@fraud-analyst` then `@legal-counsel` through
   `scenario-3/src/corp.py` so each turn produces one
   `corp.agent.invocation` child span with `gen_ai.usage.*`,
   `corp.cost_usd` (priced from `pricing.yaml`), `corp.verdict`.

**No telemetry, no answer.** If you invoke `@fraud-analyst` or
`@legal-counsel` directly, the run is ungoverned and will be flagged
by the governance evaluator.

> **Soft vs. hard control.** That evaluator is a *detective* control — it
> flags an ungoverned run after the fact. The *preventive* control is the
> APIM gateway with locked egress and `disableLocalAuth` (see
> [scenario-3/docs/governance-architecture.md](./scenario-3/docs/governance-architecture.md)
> §3, "Precondición de integridad"). Convention alone does not stop a
> direct call to the model.

## How to use the agents

### From VS Code chat (interactive)

1. Open the Copilot Chat panel.
2. Pick the chat mode **`corp`** from the dropdown.
3. Paste a case id (`case-001`) or the full case JSON.
4. `@corp` runs `scenario-3/src/corp.py --case <id>`, emits the
   telemetry, and replies with the structured JSON containing the two
   downstream verdicts and the cost.

### From the batch pipeline (CI / evals)

```powershell
# Single case
.\.venv\Scripts\python.exe scenario-3\src\corp.py --case case-001

# Whole dataset
.\.venv\Scripts\python.exe scenario-3\src\corp.py --all
```

See [scenario-3/README.md](./scenario-3/README.md).

## Editing the agents

The runner [scenario-3/src/corp.py](./scenario-3/src/corp.py)
reads the prompt text **directly** from the `.chatmode.md` files at
runtime (strips the YAML frontmatter, uses the body as the `system`
message). So:

- Edit the chat mode file → both the IDE and the batch evals see the
  change.
- Never copy the prompt into Python.
