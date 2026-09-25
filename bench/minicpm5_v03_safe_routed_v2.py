#!/usr/bin/env python3
"""Run and analyse the preregistered safe-routed v2 transfer gate."""

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import analyze_ornith_held_routes as old_routes  # noqa: E402
import minicpm5_v03_safe_routed as v1  # noqa: E402
import ornith_full as composition  # noqa: E402
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


AFFECTED = {
    "add-row-aligned-short", "add-row-aligned-repad", "add-row-ragged",
    "add-row-alignment-markers", "add-item-tight-dash", "add-item-loose",
    "replace-linux-body", "set-build-jobs", "set-build-target",
    "set-dana-role", "clear-title", "set-draft-true",
}
PREVIOUSLY_HARMFUL = {
    "add-row-aligned-repad", "add-item-tight-dash", "add-item-loose",
    "replace-linux-body",
}
NEW_TOOL = "table_add_row_target"
ALL_TOOLS = composition.ALL_TOOLS + [NEW_TOOL]
STANDARD_TOOLS = composition.STANDARD_TOOLS
HARMFUL = composition.HARMFUL
PROFILES = {"safe-routed-v2": "safe-routed"}

MODELS = {
    "minicpm": {
        "definition": {
            "id": "minicpm5-2b-q8",
            "name": "openbmb/MiniCPM5-2B Q8_0",
            "contextWindow": 65_536,
            "maxTokens": 8_192,
            "samplingParams": {"temperature": 0.7, "top_p": 0.95},
        },
        "thinking": "off", "max_tokens": 8192, "parallel": "default",
        "framing": {
            "temperature": 0.7, "top_p": 0.95,
            "parallel_tool_calls": None,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    },
    "gemma": {
        "definition": {
            "id": "gemma4-direct-q8",
            "name": "gemma-4-26B-A4B-it",
            "contextWindow": 65_536,
            "maxTokens": 8_192,
            "samplingParams": {},
        },
        "thinking": "off", "max_tokens": 8192, "parallel": "default",
        "framing": {
            "temperature": None, "top_p": None,
            "parallel_tool_calls": None,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    },
    "ornith": {
        "definition": {
            "id": "ornith-1.5-9b-q8",
            "name": "Ornith-1.5-9B",
            "reasoning": True,
            "contextWindow": 65_536,
            "maxTokens": 2_048,
            "samplingParams": {
                "temperature": 0.6, "top_p": 0.95, "top_k": 20,
                "min_p": 0.0, "presence_penalty": 0.0,
                "repeat_penalty": 1.0,
            },
            "compat": {
                "supportsDeveloperRole": False,
                "supportsReasoningEffort": False,
                "thinkingFormat": "qwen-chat-template",
            },
        },
        "thinking": "off", "max_tokens": 2048, "parallel": "false",
        "framing": {
            "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0,
            "presence_penalty": 0, "repeat_penalty": 1,
            "parallel_tool_calls": False,
            "chat_template_kwargs": {
                "enable_thinking": False, "preserve_thinking": True,
            },
        },
    },
}

DEFAULT_BINARY = ROOT / "target" / "debug" / "incise"
DEFAULT_SANDBOX = Path("/private/tmp/incise-safe-routed-v2-20260925")
ACTIVE_MODEL = "minicpm"


def spec(tool, route, resolved):
    return {"tool": tool, "route": route, "supplied": {}, "resolved": resolved}


def v2_specs():
    specs = old_routes.expected_specs()
    tables = {
        "add-row-aligned-short": (
            "Aligned table > Components",
            {"Component": "sprocket", "Status": "active", "Owner": "rowan"},
        ),
        "add-row-aligned-repad": (
            "Aligned table > Components",
            {"Component": "hyperwidget-assembly", "Status": "active", "Owner": "dana"},
        ),
        "add-row-ragged": (
            "Ragged table > Components",
            {"Component": "sprocket", "Status": "active", "Owner": "rowan"},
        ),
        "add-row-alignment-markers": (
            "Column alignment markers > All four forms", ["i", "j", "k", "l"],
        ),
    }
    for task_id, (heading, values) in tables.items():
        specs[task_id] = spec(
            NEW_TOOL, "table-add-row-target",
            {"table": {"heading": heading, "ordinal": 0}, "values": values},
        )
    specs["add-item-tight-dash"] = spec(
        "list_append_target", "list-append-target",
        {
            "list": {
                "heading": "Nested and mixed lists > Dash markers, two-space indent",
                "ordinal": 0,
            },
            "text": "fourth", "position": "end",
        },
    )
    specs["add-item-loose"] = spec(
        "list_append_target", "list-append-target",
        {
            "list": {"heading": "Nested and mixed lists > Loose vs tight", "ordinal": 1},
            "text": "loose four", "position": "end",
        },
    )
    specs["replace-linux-body"] = spec(
        "section_replace_target", "section-replace-body",
        {
            "section": "Deep heading nesting > Upgrade > Linux",
            "text": "See the platform notes.", "overwrite": True,
        },
    )
    frontmatter = {
        "set-build-jobs": ("frontmatter_set_integer", "build.jobs", 8),
        "set-build-target": ("frontmatter_set_string", "build.target", "debug"),
        "set-dana-role": ("frontmatter_set_string", "authors[1].role", "maintainer"),
        "clear-title": ("frontmatter_clear", "title", None),
        "set-draft-true": ("frontmatter_set_boolean", "draft", True),
    }
    for task_id, (tool, key, value) in frontmatter.items():
        specs[task_id] = spec(
            tool, "frontmatter-typed",
            {"key": key, "value": value, "must_exist": True},
        )
    return specs


def configure(args):
    global ACTIVE_MODEL
    ACTIVE_MODEL = args.model
    config = MODELS[args.model]
    composition.MODEL = config["definition"]
    composition.PROFILES = PROFILES
    composition.ALL_TOOLS = ALL_TOOLS
    composition.validate_framing = validate_framing
    args.thinking = config["thinking"]
    args.max_tokens = config["max_tokens"]
    args.parallel_tool_calls = config["parallel"]
    args.task_id = None if args.scope == "full" else sorted(AFFECTED)


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
        # Base grading validates framing before this wrapper can add the label.
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


def successful_results(row, name):
    return old_routes.successful_results(row, name)


def route_audit(keys, raw, graded, affected_only=False):
    specs = v2_specs()
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
        successes = successful_results(row, expected["tool"])
        if graded[key]["outcome"] == "correct" and len(successes) != 1:
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


def changed_mutations(row):
    return sum(
        not result.get("is_error") and bool((result.get("details") or {}).get("changed"))
        for result in row.get("tool_results") or []
    )


def reasoning_leak(row):
    visible = [row.get("final_content") or ""] + [
        (call.get("function") or {}).get("arguments") or ""
        for call in row.get("tool_calls") or []
    ]
    return "<think>" in "\n".join(visible) or "</think>" in "\n".join(visible)


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
    multiple = [[*key, changed_mutations(raw[key])] for key in usable
                if changed_mutations(raw[key]) > 1]
    leaks = [list(key) for key in usable if reasoning_leak(raw[key])]
    audit = route_audit(usable, raw, graded, affected_only=True)
    target_correct = sum(key[0] in AFFECTED and key in correct for key in usable)
    harmful_correct = sum(key[0] in PREVIOUSLY_HARMFUL and key in correct for key in usable)
    failures = []
    if len(keys) != 48 or len(usable) != 48:
        failures.append("not all 48 pairs usable")
    if len(correct) < 45:
        failures.append("correctness below 45/48")
    if target_correct != len(AFFECTED):
        failures.append("affected tasks not 12/12")
    if harmful_correct != len(PREVIOUSLY_HARMFUL):
        failures.append("previously harmful tasks not 4/4")
    if regressions:
        failures.append("v1-correct task regressed")
    if harms:
        failures.append("harmful outcome")
    if framing:
        failures.append("provider framing error")
    if multiple:
        failures.append("multiple changed mutations")
    if leaks:
        failures.append("reasoning leak")
    if audit["errors"]:
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
        "outcomes": counts(usable, graded),
        "affected_correct": target_correct,
        "previously_harmful_correct": harmful_correct,
        "harmful": [list(key) for key in harms],
        "framing_errors": framing, "multiple_mutations": multiple,
        "reasoning_leaks": leaks, "route_audit": audit,
        "gate_failures": failures,
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
    multiple = [[*key, changed_mutations(raw[key])] for key in usable
                if changed_mutations(raw[key]) > 1]
    leaks = [list(key) for key in usable if reasoning_leak(raw[key])]
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
    print(f"safe-routed v2 {args.model} preflight passed")


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
    parser.set_defaults(condition="safe-routed-v2")


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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
