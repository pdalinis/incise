#!/usr/bin/env python3
"""Assert that the schema incise ships is the schema the benchmark measured.

The tool description is not documentation. REQUIREMENTS.md section 6 says so
directly -- "Changes to the description are behavioural changes and belong in
the benchmark, not in a docs commit" -- and the numbers back it: B7 moved the
table family by rewording one paragraph, and L3 moved the list family from 61%
to 91% by renaming one property. Those results attach to specific text.

So there are two copies of that text: `bench/armb.py`, where it was measured,
and `crates/incise-cli/src/schema.rs`, where it is served to a model. The second
is generated from the first, which means it is right the day it is written and
says nothing about any day after. This script is the thing that keeps saying it.

    $ python3 bench/schematest.py
    5 tools, byte-identical to the schemes they were measured as.

The five adopted schemes:

  table_edit        scheme_f          B6/B7. The description carries the address,
                                      not the type constraint. `values` untyped --
                                      `oneOf` measured inert across 60/60.
                                      F-realign added `action=realign`: the six
                                      existing tasks 60/60 both ways, trial for
                                      trial, and the three ragged ones 0/29 -> 30/30.
  list_edit         list_g            L2/L3. Selector renamed `item` -> `match`,
                                      because `item` and `text` are synonyms and
                                      the model wrote the payload into the
                                      selector 39 times. 91% against list_f's 61%.
  section_edit      section_g_hpath   S15. The section address is spelled
                                      `heading`, leaving `path` to mean the file.
  frontmatter_edit  front_p           F-front. `key` names the dotted path and
                                      says to copy it from the summary. 105/110.
  table_get         table_read_g      F-read. The row selector is `filter`,
                                      "narrows the rows". 58/60 against `where`'s
                                      27/60.

A failure here is not a lint. It means a model in production is being shown a
tool that no recorded trial used, and every rate in FINDINGS.md that mentions it
now describes something else.

**What this check cannot see, stated so its silence is not read as cover.** Each
entry in `ADOPTED` pairs one tool with one *single-tool* scheme, so what it
asserts is that each tool's text is what won its own comparison. The *set* is a
separate claim with a separate measurement (FINDINGS, F-compose: five against
three is p = 0.51, three against one costs about three and a fifth points), and
`ADOPTED` does not watch it. `check_composition` does, against
`bench/compose_5.measured.json` — which is how the realign drift was found, a
day after it shipped, with every per-tool check still passing.

What neither watches is a *sixth* tool. It would pass `ADOPTED` on the day it
was added, `check_composition` would report it as a set nothing ran, and the
only answer to that is an arm.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import armb  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The adopted scheme for each published tool. Changing one of these is a
# decision about what ships, and it belongs in FINDINGS.md with the run that
# justified it -- not here.
ADOPTED = [
    ("table_edit", "scheme_f"),
    ("list_edit", "list_g"),
    ("section_edit", "section_g_hpath"),
    ("frontmatter_edit", "front_p"),
    ("table_get", "table_read_g"),
]


def find_binary():
    """The built `incise`, preferring a release build over a debug one."""
    if os.environ.get("INCISE_BIN"):
        return os.environ["INCISE_BIN"]
    for rel in ("target/release/incise", "target/debug/incise"):
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    found = shutil.which("incise")
    if found:
        return found
    sys.exit(
        "no `incise` binary. Build one:\n"
        "    PATH=$HOME/.cargo/bin:$PATH cargo build --release\n"
        "or point INCISE_BIN at it."
    )


def published(binary):
    out = subprocess.run([binary, "schema"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"`incise schema` exited {out.returncode}:\n{out.stderr}")
    return json.loads(out.stdout)


def walk(path, want, got, problems):
    """Every difference, not the first one.

    A schema that has drifted has usually drifted in one place, and reporting
    that place is the whole value of the check. `assertEqual` on two 3 kB dicts
    reports both dicts.
    """
    if isinstance(want, dict) and isinstance(got, dict):
        for key in want:
            if key not in got:
                problems.append(f"{path}.{key}: missing from the shipped schema")
            else:
                walk(f"{path}.{key}", want[key], got[key], problems)
        for key in got:
            if key not in want:
                problems.append(f"{path}.{key}: shipped, but not in the measured scheme")
    elif isinstance(want, list) and isinstance(got, list):
        if len(want) != len(got):
            problems.append(f"{path}: {len(want)} entries measured, {len(got)} shipped")
        for i, (w, g) in enumerate(zip(want, got)):
            walk(f"{path}[{i}]", w, g, problems)
    elif want != got:
        problems.append(f"{path}:\n    measured: {want!r}\n    shipped:  {got!r}")


# Backticked words a refusal may use that are not arguments of an adopted
# scheme. Every entry is a claim, and the list is short on purpose: it is the
# audit, and growing it is how the check stops checking.
#
# The second element is the refusal this word is allowed *in* -- a substring
# that has to appear in the same message -- or `None` for a word allowed
# anywhere. That split is not decoration. The first version of this check keyed
# on the word alone, so allowing `row` for the one refusal that may name it
# switched the check off for `row` everywhere, which is precisely the token it
# was written to catch. It was caught by reintroducing the defect and watching
# the check pass.
ALLOWED_BACKTICKS = {
    # `key` and `filter` used to sit here, as bench-only arguments whose families
    # shipped no tool. The note said "the day either does, these come off the
    # list rather than staying as permanent exceptions" -- `frontmatter_edit` and
    # `table_get` ship now, so `declared_arguments()` supplies both and the
    # exceptions are gone. That is the mechanism working, not a relaxation: the
    # words are still checked, just against the schema instead of against a
    # promise.
    # Markdown and YAML syntax quoted as syntax, not as an argument name.
    "\\|": ("a GFM-escaped pipe, in the cell-splitting refusals", None),
    "|": ("a bare pipe, which would start a new column", None),
    "#": ("an ATX heading marker", None),
    "<br>": ("the substitution suggested for a newline in a cell", None),
    "---": ("a frontmatter delimiter", None),
    "-": ("a YAML sequence marker, in the frontmatter delete refusal", None),
    # Op names and enum values, which are addressed by `action` and are named in
    # the refusals that say which action was asked for.
    "replace-body": ("a section_edit action", None),
    "frontmatter-set": ("a frontmatter op name", None),
    # The one legitimate mention of the retired argument, and the reason this
    # check exists. This refusal fires only when the model sent both `values`
    # and `row`, so it names what arrived. Every other mention recommended an
    # argument the shipping schema does not declare and the crate refuses --
    # see FINDINGS, "the message really was wrong, and is fixed anyway".
    "row": ("named only where it arrived", "describe different rows"),
}


def declared_arguments():
    """Every property name an adopted scheme declares, nested ones included."""
    names = set()
    for _tool, scheme in ADOPTED:
        props = armb.SCHEMES[scheme][0]["parameters"]["properties"]
        names |= set(props)
        for spec in props.values():
            if isinstance(spec, dict) and isinstance(spec.get("properties"), dict):
                names |= set(spec["properties"])
            for value in (spec or {}).get("enum") or []:
                names.add(value)
    return names


def _backticked(node):
    """Backticked words in one string or f-string, dynamic parts dropped.

    An f-string is flattened with its `{...}` holes replaced by a sentinel, so a
    word split across a hole is not read as a literal. ``{field}`` therefore
    yields nothing here — it is checked at the call site instead, by
    `check_cell_labels`.

    The traversal is by hand rather than `ast.walk` because a `JoinedStr` has to
    be read whole: walking it also yields its `Constant` pieces, and a piece is
    exactly the fragment the sentinel exists to suppress.
    """
    parts = []

    def visit(n):
        if isinstance(n, ast.JoinedStr):
            parts.append("".join(
                p.value if isinstance(p, ast.Constant) and isinstance(p.value, str)
                else "\x00"
                for p in n.values))
            return
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            parts.append(n.value)
            return
        for child in ast.iter_child_nodes(n):
            visit(child)

    visit(node)
    out = set()
    for text in parts:
        for tok in re.findall(r"`([^`\n]+)`", text):
            if "\x00" not in tok:
                out.add((tok, text))
    return out


def refusal_backticks(problems):
    """No refusal may recommend an argument the shipping schema does not have.

    This exists because one did, for the whole life of the table family.
    `a row is required: either `values` keyed by column name, or `row` as an
    ordered array.` named `row`, which `table_edit` has never declared and the
    crate refuses on purpose, so any model on a shipping schema that omitted its
    row was told to send something that could not work.

    Deliberately not justified by a number. F-framing looked like it priced this
    at 13/38 one-turn recovery; that stratum turned out to be a harness artifact
    and the claim is withdrawn (FINDINGS, "the stratum is an artifact"). What is
    left is that no recorded call from a shipping scheme has ever read the
    sentence -- which makes the cost unmeasured, not small, and is exactly the
    case a lint is for: the defect is invisible to every arm because it lives on
    a branch the measured schemes do not take, and it would have shipped.

    Nothing caught it, and the reason is worth stating because it bounds the
    differential suite rather than blaming it. The sentence was byte-identical
    in `incise_ops.py` and `ops/table.rs`, so `difftest.py` agreed on the
    string; and the thing it was wrong about -- whether `row` is accepted -- is
    a **sanctioned** divergence (the oracle keeps the alias so `scheme_d`
    regrades, `ops/dispatch.rs` refuses it), which a differential suite cannot
    see by construction. A suite that compares two implementations is blind
    exactly where they are allowed to differ, and that is where a message can
    recommend something only one of them accepts. So the check has to be
    one-sided, against the schema rather than against the other implementation.

    A source lint, and honest about it: it reads the literals, so a name
    assembled at runtime is invisible here.

    **And it is a union, not a per-tool check.** `declared_arguments()` pools
    all five adopted schemes, so a word counts as declared if *any* tool has it.
    That is right for this check's own question -- the sentence is emitted by a
    core that does not know which tool called it -- and it is exactly why this
    file did not catch F-rows: `ordinal` is declared by `table_edit`, so a read
    that could not express one would have passed here. F-remedy re-ran the same
    audit per-tool, over the call graph out of `OPS`, and the five that ship are
    clean; the class is closed on the plugin side instead, by the rule that a
    hand-written schema may take nothing but `path`.
    """
    declared = declared_arguments()
    src = open(os.path.join(ROOT, "bench/incise_ops.py"), newline="").read()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Raise):
            continue
        # One `raise` can hold several literals; the context is the whole
        # statement, so a word is judged against the refusal it is part of and
        # not against one f-string fragment of it.
        whole = "".join(sorted({text for _tok, text in _backticked(node)}))
        for tok, _text in sorted(_backticked(node)):
            if tok in declared:
                continue
            allowed = ALLOWED_BACKTICKS.get(tok)
            if allowed and (allowed[1] is None or allowed[1] in whole):
                continue
            problems.append(
                f"incise_ops.py:{node.lineno}: a refusal says `{tok}`, which no "
                f"adopted scheme declares"
                + (f" and which is only allowed in the refusal saying "
                   f"{allowed[1]!r}" if allowed else "")
                + ".\n    Rename it to the argument the model actually has, or "
                f"justify it in ALLOWED_BACKTICKS."
            )


def check_cell_labels(problems):
    """The same rule for `_check_cell`'s `field`, which is backticked at runtime.

    `the value for "X" in `{field}` must be text` interpolates its argument
    name, so `refusal_backticks` cannot see it. The label is a literal at every
    call site, and one of them said `"row"` -- the same defect, reached by a
    model that had used the *correct* argument and got told about one it does
    not have.
    """
    declared = declared_arguments()
    src = open(os.path.join(ROOT, "bench/incise_ops.py"), newline="").read()
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_check_cell"):
            continue
        for arg in node.args[2:3]:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            allowed = ALLOWED_BACKTICKS.get(arg.value)
            # Only the context-free allowances apply here: a label is stamped
            # into whatever refusal the cell check raises, so a word tied to one
            # sentence cannot be one.
            if arg.value in declared or (allowed and allowed[1] is None):
                continue
            problems.append(
                f"incise_ops.py:{node.lineno}: `_check_cell` labels the argument "
                f"`{arg.value}`, which no adopted scheme declares."
            )


# Differences between the set `schema.rs` publishes and the set the composition
# arms actually ran, keyed by the exact path `walk` reports. Every entry is a
# claim that the set-level number survives the difference, and the list is short
# on purpose for the same reason `ALLOWED_BACKTICKS` is: growing it is how the
# check stops checking.
#
# The path is the whole key. A second, different change to
# `table_edit.description` would reuse this entry silently -- which is the
# `ALLOWED_BACKTICKS` mistake in a new place -- so each entry also pins the
# measured and shipped values it was written for, and a drift whose values do
# not match is reported as unlisted.
COMPOSITION_DRIFT = {
    "table_edit.description": (
        "F-realign's fourth action. The six table tasks are 60/60 both ways, "
        "trial for trial, and reached for it zero times in 62 treatment calls."
    ),
    "table_edit.parameters.properties.action.enum": (
        "The same line, as an enum entry. `3 entries measured, 4 shipped`."
    ),
}


def check_composition(shipped, problems):
    """The set, not the members -- the claim `ADOPTED` cannot make.

    `ADOPTED` pairs each tool with the single-tool scheme that won its own
    comparison, and this file's docstring has always said what that leaves out:
    "the *set* is a separate claim with a separate measurement ... and nothing
    here watches it." This watches it.

    It exists because the gap was not hypothetical. F-realign made the realign
    augmentation unconditional, and `compose_5` holds `scheme_f`'s `table_edit`
    *by reference*, so the shipped composition silently gained a fourth action
    that the composition arm never ran. Both halves of `ADOPTED` moved together
    and every per-tool check still passed, which is exactly the failure a
    member-wise check cannot see.

    `bench/compose_5.measured.json` is the record of what was run. It is
    generated once, from git, and regenerating it would turn this check into a
    comparison of the shipped set with itself.
    """
    path = os.path.join(ROOT, "bench/compose_5.measured.json")
    measured = json.load(open(path))["tools"]
    by_name = {t.get("name"): t for t in shipped}

    names = [t["name"] for t in measured]
    if [t.get("name") for t in shipped] != names:
        problems.append(
            f"composition: the arms ran {names}; `schema.rs` publishes "
            f"{[t.get('name') for t in shipped]}. A set-level number does not "
            "carry to a different set -- F-compose is five against three, not "
            "five against anything.")
        return

    for want in measured:
        drift = []
        walk(want["name"], want, by_name[want["name"]], drift)
        for msg in drift:
            key = msg.split(":")[0]
            allowed = COMPOSITION_DRIFT.get(key)
            if allowed and allowed_matches(key, msg):
                continue
            problems.append(
                f"composition drift at {key}, not in COMPOSITION_DRIFT:\n"
                f"    {msg}\n"
                "    The shipped five-tool set is no longer the one F-compose "
                "and F-anchor measured, so `schema.rs`'s second contract "
                "clause is claiming a number for a set nothing ran. Justify "
                "it in COMPOSITION_DRIFT, or re-run the composition.")


def allowed_matches(key, msg):
    """A listed drift covers this message only if it is the one it describes.

    `COMPOSITION_DRIFT`'s justifications are prose, so matching on the path
    alone would let a *second* change to the same field inherit the first one's
    excuse. The enum's length message and the description's value message are
    both pinned to the realign text.
    """
    if key == "table_edit.description":
        return msg.rstrip("'\"").endswith(
            "action=realign      requires `table`. Re-pads a table whose "
            "columns were left ragged by some other editor. Changes no cell "
            "text.")
    if key == "table_edit.parameters.properties.action.enum":
        return msg.endswith("3 entries measured, 4 shipped")
    return False


# An op name no table contains, used to make the binary read its own list of
# valid ops aloud. Spelled the same as the plugin's forward check, so the two
# halves of the invariant below are recognisably one pair.
UNKNOWN_OP = "table-frobnicate"


def check_every_op_is_reachable(binary, shipped, problems):
    """The converse of the invariant `armb._actions_from_schemes` enforces.

    That one runs forward: every action a scheme publishes must name an op the
    executor can run, because "a refusal naming them would send the model
    somewhere that refuses again". `plugins/hermes/test_plugin.py` asserts the
    same direction by invoking all fifteen published actions for real.

    This runs the other way: every op the binary names in its own `Valid:`
    sentence must be reachable from some published action. Nothing asserted it,
    and for months it was false. `table-realign` was in `OPS` -- so every model
    that mistyped an op name was handed it as a suggestion -- while no
    published tool had an enum entry that could reach it. §5.3 governs that
    sentence like any other refusal, and a refusal that recommends an
    unreachable op is the same defect as one that names an argument the model
    does not have. Shipping realign closed it; this is what keeps it closed,
    because a sixteenth op added without an enum entry reinstates it in
    silence.

    Op names are derived through `armb.normalize`, the executor's own mapping
    from tool call to op, rather than by re-deriving the `family-action` rule
    here. A second copy of that rule would be a second thing to keep in step.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "probe.md")
        with open(path, "w", newline="") as fh:
            fh.write("# Probe\n")
        out = subprocess.run(
            [binary, UNKNOWN_OP, path, "--args", "{}", "--json"],
            capture_output=True, text=True)

    try:
        error = json.loads(out.stdout).get("error", "")
    except ValueError:
        error = ""
    if "Valid: " not in error:
        problems.append(
            f"reachability: `{UNKNOWN_OP}` did not produce the op list. The "
            f"binary said {out.stdout.strip()!r}; this check reads the shipped "
            "op table out of that refusal and has nothing to check without it.")
        return
    valid = error.split("Valid: ", 1)[1].rstrip(".").split(", ")

    reachable = {}
    for tool in shipped:
        enum = (((tool.get("parameters") or {}).get("properties")
                 or {}).get("action", {}).get("enum")) or []
        for action in enum:
            op, _ = armb.normalize(tool["name"], {"action": action})
            reachable.setdefault(op, f"{tool['name']}(action={action})")

    for op in valid:
        if op not in reachable:
            problems.append(
                f"reachability: the `unknown operation` refusal offers `{op}`, "
                "which no published tool can reach. A model that takes the "
                "suggestion gets refused again, which is what §5.3 forbids -- "
                "either publish an action for it, or take it out of `OPS`.")

    for op, via in sorted(reachable.items()):
        if op not in valid:
            problems.append(
                f"reachability: `{via}` maps to `{op}`, which the executor's "
                "own list of valid ops does not contain. `armb` enforces this "
                "against its `OPS`; the shipped binary disagrees with it.")


