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
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

# The host, if it is here. Without it `safety` fails closed and every path is
# refused, which is the right behaviour and an untestable one.
HERMES = os.path.expanduser("~/.hermes/hermes-agent")
HERMES_AVAILABLE = os.path.isdir(HERMES) and os.environ.get("INCISE_TEST_NO_HERMES") != "1"
if HERMES_AVAILABLE:
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


class _AllowTemporaryFiles:
    """Minimal host guard for functional tests when Hermes is not installed.

    The production plugin still fails closed when ``agent.file_safety`` cannot
    be imported. These tests exercise that behavior separately; their ordinary
    edit/read cases operate only on fresh files under the system temp directory.
    """

    @staticmethod
    def get_read_block_error(_path):
        return None

    @staticmethod
    def get_write_denied_error(_path, verb="Edit"):
        return None

    @staticmethod
    def is_write_approval_required(_path):
        return False


if not HERMES_AVAILABLE:
    plugin.safety._fs = _AllowTemporaryFiles()
    plugin.safety._IMPORT_ERROR = None


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
    reads = list(plugin.schema_cache.structural_tools()) + [
        t for t in plugin.schema_cache.edit_tools()
        if t["name"] in plugin.schema_cache.READ_SUBCOMMAND
    ]
    published = {s["name"] for s in plugin.schema_cache.edit_tools()
                 + plugin.schema_cache.structural_tools()}
    check("every published renderer has a tool",
          {s["name"] for s in reads}
          == published.intersection(plugin.schema_cache.READ_SUBCOMMAND),
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
    if not HERMES_AVAILABLE:
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
        self.hooks = {}
        self.middleware = {}

    def register_tool(self, name, toolset, schema, handler, **kw):
        self.tools.append((name, toolset, schema, handler, kw))

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_middleware(self, name, callback):
        self.middleware[name] = callback


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


def test_source_binary_prefers_newest_build():
    """A stale optimized build must not shadow current checkout behavior."""
    with tempfile.TemporaryDirectory(prefix="incise-runner-") as root:
        release = os.path.join(root, "target", "release", "incise")
        debug = os.path.join(root, "target", "debug", "incise")
        for path in (release, debug):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("placeholder")
            os.chmod(path, 0o755)

        os.utime(release, ns=(1_000_000_000, 1_000_000_000))
        os.utime(debug, ns=(2_000_000_000, 2_000_000_000))
        candidates = list(plugin.runner._source_candidates(Path(root)))
        check(
            "newer debug build wins stale release",
            candidates == [debug, release],
            str(candidates),
        )

        os.utime(release, ns=(3_000_000_000, 3_000_000_000))
        candidates = list(plugin.runner._source_candidates(Path(root)))
        check(
            "newer release build wins",
            candidates == [release, debug],
            str(candidates),
        )

        os.utime(debug, ns=(3_000_000_000, 3_000_000_000))
        candidates = list(plugin.runner._source_candidates(Path(root)))
        check(
            "release wins timestamp tie",
            candidates == [release, debug],
            str(candidates),
        )


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


def test_safe_small_profile():
    saved_profile = os.environ.get("INCISE_PROFILE")
    saved_binary = os.environ.get("INCISE_BIN")
    os.environ["INCISE_PROFILE"] = "safe-small"
    os.environ["INCISE_BIN"] = os.path.join(ROOT, "target", "debug", "incise")
    plugin.runner.reset_cache()
    plugin.schema_cache.reset_cache()
    try:
        schemas = plugin.schema_cache.edit_tools()
        names = [schema["name"] for schema in schemas]
        check("safe-small publishes twelve tools", len(names) == 12, str(names))
        check("safe-small exposes list inspection",
              "list_get" in names and "frontmatter_get" in names, str(names))
        check("safe-small omits destructive and generic section tools",
              not {"section_edit", "section_delete", "section_replace_body"}.intersection(names),
              str(names))

        list_path = scratch("corpus/lists/nested-mixed.md")
        got = call("list_get", {
            "path": list_path,
            "list": {"heading": "Asterisk markers, four-space indent"},
        })
        check("list_get returns exact nested item text", "beta-two" in got.get("text", ""),
              json.dumps(got)[:200])
        check("list_get keeps its structured result",
              got.get("list", {}).get("items", [None] * 4)[3].get("text") == "beta-two",
              json.dumps(got)[:300])

        front_path = scratch("corpus/frontmatter/rich.md")
        got = call("frontmatter_get", {"path": front_path, "key": "build"})
        check("frontmatter_get returns flattened child paths",
              "build.target" in got.get("text", ""), json.dumps(got)[:200])
        check("frontmatter_get keeps its structured result",
              any(key.get("path") == "build.target"
                  for key in got.get("frontmatter", {}).get("keys", [])),
              json.dumps(got)[:300])
        types = {key.get("path"): key.get("type")
                 for key in got.get("frontmatter", {}).get("keys", [])}
        check("frontmatter_get distinguishes strings and integers",
              types.get("build.target") == "string"
              and types.get("build.jobs") == "integer", str(types))

        op, normalized = plugin.normalize("section_insert", {
            "path": "doc.md",
            "parent": {"heading": "Reference > API"},
            "position": "last-child",
            "new_heading": "Rate limits",
            "body": "Limits.",
        })
        check("narrow section insert maps to the core op", op == "section-insert", op)
        check("narrow section fields normalize",
              normalized.get("section") == {"path": "Reference > API"}
              and normalized.get("heading") == "Rate limits"
              and normalized.get("text") == "Limits.", json.dumps(normalized))
    finally:
        if saved_profile is None:
            os.environ.pop("INCISE_PROFILE", None)
        else:
            os.environ["INCISE_PROFILE"] = saved_profile
        if saved_binary is None:
            os.environ.pop("INCISE_BIN", None)
        else:
            os.environ["INCISE_BIN"] = saved_binary
        plugin.runner.reset_cache()
        plugin.schema_cache.reset_cache()


def test_auto_profile_falls_back_to_measured():
    saved_profile = os.environ.get("INCISE_PROFILE")
    saved_binary = os.environ.get("INCISE_BIN")
    saved_controls = {
        name: os.environ.get(name)
        for name in (
            "INCISE_HERMES_MAX_TOKENS",
            "INCISE_HERMES_PARALLEL_TOOL_CALLS",
            "INCISE_HERMES_SEED",
            "INCISE_HERMES_TRACE",
        )
    }
    os.environ["INCISE_BIN"] = os.path.join(ROOT, "target", "debug", "incise")
    try:
        os.environ["INCISE_PROFILE"] = "measured"
        plugin.runner.reset_cache()
        plugin.schema_cache.reset_cache()
        measured = plugin.schema_cache.edit_tools()
        measured_structural = plugin.schema_cache.structural_tools()

        os.environ["INCISE_PROFILE"] = "auto"
        plugin.schema_cache.reset_cache()
        automatic = plugin.schema_cache.edit_tools()
        automatic_structural = plugin.schema_cache.structural_tools()

        check("Hermes auto keeps measured schemas byte-identical", automatic == measured)
        check("Hermes auto keeps measured structural reads byte-identical",
              automatic_structural == measured_structural)
        check("Hermes auto retains the standard eight base schemas",
              len(automatic + automatic_structural) == 8,
              str([schema["name"] for schema in automatic + automatic_structural]))

        ctx = FakeCtx()
        plugin.register(ctx)
        names = [tool[0] for tool in ctx.tools]
        base_names = [schema["name"] for schema in automatic + automatic_structural]
        check("Hermes auto registers every routed handler",
              names == base_names + list(plugin.safe_routed.ROUTED_TOOL_NAMES), str(names))
        check("Hermes auto registers turn planning",
              set(ctx.hooks) == {"pre_llm_call", "on_session_end"}, str(ctx.hooks))
        check("Hermes auto registers provider narrowing",
              set(ctx.middleware) == {"llm_request"}, str(ctx.middleware))
        check("Hermes routing shares the Incise subprocess cwd",
              plugin.safe_routed.SafeRoutedAdapter._cwd() == os.getcwd())

        tools = [{
            "type": "function",
            "function": {
                "name": name,
                "description": schema["description"],
                "parameters": schema["parameters"],
            },
        } for name, _toolset, schema, _handler, _kw in ctx.tools]
        foreign = {
            "type": "function",
            "function": {"name": "terminal", "description": "foreign", "parameters": {}},
        }
        request = {"messages": [], "tools": [foreign] + tools, "tool_choice": "auto"}

        fallback = ctx.middleware["llm_request"](
            request=request, session_id="s", task_id="t", turn_id="before")
        fallback_names = [tool["function"]["name"]
                          for tool in fallback["request"]["tools"]]
        check("auto hides inactive route tools",
              fallback_names == ["terminal"] + base_names, str(fallback_names))

        path = scratch("corpus/lists/nested-mixed.md")
        prompt = (
            f'Lists in `{path}`:\n\n'
            'Under "Asterisk markers, four-space indent", add "beta-three" '
            'immediately after "beta-two".'
        )
        planned = ctx.hooks["pre_llm_call"](
            session_id="s", task_id="t", turn_id="routed",
            user_message=prompt, model="ornith-1.5-9b-q8")
        check("Ornith auto plans an exact route",
              isinstance(planned, dict) and "list_append_target" in planned.get("context", ""),
              repr(planned))
        trace_path = os.path.join(os.path.dirname(path), "hermes-request-trace.jsonl")
        os.environ["INCISE_HERMES_MAX_TOKENS"] = "2048"
        os.environ["INCISE_HERMES_PARALLEL_TOOL_CALLS"] = "false"
        os.environ["INCISE_HERMES_SEED"] = "40"
        os.environ["INCISE_HERMES_TRACE"] = trace_path
        narrowed = ctx.middleware["llm_request"](
            request=request, session_id="s", task_id="t", turn_id="routed",
            model="ornith-1.5-9b-q8", provider="custom", api_request_id="request-1")
        narrowed_names = [tool["function"]["name"]
                          for tool in narrowed["request"]["tools"]]
        check("exact routing preserves foreign tools and exposes one Incise tool",
              narrowed_names == ["terminal", "list_append_target"], str(narrowed_names))
        check("explicit Hermes benchmark controls reach the provider request",
              narrowed["request"].get("max_tokens") == 2048
              and narrowed["request"].get("parallel_tool_calls") is False
              and narrowed["request"].get("seed") == 40,
              json.dumps(narrowed["request"]))
        trace_rows = [json.loads(line) for line in open(trace_path, encoding="utf-8")]
        trace = next(row for row in trace_rows if row.get("event") == "request")
        check("Hermes trace records provider-visible routing without messages",
              trace.get("tools") == ["terminal", "list_append_target"]
              and trace.get("route") == "list-append-target"
              and trace.get("max_tokens") == 2048
              and trace.get("parallel_tool_calls") is False
              and trace.get("seed") == 40
              and "messages" not in trace,
              json.dumps(trace))

        by_name = {name: handler for name, _ts, _schema, handler, _kw in ctx.tools}
        first = json.loads(by_name["list_append_target"](
            {}, session_id="s", task_id="t"))
        check("routed handler applies the validated edit",
              first.get("route") == "list-append-target"
              and first.get("resolvedArguments", {}).get("after") == "beta-two",
              json.dumps(first)[:300])
        check("routed edit changed only the requested list",
              "    * beta-three" in open(path, newline="").read())
        after_success = ctx.middleware["llm_request"](
            request=request, session_id="s", task_id="t", turn_id="routed")
        check("successful route removes all Incise tools for the rest of the turn",
              [tool["function"]["name"] for tool in after_success["request"]["tools"]]
              == ["terminal"])
        second = json.loads(by_name["list_append_target"](
            {}, session_id="s", task_id="t"))
        check("successful route cannot mutate twice",
              "already succeeded" in second.get("error", ""), json.dumps(second))

        unknown = ctx.hooks["pre_llm_call"](
            session_id="s", task_id="t", turn_id="unknown",
            user_message=prompt, model="some-new-model")
        check("unknown auto identity stays on standard", unknown is None, repr(unknown))
        unknown_request = ctx.middleware["llm_request"](
            request=request, session_id="s", task_id="t", turn_id="unknown")
        check("unknown auto identity retains the standard surface",
              [tool["function"]["name"] for tool in unknown_request["request"]["tools"]]
              == ["terminal"] + base_names)

        stale_path = scratch("corpus/lists/nested-mixed.md")
        stale_prompt = (
            f'Lists in `{stale_path}`:\n\n'
            'Under "Asterisk markers, four-space indent", add "beta-three" '
            'immediately after "beta-two".'
        )
        ctx.hooks["pre_llm_call"](
            session_id="stale", task_id="stale", turn_id="stale",
            user_message=stale_prompt, model="ornith-1.5-9b-q8")
        with open(stale_path, "a", newline="") as handle:
            handle.write("\nexternal change\n")
        stale = json.loads(by_name["list_append_target"](
            {}, session_id="stale", task_id="stale"))
        stale_text = open(stale_path, newline="").read()
        check("routed writes retain stale-read protection",
              stale.get("stale") is True and "beta-three" not in stale_text
              and stale_text.endswith("external change\n"), json.dumps(stale)[:240])

        release_path = scratch("corpus/frontmatter/rich.md")
        release_before = open(release_path, "rb").read()
        release_prompt = (
            f'Frontmatter in `{release_path}`: YAML\n\n'
            'Update the version to 0.5.0, and set `released` to 2026-09-12.'
        )
        ctx.hooks["pre_llm_call"](
            session_id="compound", task_id="compound", turn_id="compound",
            user_message=release_prompt, model="ornith-1.5-9b-q8")
        real_invoke = plugin.runner.invoke
        calls = []

        def fail_second(argv, timeout=30.0):
            calls.append(list(argv))
            if len(calls) == 2:
                return plugin.runner.EXIT_REFUSED, {
                    "ok": False, "error": "simulated second-step refusal"
                }, ""
            return real_invoke(argv, timeout)

        plugin.runner.invoke = fail_second
        try:
            compound = json.loads(by_name["frontmatter_release_target"](
                {}, session_id="compound", task_id="compound"))
        finally:
            plugin.runner.invoke = real_invoke
        check("compound route reports a refused follow-up",
              "simulated second-step refusal" in compound.get("error", ""),
              json.dumps(compound))
        check("compound route rolls the first write back byte-for-byte",
              open(release_path, "rb").read() == release_before)
    finally:
        if saved_profile is None:
            os.environ.pop("INCISE_PROFILE", None)
        else:
            os.environ["INCISE_PROFILE"] = saved_profile
        if saved_binary is None:
            os.environ.pop("INCISE_BIN", None)
        else:
            os.environ["INCISE_BIN"] = saved_binary
        for name, value in saved_controls.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        plugin.runner.reset_cache()
        plugin.schema_cache.reset_cache()


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
    test_source_binary_prefers_newest_build()
    print("plugin: safe-small profile")
    test_safe_small_profile()
    print("plugin: auto fallback profile")
    test_auto_profile_falls_back_to_measured()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s): {', '.join(FAILURES)}")
        return 1
    print("all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
