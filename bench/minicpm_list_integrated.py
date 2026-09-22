#!/usr/bin/env python3
"""Integrated MiniCPM structured-address and request-routed list pipeline."""

import argparse
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import minicpm_list_handle as address  # noqa: E402
import minicpm_list_required_after as placement  # noqa: E402
import minicpm_routed as routed  # noqa: E402
import minicpm_section_pipeline as provenance  # noqa: E402
from incise_ops import apply_op  # noqa: E402
from runner import call, record  # noqa: E402


SCHEME = "minicpm_list_integrated"
EXPECTED_ROUTE = {
    "add-item-tight-dash": "append",
    "add-item-nested-asterisk": "after",
    "add-item-loose": "append",
    "add-item-ordered-renumber": "between",
    "add-item-ordered-all-ones": "append",
    "add-item-paren-delimiter": "append",
    "add-item-mixed-markers": "append",
}


def tasks():
    _path, selected = routed.load_tasks("lists")
    return selected


def route_instruction(instruction):
    normalized = f" {instruction.lower()} "
    if " insert " in normalized and " between " in normalized:
        return "between"
    if " immediately after " in normalized:
        return "after"
    return "append"


def schema_for(route, item_texts):
    if route == "append":
        return address.append_schema()
    if route == "after":
        return placement.edit_schema(item_texts)
    if route == "between":
        return placement.between_schema(item_texts)
    raise ValueError(f"unknown list route: {route}")


def sample(endpoint, payload):
    response, elapsed = call(endpoint, payload)
    return response, record(response, elapsed)


def run_trial(endpoint, task, seed):
    fixture = os.path.join(ROOT, task["fixture"])
    with open(fixture, newline="") as fh:
        before = fh.read()
    doc = before
    options = address.handles(before)
    expected_entry = options[task["target_list"]][1]
    expected_address = {
        "heading": expected_entry["heading"], "ordinal": expected_entry["ordinal"]}
    selection_schema = address.address_schema(options)
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
    selected_address = None
    selected_entry = None
    if phase_error is None:
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
                phase_error = "the selected heading and ordinal are not one actual list"
            else:
                selected_entry = matches[0]

    read_report = None
    rendered = None
    item_texts = []
    read_args = None
    if phase_error is None:
        read_args = {"path": task["fixture"], "list": selected_address}
        read_report, rendered, phase_error = armb.read_call(
            doc, "list_get", read_args)
    if phase_error is None:
        item_texts = placement.exact_item_texts(read_report)

    host_route = route_instruction(task["instruction"])
    expected_route = EXPECTED_ROUTE[task["id"]]
    content_schema = None
    content_sample = None
    content_call = None
    content = None
    composed = None
    anchor_validation = None
    execution_error = None
    if phase_error is None:
        content_schema = schema_for(host_route, item_texts)
        payload["messages"].append(routed._assistant_message(selection))
        payload["messages"].append({
            "role": "tool", "tool_call_id": selection_call.get("id"),
            "content": rendered,
        })
        payload["tools"] = [{"type": "function", "function": content_schema}]
        payload["tool_choice"] = routed.forced(content_schema["name"])
        response, content_sample = sample(endpoint, payload)
        model = response.get("model")
        turns.append(content_sample)
        content_calls = content_sample.get("tool_calls") or []
        emitted.extend(content_calls)
        content_call = content_calls[0] if content_calls else None
        parsed_content, phase_error = routed._parse_call(
            content_sample, content_schema["name"])
        if phase_error is None:
            _call, content = parsed_content
            if host_route == "append":
                composed, phase_error = address.compose(task, selected_entry, content)
                anchor_validation = phase_error is None
            elif host_route == "after":
                composed, phase_error = placement.compose(
                    task, read_args, content, item_texts)
                anchor_validation = phase_error is None
            else:
                composed, anchor_validation, phase_error = placement.compose_between(
                    task, read_args, read_report, content, item_texts)

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
        "expected_address": expected_address,
        "selected_address": selected_address,
        "address_correct": selected_address == expected_address,
        "selected_entry": selected_entry,
        "read_report": read_report,
        "item_texts": item_texts,
        "expected_route": expected_route,
        "host_route": host_route,
        "route_correct": host_route == expected_route,
        "content": content,
        "anchor_validation": anchor_validation,
        "tool_calls": [composed] if composed is not None else [],
        "emitted_tool_calls": emitted,
        "composed_operation": composed,
        "turns": turns,
        "phase_error": phase_error,
        "execution_error": execution_error,
        "document_changed": doc != before,
        "structure_validated": (
            composed is None or (selected_entry in [e for _h, e in options]
                                 and anchor_validation is True)),
        "n_turns": len(turns),
        "max_turns": 2,
        "result_shape": "terminal-success",
        "fixture_sha256": provenance.sha256_bytes(before.encode()),
        "harness_sha256": provenance.sha256_file(__file__),
        "selection_schema_sha256": provenance.canonical_hash(selection_schema),
        "content_schema_sha256": (
            provenance.canonical_hash(content_schema)
            if content_schema is not None else None),
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
    print(f"{len(work)} trials to run, scheme={SCHEME}")
    started = time.time()
    with open(args.out, "a") as fh:
        for index, (task, trial) in enumerate(work, 1):
            try:
                row = run_trial(args.endpoint, task, trial)
                row.update(task_id=task["id"], trial=trial, scheme=SCHEME, error=None)
            except Exception as exc:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "trial": trial, "scheme": SCHEME,
                    "error": f"{type(exc).__name__}: {exc}", "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            elapsed = time.time() - started
            eta = elapsed / index * (len(work) - index) / 60
            print(
                f"[{index:2d}/{len(work)}] {task['id']:27s} t{trial} "
                f"address={'yes' if row.get('address_correct') else 'no ':3s} "
                f"{row.get('host_route') or '-':7s} eta {eta:.0f}m",
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
                "detail": detail, "address_correct": row.get("address_correct"),
                "host_route": row.get("host_route"),
                "route_correct": row.get("route_correct"),
                "structure_validated": row.get("structure_validated"),
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
    args = parser.parse_args()
    (grade if args.grade else run)(args)


if __name__ == "__main__":
    main()
