"""
Check Foundry continuous-evaluation rule status.

Continuous-eval RESULTS surface in the Foundry portal:
  Build -> Agents -> <agent> -> Monitor / Evaluation tabs
  (runs are not exposed via the OpenAI evals.runs API for Foundry-hosted
   eval definitions; they live as agent traces with evaluation columns).

This script verifies the rule is wired, enabled, and points to the
expected agent + eval definition.
"""
from __future__ import annotations

import os
from pathlib import Path

from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient


def _load_env() -> None:
    p = Path(__file__).resolve().parents[1].parent / ".env.scenario-2"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main() -> int:
    _load_env()
    project_endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    rule_id = os.environ.get("AZURE_AI_CONTINUOUS_EVAL_RULE_ID", "exp2-continuous-eval")
    agent_name = os.environ.get("AZURE_AI_AGENT_NAME", "exp2-finops-agent")

    cred = AzureCliCredential(process_timeout=60)
    project_client = AIProjectClient(endpoint=project_endpoint, credential=cred)

    rule = project_client.evaluation_rules.get(id=rule_id)
    print(f"[ceval-check] rule    : {rule.id} (enabled={rule.enabled})")
    print(f"[ceval-check] event   : {rule.event_type}")
    print(f"[ceval-check] agent   : {rule.filter.agent_name if rule.filter else '-'}")
    eval_id = rule.action.eval_id
    max_per_hour = getattr(rule.action, "max_hourly_runs", "-")
    print(f"[ceval-check] eval_id : {eval_id} (limit {max_per_hour}/h)")

    # Portal URL helpers
    print()
    print("[ceval-check] View results in Foundry portal:")
    print(f"  https://ai.azure.com/")
    print(f"  -> Build -> Agents -> {agent_name}")
    print( "  -> Monitor tab        (dashboards with eval scores)")
    print( "  -> Tracing tab        (per-trace Evaluation columns)")
    print()
    print("[ceval-check] Continuous eval typically takes 30-90s after each")
    print("              response_completed event before scores appear.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

