#!/usr/bin/env python3
"""MiniCPM list-get followed by a required exact-after micro-schema."""

import argparse
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import minicpm_routed as routed  # noqa: E402
import minicpm_section_pipeline as provenance  # noqa: E402
from incise_ops import apply_op  # noqa: E402
from runner import call, record  # noqa: E402


TASK_IDS = {"add-item-nested-asterisk", "add-item-ordered-renumber"}
SCHEME = "minicpm_list_required_after"
BETWEEN_SCHEME = "minicpm_list_between"
TASK_SOURCE = os.path.join(ROOT, "bench", "tasks", "lists.json")


def tasks():
    _path, selected = routed.load_tasks("lists")
    return [task for task in selected if task["id"] in TASK_IDS]


def exact_item_texts(report):
    texts = []
    for item in report.get("items") or []:
        text = item.get("text")
        if isinstance(text, str) and text not in texts:
            texts.append(text)
    return texts


def edit_schema(item_texts):
    return {
        "name": "list_insert_after",
        "description": (
            "Supply the new item text and choose the exact existing item after "
            "which it belongs. The host already knows the file and list."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text of the new list item.",
                },
                "after": {
                    "type": "string",
                    "description": (
                        "Existing item after which the new item belongs. Copy "
                        "one exact item text from this enum, not its index."
                    ),
                    "enum": list(item_texts),
                },
            },
            "required": ["text", "after"],
        },
    }


def between_schema(item_texts):
    boundary = {
        "type": "string",
        "enum": list(item_texts),
    }
    return {
        "name": "list_insert_between",
        "description": (
            "Supply the new item and both existing boundary items named by "
            "the request. Copy the boundaries in request order. The host "
            "already knows the file and list."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string", "description": "Text of the new list item.",
                },
                "after": dict(boundary, description=(
                    "First named boundary: the existing item the new item follows.")),
                "before": dict(boundary, description=(
                    "Second named boundary: the existing item the new item precedes.")),
            },
            "required": ["text", "after", "before"],
        },
    }


def compose(task, read_args, content, allowed_after):
    if read_args.get("path") != task["fixture"]:
        return None, (
            f"list_get addressed file {read_args.get('path')!r}, not "
            f"{task['fixture']!r}; no edit was executed."
        )
    if not isinstance(read_args.get("list"), dict):
        return None, "list_get did not supply a list address; no edit was executed."
    text = content.get("text")
    after = content.get("after")
    if not isinstance(text, str):
        return None, "`text` must be a string; no edit was executed."
    if not isinstance(after, str) or after not in allowed_after:
        return None, (
            "`after` must be one exact item returned by list_get; "
            "no edit was executed."
        )
    args = {
        "path": read_args["path"],
        "list": read_args["list"],
        "text": text,
        "after": after,
    }
    return {
        "type": "function",
        "function": {
            "name": "list_add_item",
            "arguments": json.dumps(args, separators=(",", ":")),
        },
    }, None


def compose_between(task, read_args, report, content, allowed_items):
    if read_args.get("path") != task["fixture"]:
        return None, False, (
            f"list_get addressed file {read_args.get('path')!r}, not "
            f"{task['fixture']!r}; no edit was executed."
        )
    if not isinstance(read_args.get("list"), dict):
        return None, False, (
            "list_get did not supply a list address; no edit was executed.")
    text = content.get("text")
    after = content.get("after")
    before = content.get("before")
    if not isinstance(text, str):
        return None, False, "`text` must be a string; no edit was executed."
    if (not isinstance(after, str) or after not in allowed_items
            or not isinstance(before, str) or before not in allowed_items):
        return None, False, (
            "both boundaries must be exact items returned by list_get; "
            "no edit was executed."
        )
    items = report.get("items") or []
    after_hits = [i for i, item in enumerate(items) if item.get("text") == after]
    before_hits = [i for i, item in enumerate(items) if item.get("text") == before]
    if len(after_hits) != 1 or len(before_hits) != 1:
        return None, False, (
            "both boundaries must identify one returned item; no edit was executed.")
    left, right = after_hits[0], before_hits[0]
    if right != left + 1:
        return None, False, (
            "the selected boundaries are not adjacent and ordered; "
            "no edit was executed."
        )
    if (items[left].get("depth") != items[right].get("depth")
            or items[left].get("parent") != items[right].get("parent")):
        return None, False, (
            "the selected boundaries are not structural siblings; "
            "no edit was executed."
        )
    call, error = compose(task, read_args, {
        "text": text, "after": after,
    }, allowed_items)
    return call, error is None, error


