"""
Load the trajectory produced by the .NET agent and turn it into DeepEval
cases. This is the only place where Python knows about the JSON contract;
the rest of the harness deals with DeepEval objects directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from deepeval.test_case import LLMTestCase, ToolCall


@dataclass(frozen=True)
class EvalCase:
    id: str
    test_case: LLMTestCase
    tokens_total: int
    token_budget: int
    trace_id: str | None = None
    span_id: str | None = None


def _to_tool_call(raw: dict) -> ToolCall:
    return ToolCall(
        name=raw["name"],
        input_parameters=raw.get("input_parameters") or {},
        output=raw.get("output"),
    )


def load_cases(path: str | Path) -> list[EvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    cases: list[EvalCase] = []
    for c in data["cases"]:
        tool_calls = [_to_tool_call(t) for t in c["tools_called"]]
        # Build a retrieval_context out of the tool outputs so that metrics
        # like Groundedness can verify the final answer is not making up
        # numbers: every figure must trace back here.
        retrieval_context = [
            json.dumps({"tool": t.name, "output": t.output}, ensure_ascii=False, default=str)
            for t in tool_calls
        ]
        test_case = LLMTestCase(
            input=c["input"],
            actual_output=c["actual_output"],
            tools_called=tool_calls,
            expected_tools=[ToolCall(name=n) for n in c["expected_tools"]],
            retrieval_context=retrieval_context,
        )
        tokens = c.get("tokens", {})
        cases.append(
            EvalCase(
                id=c["id"],
                test_case=test_case,
                tokens_total=tokens.get("total", 0),
                token_budget=c.get("token_budget", 10_000),
                trace_id=c.get("trace_id"),
                span_id=c.get("span_id"),
            )
        )
    return cases
