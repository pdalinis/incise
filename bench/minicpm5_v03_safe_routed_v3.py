#!/usr/bin/env python3
"""Run and analyse the preregistered safe-routed v3 completion gate."""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import minicpm5_v03_safe_routed_v2 as v2  # noqa: E402
import ornith_full as composition  # noqa: E402
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


V3_TASKS = {
    "delete-row-aligned", "update-cell-multi-table", "append-hotfix-note",
    "delete-install-macos", "get-ordinal-table",
}
AFFECTED = v2.AFFECTED | V3_TASKS
NEW_TOOLS = [
    "table_delete_row_target", "table_update_cell_target", "section_delete_target",
]
ALL_TOOLS = v2.ALL_TOOLS + NEW_TOOLS
STANDARD_TOOLS = v2.STANDARD_TOOLS
HARMFUL = v2.HARMFUL
PROFILES = {"safe-routed-v3": "safe-routed"}
MODELS = v2.MODELS
DEFAULT_BINARY = ROOT / "target" / "debug" / "incise"
DEFAULT_SANDBOX = Path("/private/tmp/incise-safe-routed-v3-20260925")


def spec(tool, route, resolved):
    return {"tool": tool, "route": route, "supplied": {}, "resolved": resolved}


def v3_specs():
    specs = v2.v2_specs()
    specs.update({
        "delete-row-aligned": spec(
            "table_delete_row_target", "table-delete-row-target",
            {
                "table": {"heading": "Aligned table > Components", "ordinal": 0},
                "where": {"Component": "gadget"},
            },
        ),
        "update-cell-multi-table": spec(
            "table_update_cell_target", "table-update-cell-target",
            {
                "table": {
                    "heading": "Multiple tables per section > Environments",
                    "ordinal": 1,
                },
                "where": {"Host": "stage-1"}, "column": "Size", "value": "t3.l",
            },
        ),
        "append-hotfix-note": spec(
            "section_append_target", "section-append",
            {
                "section": "Changelog > [1.4.2] - 2026-08-14",
                "text": "This release is a hotfix.",
            },
        ),
        "delete-install-macos": spec(
            "section_delete_target", "section-delete-target",
            {
                "section": "Deep heading nesting > Install > macOS",
                "subtree": True,
            },
        ),
        "get-ordinal-table": spec(
            "table_query", "table-query",
            {
                "table": {
                    "heading": "Multiple tables per section > Environments",
                    "ordinal": 1,
                },
            },
        ),
    })
    return specs


def configure(args):
    global ACTIVE_MODEL
    ACTIVE_MODEL = args.model
    config = MODELS[args.model]
    composition.MODEL = config["definition"]
    composition.PROFILES = PROFILES
    composition.ALL_TOOLS = ALL_TOOLS
    composition.ROUTED_TABLE_TASKS = composition.ROUTED_TABLE_TASKS | {
        "get-ordinal-table",
    }
    composition.validate_framing = validate_framing
    args.thinking = config["thinking"]
    args.max_tokens = config["max_tokens"]
    args.parallel_tool_calls = config["parallel"]
    args.task_id = None if args.scope == "full" else sorted(AFFECTED)


ACTIVE_MODEL = "minicpm"


def validate_framing(row):
    config = MODELS[row.get("evaluation_model", ACTIVE_MODEL)]
    requests = row.get("provider_requests") or []
    if not requests:
        return ["no provider request recorded"]
    expected = {
        "model": config["definition"]["id"],
        "seed": row["seed"], "max_tokens": config["max_tokens"],
        **config["framing"],
    }
    errors = []
    for index, request in enumerate(requests):
        for key, value in expected.items():
            if request.get(key) != value:
                errors.append(
                    f"request {index} {key}: expected {value!r}, got {request.get(key)!r}"
                )
    return errors


def run(args):
    configure(args)
    original = composition.run_one

    def run_one_with_model(run_args, task, trial):
        row, graded = original(run_args, task, trial)
        row["evaluation_model"] = args.model
        graded["evaluation_model"] = args.model
        row["framing_errors"] = validate_framing(row)
        graded["framing_errors"] = row["framing_errors"]
        return row, graded

    composition.run_one = run_one_with_model
    try:
        composition.run(args)
    finally:
        composition.run_one = original


def latest(path):
    return composition.latest_rows(path)


