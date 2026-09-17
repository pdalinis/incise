# bench/synthetic

Documents that are **not** corpus fixtures.

`corpus/` is a measured artifact: `bench/FINDINGS.md` quotes per-file trial
results against those 26 files, so it stays frozen. Every coverage gap that
needs a new document gets one here instead.

The gaps these close are all of one kind — the third row of FINDINGS' blindness
taxonomy. Differential testing cannot see an assumption both implementations
share; property invariants cannot see one an implementation shares with itself;
**both** are blind to an input the corpus does not contain. That third class is
the cheapest to close, because the fix is to add the input.

They live as files rather than as string constants because they have two
readers. `bench/difftest.py` runs them through both implementations, and
`crates/incise-core/tests/invariants.rs` asserts structural properties over
them. Two copies of a fixture is the same bet that produced F-fence — two
scanners, one test holding them together, and drift on the one point the test
could not see. One copy, two readers.

This file is `.md.txt` and not `.md` so that the loaders, which take every `.md`
in the directory, do not pick it up as a fixture. Nothing may be added to a
fixture in the way of a header comment for the same reason: the bytes are the
input. What each one is for is therefore recorded here.

## Tables

- **narrow-aligned.md** — a column whose content is narrower than the delimiter
  it must hold: a centred marker needs ` :-: `, so the floor is 5 even though
  nothing in the column is wider than one character. Every aligned corpus table
  is already wider than that, and the one narrow enough
  (`hazards/whitespace`) contains tabs, which make it ragged and skip
  re-padding entirely.
- **narrow-ragged.md** — the same floor, on the path that does not re-pad.
- **escaped-pipes.md** — escaped pipes in both an aligned and a ragged table.
  The corpus has exactly one document with an escaped pipe and its table is
  ragged for an unrelated reason (CJK cells padded to display width), so the
  aligned re-pad path over a `\|` cell is reachable nowhere else.
- **non-rectangular.md** — rows that disagree with the header on cell count,
  which every op refuses (`check_rectangular`). `corpus/tables/cell-edge-cases.md`
  has the short and long body-row forms; the delimiter mismatch has no fixture
  at all.
- **duplicate-columns.md** — a header that names the same column twice, which
  GFM permits and which nothing in the corpus does. Every name-to-cell path
  refuses it (F-dupcol) and every positional path still works, so this one
  fixture measures both halves of that claim.
- **realign-targets.md** — ragged tables that realign actually rewrites, in the
  three shapes the corpus cannot supply. Every corpus table that is CRLF,
  indented, or generously over-padded is *already aligned*, so realign returns
  it unchanged and the interesting paths through `rebuild` never run. CRLF
  catches a repair that silently converts the table to LF; indented catches a
  table nested in a list item falling out of it; over-padded is the only case
  that tells "widths from content" apart from "widths floored by what was
  there".
- **wide-ragged.md** — ragged tables holding a character wider than one display
  column, which realign refuses (`table-realign` counts width in characters, so
  it declines rather than producing a table that is aligned by that count and
  ragged on screen). `corpus/tables/cell-edge-cases.md` has a wide table and
  realign refuses it too, but that table is already aligned, so the refusal is
  incidental there and cannot be *provoked* — nobody would ask for a tidy-up.
  Here the wide cell sits in a table a user would plausibly ask to tidy, which
  is what turns the refusal into a reachable branch rather than a defensive one.
  Two width classes, because they are separate branches of the range table the
  two implementations duplicate by design: `日` is a fullwidth form, `🚀` is a
  multi-codepoint grapheme. The third table is the control — same shape, same
  raggedness, every cell ASCII — so realign applies to it and a corruption rate
  on the first two is attributable. `bench/tasks/tables_realign_width.json` is
  the task set, and FINDINGS F-width is why it exists.

  difflib's autojunk heuristic, which started at 200 elements. "Near matches:"
  comes from `get_close_matches`, which diffs the value the caller sent against
  the column's cells *by character*, so the 200 counts characters of that
  value — and no corpus cell is a tenth of the length needed to produce one.
  The heuristic, and the two extension loops in `find_longest_match` that exist
  to undo it, therefore ran zero times across the whole suite. Two rows are
  deliberate paraphrases of each other: that is what puts a second candidate
  near the 0.4 cutoff, so that purging one more element moves it across the
  line and shows up in the message, rather than being purged with no visible
  effect. `bench/difftest.py` probes it with each cell one word short of
  itself.

  It found what it was aimed at — 46 of those probes came back `Near matches:
  none` with a 98% match in the column — and F-nearmatch then removed the
  heuristic and the loops from both implementations. **The file keeps its place
  for a different job than the one it was written for:** it is the only document
  in the suite that exercises near-match ranking at a length where ranking was
  ever wrong, those 46 probes are the whole of the differential evidence for the
  change, and `difflib-autojunk-back` is the mutation that puts the heuristic
  back. Removing the heuristic did cost coverage elsewhere: these probes had
  also taken `near-cutoff` from one catching case to thirty-one without being
  aimed at the cutoff, and with autojunk off they score ~0.98 against their own
  cell — above either cutoff — so that fell back to one. `difftest.py` now emits
  a second probe per cell, a third of its words, which lands near 0.5 by
  construction. See FINDINGS F-nearmatch, F-autojunk and F-extend.

