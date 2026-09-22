#!/usr/bin/env python3
"""MiniCPM dynamic exact-handle list selection and content-only append arm."""

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
from incise_ops import apply_op, list_lists  # noqa: E402
from runner import call, record  # noqa: E402


TASK_IDS = {"add-item-loose", "add-item-mixed-markers"}
SCHEME = "minicpm_list_handle"
ADDRESS_SCHEME = "minicpm_list_address"


def tasks():
    _path, selected = routed.load_tasks("lists")
    return [task for task in selected if task["id"] in TASK_IDS]


def handle_for(entry):
    spacing = "loose" if entry["loose"] else "tight"
    return (
        f'heading="{entry["heading"]}"; ordinal={entry["ordinal"]}; '
        f'kind={entry["kind"]}; marker="{entry["marker"]}"; '
        f'items={entry["items"]}; levels={entry["levels"]}; spacing={spacing}'
    )


def handles(content):
    return [(handle_for(entry), entry) for entry in list_lists(content)]


def select_schema(options):
    return {
        "name": "list_select",
        "description": (
            "Choose the one existing list matching every constraint in the "
            "request. Copy one complete exact handle from the enum."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "handle": {
                    "type": "string",
                    "description": "Complete exact handle of the target list.",
                    "enum": [handle for handle, _entry in options],
                },
            },
            "required": ["handle"],
        },
    }


def address_schema(options):
    headings = []
    ordinals = []
    for _handle, entry in options:
        if entry["heading"] not in headings:
            headings.append(entry["heading"])
        if entry["ordinal"] not in ordinals:
            ordinals.append(entry["ordinal"])
    return {
        "name": "list_select",
        "description": (
            "Choose the one existing list matching every constraint in the "
            "request. Copy its exact full heading and ordinal from the summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "heading": {
                    "type": "string", "enum": headings,
                    "description": "Exact full heading path of the target list.",
                },
                "ordinal": {
                    "type": "integer", "enum": sorted(ordinals),
                    "description": "Exact ordinal of the target list under that heading.",
                },
            },
            "required": ["heading", "ordinal"],
        },
    }


def append_schema():
    return {
        "name": "list_append_item",
        "description": (
            "Supply the text of the one new item to append. The host already "
            "knows the exact file and list."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "New item text."},
            },
            "required": ["text"],
        },
    }


def compose(task, entry, content):
    text = content.get("text")
    if not isinstance(text, str):
        return None, "`text` must be a string; no edit was executed."
    args = {
        "path": task["fixture"],
        "list": {"heading": entry["heading"], "ordinal": entry["ordinal"]},
        "text": text,
        "position": "end",
    }
    return {
        "type": "function",
        "function": {
            "name": "list_add_item",
            "arguments": json.dumps(args, separators=(",", ":")),
        },
    }, None


def sample(endpoint, payload):
    response, elapsed = call(endpoint, payload)
    return response, record(response, elapsed)