def route_audit(keys, raw, graded, affected_only=False):
    specs = v3_specs()
    errors = []
    checked = 0
    for key in keys:
        if affected_only and key[0] not in AFFECTED:
            continue
        row = raw[key]
        expected = specs.get(key[0])
        first = (row.get("provider_requests") or [{}])[0]
        if expected is None:
            if (first.get("tools") != STANDARD_TOOLS
                    or first.get("active_tools") != STANDARD_TOOLS):
                errors.append([*key, "fallback surface"])
            continue
        checked += 1
        if (first.get("tools") != [expected["tool"]]
                or first.get("active_tools") != [expected["tool"]]
                or first.get("tool_choice") is not None):
            errors.append([*key, "provider surface", first.get("tools"),
                           first.get("active_tools"), first.get("tool_choice")])
        calls = row.get("tool_calls") or []
        if any((call.get("function") or {}).get("name") != expected["tool"]
               for call in calls):
            errors.append([*key, "unexpected tool call"])
        successes = v2.successful_results(row, expected["tool"])
        if len(successes) != 1:
            errors.append([*key, "successful calls", len(successes)])
        if len(successes) > 1:
            errors.append([*key, "multiple successful calls", len(successes)])
        for call, result in successes:
            try:
                supplied = json.loads((call.get("function") or {}).get("arguments") or "{}")
            except json.JSONDecodeError:
                supplied = "invalid-json"
            details = result.get("details") or {}
            expected_changed = expected["tool"] != "table_query"
            if (supplied != expected["supplied"]
                    or details.get("route") != expected["route"]
                    or details.get("resolvedArguments") != expected["resolved"]
                    or bool(details.get("changed")) != expected_changed):
                errors.append([*key, "resolved call", supplied, details, expected])
    return {"checked": checked, "errors": errors}


def harmful_keys(keys, graded):
    return [
        key for key in keys
        if graded[key]["outcome"] in HARMFUL
        or graded[key].get("document_outcome") in HARMFUL
    ]


def counts(keys, graded):
    return dict(sorted(Counter(graded[key]["outcome"] for key in keys).items()))


