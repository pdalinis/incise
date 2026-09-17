# `incise` — the command-line front end

```
cargo build --release      # target/release/incise
```

Content-addressed, byte-preserving markdown edits. Everything outside the
targeted range is byte-identical after an edit; addressing is semantic — heading
paths, column values, item text — and never a line number, which is stale the
moment anything above it moves.

This crate is deliberately thin. It turns argv into a JSON object, reads a file,
calls `incise_core::apply_op`, writes the file back, and prints. Every decision
about what an argument *means* belongs to the core (REQUIREMENTS.md §8:
"Neither front end contains logic").

## Editing

```
incise <op> <FILE> [flags]
```

The fifteen ops, which are not listed here because they are not listed in the
CLI either — the subcommands are generated from `incise_core::OPS`, so `incise
--help` is the list and cannot go stale:

```
incise table-add-row notes.md --table Components \
       --values Component=gizmo --values Status=new --values Owner=ada

incise section-append notes.md --section "Install > macOS" --text "Run brew."

incise list-set-checked todo.md --list Today --match "buy milk" --checked true
```

Arguments can also be given whole, which is what a tool harness should do:

```
incise table-add-row notes.md --args '{"table": "Components", "values": {"Component": "gizmo"}}'
incise table-add-row notes.md --args-file -   # from stdin
```

`--args` and the per-key flags are mutually exclusive, so there is no precedence
to remember. Shapes the flat flags cannot reach have a JSON escape hatch:
`--values-json '["i", "j", "k"]'` for an ordered row, `--children` for a
subsection tree.

`--ordinal N` has no key of its own. An ordinal disambiguates *an address*, so
it nests into whichever of `--table`/`--list`/`--section` is beside it, turning
the bare-string shorthand into `{"heading": ..., "ordinal": N}`.

Every op subcommand takes the whole flag set. Which keys an op actually reads is
the core's business, and a CLI that offered `--level` only on `section-set-level`
would be answering that question a second time, somewhere no test looks.

### §5.5: the obligations the core cannot meet

| | |
|---|---|
| `--dry-run` | Says what would change; writes nothing. The sentence on stdout is the real one, so a dry run diffs against the edit it predicts; the caveat goes to stderr. |
| `--if-match <HASH>` | Refuses unless the file still hashes to this. Any prefix works. `incise hash <FILE>` prints it, and so does every read. |
| atomic write | To a sibling temp file, then `rename`. A torn write is the one failure byte-preserving splices cannot prevent on their own. |

A no-op edit does not touch the file at all. The bytes would be identical, so the
only thing a write could change is the mtime, and something is probably watching it.

## Reading

```
incise outline <FILE>              # sections
incise tables  <FILE>              # tables
incise lists   <FILE>              # lists
incise rows    <FILE> --table S [--filter Column=value]...
```

These are a separate path from `apply_op` by requirement (§6.1): they return text
*about* a document rather than a document, so they are not ops.

**Their output is a measured artifact.** `incise tables` is byte-identical to
`render_table_list`, which is not a convenience view — it *is* the Arm B prompt
(§11, Tier 2), and `python3 bench/incise_ops.py <file>` prints the same string.
Nothing is appended to it: the content hash goes to stderr, or into a sibling
field under `--json`.

## Output and exit codes

| | stdout | stderr | exit |
|---|---|---|---|
| edit applied | `describe_change`, one line | — | 0 |
| refused | — | `Error: ` + the core's message, verbatim | 1 |
| read | the renderer's string | `hash: <64 hex>` | 0 |
| usage or I/O fault | — | `incise: ...` | 2 |
| `--if-match` miss | — | `Error: ...`, naming both hashes | 3 |

`--json` moves all of it to stdout as one object, refusals included.

Three of these are load-bearing rather than stylistic:

- **A success prints one sentence, never the document or an outline.** S14
  measured the alternatives on the same tasks: an outline in place of the
  sentence cost 8/300 redundant continuations — the model reading structure it
  had not asked for and deciding more work was implied — and three documents
  destroyed by the follow-up edit. Printing *both* measured the same as the
  outline alone. The subtraction is the requirement.
- **A refusal is reproduced word for word.** §5.3 makes the message the product;
  Arm B measured 75% one-turn recovery against these exact sentences.