## Lists (Tier 2b)

- **list-fences.md** — a closing fence with trailing words after it. The strict
  rule is CommonMark: a closing fence is nothing but fence characters. Two
  scanners disagreed about whether the text after such a line is code, and no
  corpus file reaches the difference (F-fence). This file is that missing input.
- **list-shapes.md** — shapes the corpus has no reason to contain, each aimed at
  one branch of the parser: depth beyond two, a tab as both indent and marker
  gap, the empty-item alternation, a marker change ending a run mid-paragraph,
  `.` against `)`, and the near-misses that must *not* be items at all.
- **list-loose.md** — loose lists, which the ops must neither create nor
  destroy: a blank line between any two items makes the whole run loose, and an
  insert into one has to carry a blank with it.
- **list-crlf.md** — CRLF throughout, plus a task list. The line ending is read
  off the list about to be edited, so a list whose lines all end `\r\n` must get
  an inserted item that does too. `corpus/hazards/crlf.md` has a list, but a
  bullet one with no numbering and no checkboxes.
- **list-tasks.md** — task items in every shape the ops branch on. The corpus
  has thirteen checkboxes, all in one file, all in tight bullet lists, so
  `list-set-checked` reached its success path 38 times in a 27k-case run and
  `list-add-item`'s checkbox *inference* (a new item joins an all-task group
  already ticked off) had no all-task ordered or loose group to fire against at
  all. An all-task group and a deliberately mixed one, so the inference has both
  a case where it fires and a case where it must not.
- **list-mixnum.md** — a sibling group holding both ordered and bullet items:
  F-mixnum's input, and the one shape that made the oracle report a Python
  `TypeError` to the model instead of a document. A marker change ends a
  *top-level* run, so this can only happen among children, and nothing in the
  corpus does it. The three sections are the three positions the bullet can
  hold, and they are not interchangeable — a bullet in the middle breaks the
  sequential comparison partway, a bullet at the end breaks its last step, and a
  bullet *first* makes the group's leading number `None`, which is a second
  defect only that ordering reaches.
- **list-runs.md** — where one run stops and the next begins, which is the one
  part of the parser the corpus does not exercise. Two mutations survived a full
  run against everything else here: two blank lines no longer ending a list, and
  the four-column rule that makes an indented item code rather than a list. Both
  survived for the same reason — no fixture, corpus or synthetic, contained a
  list-shaped line at an indent of four or more outside a list, or two lists
  separated by exactly two blank lines. The tab line is not decoration: the
  threshold is the *expanded* width, so a single tab must be read as four.

## Sections (Tier 2c)

- **section-repeats.md** — a section whose full path is also the *tail* of a
  longer one. The resolver tries four passes narrowest-first — exact, folded,
  suffix, suffix-folded — and `suffix` matches everything `exact` does, so the
  order between them is only observable when a query is one section's complete
  path and another section's suffix. No corpus file has that shape: nothing in
  26 documents repeats a top-level heading's text deeper down, and reordering
  the passes therefore survived a full mutation run. `Notes` here is the full
  path of one section and the tail of three, `Install` of one and two, and
  `Install > Notes` asks the same question of a two-segment path, so the shape
  is covered at three depths. `macOS` is the control: no exact match at all, so
  it resolves through the suffix pass either way.

  The other five survivors of that run were **not** corpus gaps and did not get
  a file. Three were argument shapes the case list did not contain, one was an
  argument shape it contained without the heading needed to reach it, and one
  was an equivalent mutant. A missing document and a missing argument are the
  same blindness one level apart, and only the first is fixed here.

- **section-ordinal-mix.md** — a leaf that repeats under one parent *and*
  appears under another, so a suffix match returns hits whose ordinals are
  0, 1 and 0. That repeat is the only way the valid-ordinal list in the
  "no section with ordinal N" refusal can contain the same number twice, and
  neither of the two files that look like they would reach it does:
  `section-repeats.md` gives three *distinct* paths, which take the ambiguity
  branch instead, and `duplicate-siblings.md` gives repeats that all share one
  path, so their ordinals are 0, 1, 2 and never collide. `section-ordinal-dedup`
  survived a run on exactly this gap. The dedup was not dead code — it was
  correct code no document could exercise, which reads the same from a mutation
  run and is the opposite problem.