def run_trial(endpoint, task, seed, structured=False):
    fixture = os.path.join(ROOT, task["fixture"])
    with open(fixture, newline="") as fh:
        before = fh.read()
    doc = before
    options = handles(before)
    by_handle = dict(options)
    expected_handle = options[task["target_list"]][0]
    expected_entry = options[task["target_list"]][1]
    expected_address = {
        "heading": expected_entry["heading"], "ordinal": expected_entry["ordinal"]}
    selection_schema = (address_schema(options) if structured
                        else select_schema(options))
    payload = armb.build_payload(task, "compose_5", seed)
    payload["tools"] = [{"type": "function", "function": selection_schema}]
    payload["tool_choice"] = routed.forced("list_select")

    response, selection = sample(endpoint, payload)
    model = response.get("model")
    selection_calls = selection.get("tool_calls") or []
    emitted = list(selection_calls)
    turns = [selection]
    parsed, phase_error = routed._parse_call(selection, "list_select")
    selection_call = selection_calls[0] if selection_calls else None
    selected_handle = (
        parsed[1].get("handle") if parsed is not None and not structured else None)
    selected_address = None
    selected_entry = None
    if phase_error is None:
        if structured:
            heading = parsed[1].get("heading")
            ordinal = parsed[1].get("ordinal")
            if (not isinstance(heading, str) or isinstance(ordinal, bool)
                    or not isinstance(ordinal, int)):
                phase_error = "`heading` and integer `ordinal` are both required"
            else:
                selected_address = {"heading": heading, "ordinal": ordinal}
                matches = [
                    entry for _handle, entry in options
                    if entry["heading"] == heading and entry["ordinal"] == ordinal]
                if len(matches) != 1:
                    phase_error = (
                        "the selected heading and ordinal are not one actual list")
                else:
                    selected_entry = matches[0]
        elif not isinstance(selected_handle, str) or selected_handle not in by_handle:
            phase_error = "`handle` must be one complete exact published handle"
        else:
            selected_entry = by_handle[selected_handle]

    content_sample = None
    content_call = None
    content = None
    composed = None
    execution_error = None
    content_schema = append_schema()
    if phase_error is None:
        payload["messages"].append(routed._assistant_message(selection))
        payload["messages"].append({
            "role": "tool", "tool_call_id": selection_call.get("id"),
            "content": "List handle accepted. Supply the new item text.",
        })
        payload["tools"] = [{"type": "function", "function": content_schema}]
        payload["tool_choice"] = routed.forced("list_append_item")
        response, content_sample = sample(endpoint, payload)
        model = response.get("model")
        turns.append(content_sample)
        content_calls = content_sample.get("tool_calls") or []
        emitted.extend(content_calls)
        content_call = content_calls[0] if content_calls else None
        parsed_content, phase_error = routed._parse_call(
            content_sample, "list_append_item")
        if phase_error is None:
            _call, content = parsed_content
            composed, phase_error = compose(task, selected_entry, content)

    if composed is not None:
        fn = composed["function"]
        args = json.loads(fn["arguments"])
        op, op_args = armb.normalize(fn["name"], args)
        after, execution_error = apply_op(doc, op, op_args)
        if execution_error:
            phase_error = execution_error
        else:
            doc = after

    select_tokens = selection.get("completion_tokens") or 0
    content_tokens = ((content_sample or {}).get("completion_tokens") or 0)
    select_elapsed = selection.get("elapsed_s") or 0
    content_elapsed = ((content_sample or {}).get("elapsed_s") or 0)
    return {
        "model": model,
        "finish_reason": (content_sample or selection).get("finish_reason"),
        "elapsed_s": round(select_elapsed + content_elapsed, 2),
        "completion_tokens": select_tokens + content_tokens,
        "select_completion_tokens": select_tokens,
        "content_completion_tokens": content_tokens,
        "select_elapsed_s": select_elapsed,
        "content_elapsed_s": content_elapsed,
        "selection_call": selection_call,
        "content_call": content_call,
        "handle_enum": [handle for handle, _entry in options],
        "expected_handle": expected_handle,
        "selected_handle": selected_handle,
        "handle_correct": selected_handle == expected_handle,
        "expected_address": expected_address,
        "selected_address": selected_address,
        "address_correct": selected_address == expected_address,
        "selected_entry": selected_entry,
        "content": content,
        "tool_calls": [composed] if composed is not None else [],
        "emitted_tool_calls": emitted,
        "composed_operation": composed,
        "turns": turns,
        "phase_error": phase_error,
        "execution_error": execution_error,
        "document_changed": doc != before,
        "address_from_handle": composed is None or selected_handle in by_handle,
        "address_from_entries": composed is None or selected_entry in [
            entry for _handle, entry in options],
        "n_turns": len(turns),
        "max_turns": 2,
        "result_shape": "terminal-success",
        "fixture_sha256": provenance.sha256_bytes(before.encode()),
        "harness_sha256": provenance.sha256_file(__file__),
        "selection_schema_sha256": provenance.canonical_hash(selection_schema),
        "content_schema_sha256": provenance.canonical_hash(content_schema),
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
    done = {
        key for key, row in read_last(args.out).items()
        if row.get("error") is None
    }
    work = [
        (task, trial) for task in tasks() for trial in range(args.trials)
        if (task["id"], trial) not in done
    ]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    scheme = ADDRESS_SCHEME if args.structured else SCHEME
    print(f"{len(work)} trials to run, scheme={scheme}")
    started = time.time()
    with open(args.out, "a") as fh:
        for index, (task, trial) in enumerate(work, 1):
            try:
                row = run_trial(args.endpoint, task, trial, args.structured)
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
                f"select={'yes' if (row.get('address_correct') if args.structured else row.get('handle_correct')) else 'no ':3s} "
                f"{row.get('elapsed_s') or 0:5.1f}s eta {eta:.0f}m",
                flush=True,
            )


def grade(args):
    by_id = {task["id"]: task for task in tasks()}
    outcomes = Counter()
    with open(args.graded, "w") as out:
        for _key, row in sorted(read_last(args.out).items()):
            task = by_id[row["task_id"]]
            if row.get("error"):
                outcome, detail = armb.grade_one(task, row)
            elif not row.get("tool_calls") and row.get("phase_error"):
                outcome, detail = "op_error", row["phase_error"]
            else:
                outcome, detail = armb.grade_one(task, row)
            outcomes[outcome] += 1
            out.write(json.dumps({
                "task_id": row["task_id"], "trial": row["trial"],
                "scheme": row.get("scheme", SCHEME), "outcome": outcome,
                "detail": detail, "handle_correct": row.get("handle_correct"),
                "address_from_handle": row.get("address_from_handle"),
                "address_correct": row.get("address_correct"),
                "address_from_entries": row.get("address_from_entries"),
            }) + "\n")
    print(dict(outcomes))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--out", required=True)
    parser.add_argument("--graded", required=True)
    parser.add_argument("--grade", action="store_true")
    parser.add_argument(
        "--structured", action="store_true",
        help="require separate heading and ordinal selection fields",
    )
    args = parser.parse_args()
    (grade if args.grade else run)(args)


if __name__ == "__main__":
    main()
