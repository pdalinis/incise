#!/usr/bin/env python3
"""Run the pre-registered Pi 0.1.1 live composition promotion gate.

The model is driven through Pi itself. Pi loads the requested extension, builds
its real system prompt from active tool metadata, validates tool arguments, and
executes the native package binary. This file owns fixture isolation, immutable
JSONL records, mechanical grading, pairing, and the promotion decision.
"""

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(BENCH))

import armb  # noqa: E402
import ceiling  # noqa: E402
from grade import check_result  # noqa: E402
from incise_ops import (  # noqa: E402
    OpError,
    render_frontmatter,
    render_list_summary,
    render_section_outline,
    render_table_list,
    table_get,
)
from stats import mcnemar_exact  # noqa: E402

PACKAGE_VERSION = "0.1.1"
RESULT_PREFIX = "PI_BENCH_RESULT="
CONTROL = [
    "table_edit", "list_edit", "section_edit", "frontmatter_edit", "table_get",
]
TREATMENT = CONTROL + ["md_tables", "md_lists", "md_outline"]
CONDITIONS = {"control": CONTROL, "treatment": TREATMENT}
TASK_FILES = [
    BENCH / "tasks" / "tables.json",
    BENCH / "tasks" / "lists.json",
    BENCH / "tasks" / "sections.json",
    BENCH / "tasks" / "frontmatter.json",
    BENCH / "tasks" / "tables_read.json",
]
DEFAULT_EXTENSION = ROOT / "plugins" / "pi" / "extension" / "index.ts"
DEFAULT_PI_SDK = (
    ROOT / "plugins" / "pi" / "node_modules" / "@earendil-works"
    / "pi-coding-agent" / "dist" / "index.js"
)
DEFAULT_WORKER = BENCH / "pi_trial.mjs"
DEFAULT_SANDBOX = Path("/private/tmp/incise-pi-composition-v0.1.1")
MARKER = ".incise-pi-composition-sandbox"


class WorkerError(RuntimeError):
    pass


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(raw)


def write_new_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def load_tasks():
    tasks = []
    for path in TASK_FILES:
        for task in json.loads(path.read_text())["tasks"]:
            copied = dict(task)
            copied["_task_file"] = str(path.relative_to(ROOT))
            tasks.append(copied)
    if len(tasks) != 48:
        raise SystemExit(f"expected 48 frozen tasks, found {len(tasks)}")
    return tasks


def task_family(task):
    family = task["family"]
    if family.startswith("table-get"):
        return "table-read"
    return family.split("-", 1)[0]


def task_summary(task, content):
    family = armb.family_of(task)
    render = {
        "table": render_table_list,
        "list": render_list_summary,
        "section": render_section_outline,
        "frontmatter": render_frontmatter,
    }[family]
    return render(content, task["fixture"])


def prompt_for(task, content):
    return f"{task_summary(task, content)}\n\n{task['instruction']}"


def ensure_sandbox(path):
    path = Path(path).resolve()
    if path == Path("/") or path == Path.home():
        raise SystemExit(f"refusing unsafe sandbox path: {path}")
    marker = path / MARKER
    if path.exists() and not marker.exists():
        raise SystemExit(f"refusing to clean unmarked sandbox: {path}")
    path.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return path


