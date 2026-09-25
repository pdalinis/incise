#!/usr/bin/env python3
"""Summarize the preregistered MiniCPM5 roadmap result pools."""

import argparse
import hashlib
import json
import math
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "bench", "results")

PRIMARY = {
    "tables": {
        "add-row-aligned-short",
        "add-row-aligned-repad",
        "add-row-ragged",
        "add-row-alignment-markers",
        "update-cell-multi-table",
    },
    "lists": {
        "add-item-tight-dash",
        "add-item-nested-asterisk",
        "add-item-loose",
        "add-item-ordered-renumber",
        "add-item-ordered-all-ones",
        "add-item-paren-delimiter",
        "add-item-mixed-markers",
    },
    "sections": {
        "insert-release-at-top",
        "insert-subsection-last",
        "append-hotfix-note",
        "notes-second-ordinal",
        "append-after-fence",
        "append-atx-line",
        "append-macos-note",
        "insert-nested-ratelimits",
        "insert-troubleshooting",
    },
    "frontmatter": {
        "set-build-jobs",
        "set-build-target",
        "set-dana-role",
        "add-build-cache",
        "clear-title",
        "set-draft-true",
        "release-bump",
        "create-on-absent",
        "fill-empty",
    },
}

READS = {
    "md_tables",
    "table_get",
    "md_lists",
    "list_get",
    "md_outline",
    "frontmatter_get",
}


def read_last(path):
    rows = {}
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def path_for(family, scheme, graded=False):
    suffix = "_graded" if graded else ""
    return os.path.join(
        RESULTS,
        f"minicpm5_roadmap_{family}_{scheme}_20260921{suffix}.jsonl",
    )


def exact_mcnemar(b, c):
    n = b + c
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / (2**n)
    return min(1.0, 2 * tail)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def calls_of(row):
    return [call.get("function", {}) for call in row.get("tool_calls") or []]


def summarize(family, scheme):
    allowed = PRIMARY[family]
    graded_path = path_for(family, scheme, graded=True)
    raw_path = path_for(family, scheme)
    grades = {key: row for key, row in read_last(graded_path).items()
              if key[0] in allowed}
    raw = {key: row for key, row in read_last(raw_path).items()
           if key[0] in allowed}
    if set(grades) != set(raw):
        raise RuntimeError(f"raw/graded key mismatch for {family}/{scheme}")

    outcomes = Counter(row["outcome"] for row in grades.values())
    trials = len(grades)
    silent = sum(
        count for outcome, count in outcomes.items()
        if outcome == "wrong" or outcome == "destructive"
        or outcome.startswith("collateral:")
    )
    edit_counts = []
    read_trials = 0
    for row in raw.values():
        names = [fn.get("name") for fn in calls_of(row)]
        edit_counts.append(sum(name not in READS for name in names))
        read_trials += int(any(name in READS for name in names))
    return {
        "trials": trials,
        "outcomes": dict(sorted(outcomes.items())),
        "correct": outcomes["correct"],
        "silent_corruption": silent,
        "data_loss": outcomes["destructive"],
        "read_trials": read_trials,
        "multi_mutation_trials": sum(count > 1 for count in edit_counts),
        "mean_tool_calls": round(
            sum(len(calls_of(row)) for row in raw.values()) / trials, 2),
        "mean_completion_tokens": round(
            sum(row.get("completion_tokens") or 0 for row in raw.values()) / trials,
            2,
        ),
        "mean_elapsed_s": round(
            sum(row.get("elapsed_s") or 0 for row in raw.values()) / trials, 2),
    }


