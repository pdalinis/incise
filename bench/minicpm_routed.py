#!/usr/bin/env python3
"""MiniCPM5 family-routed, forced-phase, terminal-mutation live arm.

The preregistered condition is in `MINICPM5_ROUTED_PLAN.md`. This harness uses
Arm B's prompts, model client, executor, and grader; it changes only the tools
visible on each turn and stops after the first mutation response.
"""

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
from incise_ops import apply_op  # noqa: E402
from runner import call, record  # noqa: E402


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

TASK_FILE = {
    "tables": "tables.json",
    "lists": "lists.json",
    "sections": "sections.json",
    "frontmatter": "frontmatter.json",
}

FRONTMATTER_CREATE_TASKS = {
    "add-build-cache", "create-on-absent", "fill-empty",
}


def load_schemas(binary, section_children=False):
    proc = subprocess.run(
        [binary, "schema", "--profile", "safe-small"],
        check=True, capture_output=True, text=True, timeout=10,
    )
    schemas = {schema["name"]: schema for schema in json.loads(proc.stdout)}
    required = {
        "table_add_row", "table_update_cell", "list_get", "list_add_item",
        "section_insert", "section_append", "frontmatter_get", "frontmatter_set",
    }
    missing = required - set(schemas)
    if missing:
        raise RuntimeError(f"safe-small schema is missing {sorted(missing)}")

    base = schemas.pop("frontmatter_set")
    for suffix, kind, description in (
        ("string", "string", "Set one frontmatter path to a string."),
        ("integer", "integer", "Set one frontmatter path to an integer."),
        ("boolean", "boolean", "Set one frontmatter path to a boolean."),
        ("null", "null", "Set one frontmatter path to null while retaining the key."),
    ):
        schema = copy.deepcopy(base)
        schema["name"] = f"frontmatter_set_{suffix}"
        schema["description"] = description + " Copy the exact key from frontmatter_get."
        schema["parameters"]["properties"]["value"] = {"type": kind}
        schemas[schema["name"]] = schema
    if section_children:
        insert = copy.deepcopy(schemas["section_insert"])
        insert["description"] = (
            "Insert one new markdown section atomically. Put requested "
            "subsections in children; never write subsection headings in body."
        )
        child = {
            "type": "object",
            "properties": {
                "heading": {"type": "string"},
                "body": {"type": "string"},
                "children": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["heading"],
                    },
                },
            },
            "required": ["heading"],
        }
        insert["parameters"]["properties"]["children"] = {
            "type": "array",
            "description": (
                "Subsections to create atomically under the new section. "
                "Use this instead of putting headings in body."
            ),
            "items": child,
        }
        schemas["section_insert"] = insert
    return schemas


def forced(name):
    return {"type": "function", "function": {"name": name}}


def desired_frontmatter_type(task):
    calls = task.get("ideal_calls") or []
    if not calls:
        raise RuntimeError(f"{task['id']} has no ideal call to type")
    value = calls[0]["args"].get("value")
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    raise RuntimeError(f"{task['id']} has unsupported routed value {value!r}")


def route(task):
    family = task["family"]
    if family == "table-add-row":
        return None, "table_add_row"
    if family == "table-update-cell":
        return None, "table_update_cell"
    if family == "list-add-item":
        return "list_get", "list_add_item"
    if family == "section-insert":
        return None, "section_insert"
    if family == "section-append":
        return None, "section_append"
    if family == "frontmatter-set":
        return "frontmatter_get", f"frontmatter_set_{desired_frontmatter_type(task)}"
    raise RuntimeError(f"no routed treatment for {family}")


def frontmatter_precondition(task):
    """Host-owned create/update intent; never delegated to the model."""
    if task["family"] != "frontmatter-set":
        return None
    if task["id"] in FRONTMATTER_CREATE_TASKS:
        return {"must_absent": True}
    return {"must_exist": True}


def treatment_payload(task, seed, schemas):
    payload = armb.build_payload(task, "compose_5", seed)
    read_name, edit_name = route(task)
    if read_name:
        active = read_name
    else:
        active = edit_name
    payload["tools"] = [{"type": "function", "function": schemas[active]}]
    payload["tool_choice"] = forced(active)
    return payload, read_name, edit_name