- **mixed-endings-section.md** — one section whose *own body* mixes CRLF and LF,
  which is the only input that reaches `_section_eol`'s refusal: the three
  body-writing ops read the ending off the section they are about to edit, and
  a section with two of them has no convention to match.
  `corpus/hazards/mixed-endings.md` mixes endings within the *file* and is the
  fixture that proves an op carries the right one through; every section in it
  is internally uniform, so the refusal is unreachable there and was unreachable
  everywhere. The other two sections here are uniform CRLF and uniform LF, which
  makes them the controls — the same instruction one section over applies in one
  call. `bench/tasks/sections_mixed_endings.json` is the task set, generated by
  `bench/make_mixed_endings_tasks.py`, and FINDINGS F-remedy is why it exists.

## Frontmatter (Tier 2d)

`corpus/frontmatter/rich.md` is the whole positive corpus — three of 26 corpus
files carry a block at all, one of those is TOML and one has no keys — so it is
the only fixture that constrains the family, and it is one author's YAML style
throughout: two-space nesting, sequences indented past their key, LF, and a body
after the block. These three files are the shapes that style does not reach.

- **front-shapes.md** — the YAML shapes `rich.md` does not contain, each aimed
  at one branch. Two of them found defects before any task was written.

  A **sequence written at its own key's indent** (`tags:` then `- flat` in
  column 0) is valid YAML and is what most static site generators emit; nothing
  in the corpus does it, because `rich.md` indents every sequence. Read the
  obvious way the key is null and the items are a *second, top-level* sequence
  — and `frontmatter-delete tags` then removes the `tags:` line and leaves the
  items behind, which is the family's worst available failure: a success that
  produces a document nothing can read. `list_of_maps` asks the same question of
  a sequence of maps, where the orphans would be worse still.

  **Four-space nesting** under `deep`, because a new key's indent is read off
  the siblings it joins, and a fixture that is two-space everywhere cannot tell
  that apart from a hardcoded 2.

  The rest are single branches: `empty_string: ""` beside `empty_null:`, which
  is the third leg of the absent/empty/null distinction `frontmatter-get` owes
  and the only one no file had; a `#` inside a URL fragment and a `#` inside
  quotes, neither of which is a comment, against a real trailing comment with a
  wide gap to hold; a single-quoted value containing `: `; and `"dotted.key"`,
  a key whose own name contains a dot, which **no spelling of `key` can
  address** — the path is split into segments before anything looks at the
  document. That one is a fixture for a *refusal*: it exists so the message
  says the key is unreachable rather than "no such key", which is what sends a
  model trying the same spelling four times.

- **front-crlf.md** — CRLF throughout, frontmatter included. The line ending is
  read off the block being edited, so a rewritten value line and an inserted key
  line must both carry one. `corpus/hazards/crlf.md` is CRLF and has no
  frontmatter; `rich.md` has frontmatter and is LF. This is `list-crlf.md`'s job
  one family over, and the defect is the same one `_table_eol` documents: a line
  rebuilt from parsed pieces silently drops the `\r` it arrived with.

- **front-edges.md** — the block's edges, in the three shapes that are all about
  where it stops. **One key**, so deleting it reaches "the last key is gone and
  the delimiters stay" — which `corpus/frontmatter/empty.md:9-12` states as a
  requirement and which no file could actually exercise, since emptying `rich.md`
  takes fourteen deletes. **No body at all**: the file ends at the closing
  delimiter, so an append lands against the end of the document rather than
  against a blank line. And a **`...` close**, which `mdlist.frontmatter_span`
  accepts by name and which nothing in the corpus writes; a key inserted at the
  end of that block must go above it, and a delete must leave it as written.

- **front-scalars.md** — the value and key *spellings* the other three do not
  reach, which are all branch conditions rather than shapes.

  **Block scalar indicators.** `rich.md` has a bare `|` and a bare `>`; the
  header pattern is two alternations wide because a chomping indicator may come
  before or after an indentation digit, so `|-`, `>+`, `|2`, `|2-` and `>-2` are
  five branches held up by nothing. Against them sit four near misses — `|x`,
  `||`, `>>` and `"|"` — which must read as ordinary scalars. Getting that
  wrong in either direction is silent: a block read as a scalar loses the lines
  under it, and a scalar read as a block claims lines that belong to the key
  after it.

  **A null item.** Three items under `bare_items`, of which the first is `-`
  alone and the second is `-` followed by a space. The second is the only input
  that reaches the branch rebuilding an empty item *without* that space — a
  trailing space no file wrote is the smallest possible byte-preservation
  failure, and the corpus has no empty list item in frontmatter at all. The tab
  after the dash under `tabbed` is the other half of that pattern's `[ \t]+`.

  **The two YAML quotings of a key**, which decide the name an address has to
  match: `'single'`, `'it''s'` with YAML's doubled-quote escape, `"say \"hi\""`
  with the backslash one, and `"back\\slash"`, where the two unescapings run in
  an order that matters. `rich.md` has one double-quoted key and no escape in
  it, so three of those four branches were unreached.

  **A sequence at its own key's indent, nested** (`deep_seq.nested`).
  `front-shapes.md` has that shape at the top level only, where the key's indent
  is 0 and a comparison against a hardcoded zero cannot be told from the real
  one.

