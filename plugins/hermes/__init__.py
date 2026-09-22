"""incise for Hermes: byte-preserving markdown edits behind eight tools.

Five of these tools are measured artifacts. `table_edit`, `list_edit`,
`section_edit`, `frontmatter_edit` and `table_get` are the schemes that won
their comparisons in `bench/FINDINGS.md` -- a local small model editing Markdown
directly completed 60% of table tasks and 19% of section tasks, with direct
section edits losing content in 28% of trials. Driving the adopted Incise table
interface, it completed 60/60 tasks with nothing lost. The schemas are fetched from `incise
schema` at registration so there is one copy of that text in the tree and
`bench/schematest.py` is watching it.

`table_get` is a read and is handled as one: `schema_cache.READ_SUBCOMMAND`
routes it to `_handle_view` and `safety.check_read`, never to the write guard.
It replaced a hand-written `md_rows` that published the same op behind a plain
string `table` -- see `schema_cache` for what that spelling could not address.

The other three -- `md_tables`, `md_lists`, `md_outline` -- are reads written
here rather than measured. One tool per renderer, with no discriminator between
them: see the comment above `MD_TABLES` in `schema_cache.py` for the live call
that bought that shape.

This module is a translator and nothing else. It maps a tool name and an
`action` to an op name, hands the argument object to the binary unchanged, and
turns an exit code into a tool result. It parses no markdown and validates no
argument -- see `normalize`, `_handle_edit` and `_handle_view` for why all
three are deliberate.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple

from . import runner, safety, schema_cache

try:
    from tools.registry import tool_error, tool_result
except Exception:  # pragma: no cover - only when the host layout moves
    def tool_error(message, **extra) -> str:
        return json.dumps({"error": str(message), **extra})

    def tool_result(data=None, **kwargs) -> str:
        return json.dumps(data if data is not None else kwargs)


logger = logging.getLogger(__name__)

TOOLSET = "incise"

_PATH_LOCKS: Dict[str, threading.Lock] = {}
_PATH_LOCK_USERS: Dict[str, int] = {}
_PATH_LOCKS_GUARD = threading.Lock()

EMOJI = {
    "table_edit": "📊",
    "list_edit": "☑️",
    "section_edit": "📝",
    "frontmatter_edit": "🏷️",
    "md_tables": "🔎",
    "md_lists": "🔎",
    "md_outline": "🔎",
    "table_get": "🔎",
    "list_get": "🔎",
    "frontmatter_get": "🔎",
    "table_add_row": "📊",
    "table_update_cell": "📊",
    "list_add_item": "☑️",
    "section_insert": "📝",
    "section_append": "📝",
    "frontmatter_set": "🏷️",
}


@contextmanager
def _serialize_write(path: str):
    """Serialize Incise writes to one real path inside this Hermes process.

    Hermes may run sibling agents concurrently. Each Incise subprocess performs
    a complete read-modify-write, so overlapping calls must not both read the
    same old bytes and let the last rename win. Different paths retain their
    concurrency.
    """
    resolved = os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.setdefault(resolved, threading.Lock())
        _PATH_LOCK_USERS[resolved] = _PATH_LOCK_USERS.get(resolved, 0) + 1
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _PATH_LOCKS_GUARD:
            users = _PATH_LOCK_USERS[resolved] - 1
            if users:
                _PATH_LOCK_USERS[resolved] = users
            else:
                _PATH_LOCK_USERS.pop(resolved, None)
                _PATH_LOCKS.pop(resolved, None)


def normalize(name: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Tool call -> (op name, argument object), exactly as the benchmark did.

    This is a transcription of `armb.normalize` (bench/armb.py:1328-1364). The
    5674 graded calls behind every rate in FINDINGS.md went through that
    function, so a call arriving here has to reach the core the same way or the
    numbers describe a different system.

    Three things about it are easy to mistake for tidying-up and are not:

    * **`new_heading` -> `heading` is mandatory.** `section_g_hpath` publishes
      the new name as `new_heading`, and the core reads `["heading", "title",
      "text"]` for section-rename and `["heading", "title"]` for section-insert
      -- `new_heading` is in neither. Without the rename every rename and every
      insert refuses for a heading the model did in fact supply.
    * **The section address's `heading` becomes `path`.** Inside the `section`
      object only; the top-level `path` is the file and is untouched. The core
      accepts both spellings, so dropping this would look like it worked.
    * **A missing or misspelled `action` is passed through**, producing
      `table-None` or `table-updat`, because the core answers that with
      `unknown operation "...". Valid: ...` -- a list of the fifteen real
      names, which is the sentence the model recovers from. Rejecting it here
      would replace a measured refusal with an unmeasured one.

      `armb.normalize` now has the alternative behind `CHECK_ACTION`, default
      off, and it is **deliberately not adopted here**: it has never been run
      in an arm. FINDINGS F-action is why it cannot easily be -- the five
      recorded `list-None` calls are all one seed and are not the documented
      fault at all (the key was `"action=add-item,item"`, so `action` *was*
      sent), and the genuine omissions are in live runs that may not be quoted
      beside an arm number. Adopt it when it wins something, not before.
    """
    if name == "table_edit":
        return "table-" + str(args.get("action")), args
    if name == "list_edit":
        return "list-" + str(args.get("action")), args
    if name == "section_edit":
        args = dict(args)
        if "new_heading" in args:
            args["heading"] = args.pop("new_heading")
        if "file" in args and "path" not in args:
            args["path"] = args.pop("file")
        sec = args.get("section")
        if isinstance(sec, dict) and "heading" in sec and "path" not in sec:
            sec = dict(sec)
            sec["path"] = sec.pop("heading")
            args["section"] = sec
        return "section-" + str(args.get("action")), args
    if name == "frontmatter_edit":
        return "frontmatter-" + str(args.get("action")), args
    narrow = {
        "table_add_row": "table-add-row",
        "table_update_cell": "table-update-cell",
        "list_add_item": "list-add-item",
        "section_append": "section-append",
        "frontmatter_set": "frontmatter-set",
    }
    if name in narrow:
        return narrow[name], args
    if name == "section_insert":
        args = dict(args)
        if "parent" in args:
            args["section"] = args.pop("parent")
        if "new_heading" in args:
            args["heading"] = args.pop("new_heading")
        if "body" in args:
            args["text"] = args.pop("body")
        sec = args.get("section")
        if isinstance(sec, dict) and "heading" in sec and "path" not in sec:
            sec = dict(sec)
            sec["path"] = sec.pop("heading")
            args["section"] = sec
        return "section-insert", args
    raise ValueError(f"not an edit tool: {name}")