def _assistant_message(row):
    return {
        "role": "assistant",
        "content": row.get("content"),
        "tool_calls": row.get("tool_calls") or [],
    }


def _sample(endpoint, payload):
    response, elapsed = call(endpoint, payload)
    row = record(response, elapsed)
    return response, row


def _parse_call(call_row, expected):
    calls = call_row.get("tool_calls") or []
    if not calls:
        return None, f"forced {expected} phase returned no tool call"
    call0 = calls[0]
    fn = call0.get("function", {})
    if fn.get("name") != expected:
        return call0, f"forced {expected} phase returned {fn.get('name')!r}"
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError as exc:
        return call0, f"unparseable arguments: {exc}"
    if not isinstance(args, dict):
        return call0, f"arguments are {type(args).__name__}, not an object"
    return (call0, args), None


def run_trial(endpoint, task, seed, schemas, frontmatter_guards=False):
    with open(os.path.join(ROOT, task["fixture"]), newline="") as fh:
        before = fh.read()
    doc = before
    payload, read_name, edit_name = treatment_payload(task, seed, schemas)
    executed = []
    emitted = []
    turns = []
    total_tokens = 0
    total_elapsed = 0.0
    model = None
    finish = None
    phase_error = None
    host_preconditions = None

    if read_name:
        response, row = _sample(endpoint, payload)
        model = response.get("model")
        finish = row.get("finish_reason")
        total_tokens += row.get("completion_tokens") or 0
        total_elapsed += row.get("elapsed_s") or 0
        turns.append({key: row.get(key) for key in
                      ("content", "tool_calls", "finish_reason",
                       "completion_tokens", "elapsed_s")})
        emitted += row.get("tool_calls") or []
        parsed, phase_error = _parse_call(row, read_name)
        if phase_error:
            executed += (row.get("tool_calls") or [])[:1]
        else:
            call0, args = parsed
            executed.append(call0)
            _got, text, read_error = armb.read_call(doc, read_name, args)
            if read_error:
                phase_error = read_error
            else:
                payload["messages"].append(_assistant_message(row))
                payload["messages"].append({
                    "role": "tool", "tool_call_id": call0.get("id"),
                    "content": text,
                })

    if phase_error is None:
        payload["tools"] = [{"type": "function", "function": schemas[edit_name]}]
        payload["tool_choice"] = forced(edit_name)
        response, row = _sample(endpoint, payload)
        model = response.get("model")
        finish = row.get("finish_reason")
        total_tokens += row.get("completion_tokens") or 0
        total_elapsed += row.get("elapsed_s") or 0
        turns.append({key: row.get(key) for key in
                      ("content", "tool_calls", "finish_reason",
                       "completion_tokens", "elapsed_s")})
        emitted += row.get("tool_calls") or []
        parsed, phase_error = _parse_call(row, edit_name)
        if parsed is not None:
            call0 = parsed[0] if isinstance(parsed, tuple) else parsed
            executed.append(call0)
        if phase_error is None:
            call0, args = parsed
            op, op_args = armb.normalize(edit_name, args)
            if frontmatter_guards and op == "frontmatter-set":
                host_preconditions = frontmatter_precondition(task)
                op_args = dict(op_args)
                op_args.update(host_preconditions)
            after, edit_error = apply_op(doc, op, op_args)
            if edit_error:
                phase_error = edit_error
            else:
                doc = after
                # Terminal success: the changed/no-op result is never sampled.

    return {
        "model": model,
        "finish_reason": finish,
        "elapsed_s": round(total_elapsed, 2),
        "completion_tokens": total_tokens,
        "tool_calls": executed,
        "emitted_tool_calls": emitted,
        "turns": turns,
        "n_turns": len(turns),
        "result_shape": "terminal-success",
        "max_turns": 2 if read_name else 1,
        "phase_error": phase_error,
        "document_changed": doc != before,
        "host_preconditions": host_preconditions,
    }


def load_tasks(family):
    path = os.path.join(ROOT, "bench", "tasks", TASK_FILE[family])
    with open(path) as fh:
        tasks = json.load(fh)["tasks"]
    return path, [task for task in tasks if task["id"] in PRIMARY[family]]


