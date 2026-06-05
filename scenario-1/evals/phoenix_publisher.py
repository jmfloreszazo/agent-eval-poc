"""
Publish DeepEval scores as span annotations into Phoenix.

Why this exists: pytest (DeepEval) and Phoenix live in separate worlds.
DeepEval evaluates and prints pass/fail to the terminal; Phoenix only shows
what it receives via its API. This helper closes the loop: it runs the
metric, ships the score to the matching span in Phoenix, then asserts so the
CI pipeline still has teeth.
"""
from __future__ import annotations

import os
from typing import Any

# Phoenix is optional: if not installed or not running, tests keep working
# as before (annotations just won't be published).
try:
    from phoenix.client import Client as _PhoenixClient

    _PHOENIX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PHOENIX_AVAILABLE = False


PHOENIX_ENDPOINT = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006")
PHOENIX_PROJECT = os.getenv("PHOENIX_PROJECT", "azure-cost-agent")

_client = None


def _get_client():
    global _client
    if not _PHOENIX_AVAILABLE:
        return None
    if _client is None:
        try:
            _client = _PhoenixClient(base_url=PHOENIX_ENDPOINT)
        except Exception as exc:  # pragma: no cover
            print(f"[phoenix_publisher] WARN: cannot create client: {exc}")
            return None
    return _client


def publish(eval_name: str, span_id: str | None, score: float | None,
            passed: bool, reason: str | None) -> None:
    """Upload an annotation (score + label + reason) to the given span."""
    if not span_id:
        return
    client = _get_client()
    if client is None:
        return

    try:
        client.spans.add_span_annotation(
            span_id=span_id,
            annotation_name=eval_name,
            annotator_kind="CODE",
            label="pass" if passed else "fail",
            score=float(score) if score is not None else 0.0,
            explanation=reason or "",
            sync=True,
        )
    except Exception as exc:  # pragma: no cover
        # A dead Phoenix must not bring the tests down.
        print(f"[phoenix_publisher] WARN: could not publish {eval_name}: {exc}")


def run_metric_and_log(case, metric, eval_name: str) -> None:
    """
    Run `metric.measure(case.test_case)`, publish the result to Phoenix
    against the agent span, and assert so pytest fails when it does not pass.
    """
    metric.measure(case.test_case)
    score = getattr(metric, "score", None)
    reason = getattr(metric, "reason", None)
    threshold = getattr(metric, "threshold", 0.0)
    passed = bool(getattr(metric, "success", (score or 0) >= threshold))

    publish(eval_name=eval_name, span_id=case.span_id,
            score=score, passed=passed, reason=reason)

    assert passed, (
        f"[{case.id}] {eval_name} score={score} threshold={threshold} reason={reason}"
    )


def log_simple(case, eval_name: str, passed: bool, score: float,
               reason: str) -> None:
    """For deterministic metrics (no LLM) that are not DeepEval objects."""
    publish(eval_name=eval_name, span_id=case.span_id,
            score=score, passed=passed, reason=reason)
