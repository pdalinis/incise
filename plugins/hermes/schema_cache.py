"""The tool schemas, fetched from the binary at registration.

`incise schema` emits its edit tools in exactly the shape `ctx.register_tool`
wants -- a flat `{"name", "description", "parameters"}` -- so there is nothing to
translate.

**There is no vendored copy, and that is a departure from the plan.** The plan
had one as a fallback for a missing binary. It buys nothing: the tools cannot
run without the binary either way, so the fallback's only effect would be to put
a second copy of the measured text in the tree, with nothing asserting the two
still agree. `bench/schematest.py` watches the one copy that exists (against
`bench/armb.py`, where the numbers were measured); a copy here would be outside
what it checks. When the binary is missing the plugin registers nothing and says
why.

The descriptions are not documentation. REQUIREMENTS.md section 6: "Changes to
the description are behavioural changes and belong in the benchmark, not in a
docs commit." B7 moved the table family by rewording one paragraph; L3 moved the
list family from 61% to 91% by renaming one property. Nothing in this file
edits, wraps, truncates or appends to the text it receives.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

from . import runner

# The read tools are this plugin's own, not measured artifacts -- no scheme in
# `bench/armb.py` corresponds to them, because Arm B handed the model its
# structural summary in the user turn rather than behind a tool call. They are
# written here, plainly, and they are the only schemas in this plugin that a
# future measurement is free to rewrite. Their *output* is not free: each is a
# renderer's string byte for byte, and `render_table_list` -- what `md_tables`
# returns -- *is* the Arm B prompt (section 11, Tier 2).
#
# **One tool per renderer, because one tool with a `view` enum lost a call.**
# The first live run of this plugin produced, twice, byte-identically, from the
# same model on the same prompt:
#
#     list_edit {"list": {"heading": "..."}, "path": "...", "view": "lists"}
#
# -- no `action`, and `view` borrowed from the read tool, whose enum contained a
# value naming the list family. `list_edit` requires `path`, `action`, `list`;
# the model filled the third required slot with the wrong key and the call
# refused as `list-None`. That is L3's finding again (renaming `item` to `match`
# moved the list family 61% -> 91% because two near-synonym properties let the
# payload land in the selector), and the same remedy applies: do not put a
# property in the toolset that can be absorbed. An AGENTS.md instruction did not
# and could not fix it -- the model was not disregarding guidance, it was
# mis-binding a parameter.
#
# So there is no discriminator here. Three tools, each taking the path it reads
# and nothing else to confuse with an `action`. The selection work the enum was
# doing moves into the descriptions, which is where B7 and L3 showed it belongs.
#
# Three and not four: the fourth used to be `md_rows`, hand-written here like
# these. It is gone, and `table_get` -- the measured schema, published by the
# binary -- renders `rows` instead. The comment below `MD_LISTS` says what that
# cost and why it was decidable without a run.

_PATH = {
    "type": "string",
    "description": "Path to the markdown file.",
}

MD_OUTLINE: Dict[str, Any] = {
    "name": "md_outline",
    "description": (
        "List the headings of a markdown document as a tree, with the level and "
        "ordinal of each. Returns the structure, not the document text. Call "
        "this to find the heading to address a `section_edit` to, or to see "
        "what a file contains before editing it."
    ),
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH},
        "required": ["path"],
    },
}

MD_TABLES: Dict[str, Any] = {
    "name": "md_tables",
    "description": (
        "List every markdown table in a document: the heading each one sits "
        "under, its column names, and how many rows it has. Returns the "
        "structure, not the document text. Call this before a `table_edit` to "
        "get the exact `table` heading and `column` spellings it needs, and "
        "again if an edit is refused for a table or column that is not there."
    ),
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH},
        "required": ["path"],
    },
}

MD_LISTS: Dict[str, Any] = {
    "name": "md_lists",
    "description": (
        "List every bullet or task list in a markdown document: the heading "
        "each one sits under, how many items it has, and whether they are "
        "checkboxes. Returns the structure, not item text. Call this before a "
        "`list_edit` to get the exact `list` heading; the safe-small profile "
        "provides `list_get` when exact item text is needed."
    ),
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH},
        "required": ["path"],
    },
}

# `md_rows` was the fourth read and it is retired. It published `table` as a
# plain string -- "the heading the table sits under, spelled as `md_tables`
# shows it" -- which reads better beside the three above and cost an address
# the rest of the tree has. `corpus/tables/multiple-per-section.md` holds three
# tables under one heading; every other table tool here takes
# `{"heading": ..., "ordinal": ...}` and `md_rows` took no ordinal at all, so
# all three were unreachable -- the ambiguity is in the heading, so it refuses
# for every table under it. `md_tables` prints those ordinals, and
# `table_get` refuses the bare heading with "Pass an ordinal." -- a refusal
# whose named remedy was absent from the schema that provoked it, which §5.3
# counts as the worst kind.
#
# That was decidable without a run and it was decided that way: `table_read_g`
# answers `get-ordinal-table` 10/10, `md_rows` cannot answer it at any
# temperature, and McNemar on b=10 is p <= 0.0386 even if `md_rows` wins both
# of `table_read_g`'s only two failures. See FINDINGS F-rows.
#
# `table_get` also arrives with a copy-paste wart -- a `table` that says "Which
# table to edit", in a read. It ships anyway and byte-for-byte: rewording
# measured schema text is a behaviour change with no number behind it, and the
# open item for it is in FINDINGS, not in this diff.

# Registration order. `md_tables` leads because it is the one a table edit needs
# and tables are the family with the largest measured gap to close. `table_get`
# is not in this list -- it comes from `incise schema` with the edit tools, and
# `READ_SUBCOMMAND` is what routes it to `_handle_view` rather than its origin.
READ_TOOLS: List[Dict[str, Any]] = [MD_TABLES, MD_LISTS, MD_OUTLINE]

# The CLI subcommand each read tool renders, by tool name. Membership here is
# also the read/write routing decision in `register`, so a published tool named
# here is handled as a read and never reaches `safety.check_write`.
READ_SUBCOMMAND: Dict[str, str] = {
    "md_outline": "outline",
    "md_tables": "tables",
    "md_lists": "lists",
    "table_get": "rows",
    "list_get": "items",
    "frontmatter_get": "keys",
}

_CACHE: Optional[List[Dict[str, Any]]] = None

# Every tool `incise schema` publishes is registered. The set is kept -- rather
# than the filter being deleted -- because it is the thing `test_plugin.py`
# asserts in both directions, and an empty set is a claim that has to stay true
# under test rather than an absence nothing would notice.
#
# It held `table_get` until F-rows. The reasoning then was that `md_rows` was
# already that op and registering both would publish one op under two argument
# spellings; that part was right, and the wrong one was retired. The other
# reason given -- that `table_get` would be routed to `_handle_edit` and ask
# `safety.check_write` for permission to run a read -- was a property of the
# routing, not of the tool, and `READ_SUBCOMMAND` now decides it.
NOT_REGISTERED: set = set()


def edit_tools() -> List[Dict[str, Any]]:
    """The measured schemas, straight from `incise schema`.

    Every published tool, edits and reads alike; `NOT_REGISTERED` is empty and
    the name is now the historical one. Which handler a tool gets is decided by
    `READ_SUBCOMMAND` in `register`, not by which list it arrived in.

    Empty when the binary cannot be reached or does not answer with a JSON
    array -- the caller registers nothing in that case rather than guessing.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    exe = runner.binary()
    if not exe:
        return []

    # Not `runner.invoke`: `schema` takes no path and appending `--json` to it
    # would be a second spelling of a thing that is already JSON.
    profile = os.environ.get("INCISE_PROFILE", "measured")
    if profile not in ("measured", "safe-small"):
        return []
    schema_argv = [exe, "schema"]
    if profile == "safe-small":
        schema_argv += ["--profile", profile]
    try:
        out = subprocess.run(
            schema_argv,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []

    try:
        tools = json.loads(out.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(tools, list) or not all(isinstance(t, dict) and "name" in t for t in tools):
        return []

    _CACHE = [t for t in tools if t["name"] not in NOT_REGISTERED]
    return _CACHE


def structural_tools() -> List[Dict[str, Any]]:
    """Reads added beside the measured profile; safe-small already includes them."""
    return [] if os.environ.get("INCISE_PROFILE") == "safe-small" else READ_TOOLS


def reset_cache() -> None:
    global _CACHE
    _CACHE = None