- **front-dupes.md** — the same key written twice, at three depths and in three
  kinds. Nothing forbids it in a hand-edited block and nothing in the corpus
  does it, so the rule that resolves it was carried by one dict comprehension
  and no test: `{e.path: e for e in self.entries}` keeps the **last** value for
  a repeated key, so a set rewrites the second `title:` and a delete removes the
  second `tags:` — and the first stays, ignored, exactly as a YAML reader
  ignores it.

  The position is separate from the value, and both matter. A dict keeps a
  repeated key at its **first** appearance, so `build.jobs` is listed where the
  first `build:` put it while its value comes from the second — which is the
  order a change summary reads its notes out in. An implementation that took
  the first entry, or that re-sorted on the last, would agree with this one
  everywhere else in the suite.

- **front-escapes.md** — a backslash escape inside a *value*, where it meets the
  comment scanner. `front-scalars.md` has `"say \"hi\""` as a **key**, and that
  line has no `#` on it, so dropping the backslash rule entirely changes nothing
  there: the quote state flips twice and lands back where it started. The rule
  only shows when an escaped quote and a `#` are on one line. `escaped:` puts a
  real comment after one, so losing the rule swallows the comment into an
  unterminated string; `hidden:` puts the `#` inside the value, so losing the
  rule invents a comment out of half of it. `single_bs:` is the other side of
  the same condition — YAML has no backslash escape in single quotes, so `'a \'`
  ends at that quote and the `#` after it *is* a comment. `doubled:` and
  `trailing:` hold an even number of backslashes, which is the case that comes
  out right either way and is here so that "caught" means the odd ones.

- **front-absent-blank.md**, **front-absent-crlf.md** — no block, and the first
  byte is a newline. Creating a block puts a blank line between it and the
  document *unless the document already opens with one*, and no file in either
  tree opens with one: the whole branch was unreached, in both line endings.
  They are two files because a document has one line ending and the branch tests
  for both — an implementation that checked only `\n` would keep agreeing on
  every LF document ever written.

## `describe_change`

- **no-headings.md** — a document with a table, a list and prose, and **no
  heading anywhere**. `describe_change` derives its account from the heading
  list, so this is the one document where that list is *empty* on both sides:
  the matcher runs over two zero-length sequences, every branch that names a
  section stays silent, and the line-count backstop is the whole answer. Every
  one of the 26 corpus files has at least one heading, and every one has its
  first heading before any table or list, so an op that edits a document
  without touching a heading is reachable in the corpus but an op that edits a
  document *with no headings at all* is not.

  This is the same shape of gap as `section-inert-case`, the refusal branch that
  had executed zero times in 63584 cases because every query the harness built
  came from a real section's path — a branch guarded not by a rare argument but
  by a document nobody had written.

- **repeated-lines.md** — 232 lines, most of them duplicates of each other.
  Python's `difflib` runs an "autojunk" heuristic that purges any element
  occurring more than `len(b) // 100 + 1` times, **but only once `len(b) >= 200`**,
  and `describe_change`'s line tally is the first thing in either implementation
  that diffs a sequence that long. Below the threshold the heuristic is not
  merely unused, it is *unobservable*: moving the boundary, or shifting the
  purge comparison by one, changes nothing that any test can see. Both
  mutations survived a full run against everything else here.

  So the constraints on this file are arithmetic, not stylistic. It must exceed
  200 lines, and it must repeat lines often enough for the purge to bite —
  hence fifteen releases carrying an identical three-row table and an identical
  three-item audit. The two paragraphs of `Reviewed by the release group.` are
  not filler either: deleting `Release 3` leaves exactly three copies of that
  line in the after-document, and `232 // 100 + 1` is three, so it is the one
  element that sits precisely on the boundary between `<=` and `<`. Three ops
  distinguish the autojunk threshold and two distinguish the purge comparison.

  It is also the fixture that shows what the heuristic *costs*. Deleting an
  18-line section from it makes the oracle report `(+71 lines, -89 lines)`.
  That is `difflib`'s documented behaviour and the port reproduces it
  byte-for-byte, which is the contract — but a model reading that sentence is
  being told something false about its own edit, and FINDINGS records it as
  open rather than fixing it quietly on one side.

