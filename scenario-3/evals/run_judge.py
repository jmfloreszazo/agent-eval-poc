"""
Experiment 3 — run_judge.py
============================

Deterministic, code-based evaluator that answers the single question
that matters for the demo:  **"are these agents any good, or are they
making it up?"**

For each `data/traces.jsonl` row:

* `fraud_correct`         — does the fraud-analyst verdict match the
                            ground-truth label baked into the case?
* `fraud_json_valid`      — did it return parseable JSON with the
                            required keys?
* `legal_consistent`      — does the legal-counsel recommendation make
                            sense given the upstream fraud verdict?
                            (e.g. `clean` -> `no_action`;
                            `fraud` -> at least `internal_review`)
* `legal_json_valid`      — did it return parseable JSON with the
                            required keys?
* `cited_known_statute`   — for `fraud`/`suspicious` cases, did legal
                            cite at least one statute from the allow-list?
* `verdict_severity`      — numeric 0..3 mapping for confusion-matrix.

Outputs:
  * `data/judge.jsonl`    — per-row scoring
  * `data/judge_summary.json` — aggregates (accuracy, parse rate,
                                 consistency rate, confusion matrix)
  * prints summary to stdout
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


FRAUD_VERDICTS = {"fraud", "clean", "suspicious"}
LEGAL_ACTIONS = {
    "no_action",
    "internal_review",
    "report_to_authorities",
    "suspend_employees",
    "file_lawsuit",
    "external_audit",
    "self_disclose_to_regulator",
}
STATUTE_ALLOWLIST = [
    "código penal",
    "codigo penal",
    "art. 252",
    "art. 253",
    "art. 290",
    "art. 305",
    "aml",
    "directive 2024/1640",
    "ifrs",
    "ias 8",
    "ias 10",
    "ias 36",
    "sox",
    "section 302",
    "404",
]


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _legal_consistency(fraud_verdict: str, actions: list[str]) -> tuple[bool, str]:
    actions = actions or []
    actions_lc = {a.lower() for a in actions}
    if fraud_verdict == "clean":
        ok = actions_lc == {"no_action"} or actions_lc.issubset({"no_action", "internal_review"})
        return ok, "clean -> no_action / internal_review only"
    if fraud_verdict == "suspicious":
        ok = "internal_review" in actions_lc
        return ok, "suspicious -> internal_review required"
    if fraud_verdict == "fraud":
        ok = "internal_review" in actions_lc and len(actions_lc - {"no_action"}) >= 1
        return ok, "fraud -> at least internal_review + some escalation"
    return False, f"unknown upstream verdict '{fraud_verdict}'"


def _cited_known_statute(statutes: Any) -> bool:
    if not statutes:
        return False
    if isinstance(statutes, str):
        text = statutes.lower()
    else:
        try:
            text = " ".join(str(s) for s in statutes).lower()
        except TypeError:
            return False
    return any(tag in text for tag in STATUTE_ALLOWLIST)


def main() -> int:
    traces_path = Path(__file__).resolve().parents[1] / "data" / "traces.jsonl"
    out_jsonl = traces_path.with_name("judge.jsonl")
    out_summary = traces_path.with_name("judge_summary.json")

    if not traces_path.exists():
        print(f"[judge] {traces_path} not found. Run src/pipeline.py first.", file=sys.stderr)
        return 2

    rows = _load_rows(traces_path)
    fraud_rows = [r for r in rows if r.get("stage") == "fraud"]
    legal_rows = [r for r in rows if r.get("stage") == "legal"]
    legal_by_case = {r["case_id"]: r for r in legal_rows}

    out_rows: list[dict[str, Any]] = []
    fraud_correct = 0
    fraud_parsed = 0
    legal_parsed = 0
    legal_consistent = 0
    legal_cited = 0
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    fraud_cost_total = 0.0
    legal_cost_total = 0.0

    for fr in fraud_rows:
        case_id = fr["case_id"]
        gt = fr["ground_truth"]
        verdict = fr.get("verdict") or "parse_error"
        json_valid = verdict in FRAUD_VERDICTS
        correct = verdict == gt

        fraud_parsed += int(json_valid)
        fraud_correct += int(correct)
        confusion[gt][verdict] += 1
        fraud_cost_total += float(fr.get("cost_usd") or 0.0)

        lr = legal_by_case.get(case_id, {})
        actions = lr.get("actions") or []
        legal_valid = bool(actions) and all(
            (a.lower() if isinstance(a, str) else "") in LEGAL_ACTIONS for a in actions
        )
        consistent, consistency_rule = _legal_consistency(verdict, actions)
        cited = _cited_known_statute(lr.get("statutes"))

        legal_parsed += int(legal_valid)
        legal_consistent += int(consistent and legal_valid)
        if gt in {"fraud", "suspicious"}:
            legal_cited += int(cited)
        legal_cost_total += float(lr.get("cost_usd") or 0.0)

        out_rows.append({
            "case_id": case_id,
            "ground_truth": gt,
            "fraud_verdict": verdict,
            "fraud_correct": correct,
            "fraud_json_valid": json_valid,
            "fraud_confidence": fr.get("confidence"),
            "fraud_cost_usd": fr.get("cost_usd"),
            "legal_actions": actions,
            "legal_json_valid": legal_valid,
            "legal_consistent": consistent and legal_valid,
            "legal_consistency_rule": consistency_rule,
            "legal_cited_statute": cited,
            "legal_risk_score": lr.get("risk_score"),
            "legal_cost_usd": lr.get("cost_usd"),
            "total_cost_usd": (fr.get("cost_usd") or 0.0) + (lr.get("cost_usd") or 0.0),
        })

    n = len(fraud_rows) or 1
    cases_at_risk = sum(1 for r in fraud_rows if r["ground_truth"] in {"fraud", "suspicious"}) or 1
    summary = {
        "total_cases": len(fraud_rows),
        "fraud_accuracy": round(fraud_correct / n, 3),
        "fraud_json_parse_rate": round(fraud_parsed / n, 3),
        "legal_json_parse_rate": round(legal_parsed / n, 3),
        "legal_consistency_rate": round(legal_consistent / n, 3),
        "legal_statute_citation_rate": round(legal_cited / cases_at_risk, 3),
        "confusion_matrix": {gt: dict(c) for gt, c in confusion.items()},
        "cost_usd": {
            "fraud": round(fraud_cost_total, 4),
            "legal": round(legal_cost_total, 4),
            "total": round(fraud_cost_total + legal_cost_total, 4),
            "avg_per_case": round((fraud_cost_total + legal_cost_total) / n, 5),
        },
    }

    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    out_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[judge] wrote      : {out_jsonl}")
    print(f"[judge] wrote      : {out_summary}")
    print()
    print(f"[judge] fraud accuracy            : {summary['fraud_accuracy']:.0%} "
          f"({fraud_correct}/{summary['total_cases']})")
    print(f"[judge] fraud JSON parse rate     : {summary['fraud_json_parse_rate']:.0%}")
    print(f"[judge] legal JSON parse rate     : {summary['legal_json_parse_rate']:.0%}")
    print(f"[judge] legal consistency rate    : {summary['legal_consistency_rate']:.0%}  "
          f"(legal recommendation matches fraud verdict)")
    print(f"[judge] legal statute citation    : {summary['legal_statute_citation_rate']:.0%}  "
          f"(of {cases_at_risk} non-clean cases)")
    print(f"[judge] cost                      : fraud=${summary['cost_usd']['fraud']:.4f}  "
          f"legal=${summary['cost_usd']['legal']:.4f}  total=${summary['cost_usd']['total']:.4f}  "
          f"avg/case=${summary['cost_usd']['avg_per_case']:.5f}")
    print()
    print("[judge] confusion matrix (rows = ground_truth, columns = fraud verdict):")
    all_verdicts = sorted({v for c in confusion.values() for v in c} | FRAUD_VERDICTS)
    header = "                  " + " ".join(f"{v:>11s}" for v in all_verdicts)
    print(header)
    for gt in sorted(confusion):
        row = " ".join(f"{confusion[gt].get(v, 0):>11d}" for v in all_verdicts)
        print(f"  {gt:14s}  {row}")
    print()
    print("[judge] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
