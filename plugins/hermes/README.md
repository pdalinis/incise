# incise — a Hermes plugin

Eight tools that let a model edit a markdown document without rewriting it.

Five of them — `table_edit`, `list_edit`, `section_edit`, `frontmatter_edit`,
`table_get` — are not designed here. They are the schemes that won their
comparisons in `bench/FINDINGS.md`, fetched from `incise schema` at registration
so the text a model is shown in production is the text a number was measured on.
A local small model editing Markdown directly completed 60% of table tasks and
19% of section tasks; direct section edits lost existing content in 28% of
trials. Driving the adopted Incise table interface, it completed 60/60 tasks
with no data loss.

`table_get` is a read, and it is handled as one: `READ_SUBCOMMAND` routes it to
the read handler and `safety.check_read`, never to the write guard. It replaced
a hand-written `md_rows` — see **The read that could not address a table**.

The other three — `md_tables`, `md_lists`, `md_outline` — are this plugin's own:
the structural read that Arm B handed the model in the user turn, behind a tool
call so it can ask for it. They were one tool with a `view` enum until the first
live run; see **One read tool per renderer** below.

## One read tool per renderer

The reads started as a single `md_view(path, view: outline|tables|lists|rows)`.
The first live run of this plugin — gemma4 through Hermes, one prompt, six edits
— produced this call, and produced it again byte-identically on a second run of
the same prompt:

```json
list_edit {"list": {"heading": "Release checklist"}, "path": "…", "view": "lists"}
```

`action` missing, `view` in its place, refused as `list-None`. `list_edit`
requires `path`, `action`, `list`; the model filled the third required slot with
the wrong key, because the toolset held two required enum discriminators and one
of `md_view`'s values named the list family.

This is L3 again — renaming the list selector from `item` to `match` moved that
family from 61% to 91%, because `item` and `text` were near-synonyms and the
payload landed in the selector 39 times out of 60. The remedy is the same:
remove the thing that can be absorbed rather than describe it better. An
`AGENTS.md` instruction was in context for the second run and did not help,
which is the expected result — the model was not disregarding guidance, it was
mis-binding a parameter.

So there is no discriminator. Three tools taking nothing but `path`, plus
`table_get`, and the selection work the enum was doing lives in the
descriptions. `test_plugin.py` asserts it structurally over every registered
read: none may publish a property any edit tool wants, and none may publish an
enum.

The renderers' output is unchanged. Each tool returns its renderer's string byte
for byte, `md_tables` included — that one *is* the Arm B prompt (§11 Tier 2), so
merging the reads into one call that concatenated them was rejected.

## The read that could not address a table

The fourth read used to be `md_rows`, written here like the three above. Its
`table` was a plain string, *"the heading the table sits under, spelled as
`md_tables` shows it"* — which reads better beside its neighbours and cost an
address every other table tool in the tree has.

`corpus/tables/multiple-per-section.md` puts three tables under one heading.
`md_tables` prints them with `ordinal 0`, `ordinal 1`, `ordinal 2`. `table_edit`
and `table_get` both take `{"heading": …, "ordinal": …}`. `md_rows` took no
ordinal at all, so it refused with

```
ambiguous: 3 tables under "Environments". Pass an ordinal.
```

— a refusal naming a remedy absent from the schema that provoked it, which §5.3
counts as the worst kind. All three tables were unreachable, not two: the
ambiguity is in the heading, so it refuses for every table under it.

That was decidable without spending a GPU, and it was decided that way. The
benchmark's read family has a task for exactly this shape; `table_read_g`
answers it 10/10, `md_rows` cannot answer it at any temperature, and McNemar on
ten forced discordant pairs is p ≤ 0.0386 even granting `md_rows` both of
`table_read_g`'s only two failures. `bench/FINDINGS.md` F-rows has the working.

**The narrowing happened in the handler, not just the schema.** `_handle_view`
pulled `table` out as a string and each `filter` entry out as `COLUMN=VALUE`,
and answered a missing `table` itself. `crates/incise-cli/src/main.rs` says at
`rows_subcommand` why `rows` takes `--args` at all: a front end translating an
argument object into per-key flags is *"measuring its own translation rather
than incise's answer"*. The plugin was doing that translation and lost a
capability in it — and its own refusal for a missing `table` was shorter than
the core's, which names every table in the file with its ordinal. `table_get`'s
arguments now go to the binary as `--args`, unread, the same door the edits use.

