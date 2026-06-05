"""
hook_run_corp_pipeline.py
=========================

VS Code Copilot `UserPromptSubmit` hook bound to the `corp` agent.

Goal: zero-touch governance. The user just types the case id (or the
raw case JSON) and the hook automatically:

  1. Parses the prompt for a case id (`case-XXX`) or `--all`.
  2. Runs `scenario-3/src/corp.py` in a subprocess (which opens the
     parent span, calls the two domain agents, and emits the canonical
     `corp.agent.invocation` spans with official token usage + cost).
  3. Captures stdout (JSON) and feeds it back to the chat turn via the
     hook protocol's `additionalContext` field, so the LLM in the
     `corp` chat mode just formats it for the user. The model NEVER
     decides whether to invoke the pipeline — the hook always does.

This guarantees telemetry is emitted on every `corp` turn, regardless
of what the LLM does (or doesn't do).

Hook envelope (JSON on stdin), per VS Code Copilot docs:

  {
    "hookEventName": "UserPromptSubmit",
    "agent":   "corp",
    "session": "<chat session id>",
    "prompt":  "case-001"
  }

Hook response (JSON on stdout):

  {
    "continue": true,
    "additionalContext": "<corp.py stdout / error block>"
  }

Exit 0 always — telemetry/runner failures must never block the chat.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORP_PY = REPO_ROOT / "scenario-3" / "src" / "corp.py"
VENV_PY = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


CASE_ID_RE = re.compile(r"\bcase-\d{3,}\b", re.IGNORECASE)


def _extract_intent(prompt: str) -> dict:
    """Decide how to invoke corp.py from the free-text prompt."""
    text = (prompt or "").strip()
    if not text:
        return {"mode": "noop", "reason": "empty prompt"}

    lowered = text.lower()
    if "--all" in lowered or "todos los casos" in lowered or "run all" in lowered:
        return {"mode": "all"}

    m = CASE_ID_RE.search(text)
    if m:
        return {"mode": "case", "case_id": m.group(0).lower()}

    # If the user pasted a raw JSON object, treat it as an ad-hoc case.
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return {"mode": "case_inline", "payload": text}

    return {"mode": "noop", "reason": "no case id or JSON detected"}


def _run_corp(args: list[str], cwd: Path, extra_env: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.run(
            [str(VENV_PY), str(CORP_PY), *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", (exc.stderr or "") + "\n[hook] corp.py timed out after 120s"
    except Exception as exc:  # noqa: BLE001
        return 1, "", f"[hook] failed to launch corp.py: {exc}"


def main() -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {"prompt": raw}

    prompt = (
        payload.get("prompt")
        or payload.get("userPrompt")
        or payload.get("message")
        or ""
    )
    session = (
        payload.get("session")
        or payload.get("sessionId")
        or payload.get("chatSessionId")
        or f"ide-{int(time.time())}"
    )

    intent = _extract_intent(prompt)
    started = time.time()

    if intent["mode"] == "noop":
        out_msg = (
            "[corp hook] No case id or JSON detected in the prompt — "
            f"corp.py was NOT invoked. Reason: {intent.get('reason')}.\n"
            "Send a case id (e.g. `case-001`) or paste a raw case JSON.\n"
        )
        rc, stdout, stderr = 0, "", ""
    elif intent["mode"] == "all":
        rc, stdout, stderr = _run_corp(
            ["--all"],
            cwd=REPO_ROOT,
            extra_env={"CORP_CHAT_SESSION_ID": session},
        )
        out_msg = ""
    elif intent["mode"] == "case":
        rc, stdout, stderr = _run_corp(
            ["--case", intent["case_id"]],
            cwd=REPO_ROOT,
            extra_env={"CORP_CHAT_SESSION_ID": session},
        )
        out_msg = ""
    elif intent["mode"] == "case_inline":
        # Persist the inline JSON to a temp file and pass --case-file if
        # corp.py supports it; otherwise fall back to writing into the
        # dataset path.
        tmp = Path(tempfile.gettempdir()) / f"corp_inline_{int(time.time())}.json"
        tmp.write_text(intent["payload"], encoding="utf-8")
        rc, stdout, stderr = _run_corp(
            ["--case-file", str(tmp)],
            cwd=REPO_ROOT,
            extra_env={"CORP_CHAT_SESSION_ID": session},
        )
        out_msg = f"[corp hook] inline case written to {tmp}\n"
    else:
        rc, stdout, stderr = 1, "", f"[hook] unknown intent: {intent}"
        out_msg = ""

    elapsed = time.time() - started

    # Build the context block we inject back into the chat turn.
    blocks = []
    blocks.append(
        f"[corp hook] automatic invocation — mode={intent['mode']} "
        f"rc={rc} elapsed={elapsed:.1f}s session={session}"
    )
    if out_msg:
        blocks.append(out_msg.strip())
    if stdout:
        blocks.append("=== corp.py STDOUT ===\n" + stdout.strip())
    if stderr:
        blocks.append("=== corp.py STDERR (tail) ===\n" + "\n".join(stderr.strip().splitlines()[-20:]))
    if not stdout and not stderr and intent["mode"] != "noop":
        blocks.append("(corp.py produced no output)")

    additional_context = "\n\n".join(blocks)

    response = {
        "continue": True,
        # VS Code Copilot UserPromptSubmit hooks honor `additionalContext`
        # to inject text into the model's context for this turn.
        "additionalContext": additional_context,
    }

    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