def paired(family):
    control = read_last(path_for(family, "compose_5", graded=True))
    treatment = read_last(path_for(family, "safe_small", graded=True))
    keys = {(task, trial) for task in PRIMARY[family] for trial in range(3)}
    missing = keys - set(control) | keys - set(treatment)
    if missing:
        raise RuntimeError(f"missing paired rows for {family}: {sorted(missing)}")
    b = sum(control[key]["outcome"] == "correct"
            and treatment[key]["outcome"] != "correct" for key in keys)
    c = sum(control[key]["outcome"] != "correct"
            and treatment[key]["outcome"] == "correct" for key in keys)
    return {"control_only_correct": b, "treatment_only_correct": c,
            "discordant": b + c, "exact_mcnemar_p": exact_mcnemar(b, c)}


def singleton_confirmation():
    stem = "minicpm5_roadmap_table_20260921_v3"
    raw = read_last(os.path.join(RESULTS, stem + ".jsonl"))
    grades = read_last(os.path.join(RESULTS, stem + "_graded.jsonl"))
    keys = []
    for key, row in raw.items():
        for fn in calls_of(row):
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                continue
            values = args.get("values")
            if (args.get("action") == "add-row" and isinstance(values, list)
                    and len(values) == 1 and isinstance(values[0], dict)):
                keys.append(key)
                break
    return {
        "trials": len(raw),
        "correct": sum(row["outcome"] == "correct" for row in grades.values()),
        "singleton_object_calls": len(keys),
        "singleton_object_calls_correct": sum(
            grades[key]["outcome"] == "correct" for key in keys),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write the JSON report to this path")
    args = parser.parse_args()
    families = {}
    pooled_control = Counter()
    pooled_treatment = Counter()
    pooled_pair = Counter()
    for family in PRIMARY:
        control = summarize(family, "compose_5")
        treatment = summarize(family, "safe_small")
        comparison = paired(family)
        families[family] = {
            "control": control,
            "treatment": treatment,
            "paired": comparison,
        }
        pooled_control.update(control["outcomes"])
        pooled_treatment.update(treatment["outcomes"])
        pooled_pair["control_only_correct"] += comparison["control_only_correct"]
        pooled_pair["treatment_only_correct"] += comparison["treatment_only_correct"]

    b = pooled_pair["control_only_correct"]
    c = pooled_pair["treatment_only_correct"]
    files = []
    for name in sorted(os.listdir(RESULTS)):
        if name.startswith("minicpm5_roadmap_"):
            path = os.path.join(RESULTS, name)
            if args.out and os.path.abspath(path) == os.path.abspath(args.out):
                continue
            files.append({"path": os.path.relpath(path, ROOT), "sha256": sha256(path)})
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "minicpm5-2b-q8",
        "preregistration_commit": "8b25162",
        "trials_per_primary_task": 3,
        "primary_pairs": sum(len(tasks) for tasks in PRIMARY.values()) * 3,
        "singleton_confirmation": singleton_confirmation(),
        "families": families,
        "pooled": {
            "control_outcomes": dict(sorted(pooled_control.items())),
            "treatment_outcomes": dict(sorted(pooled_treatment.items())),
            "control_correct": pooled_control["correct"],
            "treatment_correct": pooled_treatment["correct"],
            "control_only_correct": b,
            "treatment_only_correct": c,
            "exact_mcnemar_p": exact_mcnemar(b, c),
        },
        "artifacts": files,
        "inputs": {
            "executor": {
                "path": "target/debug/incise",
                "sha256": sha256(os.path.join(ROOT, "target", "debug", "incise")),
            },
            "tasks": {
                name: sha256(os.path.join(ROOT, "bench", "tasks", f"{name}.json"))
                for name in PRIMARY
            },
            "safe_small_schema_sha256": hashlib.sha256(subprocess.run(
                [os.path.join(ROOT, "target", "debug", "incise"),
                 "schema", "--profile", "safe-small"],
                check=True, capture_output=True).stdout).hexdigest(),
        },
        "invalid_pools": {
            "minicpm5_roadmap_table_20260921.jsonl":
                "localhost was unavailable inside the initial sandbox",
            "minicpm5_roadmap_table_20260921_v2.jsonl":
                "relative --binary path resolved from Arm C's temporary cwd",
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