def sample(endpoint, payload):
    response, elapsed = call(endpoint, payload)
    return response, record(response, elapsed)


def run_trial(endpoint, task, seed, list_get_schema, between=False):
    fixture = os.path.join(ROOT, task["fixture"])
    with open(fixture, newline="") as fh:
        before = fh.read()
    doc = before
    payload = armb.build_payload(task, "compose_5", seed)
    payload["tools"] = [{"type": "function", "function": list_get_schema}]
    payload["tool_choice"] = routed.forced("list_get")

    response, read_sample = sample(endpoint, payload)
    model = response.get("model")
    read_calls = read_sample.get("tool_calls") or []
    emitted = list(read_calls)
    turns = [read_sample]
    parsed, phase_error = routed._parse_call(read_sample, "list_get")
    read_call = read_calls[0] if read_calls else None
    read_args = parsed[1] if parsed is not None else None
    read_report = None
    rendered = None
    allowed_after = []
    schema = None
    content_sample = None
    content_call = None
    content = None
    composed = None
    execution_error = None
    boundaries_validated = None

    if phase_error is None:
        read_report, rendered, phase_error = armb.read_call(
            doc, "list_get", read_args)
    if phase_error is None:
        allowed_after = exact_item_texts(read_report)
        if not allowed_after:
            phase_error = "list_get returned no exact item texts"
    if phase_error is None:
        schema = (between_schema(allowed_after) if between
                  else edit_schema(allowed_after))
        payload["messages"].append(routed._assistant_message(read_sample))
        payload["messages"].append({
            "role": "tool", "tool_call_id": read_call.get("id"),
            "content": rendered,
        })
        payload["tools"] = [{"type": "function", "function": schema}]
        payload["tool_choice"] = routed.forced(schema["name"])
        response, content_sample = sample(endpoint, payload)
        model = response.get("model")
        turns.append(content_sample)
        content_calls = content_sample.get("tool_calls") or []
        emitted.extend(content_calls)
        content_call = content_calls[0] if content_calls else None
        parsed_content, phase_error = routed._parse_call(
            content_sample, schema["name"])
        if phase_error is None:
            _call, content = parsed_content
            if between:
                composed, boundaries_validated, phase_error = compose_between(
                    task, read_args, read_report, content, allowed_after)
            else:
                composed, phase_error = compose(
                    task, read_args, content, allowed_after)

    if composed is not None:
        fn = composed["function"]
        args = json.loads(fn["arguments"])
        op, op_args = armb.normalize(fn["name"], args)
        after, execution_error = apply_op(doc, op, op_args)
        if execution_error:
            phase_error = execution_error
        else:
            doc = after

    read_tokens = read_sample.get("completion_tokens") or 0
    edit_tokens = ((content_sample or {}).get("completion_tokens") or 0)
    read_elapsed = read_sample.get("elapsed_s") or 0
    edit_elapsed = ((content_sample or {}).get("elapsed_s") or 0)
    executed = ([read_call] if read_call is not None else [])
    if composed is not None:
        executed.append(composed)
    return {
        "model": model,
        "finish_reason": (
            (content_sample or read_sample).get("finish_reason")),
        "elapsed_s": round(read_elapsed + edit_elapsed, 2),
        "completion_tokens": read_tokens + edit_tokens,
        "read_elapsed_s": read_elapsed,
        "edit_elapsed_s": edit_elapsed,
        "read_completion_tokens": read_tokens,
        "edit_completion_tokens": edit_tokens,
        "read_call": read_call,
        "content_call": content_call,
        "read_report": read_report,
        "allowed_after": allowed_after,
        "content": content,
        "tool_calls": executed,
        "emitted_tool_calls": emitted,
        "composed_operation": composed,
        "turns": turns,
        "phase_error": phase_error,
        "execution_error": execution_error,
        "document_changed": doc != before,
        "after_from_read": (
            composed is None or content.get("after") in allowed_after),
        "boundaries_validated": boundaries_validated,
        "n_turns": len(turns),
        "max_turns": 2,
        "result_shape": "terminal-success",
        "fixture_sha256": provenance.sha256_bytes(before.encode()),
        "task_source_sha256": provenance.sha256_file(TASK_SOURCE),
        "harness_sha256": provenance.sha256_file(__file__),
        "list_get_schema_sha256": provenance.canonical_hash(list_get_schema),
        "edit_schema_sha256": (
            provenance.canonical_hash(schema) if schema is not None else None),
    }


