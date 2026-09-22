#!/usr/bin/env python3
"""Run and analyse the preregistered Gemma structural roadmap campaign."""

import argparse
from collections import Counter, defaultdict
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import armb  # noqa: E402
from grade import check_result  # noqa: E402
from incise_ops import (  # noqa: E402
    frontmatter_get,
    render_frontmatter_get,
    resolve_section,
    section_outline,
    table_get,
)
import pi_composition as pi_bench  # noqa: E402
from stats import mcnemar_exact  # noqa: E402


PREFIX = "gemma_roadmap_20260921"
BASELINE_TOOLS = [
    "table_edit", "list_edit", "section_edit", "frontmatter_edit", "table_get",
    "md_tables", "md_lists", "md_outline",
]
SECTION_INSERT_TASKS = {
    "insert-release-at-top", "insert-subsection-last",
    "insert-nested-ratelimits", "insert-troubleshooting",
}
SECTION_GUARD_TASKS = {"rename-closed-atx", "replace-linux-body"}
FRONTMATTER_TASKS = {
    "set-build-jobs", "set-build-target", "set-dana-role",
    "clear-title", "set-draft-true",
}
TABLE_QUERY_TASKS = {"get-filter-two-columns", "get-filter-no-match"}
ARMS = {
    "section_insert": SECTION_INSERT_TASKS,
    "section_guard": SECTION_GUARD_TASKS,
    "frontmatter": FRONTMATTER_TASKS,
    "table_query": TABLE_QUERY_TASKS,
}
FRONTMATTER_TYPES = {
    "set-build-jobs": "integer",
    "set-build-target": "string",
    "set-dana-role": "string",
    "clear-title": "null",
    "set-draft-true": "boolean",
}
TABLE_FILTER_COLUMNS = {
    "get-filter-two-columns": ["Priority", "Version"],
    "get-filter-no-match": ["Priority"],
}
CURRENT_EXTENSION = ROOT / "plugins" / "pi" / "extension" / "index.ts"
TREATMENT_EXTENSION = BENCH / "gemma_bench_extension.ts"
DEFAULT_BINARY = ROOT / "target" / "debug" / "incise"
DEFAULT_SANDBOX = Path("/private/tmp/incise-gemma-roadmap-20260921")
MARKER = ".incise-gemma-roadmap-sandbox"


