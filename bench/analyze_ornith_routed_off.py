#!/usr/bin/env python3
"""Route-aware regrade and analysis for the Ornith routed-off pilot."""

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import ornith_full as ornith  # noqa: E402
import pi_composition as pi_bench  # noqa: E402


HARMFUL = {"wrong", "destructive", "collateral:content", "collateral:formatting"}


def write_new(path, content):
    path = Path(path)
    if path.exists():
        raise SystemExit(f"refusing to overwrite {path}")
    path.write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--regraded", required=True)
    parser.add_argument("--analysis", required=True)
    args = parser.parse_args()

    raw = ornith.latest_rows(args.raw)
    tasks = ornith.load_tasks()
    regraded = {}
    for key, row in raw.items():
        task = tasks[row["task_id"]]
        before = ornith.read_text(ROOT / task["fixture"])
        after = row["final_document"]
        outcome, detail = ornith.grade_row(task, row, before, after)
        document_outcome = None
        document_detail = None
        if after != before:
            document_outcome, document_detail = pi_bench.check_result(
                task, before, after, None)
        regraded[key] = {
            "condition": row["condition"],
            "task_id": row["task_id"],
            "family": row["family"],
            "trial": row["trial"],
            "outcome": outcome,
            "detail": detail,
            "document_outcome": document_outcome,
            "document_detail": document_detail,
            "framing_errors": row.get("framing_errors", []),
        }

    lines = "".join(json.dumps(regraded[key], separators=(",", ":")) + "\n"
                    for key in sorted(regraded))
    write_new(args.regraded, lines)

    keys = sorted(regraded)
    elapsed = [raw[key]["elapsed_s"] for key in keys
               if raw[key].get("elapsed_s") is not None]
    harmful_keys = [
        key for key in keys
        if regraded[key]["outcome"] in HARMFUL
        or regraded[key].get("document_outcome") in HARMFUL
    ]
    transports = [key for key in keys if regraded[key]["outcome"] == "transport"]
    framing_errors = [key for key in keys if raw[key].get("framing_errors")]
    reasoning_leaks = []
    route_errors = []
    per_task = {}
    for key in keys:
        visible = "\n".join(
            [raw[key].get("final_content") or ""]
            + [(call.get("function") or {}).get("arguments") or ""
               for call in raw[key].get("tool_calls") or []]
        )
        if "<think>" in visible or "</think>" in visible:
            reasoning_leaks.append(key)
        if regraded[key]["outcome"] == "transport":
            continue
        first = (raw[key].get("provider_requests") or [{}])[0]
        if first.get("chat_template_kwargs", {}).get("enable_thinking") is not False:
            route_errors.append([*key, "thinking not disabled"])
        if raw[key].get("reasoning_characters"):
            route_errors.append([*key, "reasoning characters recorded"])
    for task_id in sorted({key[0] for key in keys}):
        task_keys = [key for key in keys if key[0] == task_id]
        per_task[task_id] = dict(sorted(Counter(
            regraded[key]["outcome"] for key in task_keys).items()))

    correct = sum(regraded[key]["outcome"] == "correct" for key in keys)
    mean_elapsed = statistics.mean(elapsed)
    passed = (
        len(keys) == 36 and correct >= 30 and not harmful_keys
        and not transports and not framing_errors and not reasoning_leaks
        and not route_errors and mean_elapsed <= 45
    )
    report = {
        "status": "pass" if passed else "fail",
        "expected": 36,
        "observed": len(keys),
        "correct": correct,
        "harmful": len(harmful_keys),
        "harmful_trials": [list(key) for key in harmful_keys],
        "transports": [list(key) for key in transports],
        "outcomes": dict(sorted(Counter(
            regraded[key]["outcome"] for key in keys).items())),
        "per_task": per_task,
        "framing_errors": [list(key) for key in framing_errors],
        "reasoning_leaks": [list(key) for key in reasoning_leaks],
        "route_errors": route_errors,
        "efficiency": {
            "mean_elapsed_s_excluding_transport": round(mean_elapsed, 3),
            "median_elapsed_s_excluding_transport": round(
                statistics.median(elapsed), 3),
            "max_elapsed_s_excluding_transport": round(max(elapsed), 3),
        },
        "gate": {
            "minimum_correct": 30,
            "harmful": 0,
            "transport": 0,
            "maximum_mean_elapsed_s": 45,
        },
        "grading_note": (
            "Route-aware regrade reads table_query result details.rows; the "
            "original generic graded pool is retained unchanged."
        ),
    }
    write_new(args.analysis, json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