def scheme_name(args):
    if args.section_children:
        return "minicpm_section_children"
    if args.frontmatter_guards:
        return "minicpm_routed_guarded"
    return "minicpm_routed"


def run(args):
    _path, tasks = load_tasks(args.family)
    if args.task:
        wanted = set(args.task)
        tasks = [task for task in tasks if task["id"] in wanted]
        missing = wanted - {task["id"] for task in tasks}
        if missing:
            raise RuntimeError(f"unknown or non-primary task ids: {sorted(missing)}")
    schemas = load_schemas(args.binary, section_children=args.section_children)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    done = set()
    if os.path.exists(args.out):
        for row in read_last(args.out).values():
            if row.get("error") is None:
                done.add((row["task_id"], row["trial"]))
    work = [(task, trial) for task in tasks for trial in range(args.trials)
            if (task["id"], trial) not in done]
    scheme = scheme_name(args)
    print(f"{len(work)} trials to run, family={args.family}, scheme={scheme}")
    started = time.time()
    with open(args.out, "a") as fh:
        for index, (task, trial) in enumerate(work, 1):
            try:
                row = run_trial(
                    args.endpoint, task, trial, schemas,
                    frontmatter_guards=args.frontmatter_guards)
                row.update(task_id=task["id"], scheme=scheme,
                           trial=trial, error=None)
            except Exception as exc:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "scheme": scheme,
                    "trial": trial, "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60 if index else 0
            print(
                f"[{index:3d}/{len(work)}] {task['id']:26s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s "
                f"tok={row.get('completion_tokens') or 0:5d} "
                f"{'ERR ' + row['error'][:40] if row.get('error') else ''} "
                f"eta {eta:.0f}m",
                flush=True,
            )


def read_last(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def grade(args):
    task_path, tasks = load_tasks(args.family)
    if args.task:
        wanted = set(args.task)
        tasks = [task for task in tasks if task["id"] in wanted]
    task_by_id = {task["id"]: task for task in tasks}
    outcomes = Counter()
    rows = read_last(args.out)
    with open(args.graded, "w") as out:
        for key in sorted(rows):
            row = rows[key]
            task = task_by_id.get(row["task_id"])
            if task is None:
                continue
            trial = copy.deepcopy(row)
            guard = row.get("host_preconditions")
            if guard:
                mutation_calls = [
                    call for call in trial.get("tool_calls") or []
                    if call.get("function", {}).get("name") not in armb.READS
                ]
                if len(mutation_calls) != 1:
                    raise RuntimeError(
                        f"{row['task_id']} trial {row['trial']} has "
                        f"{len(mutation_calls)} guarded mutation calls")
                fn = mutation_calls[0]["function"]
                call_args = json.loads(fn.get("arguments") or "{}")
                call_args.update(guard)
                fn["arguments"] = json.dumps(call_args, separators=(",", ":"))
            outcome, detail = armb.grade_one(task, trial)
            outcomes[outcome] += 1
            out.write(json.dumps({
                "task_id": row["task_id"], "scheme": row.get("scheme", "minicpm_routed"),
                "trial": row["trial"], "outcome": outcome, "detail": detail,
            }) + "\n")
    total = sum(outcomes.values())
    print(f"{args.family}: {total} trials")
    for outcome, count in outcomes.most_common():
        print(f"  {outcome:24s} {count:3d}  {100 * count / total:5.1f}%")
    print(f"wrote {args.graded}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    parser.add_argument("--family", required=True, choices=tuple(PRIMARY))
    parser.add_argument("--binary", default=os.path.join(ROOT, "target", "debug", "incise"))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graded", required=True)
    parser.add_argument("--grade", action="store_true")
    parser.add_argument(
        "--frontmatter-guards", action="store_true",
        help="add host-owned must_absent/must_exist to routed frontmatter writes",
    )
    parser.add_argument(
        "--section-children", action="store_true",
        help="expose atomic structured children on the routed section-insert tool",
    )
    parser.add_argument(
        "--task", action="append",
        help="run only this primary task id; repeat to select several",
    )
    args = parser.parse_args()
    if args.grade:
        grade(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
