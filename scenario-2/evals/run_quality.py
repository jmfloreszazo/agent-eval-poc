"""
Experiment 2 — run_quality.py
==============================

Runs Foundry **quality** evaluators against the agent's traces and
**uploads the run to the Foundry project** so results appear under
`AI Foundry portal -> Evaluation`.

Evaluators (LLM-as-judge, gpt-4o-mini as judge):

    Coherence | Fluency | Groundedness | Relevance | Similarity
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env.scenario-2")

from azure.ai.evaluation import (  # noqa: E402
    AzureOpenAIModelConfiguration,
    CoherenceEvaluator,
    FluencyEvaluator,
    GroundednessEvaluator,
    RelevanceEvaluator,
    SimilarityEvaluator,
    evaluate,
)

ENDPOINT = os.environ["AZURE_AI_FOUNDRY_ENDPOINT"]
API_KEY = os.environ["AZURE_AI_FOUNDRY_API_KEY"]
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
PROJECT_ENDPOINT = os.environ["AZURE_AI_PROJECT_ENDPOINT"]

JUDGE: AzureOpenAIModelConfiguration = {
    "type": "azure_openai",
    "azure_endpoint": ENDPOINT,
    "api_key": API_KEY,
    "azure_deployment": DEPLOYMENT,
    "api_version": API_VERSION,
}

EVALUATORS = {
    "coherence": CoherenceEvaluator(JUDGE),
    "fluency": FluencyEvaluator(JUDGE),
    "groundedness": GroundednessEvaluator(JUDGE),
    "relevance": RelevanceEvaluator(JUDGE),
    "similarity": SimilarityEvaluator(JUDGE),
}

# Map our traces.jsonl columns to the canonical fields each evaluator
# expects. `${data.<col>}` references columns of the input dataset.
COMMON_MAPPING = {
    "query": "${data.question}",
    "response": "${data.response}",
    "context": "${data.context}",
    "ground_truth": "${data.context}",
}
EVALUATOR_CONFIG = {name: {"column_mapping": COMMON_MAPPING} for name in EVALUATORS}


def main() -> int:
    traces_path = Path(__file__).resolve().parents[1] / "data" / "traces.jsonl"
    out_jsonl = Path(__file__).resolve().parents[1] / "data" / "quality.jsonl"
    out_json = out_jsonl.with_suffix(".json")

    if not traces_path.exists():
        print(f"[quality] {traces_path} not found. Run src/agent.py first.", file=sys.stderr)
        return 2

    print(f"[quality] judge   : {DEPLOYMENT} @ {ENDPOINT}")
    print(f"[quality] project : {PROJECT_ENDPOINT}")
    print(f"[quality] data    : {traces_path}")

    # evaluate() runs every evaluator on every row, uploads the run to
    # the Foundry project, and writes per-row results to output_path.
    result = evaluate(
        evaluation_name="exp2-quality",
        data=str(traces_path),
        evaluators=EVALUATORS,
        evaluator_config=EVALUATOR_CONFIG,
        azure_ai_project=PROJECT_ENDPOINT,
        output_path=str(out_json),
    )

    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    print("[quality] metrics :")
    for k, v in sorted(metrics.items()):
        print(f"  - {k}: {v}")

    studio_url = (result.get("studio_url") if isinstance(result, dict) else None) or "(no studio_url)"
    print(f"[quality] studio  : {studio_url}")

    # Flatten the evaluate() JSON into the JSONL shape governance.py expects.
    if out_json.exists():
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        rows = payload.get("rows", [])
        with out_jsonl.open("w", encoding="utf-8") as f:
            for r in rows:
                flat = {"id": r.get("inputs.id") or r.get("id")}
                for name in EVALUATORS:
                    key = next(
                        (
                            k for k in r
                            if k.startswith(f"outputs.{name}.")
                            and not k.endswith("_reason")
                            and not k.endswith("_threshold")
                            and not k.endswith("_result")
                        ),
                        None,
                    )
                    flat[name] = r.get(key) if key else None
                f.write(json.dumps(flat, ensure_ascii=False) + "\n")
        print(f"[quality] wrote   : {out_jsonl}")

    print("[quality] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
