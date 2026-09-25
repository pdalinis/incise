#!/usr/bin/env python3
"""Run and analyse the preregistered MiniCPM5 v0.3 Pi composition gate."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import analyze_ornith_held_routes as route_specs  # noqa: E402
import ornith_full as composition  # noqa: E402
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


MODEL = {
    "id": "minicpm5-2b-q8",
    "name": "openbmb/MiniCPM5-2B Q8_0",
    "contextWindow": 65_536,
    "maxTokens": 8_192,
    "samplingParams": {"temperature": 0.7, "top_p": 0.95},
}
PROFILES = {"standard": "standard", "forced-safe-routed": "safe-routed"}
STANDARD_TOOLS = composition.STANDARD_TOOLS
HARMFUL = composition.HARMFUL
FAMILY_ORDER = ("table", "list", "section", "frontmatter", "table-read")
FAMILY_FLOORS = {
    "table": 57,
    "list": 100,
    "section": 140,
    "frontmatter": 105,
    "table-read": 57,
}
DEFAULT_BINARY = ROOT / "target" / "debug" / "incise"
DEFAULT_SANDBOX = Path("/private/tmp/incise-minicpm5-v03-20260925")


# Reuse the established full-composition runner, changing only the frozen model
# and explicit profile labels. Its fixture reset, prompt, grader, and final-file
# safety grading stay identical to the Gemma and Ornith campaigns.
composition.MODEL = MODEL
composition.PROFILES = PROFILES


def validate_framing(row):
    errors = []
    requests = row.get("provider_requests") or []
    if not requests:
        return ["no provider request recorded"]
    expected = {
        "model": MODEL["id"],
        "seed": row["seed"],
        "max_tokens": row.get("max_tokens", 8192),
        "temperature": 0.7,
        "top_p": 0.95,
        "parallel_tool_calls": None,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    for index, request in enumerate(requests):
        for key, value in expected.items():
            if request.get(key) != value:
                errors.append(
                    f"request {index} {key}: expected {value!r}, "
                    f"got {request.get(key)!r}"
                )
        if row["condition"] == "standard":
            if request.get("tools") != STANDARD_TOOLS:
                errors.append(
                    f"request {index} standard tools: {request.get('tools')!r}"
                )
            if request.get("active_tools") != STANDARD_TOOLS:
                errors.append(
                    "request "
                    f"{index} standard active tools: {request.get('active_tools')!r}"
                )
    return errors


composition.validate_framing = validate_framing


def successful_results(row, name):
    results = {
        result["tool_call_id"]: result for result in row.get("tool_results") or []
    }
    found = []
    for call in row.get("tool_calls") or []:
        if (call.get("function") or {}).get("name") != name:
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            found.append((call, result))
    return found


def successful_changes(row):
    return sum(
        not result.get("is_error")
        and bool((result.get("details") or {}).get("changed"))
        for result in row.get("tool_results") or []
    )


def visible_reasoning_leak(row):
    visible = [row.get("final_content") or ""]
    visible.extend(
        (call.get("function") or {}).get("arguments") or ""
        for call in row.get("tool_calls") or []
    )
    text = "\n".join(visible)
    return "<think>" in text or "</think>" in text


def metrics(keys, raw, graded):
    harmful = [
        key for key in keys
        if graded[key]["outcome"] in HARMFUL
        or graded[key].get("document_outcome") in HARMFUL
    ]
    return {
        "n": len(keys),
        "correct": sum(graded[key]["outcome"] == "correct" for key in keys),
        "harmful": len(harmful),
        "harmful_trials": [list(key) for key in harmful],
        "outcomes": dict(sorted(Counter(graded[key]["outcome"] for key in keys).items())),
        "mean_elapsed_s": round(
            sum(raw[key].get("elapsed_s") or 0 for key in keys) / len(keys), 3
        ) if keys else 0,
        "mean_completion_tokens": round(
            sum(raw[key].get("completion_tokens") or 0 for key in keys) / len(keys), 3
        ) if keys else 0,
    }


def audit_treatment(keys, raw, graded):
    specs = route_specs.expected_specs()
    errors = []
    routed = 0
    fallback = 0
    for key in keys:
        row = raw[key]
        requests = row.get("provider_requests") or []
        first = requests[0] if requests else {}
        expected = specs.get(key[0])
        if expected is None:
            fallback += 1
            if (first.get("tools") != STANDARD_TOOLS
                    or first.get("active_tools") != STANDARD_TOOLS):
                errors.append([
                    *key, "fallback tool surface", first.get("tools"),
                    first.get("active_tools"),
                ])
            continue

        routed += 1
        if (first.get("tools") != [expected["tool"]]
                or first.get("active_tools") != [expected["tool"]]
                or first.get("tool_choice") is not None):
            errors.append([
                *key, "provider framing", first.get("tools"),
                first.get("active_tools"), first.get("tool_choice"),
            ])
        call_names = [
            (call.get("function") or {}).get("name")
            for call in row.get("tool_calls") or []
        ]
        if any(name != expected["tool"] for name in call_names):
            errors.append([*key, "unexpected tool calls", call_names])
        successes = successful_results(row, expected["tool"])
        if len(successes) > 1:
            errors.append([*key, "successful routed calls", len(successes)])
        if graded[key]["outcome"] == "correct" and len(successes) != 1:
            errors.append([*key, "correct outcome successful calls", len(successes)])
        for call, result in successes:
            try:
                supplied = json.loads(
                    (call.get("function") or {}).get("arguments") or "{}"
                )
            except json.JSONDecodeError:
                supplied = "invalid-json"
            details = result.get("details") or {}
            changed = bool(details.get("changed"))
            expected_changed = expected["tool"] != "table_query"
            if (supplied != expected["supplied"]
                    or details.get("route") != expected["route"]
                    or details.get("resolvedArguments") != expected["resolved"]
                    or changed != expected_changed):
                errors.append([
                    *key, "resolved call", supplied, details.get("route"),
                    details.get("resolvedArguments"), changed, expected,
                ])
    return {"routed": routed, "fallback": fallback, "errors": errors}


def file_sha256(path):
    path = Path(path)
    return pi_bench.sha256_file(path) if path.exists() else None


def git_commit():
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    )
    return process.stdout.strip()


def analyse(args):
    control_raw = composition.latest_rows(args.control_raw)
    control_graded = composition.latest_rows(args.control_graded)
    treatment_raw = composition.latest_rows(args.treatment_raw)
    treatment_graded = composition.latest_rows(args.treatment_graded)
    expected = 48 * args.trials
    key_sets = [
        set(control_raw), set(control_graded),
        set(treatment_raw), set(treatment_graded),
    ]
    observed = sorted(set.intersection(*key_sets))
    transport = [
        key for key in observed
        if control_graded[key]["outcome"] == "transport"
        or treatment_graded[key]["outcome"] == "transport"
    ]
    transport_set = set(transport)
    usable = [key for key in observed if key not in transport_set]

    control = metrics(usable, control_raw, control_graded)
    treatment = metrics(usable, treatment_raw, treatment_graded)
    only_control = sum(
        control_graded[key]["outcome"] == "correct"
        and treatment_graded[key]["outcome"] != "correct"
        for key in usable
    )
    only_treatment = sum(
        control_graded[key]["outcome"] != "correct"
        and treatment_graded[key]["outcome"] == "correct"
        for key in usable
    )

    families = {}
    family_regressions = []
    for family in FAMILY_ORDER:
        keys = [key for key in usable if treatment_graded[key]["family"] == family]
        control_correct = sum(
            control_graded[key]["outcome"] == "correct" for key in keys
        )
        treatment_correct = sum(
            treatment_graded[key]["outcome"] == "correct" for key in keys
        )
        if treatment_correct < control_correct:
            family_regressions.append(family)
        families[family] = {
            "n": len(keys),
            "control_correct": control_correct,
            "treatment_correct": treatment_correct,
            "delta": treatment_correct - control_correct,
            "full_floor": FAMILY_FLOORS[family],
        }

    framing_errors = {
        "control": [
            [*key, *control_raw[key].get("framing_errors", [])]
            for key in usable if control_raw[key].get("framing_errors")
        ],
        "treatment": [
            [*key, *treatment_raw[key].get("framing_errors", [])]
            for key in usable if treatment_raw[key].get("framing_errors")
        ],
    }
    multiple_mutations = [
        [*key, successful_changes(treatment_raw[key])]
        for key in usable if successful_changes(treatment_raw[key]) > 1
    ]
    reasoning_leaks = [
        list(key) for key in usable if visible_reasoning_leak(treatment_raw[key])
    ]
    route_audit = audit_treatment(usable, treatment_raw, treatment_graded)

    failures = []
    minimum_usable = expected if args.phase == "smoke" else expected - 2
    if len(observed) != expected:
        failures.append(f"expected {expected} paired keys, observed {len(observed)}")
    if len(usable) < minimum_usable:
        failures.append(f"usable {len(usable)} below {minimum_usable}")
    if framing_errors["control"] or framing_errors["treatment"]:
        failures.append("provider framing error")
    if treatment["harmful"]:
        failures.append("treatment harmful outcome")
    if multiple_mutations:
        failures.append("multiple successful mutations")
    if reasoning_leaks:
        failures.append("reasoning leakage")
    if route_audit["errors"]:
        failures.append("route or fallback audit error")
    if family_regressions:
        failures.append("family correctness regression")
    if treatment["correct"] <= control["correct"]:
        failures.append("treatment did not strictly improve correctness")
    if args.phase == "full":
        if treatment["correct"] < 472:
            failures.append("treatment correctness below 472")
        for family, values in families.items():
            if values["treatment_correct"] < FAMILY_FLOORS[family]:
                failures.append(f"{family} below full floor")

    report = {
        "status": "pass" if not failures else "fail",
        "phase": args.phase,
        "expected": expected,
        "observed": len(observed),
        "usable": len(usable),
        "transport_pairs": [list(key) for key in transport],
        "control": control,
        "treatment": treatment,
        "discordant": {
            "control_only": only_control,
            "treatment_only": only_treatment,
            "mcnemar_exact_p": mcnemar_exact(only_control, only_treatment),
        },
        "families": families,
        "family_regressions": family_regressions,
        "framing_errors": framing_errors,
        "route_audit": route_audit,
        "multiple_mutations": multiple_mutations,
        "reasoning_leaks": reasoning_leaks,
        "gate_failures": failures,
        "manifest": {
            "executor_commit": git_commit(),
            "model": MODEL,
            "profiles": PROFILES,
            "task_hashes": {
                str(path.relative_to(ROOT)): file_sha256(path)
                for path in pi_bench.TASK_FILES
            },
            "artifact_hashes": {
                "control_raw": file_sha256(args.control_raw),
                "control_graded": file_sha256(args.control_graded),
                "treatment_raw": file_sha256(args.treatment_raw),
                "treatment_graded": file_sha256(args.treatment_graded),
            },
        },
    }
    pi_bench.write_new_json(args.analysis, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def preflight(args):
    subprocess.run([args.binary, "--version"], check=True)
    subprocess.run([args.node, "--check", args.worker], check=True)
    response = subprocess.run(
        ["curl", "-fsS", "--max-time", "5", f"{args.endpoint}/models"],
        text=True, capture_output=True, check=True,
    )
    model_ids = [entry["id"] for entry in json.loads(response.stdout).get("data", [])]
    if MODEL["id"] not in model_ids:
        raise SystemExit(f"expected {MODEL['id']}, endpoint returned {model_ids}")
    print("MiniCPM5 v0.3 preflight passed")


def add_runtime(parser):
    parser.add_argument("--condition", choices=sorted(PROFILES), default="standard")
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--pi-sdk", default=str(pi_bench.DEFAULT_PI_SDK))
    parser.add_argument("--worker", default=str(pi_bench.DEFAULT_WORKER))
    parser.add_argument("--node", default="node")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--timeout", type=int, default=900)
    parser.set_defaults(
        thinking="off", max_tokens=8192, parallel_tool_calls="default",
        task_id=None,
    )


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("preflight")
    add_runtime(check)
    check.set_defaults(func=preflight)

    runner = subparsers.add_parser("run")
    add_runtime(runner)
    runner.add_argument("--trials", type=int, default=1)
    runner.add_argument("--seed-start", type=int, default=0)
    runner.add_argument("--out", required=True)
    runner.add_argument("--graded", required=True)
    runner.set_defaults(func=composition.run)

    report = subparsers.add_parser("analyse")
    report.add_argument("--phase", choices=("smoke", "full"), required=True)
    report.add_argument("--trials", type=int, required=True)
    report.add_argument("--control-raw", required=True)
    report.add_argument("--control-graded", required=True)
    report.add_argument("--treatment-raw", required=True)
    report.add_argument("--treatment-graded", required=True)
    report.add_argument("--analysis", required=True)
    report.set_defaults(func=analyse)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
