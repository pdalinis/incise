#!/usr/bin/env python3
"""Analyze the preregistered forced-tool MiniCPM Pi list-profile arm."""

import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import minicpm_list_integrated as treatment  # noqa: E402

GENERIC_RAW = "bench/results/minicpm5_routed_lists_20260921.jsonl"
GENERIC_GRADED = "bench/results/minicpm5_routed_lists_20260921_graded.jsonl"
PI_CONTROL_RAW = "bench/results/minicpm5_pi_list_profile_20260922_v2.jsonl"
PI_CONTROL_GRADED = "bench/results/minicpm5_pi_list_profile_20260922_v2_graded.jsonl"
TREATMENT_RAW = "bench/results/minicpm5_pi_list_profile_20260922_v3.jsonl"
TREATMENT_GRADED = "bench/results/minicpm5_pi_list_profile_20260922_v3_graded.jsonl"
OUT = "bench/results/minicpm5_pi_list_force_analysis_20260922_v3.json"
TASKS = set(treatment.EXPECTED_ROUTE)
CONTENT_TOOL = {
    "append": "list_append_item",
    "after": "list_insert_after",
    "between": "list_insert_between",
}


def rows(path):
    selected = {}
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["task_id"] in TASKS:
                selected[(row["task_id"], row["trial"])] = row
    return selected


