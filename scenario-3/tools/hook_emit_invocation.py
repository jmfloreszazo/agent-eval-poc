"""
hook_emit_invocation.py
=======================

VS Code Copilot agent hook. Wired into `.github/agents/*.agent.md` via
`hooks.UserPromptSubmit` so that EVERY direct chat invocation of one of
our custom agents (`fraud-analyst`, `legal-counsel`, `corp`) emits a
governance span to Application Insights — even when the user bypasses
the corp gateway and talks to a specialist directly from the chat picker.

VS Code passes the hook a JSON envelope on stdin, roughly:

    {
      "hookEventName": "UserPromptSubmit",
      "agent":   "fraud-analyst",          # or whatever was selected
      "session": "<chat session id>",
      "prompt":  "<the user's message text>",
      "workspace": "<repo path>"
    }

We don't know the model response yet (the model hasn't run), so we emit
an INVOCATION-START span with token *estimates* and zero output tokens.
This guarantees Compliance/FinOps sees every IDE invocation, even when:

  - the user picked the agent directly from the picker (no corp run)
  - the user runs offline / fully in the IDE (no batch script)

When the same agent IS routed through `corp.py`, the canonical span from
`telemetry.emit_invocation` will land too (with the full output and
official token counts). The two are correlated by `corp.chat_session_id`.

Exit code is always 0 — we never want a telemetry failure to block the
user's prompt.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "scenario-3" / "src"
sys.path.insert(0, str(SRC_DIR))


def _safe_emit(payload: dict) -> None:
    """Best-effort emit. Any failure is swallowed."""
    try:
        from dotenv import load_dotenv  # noqa: E402

        load_dotenv(REPO_ROOT / ".env.scenario-2")
        load_dotenv(REPO_ROOT / ".env.scenario-3", override=True)
        load_dotenv(REPO_ROOT / "scenario-3" / ".env", override=True)

        import telemetry  # noqa: E402

        telemetry.configure(service_name="exp3-corp")

        agent_name = (
            payload.get("agent")
            or payload.get("agentName")
            or os.environ.get("VSCODE_AGENT_NAME")
            or "unknown-agent"
        )
        prompt_text = (
            payload.get("prompt")
            or payload.get("userPrompt")
            or payload.get("message")
            or ""
        )
        session_id = (
            payload.get("session")
            or payload.get("sessionId")
            or payload.get("chatSessionId")
            or f"ide-{uuid.uuid4().hex[:8]}"
        )
        actor = (
            os.environ.get("USERNAME")
            or os.environ.get("USER")
            or "ide-user"
        )

        # IMPORTANT: VS Code Copilot does NOT pass the underlying model
        # used (Claude Opus, GPT-4o, etc.) nor the LLM response/tokens
        # to hooks. We can only see the user's prompt. So we tag the
        # model as 'vscode-copilot-chat:unknown' and emit a single
        # start-only span with input estimates and output_tokens=0.
        # The real cost/tokens are only available when the LLM call is
        # made by `corp.py` (which uses our own Azure OpenAI keys).
        corr_id = f"ide:{session_id}:{int(time.time() * 1000)}"
        telemetry.emit_invocation(
            agent_name=agent_name,
            agent_version="ide-1",
            model=os.environ.get("EXP3_IDE_MODEL", "vscode-copilot-chat:unknown"),
            input_text=prompt_text,
            output_text="",  # not yet generated, never knowable from hook
            official_usage=None,  # forces estimation path for input only
            actor=actor,
            team={
                "fraud-analyst": "finance-forensics",
                "legal-counsel": "legal",
                "corp": "governance",
            }.get(agent_name, "unknown"),
            repo="agent-eval-poc",
            chat_session_id=session_id,
            verdict="ide-invocation",
            corr_id=corr_id,
            extra={
                "stage": "ide-prompt",
                "orchestrator": "ide-direct",
                "hook_event": payload.get("hookEventName", "UserPromptSubmit"),
                "surface": "vscode-copilot-chat",
                "model_known": False,
                "model_note": "VS Code Copilot does not expose model/tokens to hooks; use corp.py for governed runs.",
            },
        )
        # Surface the correlation id so it shows up in the chat panel
        # (stderr is shown by VS Code when a hook produces output) and
        # can be pasted into App Insights to find this exact span.
        sys.stderr.write(
            f"[telemetry] agent={agent_name} corr_id={corr_id} "
            f"session={session_id} (model unknown — Copilot does not "
            "expose the underlying model to hooks)\n"
        )
    except Exception as exc:  # noqa: BLE001
        # Never block the chat turn on telemetry failure.
        sys.stderr.write(f"[hook_emit_invocation] non-fatal error: {exc}\n")


def main() -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {"prompt": raw}

    # Allow CLI override of the agent name (used in the .agent.md hook
    # config so we know which agent fired without parsing the envelope).
    if len(sys.argv) > 1 and sys.argv[1]:
        payload["agent"] = sys.argv[1]

    _safe_emit(payload)

    # We don't need to talk back to VS Code beyond exit 0.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
