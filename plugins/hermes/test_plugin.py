#!/usr/bin/env python3
"""Tests for the Hermes plugin, runnable without Hermes running.

    $ python3 plugins/hermes/test_plugin.py

What is worth testing here is narrow, because the plugin is narrow: the edit
semantics have 110406 differential cases and 212 mutations behind them already,
and re-testing them through a subprocess would only be slower. What has no
coverage anywhere else is the translation layer --

  * the op name a tool call maps to, including the three `normalize` renames
    that look like tidying-up and are not,
  * that a refusal reaches the model with its text intact, since that text is
    the product,
  * that a denied path is refused before the binary is invoked at all,
  * that the schemas registered are the ones `bench/schematest.py` checks.

The corpus is frozen -- FINDINGS.md quotes per-file results against those files
-- so every edit here runs on a copy in a temp directory.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

# The host, if it is here. Without it `safety` fails closed and every path is
# refused, which is the right behaviour and an untestable one.
HERMES = os.path.expanduser("~/.hermes/hermes-agent")
if os.path.isdir(HERMES):
    sys.path.insert(0, HERMES)

if "INCISE_BIN" not in os.environ:
    candidates = [
        os.path.join(ROOT, "target", "release", "incise"),
        os.path.join(ROOT, "target", "debug", "incise"),
        shutil.which("incise"),
    ]
    os.environ["INCISE_BIN"] = next((p for p in candidates if p and os.path.isfile(p)), candidates[0])


def load():
    """Import the plugin package the way Hermes does: by directory."""
    spec = importlib.util.spec_from_file_location(
        "incise", os.path.join(HERE, "__init__.py"), submodule_search_locations=[HERE]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["incise"] = module
    spec.loader.exec_module(module)
    return module


plugin = load()

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(': ' + detail) if detail else ''}")
        FAILURES.append(name)


def scratch(fixture):
    """A writable copy of a corpus fixture."""
    tmp = tempfile.mkdtemp(prefix="incise-plugin-")
    dest = os.path.join(tmp, os.path.basename(fixture))
    shutil.copy2(os.path.join(ROOT, fixture), dest)
    return dest


def call(name, args):
    handler = (
        plugin._make_view_handler(name)
        if name in plugin.schema_cache.READ_SUBCOMMAND
        else plugin._make_edit_handler(name)
    )
    return json.loads(handler(args))


# --- normalize: the three renames -------------------------------------------

def test_normalize():
    op, args = plugin.normalize("table_edit", {"action": "add-row", "table": "T"})
    check("table_edit -> table-add-row", op == "table-add-row", op)

    op, args = plugin.normalize("list_edit", {"action": "set-checked"})
    check("list_edit -> list-set-checked", op == "list-set-checked", op)

    # `frontmatter_edit` renames nothing -- `front_p` publishes `key` and
    # `value`, which are the op's own argument names. It is here because the
    # family shipping is what turned `key` from a `schematest.ALLOWED_BACKTICKS`
    # exception into a declared argument.
    op, args = plugin.normalize(
        "frontmatter_edit", {"action": "set", "key": "build.jobs", "value": 4}
    )
    check("frontmatter_edit -> frontmatter-set", op == "frontmatter-set", op)
    check("frontmatter args unchanged",
          args == {"action": "set", "key": "build.jobs", "value": 4}, json.dumps(args))

    # `new_heading` -> `heading` is mandatory, not cosmetic: section-rename
    # reads ["heading", "title", "text"] and section-insert reads ["heading",
    # "title"]. Neither includes `new_heading`, so without this every rename
    # refuses for a heading the model supplied.
    op, args = plugin.normalize(
        "section_edit", {"action": "rename", "section": "Install", "new_heading": "Setup"}
    )
    check("section rename op", op == "section-rename", op)
    check("new_heading -> heading", args.get("heading") == "Setup", json.dumps(args))
    check("new_heading removed", "new_heading" not in args, json.dumps(args))

    # Inside the section address only. The top-level `path` is the file.
    op, args = plugin.normalize(
        "section_edit",
        {"action": "append", "path": "doc.md", "section": {"heading": "Install", "ordinal": 2}},
    )
    check(
        "section address heading -> path",
        args["section"] == {"ordinal": 2, "path": "Install"},
        json.dumps(args["section"]),
    )
    check("file path untouched", args["path"] == "doc.md", args["path"])

    # A missing action reaches the core, which answers with the list of the
    # fifteen real names. Rejecting it here would replace a measured refusal
    # with an unmeasured one.
    op, _ = plugin.normalize("table_edit", {})
    check("missing action passes through", op == "table-None", op)
    op, _ = plugin.normalize("frontmatter_edit", {})
    check("missing frontmatter action passes through", op == "frontmatter-None", op)

    # The argument object is handed over unchanged otherwise -- `action` and
    # `path` included, which the core ignores. That is what the 5674 graded
    # calls contained.
    src = {"action": "add-row", "table": "T", "values": {"A": "1"}, "path": "x.md"}
    _, out = plugin.normalize("table_edit", src)
    check("table args passed through unchanged", out == src, json.dumps(out))


# --- the edit path ----------------------------------------------------------

def test_edit_applies():
    path = scratch("corpus/tables/aligned.md")
    before = open(path, "rb").read()
    out = call(
        "table_edit",
        {
            "action": "add-row",
            "path": path,
            "table": _first_table(path),
            "values": {"Component": "gizmo"},
        },
    )
    check("edit succeeded", "error" not in out, json.dumps(out)[:200])
    description = out.get("description") or ""
    check("one sentence back", bool(description) and "\n" not in description, repr(description))
    # S14: a successful edit returns a description and nothing else. Returning
    # the outline instead cost 8/300 redundant continuations and three
    # destroyed documents; returning both measured the same as the outline
    # alone. So the document must not come back with it.
    check("the document did not come back", "|" not in description, repr(description))
    after = open(path, "rb").read()
    check("the file changed", after != before)
    check("a hash came back", len(out.get("hash", "")) == 64, out.get("hash", ""))


def test_frontmatter_edit_applies():
    """The fourth family, through the plugin rather than through the bench.

    `corpus/frontmatter/rich.md` is the file that exists to catch a YAML round
    trip: the leading comment, the inline comment on `build.target`, the block
    and folded scalars, the quoting of `quoted_key` and the key order must all
    survive an edit to a sibling. Most YAML libraries destroy at least three of
    them. The plugin adds a subprocess boundary and a JSON argument encoding to
    that path, so it is worth one check that neither of those is where the bytes
    get lost.
    """
    path = scratch("corpus/frontmatter/rich.md")
    before = open(path, newline="").read()
    out = call("frontmatter_edit",
               {"action": "set", "path": path, "key": "build.jobs", "value": 8})
    check("frontmatter edit succeeded", "error" not in out, json.dumps(out)[:200])
    check("a hash came back", len(out.get("hash", "")) == 64, out.get("hash", ""))

    after = open(path, newline="").read()
    check("the value changed", "jobs: 8" in after, after[:0])
    # Everything the fixture names as fragile, unchanged. A diff of exactly one
    # line is the assertion; naming the survivors as well says which one broke.
    for fragile in ("# Build configuration for the example project",
                    "  target: release        # inline comment, must survive a sibling edit",
                    'quoted_key: "value: with a colon"',
                    "multiline: |",
                    "folded: >",
                    '"key with spaces": ok'):
        check(f"survived: {fragile[:40]}", fragile in after)
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    check("exactly one line differs", changed == [("  jobs: 4", "  jobs: 8")], str(changed))
    check("no lines added or removed",
          len(before.splitlines()) == len(after.splitlines()))


def _first_table(path):
    """The heading of the first table, read the way a model would: md_tables."""
    out = call("md_tables", {"path": path})
    for line in out.get("text", "").splitlines():
        stripped = line.strip()
        if stripped.startswith('heading "'):
            return stripped.split('"')[1]
    return ""


def test_refusal_is_verbatim():
    path = scratch("corpus/tables/aligned.md")
    before = open(path, "rb").read()
    out = call(
        "table_edit",
        {"action": "add-row", "path": path, "table": "Nonexistent Table", "values": {"A": "1"}},
    )
    check("refusal came back as an error", "error" in out, json.dumps(out)[:200])

    # The same call, straight to the binary. The message the model reads must be
    # the message the core wrote -- section 5.3 measured 75% one-turn recovery
    # against these exact sentences.
    import subprocess

    direct = subprocess.run(
        [
            os.environ["INCISE_BIN"],
            "table-add-row",
            path,
            "--args",
            json.dumps({"action": "add-row", "path": path, "table": "Nonexistent Table",
                        "values": {"A": "1"}}),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    expected = json.loads(direct.stdout)["error"]
    check("refusal text is byte-identical", out.get("error") == expected,
          f"\n    plugin: {out.get('error')!r}\n    binary: {expected!r}")
    check("a refused edit wrote nothing", open(path, "rb").read() == before)


def test_same_file_edits_are_serialized():
    path = scratch("corpus/tables/aligned.md")
    real_invoke = plugin.runner.invoke
    state_lock = threading.Lock()
    active = 0
    maximum = 0

    def observed_invoke(_argv, timeout=30.0):
        nonlocal active, maximum
        with state_lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return 0, {"description": "Applied test edit.", "changed": True, "path": path}, ""

    plugin.runner.invoke = observed_invoke
    try:
        args = {"action": "realign", "path": path, "table": "Components"}
        threads = [threading.Thread(target=plugin._handle_edit, args=("table_edit", args)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        plugin.runner.invoke = real_invoke

    check("same-file edits serialize", maximum == 1, f"maximum concurrency was {maximum}")


def test_long_refusal_is_capped_by_the_host():
    """The one place a refusal does not arrive whole, measured rather than guessed.

    `tools.registry.tool_error` bounds an error body at 2048 characters before
    it reaches model context. incise's "no table under heading X" refusal ends
    in a list of every heading that has a table, so on a document with enough
    tables it crosses that line: `corpus/documents/api-reference.md` produces
    2200 characters, and the last ~150 -- the tail of the heading list -- are
    replaced by the host's truncation marker.

    The plugin does not route around it. The cap is the host's policy applied to
    every tool it runs, and a plugin quietly exempting itself would be a worse
    defect than a clipped list. What the plugin must not do is truncate or
    re-word on its own account, which is what this asserts: the cut is the
    host's, at the host's threshold, and everything below it is verbatim.
    """
    path = scratch("corpus/documents/api-reference.md")
    out = call(
        "table_edit",
        {"action": "add-row", "path": path, "table": "zzz", "values": {"A": "1"}},
    )
    message = out.get("error", "")
    check("a long refusal still arrives", message.startswith('no table under heading "zzz"'),
          message[:80])
    check("the actionable part survives", "Headings with tables:" in message)

    try:
        from tools.registry import _MAX_TOOL_ERROR_CHARS as cap
    except Exception:
        print("  skip  refusal cap (hermes-agent not installed)")
        return
    raw = _direct_refusal(path)
    if len(raw) <= cap:
        check("no corpus refusal exceeds the cap", message == raw,
              f"{len(raw)} chars, cap {cap}")
    else:
        check(
            "over the cap, the host truncates and says so",
            len(message) <= cap + 32 and message.endswith("[truncated]"),
            f"raw {len(raw)}, delivered {len(message)}, cap {cap}",
        )
        check("everything below the cut is verbatim", raw.startswith(message[:cap]))


def _direct_refusal(path):
    import subprocess

    out = subprocess.run(
        [
            os.environ["INCISE_BIN"], "table-add-row", path, "--args",
            json.dumps({"table": "zzz", "values": {"A": "1"}}), "--json",
        ],
        capture_output=True, text=True,
    )
    return json.loads(out.stdout)["error"]


def test_unknown_action():
    path = scratch("corpus/tables/aligned.md")
    out = call("table_edit", {"action": "updat", "path": path, "table": "T"})
    check(
        "a misspelled action gets the core's list",
        "unknown operation" in out.get("error", "") and "table-add-row" in out.get("error", ""),
        out.get("error", "")[:160],
    )


def test_missing_path():
    out = call("table_edit", {"action": "add-row", "table": "T"})
    check("no path is named as such", "path" in out.get("error", "").lower(), out.get("error", ""))


# --- reads ------------------------------------------------------------------

def test_view_is_byte_identical():
    path = scratch("corpus/tables/aligned.md")
    out = call("md_tables", {"path": path})
    import subprocess

    direct = subprocess.run(
        [os.environ["INCISE_BIN"], "tables", path], capture_output=True, text=True
    )
    # The CLI's println adds the trailing newline the renderer's string lacks.
    check(
        "md_tables text equals the renderer's",
        out.get("text", "") == direct.stdout.rstrip("\n"),
        f"\n    plugin: {out.get('text','')[:120]!r}\n    binary: {direct.stdout[:120]!r}",
    )
    check("nothing appended to it", "hash:" not in out.get("text", ""))
    check("the hash is beside it", len(out.get("hash", "")) == 64, out.get("hash", ""))

    # The other three renderers reach their subcommands too, with the same
    # byte-for-byte rule. Splitting one tool into four is only safe if each one
    # still returns exactly what the renderer wrote.
    import subprocess

    for tool, sub in [("md_lists", "lists"), ("md_outline", "outline")]:
        got = call(tool, {"path": path})
        want = subprocess.run(
            [os.environ["INCISE_BIN"], sub, path], capture_output=True, text=True
        ).stdout.rstrip("\n")
        check(f"{tool} text equals the renderer's", got.get("text", "") == want,
              f"\n    plugin: {got.get('text','')[:120]!r}\n    binary: {want[:120]!r}")

    # `table_get` is the fourth read and the only one that takes arguments, so
    # it is the only one where the plugin's door into the CLI (`--args`) differs
    # from the door this test drives (`--table`). Both must land on the same
    # renderer output, or the passthrough is doing something to the argument.
    rows_path = scratch("corpus/tables/multiple-per-section.md")
    got = call("table_get", {"path": rows_path, "table": {"heading": "Networks"}})
    want = subprocess.run(
        [os.environ["INCISE_BIN"], "rows", rows_path, "--table", "Networks"],
        capture_output=True, text=True,
    ).stdout.rstrip("\n")
    check("table_get text equals the renderer's", got.get("text", "") == want,
          f"\n    plugin: {got.get('text','')[:120]!r}\n    binary: {want[:120]!r}")


def test_read_tools_have_nothing_to_absorb():
    """The regression guard for the call that split this tool four ways.

    A single `md_view(path, view: outline|tables|lists|rows)` produced, twice,
    byte-identically, from the same model on the same prompt:

        list_edit {"list": {...}, "path": "...", "view": "lists"}

    -- `action` missing and `view` in its place, refusing as `list-None`. Two
    required enum discriminators in one toolset, one of whose values named the
    other tool's family, and the model bound the wrong one. L3 measured the same
    shape of mistake at 30 points of accuracy.

    So the invariant is structural, not advisory: no read tool publishes a
    property that an edit tool could want. `path`, `table` and `filter` are the
    whole surface, and the first two mean the same thing in both families.

    It is checked over every tool registered as a read, not over `READ_TOOLS`,
    because one of them -- `table_get` -- is published by the binary and would
    otherwise be outside the check that exists to catch exactly its shape.
    """
    editable = {"action", "view", "values", "where", "column", "value", "position",
                "list", "section", "text", "body", "match", "checked", "after",
                "level", "subtree", "new_heading", "overwrite", "key"}
    reads = list(plugin.schema_cache.READ_TOOLS) + [
        t for t in plugin.schema_cache.edit_tools()
        if t["name"] in plugin.schema_cache.READ_SUBCOMMAND
    ]
    check("every renderer has a tool",
          {s["name"] for s in reads} == set(plugin.schema_cache.READ_SUBCOMMAND),
          str(sorted({s["name"] for s in reads})))
    for schema in reads:
        props = set(schema["parameters"].get("properties", {}))
        check(
            f"{schema['name']} publishes nothing an edit tool wants",
            not (props & editable),
            f"absorbable: {sorted(props & editable)}",
        )
        check(f"{schema['name']} has no enum", not any(
            "enum" in p for p in schema["parameters"].get("properties", {}).values()))

    # And the rule that keeps F-rows from happening again, stated as a shape
    # rather than as a warning: a schema written *here* may take nothing but
    # `path`. `md_rows` was hand-written and took arguments, and a hand-written
    # argument is one nothing compares against the op -- it narrowed `table`
    # from the op's `{heading, ordinal}` to a bare string and made all three
    # tables under one heading in `multiple-per-section.md` unaddressable. Anything that
    # takes arguments has to come from `incise schema`, where `schematest.py`
    # is watching it.
    for schema in plugin.schema_cache.READ_TOOLS:
        props = set(schema["parameters"].get("properties", {}))
        check(f"{schema['name']} is hand-written and takes only `path`",
              props == {"path"}, str(sorted(props)))


def test_a_read_argument_is_not_pre_validated():
    """F-rows: the plugin must not answer a read's argument error itself.

    `table_get` arrives with no `table`. The core's refusal for that names every
    table in the file with its ordinal; the `md_rows` handler this replaced
    answered first, with a shorter sentence pointing at another tool, and in
    doing so also made a table sharing its heading with another unaddressable.
    Section 5.3 makes the refusal the product, so the test is that the core's
    sentence is what comes back.
    """
    path = scratch("corpus/tables/multiple-per-section.md")
    out = call("table_get", {"path": path})
    err = out.get("error", "")
    check("the core answers, not the plugin", "this file has 4 tables" in err, err[:200])
    check("and it lists the ordinals", "ordinal 1" in err, err[:200])

    # The address the retired `md_rows` could not spell, end to end.
    out = call("table_get", {"path": path, "table": {"heading": "Environments", "ordinal": 1}})
    text = out.get("text", "")
    check("an ordinal reaches the core", "stage-1" in text, json.dumps(out)[:200])
    # `not in` on its own would also pass on an empty body, which is what a
    # regression here actually produces. The rows must be there *and* be the
    # ones the ordinal names.
    check("and it is the table the ordinal names",
          "stage-1" in text and "web-1" not in text, json.dumps(out)[:200])


# --- safety -----------------------------------------------------------------

def test_denied_write_never_reaches_the_binary():
    if not os.path.isdir(HERMES):
        print("  skip  file-safety (hermes-agent not installed)")
        return

    denied = os.path.expanduser("~/.ssh/id_rsa")
    out = call("table_edit", {"action": "add-row", "path": denied, "table": "T"})
    check("a protected path is refused", "error" in out, json.dumps(out)[:200])
    check("refused by the host's own wording", "denied" in out.get("error", "").lower(),
          out.get("error", ""))

    # And the guard survives the binary being absent, because it runs first.
    saved = os.environ.pop("INCISE_BIN")
    plugin.runner.reset_cache()
    try:
        out = call("table_edit", {"action": "add-row", "path": denied, "table": "T"})
        check("guard runs before the binary is resolved", "denied" in out.get("error", "").lower(),
              out.get("error", ""))
    finally:
        os.environ["INCISE_BIN"] = saved
        plugin.runner.reset_cache()


def test_safety_fails_closed():
    """With the guards unavailable, every path is refused -- not allowed."""
    saved = plugin.safety._fs
    plugin.safety._fs = None
    plugin.safety._IMPORT_ERROR = "simulated"
    try:
        check("read fails closed", plugin.safety.check_read("/tmp/x.md") is not None)
        check("write fails closed", plugin.safety.check_write("/tmp/x.md") is not None)
    finally:
        plugin.safety._fs = saved


# --- registration -----------------------------------------------------------

class FakeCtx:
    def __init__(self):
        self.tools = []

    def register_tool(self, name, toolset, schema, handler, **kw):
        self.tools.append((name, toolset, schema, handler, kw))


def test_register():
    ctx = FakeCtx()
    plugin.register(ctx)
    names = [t[0] for t in ctx.tools]
    check(
        "eight tools, the measured five first",
        names == ["table_edit", "list_edit", "section_edit", "frontmatter_edit",
                  "table_get", "md_tables", "md_lists", "md_outline"],
        str(names),
    )
    check("all in one toolset", {t[1] for t in ctx.tools} == {"incise"})
    check("every tool has a check_fn", all(t[4].get("check_fn") for t in ctx.tools))

    # Each read tool must get its own handler. One shared closure over a stale
    # `name` would send all four to the same renderer and still look registered.
    import subprocess

    for name, _ts, _schema, handler, _kw in ctx.tools:
        if name in plugin.schema_cache.READ_SUBCOMMAND:
            check(f"{name} has its own handler", handler.__name__ == f"incise_{name}",
                  handler.__name__)

    # The schemas registered are the ones `incise schema` publishes, which is
    # what bench/schematest.py compares against bench/armb.py. One copy.
    published = json.loads(
        subprocess.run(
            [os.environ["INCISE_BIN"], "schema"], capture_output=True, text=True
        ).stdout
    )
    want = [t for t in published if t["name"] not in plugin.schema_cache.NOT_REGISTERED]
    by_name = {t[0]: t[2] for t in ctx.tools}
    check("schemas are the published ones",
          [by_name.get(t["name"]) for t in want] == want,
          str([t["name"] for t in want if by_name.get(t["name"]) != t]))

    # And in the other direction, because the check above would also pass if the
    # binary stopped publishing a tool: whatever the binary publishes and this
    # plugin does not register is exactly `NOT_REGISTERED` and nothing else. The
    # set is empty today, so this asserts that every published tool is live.
    dropped = {t["name"] for t in published} - set(by_name)
    check("nothing published is silently dropped",
          dropped == set(plugin.schema_cache.NOT_REGISTERED), str(dropped))

    # `table_get` by name, because it is the one whose routing is the whole
    # point. It is published, it is registered, it gets the *read* handler --
    # and `normalize` still refuses it, which is what makes the routing rather
    # than `normalize` the thing keeping a read out of `safety.check_write`.
    check(
        "the binary still publishes table_get",
        "table_get" in {t["name"] for t in published},
        str([t["name"] for t in published]),
    )
    check("table_get is registered", "table_get" in names, str(names))
    check("table_get gets the read handler",
          plugin.schema_cache.READ_SUBCOMMAND.get("table_get") == "rows",
          str(plugin.schema_cache.READ_SUBCOMMAND))
    try:
        plugin.normalize("table_get", {"path": "x.md"})
        check("normalize still refuses table_get", False, "it returned instead")
    except ValueError:
        check("normalize still refuses table_get", True)

    # The manifest and the registration have to agree, or `provides_tools` is
    # advertising something that never appears.
    manifest = os.path.join(HERE, "plugin.yaml")
    text = open(manifest).read()
    for name in names:
        check(f"plugin.yaml lists {name}", f"- {name}" in text)

    manifest_version = re.search(r"^version:\s*([^\s]+)", text, re.MULTILINE)
    workspace_text = open(os.path.join(ROOT, "Cargo.toml")).read()
    workspace_version = re.search(
        r"^version\s*=\s*\"([^\"]+)\"", workspace_text, re.MULTILINE
    )
    check(
        "plugin version matches the workspace",
        bool(manifest_version and workspace_version)
        and manifest_version.group(1) == workspace_version.group(1),
        f"plugin={manifest_version.group(1) if manifest_version else '?'} "
        f"workspace={workspace_version.group(1) if workspace_version else '?'}",
    )
    check(
        "plugin declares its tested Hermes floor",
        'requires_hermes: \">=0.21.3\"' in text,
    )


def test_check_fn():
    # The host does `bool(check_fn())` and hides the tool when it is falsy, so
    # the polarity is the thing to assert: True means usable. Returning
    # `runner.available()` -- None when usable -- reads correctly and hides all
    # four tools exactly when they work.
    check("check_fn is True with a binary", plugin._check() is True, repr(plugin._check()))
    saved = os.environ.pop("INCISE_BIN")
    plugin.runner.reset_cache()
    try:
        # Only conclusive when there is no `incise` on PATH or in target/ to
        # find instead -- and in this repo there is, so this asserts the
        # fallback order works rather than that absence is reported.
        check("binary still found without the env var", plugin.runner.binary() is not None)
    finally:
        os.environ["INCISE_BIN"] = saved
        plugin.runner.reset_cache()


def test_every_published_action_can_be_invoked():
    """Every action in a published enum has to be a subcommand the binary has.

    `test_register` checks tool-level registration in both directions and stops
    there, which is one level too shallow. The plugin does not enumerate ops: it
    takes whatever `incise schema` publishes and `normalize` turns
    `table_edit` + `action` into `"table-" + action` with nothing in between. So
    an action added to an enum arrives here the day it is published, correctly
    -- and an action added to an enum *without* the matching subcommand would
    also arrive here, as a call the binary answers `unknown operation`.

    That is not hypothetical. F-realign published `action=realign` yesterday, and
    nothing in this file would have noticed either outcome: not the arrival, and
    not the failure.

    The binary's own op list is the source of truth, and it is asked for in the
    product's words -- the `unknown operation` sentence names every valid op,
    which is the sentence F-action is about. No file is written to get it.
    """
    path = scratch("corpus/tables/aligned.md")
    before = open(path, newline="").read()

    code, payload, _ = plugin.runner.invoke(
        ["table-frobnicate", path, "--args", "{}"])
    error = payload.get("error", "")
    check("an unknown op names the valid ones",
          "unknown operation" in error and "Valid: " in error, error[:160])
    valid = set(error.split("Valid: ", 1)[1].rstrip(".").split(", "))

    # The control. If the sentence ever stops being a list of ops, `valid` would
    # be some other set of strings and every check below would pass vacuously.
    check("the control op is not in it", "table-frobnicate" not in valid,
          str(sorted(valid)))
    check("asking cost no write", open(path, newline="").read() == before)

    seen = 0
    for tool in plugin.schema_cache.edit_tools():
        enum = ((tool.get("parameters") or {}).get("properties")
                or {}).get("action", {}).get("enum")
        if not enum:
            continue
        for action in enum:
            op, _ = plugin.normalize(tool["name"], {"action": action})
            seen += 1
            check(f"{tool['name']} action={action} reaches {op}",
                  op in valid, f"binary knows {sorted(valid)}")
    check("some actions were actually checked", seen > 0, str(seen))


def main():
    print("plugin: translation")
    test_normalize()
    print("plugin: edits")
    test_edit_applies()
    test_frontmatter_edit_applies()
    test_refusal_is_verbatim()
    test_same_file_edits_are_serialized()
    test_long_refusal_is_capped_by_the_host()
    test_unknown_action()
    test_missing_path()
    print("plugin: reads")
    test_view_is_byte_identical()
    test_read_tools_have_nothing_to_absorb()
    test_a_read_argument_is_not_pre_validated()
    print("plugin: safety")
    test_denied_write_never_reaches_the_binary()
    test_safety_fails_closed()
    print("plugin: registration")
    test_register()
    test_every_published_action_can_be_invoked()
    test_check_fn()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): {', '.join(FAILURES)}")
        return 1
    print("all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