def main():
    binary = find_binary()
    shipped = published(binary)

    problems = []
    refusal_backticks(problems)
    check_cell_labels(problems)
    check_composition(shipped, problems)
    check_every_op_is_reachable(binary, shipped, problems)

    names = [t.get("name") for t in shipped]
    if names != [name for name, _ in ADOPTED]:
        problems.append(
            f"tools: expected {[n for n, _ in ADOPTED]} in that order, got {names}"
        )

    by_name = {t.get("name"): t for t in shipped}
    for name, scheme in ADOPTED:
        measured = armb.SCHEMES[scheme]
        assert len(measured) == 1, f"{scheme} is not a single-tool scheme"
        if name not in by_name:
            problems.append(f"{name}: not published at all")
            continue
        walk(name, measured[0], by_name[name], problems)

    # `--tool` has to agree with the whole, or a caller reading one tool gets a
    # different contract from a caller reading all three.
    for name, _ in ADOPTED:
        out = subprocess.run([binary, "schema", "--tool", name], capture_output=True, text=True)
        if out.returncode != 0:
            problems.append(f"{name}: `schema --tool` exited {out.returncode}")
        elif json.loads(out.stdout) != by_name.get(name):
            problems.append(f"{name}: `schema --tool` differs from `schema`")

    if problems:
        print(f"{len(problems)} divergence(s) between the shipped and measured schemas:\n")
        for p in problems:
            print(f"  {p}")
        print(
            "\nRegenerate from the measured source, or -- if the change is "
            "intended -- run the benchmark on it first and record the result."
        )
        return 1

    print(f"{len(ADOPTED)} tools, byte-identical to the schemes they were measured as.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
