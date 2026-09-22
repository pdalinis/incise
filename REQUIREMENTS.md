# incise — Requirements & Goals

Status: draft v0.12 · 2026-09-07 · §1.1, §1.2, §1.3, §9 and §11 grounded in
`bench/FINDINGS.md` (tables 613 trials + lists 600 trials + sections 430 + 77
retries + 510 multi-turn + 1179 replay + 600 rename, **4009 total**). Three op
families are now measured. The table schema is settled
(§6.2, §12.7, §12.9) at 60/60; the list schema is settled (§6.4) at 94/100 with
zero silent corruption; the section schema is settled (§6.3) at 104/130 — 116/130
with one retry turn — with 0.8% data loss, and its last open design problem
(§6.3.1, the `body` payload) is now closed by measurement.
§6.5–6.7 remain unmeasured.

**v0.12 is the first version where part of §11 describes code that exists.**
No new trials: the count above is unchanged and every measured claim is the
same. What changed is that Tier 1 is built. `crates/incise-core` implements
`table-add-row`, `table-update-cell`, `table-delete-row` and the addressing
surface they need, with no dependencies, and is held to `bench/incise_ops.py`
byte-for-byte — refusal messages included, because §5.3 makes them contract.
The equivalence test was itself tested by fault injection before being trusted
(`bench/PLAN.md` §8.1); the two faults that initially slipped through were gaps
in what the corpus reaches, not in the port, and are recorded rather than
quietly patched. §11 now carries the port's status; §6 is unchanged, which is
the point — the schema was settled before the building started.

**v0.11 renames one argument, and it is the last thing the section schema was
waiting on.** `section_edit` spelled the file `path` and the heading path
`section.path` — one word, two meanings, one call. S12 named this as its
largest unrecovered bucket and predicted prose could not fix it. Measured: the
collision is ~0% on fourteen of the fifteen tasks and **~20% on `promote-api`**,
where it accounts for *every* failure, is unrecoverable inside a four-turn loop,
and twice escalates into a destroyed document. Renaming either side fixes it
completely and identically — 53/60 → **60/60**, misfilings 9 → 0 (McNemar
p = 0.0039), and zero `op_error` or destructive outcomes in 120 trials across
the two renames. **Adopted: `section` is now `{heading, ordinal?}`** (§6.3), so
`path` means the file and nothing else on every tool in every family. The
address was renamed rather than the file argument because both measured the
same and `path` is the file argument on the table and list tools, whose numbers
are frozen. The general rule this makes explicit: **no two arguments reachable
in one call may share a name while meaning different things** (§9 criterion 12),
which is result 7 of §1.3 stated as a build constraint rather than an
observation. A free second result rides along: the first full arm at v0.10's
new result shape scores 127/150, identical to the same tasks and seeds at the
old one (p = 1), so the S14 subtraction costs nothing on first calls (S15).

**v0.10 fixes the danger v0.9 found, and the fix is a subtraction.** v0.9's
32× finding said the redundant turn was the threat; §6.3.2 asserted the remedy
was to make a successful result *state what changed*. Measured across 1179
replays — same document, same first call, one string different — that assertion
is half right, and the wrong half is the half everyone would implement.
Returning a one-line description **instead of** the document takes redundant
continuation from 8/300 to **0/300** (McNemar p = 0.0078) and destructive
outcomes from 3 to 0. Returning the description **as well as** the document
does nothing at all (6/300, p = 0.73). The requirement is therefore not "say
what changed" but **"say what changed, and stop showing the document"**
(§5.4, §6.3.2, §9 criterion 11). Two controls say it is a fix and not a muzzle:
where a second call is genuinely required the model still makes it (61/83 vs
63/83, p = 0.5), and where the first call applied cleanly but did the wrong
thing it still self-corrects (3/10 vs 0/300, Fisher p = 2.4 × 10⁻⁵). The
description is also 91% shorter than the outline it replaces, so §5.4's
token-frugality and §6.3.2's safety turn out to be the same edit (S14).

**v0.9 closed the last section design question and opened a bigger one.**
§6.3.1's `body` hole was measured two ways across 510 multi-turn trials: a
prose-only `body` the executor enforces, and a structured
`children: [{heading, body}]` whose levels are derived. The structured payload
takes the three tasks that need a section *and* a subsection from 12/30 to
26/30 and costs 12 points to the twelve tasks that cannot use it — so the field
works where it was aimed, and the cost decides *where it lives* rather than
whether to have it: not on a tool this wide (S13, §12.11). The larger
finding is about turns, not payloads: **a tool call the model did not need is
32× more likely to destroy the document than one it did** (4/11 vs 4/349,
Fisher p = 3.2 × 10⁻⁵), and every guard in §6.3 was designed against
single-turn evidence. v0.9 also records the one place in the project where an
answer key moved to agree with the trials, as a caveat rather than a footnote.

**v0.8 measured a fix and did not ship it.** §6.3.1's remaining minor problem —
the executor refusing an `ordinal` on a path that already resolves uniquely —
looked free to fix. Re-grading the lenient variant against all 330 section
trials showed it buys 3 correct answers for 6 destroyed sections, because the
contradicting argument is the only evidence the address is wrong (S11). v0.8
also tested the premise v0.7 rested on: `op_error` is recoverable in one turn at
75% for sections, not just 100% for tables (S12). The item that closed as a
*decision to keep refusing* is worth as much as the two that closed as fixes.

**v0.7 closed two of §6.3.1's three open problems** with executor guards rather
than schema prose, and measured them by re-grading trials already collected —
no new sampling. The method matters as much as the result: an executor-side fix
is testable against every trial ever run, so it costs nothing to evaluate, and
the evaluation caught a bug in the fix itself before any GPU time was spent on
it. See `bench/FINDINGS.md` S8.

**v0.6 changed a v0.5 conclusion.** Result 6 below — "the description is the
interface" — did not survive contact with a second op family. It is corrected
in §1.3, and the correction (parameter *names* matter more than the prose
describing them) is the single most actionable finding in this document.

## 1. Problem

Small models with small context windows spend a disproportionate amount of time and
tokens editing markdown files. Routine structural operations — search/replace, add a
row to a table, sort a table, remove a row, edit a list — are error-prone and
inconsistent for them.

Two distinct costs, both significant:

**Write cost.** Producing a correct edit requires the model to reproduce surrounding
context byte-for-byte. It mangles table pipe alignment, drops or reorders columns,
breaks list indentation, corrupts adjacent rows, or silently rewrites more than
intended. Failures often need several correction turns.

**Read cost — the larger and less obvious one.** Before it can edit, the model must
load enough of the file to locate the edit site. For a 400-line document with a
4k-usable context, that alone can consume the budget. The model then edits from a
partial view, which is where many of the write errors originate.

### 1.1 What the baseline actually measured

The above was the starting hypothesis. It has now been tested against the local
model (`bench/FINDINGS.md`, 120 trials, table tasks, reasoning on and off). The
premise holds, but it is **narrower and more alarming** than stated:

| | reasoning off | reasoning on |
| --- | --- | --- |
| Correct | 60% | 60% |
| Silent corruption — success reported, document damaged | 30% | 36.7% |
| Outright data loss — an existing row destroyed | 10% | 6.7% |
| Cost per edit | 77 tok / 2.4 s | 1266 tok / 37 s |

Four results reshape this document:

1. **The failure is one specific invariant, not general difficulty.** An
   identical instruction against identical row content scored **10/10 on a
   ragged table and 4/10 on an aligned one**; the only difference was whether
   the pipes lined up. Forcing a full re-pad (a new value wider than any
   existing column) scored **0/10**. The model composes the right content every
   time and fails at maintaining byte alignment. That is precisely what §5.2's
   re-padding rule makes free — so the project's value is real but concentrated.

2. **Failure is destructive and silent.** Every incorrect-edit trial was the
   same thing: the model overwrote a *neighbouring* row while adding a new one.
   Row count unchanged, patch applies, tool reports success, row gone. This is
   the strongest argument for §5.1 content-addressed ops — not token frugality,
   but that an op taking a row address *cannot* express "delete a different
   row."

3. **Some failures are about tool shape, not markdown.** 6/10 delete attempts
   emitted an identical `old_string`/`new_string` pair — the model located the
   row correctly but could not express removal in a find-and-replace schema.
   The affordance was wrong for the operation.

4. **The failure is arithmetic, and reasoning cannot fix it.** Both conditions
   scored *exactly* 60%; the paired test split 9/9 across 18 discordant trials
   (McNemar p = 1.0). Reasoning bought nothing net at 16× the tokens. What it
   did change is revealing: given the forced re-pad, the reasoning-on model
   **correctly worked out that every line must be widened, rewrote them all, and
   then miscounted** — padding existing rows to 23 columns and the new row to
   24, where 22 was correct. It knows the rule and cannot execute it.

   This is the sharpest statement of what incise is for. The advantage over a
   capable model is not knowledge or reasoning; it is that `max(len(cell))` is
   exact and free in Rust and probabilistic in a language model. It also rules
   out the cheap alternative — more thinking budget is not a fix — and means the
   tool replaces 1266 tokens and 37 s per edit, not just the errors.

The read-cost argument above remains **unmeasured**. It is plausible and
motivates §5.4, but no number in this document supports it yet.

**Two more families since, and one of them is far worse.** Tables and lists sit
close together; sections do not:

| Family | Arm A correct | data loss | silent corruption |
| --- | --- | --- | --- |
| Tables | 60% | 10% | 30% |
| Lists | 63% | 2% | 30% |
| **Sections** | **19%** | **28%** | **62%** |

The section number is the one to read (`bench/FINDINGS.md` S7). Asked to rename
a setext heading, the direct-edit arm destroyed a *different* section in **10
trials out of 10**; asked to promote a heading and its subtree, it deleted the
subtree's parent in 8. Both are ops incise performs with an address and an
integer. The pattern across all three families: **the more lines an edit spans,
the worse find-and-replace does**, and section edits span the most.

### 1.2 What the proposed fix actually measured

The design in §5 has now been tested against the same model and the same six
tasks, with **no document content in the prompt** — only a structural summary —
and the ops executed by a Python reference implementation
(`bench/FINDINGS.md` B1–B7, 433 trials).

| | direct edit | incise ops | + ordered rows | + address in prose |
| --- | --- | --- | --- | --- |
| Correct | 60.0% | 88.3% | 95.0% | **100%** |
| Silent corruption | 30.0% | 11.7% | **0%** | **0%** |
| Data loss | 10.0% | **0%** | **0%** | **0%** |
| `add-row-aligned-repad` | **0/10** | **10/10** | 10/10 | 10/10 |

Columns 2–4 are three successive changes to the tool schema and its description,
each measured at 60 trials on identical tasks and seeds. The retry turn is not
in the table because it was measured on column 2, where there were failures left
to recover: it took 88.3% to **98.3%**, 13/13 (§5.3). By column 4 there is
nothing on this task set for it to recover.

McNemar against the same-seed baseline trials: 6 / 23 discordant,
**p = 0.0023**. The 100% column is 60/60 on the adopted schema; its Wilson
lower bound is 94.0%, and §12.1's caveats about effective N still apply. It
means no failure remains *that this benchmark can see* — which is an argument
for extending the benchmark (§12.1), not for declaring the problem solved.

Six results shape the build:

1. **The impossible task became free.** `add-row-aligned-repad` — the forced
   full re-pad that scored 0/10 direct and 1/10 with reasoning — is 10/10. The
   width arithmetic did not get easier; it left the model's job.

2. **Zero data loss is structural, not lucky.** No `table-add-row` call can be
   phrased so that it removes a different row. The measured 0% confirms the
   absence of a harness bug; the guarantee comes from the op shape (§5.1).

3. **Hiding the document creates one new failure, and it is the safe kind.**
   The model over-specifies row selectors with **invented cell values** it
   cannot see — `{Component: "gadget", Owner: "unknown", Status: "active"}`
   against a row that is retired/rowan. incise refuses, the document is
   untouched, and 13/13 recovered on the next call. This is the trade the §2
   claim buys: silent corruption is exchanged for loud, recoverable refusal.
   Strict matching must therefore stay strict — see §5.3.

4. **One regression, and it is the tool's fault.** Given *"add a row with the
   values i, j, k and l"*, the model editing directly writes `| i | j | k | l |`
   and is right 9/10. Asked for a `values` object keyed by column name, it must
   translate positional intent into names and gets it wrong — 3/10. The object
   shape imposed work the baseline never had. §6.2 therefore accepts an ordered
   array as well.

5. **Accepting ordered rows removed silent corruption entirely — 7/60 → 0/60,
   McNemar p = 0.0156.** All seven remaining silent failures were result 4's
   garbled translation; every failure that survives the fix is a loud refusal
   with the document untouched. Three sub-results carry into §6.2: a single
   `values` argument accepting either shape beats a second `row` parameter,
   which the model fills in twice and misuses as a selector; deleting the
   `oneOf` union from that argument changed the output in **0 of 60 trials**, so
   the prose does the work and the portable schema is free; and the model
   omitted the `table` address in **3/60 calls despite `table` being
   `required`** — schemas do not constrain output, so every field must be
   validated at runtime.