## Install

The plugin targets Hermes 0.21.3 or newer and declares that floor in its
manifest. It has no Python package dependencies; it requires an `incise` binary.

```bash
cd /path/to/incise
PATH=$HOME/.cargo/bin:$PATH cargo build --release

ln -s "$PWD/plugins/hermes" ~/.hermes/plugins/incise
hermes plugins enable incise
hermes tools | grep incise
```

The symlink is the install. The source stays in the incise repo because it is
versioned with the CLI contract it depends on — the op names, the exit codes and
the schema all come from the binary next to it, and a copy under `~/.hermes`
would be pinned to whichever build happened to be current the day it was made.

The binary is looked for in `$INCISE_BIN`, then on `PATH`, then in the repo's
`target/release` and `target/debug`. Installing it properly — `cargo install
--path crates/incise-cli`, or a symlink into `~/.local/bin` — means the plugin
keeps working if the repo's `target/` is cleaned.

**If the binary is not found, no tools are registered** and the reason is
logged. There is no vendored schema fallback: the tools could not run anyway,
and a second copy of the measured schema text is a thing that drifts with
nothing watching it. `bench/schematest.py` watches the one copy that exists.

## What the plugin does

It is a translator. It maps a tool name and an `action` to one of the fifteen
op names, hands the argument object to the binary unchanged, and turns an exit
code into a tool result. It parses no markdown, and it validates no argument.

Both of those are deliberate:

- **No second implementation.** `bench/incise_ops.py` and `crates/incise-core`
  are a differential pair, compared byte-for-byte across 110406 cases with 212
  mutations to prove the comparison bites. A third implementation here would be
  a third thing to keep in step, with no test watching it.
- **No pre-validation.** The order arguments are checked in is part of incise's
  contract — a malformed `values` outranks a nonexistent table, and a malformed
  `position` does not. A front end that rejected an argument early would answer
  the same call with a different sentence, and §5.3 counts that as a behaviour
  regression rather than as strictness. So a misspelled `action` is passed
  through as `table-updat`, and the core answers with its own list of the
  fifteen real names.

  This paragraph was written about the edit path and was not true of the read
  path until F-rows. `md_rows` read `table` and `filter` and answered a missing
  `table` itself; what it cost is above. It holds for every tool now, and
  `test_plugin.py` checks the read side of it rather than leaving it as prose.

Two things are checked, because they are the two the core cannot see: which file
to open, and whether this process is allowed to open it.

### `normalize` is a transcription, not a convenience

`__init__.py:normalize` reproduces `bench/armb.py:1328-1364` line for line. The
5674 graded calls behind every rate in FINDINGS.md went through that function.
Three of its renames look like tidying-up and are not:

| | |
|---|---|
| `new_heading` → `heading` | **Mandatory.** `section_g_hpath` publishes the new name as `new_heading`; the core reads `["heading","title","text"]` for `section-rename` and `["heading","title"]` for `section-insert`. `new_heading` is in neither. Without this, every rename and every insert refuses for a heading the model did supply. |
| the section address's `heading` → `path` | Inside the `section` object only; the top-level `path` is the file. The core accepts both spellings, so losing this would look like it worked. |
| `action` and `path` left in the argument object | The core ignores them. They are what the graded calls contained, so they stay. |

## Safety

Every path goes through `agent.file_safety` before the binary is invoked —
`get_read_block_error`, `get_write_denied_error`, `is_write_approval_required`,
the same functions `tools/file_tools.py` calls.

This plugin is a new write path into the filesystem. One that shelled out to a
binary without consulting the host's denylist would be a way to write to a
denied path without the denial ever being asked about, and it would be this
plugin's most likely real defect — not one that a test of the edit semantics
would catch.

Writes to the same resolved path are serialized inside the Hermes process.
Sibling agents may run concurrently, and each Incise subprocess performs a
complete read-modify-write; without the per-path lock, two calls could read the
same old bytes and let the last rename discard the first edit. Calls targeting
different files remain independent.

`safety.py` **fails closed**: if `agent.file_safety` cannot be imported it
refuses every path rather than allowing every path. An approval-gated path
(`~/.ssh/config`) is refused outright, since a tool call has no channel to
prompt a human on, which is what `is_write_approval_required` documents a
caller without one should do.

