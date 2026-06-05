"""
Agent evaluation suite for CI.

Three layers, cheap to expensive:
  1. ToolCorrectnessMetric  -> deterministic, no LLM, no cost (always runs).
  2. Token budget           -> cost / FinOps regression, no LLM.
  3. GEval (task completion, groundedness) + AnswerRelevancy -> LLM-as-judge,
     only if a judge is configured.

Each metric also publishes its score as an annotation in Phoenix (on the
matching `agent.invoke` span) via phoenix_publisher. That way the UI shows
the same numbers pytest does, without duplicating evaluation logic.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from trajectory_loader import load_cases
from phoenix_publisher import log_simple, run_metric_and_log

TRAJECTORY_PATH = os.getenv(
    "TRAJECTORY_PATH",
    str(Path(__file__).resolve().parents[1] / "data" / "trajectory.json"),
)

CASES = load_cases(TRAJECTORY_PATH)

HAS_JUDGE = bool(
    os.getenv("OPENAI_API_KEY")
    or os.getenv("AZURE_OPENAI_API_KEY")
    or os.getenv("LOCAL_MODEL_API_KEY")
)
JUDGE_MODEL = os.getenv("DEEPEVAL_JUDGE_MODEL", "gpt-4o-mini")


def _uses_managed_provider() -> bool:
    return (
        os.getenv("USE_AZURE_OPENAI", "").upper() in ("YES", "TRUE", "1")
        or os.getenv("USE_LOCAL_MODEL", "").upper() in ("YES", "TRUE", "1")
    )


# ---------------------------------------------------------------------------
# Layer 1 - Tool correctness (deterministic, no LLM)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_tool_correctness(case):
    from deepeval.metrics import ToolCorrectnessMetric

    metric = ToolCorrectnessMetric(threshold=1.0, should_consider_ordering=False)
    run_metric_and_log(case, metric, eval_name="ToolCorrectness")


# ---------------------------------------------------------------------------
# Layer 2 - Token budget (deterministic, no LLM)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_token_budget(case):
    passed = case.tokens_total <= case.token_budget
    ratio = case.tokens_total / case.token_budget if case.token_budget else 1.0
    # Score: 1.0 under budget, falls off linearly when over.
    score = 1.0 if passed else max(0.0, 2.0 - ratio)
    reason = (
        f"{case.tokens_total} tokens vs budget {case.token_budget} "
        f"({ratio:.0%})"
    )
    log_simple(case, eval_name="TokenBudget", passed=passed,
               score=score, reason=reason)
    assert passed, reason


# ---------------------------------------------------------------------------
# Layer 3 - LLM-as-judge
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not HAS_JUDGE, reason="no LLM judge (OPENAI_API_KEY / AZURE_OPENAI_API_KEY)")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_task_completion(case):
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    kwargs = dict(
        name="TaskCompletion",
        criteria=(
            "Decide whether 'actual_output' answers the user's request in "
            "'input' in a complete and correct way, without inventing data."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.7,
    )
    if not _uses_managed_provider():
        kwargs["model"] = JUDGE_MODEL
    run_metric_and_log(case, GEval(**kwargs), eval_name="TaskCompletion")


@pytest.mark.skipif(not HAS_JUDGE, reason="no LLM judge (OPENAI_API_KEY / AZURE_OPENAI_API_KEY)")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_groundedness(case):
    """Custom GEval: penalize figures/resources not present in retrieval_context."""
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    kwargs = dict(
        name="Groundedness",
        criteria=(
            "Every figure (USD, %, quantities) and every resource name cited in "
            "'actual_output' MUST be locatable literally in one of the items of "
            "'retrieval_context' (which contains the real tool outputs). "
            "Heavily penalize any number or resource that does not appear in the "
            "context: that is hallucination."
        ),
        evaluation_params=[
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.RETRIEVAL_CONTEXT,
        ],
        threshold=0.8,
    )
    if not _uses_managed_provider():
        kwargs["model"] = JUDGE_MODEL
    run_metric_and_log(case, GEval(**kwargs), eval_name="Groundedness")


@pytest.mark.skipif(not HAS_JUDGE, reason="no LLM judge (OPENAI_API_KEY / AZURE_OPENAI_API_KEY)")
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_answer_relevancy(case):
    from deepeval.metrics import AnswerRelevancyMetric

    kwargs = dict(threshold=0.7)
    if not _uses_managed_provider():
        kwargs["model"] = JUDGE_MODEL
    run_metric_and_log(case, AnswerRelevancyMetric(**kwargs),
                       eval_name="AnswerRelevancy")
