"""
Experiment 3 — run_quality.py
==============================

Same Foundry LLM-as-judge evaluators as scenario-2 (Coherence,
Fluency, Groundedness, Relevance, Similarity), pointed at the
scenario-3 traces produced by `src/pipeline.py`. Uploads the run to
the Foundry project so results appear under `AI Foundry portal -> Evaluation`.

Reuses the Foundry project from scenario-2 (no need to deploy a new
one — both experiments share the same `.env.scenario-2`).
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
# Prefer the exp-3 dedicated stack (.env.scenario-3); fall back to exp-2's .env.scenario-2
# if the exp-3 infra has not been deployed yet.
load_dotenv(REPO_ROOT / ".env.scenario-2")
load_dotenv(REPO_ROOT / ".env.scenario-3", override=True)

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
        print(f"[quality] {traces_path} not found. Run src/pipeline.py first.", file=sys.stderr)
        return 2

    print(f"[quality] judge   : {DEPLOYMENT} @ {ENDPOINT}")
    print(f"[quality] project : {PROJECT_ENDPOINT}")
    print(f"[quality] data    : {traces_path}")

    result = evaluate(
        evaluation_name="exp3-quality",
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