## Divergences from what was measured

Recorded rather than absorbed, because each is a place where this plugin is not
quite the thing the numbers describe.

**1. Refusal framing.** §5.3's recovery rates (100% one-turn for tables in B3,
75% for sections in S12) were measured with the tool result `"Error: " +
message`, a plain string. Hermes's `tool_error` yields `{"error": "<message>"}`.
The message content is identical — the near matches, the column list, the named
next action. Only the framing moves. Following the host's convention is right;
assuming the difference is inert is not, so it is written down here.

*Measured — `bench/FINDINGS.md` F-framing.* 202 refused prefixes across all
three families, both framings, four turns, paired. **No effect on the graded
outcome** (18–17 discordant, p = 1.00, 74.3% against 73.8%). A one-turn cost
that looked consistent on the first two families — 22–11, p = 0.080 — did not
survive the third: tables is level at 6–6, and the pool goes to 28–17,
p = 0.135. So following the host's convention is measured to cost nothing in
what the model ends up doing, and the suggestion that it costs a first repair
attempt is not supported.

A single-turn caller is the case where a turn cost would become an outcome cost,
so it was measured too, and it is the same answer: 60.9% against 55.9%, 25–15,
p = 0.154. It needed no new trials — a single-turn caller's only attempt is the
trial's second call, and the turn budget never reaches the model. What that
comparison does show is where the difference goes: `json` starts ten trials
behind at one turn and finishes one behind at four, because the later turns
spend themselves repairing it.

**2. A long refusal is truncated by the host, at 2048 characters.**
`tools.registry.tool_error` bounds an error body before it reaches model
context. incise's "no table under heading X" refusal ends in a list of every
heading that has a table, so a document with enough tables crosses that line:
`corpus/documents/api-reference.md` produces 2200 characters and loses the last
~150 — the tail of the heading list — to a `… [truncated]` marker.

*Measured — F-framing, and it is one refusal in 353.* Re-executing the first
tool call of every trial in `bench/results/` through the release binary gives
353 real refusals; exactly one crosses the cap, by 9 characters. (A raw count
over that directory gives 1727, but 1374 of those are the harness pointed at the
wrong executor — Arm A's `patch` tool, the frontmatter ops the Rust core does
not implement yet, and the two read ops that are off `apply_op` by design. All
answer `unknown operation`. `bench/refusal_pool.py` separates them and is where
this number comes from.) No condition can be sized on n = 1, and below the cap
this divergence and divergence 1 are the same bytes — the host bounds the body
and *then* encodes it, so there is no truncation that is not also a JSON
wrapping. Record it as measured and inert rather than unmeasured; a corpus with
more tables would revive it.

Note what the cap does *not* take. §5.3's repair line here is `Near matches:`,
which is line 1 and survives whole; what goes is four entries off the end of a
list whose opening still reads as exhaustive.

The plugin does not route around it. The cap is the host's policy, applied to
every tool it runs, and a plugin quietly exempting itself would be worse than a
clipped list. What the plugin must not do is truncate or re-word on its own
account: `test_plugin.py` asserts the cut is the host's, at the host's
threshold, and that everything below it is verbatim.

**3. This is not a benchmark.** `bench/PLAN.md:1577-1591` closed "run real
hermes" as won't-do and made the limitation permanent: Arm A is a replication of
hermes's edit path, never "the hermes baseline". Using the plugin as a product
is a different activity. Nothing that comes out of driving it may be reported
alongside an Arm A or Arm B number.

## Tests

```bash
python3 plugins/hermes/test_plugin.py
```

Runs without Hermes running; the file-safety checks skip themselves if
`~/.hermes/hermes-agent` is not there. What it covers is the translation layer
and only that — the op name a call maps to, the three renames, that a refusal
reaches the model with its text intact (including a read's, which the plugin
used to answer itself), that a denied path is refused before the binary is
reached, and that the registered schemas are the published ones minus
`schema_cache.NOT_REGISTERED`, which is empty and is asserted in both
directions. The edit semantics are tested where they live.

Every edit runs on a copy in a temp directory. The corpus is frozen —
`bench/FINDINGS.md` quotes per-file results against those files.
