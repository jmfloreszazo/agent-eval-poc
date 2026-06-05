"""
Publish the trajectory as a Phoenix Dataset + Experiment.

While ``phoenix_publisher.py`` attaches scores to live spans (good for
observing real traffic), this script does the *other* Phoenix workflow:
turn the 4 fixture cases into a versioned **Dataset** and a comparable
**Experiment**, so you can diff runs over time in the Phoenix UI
(http://127.0.0.1:6006/datasets and /experiments).

Run:
    .\\.venv\\Scripts\\python.exe evals/phoenix_experiment.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Phoenix prints emojis to stdout; on Windows the default cp1252 codec dies.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# Allow `evals/` modules to import each other when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

# evals/ -> scenario-1/ -> repo root
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from phoenix.client import Client  # noqa: E402

from trajectory_loader import load_cases  # noqa: E402


PHOENIX_ENDPOINT = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006")
DATASET_NAME = os.getenv("PHOENIX_DATASET", "azure-cost-agent-fixture")
TRAJECTORY_PATH = os.getenv(
    "TRAJECTORY_PATH",
    str(Path(__file__).resolve().parents[1] / "data" / "trajectory.json"),
)


# ---------------------------------------------------------------------------
# 1. Load the trajectory and shape it as Phoenix dataset Examples.
# ---------------------------------------------------------------------------
def _build_examples(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    examples: list[dict[str, Any]] = []
    for c in data["cases"]:
        examples.append({
            # input: what the user asked
            "input": {"question": c["input"]},
            # output: the ground-truth contract (what we expect / actually got)
            "output": {
                "actual_output": c["actual_output"],
                "expected_tools": c["expected_tools"],
            },
            # metadata: everything else the task callback may need
            "metadata": {
                "case_id": c["id"],
                "tools_called": c["tools_called"],
                "tokens_total": c.get("tokens", {}).get("total", 0),
                "token_budget": c.get("token_budget", 10_000),
                "trace_id": c.get("trace_id"),
                "span_id": c.get("span_id"),
            },
        })
    return examples


# ---------------------------------------------------------------------------
# 2. The "task" — Phoenix calls this once per dataset Example.
# Since the agent already ran and we just want to grade the stored answer,
# the task is a pure lookup over the example's metadata. This makes the
# Experiment fully deterministic and reproducible.
# ---------------------------------------------------------------------------
def replay_task(example) -> dict[str, Any]:
    meta = example.metadata or {}
    output = example.output or {}
    return {
        "actual_output": output.get("actual_output", ""),
        "tools_called": meta.get("tools_called", []),
        "tokens_total": meta.get("tokens_total", 0),
        "token_budget": meta.get("token_budget", 10_000),
    }


# ---------------------------------------------------------------------------
# 3. Evaluators — return (score, label, explanation) tuples.
#    Two deterministic ones here; LLM-as-judge ones are kept in pytest so we
#    do not double-spend on judge calls. (You can wire them here just as
#    easily if you prefer the Phoenix UI as the source of truth.)
# ---------------------------------------------------------------------------
def tool_correctness(output, expected) -> tuple[float, str, str]:
    called = {t["name"] for t in (output or {}).get("tools_called", [])}
    wanted = set((expected or {}).get("expected_tools", []))
    missing = wanted - called
    score = 1.0 if not missing else max(0.0, 1.0 - len(missing) / max(1, len(wanted)))
    label = "pass" if not missing else "fail"
    reason = (
        "all expected tools were called"
        if not missing
        else f"missing tools: {sorted(missing)}"
    )
    return score, label, reason


def token_budget(output) -> tuple[float, str, str]:
    out = output or {}
    used = int(out.get("tokens_total", 0))
    cap = int(out.get("token_budget", 10_000))
    ratio = used / cap if cap else 1.0
    passed = used <= cap
    score = 1.0 if passed else max(0.0, 2.0 - ratio)
    label = "pass" if passed else "fail"
    reason = f"{used} tokens / {cap} budget ({ratio:.0%})"
    return score, label, reason


# ---------------------------------------------------------------------------
# 4. Wire it all together.
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"[experiment] trajectory : {TRAJECTORY_PATH}")
    print(f"[experiment] phoenix    : {PHOENIX_ENDPOINT}")
    print(f"[experiment] dataset    : {DATASET_NAME}")

    examples = _build_examples(TRAJECTORY_PATH)
    if not examples:
        print("[experiment] no cases in trajectory; nothing to do")
        return 1

    client = Client(base_url=PHOENIX_ENDPOINT)

    dataset = client.datasets.create_dataset(
        name=DATASET_NAME,
        inputs=[e["input"] for e in examples],
        outputs=[e["output"] for e in examples],
        metadata=[e["metadata"] for e in examples],
        dataset_description=(
            "Azure FinOps agent fixture: 4 canonical cases (cost / inventory "
            "/ savings / tags) replayed against the latest stored trajectory."
        ),
    )
    print(f"[experiment] dataset created: id={dataset.id} examples={len(examples)}")
    # Sanity: load_cases also works against the same file — keep harness path warm.
    _ = load_cases(TRAJECTORY_PATH)

    experiment = client.experiments.run_experiment(
        dataset=dataset,
        task=replay_task,
        evaluators=[tool_correctness, token_budget],
        experiment_name=f"replay-{Path(TRAJECTORY_PATH).stem}",
        experiment_description=(
            "Deterministic replay of the stored .NET trajectory, graded with "
            "the two zero-cost evaluators. LLM-as-judge metrics stay in pytest."
        ),
    )
    exp_id = (
        experiment["experiment_id"]
        if isinstance(experiment, dict)
        else getattr(experiment, "experiment_id", None)
    )
    ds_id = (
        experiment["dataset_id"]
        if isinstance(experiment, dict)
        else getattr(experiment, "dataset_id", None)
    )
    url = client.experiments.get_experiment_url(
        dataset_id=ds_id, experiment_id=exp_id
    )
    print(f"[experiment] OK -> {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