def analyse_minicpm(args):
    previous_raw, previous_graded = latest(args.previous_raw), latest(args.previous_graded)
    raw, graded = latest(args.out), latest(args.graded)
    keys = sorted(set(previous_raw) & set(previous_graded) & set(raw) & set(graded))
    usable = [key for key in keys if previous_graded[key]["outcome"] != "transport"
              and graded[key]["outcome"] != "transport"]
    previous_correct = {key for key in usable if previous_graded[key]["outcome"] == "correct"}
    correct = {key for key in usable if graded[key]["outcome"] == "correct"}
    regressions = sorted(previous_correct - correct)
    gains = sorted(correct - previous_correct)
    harms = harmful_keys(usable, graded)
    framing = [[*key, *raw[key].get("framing_errors", [])]
               for key in usable if raw[key].get("framing_errors")]
    multiple = [[*key, v2.changed_mutations(raw[key])] for key in usable
                if v2.changed_mutations(raw[key]) > 1]
    leaks = [list(key) for key in usable if v2.reasoning_leak(raw[key])]
    audit = route_audit(usable, raw, graded, affected_only=True)
    target_correct = sum(key[0] in AFFECTED and key in correct for key in usable)
    failures = []
    if len(keys) != 48 or len(usable) != 48:
        failures.append("not all 48 pairs usable")
    if len(correct) != 48:
        failures.append("correctness is not 48/48")
    if target_correct != len(AFFECTED):
        failures.append("affected tasks not 17/17")
    if regressions:
        failures.append("v2-correct task regressed")
    if harms:
        failures.append("harmful outcome")
    if framing:
        failures.append("provider framing error")
    if multiple:
        failures.append("multiple changed mutations")
    if leaks:
        failures.append("reasoning leak")
    if audit["checked"] != len(AFFECTED) or audit["errors"]:
        failures.append("affected route audit error")
    report = {
        "status": "pass" if not failures else "fail",
        "pairs": len(usable),
        "previous_correct": len(previous_correct), "treatment_correct": len(correct),
        "gains": [list(key) for key in gains], "regressions": [list(key) for key in regressions],
        "discordant": {
            "previous_only": len(regressions), "treatment_only": len(gains),
            "mcnemar_exact_p": mcnemar_exact(len(regressions), len(gains)),
        },
        "outcomes": counts(usable, graded), "affected_correct": target_correct,
        "harmful": [list(key) for key in harms], "framing_errors": framing,
        "multiple_mutations": multiple, "reasoning_leaks": leaks,
        "route_audit": audit, "gate_failures": failures,
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def analyse_retention(args):
    raw, graded = latest(args.out), latest(args.graded)
    keys = sorted(set(raw) & set(graded))
    usable = [key for key in keys if graded[key]["outcome"] != "transport"]
    correct = sum(graded[key]["outcome"] == "correct" for key in usable)
    harms = harmful_keys(usable, graded)
    framing = [[*key, *raw[key].get("framing_errors", [])]
               for key in usable if raw[key].get("framing_errors")]
    multiple = [[*key, v2.changed_mutations(raw[key])] for key in usable
                if v2.changed_mutations(raw[key]) > 1]
    leaks = [list(key) for key in usable if v2.reasoning_leak(raw[key])]
    audit = route_audit(usable, raw, graded, affected_only=True)
    expected = len(AFFECTED) * args.trials
    failures = []
    if len(keys) != expected or len(usable) != expected or correct != expected:
        failures.append(f"retention is not {expected}/{expected} correct")
    if harms:
        failures.append("harmful outcome")
    if framing:
        failures.append("provider framing error")
    if multiple:
        failures.append("multiple changed mutations")
    if leaks:
        failures.append("reasoning leak")
    if audit["checked"] != expected or audit["errors"]:
        failures.append("route audit error")
    report = {
        "status": "pass" if not failures else "fail", "model": args.model,
        "expected": expected, "usable": len(usable), "correct": correct,
        "outcomes": counts(usable, graded), "harmful": [list(key) for key in harms],
        "framing_errors": framing, "multiple_mutations": multiple,
        "reasoning_leaks": leaks, "route_audit": audit,
        "gate_failures": failures,
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def regrade(args):
    """Regrade an immutable raw pool after fixing route-aware grading."""
    composition.ROUTED_TABLE_TASKS = composition.ROUTED_TABLE_TASKS | {
        "get-ordinal-table",
    }
    tasks = composition.load_tasks()
    raw = latest(args.out)
    destination = Path(args.graded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        for key in sorted(raw):
            row = raw[key]
            task = tasks[row["task_id"]]
            before = composition.read_text(ROOT / task["fixture"])
            after = row["final_document"]
            outcome, detail = composition.grade_row(task, row, before, after)
            document_outcome = None
            document_detail = None
            if after != before:
                document_outcome, document_detail = pi_bench.check_result(
                    task, before, after, None,
                )
            graded = {
                "condition": row["condition"], "task_id": row["task_id"],
                "family": row["family"], "trial": row["trial"],
                "outcome": outcome, "detail": detail,
                "document_outcome": document_outcome,
                "document_detail": document_detail,
                "evaluation_model": row.get("evaluation_model"),
                "framing_errors": row.get("framing_errors", []),
            }
            handle.write(json.dumps(graded, separators=(",", ":")) + "\n")
    print(f"regraded {len(raw)} existing raw rows into {destination}")


def preflight(args):
    configure(args)
    subprocess.run([args.binary, "--version"], check=True)
    response = subprocess.run(
        ["curl", "-fsS", "--max-time", "5", f"{args.endpoint}/models"],
        text=True, capture_output=True, check=True,
    )
    ids = [entry["id"] for entry in json.loads(response.stdout).get("data", [])]
    expected = MODELS[args.model]["definition"]["id"]
    if expected not in ids:
        raise SystemExit(f"expected {expected}, endpoint returned {ids}")
    print(f"safe-routed v3 {args.model} preflight passed")


def add_runtime(parser):
    parser.add_argument("--model", choices=sorted(MODELS), required=True)
    parser.add_argument("--scope", choices=("full", "affected"), default="affected")
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--pi-sdk", default=str(pi_bench.DEFAULT_PI_SDK))
    parser.add_argument("--worker", default=str(pi_bench.DEFAULT_WORKER))
    parser.add_argument("--node", default="node")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--timeout", type=int, default=900)
    parser.set_defaults(condition="safe-routed-v3")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("preflight")
    add_runtime(check)
    check.set_defaults(func=preflight)

    runner = sub.add_parser("run")
    add_runtime(runner)
    runner.add_argument("--trials", type=int, required=True)
    runner.add_argument("--seed-start", type=int, default=0)
    runner.add_argument("--out", required=True)
    runner.add_argument("--graded", required=True)
    runner.set_defaults(func=run)

    mini = sub.add_parser("analyse-minicpm")
    mini.add_argument("--previous-raw", required=True)
    mini.add_argument("--previous-graded", required=True)
    mini.add_argument("--out", required=True)
    mini.add_argument("--graded", required=True)
    mini.add_argument("--analysis", required=True)
    mini.set_defaults(func=analyse_minicpm)

    retain = sub.add_parser("analyse-retention")
    retain.add_argument("--model", choices=("gemma", "ornith"), required=True)
    retain.add_argument("--trials", type=int, required=True)
    retain.add_argument("--out", required=True)
    retain.add_argument("--graded", required=True)
    retain.add_argument("--analysis", required=True)
    retain.set_defaults(func=analyse_retention)

    correction = sub.add_parser("regrade")
    correction.add_argument("--out", required=True)
    correction.add_argument("--graded", required=True)
    correction.set_defaults(func=regrade)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
