"""
Token estimation across LLM families.

Used by `telemetry.py` to populate `gen_ai.usage.input_tokens` and
`output_tokens` when the SDK does not return them (Copilot SaaS,
opaque endpoints) or when you want to estimate cost before the call.

Source of truth precedence:
    1. Official `usage.*` from the SDK response  -> source="official"
    2. Local tokenizer (tiktoken / Anthropic SDK) -> source="estimated:<encoder>"

Always pair the count with the `source` so KQL can distinguish
official vs estimated coverage.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None  # type: ignore[assignment]


@dataclass(frozen=True)
class TokenCount:
    input_tokens: int
    output_tokens: int
    source: str  # "official" | "estimated:tiktoken:<encoder>" | "estimated:anthropic-sdk" | ...

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# OpenAI / Azure OpenAI / GitHub Models (tiktoken)
# ---------------------------------------------------------------------------

# Modern models all use o200k_base; older 3.5/4 use cl100k_base.
_DEFAULT_ENCODER = "o200k_base"


@lru_cache(maxsize=8)
def _tiktoken_encoder(name: str):
    if tiktoken is None:
        raise RuntimeError("tiktoken is not installed; run `pip install tiktoken`")
    return tiktoken.get_encoding(name)


def _count_tiktoken(text: str, encoder: str = _DEFAULT_ENCODER) -> int:
    if not text:
        return 0
    return len(_tiktoken_encoder(encoder).encode(text))


# ---------------------------------------------------------------------------
# Anthropic (SDK)
# ---------------------------------------------------------------------------

def _count_anthropic(text: str, model: str) -> int:
    """Use Anthropic's free /count_tokens endpoint via the SDK.

    Falls back to a tiktoken approximation if the SDK or network is not
    available, so a CI box without internet still gets a number.
    """
    try:
        from anthropic import Anthropic

        client = Anthropic()
        result = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return int(result.input_tokens)
    except Exception:
        # Fallback: tiktoken o200k is ~5-10% off for Claude but better
        # than nothing when we cannot reach Anthropic.
        return _count_tiktoken(text, _DEFAULT_ENCODER)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def count_tokens(text: str, *, model: str, encoder: str | None = None) -> tuple[int, str]:
    """Return (token_count, source) for a piece of text.

    `encoder` overrides auto-detection; `model` is used for the
    Anthropic SDK call and to set a meaningful `source` tag.
    """
    text = text or ""
    if encoder == "anthropic-sdk" or model.startswith("claude"):
        return _count_anthropic(text, model), "estimated:anthropic-sdk"
    enc = encoder or _DEFAULT_ENCODER
    return _count_tiktoken(text, enc), f"estimated:tiktoken:{enc}"


def estimate_messages(
    messages: Iterable[dict[str, Any]],
    *,
    model: str,
    encoder: str | None = None,
    tools_schema: Any = None,
    hidden_input_tokens: int = 0,
) -> tuple[int, str]:
    """Estimate input tokens for an OpenAI-style messages array.

    Adds per-message envelope overhead (~4 tokens) and tools schema if
    provided. `hidden_input_tokens` accounts for system prompts or
    tool definitions that you can't see (Copilot SaaS).
    """
    total = 0
    source = "estimated:tiktoken:" + (encoder or _DEFAULT_ENCODER)
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            # multimodal: collapse text parts; images are NOT tokenized here
            content = "\n".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        n, src = count_tokens(str(content), model=model, encoder=encoder)
        total += n + 4  # role/separator envelope
        source = src
    if tools_schema:
        n, _ = count_tokens(json.dumps(tools_schema), model=model, encoder=encoder)
        total += n
    total += int(hidden_input_tokens)
    return total, source


def from_official_usage(usage: Any) -> TokenCount | None:
    """Try to extract official usage from a provider response object."""
    if usage is None:
        return None
    # OpenAI / AOAI: CompletionUsage(prompt_tokens, completion_tokens, total_tokens)
    # Responses API: usage(input_tokens, output_tokens, total_tokens)
    # Anthropic: usage(input_tokens, output_tokens)
    inp = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_tokens", None)
    )
    out = (
        getattr(usage, "output_tokens", None)
        or getattr(usage, "completion_tokens", None)
    )
    if inp is None or out is None:
        return None
    return TokenCount(input_tokens=int(inp), output_tokens=int(out), source="official")