6. **The description is the interface; the JSON Schema is decoration.**
   *(Qualified by §1.3 — this held for tables and inverted for lists. Read §1.3
   before acting on it.)* The
   last failure — the dropped `table` address — was closed by adding one
   sentence naming `table` on every per-action line: **60/60, up from 57/60**,
   and the three seeds that had dropped it all supplied it. The alternative fix,
   *loosening* the address to also accept a bare heading string, was **inert**:
   same 95.0%, same three seeds failing. Together with result 5's dead `oneOf`
   this is a consistent pattern across 240 trials — prose moved the outcome
   three times out of three, schema structure moved it zero times out of two.
   §6.2 and §5.3 are therefore requirements about *wording*, not just shape.

   The contrast is the useful part. Ordered `values` (result 4) worked because
   it removed a **translation** the model was performing badly. A string address
   removes no translation — the model was not getting the address wrong, it was
   omitting it — so the same move against a different cause did nothing.
   Loosening a shape helps only when shape was the problem.

The §2 success criterion — one tool call, no document in context — is met on
**all six tasks, 60/60**, on the adopted schema. That is the criterion as
written; "correct every time" in the stronger sense it implies is not
demonstrated, and §12.1 records why (one op family, six tasks, effective N
below nominal N, no goldens).

### 1.3 What a second op family changed

§1.2's caveat — one family, six tasks — was acted on. Lists were added as a
second family: 10 tasks, 100 Arm A trials and 500 Arm B trials across five tool
schemes (`bench/FINDINGS.md` L1–L6). Lists were chosen because ordered-list
renumbering is the structural analogue of table re-padding, the operation the
baseline never once got right.

**The design transferred. One of the conclusions did not.**

| | direct edit | best list scheme |
| --- | --- | --- |
| Correct | 63.0% | **94.0%** |
| Silent corruption | 30.0% | **0%** |
| Data loss | 2.0% | **0%** |
| `add-item-ordered-renumber` | **0/10** | **10/10** |

Paired over the same tasks and seeds, McNemar exact **p = 1.6 × 10⁻⁶**. Across
**500 Arm B list trials, silent corruption was zero** — every failure was a
refusal with the document untouched. The renumbering task replicates the table
family's re-pad result exactly, 0/10 direct and 10/10 through an op.

Three results change what this document requires.

7. **Parameter names outrank the descriptions that explain them.** The list
   vocabulary shipped with `text` (the new item's content) and `item` (a
   selector for an existing item). Those are synonyms in English, and the model
   put the payload in the selector 39 times in 100 trials. Renaming the selector
   to `match` — one word, nothing else changed — moved the scheme from 61/100 to
   91/100, **30 discordant trials to 0, p = 1.9 × 10⁻⁹**.

   The table family never had this failure and structurally could not: its
   payload is `values` and its selector is `where`, two words that cannot be
   confused. That was luck, not design. **Every op's payload argument and its
   selector argument must be named so that neither could be read as the other**,
   and this must be checked before a schema is measured, not after. It is the
   cheapest fix found in the entire project and it was found by accident.

8. **Result 6 inverted, and the mechanism is instructive.** B7's adopted
   sentence — naming the address argument on every action line — ported verbatim
   to lists *lost* 19 points (80% → 61%, p = 0.00088). The full 2×2:

   | | selector `item` | selector `match` |
   | --- | --- | --- |
   | **no address prose** | 80% | 84% |
   | **address prose** | **61%** | **91%** |

   The same sentence costs 19 points in one column and gains 7 in the other
   (p = 0.016). These factors **interact**; neither has a main effect. The
   sentence prepends the address to every action line, pushing the
   distinguishing field name into second position — where two of three lines
   name the selector — which amplifies any collision already present.

   So §1.2 result 6 stands as an observation about tables and fails as a general
   rule. The corrected rule: **fix the names first; a description is only as
   good as the parameters under it.** Descriptions remain load-bearing — they
   are still where the contract lives, and the JSON Schema is still decoration
   (that part survives) — but they cannot rescue a vocabulary whose words
   overlap.

9. **A description cannot stop the model inventing a value it does not have.**
   §1.2 result 3 left open whether warning the model in the schema would prevent
   the invented-selector failure in the first turn. It was measured: one
   sentence telling the model to omit the field rather than guess moved 91% →
   94%, **p = 0.55, not significant**. Every remaining failure is still an
   invented item text.

   This is a constraint on §6.4 and §5.3, not a wording problem. The optional
   `after` field is what invites the guess — the model reaches for it even when
   `position: "end"` fully expresses the task. **An optional argument whose
   value the model cannot see is a liability**; the remaining candidate fixes
   are structural (drop it, or have it take an ordinal rather than text) and are
   unmeasured. What survives from result 3 is unchanged and important: the
   failure is loud, the document is untouched, and it costs a turn.

**What this says about the remaining op families.** §6.3, §6.5 and §6.6 are
unmeasured, and the list family is now direct evidence that a conclusion drawn
from one family can invert in the next. They should be measured, not assumed —
and their parameter names audited for result 7's collision before any trial is
run. That audit is no longer hypothetical: §6.3 shipped one (`path` as both the
file and the address) and it cost 7 points and two destroyed documents on the
task that provoked it, unrecoverably (S15, §9 criterion 12).

## 2. Goal

Offload common markdown operations to a tool that is more dependable and faster than
model-generated edits — covering both locating and mutating content, so the model
never needs to hold the document in context to change it.

Success means: a small model performs a routine markdown edit in **one tool call**,
with **no document content in its context**, and the edit is **correct every time**.

## 3. Non-goals

- Not a markdown formatter, linter, or prettifier. It does not reformat documents.
- Not a general text editor. Free-form prose rewriting stays with the model.
- Not a markdown renderer or HTML converter.
- Not a document database or index. It operates on files, statelessly.
- Does not attempt semantic understanding of content. Structure only.
- **Does not search for which file to edit.** The caller supplies the path.
  Deciding which document a change belongs in is the agent's job, not the
  tool's; `find` (§6.1) locates content *within* a named file only.
- Not a multi-file tool. One invocation, one document.

## 4. Users

1. **Primary:** small/local models operating through an agent harness, invoking the
   tool via MCP tool calls or shell.
2. **Secondary:** larger models (Claude Code and similar) using it to make
   token-cheap structural edits instead of full-file rewrites.
3. **Tertiary:** humans, via the CLI, for scripting and CI (e.g. keeping a table in
   a README sorted).

The design target is user (1). Every interface decision optimizes for a model with a
small context, a weak grasp of exact formatting, and limited ability to recover from
an unhelpful error.

## 5. Design principles

### 5.1 Content-addressed, not position-addressed

Operations never require line or character offsets. A model must have read the file
to know a line number, and the number goes stale after the first edit — which
defeats the purpose and makes multi-step edits fragile.

Addressing is semantic and stable:

| Target | Address |
|---|---|
| Section | Heading path — `Install > macOS` |
| Table | Enclosing heading path, plus ordinal if a section has several |
| Row | Key column value — `--where Name=widget` |
| Cell | Row address + column name |
| List item | Its text, or a prefix match |
| Frontmatter field | Dotted key path, with bracket indices into sequences — `build.target`, `authors[0].role` |

Consequence: operations are chainable without re-reading the file between them.

### 5.2 Surgical byte-range edits, not parse-and-serialize

Round-tripping a document through an AST reformats content that was never targeted,
producing large diffs and destroying the author's formatting choices. incise parses
to *locate*, then splices bytes to *mutate*. Everything outside the targeted range is
byte-identical after the edit.

This constraint drives parser selection: the parser must expose accurate source
offsets for every node.

**Exception — table re-padding.** A table whose pipes are padded to uniform
width cannot stay aligned when a longer value is added without rewriting every
one of its lines. The rule is *match what the table already does*:

- If a table is already aligned — every row's pipes line up — re-pad it after
  any mutation so it stays aligned.
- If it is ragged, leave it ragged. Insert new rows with single-space cell
  padding and touch nothing else.
- Alignment is binary and computed from the table as found. A nearly-aligned
  table counts as ragged.
- **Widen when necessary, never shrink.** A column's new width is
  `max(widest cell + 2, its current width)`. Never normalize a column down to
  its minimum.
- The exception is scoped to the lines of the mutated table. It never licenses
  reformatting anything else.

The widen-never-shrink rule was discovered by building the reference
implementation and is not cosmetic. `corpus/tables/aligned.md` pads `Owner` to 9
where its content needs only 7 — an author's deliberate choice. A renderer that
normalized to minimum width would rewrite **all three existing rows just to
append a short one**, and shrink a whole table to delete one row from it. Both
violate the byte-preservation invariant on the two most common operations there
are. With the rule, a short add touches only the added line, a delete touches
only the removed line, and a full re-pad happens exactly when some value
genuinely outgrows its column.

Rationale: the alternative — never re-padding — degrades every aligned table in
a repository a little on each edit, which is precisely the sloppiness this tool
exists to prevent. Fixtures: `corpus/tables/aligned.md`, `corpus/tables/ragged.md`.

**A cell is delimited by unescaped pipes, and by the end of the line.** GFM lets
a cell hold a literal pipe by escaping it, so

```
| escaped pipe    | a \| b                   | literal pipe, backslashed  |
```

is a three-column row. Splitting on `|` reads four, and that mistake runs both
ways:

- **Reading.** The row's cell count disagreed with the header's, so the table
  was classified ragged for a reason that does not exist, and
  `table-update-cell` on `Note` overwrote the fragment `b` — index 2 under the
  naive split — and re-emitted the row with four columns. Reported as success,
  on `corpus/tables/cell-edge-cases.md`, whose own text says "Any operation on
  this table must round-trip every cell exactly."
- **Writing.** A cell *value* containing a bare `|` was written straight into
  the row, so `{"A": "x | y"}` produced a three-column line in a two-column
  table; a value containing a newline ended the table mid-row and turned the
  remainder into a second, headerless one. Both reported success.

A cell holds **source markdown** — `**bold**` in a cell is bold, and a selector
matches the source text — so the write side refuses rather than escaping on the
caller's behalf. Escaping silently would make the stored text differ from the
text that was sent, and `where` matches the stored text. The refusal names the
escape to write (§5.3).

**A table whose rows disagree with its header on cell count is refused, not
normalized.** `corpus/tables/cell-edge-cases.md` poses this in the document
itself — "GFM pads short rows and truncates long ones. incise must decide
explicitly: normalize to the header's column count, or fail loudly. It must not
silently drop the extra cell." Padding a short row invents a cell and truncating
a long one destroys bytes that GFM hides but does not delete; neither is a
formatting change, and the only reformatting operation in this tool is one the
caller asks for by name. So every write op refuses the table and says which row
disagrees. Before the guard, a short row indexed past the end of itself and a
long row was rewritten at its own width.

**Line endings are matched per table, not per file.** Rebuilt lines are
constructed fresh and would otherwise silently convert a CRLF table to LF
(`corpus/hazards/crlf.md`). An op matches the line ending the target table's own
lines use, and **refuses** if that table mixes CRLF and LF rather than picking a
winner. Whole-file convention is deliberately not consulted — §5.2 says an edit
touches the target range only, and `corpus/hazards/mixed-endings.md` is a file
with no single convention to consult. This narrows §12.3 for the table ops:
per-table is answerable where per-file is not.

**Indentation is matched per table, and mixed indentation refuses.** The same
hazard as line endings, from the same cause: a rebuilt line carries no
indentation, so a table nested inside a list item
(`corpus/hazards/nested-blocks.md`) is silently de-indented and falls out of its
list. An op re-applies the table's own leading whitespace and refuses if its
lines disagree.

**A table containing tabs is treated as ragged.** `corpus/hazards/whitespace.md`
pads cells with tabs. Those cells have equal *character* counts, so a naive
alignment check reports "aligned" and the re-pad rewrites every tab to spaces —
a silent whitespace rewrite of lines nobody asked to touch. Character-count
alignment is the only kind incise can maintain arithmetically; tab alignment
depends on a tab stop the tool does not know. So tabs mean ragged: existing
lines are preserved byte-for-byte and only the new row is rendered.

The last three rules were all found the same way — by asserting that adding a
row and then deleting it restores the file byte-for-byte, across every table in
`corpus/`. None was found by inspection, and each was a *silent* mangle. That
round-trip is the cheapest high-yield invariant available and belongs in the
Rust test suite (§9).

**The ratchet, and `table-realign`.** Because alignment is detected from the
table as found and the detection is binary, a single misalignment introduced by
anything else — a model editing directly, a careless hand edit — flips that
table to "ragged" permanently. Every later incise edit then preserves the
raggedness faithfully, because that is the rule above, and nothing in the design
restores it. One bad edit therefore downgrades the document class for good.

incise cannot fix this automatically: it has no way to distinguish a ragged
table the author *wrote* from one that was *damaged*, and guessing would violate
§5.2 wholesale. So the repair is an explicit, separately-invoked operation —
`table-realign` (§6.2), scoped to one named table. It is the sole sanctioned
reformatting operation in the tool, and it is safe only because it is requested
rather than inferred.