def read_text(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def load_tasks():
    tasks = []
    for path in pi_bench.TASK_FILES:
        for source in json.loads(path.read_text())["tasks"]:
            task = dict(source)
            task["_task_file"] = str(path.relative_to(ROOT))
            tasks.append(task)
    if len(tasks) != 48:
        raise RuntimeError(f"expected 48 tasks, found {len(tasks)}")
    return tasks


def task_family(task):
    return pi_bench.task_family(task)


def ensure_sandbox(path):
    path = Path(path).resolve()
    if path in (Path("/"), Path.home()):
        raise RuntimeError(f"unsafe sandbox: {path}")
    marker = path / MARKER
    if path.exists() and not marker.exists():
        raise RuntimeError(f"refusing unmarked sandbox: {path}")
    path.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return path


def reset_sandbox(path, task):
    path = ensure_sandbox(path)
    for child in path.iterdir():
        if child.name == MARKER:
            continue
        if child.is_dir() and not child.is_symlink():
            import shutil
            shutil.rmtree(child)
        else:
            child.unlink()
    (path / ".agent").mkdir()
    source = ROOT / task["fixture"]
    destination = path / task["fixture"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copyfile(source, destination)
    return path


def call_worker(args, request, config=None):
    env = os.environ.copy()
    env["INCISE_BIN"] = str(Path(args.binary).resolve())
    env.pop("INCISE_PROFILE", None)
    if config is None:
        env.pop("INCISE_GEMMA_BENCH_CONFIG", None)
    else:
        env["INCISE_GEMMA_BENCH_CONFIG"] = json.dumps(
            config, separators=(",", ":"))
    process = subprocess.run(
        [args.node, str(Path(args.worker).resolve())],
        input=json.dumps(request), text=True, capture_output=True,
        timeout=args.timeout, env=env,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise pi_bench.WorkerError(detail or f"worker exited {process.returncode}")
    matches = [line for line in process.stdout.splitlines()
               if line.startswith(pi_bench.RESULT_PREFIX)]
    if len(matches) != 1:
        raise pi_bench.WorkerError(
            f"worker returned {len(matches)} records: {process.stdout!r}")
    return json.loads(matches[0][len(pi_bench.RESULT_PREFIX):])


def worker_request(args, sandbox, extension, tools, task, prompt, max_turns):
    return {
        "mode": "run",
        "cwd": str(sandbox),
        "agentDir": str(sandbox / ".agent"),
        "extension": str(extension.resolve()),
        "piSdk": str(Path(args.pi_sdk).resolve()),
        "endpoint": args.endpoint,
        "tools": tools,
        "seed": task["_trial"],
        "maxTurns": max_turns,
        "prompt": prompt,
        "recordActiveTools": True,
        "recordProviderRequests": True,
    }


def shortest_section_addresses(content):
    entries = section_outline(content)
    segments = [[part.strip() for part in entry["path"].split(">")]
                for entry in entries]
    addresses = []
    for parts in segments:
        selected = None
        for width in range(1, len(parts) + 1):
            suffix = parts[-width:]
            matches = sum(
                len(other) >= width and other[-width:] == suffix
                for other in segments)
            if matches == 1:
                selected = " > ".join(suffix)
                break
        if selected is not None:
            addresses.append(selected)
    return addresses


def literal_section_target(task, content):
    instruction = task["instruction"]
    if task["id"] == "rename-closed-atx":
        match = re.search(r'Rename\s+"([^"]+)"\s+to\s+"', instruction)
    elif task["id"] == "replace-linux-body":
        match = re.search(r"under\s+(.+?)\s+with\s+\"", instruction)
    else:
        raise RuntimeError(f"no literal target parser for {task['id']}")
    if not match:
        raise RuntimeError(f"could not recover literal section target from {instruction!r}")
    target = match.group(1).strip()
    try:
        resolve_section(content, target)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"literal target {target!r} does not resolve uniquely: {exc}") from exc
    return target


def scalar_frontmatter_keys(content):
    report = frontmatter_get(content, None)
    keys = []
    for entry in report.get("keys", []):
        if entry.get("type") not in ("map", "sequence"):
            keys.append(entry["path"])
    if not keys:
        raise RuntimeError("frontmatter read returned no scalar paths")
    return keys


def config_for(arm, task, content):
    common = {"path": task["fixture"]}
    if arm == "section_insert":
        return {
            **common, "kind": "section_insert_tree",
            "anchors": shortest_section_addresses(content),
        }
    if arm == "section_guard":
        target = literal_section_target(task, content)
        kind = ("section_rename_target" if task["id"] == "rename-closed-atx"
                else "section_replace_target")
        return {**common, "kind": kind, "target": target}
    if arm == "frontmatter":
        return {
            **common, "kind": "frontmatter_typed",
            "valueType": FRONTMATTER_TYPES[task["id"]],
            "keys": scalar_frontmatter_keys(content),
        }
    if arm == "table_query":
        return {
            **common, "kind": "table_query",
            "table": {"heading": "Packages"},
            "filterColumns": TABLE_FILTER_COLUMNS[task["id"]],
        }
    raise RuntimeError(f"unknown arm: {arm}")


def treatment_prompt(task, content, arm):
    summary = pi_bench.task_summary(task, content)
    if arm == "frontmatter":
        values = render_frontmatter_get(content, task["fixture"], None)
        summary = f"{summary}\n\nFlattened frontmatter values:\n{values}"
    return f"{summary}\n\n{task['instruction']}"


def latest_rows(path):
    rows = {}
    path = Path(path)
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[(row["task_id"], row["trial"])] = row
    return rows


def is_transport(error):
    return pi_bench.is_transport(error)


def successful_call(row, name):
    results = {result["tool_call_id"]: result
               for result in row.get("tool_results", [])}
    for call in row.get("tool_calls", []):
        if call.get("function", {}).get("name") != name:
            continue
        result = results.get(call.get("id"))
        if result is not None and not result.get("is_error"):
            return call, result
    return None, None


def grade_treatment(task, arm, row, before, after, config):
    if row.get("error"):
        return ("transport" if is_transport(row["error"]) else "malformed",
                row["error"])
    if arm != "table_query":
        return pi_bench.grade_actual(task, row, before, after)
    if after != before:
        return check_result(task, before, after, None)
    call, _result = successful_call(row, "table_query")
    if call is None:
        errors = [r.get("content", "tool failed") for r in row.get("tool_results", [])
                  if r.get("is_error")]
        return ("op_error", errors[-1]) if errors else ("malformed", "no successful table query")
    try:
        values = json.loads(call["function"].get("arguments") or "{}")
        columns = config["filterColumns"]
        query_filter = {column: values[column] for column in columns}
        report = table_get(before, config["table"], query_filter)
    except Exception as exc:  # noqa: BLE001
        return "malformed", f"could not reconstruct table query: {exc}"
    return check_result(task, before, after, report)


def run_one(args, condition, task, trial):
    task = dict(task)
    task["_trial"] = trial
    sandbox = reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = read_text(ROOT / task["fixture"])
    config = None
    if condition == "baseline":
        extension = CURRENT_EXTENSION
        tools = BASELINE_TOOLS
        prompt = pi_bench.prompt_for(task, before)
        max_turns = 4
    else:
        config = config_for(condition, task, before)
        extension = TREATMENT_EXTENSION
        if condition == "section_insert":
            tool_name = "section_insert_tree"
        elif condition == "section_guard":
            tool_name = ("section_rename_target"
                         if task["id"] == "rename-closed-atx"
                         else "section_replace_target")
        elif condition == "frontmatter":
            value_type = FRONTMATTER_TYPES[task["id"]]
            tool_name = ("frontmatter_clear" if value_type == "null"
                         else f"frontmatter_set_{value_type}")
        else:
            tool_name = "table_query"
        tools = [tool_name]
        prompt = treatment_prompt(task, before, condition)
        max_turns = 2
    try:
        request = worker_request(
            args, sandbox, extension, tools, task, prompt, max_turns)
        result = call_worker(args, request, config)
        error = result.get("error")
    except (pi_bench.WorkerError, subprocess.TimeoutExpired) as exc:
        result = {
            "elapsed_s": None, "completion_tokens": 0, "n_turns": 0,
            "turns": [], "tool_calls": [], "tool_results": [],
            "final_content": "", "capped": False,
        }
        error = f"{type(exc).__name__}: {exc}"
    after = read_text(fixture)
    row = {
        **result,
        "condition": condition,
        "task_id": task["id"],
        "task_file": task["_task_file"],
        "family": task_family(task),
        "trial": trial,
        "seed": trial,
        "max_turns": max_turns,
        "error": error,
        "initial_sha256": pi_bench.sha256_bytes(before.encode()),
        "final_sha256": pi_bench.sha256_bytes(after.encode()),
        "final_document": after,
        "bench_config": config,
    }
    outcome, detail = (
        pi_bench.grade_actual(task, row, before, after)
        if condition == "baseline"
        else grade_treatment(task, condition, row, before, after, config)
    )
    graded = {
        "condition": condition,
        "task_id": task["id"],
        "family": task_family(task),
        "trial": trial,
        "outcome": outcome,
        "detail": detail,
    }
    return row, graded


def write_jsonl(handle, value):
    handle.write(json.dumps(value, separators=(",", ":")) + "\n")
    handle.flush()


def run(args):
    tasks = load_tasks()
    if args.condition != "baseline":
        tasks = [task for task in tasks if task["id"] in ARMS[args.condition]]
    raw_path = Path(args.out)
    graded_path = Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in latest_rows(raw_path).items()
            if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} trials to run, condition={args.condition}", flush=True)
    started = time.time()
    with open(raw_path, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(graded_path, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, args.condition, task, trial)
            write_jsonl(raw_handle, row)
            write_jsonl(graded_handle, graded)
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60 if index else 0
            print(
                f"[{index:3d}/{len(work)}] {task['id']:27s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:18s} "
                f"eta {eta:.0f}m", flush=True)


def regrade(args):
    tasks = {task["id"]: task for task in load_tasks()}
    rows = latest_rows(args.out)
    with open(args.graded, "w", encoding="utf-8", newline="\n") as handle:
        for key in sorted(rows):
            row = rows[key]
            task = tasks[row["task_id"]]
            before = read_text(ROOT / task["fixture"])
            after = row.get("final_document", before)
            condition = row["condition"]
            if condition == "baseline":
                outcome, detail = pi_bench.grade_actual(task, row, before, after)
            else:
                outcome, detail = grade_treatment(
                    task, condition, row, before, after, row["bench_config"])
            write_jsonl(handle, {
                "condition": condition, "task_id": task["id"],
                "family": task_family(task), "trial": row["trial"],
                "outcome": outcome, "detail": detail,
            })


def count_outcomes(rows):
    return dict(sorted(Counter(row["outcome"] for row in rows).items()))


def analyse(args):
    baseline = latest_rows(args.baseline)
    treatments = {arm: latest_rows(path) for arm, path in (
        ("section_insert", args.section_insert),
        ("section_guard", args.section_guard),
        ("frontmatter", args.frontmatter),
        ("table_query", args.table_query),
    )}
    expected_baseline = args.trials * 48
    report = {
        "status": "complete",
        "baseline": {
            "expected": expected_baseline,
            "observed": len(baseline),
            "outcomes": count_outcomes(baseline.values()),
            "families": {},
        },
        "arms": {},
    }
    for family in ("table", "list", "section", "frontmatter", "table-read"):
        rows = [row for row in baseline.values() if row["family"] == family]
        report["baseline"]["families"][family] = {
            "n": len(rows), "outcomes": count_outcomes(rows),
        }
    if len(baseline) != expected_baseline:
        report["status"] = "incomplete"

    gate_thresholds = {
        "section_insert": 32,
        "section_guard": 18,
        "frontmatter": 45,
        "table_query": 18,
    }
    for arm, treatment in treatments.items():
        expected = args.trials * len(ARMS[arm])
        shared = sorted(set(baseline) & set(treatment))
        transport = [key for key in shared
                     if baseline[key]["outcome"] == "transport"
                     or treatment[key]["outcome"] == "transport"]
        usable = [key for key in shared if key not in set(transport)]
        control_correct = sum(baseline[key]["outcome"] == "correct" for key in usable)
        treatment_correct = sum(treatment[key]["outcome"] == "correct" for key in usable)
        only_control = sum(
            baseline[key]["outcome"] == "correct"
            and treatment[key]["outcome"] != "correct" for key in usable)
        only_treatment = sum(
            baseline[key]["outcome"] != "correct"
            and treatment[key]["outcome"] == "correct" for key in usable)
        harmful = {"destructive", "collateral:content", "collateral:formatting"}
        forbidden = set(harmful)
        if arm == "table_query":
            forbidden |= {"unfiltered", "misreported"}
        forbidden_count = sum(
            treatment[key]["outcome"] in forbidden for key in usable)
        regression_limit = 2 if arm == "section_insert" else 0
        passes = (
            len(treatment) == expected
            and treatment_correct >= gate_thresholds[arm]
            and treatment_correct > control_correct
            and forbidden_count == 0
            and only_control <= regression_limit
        )
        per_task = {}
        for task_id in sorted(ARMS[arm]):
            keys = [key for key in usable if key[0] == task_id]
            per_task[task_id] = {
                "n": len(keys),
                "baseline": count_outcomes(baseline[key] for key in keys),
                "treatment": count_outcomes(treatment[key] for key in keys),
            }
        report["arms"][arm] = {
            "status": "pass" if passes else "fail",
            "expected": expected,
            "observed": len(treatment),
            "paired": len(usable),
            "transport_pairs": [list(key) for key in transport],
            "baseline_correct": control_correct,
            "treatment_correct": treatment_correct,
            "discordant": {
                "only_baseline": only_control,
                "only_treatment": only_treatment,
                "mcnemar_exact_p": mcnemar_exact(only_control, only_treatment),
            },
            "treatment_outcomes": count_outcomes(treatment.values()),
            "forbidden_outcomes": forbidden_count,
            "gate": {
                "minimum_correct": gate_thresholds[arm],
                "regression_limit": regression_limit,
            },
            "tasks": per_task,
        }
        if len(treatment) != expected:
            report["status"] = "incomplete"
    pi_bench.write_new_json(args.out, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def preflight(args):
    subprocess.run([args.binary, "--version"], check=True)
    subprocess.run([args.binary, "schema"], check=True, capture_output=True)
    subprocess.run(
        [args.node, "--experimental-strip-types", "--check",
         str(TREATMENT_EXTENSION)], check=True)
    tasks = load_tasks()
    for arm, task_ids in ARMS.items():
        for task in tasks:
            if task["id"] not in task_ids:
                continue
            content = read_text(ROOT / task["fixture"])
            config_for(arm, task, content)
    print("preflight passed")


def add_runtime(parser):
    parser.add_argument("--binary", default=str(DEFAULT_BINARY))
    parser.add_argument("--pi-sdk", default=str(pi_bench.DEFAULT_PI_SDK))
    parser.add_argument("--worker", default=str(pi_bench.DEFAULT_WORKER))
    parser.add_argument("--node", default="node")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--timeout", type=int, default=900)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("preflight")
    add_runtime(check)
    check.set_defaults(func=preflight)

    run_parser = subparsers.add_parser("run")
    add_runtime(run_parser)
    run_parser.add_argument("--condition", choices=("baseline", *ARMS), required=True)
    run_parser.add_argument("--trials", type=int, default=10)
    run_parser.add_argument("--out", required=True)
    run_parser.add_argument("--graded", required=True)
    run_parser.set_defaults(func=run)

    grade_parser = subparsers.add_parser("regrade")
    grade_parser.add_argument("--out", required=True)
    grade_parser.add_argument("--graded", required=True)
    grade_parser.set_defaults(func=regrade)

    analysis = subparsers.add_parser("analyse")
    analysis.add_argument("--trials", type=int, default=10)
    analysis.add_argument("--baseline", required=True)
    analysis.add_argument("--section-insert", required=True)
    analysis.add_argument("--section-guard", required=True)
    analysis.add_argument("--frontmatter", required=True)
    analysis.add_argument("--table-query", required=True)
    analysis.add_argument("--out", required=True)
    analysis.set_defaults(func=analyse)

    args = parser.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