def reset_sandbox(path, task=None):
    path = ensure_sandbox(path)
    for child in path.iterdir():
        if child.name == MARKER:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    (path / ".agent").mkdir()
    if task is not None:
        source = ROOT / task["fixture"]
        destination = path / task["fixture"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return path


def worker_request(args, mode, condition, **extra):
    sandbox = Path(args.sandbox).resolve()
    return {
        "mode": mode,
        "cwd": str(sandbox),
        "agentDir": str(sandbox / ".agent"),
        "extension": str(Path(args.extension).resolve()),
        "piSdk": str(Path(args.pi_sdk).resolve()),
        "endpoint": args.endpoint,
        "tools": CONDITIONS[condition],
        **extra,
    }


def call_worker(args, request):
    process = subprocess.run(
        [args.node, str(Path(args.worker).resolve())],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=args.timeout,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise WorkerError(detail or f"worker exited {process.returncode}")
    matches = [line for line in process.stdout.splitlines()
               if line.startswith(RESULT_PREFIX)]
    if len(matches) != 1:
        raise WorkerError(f"worker returned {len(matches)} result records; stdout={process.stdout!r}")
    return json.loads(matches[0][len(RESULT_PREFIX):])


def package_lock_integrity(package_root):
    package_root = Path(package_root).resolve()
    for parent in package_root.parents:
        lock = parent / "package-lock.json"
        if not lock.exists():
            continue
        value = json.loads(lock.read_text())
        packages = value.get("packages", {})
        try:
            relative = package_root.relative_to(parent).as_posix()
        except ValueError:
            continue
        entry = packages.get(relative, {})
        if entry.get("integrity"):
            return entry["integrity"], str(lock)
    return None, None


def probe_condition(args, condition):
    reset_sandbox(args.sandbox)
    result = call_worker(args, worker_request(
        args, "probe", condition, seed=0,
    ))
    expected = CONDITIONS[condition]
    if result.get("packageVersion") != PACKAGE_VERSION:
        raise SystemExit(
            f"expected pi-incise {PACKAGE_VERSION}, got {result.get('packageVersion')}")
    if result.get("activeTools") != expected:
        raise SystemExit(
            f"active tool order differs: expected {expected}, got {result.get('activeTools')}")
    names = [tool["name"] for tool in result.get("tools", [])]
    if names != expected:
        raise SystemExit(f"registered tool order differs: expected {expected}, got {names}")
    binary = result.get("binary") or {}
    if binary.get("version") != f"incise {PACKAGE_VERSION}":
        raise SystemExit(f"wrong binary version: {binary.get('version')}")
    if not args.allow_nonpackage_binary and binary.get("source") != "package":
        raise SystemExit(
            f"benchmark requires the npm package binary, got source={binary.get('source')!r}")
    return result


def validate_measured_schemas(probe):
    binary = probe["binary"]["path"]
    process = subprocess.run(
        [binary, "schema"], text=True, capture_output=True, check=True,
    )
    native = json.loads(process.stdout)
    active = [
        {"name": tool["name"], "description": tool["description"],
         "parameters": tool["parameters"]}
        for tool in probe["tools"] if tool["name"] in CONTROL
    ]
    if active != native:
        raise SystemExit("Pi measured schemas differ from the selected binary schema")


def git_output(*arguments):
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.strip()


def command_probe(args):
    control = probe_condition(args, "control")
    treatment = probe_condition(args, "treatment")
    validate_measured_schemas(treatment)
    integrity, lock_path = package_lock_integrity(treatment["packageRoot"])
    if not integrity:
        raise SystemExit("could not recover pi-incise tarball integrity from package-lock.json")
    sdk_root = Path(args.pi_sdk).resolve().parent.parent
    sdk_version = json.loads((sdk_root / "package.json").read_text())["version"]
    if sdk_version != "0.85.1":
        raise SystemExit(f"expected Pi SDK 0.85.1, got {sdk_version}")

    manifest = {
        "status": "preflight",
        "preregistration": {
            "issue": "https://github.com/pdalinis/incise/issues/10",
            "commit": "455ffda",
            "plan": "bench/PI_COMPOSITION_PLAN.md",
        },
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "commit": git_output("rev-parse", "HEAD"),
            "describe": git_output("describe", "--always", "--dirty"),
        },
        "package": {
            "name": "pi-incise",
            "version": PACKAGE_VERSION,
            "root": treatment["packageRoot"],
            "integrity": integrity,
            "integrity_source": lock_path,
            "binary": treatment["binary"],
        },
        "pi": {"version": sdk_version, "sdk": str(Path(args.pi_sdk).resolve())},
        "model": {
            "name": "gemma-4-26B-A4B-it",
            "alias": "gemma4-direct-q8",
            "endpoint": args.endpoint,
            "model_file": str(Path(args.model_file).resolve()) if args.model_file else None,
            "model_sha256": sha256_file(args.model_file) if args.model_file else None,
            "server": "llama.cpp 0.4.0 build 10809 (5266f24da)",
            "launch_flags": [
                "--jinja", "--ctx-size 65536", "--parallel 1", "--n-gpu-layers 999",
                "--cache-type-k q8_0", "--cache-type-v q8_0", "--flash-attn on",
                "--cache-ram 8192", "--temperature 1.0", "--top-k 64",
                "--top-p 0.95", "--min-p 0.05", "--repeat-penalty 1.15",
                "--repeat-last-n 256", "--presence-penalty 0",
                "--reasoning-budget 3000", "--reasoning-format deepseek", "-n 8192",
                "--host 127.0.0.1", "--port 8081",
            ],
        },
        "tasks": {str(path.relative_to(ROOT)): sha256_file(path) for path in TASK_FILES},
        "conditions": {
            "control": {
                "tools": CONTROL,
                "tools_sha256": canonical_hash(control["tools"]),
                "system_prompt": control["systemPrompt"],
                "system_prompt_sha256": sha256_bytes(control["systemPrompt"].encode()),
            },
            "treatment": {
                "tools": TREATMENT,
                "tools_sha256": canonical_hash(treatment["tools"]),
                "system_prompt": treatment["systemPrompt"],
                "system_prompt_sha256": sha256_bytes(treatment["systemPrompt"].encode()),
            },
        },
        "design": {
            "tasks": 48,
            "trials_per_task": 10,
            "trials_per_condition": 480,
            "max_turns": 4,
            "seed": "trial index",
            "primary": "graded correct, paired exact McNemar",
            "decision": "p >= 0.05 pooled and no family loss > 5.0 percentage points",
        },
    }
    write_new_json(args.out, manifest)
    print(f"wrote {args.out}")


def ideal_calls(task):
    source = task.get("ideal_calls")
    if source is None and "ideal_call" in task:
        source = [task["ideal_call"]]
    if source is None:
        raise SystemExit(f"{task['id']}: no ideal call")
    expressed = []
    for call in source:
        name, arguments = ceiling.as_tool_call(task, "compose_5", call)
        if name is None:
            raise SystemExit(f"{task['id']}: {arguments}")
        expressed.append({"name": name, "arguments": arguments})
    return expressed


def call_map(row):
    return {result["tool_call_id"]: result for result in row.get("tool_results", [])}


def structured_table_report(before, row):
    results = call_map(row)
    report = None
    errors = []
    for call in row.get("tool_calls", []):
        function = call.get("function", {})
        if function.get("name") != "table_get":
            continue
        result = results.get(call.get("id"))
        if result and result.get("is_error"):
            errors.append(result.get("content", "table_get failed"))
            continue
        if result is None:
            errors.append("table_get produced no tool result")
            continue
        try:
            arguments = json.loads(function.get("arguments") or "{}")
            report = table_get(before, arguments.get("table"), arguments.get("filter"))
        except (json.JSONDecodeError, OpError, TypeError) as error:
            errors.append(str(error))
    return report, errors


def is_transport(error):
    if not error:
        return False
    return any(token in error for token in (
        "APIConnection", "Connection refused", "ECONNREFUSED", "fetch failed",
        "HTTP 500", "InternalServer", "Timeout", "timed out",
    ))


def grade_actual(task, row, before, after):
    if row.get("error"):
        return ("transport" if is_transport(row["error"]) else "malformed", row["error"])
    calls = row.get("tool_calls") or []
    if not calls:
        return "malformed", "no tool call"

    if task["family"].startswith("table-get"):
        report, errors = structured_table_report(before, row)
        return check_result(
            task, before, after,
            report if report is not None else (errors[-1] if errors else None),
        )

    errors = [
        result.get("content", "tool failed")
        for result in row.get("tool_results", []) if result.get("is_error")
    ]
    if after == before:
        if errors:
            return "op_error", errors[-1]
        return "wrong", "tool sequence changed nothing"
    outcome, detail = check_result(task, before, after)
    if outcome == "wrong" and errors:
        return "op_error", f"{detail}; after: {errors[-1]}"
    return outcome, detail


def raw_call(name, arguments, index):
    return {
        "id": f"ideal-{index}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def command_ceiling(args):
    probes = {name: probe_condition(args, name) for name in CONDITIONS}
    validate_measured_schemas(probes["treatment"])
    tasks = load_tasks()
    records = []
    failures = 0
    for condition in CONDITIONS:
        for task in tasks:
            sandbox = reset_sandbox(args.sandbox, task)
            before = read_text(ROOT / task["fixture"])
            calls = ideal_calls(task)
            result = call_worker(args, worker_request(
                args, "ideal", condition, seed=0, calls=calls,
            ))
            after = read_text(sandbox / task["fixture"])
            row = {
                "condition": condition,
                "task_id": task["id"],
                "tool_calls": [raw_call(call["name"], call["arguments"], index)
                               for index, call in enumerate(calls)],
                "tool_results": result["toolResults"],
                "error": None,
            }
            outcome, detail = grade_actual(task, row, before, after)
            records.append({
                "condition": condition,
                "task_id": task["id"],
                "outcome": outcome,
                "detail": detail,
                "final_sha256": sha256_bytes(after.encode()),
            })
            mark = "ok" if outcome == "correct" else "FAIL"
            print(f"{mark:4s} {condition:9s} {task['id']}")
            failures += outcome != "correct"
    result = {
        "status": "pass" if not failures else "fail",
        "expected": len(tasks) * len(CONDITIONS),
        "correct": len(tasks) * len(CONDITIONS) - failures,
        "records": records,
    }
    write_new_json(args.out, result)
    print(f"ceiling: {result['correct']}/{result['expected']}")
    return 1 if failures else 0


def run_one(args, condition, task, trial):
    sandbox = reset_sandbox(args.sandbox, task)
    fixture = sandbox / task["fixture"]
    before = read_text(ROOT / task["fixture"])
    try:
        result = call_worker(args, worker_request(
            args,
            "run",
            condition,
            seed=trial,
            maxTurns=4,
            prompt=prompt_for(task, before),
        ))
        error = result.get("error")
    except (WorkerError, subprocess.TimeoutExpired) as exc:
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
        "max_turns": 4,
        "error": error,
        "initial_sha256": sha256_bytes(before.encode()),
        "final_sha256": sha256_bytes(after.encode()),
        "final_document": after,
    }
    outcome, detail = grade_actual(task, row, before, after)
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


def latest_rows(path):
    rows = {}
    if not Path(path).exists():
        return rows
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def command_clap(args):
    probe_condition(args, "control")
    tasks = load_tasks()
    paths = [Path(args.out_a), Path(args.out_b)]
    graded_paths = [Path(args.graded_a), Path(args.graded_b)]
    for path in paths + graded_paths + [Path(args.report)]:
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    all_graded = []
    for repetition, (raw_path, graded_path) in enumerate(zip(paths, graded_paths), 1):
        current = []
        with open(raw_path, "x", encoding="utf-8", newline="\n") as raw_handle, \
                open(graded_path, "x", encoding="utf-8", newline="\n") as graded_handle:
            for index, task in enumerate(tasks, 1):
                row, graded = run_one(args, "control", task, 0)
                write_jsonl(raw_handle, row)
                write_jsonl(graded_handle, graded)
                current.append((row, graded))
                print(f"clap {repetition}/2 [{index:2d}/48] {task['id']:26s} {graded['outcome']}")
        all_graded.append(current)

    mismatches = []
    for (row_a, grade_a), (row_b, grade_b) in zip(*all_graded):
        sequence_a = [(call["function"]["name"], call["function"]["arguments"])
                      for call in row_a["tool_calls"]]
        sequence_b = [(call["function"]["name"], call["function"]["arguments"])
                      for call in row_b["tool_calls"]]
        if (row_a.get("error")
                or row_b.get("error")
                or not row_a.get("n_turns")
                or not row_b.get("n_turns")
                or grade_a["outcome"] == "transport"
                or grade_b["outcome"] == "transport"
                or grade_a["outcome"] != grade_b["outcome"]
                or sequence_a != sequence_b):
            mismatches.append({
                "task_id": row_a["task_id"],
                "outcomes": [grade_a["outcome"], grade_b["outcome"]],
                "tool_calls_equal": sequence_a == sequence_b,
            })
    report = {
        "status": "pass" if not mismatches else "fail",
        "pairs": 48,
        "mismatches": mismatches,
        "raw": [str(path) for path in paths],
        "graded": [str(path) for path in graded_paths],
    }
    write_new_json(args.report, report)
    print(f"determinism clap: {48 - len(mismatches)}/48 identical")
    return 1 if mismatches else 0


def require_treatment_gate(args):
    clap = json.loads(Path(args.clap_report).read_text())
    if clap.get("status") != "pass":
        raise SystemExit("treatment is gated on a passing determinism clap")
    control = latest_rows(args.control_graded)
    correct_keys = {key for key, row in control.items() if row.get("outcome") != "transport"}
    if len(correct_keys) != 480:
        raise SystemExit(
            f"treatment is gated on 480 completed control outcomes; found {len(correct_keys)}")


def command_run(args):
    condition = args.condition
    probe = probe_condition(args, condition)
    validate_measured_schemas(probe)
    if condition == "treatment":
        require_treatment_gate(args)
    tasks = load_tasks()
    raw_path, graded_path = Path(args.out), Path(args.graded)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    graded_path.parent.mkdir(parents=True, exist_ok=True)
    done = {key for key, row in latest_rows(raw_path).items() if not row.get("error")}
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    print(f"{len(work)} trials to run, condition={condition}")
    started = time.time()
    with open(raw_path, "a", encoding="utf-8", newline="\n") as raw_handle, \
            open(graded_path, "a", encoding="utf-8", newline="\n") as graded_handle:
        for index, (task, trial) in enumerate(work, 1):
            row, graded = run_one(args, condition, task, trial)
            write_jsonl(raw_handle, row)
            write_jsonl(graded_handle, graded)
            elapsed = time.time() - started
            eta = (elapsed / index) * (len(work) - index) / 60 if index else 0
            print(
                f"[{index:3d}/{len(work)}] {task['id']:26s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s {graded['outcome']:16s} eta {eta:.0f}m",
                flush=True,
            )


def paired_data(path):
    return {(row["task_id"], row["trial"]): row for row in latest_rows(path).values()}


def command_analyse(args):
    control = paired_data(args.control)
    treatment = paired_data(args.treatment)
    shared = sorted(set(control) & set(treatment))
    dropped = [key for key in shared
               if control[key]["outcome"] == "transport"
               or treatment[key]["outcome"] == "transport"]
    shared = [key for key in shared if key not in set(dropped)]
    if len(shared) != 480:
        raise SystemExit(f"expected 480 complete paired trials, found {len(shared)}")

    only_control = sum(control[key]["outcome"] == "correct"
                       and treatment[key]["outcome"] != "correct" for key in shared)
    only_treatment = sum(control[key]["outcome"] != "correct"
                         and treatment[key]["outcome"] == "correct" for key in shared)
    pooled_p = mcnemar_exact(only_control, only_treatment)
    families = {}
    for family in ("table", "list", "section", "frontmatter", "table-read"):
        keys = [key for key in shared if control[key]["family"] == family]
        control_correct = sum(control[key]["outcome"] == "correct" for key in keys)
        treatment_correct = sum(treatment[key]["outcome"] == "correct" for key in keys)
        families[family] = {
            "n": len(keys),
            "control_correct": control_correct,
            "treatment_correct": treatment_correct,
            "delta_points": 100 * (treatment_correct - control_correct) / len(keys),
        }
    passes = pooled_p >= 0.05 and all(
        value["delta_points"] >= -5.0 for value in families.values()
    )
    result = {
        "status": "pass" if passes else "fail",
        "pairs": len(shared),
        "transport_pairs_dropped": [list(key) for key in dropped],
        "discordant": {"only_control": only_control, "only_treatment": only_treatment},
        "mcnemar_exact_p": pooled_p,
        "families": families,
    }
    write_new_json(args.out, result)
    print(f"promotion gate: {result['status'].upper()}")
    print(f"pooled discordant {only_control}-{only_treatment}, p={pooled_p:.6g}")
    for family, value in families.items():
        print(
            f"{family:12s} {value['control_correct']:3d}/{value['n']:<3d} -> "
            f"{value['treatment_correct']:3d}/{value['n']:<3d} "
            f"({value['delta_points']:+.1f} points)"
        )
    return 0 if passes else 1


def add_runtime_arguments(parser):
    parser.add_argument("--extension", default=str(DEFAULT_EXTENSION))
    parser.add_argument("--pi-sdk", default=str(DEFAULT_PI_SDK))
    parser.add_argument("--worker", default=str(DEFAULT_WORKER))
    parser.add_argument("--node", default="node")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--sandbox", default=str(DEFAULT_SANDBOX))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--allow-nonpackage-binary", action="store_true")


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe")
    add_runtime_arguments(probe)
    probe.add_argument("--model-file")
    probe.add_argument("--out", default=str(BENCH / "results" / "pi_0_1_1_manifest.json"))
    probe.set_defaults(func=command_probe)

    ceiling_parser = subparsers.add_parser("ceiling")
    add_runtime_arguments(ceiling_parser)
    ceiling_parser.add_argument(
        "--out", default=str(BENCH / "results" / "pi_0_1_1_ceiling.json"))
    ceiling_parser.set_defaults(func=command_ceiling)

    clap = subparsers.add_parser("clap")
    add_runtime_arguments(clap)
    clap.add_argument("--out-a", default=str(BENCH / "results" / "pi_0_1_1_clap_a.jsonl"))
    clap.add_argument("--out-b", default=str(BENCH / "results" / "pi_0_1_1_clap_b.jsonl"))
    clap.add_argument("--graded-a", default=str(BENCH / "results" / "pi_0_1_1_clap_a_graded.jsonl"))
    clap.add_argument("--graded-b", default=str(BENCH / "results" / "pi_0_1_1_clap_b_graded.jsonl"))
    clap.add_argument("--report", default=str(BENCH / "results" / "pi_0_1_1_clap.json"))
    clap.set_defaults(func=command_clap)

    run = subparsers.add_parser("run")
    add_runtime_arguments(run)
    run.add_argument("--condition", choices=tuple(CONDITIONS), required=True)
    run.add_argument("--trials", type=int, default=10)
    run.add_argument("--out", required=True)
    run.add_argument("--graded", required=True)
    run.add_argument("--clap-report", default=str(BENCH / "results" / "pi_0_1_1_clap.json"))
    run.add_argument("--control-graded", default=str(BENCH / "results" / "pi_0_1_1_control_graded.jsonl"))
    run.set_defaults(func=command_run)

    analyse = subparsers.add_parser("analyse")
    analyse.add_argument("--control", default=str(BENCH / "results" / "pi_0_1_1_control_graded.jsonl"))
    analyse.add_argument("--treatment", default=str(BENCH / "results" / "pi_0_1_1_treatment_graded.jsonl"))
    analyse.add_argument("--out", default=str(BENCH / "results" / "pi_0_1_1_analysis.json"))
    analyse.set_defaults(func=command_analyse)

    args = parser.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
