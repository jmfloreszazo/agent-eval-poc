"""
Experiment 2 - setup_continuous_eval.py
=========================================

Creates (or updates) a **continuous evaluation rule** on the Foundry
project so every ``response_completed`` event from the hosted agent
``AZURE_AI_AGENT_NAME`` is scored by a set of built-in evaluators.

Results land in two places:
  * The Foundry portal **Monitor** tab of the agent (charts + per-run
    evaluation scores).
  * App Insights, queryable with KQL on ``gen_ai.evaluation.result``.

Run **once** after `infra/deploy.ps1` and **before** the first hosted
agent run:

    .\\.venv\\Scripts\\python.exe scenario-2\\evals\\setup_continuous_eval.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env.scenario-2")

from azure.ai.projects import AIProjectClient  # noqa: E402
from azure.ai.projects.models import (  # noqa: E402
    ContinuousEvaluationRuleAction,
    EvaluationRule,
    EvaluationRuleEventType,
    EvaluationRuleFilter,
)
from azure.identity import AzureCliCredential  # noqa: E402

PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
AGENT_NAME = os.environ.get("AZURE_AI_AGENT_NAME", "exp2-finops-agent")
RULE_ID = os.environ.get("AZURE_AI_EVAL_RULE_ID", "exp2-continuous-eval")
MAX_HOURLY_RUNS = int(os.environ.get("AZURE_AI_EVAL_MAX_HOURLY_RUNS", "100"))
JUDGE_DEPLOYMENT = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.environ.get(
    "AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"
)

# Data mappings - the `azure_ai_source / scenario=responses` data source
# exposes the agent's query/response/context as template variables.
MAP_QR = {
    "query": "{{item.query}}",
    "response": "{{item.response}}",
}
MAP_QRC = {**MAP_QR, "context": "{{item.context}}"}
MAP_R = {"response": "{{item.response}}"}

# Quality evaluators need a judge LLM (deployment_name).
JUDGE_INIT = {"deployment_name": JUDGE_DEPLOYMENT}

# (display_name, builtin id, data_mapping, init_params)
EVALUATORS: list[tuple[str, str, dict, dict | None]] = [
    ("relevance",          "builtin.relevance",          MAP_QR,  JUDGE_INIT),
    ("coherence",          "builtin.coherence",          MAP_QR,  JUDGE_INIT),
    ("fluency",            "builtin.fluency",            MAP_R,   JUDGE_INIT),
    ("groundedness_pro",   "builtin.groundedness_pro",   MAP_QRC, None),
    ("violence",           "builtin.violence",           MAP_QR,  None),
    ("self_harm",          "builtin.self_harm",          MAP_QR,  None),
    ("hate_unfairness",    "builtin.hate_unfairness",    MAP_QR,  None),
    ("sexual",             "builtin.sexual",             MAP_QR,  None),
    ("indirect_attack",    "builtin.indirect_attack",    MAP_QR,  None),
    ("protected_material", "builtin.protected_material", MAP_QR,  None),
]


def main() -> int:
    print(f"[ceval] project : {PROJECT_ENDPOINT}")
    print(f"[ceval] agent   : {AGENT_NAME}")
    print(f"[ceval] rule_id : {RULE_ID}")
    print(f"[ceval] judge   : {JUDGE_DEPLOYMENT}")
    print(f"[ceval] evals   : {', '.join(n for n, *_ in EVALUATORS)}")

    credential = AzureCliCredential()
    with (
        AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential) as project_client,
        project_client.get_openai_client() as openai_client,
    ):
        # Step 1: create the evaluation definition (data source = agent
        # responses, testing criteria = the builtin evaluator IDs).
        data_source_config = {"type": "azure_ai_source", "scenario": "responses"}
        testing_criteria: list[dict] = []
        for name, ev_id, mapping, init in EVALUATORS:
            crit: dict = {
                "type": "azure_ai_evaluator",
                "name": name,
                "evaluator_name": ev_id,
                "data_mapping": mapping,
            }
            if init:
                crit["initialization_parameters"] = init
            testing_criteria.append(crit)
        eval_object = openai_client.evals.create(
            name=f"continuous-eval-{AGENT_NAME}",
            data_source_config=data_source_config,  # type: ignore[arg-type]
            testing_criteria=testing_criteria,      # type: ignore[arg-type]
        )
        print(f"[ceval] eval id : {eval_object.id}")

        # Step 2: create-or-update the rule that fires on every
        # response_completed event from our agent.
        rule = project_client.evaluation_rules.create_or_update(
            id=RULE_ID,
            evaluation_rule=EvaluationRule(
                display_name="exp2 continuous evaluation",
                description="Runs builtin quality + safety evaluators on every "
                            "completed response from the exp2 hosted agent.",
                action=ContinuousEvaluationRuleAction(
                    eval_id=eval_object.id,
                    max_hourly_runs=MAX_HOURLY_RUNS,
                ),
                event_type=EvaluationRuleEventType.RESPONSE_COMPLETED,
                filter=EvaluationRuleFilter(agent_name=AGENT_NAME),
                enabled=True,
            ),
        )
        print(f"[ceval] rule    : {rule.id} (enabled={rule.enabled})")
        print(f"[ceval] limit   : {MAX_HOURLY_RUNS} runs/hour")

    print("[ceval] OK - now run scenario-2/src/hosted_agent.py to generate traffic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