def sha256(path):
    with open(os.path.join(ROOT, path), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def exact_mcnemar(control_only, treatment_only):
    n = control_only + treatment_only
    if not n:
        return 1.0
    tail = sum(
        math.comb(n, k) for k in range(min(control_only, treatment_only) + 1))
    return min(1.0, 2 * tail / (2 ** n))


def mean(data, field):
    values = [row[field] for row in data.values() if row.get(field) is not None]
    return round(sum(values) / len(values), 2) if values else None


def successful_content_is_validated(row):
    results = {
        result["tool_call_id"]: result for result in row.get("tool_results", [])
    }
    successful = []
    for call in row.get("tool_calls", []):
        if call.get("function", {}).get("name") not in set(CONTENT_TOOL.values()):
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            successful.append((result.get("details") or {}).get("validated") is True)
    return bool(successful) and all(successful)


def paired(control, treated, expected):
    control_only = sum(
        control[key]["outcome"] == "correct"
        and treated[key]["outcome"] != "correct" for key in expected)
    treatment_only = sum(
        control[key]["outcome"] != "correct"
        and treated[key]["outcome"] == "correct" for key in expected)
    control_correct = sum(
        control[key]["outcome"] == "correct" for key in expected)
    treatment_correct = sum(
        treated[key]["outcome"] == "correct" for key in expected)
    return {
        "control": control_correct,
        "treatment": treatment_correct,
        "control_only": control_only,
        "treatment_only": treatment_only,
        "exact_mcnemar_p": exact_mcnemar(control_only, treatment_only),
    }


def localize(raw, graded):
    if graded["outcome"] == "correct":
        return "correct"
    names = [call.get("function", {}).get("name")
             for call in raw.get("tool_calls", [])]
    if "list_select" not in names:
        return "selection_invocation_or_arguments"
    if raw.get("selection_validated") is not True:
        return "address_selection"
    if raw.get("route_correct") is not True:
        return "request_routing"
    if not any(name in CONTENT_TOOL.values() for name in names):
        return "content_invocation_or_arguments"
    if raw.get("content_validated") is not True:
        return "content_or_anchor_selection"
    return "execution_or_content_semantics"


def schema_snapshot_is_identical():
    process = subprocess.run(
        [sys.executable, "bench/schematest.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return (
        process.returncode == 0
        and "byte-identical to the schemes they were measured as" in process.stdout
    ), process.stdout.strip() or process.stderr.strip()


def main():
    generic = rows(GENERIC_GRADED)
    generic_raw = rows(GENERIC_RAW)
    pi_control = rows(PI_CONTROL_GRADED)
    pi_control_raw = rows(PI_CONTROL_RAW)
    treated = rows(TREATMENT_GRADED)
    raw = rows(TREATMENT_RAW)
    expected = {(task, trial) for task in TASKS for trial in range(3)}
    pools = (generic, generic_raw, pi_control, pi_control_raw, treated, raw)
    if not all(set(data) == expected for data in pools):
        raise RuntimeError("controls and treatment are not the fixed 21 pairs")

    outcomes = Counter(row["outcome"] for row in treated.values())
    by_task = defaultdict(Counter)
    localization = Counter()
    for key in expected:
        by_task[key[0]][treated[key]["outcome"]] += 1
        localization[localize(raw[key], treated[key])] += 1

    pi_pair = paired(pi_control, treated, expected)
    generic_pair = paired(generic, treated, expected)
    phase_requests = [
        request
        for key in expected
        for request in raw[key].get("phase_provider_requests", [])
    ]
    phase_sequences = {
        f"{task}:{trial}": [request.get("expected") for request in
                            raw[(task, trial)].get("phase_provider_requests", [])]
        for task, trial in sorted(expected)
    }
    phase_coverage = all(
        (requests := raw[key].get("phase_provider_requests", []))
        and requests[0].get("expected") == "list_select"
        and CONTENT_TOOL[treatment.EXPECTED_ROUTE[key[0]]] in {
            request.get("expected") for request in requests[1:]
        }
        for key in expected
    )
    schema_identical, schema_output = schema_snapshot_is_identical()

    unsafe = {"destructive", "collateral:content", "collateral:formatting"}
    gate = {
        "at_least_nineteen_correct": outcomes["correct"] >= 19,
        "each_task_correct_in_two_seeds": all(
            by_task[task]["correct"] >= 2 for task in TASKS),
        "no_pi_control_correct_regressed": pi_pair["control_only"] == 0,
        "no_generic_control_correct_regressed": generic_pair["control_only"] == 0,
        "no_destructive_or_collateral": not any(outcomes[name] for name in unsafe),
        "refusals_left_fixture_unchanged": all(
            not raw[key].get("document_changed")
            for key in expected if treated[key]["outcome"] == "op_error"),
        "all_routes_match_preregistered_mapping": all(
            raw[key].get("route_correct") is True for key in expected),
        "executed_structure_was_validated": all(
            raw[key].get("selection_validated") is True
            and successful_content_is_validated(raw[key])
            for key in expected if raw[key].get("successful_mutations", 0) > 0),
        "at_most_one_successful_mutation_per_turn": all(
            raw[key].get("successful_mutations", 0) <= 1 for key in expected),
        "every_active_request_forced_exact_advertised_tool": (
            len(phase_requests) >= 42
            and phase_coverage
            and all(raw[key].get("forced_choice_correct") is True
                    for key in expected)
        ),
        "default_schema_snapshot_byte_identical": schema_identical,
    }
    gate["passed"] = all(gate.values())

    artifact_paths = (
        GENERIC_RAW, GENERIC_GRADED,
        PI_CONTROL_RAW, PI_CONTROL_GRADED,
        TREATMENT_RAW, TREATMENT_GRADED,
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration_commit": "4ae14da",
        "implementation_commit": "08b65e2",
        "model": "minicpm5-2b-q8",
        "pi_version": "0.85.1",
        "pairs": 21,
        "treatment_outcomes": dict(sorted(outcomes.items())),
        "treatment_by_task": {
            task: dict(sorted(counts.items()))
            for task, counts in sorted(by_task.items())
        },
        "failure_localization": dict(sorted(localization.items())),
        "paired_vs_pi_control": pi_pair,
        "paired_vs_generic_control": generic_pair,
        "provider_request_audit": {
            "active_phase_requests": len(phase_requests),
            "all_exact": all(request.get("correct") is True
                             for request in phase_requests),
            "all_expected_tools_advertised": all(
                request.get("advertised") is True for request in phase_requests),
            "every_pair_covers_both_phases": phase_coverage,
            "phase_sequences": phase_sequences,
        },
        "invocation": {
            "selection_calls": sum(
                any(call.get("function", {}).get("name") == "list_select"
                    for call in row.get("tool_calls", [])) for row in raw.values()),
            "validated_content_calls": sum(
                successful_content_is_validated(row) for row in raw.values()),
            "successful_mutations": sum(
                row.get("successful_mutations", 0) for row in raw.values()),
        },
        "efficiency": {
            "pi_control_mean_completion_tokens": mean(
                pi_control_raw, "completion_tokens"),
            "treatment_mean_completion_tokens": mean(raw, "completion_tokens"),
            "treatment_mean_elapsed_s": mean(raw, "elapsed_s"),
            "treatment_mean_turns": mean(raw, "n_turns"),
        },
        "schema_test_output": schema_output,
        "gate": gate,
        "source_sha256": {
            "extension": sorted({row.get("extension_sha256") for row in raw.values()}),
            "pipeline": sorted({row.get("pipeline_sha256") for row in raw.values()}),
            "worker": sorted({row.get("worker_sha256") for row in raw.values()}),
        },
        "artifacts": {path: sha256(path) for path in artifact_paths},
    }
    with open(os.path.join(ROOT, OUT), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