def _path_of(args: Dict[str, Any]) -> Optional[str]:
    path = args.get("path") or args.get("file")
    return path if isinstance(path, str) and path.strip() else None


def _handle_edit(name: str, args: Dict[str, Any]) -> str:
    """One edit tool call.

    Nothing is checked here that the core could check itself. The order
    arguments are validated in is part of incise's contract -- a malformed
    `values` outranks a nonexistent table and a malformed `position` does not
    (crates/incise-core/src/ops/dispatch.rs) -- so a front end that rejected an
    argument early would answer the same call with a different sentence, and
    section 5.3 counts that as a behaviour regression rather than as strictness.

    The two things checked are the two the core cannot see: which file to open,
    and whether this process is allowed to open it.
    """
    if not isinstance(args, dict):
        return tool_error(f"{name} expects an object of arguments, got {type(args).__name__}.")

    path = _path_of(args)
    if not path:
        return tool_error(
            f"{name} needs `path`: the markdown file to edit. Give the path you "
            "read the document from."
        )

    denied = safety.check_write(path)
    if denied:
        return tool_error(denied)

    op, normalized = normalize(name, args)
    with _serialize_write(path):
        code, payload, _ = runner.invoke([op, path, "--args", json.dumps(normalized)])

    if code == runner.EXIT_OK:
        return tool_result(
            description=payload.get("description", ""),
            hash=payload.get("hash", ""),
            changed=bool(payload.get("changed", True)),
            path=payload.get("path", path),
        )

    # Every other exit is an error, and the message is reproduced word for word.
    # Section 5.3 makes the refusal the product: Arm B measured 75% one-turn
    # recovery against these exact sentences -- the near matches, the column
    # list, the named next action. Nothing is prepended, appended or reworded.
    message = payload.get("error") or f"incise exited {code} with nothing to say."
    if code == runner.EXIT_STALE:
        return tool_error(message, stale=True)
    if code == runner.EXIT_USAGE:
        return tool_error(message, usage=True)
    extra = {"repair": payload["repair"]} if isinstance(payload.get("repair"), dict) else {}
    return tool_error(message, **extra)


