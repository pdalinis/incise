#!/usr/bin/env python3
"""Compare paired Ornith reasoning-on and reasoning-off result pools."""

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics


HARMFUL = {"wrong", "destructive", "collateral:content", "collateral:formatting"}


def latest(path):
    rows = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def is_harmful(row):
    return row["outcome"] in HARMFUL or row.get("document_outcome") in HARMFUL


def metrics(keys, raw, graded):
    elapsed = [raw[key]["elapsed_s"] for key in keys
               if raw[key].get("elapsed_s") is not None]
    return {
        "observed": len(keys),
        "correct": sum(graded[key]["outcome"] == "correct" for key in keys),
        "harmful": sum(is_harmful(graded[key]) for key in keys),
        "outcomes": dict(sorted(Counter(graded[key]["outcome"]
                                         for key in keys).items())),
        "framing_errors": sum(bool(raw[key].get("framing_errors")) for key in keys),
        "reasoning_characters": sum(raw[key].get("reasoning_characters") or 0
                                    for key in keys),
        "mean_elapsed_s": round(statistics.mean(elapsed), 3),
        "median_elapsed_s": round(statistics.median(elapsed), 3),
        "max_elapsed_s": round(max(elapsed), 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--on-raw", required=True)
    parser.add_argument("--on-graded", required=True)
    parser.add_argument("--off-raw", required=True)
    parser.add_argument("--off-graded", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    on_raw, on_graded = latest(args.on_raw), latest(args.on_graded)
    off_raw, off_graded = latest(args.off_raw), latest(args.off_graded)
    keys = sorted(set(off_raw) & set(off_graded))
    missing = sorted(set(keys) - set(on_raw) | set(keys) - set(on_graded))
    if missing:
        raise SystemExit(f"control pool lacks paired keys: {missing}")

    on = metrics(keys, on_raw, on_graded)
    off = metrics(keys, off_raw, off_graded)
    tasks = {}
    for task_id in sorted({key[0] for key in keys}):
        task_keys = [key for key in keys if key[0] == task_id]
        tasks[task_id] = {
            "on": metrics(task_keys, on_raw, on_graded),
            "off": metrics(task_keys, off_raw, off_graded),
        }

    elapsed_reduction = 1 - off["mean_elapsed_s"] / on["mean_elapsed_s"]
    passed = (
        off["framing_errors"] == 0
        and off["observed"] == len(keys)
        and off["harmful"] <= on["harmful"]
        and off["correct"] >= on["correct"] - 1
        and elapsed_reduction >= 0.5
    )
    report = {
        "status": "pass" if passed else "fail",
        "pairs": len(keys),
        "on": on,
        "off": off,
        "delta": {
            "correct": off["correct"] - on["correct"],
            "harmful": off["harmful"] - on["harmful"],
            "mean_elapsed_reduction": round(elapsed_reduction, 6),
        },
        "tasks": tasks,
        "decision_rule": {
            "maximum_correct_loss": 1,
            "maximum_harmful_increase": 0,
            "minimum_mean_elapsed_reduction": 0.5,
            "maximum_framing_errors": 0,
        },
    }
    path = Path(args.out)
    if path.exists():
        raise SystemExit(f"refusing to overwrite {path}")
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
