"""
Experiment 3 — corp.py
=======================

**Corp governance gateway.** This is the ONE entry point that the
`@corp` chat mode (and the batch pipeline) is allowed to call. It:

  1. Configures OpenTelemetry -> Application Insights ONCE per process.
  2. Opens a parent span `corp.case.run` carrying business context
     (case_id, ground_truth, actor, repo, run_id).
  3. Dispatches to `@fraud-analyst` then `@legal-counsel` (both read
     their system prompt from `.github/chatmodes/*.chatmode.md`).
  4. Emits one child `corp.agent.invocation` span per turn via
     `telemetry.emit_invocation` — with official tokens from the SDK,
     daily-priced cost in USD, prompt + response text, verdict.

If anyone tries to invoke the downstream agents directly (bypassing
`Corp.analyze_case` / `corp.py --case`), nothing reaches App Insights
and the governance contract is broken. So:

    >>> from corp import Corp
    >>> corp = Corp()
    >>> result = corp.analyze_case(case_dict)

is the only supported way to call the chain from Python.

CLI usage:

    .\\.venv\\Scripts\\python.exe scenario-3\\src\\corp.py --all
    .\\.venv\\Scripts\\python.exe scenario-3\\src\\corp.py --case case-001
    .\\.venv\\Scripts\\python.exe scenario-3\\src\\corp.py --case-file path\\to\\case.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
# Precedence (lowest -> highest, last write wins because of override=True):
#   .env.scenario-2  (scenario-2 fallback if exp-3 infra is not deployed yet)
#   .env.scenario-3     (scenario-3-dedicated stack — preferred)
#   scenario-3/.env (local overrides, e.g. GITHUB_MODELS_TOKEN)
load_dotenv(REPO_ROOT / ".env.scenario-2")
load_dotenv(REPO_ROOT / ".env.scenario-3", override=True)
load_dotenv(REPO_ROOT / "scenario-3" / ".env", override=True)

import telemetry  # noqa: E402
from openai import AzureOpenAI, OpenAI  # noqa: E402
from opentelemetry import trace  # noqa: E402


# ----------------------------------------------------------------------------
# Model backend selection
# ----------------------------------------------------------------------------
# Two backends supported:
#   * "azure"  - Azure OpenAI deployment (exp-3 Foundry, recommended once
#                 scenario-3/infra/deploy.ps1 has run -> .env.scenario-3 exists).
#   * "github" - GitHub Models inference endpoint (handy from a laptop
#                 without Azure; needs GITHUB_MODELS_TOKEN with models:read).
#
# Auto-pick: prefer azure if AZURE_AI_FOUNDRY_ENDPOINT + API key + deployment
# are present; otherwise fall back to github. Override with EXP3_BACKEND.
GITHUB_MODELS_ENDPOINT = os.environ.get(
    "GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference"
)
GITHUB_TOKEN = (
    os.environ.get("GITHUB_MODELS_TOKEN")
    or os.environ.get("GITHUB_TOKEN")
    or os.environ.get("GH_TOKEN")
)

AZURE_FOUNDRY_ENDPOINT = os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", "").rstrip("/")
AZURE_FOUNDRY_API_KEY = os.environ.get("AZURE_AI_FOUNDRY_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

_AZURE_AVAILABLE = bool(AZURE_FOUNDRY_ENDPOINT and AZURE_FOUNDRY_API_KEY and AZURE_OPENAI_DEPLOYMENT)
_GITHUB_AVAILABLE = bool(GITHUB_TOKEN)

EXP3_BACKEND = (os.environ.get("EXP3_BACKEND") or "").strip().lower()
if EXP3_BACKEND not in ("azure", "github"):
    EXP3_BACKEND = "azure" if _AZURE_AVAILABLE else "github"

# Model id sent on the request differs by backend. For Azure OpenAI the
# `model` argument is the deployment name; for GitHub Models it is the
# catalog id (openai/gpt-4o-mini, etc).
_DEFAULT_AZURE_MODEL = AZURE_OPENAI_DEPLOYMENT
_DEFAULT_GITHUB_MODEL = "openai/gpt-4o-mini"

if EXP3_BACKEND == "azure":
    FRAUD_MODEL = os.environ.get("EXP3_FRAUD_MODEL", _DEFAULT_AZURE_MODEL)
    LEGAL_MODEL = os.environ.get("EXP3_LEGAL_MODEL", _DEFAULT_AZURE_MODEL)
    # Token pricing in pricing.yaml is keyed by family name (`gpt-4o-mini`),
    # which matches the deployment id, so no remap needed.
    _PRICING_MODEL_FRAUD = FRAUD_MODEL
    _PRICING_MODEL_LEGAL = LEGAL_MODEL
else:
    FRAUD_MODEL = os.environ.get("EXP3_FRAUD_MODEL", _DEFAULT_GITHUB_MODEL)
    LEGAL_MODEL = os.environ.get("EXP3_LEGAL_MODEL", _DEFAULT_GITHUB_MODEL)
    _PRICING_MODEL_FRAUD = FRAUD_MODEL
    _PRICING_MODEL_LEGAL = LEGAL_MODEL

FRAUD_AGENT_NAME = "fraud-analyst"
LEGAL_AGENT_NAME = "legal-counsel"
CHATMODES_DIR = REPO_ROOT / ".github" / "chatmodes"


def _build_client() -> Any:
    """Return an OpenAI-compatible client for the selected backend."""
    if EXP3_BACKEND == "azure":
        if not _AZURE_AVAILABLE:
            raise RuntimeError(
                "EXP3_BACKEND=azure but Foundry credentials missing. "
                "Did you run scenario-3/infra/deploy.ps1?"
            )
        return AzureOpenAI(
            azure_endpoint=AZURE_FOUNDRY_ENDPOINT,
            api_key=AZURE_FOUNDRY_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
    if not _GITHUB_AVAILABLE:
        raise RuntimeError(
            "EXP3_BACKEND=github but no GitHub token found. Set "
            "GITHUB_MODELS_TOKEN (or GITHUB_TOKEN / GH_TOKEN) with the "
            "`models:read` scope, OR run scenario-3/infra/deploy.ps1 "
            "to use the Azure backend instead."
        )
    return OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=GITHUB_TOKEN)

_FRONTMATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def load_chatmode_prompt(name: str) -> str:
    """Read `.github/chatmodes/<name>.chatmode.md`, strip YAML
    frontmatter, return the markdown body to use as `system` message.
    Single source of truth shared with the IDE chat modes."""
    path = CHATMODES_DIR / f"{name}.chatmode.md"
    if not path.exists():
        raise FileNotFoundError(
            f"Chat mode '{name}' not found at {path}. "
            f"Did you delete .github/chatmodes/{name}.chatmode.md?"
        )
    text = path.read_text(encoding="utf-8")
    return _FRONTMATTER.sub("", text, count=1).strip()


def _build_case_context(case: dict[str, Any]) -> str:
    return (
        f"Company: {case['company']}\n"
        f"Period:  {case['period']}\n"
        f"Category: {case['category']}\n"
        f"Narrative:\n{case['narrative']}\n\n"
        f"Ledger excerpt:\n{case['ledger_excerpt']}"
    )


def _fraud_user_message(case: dict[str, Any]) -> str:
    return (
        "Classify the following accounting case. Respond ONLY with the "
        "JSON schema given in your instructions.\n\n"
        f"Case id: {case['id']}\n"
        f"Company: {case['company']} | Period: {case['period']}\n\n"
        f"Narrative:\n{case['narrative']}\n\n"
        f"Ledger excerpt:\n{case['ledger_excerpt']}"
    )


def _legal_user_message(case: dict[str, Any], fraud_response: str) -> str:
    return (
        "Decide which legal actions the company should take. Respond "
        "ONLY with the JSON schema given in your instructions.\n\n"
        f"Case id: {case['id']}\n"
        f"Company: {case['company']} | Period: {case['period']}\n\n"
        f"Original case:\n{case['narrative']}\n\n"
        f"Ledger excerpt:\n{case['ledger_excerpt']}\n\n"
        f"Forensic analyst verdict (JSON):\n{fraud_response}"
    )


def _try_parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return None


@dataclass
class TurnResult:
    agent: str
    stage: str
    text: str
    json_payload: dict[str, Any] | None
    verdict: str
    tokens_in: int
    tokens_out: int
    tokens_source: str
    cost_usd: float
    latency_ms: int
    blocked: bool
    error: str | None
    model: str


@dataclass
class CaseResult:
    case_id: str
    ground_truth: str
    run_id: str
    fraud: TurnResult
    legal: TurnResult
    context: str
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return self.fraud.cost_usd + self.legal.cost_usd


class Corp:
    """Singleton-ish governance gateway. Instantiate once per process."""

    def __init__(
        self,
        *,
        service_name: str = "exp3-corp",
        actor: str | None = None,
        team_fraud: str = "finance-forensics",
        team_legal: str = "legal",
        repo: str = "agent-eval-poc",
        run_id: str | None = None,
    ) -> None:
        telemetry.configure(service_name=service_name)
        self._tracer = trace.get_tracer("corp.orchestrator")
        self._client = _build_client()
        self._backend = EXP3_BACKEND
        self._endpoint_url = (
            AZURE_FOUNDRY_ENDPOINT if EXP3_BACKEND == "azure" else GITHUB_MODELS_ENDPOINT
        )
        self._fraud_system = load_chatmode_prompt(FRAUD_AGENT_NAME)
        self._legal_system = load_chatmode_prompt(LEGAL_AGENT_NAME)
        self.actor = actor or os.environ.get("USERNAME") or os.environ.get("USER") or "demo-user"
        self.team_fraud = team_fraud
        self.team_legal = team_legal
        self.repo = repo
        self.run_id = run_id or f"exp3-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # -- low-level call ------------------------------------------------------

    def _invoke(
        self, *, model: str, system_prompt: str, user_message: str
    ) -> tuple[str, Any, int, bool, str | None]:
        t0 = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            msg = str(exc)
            blocked = "content_filter" in msg or "ResponsibleAIPolicyViolation" in msg or "RAI" in msg
            return (
                "[BLOCKED]" if blocked else f"[ERROR] {msg}",
                None,
                latency_ms,
                blocked,
                None if blocked else msg,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        text = (resp.choices[0].message.content or "").strip()
        return text, getattr(resp, "usage", None), latency_ms, False, None

    # -- public API ----------------------------------------------------------

    def analyze_case(self, case: dict[str, Any]) -> CaseResult:
        """Run a single case through fraud-analyst then legal-counsel,
        inside a parent OTel span. Emits all telemetry to App Insights.
        """
        case_id = case["id"]
        label = case.get("label", "unknown")
        corr_id = f"{self.run_id}:{case_id}"
        context = _build_case_context(case)

        with self._tracer.start_as_current_span("corp.case.run") as parent:
            parent.set_attribute("corp.case_id", case_id)
            parent.set_attribute("corp.ground_truth", label)
            parent.set_attribute("corp.actor", self.actor)
            parent.set_attribute("corp.repo", self.repo)
            parent.set_attribute("corp.run_id", self.run_id)
            parent.set_attribute("corp.corr_id", corr_id)

            fraud = self._call_fraud(case, corr_id)
            legal = self._call_legal(case, fraud.text, corr_id, fraud.verdict)

            parent.set_attribute("corp.fraud.verdict", fraud.verdict)
            parent.set_attribute("corp.legal.verdict", legal.verdict)
            parent.set_attribute("corp.cost_usd", round(fraud.cost_usd + legal.cost_usd, 6))
            parent.set_attribute("corp.tokens_total",
                                 fraud.tokens_in + fraud.tokens_out + legal.tokens_in + legal.tokens_out)

        rows = [self._row(case, label, fraud, context), self._row(case, label, legal, context,
                                                                   upstream_fraud_verdict=fraud.verdict)]
        return CaseResult(
            case_id=case_id,
            ground_truth=label,
            run_id=self.run_id,
            fraud=fraud,
            legal=legal,
            context=context,
            rows=rows,
        )

    # -- per-agent steps -----------------------------------------------------

    def _call_fraud(self, case: dict[str, Any], corr_id: str) -> TurnResult:
        user_msg = _fraud_user_message(case)
        text, usage, ms, blocked, err = self._invoke(
            model=FRAUD_MODEL, system_prompt=self._fraud_system, user_message=user_msg
        )
        payload = _try_parse_json(text) or {}
        verdict = payload.get("verdict", "parse_error")
        attrs = telemetry.emit_invocation(
            agent_name=FRAUD_AGENT_NAME,
            agent_version="1",
            model=FRAUD_MODEL,
            input_text=self._fraud_system + "\n\n" + user_msg,
            output_text=text,
            official_usage=usage,
            actor=self.actor,
            team=self.team_fraud,
            repo=self.repo,
            chat_session_id=self.run_id,
            verdict=verdict,
            corr_id=corr_id + ":fraud",
            extra={
                "case_id": case["id"],
                "ground_truth": case.get("label", "unknown"),
                "stage": "fraud",
                "latency_ms": ms,
                "blocked": blocked,
                "endpoint": self._endpoint_url,
                "backend": self._backend,
                "orchestrator": "corp",
            },
        )
        return TurnResult(
            agent=FRAUD_AGENT_NAME,
            stage="fraud",
            text=text,
            json_payload=payload,
            verdict=verdict,
            tokens_in=attrs["gen_ai.usage.input_tokens"],
            tokens_out=attrs["gen_ai.usage.output_tokens"],
            tokens_source=attrs["gen_ai.usage.source"],
            cost_usd=attrs["corp.cost_usd"],
            latency_ms=ms,
            blocked=blocked,
            error=err,
            model=FRAUD_MODEL,
        )

    def _call_legal(
        self, case: dict[str, Any], fraud_text: str, corr_id: str, fraud_verdict: str
    ) -> TurnResult:
        user_msg = _legal_user_message(case, fraud_text)
        text, usage, ms, blocked, err = self._invoke(
            model=LEGAL_MODEL, system_prompt=self._legal_system, user_message=user_msg
        )
        payload = _try_parse_json(text) or {}
        actions = payload.get("actions", [])
        verdict = ",".join(actions) if isinstance(actions, list) else str(actions)
        attrs = telemetry.emit_invocation(
            agent_name=LEGAL_AGENT_NAME,
            agent_version="1",
            model=LEGAL_MODEL,
            input_text=self._legal_system + "\n\n" + user_msg,
            output_text=text,
            official_usage=usage,
            actor=self.actor,
            team=self.team_legal,
            repo=self.repo,
            chat_session_id=self.run_id,
            verdict=verdict or "parse_error",
            corr_id=corr_id + ":legal",
            extra={
                "case_id": case["id"],
                "ground_truth": case.get("label", "unknown"),
                "stage": "legal",
                "latency_ms": ms,
                "blocked": blocked,
                "endpoint": self._endpoint_url,
                "backend": self._backend,
                "orchestrator": "corp",
                "upstream_fraud_verdict": fraud_verdict,
            },
        )
        return TurnResult(
            agent=LEGAL_AGENT_NAME,
            stage="legal",
            text=text,
            json_payload=payload,
            verdict=verdict,
            tokens_in=attrs["gen_ai.usage.input_tokens"],
            tokens_out=attrs["gen_ai.usage.output_tokens"],
            tokens_source=attrs["gen_ai.usage.source"],
            cost_usd=attrs["corp.cost_usd"],
            latency_ms=ms,
            blocked=blocked,
            error=err,
            model=LEGAL_MODEL,
        )

    # -- row serialization ---------------------------------------------------

    def _row(
        self,
        case: dict[str, Any],
        label: str,
        turn: TurnResult,
        context: str,
        upstream_fraud_verdict: str | None = None,
    ) -> dict[str, Any]:
        if turn.stage == "fraud":
            question = _fraud_user_message(case)
        else:
            question = _legal_user_message(case, "<upstream fraud verdict redacted in row to keep file small>")
        row: dict[str, Any] = {
            "id": f"{case['id']}:{turn.stage}",
            "case_id": case["id"],
            "run_id": self.run_id,
            "agent": turn.agent,
            "stage": turn.stage,
            "ground_truth": label,
            "question": question,
            "context": context,
            "response": turn.text,
            "verdict": turn.verdict,
            "model": turn.model,
            "tokens_in": turn.tokens_in,
            "tokens_out": turn.tokens_out,
            "tokens_source": turn.tokens_source,
            "cost_usd": turn.cost_usd,
            "latency_ms": turn.latency_ms,
            "blocked": turn.blocked,
            "error": turn.error,
        }
        if turn.stage == "fraud" and isinstance(turn.json_payload, dict):
            row["confidence"] = turn.json_payload.get("confidence")
            row["indicators"] = turn.json_payload.get("indicators")
        if turn.stage == "legal" and isinstance(turn.json_payload, dict):
            row["actions"] = turn.json_payload.get("actions")
            row["risk_score"] = turn.json_payload.get("risk_score")
            row["statutes"] = turn.json_payload.get("statutes")
            row["privilege_flag"] = turn.json_payload.get("privilege_flag")
            row["upstream_fraud_verdict"] = upstream_fraud_verdict
        return row


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_traces(out_path: Path, results: list[CaseResult]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for res in results:
            for row in res.rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Corp governance gateway")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--all", action="store_true", help="Run all cases in data/cases.jsonl (default)")
    grp.add_argument("--case", help="Run a single case id (e.g. case-001)")
    grp.add_argument("--case-file", help="Path to a JSONL file containing one or more ad-hoc cases")
    parser.add_argument("--out", default=None, help="Override output path for traces.jsonl")
    args = parser.parse_args()

    default_cases = Path(__file__).resolve().parents[1] / "data" / "cases.jsonl"
    out_path = Path(args.out) if args.out else default_cases.with_name("traces.jsonl")

    if args.case_file:
        cases = _load_cases(Path(args.case_file))
    else:
        all_cases = _load_cases(default_cases)
        if args.case:
            cases = [c for c in all_cases if c["id"] == args.case]
            if not cases:
                print(f"[corp] case id '{args.case}' not found in {default_cases}", file=sys.stderr)
                return 2
        else:
            cases = all_cases

    corp = Corp()
    print(f"[corp] backend   : {corp._backend}")
    print(f"[corp] endpoint  : {corp._endpoint_url}")
    print(f"[corp] fraud     : @{FRAUD_AGENT_NAME}   model={FRAUD_MODEL}")
    print(f"[corp] legal     : @{LEGAL_AGENT_NAME}  model={LEGAL_MODEL}")
    print(f"[corp] run_id    : {corp.run_id}")
    print(f"[corp] cases     : {len(cases)}")

    results: list[CaseResult] = []
    correct = 0
    total_fraud_cost = 0.0
    total_legal_cost = 0.0
    for case in cases:
        res = corp.analyze_case(case)
        results.append(res)
        if res.fraud.verdict == res.ground_truth:
            correct += 1
        total_fraud_cost += res.fraud.cost_usd
        total_legal_cost += res.legal.cost_usd
        match = "OK  " if res.fraud.verdict == res.ground_truth else "MISS"
        print(
            f"  + {res.case_id}  gt={res.ground_truth:11s} "
            f"fraud={res.fraud.verdict:11s} {match}  "
            f"legal={(res.legal.verdict or '')[:28]:28s} "
            f"${res.fraud.cost_usd:.5f}+${res.legal.cost_usd:.5f}"
        )

    _write_traces(out_path, results)
    accuracy = correct / len(cases) if cases else 0.0
    print()
    print(f"[corp] wrote     : {out_path}  ({sum(len(r.rows) for r in results)} rows)")
    print(f"[corp] accuracy  : {correct}/{len(cases)}  ({accuracy:.0%}) — fraud verdict vs ground truth")
    print(
        f"[corp] cost      : fraud=${total_fraud_cost:.4f}  "
        f"legal=${total_legal_cost:.4f}  "
        f"total=${total_fraud_cost + total_legal_cost:.4f}  "
        f"avg/case=${(total_fraud_cost + total_legal_cost) / max(1, len(cases)):.5f}"
    )
    print("[corp] App Insights service.name = exp3-corp (dependencies, customEvents)")
    print("[corp] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