def read_last(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            rows[(row["task_id"], row["trial"])] = row
    return rows


def run(args):
    schemas = routed.load_schemas(args.binary)
    list_get_schema = schemas["list_get"]
    done = {
        key for key, row in read_last(args.out).items()
        if row.get("error") is None
    }
    selected = tasks()
    if args.between:
        selected = [
            task for task in selected
            if task["id"] == "add-item-ordered-renumber"]
    work = [
        (task, trial) for task in selected for trial in range(args.trials)
        if (task["id"], trial) not in done
    ]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    scheme = BETWEEN_SCHEME if args.between else SCHEME
    print(f"{len(work)} trials to run, scheme={scheme}")
    started = time.time()
    with open(args.out, "a") as fh:
        for index, (task, trial) in enumerate(work, 1):
            try:
                row = run_trial(
                    args.endpoint, task, trial, list_get_schema, args.between)
                row.update(task_id=task["id"], trial=trial, scheme=scheme, error=None)
            except Exception as exc:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "trial": trial, "scheme": scheme,
                    "error": f"{type(exc).__name__}: {exc}", "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60
            print(
                f"[{index}/{len(work)}] {task['id']:27s} t{trial} "
                f"{row.get('elapsed_s') or 0:5.1f}s "
                f"tok={row.get('completion_tokens') or 0:4d} eta {eta:.0f}m",
                flush=True,
            )


def grade(args):
    by_id = {task["id"]: task for task in tasks()}
    outcomes = Counter()
    with open(args.graded, "w") as out:
        for _key, row in sorted(read_last(args.out).items()):
            task = by_id[row["task_id"]]
            mutations = [
                call for call in row.get("tool_calls") or []
                if call.get("function", {}).get("name") not in armb.READS
            ]
            if row.get("error"):
                outcome, detail = armb.grade_one(task, row)
            elif not mutations and row.get("phase_error"):
                outcome, detail = "op_error", row["phase_error"]
            else:
                outcome, detail = armb.grade_one(task, row)
            outcomes[outcome] += 1
            out.write(json.dumps({
                "task_id": row["task_id"], "trial": row["trial"],
                "scheme": row.get("scheme", SCHEME), "outcome": outcome,
                "detail": detail, "after_from_read": row.get("after_from_read"),
                "boundaries_validated": row.get("boundaries_validated"),
            }) + "\n")
    print(dict(outcomes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    parser.add_argument(
        "--binary", default=os.path.join(ROOT, "target", "debug", "incise"))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graded", required=True)
    parser.add_argument("--grade", action="store_true")
    parser.add_argument(
        "--between", action="store_true",
        help="use the required adjacent-boundaries treatment",
    )
    args = parser.parse_args()
    (grade if args.grade else run)(args)


if __name__ == "__main__":
    main()