**Realign refuses a table it cannot measure.** The tabs rule above says incise
counts column width in *characters*. That count is right for the Latin text most
tables hold and wrong for anything that does not occupy exactly one terminal
column — CJK and fullwidth forms occupy two, combining marks and zero-width
joiners occupy none, and an emoji is a display-width question no character count
answers. For the mutating ops this costs nothing, because they preserve existing
lines and pad only what they write. Realign is different: it exists *only* to
make a table look aligned, and on such a table it would produce one that is
aligned by incise's count and visibly ragged on screen — the precise opposite of
what was asked for, applied to every line in the table, in the one operation
licensed to rewrite lines nobody named.

So `table-realign` refuses a table containing any character outside the
one-column set, names the character and the first cell holding it, and says that
add, update and delete still work on that table and still leave its existing
lines byte-for-byte intact. The check is a range table, not a blanket non-ASCII
test: the first draft refused on any non-ASCII byte and thereby refused
`corpus/documents/project-readme.md` "Feature status", whose only non-ASCII
content is em dashes — one column each, and the most realistic ratchet-repair
case in the corpus. Refusing to repair the tables that most need repairing is a
worse failure than the one the rule prevents.

This is a **narrowing, not a solution**. The general answer is a Unicode width
table, which the crate's no-dependencies rule (§11) puts out of reach for now; the
refusal buys correctness at the cost of coverage and says so out loud, which is
the trade §5.3 asks for everywhere else.

### 5.3 Error messages are the product

A small model that receives `Error: row not found` will flail for several turns. The
same model receiving the candidates recovers on the next call. Every failure must
return what the model needs to retry correctly:

```
Error: no row where Name="widgit" in table under "Components".
  Near matches: "widget", "widget-core"
  Columns: Name | Status | Owner
```

**This is measured, not asserted.** Arm B (`bench/FINDINGS.md` B3) produced a
21.7% `op_error` rate; replaying each failure with the error appended recovered
**13 of 13 on the next call**, taking the scheme from 76.7% to 98.3%. One round
trip bought 21 points. Recovery rate is therefore an acceptance criterion (§9),
not a quality-of-life goal.

Requirements for the error contract:

- Never guess at an ambiguous address. Return the candidate list and fail.
- Include near-matches (edit distance) whenever a lookup misses.
- Include the valid alternatives — column names, heading paths, list items.
- Errors are machine-parseable (structured field in JSON mode) and human-readable.
- Every error names a concrete next action.
- **Name the part of the request that is wrong, not a part that is right.** The
  first version of the row-selector error reported the first key in `where`,
  which on the measured failure was *the one key that matched* — it answered
  `no row where Component="gadget" / Near matches: gadget`. When a selector
  partially matches, identify the intended row by scoring each candidate on how
  identifying its matched values are (`1/(rows sharing that value)`, so a unique
  value outranks one shared by two rows), then state the conflict per column.
- **Any selector the error suggests must be verified to match exactly one row
  before it is offered.** An earlier revision suggested `{"Status": "active"}`,
  which matched two. A wrong suggestion is worse than none: it is authoritative
  and the model will follow it.

Machine-readable repair data may accompany a refusal, but never replace or rewrite its human-readable message. Repair metadata uses a stable code plus the relevant argument, received value, copyable candidates, and remedy. Initial typed cases are ambiguous list-item matches, attempted replacement of a frontmatter container, and unconfirmed section-subtree deletion; callers that ignore the additional object continue to receive the original sentence byte-for-byte.

### 5.4 Token-frugal output

Never echo the document. Default success output is a single confirmation line
(`ok: added 1 row to table under "Components" (now 7 rows)`). Diffs are available on
request and are unified and minimal. Read operations return only the requested
slice — a table query returns matching rows, not the table.

**This principle is load-bearing, not a nicety, and it was measured.** The
harness originally returned the document's heading outline on every successful
section call — helpful-looking, 702 characters. Replacing it with the
63-character confirmation line eliminated redundant follow-up calls entirely
(8/300 → 0/300, McNemar p = 0.0078) and with them three destroyed documents;
returning *both* was statistically identical to returning the outline alone
(S14). Echoing the document is not merely wasteful, it is an invitation to
keep editing: what the model can see, it will re-inspect and second-guess. The
confirmation line must therefore be derived from before-vs-after, never from
the arguments — a model asking "did my call land?" learns nothing from being
told what it asked for, and an argument-echo can report a change that did not
happen (§6.3.2).

### 5.5 Safety and predictability

- **Atomic writes.** Write to a temp file in the same directory, then rename. A
  crash or a parse failure never leaves a partial document.
- **Match-count guards.** Mutating ops accept an expected count and fail if actual
  differs. A typo in a search-replace must not silently rewrite 40 sites.
- **`--dry-run` on every mutating op**, printing the diff without writing.
- **Idempotency where meaningful.** Re-sorting a sorted table is a no-op that
  reports as such rather than rewriting the file.
- **Scoping.** Search/replace can be constrained to a section or a table, so a
  global term doesn't get rewritten document-wide.
- **Stale-read detection.** Every read operation returns a short content hash of
  the file. Mutating operations accept an optional `--if-match <hash>` and fail
  if the file has changed since. This closes the read-then-write race that arises
  whenever a model locates an edit site in one call and mutates in another —
  cheap now, awkward to retrofit into a published CLI contract later. Omitting
  the flag skips the check, so single-call edits pay nothing for it.
- Refuse and explain rather than produce a plausible-but-wrong edit.

## 6. Functional requirements

### 6.1 Read / locate operations

| Op | Purpose |
|---|---|
| `outline` | Heading tree with levels and child counts — the cheap map of the document |
| `get-section` | Body of one section, optionally excluding subsections |
| `list-tables` | Tables present, with heading path, **caption**, columns, row count |
| `table-get` | Rows matching a predicate, as JSON or markdown |
| `list-items` | Items of a list under an address |
| `frontmatter-get` | One key or the whole block |
| `find` | Locate a string within the given file and report its structural address, not its line number |

Every read operation also returns the file's content hash, for optional use as
`--if-match` on a subsequent write (§5.5).

**Read ops are not `apply_op` entries.** Every op in §6.2 takes a document and
returns a document or a refusal, and the executor's contract is exactly that
pair. A read returns *text about* a document, which does not fit, and forcing it
in would also change the "unknown operation" refusal — a sentence §1.2 measured.
So `table-get` sits on the same path as `list-tables`/`render-table-list`:
a function returning structured data, and a renderer that turns it into the
prose a model reads. Two entry points, one of which the benchmark already uses.

Five decisions `table-get` inherits rather than re-opens:

- **The filter argument is not called `where`.** On `table-update-cell` and
  `table-delete-row`, `where` must match *exactly one* row or the op refuses —
  §6.2's strict-selector rule, adopted because §1.2 result 3 measured the model
  inventing selector values. On a read, matching zero or many rows is the normal
  case and refusing would be absurd. That is one word carrying two contracts,
  which is precisely the failure S15 measured and fixed for `path` (~20% of
  `promote-api` trials, 100% of that task's failures). The filter is `filter`,
  which says 0-or-many in the word itself where `match` would not; `where` stays
  strict and stays on the write ops. Untested against a model — the naming
  lesson is measured, this particular word is not, and it is listed as open.
- **A non-rectangular table is refused on read too.** `table-get` names cells by
  column, and a row that disagrees with the header has no unambiguous mapping —
  the same reason §5.2 refuses it on write. Refusing is also the more useful
  answer: every write to that table will refuse as well, so telling the caller
  now, with the row named, is the shortest path to a working document. The
  refusal's last sentence differs from the write ops', because "incise will not
  rewrite a table it cannot read unambiguously" is not true of a read.
- **Rows come back positional, not keyed by column name.** A table may legally
  repeat a header, and keying rows by name would then report the last such
  cell's value under every one of its positions — a false statement about the
  document, in the op whose entire job is to report the document. The oracle's
  first draft did exactly that, via `dict(zip(cols, row))` (F-dupcol).
- **A repeated column name is refused, not resolved.** Wherever a *name* has to
  become a cell — `where`, `column`, named `values`, `filter` — a header that
  uses that name twice makes the request unanswerable, and incise does not guess
  which cell was meant. Positional paths (ordered `values`, `table-realign`) are
  unaffected, so such a table stays editable and stays repairable. F-dupcol has
  the account and the reason nothing caught it.
- **No `format` argument yet.** §6.1's "as JSON or markdown" is two renderers,
  not two arguments, until there is evidence a model needs to choose. The
  structured/renderer split above gives both for free at the call site, and
  §6.2's measured lesson is that an extra argument is a thing the model fills in
  wrongly.

The read surface also includes `list-items` (`list_get` in agent schemas), which resolves one list through the same address path as list edits and returns each exact item text, depth, parent index, and checkbox state. This is the inspect step for placement-sensitive list edits: callers copy an exact returned item into `after` rather than ask the executor to guess. `frontmatter_get` likewise returns flattened paths, kinds, and values so nested and indexed keys can be copied into a later set. Both reads return the current content hash beside their structured result.

Frontmatter leaf results MUST distinguish string, integer, number, boolean, and null values; containers report object or array. A version-like plain scalar containing more than one decimal point, such as `0.5.0`, is a string.

### 6.2 Table operations

Add row · update row/cell · delete row · sort by column (with a numeric/lexical/
semver/date mode and stable ordering) · add column · remove column · reorder
columns · rename column. Column alignment markers move with their columns.
Padding follows the re-padding rule in §5.2.

`table-realign` — re-pad one named table to uniform column width. The only
reformatting operation in the tool, and the repair path for the ratchet
described in §5.2. Never invoked implicitly, never applied to a whole document,
and a no-op that reports as such if the table is already aligned. It takes one
argument, `table`, and no others: an operation whose entire effect is "make this
look right" has nothing left to parameterize, and it is the only op in the
family with no argument-ordering contract to hold (§5.3). It refuses a table
whose width incise cannot measure in characters — §5.2 gives the reasoning and
the message.

**Row values accept two shapes, through one argument.** Named — `{"Component":
"widget", "Status": "active"}` — and ordered — `["widget", "active", "peter"]`,
positional in column order and rejected unless its length matches the column
count exactly. Both arrive as `values`; there is no second `row` parameter.

The ordered form is not a convenience. §1.2 result 4 measured the named-only
shape scoring **3/10** on an instruction that supplied values positionally
(*"add a row with the values i, j, k and l"*), against 9/10 for direct editing,
because the model must translate position into column names and does it wrong.
Accepting the shape the instruction already has removes the translation. §1.2
result 5 then measured the fix: **silent corruption fell 7/60 → 0/60**
(McNemar p = 0.0156), and the entire `wrong`-outcome class disappeared. Named
remains the default and the one an addressing-by-content tool should encourage;
ordered exists because instructions in the wild are frequently positional.

*One argument, not two.* The two-parameter variant (`values` object plus a
separate `row` array) was measured alongside the single-parameter one and scored
the same. It loses on failure mode: given two ways to say one thing the model
fills in both, and once used `row` as a *row selector* on a delete. One argument
that accepts either shape cannot be misused that way.

*Untyped, and described in prose.* The single `values` argument carries a
description covering both shapes and no JSON-Schema type constraint. Deleting a
`oneOf: [object, array]` union changed the model's output in **0 of 60 trials**
(§1.2 result 5) — the description does the work — and `oneOf` is unevenly
supported across constrained decoders and MCP clients. Costing nothing, the
portable form wins. This is a schema-presentation choice only: the *executor*
still type-checks what arrives (below).

**Nothing in the schema is a guarantee.** Required fields and type constraints
are hints to the model, not constraints on its output: §1.2 result 5 measured
the model omitting the `table` address in 3/60 calls despite `table` being in
`required`. Every argument must therefore be validated at runtime — presence,
type, and shape — and every violation must produce a refusal with a recoverable
message (§5.3), never a panic, a default, or a guess. A tool that trusts its
schema is trusting the wrong layer.

**The tool description carries the contract.** Because the schema does not bind
(above) and prose demonstrably does (§1.2 result 6), the description is a
requirement surface, not documentation. It must name **every required argument
on every action line** — the omission of exactly this took the address failure
from 3/60 to 0/60 — and it must state that widths and alignment are handled
automatically, so the model does not attempt the arithmetic F6 shows it cannot
do. Changes to the description are behavioural changes and belong in the
benchmark, not in a docs commit.

**Structured arguments arrive as strings sometimes; parse what parses.** The
model occasionally serializes a structured argument — `"{\"Component\":
\"gadget\"}"` for an object, or an object key carrying literal quotes. A string
that JSON-parses to the expected type must be accepted: it recovers the call
with nothing invented. A string that does not parse — `"i, j, k, l"` for a row —
must be **refused**, because splitting it on commas would be guessing at cell
boundaries, which is precisely what the ordered-row rule above exists to
prevent. Parse what parses; refuse what would have to be guessed. The refusal
must name the shape expected, not report a downstream symptom: the measured
failure surfaced as `no column "{"`, an error three layers from its cause.

**Row selectors (`where`) match strictly.** All supplied columns must match, and
the selector must identify exactly one row, or the op refuses. The tempting
relaxation — retry with whichever subset does match — is rejected: §1.2 result 3
measured the model supplying *invented* selector values, and silently discarding
a constraint the model asserted is the mechanism by which the wrong row gets
deleted. Refuse, and spend the error message (§5.3) instead.

**Redundant-but-consistent input is accepted; contradictory input refuses.**
Where a caller supplies the same fact twice, resolve both readings and proceed
if they are identical, refuse if they differ. Measured: when the model filled in
two competing row arguments it usually filled them in *agreeing*, and refusing
spent a turn to reach the same bytes. This does not weaken the `where` rule
above, and the distinction is the whole point — accepting agreement discards
nothing and leaves no ambiguity to resolve, whereas relaxing `where` would throw
away a stated constraint and change which row is touched. Agreement is free;
guessing is not.

### 6.3 Section operations

**Measured (`bench/FINDINGS.md` S1–S15, 430 trials + 77 retries + 510
multi-turn + 1179 replay + 600 rename, both arms, a fix arm, a multi-turn arm,
a replay arm and a rename arm). 80/100 correct with 0.8%
data loss — 89.2% with one retry turn —
against a direct-edit baseline of 19% correct
and 28% data loss.** This is the family with the largest measured gap between
editing markdown as text and editing it with ops — and it took two executor
guards to get there, because it is also the only family where the executor does
not absorb the model's mistakes (S1). The schema is settled: the last open
design problem closed in S13 (§6.3.1), which in closing raised a question about
*turns* rather than arguments — answered in S14, and the answer is about the
tool's **response**, not its arguments (§6.3.2). One argument *name* changed
after that: S15 renamed the address out of its collision with the file
argument.

The adopted schema is one tool with an `action` enum, the same shape as §6.2
and §6.4 so the model does not learn a third habit:

```
section_edit(path, action, section, ...)      # `path` is the file, and only the file
  action=append        requires `text`
  action=replace-body  requires `text`     (+ `overwrite`=true if the body is non-empty)
  action=insert        requires `position`, `new_heading`  (+ optional `body`)
  action=delete        requires nothing else -- takes the subtree with it
  action=rename        requires `new_heading`
  action=set-level     requires `level`                    (+ optional `subtree`)
```

`section` is `{heading, ordinal?}`: a heading path, either the leaf (`"macOS"`)
or the full path (`"Install > macOS"`), with a 0-based `ordinal` only where two
sections share an *identical* path. A bare string is accepted as shorthand, as
in §6.2 and §6.4.

- **`new_heading`, not `heading`** — adopted on its mechanism, not its headline
  (S5). The rename is +5 points and not significant (p = 0.33), but it took
  calls that omitted the `section` address from 4 to 0: the model had been using
  `heading` to say *which* section, because in English a heading names one.
  Third replication of L3, "naming beats description", with the caveat that a
  naming fix buys only the failure mode it targets. Its one side effect —
  the model generalizing the prefix and inventing `new_text` — argues for
  renaming `text` to match rather than reverting.
- **`section.heading`, not `section.path`** — the one change v0.11 makes, and
  the fourth replication of L3. `path` was simultaneously the file argument and
  the address, and the model resolved the ambiguity by putting the heading path
  in the file slot: ~20% of `promote-api` trials, 100% of that task's failures,
  and unrecoverable — three trials burn all four turns re-issuing the identical
  failing call, two escalate to `rename`/`replace-body` and destroy the
  document. Renaming the address and renaming the file argument were run as
  separate single-factor arms and measured *identically* (60/60 each, 9 → 0
  misfilings, p = 0.0039), which is the finding: the collision itself is the
  defect and either disambiguation removes it. The address moved because `path`
  is the file on every table and list tool. The payload stays `new_heading`
  (S5); `heading` at the two depths is now distinguished by nesting, and the
  schema must never offer both at once. Costs nothing elsewhere: on the
  balanced arm's twelve single-call tasks it is 115/120 → 120/120, ten trials
  each, with no misfilings in either rename (S15).
- **`replace-body` requires `overwrite`=true when the body is non-empty, and
  `append` refuses a `heading`** — the two guards from S8, adopted on a
  counterfactual re-grade of 200 already-collected trials: destructive 6→1 and
  4→1 at a cost of zero correct answers. Both are *executor* requirements, not
  schema advice: they hold whether or not the model reads anything.
- **Action descriptions name what each action does to existing text and which
  action creates a section** (S9). `insert-subsection-last` went 1/10 → 8/10.
  Weaker evidence than the guards — against `section_p` the overall gain is
  p = 0.14 — so this is adopted as free and probably helpful, not as the reason
  for the headline.
- Everything else below is a reference-implementation contract, settled against
  the corpus by `bench/test_incise_ops.py`, and independent of the schema
  question.

#### 6.3.1 What the measurement settled

Three design problems were open after S1–S6. All three are now closed:

1. ~~**`append` and `replace-body` are a data-loss pair (S2).**~~ **Closed.**
   `replace-body` refuses a non-empty own body unless the call passes
   `overwrite=true`; an empty body is unprotected, because there is nothing to
   lose and the two actions produce identical documents there. Measured in S8:
   five of six destructive trials became loud `op_error`s and no correct trial
   was lost. The `overwrite` field must exist in the schema — a guard whose
   acknowledgement cannot be expressed makes the correct call unreachable, which
   is what happened to `section_naive` and `section_p` on
   `replace-install-preamble`.
   **One requirement fell out of the fix:** a `heading` argument that merely
   echoes the addressed section's own name requests nothing and must pass
   through. Refusing it cost six correct trials in the first version.
2. ~~**`after` and `last-child` are the same word to the model (S3).**~~
   **Closed.** `append` and `replace-body` refuse a `heading` and name `insert`
   and `rename` in the error, and the schema says `insert` is the only action
   that creates a section. 1/10 → 8/10. The `position` enum is unchanged; what
   moved was which *action* the model picked, not which position.
3. ~~**`body` takes raw markdown, and that is a hole in the tool's promise
   (S6).**~~ **Closed.** The schema tells the model it never has to count
   heading levels, and for `new_heading` that is true and works (18–20/20 on
   rename and set-level). `body` is markdown source, so a new section containing
   a subsection requires the model to work out the child's level by hand — and
   across 30 `insert-release-at-top` trials it wrote that heading at levels 1, 2
   and 4, never at 3. When it happens the subsection lands as a *sibling* of the
   release it belongs to and every argument in the call is right.

   S10 originally read this as the task's dominant failure, at five trials of
   ten. Re-reading the raw calls corrects that to **two**: the largest group is
   three trials that create the release perfectly and then stop, never
   attempting the subsection at all. That is a limit of the single-turn harness,
   not of the vocabulary — so the payload hole is real and worth closing, but it
   is not what this task's score was measuring. Fixing the hole and re-running
   without a multi-turn harness would produce a number that means nothing.

   Two candidate closures: make it two calls with derived levels, or make the
   payload structured (`children: [{heading, body}]`). In both, `insert` refuses
   a `body` containing a heading rather than writing a level it was not given.

   ~~**Still open.**~~ **Closed by S13**, which built both and ran them across
   510 multi-turn trials. Three requirements come out of it:

   - **`insert` refuses a heading anywhere in `body`, parsed rather than
     pattern-matched.** Not just on the first line: one trial sent a stray table
     row followed by `## Added`, and a first-line check would have written it.
     The same parser the document goes through decides, so a `#` inside a fenced
     block is prose here too. Re-graded against all 330 single-turn section
     trials the guard costs **zero** correct answers and converts four silent
     failures — one of them destructive — into `op_error`.
   - **Where a nested payload is offered at all, it is
     `children: [{heading, body, children?}]` with levels derived from the
     parent recursively, refusing a child that would be level 7.** On
     the three tasks that need a section *and* a subsection it goes 12/30
     (raw `body`) → 14/30 (prose-only `body`, two calls) → **26/30**.
     `insert-troubleshooting` reaches 8/10 in one call where the vocabulary
     without it needs three.
   - **A nested payload does not belong on a tool this wide.** `children` costs
     12 points across the twelve tasks that never touch it: single-call
     correctness falls 98% → 94%, `malformed` output rises 0 → 3, and
     `promote-api` — which cannot use the field at all — drops 8/10 → 4/10. The
     net across fifteen tasks is +2, which is noise. **A field is paid for by
     every task in the tool, including the ones that ignore it**, so a nested
     payload has to sit on a surface narrow enough that the payers are the
     users. Measuring `children` on a dedicated create-a-section tool is the
     next step (§12.11); until then `section_edit` ships without it and
     section-plus-subsection is two calls.

One new problem, below the severity of the three above because it costs a round
trip and no bytes: **an out-of-range `ordinal` on a path that resolves to
exactly one section is refused** (S10, 12 of 26 remaining failures). This is now
**decided: keep refusing.** The lenient variant was implemented as a throwaway
monkeypatch and re-graded across all 330 section trials (S11) — it buys 3
correct answers for **6 destroyed sections**, all six the same case, where the
model truncates the path to the parent and uses the ordinal to mean "the second
child". The path resolves; it resolves to the wrong section. The ordinal is the
only evidence the address is wrong, so an executor requirement follows:

- **When two address arguments contradict each other, refuse — do not drop the
  one that fails to resolve.** Dropping it keeps the one that resolves to the
  wrong thing, and turns a loud refusal into a silent overwrite.

What is left is the *message*, not the resolution. `"Valid ordinals: 0"` names
the argument that is easy to compute rather than the one that is wrong, and one
retry trial followed it literally into the only destructive second turn measured
in the project (S12). The refusal must say that the path resolves to exactly one
section so an ordinal cannot apply, and ask whether a child was meant.

**Done — FINDINGS F-address**, with one correction the requirement as written
did not anticipate: "resolves to exactly one section" is only one of the two
cases. A leaf can resolve to *many* sections with many different paths, and
there an ordinal is not merely inapplicable but useless — the repair is a longer
path, and the refusal has to say which. The message now branches on that, the
same way the resolver's no-ordinal branch already did.

**`op_error` is recoverable in this family too — 75%, and that is what the
guards are worth.** §6.3's two guards are justified by converting silent
corruption into loud failure, which only pays if loud failure is cheap. B3
measured that on tables (13/13); S12 measures it on sections: 75.0% of the fix
arm's `op_error` trials recover in one extra turn, taking it from 80.0% to
**89.2% correct**. Two requirements fall out of the 15 that still error:

- ~~**`path` must be renamed.**~~ **Done in S15 — the address is now
  `section.heading`.** Six of the fifteen are the model putting the *heading*
  path into `path`, the file argument — and they are the only failures that
  reproduce byte-identically on the retry turn. An error message listing all 18
  candidate sections does not dislodge it; a name collision responds to a
  different name, not better prose (L3). It did: 9 misfilings → 0, p = 0.0039.
  Read the "six of fifteen" carefully — it is six of the *unrecovered
  failures*, about 1.3% of trials pooled and ~20% on one task, which is why the
  arm that measured it spent its sampling on that task rather than spreading it
  (`bench/PLAN.md` step 8).
- **Error messages are part of the executor's contract, and must be tested.**
  Six unrecovered trials are a model bouncing off §6.3's `overwrite` guard on
  the recovery turn — the guard working, counted as a failure. One is a message
  inviting the wrong repair. Both are only visible by reading second turns.

#### 6.3.2 The redundant turn, and what it means for the guards

S13's larger result, and the one that most affects what gets built. Across the
twelve section tasks that need exactly one call, 360 trials:

| | n | correct | destructive |
| --- | --- | --- | --- |
| stopped after the first call, or the first call failed | 349 | 326 (93%) | 4 (1.1%) |
| made a further call after one that had already succeeded | 11 | 4 (36%) | **4 (36%)** |

Fisher exact p = 3.2 × 10⁻⁵, a 32× relative risk. The behaviour is rare — 3% of
trials — and when it happens it is worse than a coin flip. All four have the
same shape: the first call was right, the model could not tell, and it escalated
to `delete`, to `rename` over a wrong anchor, or to `replace-body` with
`overwrite: true`.

Two requirements:

- **A tool result must say what changed, and must not say what the document now
  looks like.** Both halves are load-bearing, and S14 measured which one does
  the work. The harness returned the document's heading outline. One trial
  repeated an identical `set-level` after it had worked, then renamed the parent
  out of existence — an outline that already reflects the change cannot tell the
  model it made the change. `"Applied: promoted \"API\" and 2 descendants from
  level 3 to level 2."` can.

  Replaying 393 fixed prefixes at three response shapes — outline, description,
  and both — settles the wording. On the 300 prefixes whose first call had
  already produced the correct document:

  | result shape | continued anyway | destructive | correct | mean chars |
  | --- | --- | --- | --- | --- |
  | outline (S13's behaviour) | 8/300 (2.7%) | 3 | 295 | 702 |
  | description only | **0/300 (0.0%)** | **0** | **300** | **63** |
  | description **and** outline | 6/300 (2.0%) | 3 | 297 | 758 |

  McNemar outline → description p = 0.0078; outline → both p = 0.73. **Adding a
  statement of what changed buys nothing while the document is still in the
  response.** A requirement that said only "state what changed" would have been
  implemented as the third row. The subtraction is the fix.

  The description must be derived by diffing before against after, not by
  echoing the arguments: the model's question is whether its call landed, which
  its own arguments cannot answer, and an argument-echo can claim a change that
  did not occur. See `bench/incise_ops.py::describe_change` for the reference
  wording, and §9 criterion 11 for the acceptance bar.

  Two controls rule out "the model was simply silenced". Where a second call is
  genuinely required (the three section-plus-subsection tasks, 83 prefixes)
  continuation is unchanged: 63 → 61, p = 0.5, with correctness 46 → 48. And
  where the first call applied cleanly but edited the *wrong* section (10
  prefixes) the model still continues 3/10 under the description shape, against
  0/300 when the call was right — Fisher p = 2.4 × 10⁻⁵. Under the outline
  shape that same contrast is p = 0.26: the old response provoked continuation
  without regard to whether continuation was warranted. The new one continues
  where it should and stops where it should.

  A tempting stronger claim was tested and is false: it is *not* that
  outline-invisible edits get retried more. Grouped by op, `append` is retried
  2% of the time after succeeding and `insert` 64% — the variable is whether the
  task needed more calls, not whether the effect was visible.
- **Acknowledgement is not consent when the model's picture is stale.** §6.3.1's
  `overwrite: true` guard was justified on single-turn evidence, where the model
  sets the flag having just read the outline. Three of the four escalations pass
  straight through it, because a model that has decided the document is wrong
  will acknowledge anything. The guard is still correct and stays; what it does
  not do is protect a *second* edit to a section this conversation has already
  edited. Whether that case should refuse regardless of `overwrite` is still
  open (§12.12) — though it is now a smaller question than it was, because the
  response-shape fix removes the escalations that motivated it. The three
  continuations that survive the fix are not `overwrite` cases: two are the same
  `rename` retried three times against a mis-resolved ordinal (§6.3.1's open
  refusal-message problem, arriving from a second direction) and one is an
  `append` that produced an `op_error`.

#### 6.3.3 Reference contract

Requirements the reference implementation imposes, all independent of the
schema question above:

- **A section's body and a section's subtree are different spans, and both are
  needed.** `append` and `replace-body` act on the own body — the part above the
  first subsection — because "add a note to the Install section" must not land
  after its last subsection's last paragraph. `delete` and `set-level` act on
  the subtree, because deleting a section that leaves its children orphaned at
  the wrong depth is not what anyone means. One address, two spans, chosen by
  the action.
- **Heading level is derived from the anchor, never supplied.** `insert` takes
  `position` (`before` / `after` / `first-child` / `last-child`) and works the
  level out. There is no way to name an impossible level, so the model cannot
  produce an H4 under an H2 by arithmetic — the same argument as §6.4's "no
  `depth` argument", and it is why `level` appears only on `set-level`, where it
  is the operation. **The guarantee used to stop at `body`** — markdown source,
  where the model wrote the level by hand and got it wrong (S6). It no longer
  does: `insert` refuses a heading anywhere in `body` and parses to decide, so
  the only way to create a section is an action that derives its level (§6.3.1).
  Where a nested payload is offered at all, its levels derive from the parent
  recursively and a level-7 child refuses.
- **Heading level is content; heading *syntax* is formatting.** The three
  syntaxes (setext, ATX, closed ATX) address identically and must round-trip
  distinctly. Rewriting a setext H2 as `## ` is `collateral:formatting` under
  §5.1, so `set-level` on a setext heading changes the underline character and
  refuses the levels setext cannot express.
- **A trailing link-reference block is document-level, not section-level.** By
  CommonMark it belongs to the last section; treating it that way made
  "delete the oldest release" silently delete every link definition in a
  changelog, including live ones. Section spans are capped before such a block.
  The rule is narrow by construction — end of document, every line a reference
  definition, blank-line separated — and orphaned references are left alone: the
  op deletes what it was asked to delete and does not guess at cleanup.
- **A payload's own blank lines are not an instruction.** `text` and `body` are
  stripped of leading *and* trailing blank lines; the spacing between a block and
  what surrounds it is the document's convention, and the op supplies it. Four
  trials in 130 sent `"\nSuperseded."` — the right prose, with the separator the
  op already inserts supplied a second time by hand — and keeping it put two
  blank lines where the document uses one. `collateral:formatting` under §5.1: a
  document damaged in a way nobody asked for, because the executor read a guess
  about whitespace as an instruction.
- **Inert headings refuse as inert, never as absent.** A `## ` inside a fence,
  a blockquote, an indented code block or frontmatter is not addressable, and
  saying "no such section" about text the user can plainly see is the wrong
  error. It says where the text is and why it does not count.
- **A write that does not produce the section it promised is an error, not a
  success.** `insert` re-parses its own output and refuses if the heading it
  wrote did not become a heading — the case is a document ending inside an
  unclosed fence. §12's `wrong` vs `op_error` distinction, resolved toward the
  loud one.
- **Insert and delete must be inverses.** Not each checked against a golden:
  round-tripping a probe section through every position of every corpus section
  (755 probes) failed 113 times on three defects that per-op golden tests had
  not surfaced, all of them at the boundary between two constructs. This is a
  testing requirement on the Rust, not only on the reference.

Beyond the six: move a section (a delete and an insert that must be one
transaction), and sort sibling sections. Unmeasured and unimplemented (§11
Tier 3).

`section-delete` deletes a leaf in one call. If the resolved section has descendants, it MUST refuse before mutation unless the caller supplies `subtree=true`; the refusal MUST report the descendant count and exact descendant paths. This acknowledgement is defense in depth for generic callers. Profiles aimed at small models SHOULD omit section deletion and body replacement entirely unless the task explicitly requires them.

### 6.4 List operations

**Measured (`bench/FINDINGS.md` L1–L6, 600 trials). Settled at 94/100 with zero
silent corruption.** The adopted schema is one tool with an `action` enum, the
same shape as §6.2:

```
list_edit(path, action, list, ...)
  action=add-item     requires `list`, `text`
  action=remove-item  requires `list`, `match`
  action=set-checked  requires `list`, `match`, `checked`
```

Beyond the measured three: reorder / sort · change nesting depth · insert
alphabetically. These are unmeasured and marked as such (§11 Tier 3).

Requirements the measurements impose:

- **`text` is the payload, `match` is the selector, and they may not be
  synonyms.** Naming the selector `item` cost 30 points against `text`
  (§1.3 result 7). This is a hard requirement on the vocabulary, not a
  preference.
- **`list` is required on every action**, addressed by heading path plus ordinal
  where a heading holds more than one list — the same contract as `table` in
  §6.2, so the model does not learn two addressing habits. A bare heading string
  is accepted as shorthand.
- **Every per-list convention is read off the list as found and never
  normalized.** This is §5.2's "widen when necessary, never shrink" applied to
  lists, and it covers more state than tables do:

  | Convention | Rule |
  | --- | --- |
  | Marker character (`-`, `*`, `+`) | Copied from the sibling the new item joins |
  | Ordered delimiter (`.` vs `)`) | Part of the marker; `1.` and `1)` are different lists |
  | Indent width | Copied from the sibling, not from house style |
  | Loose vs tight | A property of the whole list; an insert must not silently change it |
  | Checkbox spelling (`[x]` vs `[X]`) | Preserved; both mean done |

- **Ordered-list numbering has three cases and needs three behaviours.** A rule
  that always renumbers and a rule that never renumbers are both wrong:

  | Style | Example | On insert / removal |
  | --- | --- | --- |
  | `sequential` | `1. 2. 3.` | Renumber from the insertion point |
  | `constant` | `1. 1. 1.` | Do not renumber — it is legal CommonMark and renumbering is the bug |
  | `irregular` | `1. 3. 7.` | Do not renumber — an unasked-for behaviour change |

  A list starting at 5 continues at 8, not at 4.

- **Nesting is expressed through `after`, not a depth argument.** A new item
  copies the indent and marker of the sibling it follows, so "add a nested item"
  needs no `depth` and there is no way to name an impossible one.
- **`after` is a known liability (§1.3 result 9).** It is optional, its value is
  item text the model usually cannot see, and offering it invites a guess that a
  schema description does not prevent (91% → 94%, p = 0.55). Every failure left
  in the best scheme is this. Dropping it, or having it take an ordinal instead
  of text, is the open question in §12.


### 6.5 Frontmatter operations

Get, set, delete by dotted key path, with bracket indices into sequences
(`build.target`, `authors[0].role`). YAML preserved; comments and key order
untouched.

The preservation clause is the hard part and `corpus/frontmatter/rich.md:37-52`
is its acceptance test: a `frontmatter-set` on one value must leave key order,
the leading comment, the inline comment on `build.target`, the block scalar
styles and the quoting of `quoted_key` byte-identical. Most YAML libraries
destroy at least three of those on a load/dump round trip, so the family is a
line-preserving editor rather than a parse-and-serialize — the same constraint
§5.2 places on the document body, applied inside the block.

Four distinctions the ops must keep, because the fixtures already state them:
**absent** frontmatter and an **empty** block are different documents; a `set`
on an absent block creates `---` at the very top and leaves the rest
byte-identical, including the blank line; deleting the last key leaves the empty
block intact rather than removing the delimiters; and a TOML `+++` block is
refused by name while tables, sections and lists on the same file keep working.
`frontmatter_span` accepts `+++` so the other three families skip it correctly,
which means a frontmatter op has to re-inspect the delimiter itself.

`frontmatter-set` also accepts host-owned `must_absent` and `must_exist`
preconditions. Omitting both preserves the original set-or-create behavior and
all existing refusal bytes. `must_absent: true` refuses if the addressed path
already exists; `must_exist: true` refuses if it does not; setting both refuses.
These fields are not published in the measured default schema. A router that
has already classified create versus update intent supplies the precondition so
a model cannot turn an add request into an overwrite by choosing the wrong
existing path. A precondition refusal returns no document and carries structured
repair metadata naming the path and violated condition.

`frontmatter-get` is a **read**, so it is off `apply_op` like `table-get` (§6.1)
and its failure mode is a false report rather than a damaged document.

Built and measured on the bench side only — see F-frontmatter and F-frontread.
The Rust port, `difftest.py` cases, mutations, `invariants.rs`, CLI subcommands
and Arm C are the later decision reserved below.

### 6.6 Scoped search / replace

Literal and regex modes, scopable to a section or table, with an expected-match-count
guard and a `--dry-run` default in ambiguous cases.

### 6.7 Transactions

Multiple operations applied against one file in a single call, all-or-nothing. This
matters for small models: one call, one result, one chance to be wrong. Batch input
is a JSON array of ops.

## 7. Non-functional requirements

- **Startup latency < 10ms.** The tool is invoked per-edit; process startup is a real
  cost. This rules out interpreted runtimes and is a primary reason for Rust.
- **Correctness over coverage.** An unsupported construct must fail loudly, never
  mangle. Encountering something the parser doesn't model is an error, not a silent
  best-effort edit.
- **Format preservation is a hard invariant**, verified by test: for every operation,
  bytes outside the target range are unchanged.
- **Deterministic.** Same input plus same op yields identical output bytes.
- Handles files up to a few MB without special handling.
- No network access, no telemetry, no config file required to be useful.

## 8. Technical decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language | Rust | Single static binary, sub-10ms startup, mature GFM parsers with source spans |
| Interfaces | CLI **and** MCP server, from day one, over a shared core crate | Primary consumers need both; building together prevents the CLI contract from drifting into something awkward to expose as tool schemas |
| Markdown flavor | CommonMark + GFM (tables, task lists, strikethrough) + YAML frontmatter | Covers the documents agents actually edit |
| Distribution | Build for our own use first, but keep it releasable — stable CLI contract, documented behavior, no hardcoded local assumptions | Avoids a rewrite if it proves out |

Parser candidates to evaluate against the byte-offset requirement in §5.2:
`pulldown-cmark` (offset iterator gives byte ranges directly) and `comrak` (fuller
GFM coverage, source position data). MCP side: the official Rust SDK (`rmcp`).

Repository shape: a core crate holding parse/locate/splice and the operation set,
with thin CLI and MCP binaries over it. Neither front end contains logic.

## 9. Acceptance criteria

The project meets its goal when:

1. A model with no document content in context can add a row to a table in
   `corpus/documents/api-reference.md` (820 lines) with one call, and the
   resulting diff touches only that table.
2. Every operation has a test asserting byte-identity outside the edited range.
3. Every failure mode returns near-matches or a candidate list — verified by test,
   not by inspection.
4. Every operation runs cleanly against every file in `corpus/` — preserving
   alignment, marker style, blank-line conventions, line endings, trailing
   whitespace, and the absent final newline in `corpus/hazards/whitespace.md`.
5. Every hazard in `corpus/hazards/` either works correctly or fails with a clear
   error. None of them produces a silently mangled document.
6. A local small model completes the benchmark task set with a materially lower
   error rate and token count than editing the files directly.

Criterion 6 now has numbers attached. Arm B (§1.2) established these against the
Python reference implementation, so they are the bar the Rust must **match, not
beat** — a regression against them is a bug in the port:

| | direct edit | required of incise |
| --- | --- | --- |
| correct, first call | 60.0% | **60/60 on the six benchmark tasks** |
| data loss | 10.0% | **0%, structurally** |
| silent corruption | 30.0% | **0%** |
| `add-row-aligned-repad` | 0/10 | 10/10 |

These are not the same kind of requirement, and conflating them would be a
mistake. **Data loss is structurally inexpressible** — no `add-row` call can be
phrased so that it removes a different row (§5.1) — so any non-zero count is a
defect in incise, not a bad trial. **Silent corruption is 0% measured**, over
60 trials, and it is not structurally impossible: a model can still name a valid
row and give it wrong content, and no op shape prevents that. What §1.2 result 5
eliminated is the one *mechanism* that produced all of it. **The 60/60 is a
regression bar, not a claim of perfection** — its Wilson lower bound is 94.0%,
and it holds for one op family on six tasks. Treat a drop below it as a port
defect; do not treat it as evidence that untested op families will behave.

7. **The Rust matches `bench/incise_ops.py` byte-for-byte** on every op in
   every measured family — tables, lists and sections — across every file in
   `corpus/`. The Python is the differential-testing oracle, and it is the
   artifact §1.2's, §1.3's and §6.3's numbers were actually measured
   against — so divergence invalidates those numbers rather than merely
   differing from them.
8. **`op_error` recovery is tested, not assumed.** For each refusal the error
   text names the intended row, states the conflict per column, and any selector
   it suggests is verified unique before being offered (§5.3). Recovery is
   measured, not asserted: 100% for tables (B3) and 75% for sections (S12), and
   the section guards are only justified while that number stays high.
9. **Add-then-delete round-trips byte-for-byte** on every table in `corpus/`
   (81 tables), and **insert-then-delete round-trips** through every position of
   every section (755 probes). Each assertion found silent-mangle bugs that
   per-op golden tests missed — three in the table reference (lost indentation,
   tabs rewritten to spaces, dropped CRLF) and three in the section reference,
   all at the boundary between two constructs (§6.3.3).
   `bench/test_incise_ops.py` is the working version; the Rust suite must carry
   both.
10. **The three section guards fire, and fire loudly** (§6.3): `replace-body`
    refuses a non-empty own body without `overwrite: true`, `append` refuses a
    `heading`, and `insert` refuses a heading anywhere in a parsed `body`. Each
    was adopted because it converts silent corruption into `op_error` at a
    measured cost of zero correct answers; a port that quietly widens any of
    them is a regression against the only family with measured data loss.
11. **A successful mutation returns a description of what changed and nothing
    else** (§5.4, §6.3.2). The description is computed by diffing the document
    before against after — never from the call's own arguments — and every
    change it claims must be present in the result, asserted over the whole
    corpus rather than on examples (`bench/test_incise_ops.py::test_describe_change`,
    and in Rust `incise_core::describe_change` plus the three
    `crates/incise-core/tests/invariants.rs` tests that assert a description
    never claims a heading the after-document lacks, that the no-op sentence
    appears exactly when nothing changed, and that the response stays one line).
    The response must not contain the document, an outline of it, or any other
    re-statement of its current contents: returning the description *alongside*
    the outline measured identically to returning the outline alone, so the
    omission is the requirement, not a style preference. This is the only
    acceptance criterion about the shape of a *success*, and it is worth as much
    as the guards in criterion 10 — it eliminated every destructive outcome
    that followed an already-successful call (3 → 0, and 7 → 3 across the whole
    replay set) at no cost to the tasks that legitimately need a second call
    (S14).
12. **No two arguments reachable in one call share a name while meaning
    different things** (§6.3, §1.3 result 7). `section_edit` violated this —
    `path` was the file and `section.path` was the address — and the model
    resolved the ambiguity by filing the address as the filename on ~20% of the
    one task where the two are easiest to confuse, unrecoverably. The rule is
    checkable rather than stylistic: for every tool, flatten the parameter tree
    and assert no leaf name appears at two depths with two referents. It is
    cheap to satisfy at design time and, once shipped, cannot be repaired by
    error messages, retries or a better description — S12 tried all three
    (S15).

## 10. Test corpus

`corpus/` holds 25 markdown files, each isolating one failure mode, plus three
realistic documents. See `corpus/README.md` for the full inventory. Structure:

| Directory | Covers |
|---|---|
| `tables/` | Alignment, ragged pipes, alignment markers, ordinal addressing, cell escaping, sort modes |
| `sections/` | Deep nesting, repeated leaf names, unresolvable duplicate siblings, setext and closed ATX |
| `lists/` | Marker styles, indent widths, tight/loose, task checkboxes, ordered-list renumbering |
| `frontmatter/` | Comment and key-order preservation, absent vs empty blocks |
| `hazards/` | Code fences, HTML, nested blocks, whitespace semantics, CRLF and mixed endings, TOML frontmatter |
| `documents/` | A project README, a changelog, and an 820-line API reference |

The corpus files are fixtures: their exact bytes are the test. They must not be
reformatted, and tests operate on copies.

Benchmark tasks are documented per file in each fixture's own body, so a failing
test points at a document that explains what it was protecting.

## 11. Build order

Derived from §1.1, not from the shape of the op list. §6 describes the eventual
surface; this is the order to build it in, ranked by measured harm.

**The pre-build gate is cleared.** The repeat-penalty confound — the one result
that could have invalidated this ranking — was tested and closed: a matched
control at `repeat_penalty: 1.0` moved the score by +1/60 (p = 1.000) and left
the forced re-pad task at 0/10 (`bench/FINDINGS.md` F7). The corruption is a
capability limit, not a sampling artifact.

Note also what the evidence does *not* support: reasoning budget. Both reasoning
conditions scored exactly 60% (§1.1 point 4), so there is no "just let the model
think harder" alternative to weigh this build against. Nothing outstanding
blocks starting Tier 1.

### Tier 1 — the measured failures

| Build | Evidence | Guards |
| --- | --- | --- |
| `table-add-row` with §5.2 re-padding | 4/10 aligned, **0/10** when a re-pad is forced; 1/10 even with reasoning | Widest failure. Under reasoning the model derives the re-pad rule and then miscounts (§1.1 point 4) — so this must be correct-by-construction, not an option |
| `table-update-cell` | 10/10 in *both* conditions — but only because the test value was *narrower* than the column | Same re-pad path as above the moment a value grows. Do not read 10/10 as "solved" |
| `table-delete-row` | 6/10 could not express deletion at all | Fails on tool *shape*, not markdown; no alignment reasoning involved |

These three cover every failure observed. Nothing else in §6.2 has evidence
behind it yet.

**All three are now validated end-to-end** against the Python reference
implementation (§1.2): **60/60 first-call** on the adopted schema, zero data
loss, zero silent corruption, and the forced re-pad at 10/10. The Tier 1 surface
is settled.

**It is now also ported.** `crates/incise-core` implements the three ops, plus
`list_tables`/`render_table_list` because a model that cannot address a table
cannot call them. Equivalence to the oracle (§9 criterion 7) is enforced by
`bench/difftest.py`, which runs 10482 corpus-generated cases through both
implementations and compares byte-for-byte — documents *and* refusal messages,
since §5.3 makes the message part of the contract. `bench/mutate.py` establishes
that this test can fail, by injecting 56 faults and requiring each to be caught;
the two that initially survived were corpus coverage gaps, not port bugs, and
both are closed (`bench/PLAN.md` §8.1). What that suite cannot reach is why
`crates/incise-core/tests/invariants.rs` exists alongside it: a differential test
is blind to an assumption both implementations share
(`bench/FINDINGS.md` F-pipes), and an invariant is blind to one the
implementation shares with itself (F-realign). Twelve invariants, each shown to
fail under a targeted fault rather than trusted for being green.

Both are blind to a third thing: **an input the corpus does not contain.** A
table whose header names the same column twice is legal GFM, occurs in none of
the 81 tables in the corpus, and was being resolved two different ways inside
the oracle alone — silently, and in agreement with nothing (F-dupcol). That
class is the cheapest of the three to close, because the fix is to add the
input: one synthetic fixture, and every name-resolving path now runs against a
repeated header.

The crate has **no dependencies**, deliberately. `incise_ops.py` imports only
`difflib` and `json`, and both are reachable inside refusal text, so both are
ported into the crate — otherwise a library upgrade on one side would silently
break the equivalence that everything else here rests on.

Five details Tier 1 must carry that only emerged from building the reference:

- **Widen, never shrink** column widths (§5.2) — otherwise appending one short
  row rewrites the whole table.
- **Match the target table's line ending**, and refuse if it mixes them (§5.2).
- **`values` accepts an ordered array as well as a named object**, through a
  single untyped argument (§6.2) — the named-only shape measured 3/10 on
  positionally-phrased instructions, and fixing it took silent corruption to
  0/60.
- **Every argument is validated at runtime**, because the schema's `required`
  and type constraints do not bind the model's output (§6.2). A missing or
  mistyped field is a refusal with a recoverable message, never a default.
  This is now built in the reference, and building it found that the reference
  had not been obeying it (FINDINGS F-args): `table` as a number crashed the
  executor, a missing `column` leaked a Python `TypeError`, and `position: "0"`
  silently appended at the end and reported success. No recorded trial ever
  reached those paths, which is why no measured number moved — proven by
  replaying all 5674 recorded tool calls before and after
  (`bench/regrade_snapshot.py`) — and is also why they survived: an argument
  layer is only exercised by the clients that get it wrong, and this model
  never did. The rule the checks follow is **parse what parses, refuse the
  rest**: `"0"` is an integer and `"End"` is `end`, but `"middle"`, `1.5`, and
  a nested object in a cell are refusals. A default is not a guess only when
  the argument is *absent*.

  A fourth defect surfaced later, while porting the dispatch, and it was the
  worst: `table-update-cell` never checked `value` at all, so a missing one
  wrote the literal string `None` into the cell and reported success — in the op
  whose entire purpose is to write one cell. Fixed, and re-proved neutral over
  the same 5674 calls.
- **The order of the checks is part of the contract, not an implementation
  detail.** §5.3 makes the refusal message the product, so a different-but-valid
  refusal is a regression. In the reference that order is made by Python's
  argument evaluation rather than by any code — a malformed `values` outranks a
  nonexistent table while a malformed `position` does not — so the port has to
  transcribe it, and the transcription has to be tested against the reference
  rather than against the porter's reading of it. Twice now that reading was
  wrong (FINDINGS F-args).
- **The tool description names every required argument on every action line**
  (§6.2). One sentence doing this took the adopted schema from 57/60 to 60/60;
  the equivalent change made in the *schema* instead moved nothing (§12.9). The
  description is a requirement surface, and changing it is a behavioural change.
- **No op's payload argument may be a synonym of its selector argument**
  (§1.3 result 7). Tables get this free — `values` against `where` — but the
  list family shipped `text` against `item` and lost 30 points to it. This is a
  precondition on the *names*, checked before the description is written, and it
  applies to every op family added later.

Two invariants Tier 1 must carry, both from observed damage:

- **No op may remove a row it was not asked to remove.** Enforced structurally,
  not by care: this is the 10% data-loss finding, and it is the reason the
  addressing model in §5.1 exists.
- **The blank line after a table survives.** Three trials consumed it. Anchor
  insertion to the table's last row, never to the following line, and assert it
  in the acceptance test for every insert op.

Both are now asserted in `crates/incise-core/tests/invariants.rs`, over every
table in the corpus rather than over examples, alongside three more that follow
from §5.2: bytes outside the target range are unchanged, re-padding widens and
never shrinks, and a ragged table is never prettified. Differential testing
cannot cover these — if both implementations ate a row they would still agree —
so these are the tests that hold the property rather than the parity. They were
themselves verified by mutation: a delete that removes an extra row fails two of
them by name; an insert that swallows the following line fails three.

### Tier 2 — implied by Tier 1

`table-realign` (§6.2), because Tier 1 creates the ratchet described in §5.2 and
nothing else can repair it. Then `list-tables` / `table-get` (§6.1), because a
model that cannot address a table cannot call Tier 1 at all — `find` and
`outline` are the cheapest path to that.

**`table-realign` is built** — in both implementations, with six mutations and
three property invariants, and refusing tables whose width incise cannot measure
in characters (§5.2). It is the fourth entry in the executor's op list and the
only one with a single argument. `bench/FINDINGS.md` F-realign has the account,
including the two mutations that survive every invariant and why that is a
statement about layering rather than a gap.

**`table-get` is built** — in both implementations, and it is **not** an
`apply_op` entry: it returns text about a document rather than a new document,
so it does not fit that op's `(content, error)` contract. It sits on the same
read path as `render_table_list`, which also keeps the "unknown operation"
refusal — a measured sentence — from changing again. Ten mutations on the read
op and its `filter` argument, three more on the duplicate-column guard below,
and three property invariants — the ones a read needs and an edit does not: an unfiltered read reports every row unchanged, a filter returns a
subsequence whose rows actually match, and the rendered result parses back as a
table with the same cells.

Porting it turned up a divergence neither implementation could see on its own —
a header naming the same column twice, which the oracle resolved one way when
matching and another when writing. Refused in both, now, rather than resolved.
`bench/FINDINGS.md` F-dupcol has the account.

Tier 2 therefore stands at **10482 differential cases over 32 fixtures**, all
agreeing, with 56 mutations — all caught, none stale — and twelve invariants
behind them. (Tier 2b took those totals to 30085 cases over 39 fixtures, 93
mutations and 19 invariants; Tier 2c to 66127 over 40, 150 and 26, and the
`describe_change` addendum to 77580 over 43, 172 and 29, and F-nearmatch to
77805 over 43, 169 and 29. See below.)

`list-tables` is **not** optional infrastructure. It is the entire prompt Arm B
gave the model, so §1.2's numbers are a measurement of Tier 1 *and* of
`list-tables` together. Two of its details were forced by measurement: it must
include a per-heading **ordinal** (three tables under one heading in
`corpus/tables/multiple-per-section.md` are otherwise indistinguishable — the
model used the ordinal correctly 10/10 once given it), and a **caption**, the
label line above a table, restricted to lines ending in a colon. The
unrestricted version returned the tail of whatever paragraph preceded the table
— on `corpus/tables/ragged.md`, the mid-sentence fragment "treated as ragged and
left alone." A wrong label costs prompt tokens and misdescribes the table.

### Tier 2b — lists, now measured

`list-add-item`, `list-remove-item`, `list-set-checked` and `list-lists` (§6.4),
promoted out of Tier 3 by the list benchmark: **94/100 first-call, zero silent
corruption across 500 trials**, with the renumbering task at 10/10 against 0/10
direct (§1.3). Like `list-tables`, `list-lists` is not optional — it is the
entire prompt the model was given, so the numbers measure the ops and the
summary together.

Details Tier 2b must carry, all forced by measurement and all listed in §6.4:
the payload/selector naming rule, per-list convention preservation (marker,
delimiter, indent, loose/tight, checkbox spelling), and three distinct
numbering behaviours. One summary detail is worth calling out because it was a
bug: the list summary reports the **first item's actual marker**, so a list
numbered 5, 6, 7 is described as `5.` and not a tidied-up `1.` The summary is
the model's only view of the file and a false line in it is a defect even where
no current task depends on it.

`after` ships behind the §12 open question, not as settled surface.

**Tier 2b is built** — all four, in both implementations. Every convention above
is read off the list as found rather than normalized: the marker character, the
ordered delimiter (`.` against `)`), the indent, the gap after the marker, the
loose blank line, and the numbering. `after` is the only way to say "nested",
which is what makes `depth`, `indent` and `marker` arguments unnecessary and an
impossible depth unsayable.

Three things fell out of the port, all in `bench/FINDINGS.md`:

- **F-fence** — the two Python fence scanners disagreed about whether a closing
  fence may carry trailing words, so the same document had two answers to "is
  this line code?" depending on which op was called. Predicted by reading,
  exposed by a fixture written for it, and fixed on the side CommonMark says is
  wrong. There is one scanner now.
- **F-mixnum** — a sibling group mixing `1. x` with `- y` (legal below the top
  level) made the executor do arithmetic on `None` and report a `TypeError` to
  the model. Such a group is `irregular`, which is the answer that invents no
  change.
- **The list address was unchecked.** `resolve_list` read `heading` and
  `ordinal` raw where `resolve_table` checks them, so `{"list": {"heading": 7}}`
  crashed into the backstop and `{"list": {"ordinal": "0"}}` failed to coerce.
  §6.4 makes the two addresses one habit; both resolvers run the same checks
  now.

One divergence is recorded rather than fixed: `list-add-item`'s `position` is
compared only against the literal `"start"`, so every other value — including
ones `check_position` refuses on the table family — means "end". §1.3's numbers
came from this executor, so tightening it is a schema decision to be made and
re-measured rather than a quiet edit. *(Closed by FINDINGS F-address, which also
measured it as worse than this paragraph says: `"Start"` and `0` each meant
**start on a table and end on a list**, silently. A list now refuses an index
and points at `after`. The re-measurement is still outstanding.)*

With Tier 2b the totals stand at **30085 differential cases over 39 fixtures**
(13 synthetic), all agreeing, **93 mutations** — all caught, none stale — **19
property invariants**, and the same 5674 recorded tool calls replayed with none
changed. 37 of the mutations are the list family's, spread over the three layers
that can be wrong independently: the run parser, the conventions an inserted
item copies, and the dispatch's argument ordering.

### Tier 2c — sections, now measured

`section_edit`'s six actions and `outline` (§6.3), promoted out of Tier 3 by the
section benchmark: **80/100 first-call, 89.2% with one retry turn, 0.8% data
loss** against a direct-edit baseline of 19% correct and 28% data loss (§6.3) —
the largest measured gap of the three families, across 430 trials plus 77
retries plus 510 multi-turn plus 1179 replays. `outline` is not optional for the
same reason `list-tables` and `list-lists` are not: it is the entire prompt, so
the numbers measure the ops and the summary together.

This tier is *below* Tier 2b in build order despite the larger gap, because it
is the one family where the executor does not absorb the model's mistakes
(§6.3 / FINDINGS S1) — it needs three guards to reach those numbers, and the
guards are the deliverable as much as the actions are:

- **`replace-body` refuses a non-empty own body without `overwrite: true`**,
  with `overwrite` present in the schema so the acknowledgement is expressible.
- **`append` refuses a `heading`**, naming `insert` and `rename` in the error.
- **`insert` refuses a heading anywhere in `body`**, parsed rather than
  pattern-matched.

A fourth requirement is not a guard but the shape of a *success*: **`outline` is
what the model reads before it calls, and must not be what it reads after.** A
successful `section_edit` returns one line saying what changed and does not
return the outline (§5.4, §6.3.2, §9 criterion 11). This is the only Tier 2c
requirement that costs nothing to implement and removed three destroyed
documents (S14), and it is easy to lose in a port precisely because returning
the outline looks helpful.

All three are executor requirements: they hold whether or not the model reads
anything, and each was adopted on a counterfactual re-grade of already-collected
trials showing it costs zero correct answers. Two more details are forced by
measurement and easy to get wrong: contradictory address arguments must
*refuse*, not drop the one that fails to resolve (§6.3.1), and the refusal
messages are surface — the ordinal message as written led the one destructive
second turn in the project (§6.3.1, S12).

The naming constraint is part of the deliverable too, and it is the cheapest
item in this tier: **`section` is `{heading, ordinal?}`, and `path` means the
file**. A port that "tidies" the address back to `path` for symmetry with the
other two families reintroduces a defect worth 7 points and two destroyed
documents on the one task that provokes it (§6.3, §9 criterion 12, S15).

Section-plus-subsection ships as **two calls**. The one-call `children` payload
measured better where it applies and worse everywhere else (§6.3.1, S13); it is
waiting on a narrower tool, not on more evidence about this one.

**Tier 2c is built** — the six actions, `outline`, and the four-pass resolver, in
both implementations. All three guards are in the core rather than in the schema,
which is what "executor requirement" means here: `replace-body` refuses a
non-empty own body without `overwrite`, `append` refuses a `heading` (except an
echo of the section it already addressed), and `insert` refuses a heading
anywhere in `body` — parsed with the same parser the document goes through, so a
`# comment` inside a fenced block is prose and a heading arriving on the third
line is still refused.

The level is derived and never passed, so an impossible level is unsayable
rather than merely invalid; `insert` also re-parses its own output and refuses if
the heading it just wrote is not a heading there (`corpus/hazards/code-fences.md`
ends inside an unclosed fence, where a successful-looking write creates no
section).

**The result shape is now in the core too.** Tier 2c originally left
`describe_change` — one line saying what changed, instead of the outline, the
§5.4 / §9-criterion-11 requirement above — to a front end that does not exist,
on the grounds that it is not an op and needs `difflib`'s `get_opcodes` where
`similar.rs` ports only the ratio. That reasoning holds for the *first* half and
not the second: the core is the only place `difftest.py`, `mutate.py` and
`invariants.rs` can reach, so a requirement parked outside it is a requirement
nothing measures. It ships as `crates/incise-core/src/describe.rs`, held to the
oracle byte-for-byte like every op, and deliberately **not** in `OPS` or
`dispatch.rs` — it returns text about a change rather than a new document, the
same reason `table-get` sits off that path.

Completing `similar.rs` to get there turned up a defect in it, which
`bench/FINDINGS.md` F-extend records: two of `difflib`'s four extension loops
were omitted under a comment that conflated *popular* with *junk*. They are
provably inert below difflib's `n >= 200` autojunk threshold, which is why three
op families never noticed — every sequence the port had seen was a heading or a
column name. `describe_change`'s line tally is the first caller that crosses it.
The lesson is not about diffing: `similar.rs`'s `matches`, `longest_match` and
autojunk branch carried **no mutation and no invariant**, and a file with no
mutation is a file the differential suite has never been given a chance to
check. The gap was in the mutation list before it was in the code.

(F-nearmatch has since removed all four loops and the autojunk branch with
them. Once nothing purges the index the loops can only fire on a match the DP
failed to find, which cannot happen — so they are dead rather than restored, and
the port is smaller than when this paragraph was written. The lesson above is
unchanged; it is what found the defect in the first place.)

One item of this tier is still **not** in the core, and it belongs to the front
end:

- **The naming constraint.** The core accepts *both* `heading` and `path` inside
  the section address, with `path` winning when truthy, because the oracle does
  and byte-agreement is the port's contract. S15's adoption — `section` is
  `{heading, ordinal?}` and `path` means the file — is therefore enforced by the
  schema the front end publishes, not by the core. Accepting the old spelling is
  tolerance; *naming* it is the defect S15 measured.

One divergence is recorded rather than fixed, and it is the third of its kind:
the section resolver compares the ordinal with a raw `==`, not with the
`check_ordinal` that F-args gave the table and list families, so `{"ordinal":
"0"}` addresses a table and a list and refuses a section. §6.4 says the three
addresses teach one habit; they now disagree three ways (this, the list/table
ordinal, and `list-add-item`'s `position`). One decision on the shipping schema,
re-measured — not three quiet edits.

*(Closed by FINDINGS F-address. It disagreed four ways, not three: the section
resolver also skipped `check_heading`, so `{"path": 1}` was stringified to `"1"`
and hunted for where the other two families raise a typed refusal. All four are
now one habit. The re-measurement the paragraph asks for has not been run.)*

With Tier 2c the totals stand at **66127 differential cases over 40 fixtures**
(14 synthetic), all agreeing, **150 mutations** — 150/150 caught in one full
run, no survivors and none stale — and **26 property invariants**. The
`describe_change` addendum takes them to **77580 cases over 43 fixtures** (17
synthetic), **172 mutations** — 172/172 caught in a full run, no survivors,
none stale, re-run after F-autojunk and clean again — and **29 invariants**.
F-nearmatch then retired four `difflib-*` mutations by deleting the code they
anchored to, added one stronger replacement, and added the case family that
tells two near-match cutoffs apart, taking the totals to
**77805 cases over 43 fixtures, 169 mutations and 29 invariants**. F-address
reconciled the three addressing habits and added the coverage they had been
missing — eleven mutations, one synthetic fixture, and the section, list and
`position` case families — so the standing totals are
**84267 cases over 44 fixtures, 180 mutations and 29 invariants**.
The 5674-call grade-neutrality replay was *not* re-run, and did not need to be:
unlike Tier 2b, this tier did not move the oracle at all — `incise_ops.py` and
the corpus are byte-identical to their Tier 2b state, and every change is on the
Rust side or in the harness. 58 of the mutations answer to `-k section-`, 57 of
them written for this tier and one (`section-end`) already guarding the parser,
and six do nothing but swap the family's two
ends — `own_end`, where a section's own prose stops, against `end`, where its
subtree stops — because that swap produces a plausible edit in the wrong place
that two agreeing implementations cannot see.

"All caught" took two passes. Six of the 58 survived the first full run, and
the breakdown is the useful part: **one** was a missing document, four were
argument shapes the hand-written case list did not contain, and one was an
equivalent mutant with no distinguishing input, which was deleted rather than
left in the survivor list. The most instructive was `section-inert-case` — the
refusal branch that says "that heading is inside a code fence" instead of "not
found", §5.3's rule made concrete, which had executed **zero times** in 63584
cases because every query the harness built came from a real section's path.
A surviving mutation is evidence about the harness before it is evidence about
the code.

Read the clean sweep with the tail it hides: **nine of the 169 are caught by
five cases or fewer and two by exactly one.** That tail is not a stable
property of the suite — F-nearmatch watched it lengthen and shorten again for
reasons that had nothing to do with the mutations in it. `near-cutoff` went 1 →
31 when `bench/synthetic/long-cells.md` arrived, fell back to 1 when the fix
removed the heuristic that had been holding its probes near the cutoff, and
reached 76 only once `difftest.py` emitted a probe built to land between the two
cutoffs arithmetically rather than by accident. Those nine are the mutations one
fixture edit away from surviving, so a run is read by sorting on mismatch count
and looking at the bottom, not by checking the total.

Two of the new invariants are conditional, and the conditions are findings:
`rename` normalizes whitespace inside the heading span by design, so a heading
whose verbatim form is not its addressing form cannot round-trip through the op's
own vocabulary; and `set-level` is not invertible when a promotion changes which
siblings the subtree contains, because subtree membership is derived from the
document. A front end must not offer "undo the level change" as another level
change. `bench/FINDINGS.md` Tier 2c has both accounts.

### Tier 3 — unmeasured, and marked as such

Frontmatter (§6.5), scoped search/replace (§6.6), transactions (§6.7). Each is
plausible and none is measured. Build these only after extending the benchmark
to their families, or accept explicitly that they are being built on assumption
— and note that the list family is direct evidence this matters: it *inverted* a
conclusion the table family had reached (§1.3 result 8). Sorting, column ops,
and multi-op transactions are the easiest places to over-build ahead of
evidence.

Sections left this tier for Tier 2c: §6.3 is now measured across 430 trials plus
77 retries plus 510 multi-turn plus 1179 replays (FINDINGS S1–S14) and carries
its own requirements. What is still unmeasured *within* sections is the
move/sort pair named at the end of §6.3, and the `children` payload on a
narrower tool (§6.3.1).

## 12. Open questions

1. **Benchmark methodology.** *Partially resolved.* Both arms have run for three
   op families: `bench/FINDINGS.md`, 4009 trials, summarized in §1.1, §1.2, §1.3
   and §6.3. Method in `bench/PLAN.md`. Still open:

   - ~~The repeat-penalty confound.~~ **Resolved (F7).** A matched 60-trial
     control at `repeat_penalty: 1.0` moved the result by +1/60 (McNemar
     p = 1.000) and left the re-pad task at 0/10. The parameter was verified
     honored before the run rather than assumed, which mattered:
     `reasoning_budget: 0` *is* silently ignored by this server. §1.1 does not
     need rewriting downward.
   - ~~Only tables are measured.~~ **Three families now (tables, lists,
     sections).** That was worth doing twice over: the second family inverted a
     conclusion the first had reached (§1.3 result 8), and the third produced
     the only destructive outcomes in the project. What remains unmeasured is
     frontmatter (§6.5) and scoped search/replace (§6.6), and nothing in
     §1.1–§1.3 or §6.3 should be generalized to them.
   - **The three families are graded to three different standards,
     deliberately.** Tables have no goldens — `correct` means "passes every
     mechanical check." Lists are graded against exact goldens scoped to the
     target list, because a list's correctness *is* its formatting (§6.4) and a
     predicate for "numbered the way this list is numbered" is a golden written
     less legibly. Sections are graded against whole-document goldens stored as
     a minimal changed window, because a section edit can reach the whole file.
     Reports must state which standard they are quoting rather than say "no
     goldens."
   - The **read cost** claim in §1 has no measurement behind it at all.
   - **Effective N is below nominal N.** Trials differ only by seed and seeds
     collapse where the model is confident (1–10 distinct outputs per 10). The
     confidence intervals in §1.1–§1.3 understate uncertainty.
   - **The harness ceiling must be re-verified whenever a schema changes.**
     `bench/ceiling.py` runs every task's ideal call through every scheme; it
     must read 100% before an arm is run, or a harness bug is indistinguishable
     from a model failure. It caught nothing this round, which is the point.
   - **A single-turn harness cannot show you a broken task.** Two of the fifteen
     section tasks were defective and neither was visible until S13 gave the
     model four turns: with one call the model produced the answer key's shape
     and the defect stayed hidden; with four it disagreed, consistently, and was
     right. A 100% ceiling does not catch this — the ceiling asserts the ideal
     call reaches the golden, not that the instruction asks for it. Distinguish
     the two repair kinds when one is found: `insert-release-at-top`'s golden is
     byte-identical and only became *reachable*, while `insert-troubleshooting`'s
     golden *moved* a heading level, which is a caveat on every earlier number
     that used it (FINDINGS caveat 9).
   - **A prefix is reusable, not just a grade.** S8 established that grading is a
     separate pass, so an executor change costs no GPU. S14 is the same move one
     level up: to test what a model does *after* a call, the messages before that
     call can be replayed from disk and only the turn under test re-sampled.
     That makes the comparison paired by construction (McNemar, not Fisher) and
     spends sampling only where the behaviour lives — 1179 replays answered a
     question a fresh arm would not have answered at ten times the cost. Two
     conditions on using it: run the unchanged shape as a replication check
     (`outline` returned 9 continuations against the original 11), and exclude
     prefixes whose first call errored rather than grading them, because
     continuing after an error is correct behaviour.
   - **Size the arm against the base rate, not against the last report's
     fraction.** S15 aimed at S12's "6 of 15", read it as 6 of 150 trials, and
     spent 450 trials measuring p = 0.5. It was six of the fifteen *unrecovered
     failures* — ~1.3% pooled — and the behaviour turned out to live almost
     entirely on one task at ~20%. Re-running the detector over all 4137 section
     trials on disk diagnosed that for free (S8 again: grading is a separate
     pass), and 50 extra trials on the provoking task moved the same question to
     p = 0.0039. Two conditions on doing this: the concentrated task must be
     reported in its own stratum, never pooled, or one task wears the family's
     name; and a resume that treats an errored row as complete will silently
     thin whichever arm was running when the server hiccuped, which is a bias in
     exactly the paired design that made the arm cheap.

   One earlier concern is now settled: the `--ctx-size 65536` finding means the
   "small context" framing in §1 overstates the constraint *for this model*. The
   measured failures were not context-exhaustion failures — every fixture fit
   comfortably. §1 leads with the write-cost evidence for that reason.

2. **Ragged cell counts.** When a table row has more or fewer cells than the
   header (`corpus/tables/cell-edge-cases.md`), does incise normalize to the
   header's count or fail? GFM renders it; silently dropping a cell is the one
   unacceptable answer.
3. **Mixed line endings.** *Narrowed for tables (§5.2): match the target
   table's own line ending, refuse if that table mixes them.* Still open for ops
   whose target is not a self-contained block — section and list operations, and
   any op that inserts a new line adjacent to content it does not own.
4. **Nested and non-top-level content.** *Partially narrowed for tables.* A
   table inside a list item is now located and edited correctly, with its
   indentation preserved (§5.2) — the reference implementation initially
   de-indented it silently, which is the failure this question exists to
   prevent. Still open: tables inside blockquotes, and markdown inside
   `<details>` (`corpus/hazards/nested-blocks.md`, `html-blocks.md`).
   Reporting "not found" for a table that is plainly there remains the worst
   outcome.
5. **Unclosed fences.** `corpus/hazards/code-fences.md` ends with one. Treat the
   remainder as code, or recover and treat it as text? Either is defensible;
   it must be deliberate and documented.
6. **Heading-like edge cases in `outline`.** Do HTML headings and headings inside
   blockquotes appear? Are headings differing only in case or trailing whitespace
   duplicates? (`corpus/sections/duplicate-siblings.md`)
7. **Op naming.** *Resolved.* Arm B ran three narrow tools (`table-add-row`)
   against one broad tool with an action enum (`table_edit(action=…)`) on
   identical tasks and seeds: 46/60 vs 53/60, McNemar **p = 0.167**. Not
   significant, and the aggregate hid that they failed at different things — the
   broad tool was perfect at row addressing (20/20 vs 15/20) and much worse at
   positional values (3/10 vs 9/10).

   The tiebreak was the *failure mode*, not the rate: the broad tool's weakness
   was silent and wrong, the narrow tool's loud and recoverable. Fixing the
   silent one and keeping the broad shape was then measured rather than
   inferred — **single tool + ordered rows scores 57/60 with 0/60 silent
   corruption** (§1.2 result 5). Adopted: one `table_edit` tool, one untyped
   `values` argument accepting an object or an ordered array (§6.2).

8. **Does a schema warning prevent invented selector values?** **Answered — no
   (§1.3 result 9).** Measured directly on the list family, where the pressure
   was live: one sentence telling the model to omit the field rather than guess
   moved 91/100 → 94/100, **p = 0.55, not significant**, and every remaining
   failure is still an invented item text. A description can move *where* the
   model puts a value; it cannot stop one being manufactured. The fix is
   structural — remove the optional argument whose value the model cannot see,
   or have it take an ordinal instead of text. Unmeasured, and now the main
   open item for §6.4.

   The original table-family reading is kept below, because on *that* family
   the evidence is still only a bound and not a fix.

   §1.2 result 3 cost 21.7% of first calls **on the three narrow tools**; the adopted single-tool schema produced **zero** invented
   selectors in 60 trials, so the sentence has nothing left to prevent on this
   task set. Read that as a bound, not a fix: 0/20 on the one task that provoked
   it puts the true rate only below roughly 16%. The question becomes live again
   the moment a `where` is asked for on a column the request does not name, so
   the sentence — *"only include columns you have been told the value of"* —
   stays a candidate for the first op family that reintroduces the pressure.

9. **How do we stop the model dropping the `table` address?** *Resolved (B7).*
   Both candidates were run at 60 trials each against the adopted schema's
   57/60. Naming the address on every per-action line of the tool description
   scored **60/60** and supplied `table` on all 10 trials of the failing task,
   including the exact three seeds that dropped it. Accepting a bare heading
   string as shorthand scored 57/60 — *trial-for-trial identical* to no change
   at all, despite the model taking the shorthand 13/60 times. The prose fix is
   adopted (§6.2); the shorthand is kept in the executor as tolerance, not
   advertised in the schema. Token cost of the added sentence: +1 completion
   token on average.

   The general lesson, across the 240 trials of §12.7 and this question:
   **prose moved the outcome 3/3 times and schema structure 0/2 times.** But the
   contrast with result 5 matters — an ordered `values` array worked because it
   removed a *translation* the model was performing badly. A string address
   removed no translation: the model was not getting the address wrong, it was
   omitting it, and only prose could tell it not to.

   > **Do not carry that 3/3 vs 0/2 tally forward.** The list family reversed
   > both halves of it (§1.3 results 7 and 8): the same prose fix *lost* 19
   > points, and renaming one parameter — pure schema structure — gained 30 with
   > p = 1.9×10⁻⁹. The durable form of the lesson is the sentence above it, not
   > the tally: a change works when it removes a translation the model is doing
   > badly, and the tally only recorded which kind of change happened to do that
   > on the table family.

10. **What replaces the `after` argument?** *Open, and the largest known
    remaining defect in §6.4.* `after` positions a new list item by naming the
    text of the item it should follow. Every residual failure in the best list
    scheme is the model inventing a value for it — `"* current item"`,
    `"third child"`, `"* First asterisk item"` — for a list it has been shown
    only a summary of. §12.8 establishes that a warning does not stop this. Two
    structural candidates, neither measured:

    - **Drop it.** `position: start|end` plus a follow-up edit covers most of
      what `after` is used for, at the cost of two calls for "insert in the
      middle" and of losing the marker/indent inference that makes `after`
      express nesting without a `depth` argument (§6.4).
    - **Make it an ordinal.** `after: 3` cannot be invented from nothing the way
      a string can — the summary states the item count, so an out-of-range
      value is checkable and refusable rather than a silent near-miss.

    The second is preferred on the evidence but has the known cost that ordinals
    are position-addressing, which §3 rules out for *selecting* existing content.
    Inserting is not selecting, so the rule may not bind here; that distinction
    needs to be argued explicitly before it is adopted, not assumed.

11. **Where does a nested payload belong?** *Open, and it is a question about
    tool width, not about the field.* S13 measured `children:
    [{heading, body, children?}]` on `insert` and got both results at once: on
    the three tasks that need a section and a subsection, 12/30 → 26/30; on the
    twelve that never touch it, 115/120 → 103/120, with `malformed` going 0 → 3
    and `promote-api` — which cannot use the field at all — 8/10 → 4/10. The net
    is +2 across fifteen tasks, which is noise, and quoting the net is the
    mistake this question exists to prevent.

    The generalization: **a field is paid for by every task on the tool,
    including the ones that ignore it.** `section_edit` carries six actions, so
    the payers outnumber the users five to one. The measurable follow-up is to
    put `children` on a dedicated create-a-section tool, where the ratio
    inverts, and re-run the same fifteen tasks. Until that is run, sections ship
    without it and section-plus-subsection is two calls (§6.3.1).

    This also predicts something checkable about §12.10: whatever replaces
    `after` should be priced the same way, against the list tasks that never
    position an item, not against the ones that do.

12. **Should a second edit to an already-edited section refuse?** *Half closed
    by S14; the expensive half is now probably unnecessary.* 3% of single-call
    section trials made a further call after one that had already succeeded, and
    those trials were destructive 36% of the time against 1.1% for the rest
    (Fisher p = 3.2 × 10⁻⁵). The `overwrite: true` guard does not catch it:
    three of the four escalations set the flag. Two separable questions were
    raised, and the cheap one was measured first:

    - ~~Whether the **tool result** stating what changed — rather than the
      document's new outline — removes the behaviour on its own.~~ **Closed
      (S14): it does, and only if the outline goes away.** 0/300 continuations
      against 8/300, p = 0.0078; returning both strings changes nothing
      (6/300). Now §5.4, §6.3.2 and §9 criterion 11.
    - Whether the executor should **refuse a destructive op on a section this
      session has already edited**, regardless of `overwrite`. Still open, but
      the case for paying for it has weakened: with the response fixed there are
      no surviving `overwrite` escalations in 300 prefixes to protect against.
      That is conversation state in an executor that is otherwise stateless — a
      real architectural cost, and the cheap fix appears to have removed the
      motivation for it. Revisit only if a family other than sections shows the
      behaviour, or if a larger sample finds it below the 1.3% ceiling S14 could
      rule out.

    The general form is the one worth carrying: **a guard validated on a model's
    first call is not validated on its third.** Every guard in §6.3 was designed
    against single-turn evidence, and the multi-turn arm is the only place their
    failure mode is visible. S14 adds the corollary: **the cheapest place to fix
    a bad third call is what the first one returned.** Every other fix in §6.3
    is an addition to the executor; this one is a subtraction from the response,
    and it also cuts the tool result by 91%.