# The read subcommands, by tool name. One tool per renderer -- see the comment
# above `MD_TABLES` in schema_cache.py for the call that cost.
_VIEWS = schema_cache.READ_SUBCOMMAND


def _handle_view(name: str, args: Dict[str, Any]) -> str:
    """One read tool call.

    `table_get` is the only read that takes arguments, and they go to the binary
    as `--args <json>`, unread. That is the same door `_handle_edit` uses and it
    is deliberate for the same reason, stated at `rows_subcommand` in
    `crates/incise-cli/src/main.rs`: a front end translating an argument object
    into per-key flags is "measuring its own translation rather than incise's
    answer".

    This function used to do that translation, for `md_rows`. It pulled `table`
    out as a string and each `filter` entry out as `COLUMN=VALUE`, which meant
    no ordinal could be spelled and a table sharing its heading with another was
    unreachable -- and it answered a missing `table` itself, with a shorter
    sentence than the core's, which names every candidate table in the file.
    F-rows is what that cost. Nothing here reads an argument now.
    """
    if not isinstance(args, dict):
        return tool_error(f"{name} expects an object of arguments, got {type(args).__name__}.")

    path = _path_of(args)
    if not path:
        return tool_error(f"{name} needs `path`: the markdown file to read.")

    blocked = safety.check_read(path)
    if blocked:
        return tool_error(blocked)

    argv = [_VIEWS[name], path]
    if name in {"table_get", "list_get", "frontmatter_get"}:
        argv += ["--args", json.dumps(args)]

    code, payload, _ = runner.invoke(argv)
    if code != runner.EXIT_OK:
        message = payload.get("error") or f"incise exited {code} with nothing to say."
        extra = {"repair": payload["repair"]} if isinstance(payload.get("repair"), dict) else {}
        return tool_error(message, **extra)

    # The renderer's string, untouched. `render_table_list` is not a convenience
    # view -- it *is* the Arm B prompt (section 11, Tier 2), and every rate
    # measured against it was measured against these bytes. The content hash
    # section 5.5 asks for goes beside it in its own field, never inside it.
    result = {
        "text": payload.get("text", ""),
        "hash": payload.get("hash", ""),
        "path": path,
    }
    for field in ("rows", "list", "frontmatter"):
        if field in payload:
            result[field] = payload[field]
    return tool_result(**result)


def _make_edit_handler(name: str):
    def handler(args: Dict[str, Any], **_kw) -> str:
        return _handle_edit(name, args)

    handler.__name__ = f"incise_{name}"
    return handler


def _make_view_handler(name: str):
    def handler(args: Dict[str, Any], **_kw) -> str:
        return _handle_view(name, args)

    handler.__name__ = f"incise_{name}"
    return handler


def _check() -> bool:
    """`check_fn`: True when the tool can actually run.

    The polarity is the host's, not this plugin's: `tools/registry.py` does
    `value = bool(fn())` and hides the tool from the model when it is falsy.
    `runner.available()` answers the opposite question -- None when usable, the
    reason otherwise -- because that is what a log line wants. Returning it
    directly would hide every tool exactly when they work.
    """
    return runner.binary() is not None


def register(ctx) -> None:
    schemas = schema_cache.edit_tools()
    if not schemas:
        # No vendored fallback on purpose: the tools cannot run without the
        # binary either way, and a second copy of the measured schema text is a
        # thing that can drift with nothing watching it. Say what is wrong and
        # register nothing.
        logger.error(
            "incise plugin: no usable `incise` binary, so no tools were "
            "registered. %s",
            runner.available() or "`incise schema` did not return a tool list.",
        )
        return

    for schema in schemas + schema_cache.structural_tools():
        name = schema["name"]
        is_read = name in schema_cache.READ_SUBCOMMAND
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=_make_view_handler(name) if is_read else _make_edit_handler(name),
            check_fn=_check,
            description=schema.get("description", ""),
            emoji=EMOJI.get(name, "📄"),
        )