- **A stale `--if-match` has its own exit code.** It is neither a refusal the
  caller should re-word its call to fix nor a usage fault: the call was right and
  the world moved. A caller that cannot tell those apart retries the wrong one.

### Nothing is validated before the core sees it

The order arguments are checked in is part of the contract: a malformed `values`
outranks a nonexistent table, and a malformed `position` does not. A front end
that rejected either early would answer the same call with a different sentence,
and §5.3 counts that as a regression rather than as strictness. So `--args '[1,
2]'` is passed through to be refused by the core, which quotes it back, and an
unknown op name is handed to `apply_op` rather than to clap's "unrecognized
subcommand" — the core owns the list, so the core names it.

Only faults the core can never see are answered here: argv that is not JSON at
all, a `KEY=VALUE` pair with no `=`, a missing file.

### Two encoding decisions the requirements leave open

Encoding is unspecified everywhere in REQUIREMENTS.md, so the front end decides,
and says so rather than absorbing it:

- **Not UTF-8** — the core's signature cannot accept it. Exit 2.
- **A leading U+FEFF is refused.** The core *would* accept it, as an ordinary
  character sitting in front of the first `#`. The document would parse with no
  first heading, every address into it would miss, and the refusal the model read
  would be about a section that is plainly there. §5.5 says refuse and explain
  rather than produce a plausible-but-wrong edit.

Both are front-end refusals. `bench/incise_ops.py` has no opinion on either, so
neither is under differential test and neither pretends to be.

## The published schema

```
incise schema [--tool table_edit|list_edit|section_edit|frontmatter_edit|table_get]
```

A harness wiring incise to a model should read the tool schemas from here rather
than keep a copy. They are not descriptive: each is the variant that *won* its
measured comparison, generated from `bench/armb.py` so the schema shown in
production is the schema the number was measured on.

| tool | scheme | what it settled |
|---|---|---|
| `table_edit` | `scheme_f` | The description, not the type constraint, carries the address. `values` untyped — `oneOf` measured inert across 60/60 byte-identical calls, and is unevenly supported by MCP clients. |
| `list_edit` | `list_g` | The selector renamed `item` → `match`: `item` and `text` are synonyms and the model wrote the payload into the selector 39 times. 91%, against `list_f`'s 61%. |
| `section_edit` | `section_g_hpath` | The section address is spelled `heading`, leaving `path` to mean the file. This is the one adopted decision the core cannot enforce — `resolve_section` accepts both spellings, so if it is lost, it is lost silently. |
| `frontmatter_edit` | `front_p` | The dotted `key` is copied from the frontmatter summary rather than invented. The adopted schema completed 105/110 tasks; the task-set caveat and paired analysis remain in `bench/FINDINGS.md`. |
| `table_get` | `table_read_g` | The row selector is `filter`, described as narrowing rows, rather than the write tools’ `where`. It completed 58/60 tasks versus 27/60 for the naive spelling. |

`python3 bench/schematest.py` asserts the shipped text still equals those five
entries. A failure there means a model in production is being shown a tool no
recorded trial used.

## Dependencies

`clap` and `sha2`. `incise-core` has none and must not acquire any: it is one
half of a differential pair against `bench/incise_ops.py`, and a library upgrade
on one side would be a divergence nothing tests (§9 criterion 7). Nothing in this
crate is under differential test — it carries argv, file I/O and exit codes,
which the oracle has no opinion about — so the ban stops at the crate boundary
rather than at the workspace's.

## Tests

```
PATH=$HOME/.cargo/bin:$PATH cargo test -p incise-cli
python3 bench/schematest.py

# The renderers, cross-checked against the Python oracle for free.
# `sed '$d'` drops the oracle's per-file separator, which is not part of the string.
diff <(incise tables corpus/tables/aligned.md 2>/dev/null) \
     <(python3 bench/incise_ops.py corpus/tables/aligned.md | sed '$d')
```

`tests/cli.rs` drives the built binary rather than the library, because the
things this layer risks getting wrong are all at the process boundary: which
stream a message leaves on, what the exit code says, and whether the file on disk
afterwards is the one the op returned. Every case runs on a copy in a temporary
directory — the corpus is frozen, and `bench/FINDINGS.md` quotes per-file results
against those files.
