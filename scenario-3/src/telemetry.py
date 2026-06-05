"""
Emit a single `corp.agent.invocation` span per LLM turn to App Insights.

This is the function you call from any place that does an LLM call —
the corp agent (Foundry), the Copilot Extension server, a CLI, a
Function App processing webhooks, ...  It records tokens (official or
estimated) and cost in USD with the day's pricing.

Configure once at process start:

    from telemetry import configure
    configure(service_name="exp3-finops-demo")

Then per call:

    from telemetry import emit_invocation
    emit_invocation(
        agent_name="exp3-finops-agent",
        agent_version="1",
        model="gpt-4o-mini",
        input_text="...",          # for estimation if no official usage
        output_text="...",         # idem
        official_usage=resp.usage, # OPTIONAL; preferred when available
        actor="jose@corp",
        repo="agent-eval-poc",
        verdict="approve",
        chat_session_id=session_id,
        team="platform",
    )
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from opentelemetry import trace

from tokens import (
    TokenCount,
    count_tokens,
    estimate_messages,
    from_official_usage,
)
from pricing import cost, overhead, price_for


_tracer: trace.Tracer | None = None


def configure(service_name: str = "exp3-corp-agent") -> None:
    """Wire OTel to Application Insights (idempotent)."""
    global _tracer
    if _tracer is not None:
        return

    # Capture message content on spans so Foundry Tracing UI shows
    # input/output, like exp-2 does.
    os.environ.setdefault(
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true"
    )

    conn = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if conn:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=conn,
            resource_attributes={
                "service.name": service_name,
                "service.namespace": "agent-eval-poc",
                "experiment": "exp3",
            },
        )
    _tracer = trace.get_tracer("corp.agent")


def _resolve_tokens(
    *,
    model: str,
    input_text: str | None,
    output_text: str | None,
    official_usage: Any,
    opaque_profile: str | None,
) -> TokenCount:
    """Pick official usage if present, otherwise estimate."""
    official = from_official_usage(official_usage)
    if official is not None:
        return official

    # Estimation path.
    over = overhead(opaque_profile or "direct")
    p = price_for(model)
    encoder = p.encoder

    in_tok = 0
    src = "estimated"
    if input_text:
        in_tok, src = count_tokens(input_text, model=model, encoder=encoder)
    in_tok += over.hidden_input_tokens

    out_tok = 0
    if output_text:
        n, _ = count_tokens(output_text, model=model, encoder=encoder)
        out_tok += n
    out_tok += over.hidden_output_tokens

    return TokenCount(input_tokens=in_tok, output_tokens=out_tok, source=src)


def emit_invocation(
    *,
    agent_name: str,
    model: str,
    agent_version: str | None = None,
    input_text: str | None = None,
    output_text: str | None = None,
    official_usage: Any = None,
    opaque_profile: str | None = None,   # e.g. "github-copilot-chat"
    actor: str | None = None,
    team: str | None = None,
    repo: str | None = None,
    pr_number: int | str | None = None,
    chat_session_id: str | None = None,
    verdict: str | None = None,
    corr_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit one OTel span describing a single LLM/agent turn.

    Returns a dict snapshot of what was logged (useful for tests and
    for echoing to the workflow log).
    """
    if _tracer is None:
        configure()
    assert _tracer is not None

    tokens = _resolve_tokens(
        model=model,
        input_text=input_text,
        output_text=output_text,
        official_usage=official_usage,
        opaque_profile=opaque_profile,
    )
    usd, price_date = cost(model, tokens.input_tokens, tokens.output_tokens)
    corr_id = corr_id or uuid.uuid4().hex

    attrs: dict[str, Any] = {
        # gen_ai.* — keep the OTel semantic conventions for LLM
        "gen_ai.system": "azure.ai.foundry" if "azure" in (opaque_profile or "") else "openai",
        "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": tokens.input_tokens,
        "gen_ai.usage.output_tokens": tokens.output_tokens,
        "gen_ai.usage.total_tokens": tokens.total_tokens,
        "gen_ai.usage.source": tokens.source,
        "gen_ai.agent.name": agent_name,
        # corp.* — business / governance dimensions
        "corp.agent_name": agent_name,
        "corp.cost_usd": usd,
        "corp.pricing.date": price_date.isoformat(),
        "corp.corr_id": corr_id,
    }
    if agent_version:
        attrs["gen_ai.agent.version"] = agent_version
        attrs["corp.agent_version"] = agent_version
    if opaque_profile:
        attrs["corp.opaque_profile"] = opaque_profile
    if actor:
        attrs["corp.actor"] = actor
    if team:
        attrs["corp.team"] = team
    if repo:
        attrs["corp.repo"] = repo
    if pr_number is not None:
        attrs["corp.pr_number"] = str(pr_number)
    if chat_session_id:
        attrs["corp.chat_session_id"] = chat_session_id
    if verdict:
        attrs["corp.verdict"] = verdict
    if extra:
        for k, v in extra.items():
            attrs[f"corp.{k}"] = v

    with _tracer.start_as_current_span("corp.agent.invocation") as span:
        for k, v in attrs.items():
            span.set_attribute(k, v)

    return attrs
