# Benchmark findings

Status: tables complete (613 trials) · lists complete (600 trials) ·
sections complete (430 trials, both arms, + 77 retries + 510 multi-turn
+ 1179 replay + 600 rename) · **4009 trials** · 2026-09-07

What a local model actually gets wrong when editing markdown, measured rather
than assumed. This is the evidence base for `REQUIREMENTS.md`; where the two
disagree, this file is the record of what was observed and `REQUIREMENTS.md` is
what we decided to do about it.

- **Arm A** (F1–F7) — the baseline. Document in context, hermes-style
  find/replace `patch` tool. What editing markdown directly costs today.
- **Arm B** (B1–B7) — the proposed fix. No document in context, incise table ops
  executed by a Python reference implementation.
- **Lists** (L1–L6) — the second op family, both arms. Whether the design
  transfers to a vocabulary the model has never seen, and whether the table
  family's conclusions replicate. One of them does not (L2).
- **Sections** (S1–S15) — the third family, both arms, a fix arm, a
  multi-turn arm, a replay arm and a rename arm. Whether the *result* transfers. Not at
  first: this was the
  first family where the executor did not absorb the model's mistakes, and the
  first with measured data loss in Arm B (S1–S3). Two executor guards and a
  schema rewrite took it from 58% to 80% correct with data loss at 0.8% (S8,
  S9), against a direct-edit baseline of 19% correct and 28% data loss (S7) —
  the worst Arm A result in the project. One retry turn takes it to 89.2% (S12),
  and the fix that looked obvious after S10 turned out to cost six destroyed
  sections to buy three correct ones (S11). S13 closes S6 by measuring two
  candidate payload designs across 510 multi-turn trials, and finds the larger
  result somewhere else: a turn the model did not need is 32× more likely to
  destroy the document than one it did. S14 closes that in turn — a tool result
  that states what changed, *instead of* showing the document, takes the
  redundant turn to 0/300 (p = 0.0078) and is 91% shorter. S15 removes the last
  known schema defect: `path` meant the file *and* the heading path, and
  renaming the address to `section.heading` takes the task that provokes the
  collision from 53/60 to 60/60 (misfiling 9 → 0, p = 0.0039).

Method in `PLAN.md`. Raw trials in `results/trials*.jsonl` and
`results/armb*.jsonl`, grades in `results/graded*.jsonl` and
`results/armb*_graded.jsonl`, all regradable without re-spending GPU time.
Intervals and paired tests come from `bench/stats.py`; harness ceilings from
`bench/ceiling.py`, which must read 100% before an arm is run.

## Setup

| | |
| --- | --- |
| Model | gemma-4-26B-A4B-it (`gemma4-direct-q8`), llama.cpp, `127.0.0.1:8081` |
| Arm A | hermes-style `patch` tool call (find/replace), schema replicated verbatim |
| Arm B | incise table ops, executed by `incise_ops.py`, no document content in the prompt |
| Arm C | Arm B's tasks, seeds, prompts and schemas, executed by the release `incise` binary on a real file in a temp root mirroring the repo-relative path |
| Tasks | 6 table tasks (`tasks/tables.json`) + 10 list tasks (`tasks/lists.json`) + 15 section tasks (`tasks/sections.json`; three added after S1–S6, see caveat 6, and two more for S13), 10 trials each, seed = trial index |
| Conditions | Tables — A: `reasoning_off`, `reasoning_on`, `repen_off` (180); B: `scheme_a`–`scheme_g` (420 + 13 retries). Lists — A: `reasoning_off` (100); B: `list_naive`, `list_f`, `list_g`, `list_h`, `list_i` (500). Sections — A: `reasoning_off` (100); B: `section_naive`, `section_p` (200, 10 tasks), `section_g` (130, 13 tasks), + 77 retries; multi-turn (4 turns, 15 tasks): `section_g`, `section_2call`, `section_kids` (450 + 60 re-runs); replay (S14, turn 2 onward re-sampled from 393 fixed prefixes x 3 result shapes, 1179); rename (S15, 4 turns at `--result-shape delta`: `section_g`, `section_g_file`, `section_g_hpath`, 15 tasks x 10 trials + `promote-api` x 50 more, 600). **Arm C** (real binary, real files) — tables `scheme_f` (60), lists `list_g` + `list_h` (200), sections `section_g_hpath` at 4 turns (150) |
| Grading | Both arms share `grade.check_result` and one outcome taxonomy. Tables are graded by mechanical predicates with no goldens; lists against exact goldens scoped to the target list (L1); sections against whole-document goldens stored as a minimal changed window |
| Executor versions | `section_naive` and `section_p` were run against an unguarded executor and are reported both as run (v1) and re-graded under the S2/S3 guards (v2). `section_g` was run against the guarded executor. The S13 arms add a third guard: `insert` refuses a heading anywhere in `body`. S14 changes no executor behaviour, only what a successful call returns. Grading is a separate pass over raw trials, so an executor change is measurable without re-spending GPU time (S8), and S14 extends that: a *prefix* is reusable too, so only the turn under test costs GPU time |
| Sampling | Server defaults, unmodified — including `--repeat-penalty 1.15` — except the `repen_off` control, which pins it to 1.0 |

## Headline — Arm A (baseline)

| | reasoning off | reasoning on | rp=1.0 control |
| --- | --- | --- | --- |
| **correct** | **60.0%** | **60.0%** | **61.7%** |
| silent corruption | 30.0% | 36.7% | 31.7% |
| — data loss | 10.0% | 6.7% | 20.0% |
| — formatting | 11.7% | 20.0% | 8.3% |
| — outside target | 8.3% | 8.3% | 3.3% |
| failed to apply | 10.0% | 3.3% | 6.7% |
| completion tokens | 77 | **1266** | 74 |
| wall clock | 2.4 s | **37.1 s** | 2.3 s |

95% Wilson CI on correct: 47.4–71.4 for all three. **Nothing moved the headline
number** — not reasoning (F5), not sampling (F7).

Per task (correct / 10):

| Task | off | on | rp=1.0 | |
| --- | --- | --- | --- | --- |
| `update-cell-multi-table` | 10 | 10 | 10 | |
| `add-row-ragged` | **10** | **7** | 10 | reasoning *hurt* |
| `add-row-alignment-markers` | 9 | 8 | 9 | |
| `add-row-aligned-short` | 4 | 3 | 2 | |
| `delete-row-aligned` | **3** | **7** | 6 | reasoning helped |
| `add-row-aligned-repad` | **0** | **1** | **0** | never works |

## F1 — Alignment maintenance is the failure, isolated

`add-row-aligned-short` and `add-row-ragged` send a **byte-identical
instruction** against tables with **identical row content**. The only difference
between the two fixtures is whether the pipes line up.

| Fixture | Aligned | correct (reasoning off) |
| --- | --- | --- |
| `corpus/tables/ragged.md` | no | **10/10** (CI 72.2–100) |
| `corpus/tables/aligned.md` | yes | **4/10** (CI 16.8–68.7) |

An unplanned but clean natural experiment. The model parses the request,
finds the table, and produces the right cell values every time. It fails at
*maintaining the byte-alignment invariant*, and only when there is one to
maintain.

Escalating the same task confirms the mechanism. `add-row-aligned-repad` adds a
value (`hyperwidget-assembly`, 20 chars) longer than the widest existing column
(13), so every line of the table — including the delimiter row — must be
re-padded: **0/10 correct** with reasoning off, **1/10 with it on**.

**Consequence for the design.** The premise in `REQUIREMENTS.md` §1 is correct
but broader than the evidence. The measured cost is not diffuse difficulty with
markdown; it is one specific invariant, and it is the invariant §5.2's
re-padding rule makes free. This *narrows and strengthens* the case: incise
does not need to be better at markdown than the model, it needs to be better at
one arithmetic property the model cannot hold while also composing content.

It also means the highest-value operations to build first are the ones that
mutate an aligned table's column widths — `table-add-row` and `table-update-cell`
with re-padding — not the broader op surface.

## F2 — Failures are destructive, and silent

All six `wrong` outcomes in the first grading pass turned out to be the same
thing: the model **overwrote an existing row while adding the new one**. It
emits an `old_string` naming a neighbouring row and a `new_string` containing
only the new row — an add expressed as a replace:

```
OLD: | widget-core | active  | dana    |\n| gadget      | retired | rowan   |
NEW: | widget-core | active  | dana    |\n| sprocket    | active  | rowan   |
```

The `gadget` row is gone. Row count is unchanged, the patch applies cleanly, the
tool reports success, and nothing in the output signals the loss. In a real
session the model would move on.

This was hiding inside the generic `wrong` class, so the grader now has a
`destructive` outcome checked *before* `wrong` (see taxonomy change below). A
vanished row is the worst thing that can happen here and it should never again
be aggregated with "didn't do the edit."

**Consequence for the design.** Row loss is structurally impossible for an op
that takes a row address and an operation — there is no way to express
`table-add-row` such that it deletes a different row. This is the strongest
available argument for content-addressed ops (§5.1) over find/replace, and it is
about *safety*, not convenience or token count.

## F3 — Deletion fails at the schema, not at the markdown

Six of ten `delete-row-aligned` trials emitted `old_string` and `new_string`
**identical** — hermes's matcher rejects this outright, so no edit was applied:

```
OLD: '| gadget      | retired | rowan   |\n'
NEW: '| gadget      | retired | rowan   |\n'
```

The model located the correct row every time. It could not express "remove
this" in a find-and-replace schema, where deletion means passing an empty
`new_string`. This failure involves no alignment reasoning at all — it is
purely the affordance being wrong for the operation.

This is the one failure class that is a *loud* failure rather than a silent one:
the edit does not apply and the model gets an error. It costs a turn, not a
document.

**Consequence for the design.** `table-delete-row` earns its place as an
explicit named op on its own evidence, independent of the alignment argument.
It also supports the §11 open question on op naming: the *shape* of the tool
call determines whether the model can express its intent at all.

## F4 — Blank lines around tables are collateral

Three `collateral:content` cases were the model consuming or duplicating the
blank line immediately after the table:

```
@@ -13 +13 @@
-
+| hyperwidget-assembly | active | dana    |
```

Lower severity than F2 — no content is lost — but it is byte damage outside the
target region, and a table that runs directly into the following block is a
structural hazard.

**Consequence for the design.** Row insertion must be anchored to the table's
last row, not to the blank line after it, and the acceptance test for every
insert op should assert the trailing blank line survives.

## F5 — Reasoning is not a fix. It is a 16× tax for zero net gain

Both arms scored **exactly 60.0% correct**. Reasoning cost 1266 completion
tokens against 77, and 37.1 s against 2.4 s.

The paired test says this is not a near-miss that more trials would resolve —
it is a clean null. Across all 120 paired trials there were 18 discordant pairs,
split **9 / 9**: nine tasks reasoning fixed, nine it broke. McNemar p = 1.0.

The redistribution is the interesting part, because it is not noise:

| Task | off | on | What reasoning did |
| --- | --- | --- | --- |
| `delete-row-aligned` | 3 | **7** | Solved the schema confusion in F3 — it works out that deletion means an empty `new_string` |
| `add-row-ragged` | 10 | **7** | *Made it worse.* Thinking about the table makes the model want to tidy it |
| `add-row-aligned-repad` | 0 | 1 | Changed the failure mode entirely — see F6 |

**Consequence for the design.** This closes off the obvious alternative to
building the tool. "Give the small model more thinking budget" is not a fix for
markdown editing: it reallocates errors at 16× the cost, and on the one task the
model was already perfect at, it actively causes damage. A deterministic tool is
not competing against a model that could get there with more compute.

It also means incise's value is *larger* than the correctness numbers suggest.
If an agent runs reasoning-on by default, every table edit costs ~1266 tokens
and 37 s to land at 60% correct. A tool call that is right by construction
replaces both the tokens and the latency, not just the errors.

## F6 — Under reasoning, the model attempts the re-pad and fails the arithmetic

The most design-relevant single result in the run.

With reasoning off, the model mostly did not re-pad at all — it appended a row
of the wrong width and left the table ragged. With reasoning on, on
`add-row-aligned-repad`, it **correctly worked out that every line of the table
must be widened**, and rewrote all of them:

```
-| Component   | Status  | Owner   |          +| Component             | Status  | Owner   |
-| ----------- | ------- | ------- |          +| --------------------- | ------- | ------- |
-| widget      | active  | peter   |          +| widget                | active  | peter   |
-| widget-core | active  | dana    |          +| widget-core           | active  | dana    |
```

Right procedure. Wrong count. `hyperwidget-assembly` is 20 characters, so the
column needs to be 22 wide; the model padded the existing rows to **23** and the
new row to **24** — inconsistent with each other *and* with the correct answer.
8/10 reasoning-on trials failed this way.

So the failure is not conceptual. The model knows the rule, applies the rule,
and cannot count characters reliably enough to execute it. Reasoning converts
"didn't try" into "tried and missed by one," which is *harder to spot* and
therefore worse.

**Consequence for the design.** This is the cleanest possible statement of what
incise is for. The tool's advantage over a competent model is not knowledge or
reasoning — it is that `max(len(cell))` is exact and free in Rust and
probabilistic in a language model. It also means:

- Re-padding is the highest-value single behaviour in the tool, and it should be
  correct-by-construction rather than an option.
- Any future prompt-engineering mitigation is a dead end. You cannot prompt a
  model into reliable character counting.

## F7 — The repeat penalty is exonerated. The premise survives

The largest threat to everything above was that `--repeat-penalty 1.15` — hostile
to reproducing repeated tokens, and markdown tables are almost entirely repeated
tokens — was manufacturing the corruption this project exists to fix. If so, the
honest answer would have been "fix your sampling params."

It was not. `repen_off` is identical to `reasoning_off` except `repeat_penalty`
is pinned to **1.0** instead of inheriting the server's 1.15:

| Task | rp=1.15 | rp=1.0 | Δ |
| --- | --- | --- | --- |
| `add-row-aligned-short` | 4/10 | 2/10 | −2 |
| **`add-row-aligned-repad`** | **0/10** | **0/10** | **0** |
| `add-row-ragged` | 10/10 | 10/10 | 0 |
| `add-row-alignment-markers` | 9/10 | 9/10 | 0 |
| `delete-row-aligned` | 3/10 | 6/10 | +3 |
| `update-cell-multi-table` | 10/10 | 10/10 | 0 |
| **TOTAL** | **36/60** | **37/60** | **+1** |

McNemar on the 9 discordant pairs: 4 / 5. **p = 1.000.**

The re-pad task stayed at **0/10 with the penalty removed entirely**. Removing
the sampling pressure that supposedly caused the corruption changed nothing
about the corruption. F1 and F6 stand as capability findings, not artifacts, and
`REQUIREMENTS.md` §1 does not need rewriting downward.

The parameter was verified honored *before* the run rather than assumed —
`runner.py --probe-repen` decodes greedily at `repeat_penalty` 1.0 vs 1.9 and
confirms the outputs differ (78 vs 3468 tokens; the extreme value makes the
model babble). Given that `reasoning_budget: 0` *is* silently ignored by this
same server, an unverified null here would have been worthless.

**Secondary observation, underpowered.** Data loss roughly doubled with the
penalty removed — 6/60 → 12/60 (10% → 20%), driven by `add-row-aligned-short`
producing 6 destructive trials. McNemar 2 / 8, **p = 0.109**: suggestive, not
significant, and the Wilson intervals overlap (4.7–20.1 vs 11.8–31.8). A
plausible reading is that the repeat penalty was mildly *suppressing* the
replace-style patch that destroys a neighbouring row, since that pattern
requires re-emitting a nearby row verbatim. Not established. If it holds, the
operator's default is accidentally protective and the 10% headline figure is the
optimistic one — which would strengthen the case for the tool, so it is not
worth chasing before building.

## Arm B — the op vocabulary, measured against a mock

120 trials, `bench/armb.py`, executor `bench/incise_ops.py`, reasoning off.

The model is given **no document content at all** — only a structural summary
(heading path, caption, column names, row count) — and must emit one incise op
that names the table and the row by content. This tests the load-bearing claim
in `REQUIREMENTS.md` §2 directly.

Two tool vocabularies, identical tasks, identical seeds:

| | |
| --- | --- |
| `scheme_a` | three narrow tools — `table-add-row` / `table-update-cell` / `table-delete-row` |
| `scheme_b` | one broad tool — `table_edit(action=add-row\|update-cell\|delete-row)` |

**Harness ceiling verified first.** Twelve hand-written ideal tool calls (six
tasks × two schemes) grade `correct` through the same path, so the ceiling is
100% and every failure below is the model's, not the harness's.

### B1 — Headline: the operation the model could never do is now free

| | A1 direct edit | B `scheme_a` | B `scheme_b` | B `scheme_a` +1 retry |
| --- | --- | --- | --- | --- |
| **correct** | **60.0%** | **76.7%** | **88.3%** | **98.3%** |
| 95% CI | 47.4–71.4 | 64.6–85.6 | 77.8–94.2 | 91.1–99.7 |
| silent corruption | 30.0% | 1.7% | 11.7% | **0%** |
| — data loss | 10.0% | **0%** | **0%** | **0%** |
| loud failure | 10.0% | 21.7% | 0% | 0% |
| completion tokens | 77 | 66 | 70 | — |

> **Correction.** This row originally read 0% for both schemes, because the
> harness computed silent corruption as `collateral + destructive` and excluded
> `wrong`. `wrong` means the document was modified, incorrectly, with no error
> raised — silent by any reasonable reading. The exclusion cost nothing in Arm A
> (30.0% under either definition) but understated `scheme_b`, whose seven B4
> failures are all `wrong`. Both the metric and this table now include it. The
> honest arc is **30% → 11.7% → 0%**, where the last step is B6's ordered rows —
> which makes the fix load-bearing rather than decorative.

Paired against the same-seed A1 trials: `scheme_b` vs A1 has 29 discordant
pairs split 6 / 23, **McNemar p = 0.0023**. `scheme_a` vs A1 is 10 / 20,
p = 0.099.

Per task (correct / 10):

| Task | A1 off | `scheme_a` | `scheme_b` | |
| --- | --- | --- | --- | --- |
| `add-row-aligned-repad` | **0** | **10** | **10** | the impossible task |
| `add-row-aligned-short` | 4 | 10 | 10 | |
| `add-row-ragged` | 10 | 10 | 10 | |
| `update-cell-multi-table` | 10 | 2 | 10 | see B2 |
| `delete-row-aligned` | 3 | 5 | 10 | see B2 |
| `add-row-alignment-markers` | 9 | 9 | **3** | **regression — see B4** |

`add-row-aligned-repad` is the result to keep. It went **0/10 → 10/10**. F1 and
F6 established that this task is not merely hard for the model but essentially
impossible — reasoning-on scored 1/10 by attempting the arithmetic and
miscounting. Moving the width calculation into the executor did not improve it;
it removed it.

**Comparability caveat, stated plainly.** A1 and Arm B are not measuring the
same job. Arm B removes formatting from the model's work *by construction* —
that is the tool's entire value, but it means `correct` in Arm B means "the
model addressed the edit correctly," with formatting correctness supplied by the
executor and verified separately by the oracle pass. The comparison is
legitimate as an end-to-end outcome comparison. It is not evidence that the
model got better at markdown.

### B2 — The model invents cell values it cannot see

Every `scheme_a` failure was the same mechanism, and it is one the direct-edit
arm could not exhibit: the model **over-specified the row selector with
confabulated values**.

```
delete "the gadget row"   →  where {Component: "gadget", Owner: "unknown", Status: "active"}
                             (the row is actually  retired / rowan)

resize host stage-1       →  where {Host: "stage-1", Region: "us-east-1"}
                             (stage-1 is in us-west-2)
```

`Owner: "unknown"` is invented outright. The model knows a row selector wants
columns, cannot see the values, and fills them in anyway. 13 of 120 trials.

This is a **new failure mode created by hiding the document**, and it is the
honest cost of the §2 no-content-in-context claim. It is also, importantly, the
*benign* kind: the selector matched nothing, so incise refused and the document
was untouched.

**Consequence for the design.** Strict matching is correct and must stay. The
tempting relaxation — "if the full selector matches nothing, retry with the
subset that does" — would silently discard a constraint the model asserted, and
that is precisely the road to deleting the wrong row. Refuse, and spend the
error message instead (§5.3).

### B3 — Loud failures recover in one turn. Measured, not assumed

The safety argument for content-addressed ops is that their failures cost a turn
rather than a document. "Costs a turn" is a claim about whether the model can
act on the error, so it was measured: each of the 13 `op_error` trials was
replayed with the tool result appended.

**13 / 13 recovered on the next call.** `scheme_a` goes 46/60 → **59/60 (98.3%)**
with one extra turn.

This required fixing the error text first, and the fix is the finding. The
original message reported `next(iter(where))` — which picked *the one key that
matched*:

```
no row where Component="gadget".
  Near matches: gadget
```

Incoherent: it names the correct part of the selector as the problem. The
message now identifies the intended row by scoring each candidate on how
*identifying* its matched values are — `1/(rows sharing that value)`, so a
unique value beats one shared by two rows — then names the conflict and supplies
a selector that is verified unique before being suggested:

```
no row matches all of {Component="gadget", Owner="unknown", Status="active"}.
  Row 3 matches on Component, but you said Owner="unknown" but it is "rowan",
  you said Status="active" but it is "retired".
  `where` only needs enough columns to identify one row. Send {"Component": "gadget"}.
```

An earlier version of this scoring picked the first row matching *any* key,
which selected `widget` on `Status="active"` and then advised sending
`{"Status": "active"}` — a selector matching two rows. Suggestions are now
checked for uniqueness before they are offered.

**Consequence for the design.** §5.3's "error messages are the product" is not a
slogan; it converted a 21.7% failure rate into a 1.7% one at the cost of one
round trip. The recovery rate is a first-class acceptance criterion for the Rust
implementation, not a nice-to-have.

### B4 — Named `values` introduces a mapping the model gets wrong

The one place Arm B is **worse** than direct editing. `add-row-alignment-markers`
says: *"Add a row with the values i, j, k and l"* against columns
`Default | Left | Center | Right`. Values are given **positionally, with no
column names**.

Editing the document directly, the model writes `| i | j | k | l |` and is
trivially right — 9/10. Given a `values` object keyed by column name, it must
perform a positional→named translation, and it garbles it:

```
{"Default": "i", "Left": "k", "Center": "j", "Right": "l"}   ← 4 trials
{"Default": "i", "Left": "h", "Center": "j", "Right": "k"}   ← 1 trial ("h" is from the row above)
```

`scheme_b` scored **3/10** here, against 9/10 for both `scheme_a` and A1.

**Consequence for the design.** `values` should also accept an **ordered array**
matching column order, so positional intent can be expressed positionally
instead of being translated. This is a concrete spec change earned by
measurement, and it is untested — the array form should be measured before it is
committed to Rust.

### B5 — Op naming: no significant difference, but the failure modes differ

`scheme_a` 46/60 vs `scheme_b` 53/60; 19 discordant pairs split 6 / 13,
**McNemar p = 0.167**. Not significant at n = 60.

The aggregate hides that the two fail at *different things*, and neither
dominates:

| | `scheme_a` | `scheme_b` |
| --- | --- | --- |
| row addressing (`where`) | 15/20 — invents selector columns (B2) | **20/20** |
| positional values (B4) | **9/10** | 3/10 |

**Consequence for the design.** The naming question in §12.1 does not resolve on
correctness, so it should be decided on the failure modes: `scheme_b`'s
advantage is on row addressing, which fails *safely and recoverably* (B3), while
`scheme_a`'s advantage is on value mapping, which fails *silently with wrong
content*. Prefer `scheme_b`'s single-tool shape and fix B4 with an array form —
a combination that has not yet been measured, and should be. **Now measured —
see B6.**

### B6 — The ordered row form eliminates silent corruption outright

B4's fix, measured. Three variants of `scheme_b`, 60 trials each, all six tasks
— not just the failing one, because a second way to express a row can degrade
the five tasks already at 10/10:

| | shape of the row argument |
| --- | --- |
| `scheme_c` | one `values` field, `oneOf: [object, array]` |
| `scheme_d` | two fields — `values` (object) and `row` (array) |
| `scheme_e` | one `values` field, **untyped**, both shapes described in prose |

| scheme | correct | rate | 95% CI | **silent corruption** | loud `op_error` |
| --- | --- | --- | --- | --- | --- |
| `scheme_a` | 46/60 | 76.7% | 64.6–85.6 | 1 | 13 |
| `scheme_b` | 53/60 | 88.3% | 77.8–94.2 | **7** | 0 |
| `scheme_c` | 57/60 | 95.0% | 86.3–98.3 | **0** | 3 |
| `scheme_d` | 58/60 | 96.7% | 88.6–99.1 | **0** | 2 |
| `scheme_e` | 57/60 | 95.0% | 86.3–98.3 | **0** | 3 |

Per task, correct/10:

| task | a | b | c | d | e |
| --- | --- | --- | --- | --- | --- |
| add-row-aligned-repad | 10 | 10 | 10 | 10 | 10 |
| add-row-aligned-short | 10 | 10 | 10 | 10 | 10 |
| add-row-alignment-markers | 9 | **3** | 7 | **10** | 7 |
| add-row-ragged | 10 | 10 | 10 | 9 | 10 |
| delete-row-aligned | 5 | 10 | 10 | 9 | 10 |
| update-cell-multi-table | 2 | 10 | 10 | 10 | 10 |

**On raw correctness the gain is not significant** at n = 60 — `scheme_b` vs
`scheme_c` splits 2/6, McNemar p = 0.289; vs `scheme_d` 2/7, p = 0.180. Read the
headline column instead:

> **Silent corruption 7/60 → 0/60. McNemar p = 0.0156.**

That is the result. All seven of `scheme_b`'s failures were the same `wrong`
outcome — the garbled positional→named translation of B4, which writes a
plausible, well-formed, *incorrect* row. Give the model a way to state a row
positionally and the entire failure class disappears. Every remaining failure
across all three variants is a loud refusal with the document untouched.

**`oneOf` is inert. The prose carries it.** `scheme_e` is `scheme_c` with the
union type deleted, and it did not merely score the same — trial for trial, all
**60/60 tool calls were byte-identical**, same three failures on the same three
seeds. This model reads the description and ignores the type constraint. Since
`oneOf` is unevenly supported by constrained decoders and by MCP clients, the
portable schema costs nothing here. (One model, one server: a client that
*validates* rather than merely decodes could still reject an untyped property.)

**`scheme_d`'s second field creates its own failures.** Two of its three
op_errors were caused by having two ways to say one thing: the model filled in
*both* `values` and `row`, and once used `row` as a *selector* on `delete-row`
where `where` was required. It bought 10/10 on the B4 task and paid for it on
two others — hence 9/10 twice, where `scheme_c`/`scheme_e` are 10/10.

That both-fields case turned out to be worth accepting rather than refusing. In
2 of 3 occurrences the two fields **agreed exactly**, so refusing spent a turn to
arrive at the same bytes. `incise_ops.py` now resolves both and accepts iff they
are identical — which recovered one trial (`scheme_d` 57 → 58). This is *not*
the relaxation rejected for `where` in REQUIREMENTS.md §6.2: that one would have
discarded a constraint the model asserted and changed which row was affected.
Here nothing is discarded and there is no ambiguity to resolve; if the two
disagree by one cell we still refuse, because then one of them is wrong.

**The remaining failure is not about values at all.** All three `scheme_c` /
`scheme_e` op_errors are the same thing: on the two-table file, the model emitted
`{"action":"add-row","path":"…","values":["i","j","k","l"]}` and **omitted the
`table` address entirely** — even though `table` is in the schema's `required`
list (see Server facts). It refuses correctly and names both candidates, so it
is loud and recoverable, but it is an *addressing* defect that will recur in
every op, and it should be fixed by making the address harder to drop, not by
choosing a values shape.

**Consequence for the design.** Adopt `scheme_e`: the single-tool `table_edit`
shape, one `values` argument accepting either an object keyed by column name or
an array in column order, described in prose and left untyped. `scheme_d`'s
edge on one task does not pay for a second field that the model then misuses as
a selector. Ordered arrays must stay **strict about length** — silently padding
a short array puts every value in the wrong column and produces a well-formed,
wholly wrong row, which is exactly the failure this change exists to remove.


### B7 — The last failure was a description bug, not a schema bug

B6 left one failure mode: the model omitting the required `table` address,
3/60, all on files with more than one table. Two candidate fixes, each built on
`scheme_e` so the only variable is the one under test:

| | change from `scheme_e` |
| --- | --- |
| `scheme_f` | **prose only** — name `table` on every per-action line and say it is required |
| `scheme_g` | **shape** — `table` also accepts a bare heading string, not just an object |

| scheme | correct | rate | 95% CI | `op_error` |
| --- | --- | --- | --- | --- |
| `scheme_e` | 57/60 | 95.0% | 86.3–98.3 | 3 |
| `scheme_f` | **60/60** | **100%** | **94.0–100** | **0** |
| `scheme_g` | 57/60 | 95.0% | 86.3–98.3 | 3 |

**Prose fixed it; loosening the shape did nothing.** `scheme_f` supplied the
address in 10/10 trials on the task that had lost it — *including seeds t1, t6
and t9, the exact three that dropped it in both other variants*. `scheme_g` was
inert: same 95.0%, and the same three seeds failed. Its shorthand was used in
13/60 calls and bought nothing.

> **Superseded in part by L2/L3/L4.** The same prose change, ported verbatim to
> the list family, *lost* 19 points (`list_naive` 80% → `list_f` 61%,
> p = 0.00088). It only helps once the parameter names it describes are mutually
> exclusive; prepending the address to every action line pushes the
> distinguishing field name later, which amplifies any name collision already
> present. The table family had no collision (`values` vs `where`) and so never
> saw the cost. Read this section as "prose fixed it *here*", not as a general
> rule, and read L3 first.

This is the second time the same lever has moved the result and the second time
the schema has not. B6: deleting a `oneOf` union changed 0 of 60 outputs. B7:
adding one sentence to a description closed the last gap. **The description is
the interface this model actually reads; the JSON Schema is decoration.** That
is worth designing around, not just noting.

`scheme_g` is also a caution against the reflex that produced B6's fix. Ordered
`values` worked because it removed a *translation* the model was performing
badly. A string address removes no translation — the model was not getting the
address wrong, it was omitting it — so the same move applied to a different
cause did nothing. Loosening a shape only helps when shape was the problem.

**Two fixes, and they were independent.** `scheme_f`'s 60/60 is not the prose
alone. Its one non-address failure was a *stringified argument*:

```
scheme_f  "where":  "{\"Component\": \"gadget\"}"     ← object serialized to a string
scheme_g  "values": "i, j, k, l"                       ← comma string, not an array
scheme_g  "table":  {"\"heading\"": "Ragged > ..."}    ← object key with literal quotes
```

The executor now recovers the first and third and refuses the second. The rule
is the one from §6.2: **parse what parses, refuse what would have to be
guessed.** A string that JSON-parses to the expected type recovers the call with
nothing invented; `"i, j, k, l"` does not parse, and splitting it on commas
would be guessing at cell boundaries — exactly the failure class ordered rows
exist to prevent. Re-grading the recorded trials with the fix moved `scheme_f`
59 → 60 and `scheme_g` 55 → 57, with no scheme regressing.

The original error text for the stringified `where` was `no column "{"` — a
report of the *consequence* three layers downstream of the cause. Under §5.3
that is the bug, independent of whether the call is recoverable.

**Consequence for the design.** Adopt `scheme_f` — `scheme_e`'s schema with the
address named on every action line. The `table` shorthand is not adopted: it is
measurably inert and a second accepted shape is surface area. The *executor*
keeps its tolerance for both the string address and stringified arguments,
because tolerance costs nothing and the schema is not a guarantee (Server
facts). Mean completion tokens are unchanged, 66 against 65.

**60/60 is not "always."** The Wilson lower bound is 94.0%, the six tasks are
one family, and effective N is below nominal N (caveat 2). The honest claim is
that no failure remains *that this benchmark can see*, which is the signal to
extend the benchmark rather than to declare the problem solved.

---

## F-minicpm5 — singleton compatibility ships; the broad small-model profile does not

The executor compatibility change clears its live gate. The preregistration was committed at `8b25162` before outcomes were inspected. Arm C then ran 18 MiniCPM5 calls through the real binary: **18/18 correct**, including **9/9** `values: [{...}]` calls normalized to named rows, with zero loud refusal, silent corruption, or data loss. The first two pool names are retained but invalid: the initial process could not reach localhost, and `_v2` used a relative binary path inside Arm C's temporary working directory. `_v3` is the valid pool.

The broader `safe-small` composition does not clear its gate. On the 90 preregistered supported-operation pairs, `compose_5` was **40/90 correct (44.4%)** and `safe_small` was **30/90 (33.3%)**. Discordants were 23 control-only and 13 treatment-only, exact paired McNemar p = 0.1325. The pooled null is not a license to ship: the family gate and safety gate both fail, and the directions are strongly heterogeneous.

| Family | Control | `safe_small` | Control-only / treatment-only | Exact p | Data loss | Silent corruption |
|---|---:|---:|---:|---:|---:|---:|
| Tables | 10/15 | 11/15 | 3 / 4 | 1.0000 | 0 → 1 | 2 → 3 |
| Lists | 8/21 | **15/21** | 1 / 8 | **0.0391** | 0 → 0 | 8 → 3 |
| Sections | 8/27 | 4/27 | 5 / 1 | 0.2188 | 1 → 0 | 8 → 4 |
| Frontmatter | **14/27** | **0/27** | 14 / 0 | **0.0001** | 5 → 0 | 9 → 4 |
| Pooled | 40/90 | 30/90 | 23 / 13 | 0.1325 | 6 → 1 | 27 → 14 |

The list result is real and narrow: publishing `list_get` with `list_add_item` raised supported add-item correctness by seven pairs, cut silent corruption from 8 to 3, and reduced mean completion tokens from 243 to 177. It deserves an isolated list-profile follow-up rather than being buried inside a rejected cross-family bundle.

The failures explain what comes next. Frontmatter inspection caused MiniCPM to copy type wrappers into the edit value (`{"integer": 8}`, `{"type": "string", "value": ...}`, or `{}`), turning all 27 treatment trials into failures. Section-specific tools did not cure invented ordinals or unrelated follow-up calls. The table treatment's single destructive result happened after continued mutation. Across primary treatment trials, more than one mutation occurred in 2/15 table, 2/21 list, 16/27 section, and 17/27 frontmatter trials. An inspect tool is therefore not a substitute for orchestration that stops after the requested successful mutation.

The subtree guard did its safety job but not its recovery job. In all three `delete-install-macos` control seeds MiniCPM failed to add `subtree: true`; the operation remained a loud refusal rather than deleting descendants. No destructive delete passed the guard. Structured repair remains adapter-tested, not independently live A/B measured.

Disposition: keep the singleton normalization in core; keep `list_get`, typed frontmatter reads, action-specific schemas, structured repairs, and the opt-in profile as experimental building blocks; do not make `safe-small` the default or claim a general MiniCPM gain. The next live work should isolate the list pair, redesign frontmatter read output for scalar copying, and add a host-enforceable one-successful-mutation stop before retrying tables or sections. Earlier benchmark claims remain current for their exact schemas and pools.

Raw and graded pools use the `bench/results/minicpm5_roadmap_*_20260921` prefix. `bench/results/minicpm5_roadmap_analysis_20260921.json` contains the paired counts, diagnostics, input hashes, and artifact hashes.

## F-minicpm-routed — orchestration wins accuracy and efficiency, but one missing guard blocks adoption

The routed single-mutation arm was preregistered at `cc97711` and paired against the 90 existing `compose_5` control observations. The treatment assumed perfect family/action routing, exposed only the required read or write tool, forced function choice, used typed frontmatter setters, and stopped after the first mutation response. Temperature 0.7, top-p 0.95, prompts, fixtures, seeds, executor, and grader remained fixed.

The primary endpoint moves: **40/90 correct (44.4%) → 54/90 (60.0%)**. Discordants are 7 control-only and 21 treatment-only, exact paired McNemar **p = 0.01254**. Every family improves in raw count.

| Family | Control | Routed | Control-only / routed-only | Exact p | Mean tokens, control → routed |
|---|---:|---:|---:|---:|---:|
| Tables | 10/15 | **14/15** | 0 / 4 | 0.1250 | 232 → 79 |
| Lists | 8/21 | **13/21** | 2 / 7 | 0.1797 | 243 → 117 |
| Sections | 8/27 | **9/27** | 1 / 2 | 1.0000 | 280 → 89 |
| Frontmatter | 14/27 | **18/27** | 4 / 8 | 0.3877 | 225 → 138 |
| Pooled | 40/90 | **54/90** | 7 / 21 | **0.0125** | 247 → 109 |

The efficiency effect is as important as the score: mean completion tokens fall 56%, mean elapsed time falls from about 7.85 s to 3.23 s, and executed tool calls fall from 3.21 to 1.49 per trial. There is one >1,000-token generation in each arm. The routed list pool contains 21 initial zero-token localhost transport rows from an accidentally sandboxed command; the harness's fixed resume rule appended one valid row per key, and the analysis takes the last row.

Safety improves but misses the preregistered gate. Silent corruption falls **27 → 20** and destructive outcomes fall **6 → 2**, with no family increasing its silent-corruption count. Both remaining destructive trials are the same frontmatter mistake: on `add-build-cache`, MiniCPM calls the forced boolean setter with `key="build.target"` and `value=true`, overwriting the existing release target instead of creating `build.cache`. Typed setters prevent object-shaped values; they do not prevent an add request from overwriting an existing leaf. Because the rule required zero treatment data loss, the treatment does **not** ship as measured.

The failure names the next guard without another model run: an add-only frontmatter tool must require the addressed key to be absent. Under that precondition both recorded destructive calls become loud refusals rather than writes. This can be replayed on stored calls, but it cannot retroactively make the treatment pass; correctness remains a separate question. Existing-key setters should symmetrically support `must_exist`, and both should retain the file hash precondition.

The single-mutation boundary also exposes its coverage cost. All three `release-bump` responses emitted both requested string setter calls, but the harness executed only the first, so the `released` key remained absent. Three section tasks likewise require two or three insertions and cannot complete under a singular tool. Deployment therefore needs external task decomposition or atomic batch/children payloads rather than permitting an unconstrained correction loop.

Disposition: orchestration is the right direction for MiniCPM, and table routing is immediately compelling, but the measured treatment fails its safety gate. Keep it evaluation-only until the create-vs-update frontmatter precondition is implemented and replayed, and until multi-mutation requests have an atomic or externally decomposed path. Raw and graded pools use `bench/results/minicpm5_routed_*_20260921`; `minicpm5_routed_analysis_20260921.json` pins paired counts, gates, schemas, inputs, and artifact hashes.

Guard follow-up (preregistered at `657daa4`): replaying all 27 stored routed frontmatter pairs with a host-owned existence precondition passed every gate. The 18 correct results stayed byte-identical; the two destructive `add-build-cache` overwrites became `op_error` refusals with byte-identical documents; six wrong and one malformed result were unchanged; no destructive or collateral outcome remained. This is replay evidence only: unguarded calls and the measured default schemas are unchanged, while any model-facing create/update tool names still require targeted live remeasurement. Artifacts are `bench/results/minicpm5_frontmatter_guard_{replay,analysis}_20260921.{jsonl,json}`.

Atomic-section follow-up (preregistered at `789aa42`): exposing the core's structured `children` payload did **not** improve the 12 routed insertion pairs. Control and treatment both scored 0/12 (exact McNemar p = 1.0); treatment outcomes were 11 wrong and one `op_error`, with zero destructive or collateral outcomes and byte-identical refusal behavior. MiniCPM never used `children`. It continued omitting subsections or placing their names in `body`, and several calls confused the file `path` with the new section path or chose the wrong anchor/position. The gate failed its 4/12 correctness threshold. This narrows the next design: adding a nested field is insufficient; a MiniCPM host must remove structural slots from the model through host-injected file paths and positions, exact dynamic section handles, and flatter content-only payloads. Artifacts use `bench/results/minicpm5_section_children*_20260921`.

Flat content-slot follow-up (preregistered at `159e54a`): moving file, anchor, ordinal, and position entirely into the host improved the same insertion population from **0/12 to 6/12** (six treatment-only wins, exact McNemar **p = 0.03125**). Treatment had six correct and six wrong outcomes, zero destructive or collateral outcomes, and no refusal-safety failure. Mean completion fell from 106 to 55 tokens and elapsed time from 2.98 s to 1.58 s. Results by task were release 3/3, a single subsection 2/3, one nested child 1/3, and two nested children 0/3. The arm missed its preregistered 8/12 and multi-task gates, so it remains evaluation-only. It nevertheless confirms the architectural direction: host-owned structure works; optional multi-child slots remain too easy for MiniCPM to omit. The next isolated question is whether a router that knows requested child cardinality can expose only those slots and mark every requested field required. Artifacts use `bench/results/minicpm5_section_slots*_20260921`.

Required-slot follow-up (preregistered at `a0333b1`): once the host selected a zero-, one-, or two-child micro-schema and made every requested content field required, the same population improved from **6/12 to 12/12** (six treatment-only wins, exact McNemar **p = 0.03125**). All four task types scored 3/3, every control-correct pair stayed correct, and there were zero destructive, collateral, or refusal-safety outcomes; every preregistered gate passed. Mean completion rose from 55 to 73 tokens versus the optional-slot control, but remained well below the original routed insertion mean of 106. This is a routing ceiling: the host used known file, anchor, position, and requested child count. It validates cardinality-specific required micro-schemas, not the yet-unbuilt classifier that must derive those facts from a real request. Artifacts use `bench/results/minicpm5_section_required_slots*_20260921`.

Dynamic-planner follow-up (preregistered at `72f5ec0`): replacing the oracle structure with a MiniCPM planning turn failed the gate. Exact plans and final documents were both **3/12**; the final outcomes were three correct, six wrong, and three loud `op_error` refusals, versus the 12/12 required-slot ceiling and the 0/12 original routed insertion arm. Position was wrong in 8/12 plans and requested child count in 7/12. Anchor intent was semantically right in all 12, although two calls copied the valid longer address `Reference > API` instead of the schema enum canonical `API`, so the host refused them; both also chose the wrong position. Safety held with zero destructive or collateral outcomes and byte-identical refusals. Mean generation was 102 tokens: 51 for planning and 51 for content, compared with 73 for the oracle-routed ceiling and 106 for the original route. The result rejects a generic three-field structural classifier for this model. The next bounded question is whether request-aligned placement and content-shape labels can replace executor jargon such as `last-child` and numeric cardinality; otherwise section structure must remain host-derived or use a stronger model. Artifacts use `bench/results/minicpm5_section_pipeline*_20260921`.

Semantic-label planner follow-up (preregistered at `e3ec099`): replacing executor placement and numeric cardinality with sibling/subsection, before/after-existing, and named content shapes scored **0/12 exact plans**, down from 3/12 for the recorded generic planner; discordants were three control-only and zero treatment-only (exact McNemar p = 0.25). Independently regraded fields were anchor 12/12, order 11/12, relationship 8/12, and content shape 3/12. The initial grader coupled all field scores to whole-plan validity and understated anchor, order, and shape accuracy; the immutable raw pool and original graded pool are retained, while `minicpm5_section_semantic_plan_20260921_regraded.jsonl` corrects only those per-field metrics. Primary exact accuracy and the failed gate do not move. No edit executor ran. Under the preregistered stopping rule, schema-only section-classifier tuning ends here: MiniCPM can copy a section anchor, but section relationship and requested nested-heading cardinality must be host-derived or assigned to a stronger model. Artifacts use `bench/results/minicpm5_section_semantic_plan*_20260921`.

Required list-anchor follow-up (preregistered at `f12ab5d`): after a successful `list_get`, a content-only micro-schema made `text` and `after` required and constrained `after` to exact returned item text. The same six pairs improved from **0/6 to 4/6** (four treatment-only, exact McNemar p = 0.125), with zero destructive, collateral, or refusal-safety outcomes. Nested insertion reached 3/3; ordered insertion reached 1/3. Mean completion fell from 122 to 84 tokens. The arm missed its 5/6 gate and remains evaluation-only. Both misses chose the real item `third` when asked to insert between `second` and `third`; no selector was omitted or invented. This separates two request shapes: explicit "after X" is solved in this sample, while "between A and B" should expose both exact boundaries and validate adjacency instead of asking the model to translate the pair into one `after` value. Artifacts use `bench/results/minicpm5_list_required_after*_20260922`.

Exact list-boundaries follow-up (preregistered at `24276e6`): for the three explicit "between second and third" pairs, requiring both `after` and `before` as exact dynamic-enum values and validating adjacency, depth, and parent improved **1/3 to 3/3**. Both control failures became correct, the control-correct pair stayed correct, and every preregistered gate passed; exact McNemar p = 0.5 on this three-pair sample. All calls selected `after="second"` and `before="third"`, and every pair passed host validation before the existing `list-add-item` executor received only the validated `after`. Mean completion rose from 78 to 90 tokens. Combined descriptively with the preceding arm, request-shaped `after X` and `between A and B` micro-schemas score 6/6 on the six placement-sensitive pairs, versus 0/6 for the generic routed edit schema. This supports adapter-level request routing and dynamic required slots; it does not expand the core executor contract, establish a general list score, or show that MiniCPM can choose the correct micro-schema unaided. Artifacts use `bench/results/minicpm5_list_between*_20260922`.

List-relation router follow-up (preregistered at `e105bb4`): exposing both validated micro-tools after `list_get` produced **6/6 correct final documents**, versus 0/6 for generic routed `list_add_item` (six treatment-only, exact McNemar p = 0.03125) and identical to the 6/6 oracle request-shape ceiling. All edits passed exact-item validation and there were zero destructive, collateral, or refusal-safety outcomes. However, the preregistered gate **failed** because MiniCPM selected `list_insert_after` on all six calls: relation choice was only 3/6, below the 5/6 requirement. On every between-request it nevertheless supplied the correct `after="second"`; the unused `list_insert_between` contrast or revised descriptions changed argument behavior without changing tool choice. Mean completion was 86 tokens. The behavioral result is promising, but it does not validate model-owned relation routing. Per the decision rule, production routing remains host-owned until a separate integration contract supplies the request shape; the result must not be reported as a passed router arm. Artifacts use `bench/results/minicpm5_list_relation_router*_20260922`.

Composite list-handle follow-up (preregistered at `7677258`): requiring one long enum string containing heading, ordinal, kind, marker, item count, levels, and spacing regressed the two remaining selection tasks from **4/6 to 1/6**. Five calls became byte-preserving `op_error` refusals and no destructive or collateral edit occurred. The model chose the semantically correct heading and ordinal in all six calls, but three omitted one semicolon, one truncated the handle after item count, and one changed `spacing=loose` to `spacing=tight`; exact validation correctly rejected all five. The result rejects composite serialized handles, not the underlying selection. It motivates one final smaller representation: require ordinary `heading` and `ordinal` fields separately, validate their pair against `list_lists`, and leave descriptive metadata in the existing summary. Artifacts use `bench/results/minicpm5_list_handle*_20260922`.

Required structured list-address follow-up (preregistered at `ba0016e`): replacing the composite string with separately required `heading` and `ordinal` fields reached **6/6 correct addresses and 6/6 correct final documents**. Both task types scored 3/3, every generic-control correct pair stayed correct, and there were zero destructive, collateral, or refusal-safety outcomes; every preregistered gate passed. Against generic routing the move was 4/6 to 6/6 (two treatment-only, exact McNemar p = 0.5); against the rejected composite handle it was 1/6 to 6/6 (five treatment-only, p = 0.0625). Mean completion fell from 114 tokens in the generic control to 67. This is the same pattern as required section content slots: MiniCPM benefits from small ordinary fields that are independently required and host-validated, while optional nested addresses and serialized compound handles are brittle. The supported design is a host-validated `(heading, ordinal)` selector followed by a content-only mutation tool. Artifacts use `bench/results/minicpm5_list_address*_20260922`.

Integrated list-pipeline follow-up (preregistered at 9564eee, with the request classifier clarified before sampling at ab0e487): combining required structured address selection, automatic list_get, host-owned request-shape routing, and route-specific required content fields improved the complete seven-task list population from **13/21 to 21/21**. All eight control failures became correct, no control-correct pair regressed, and exact paired McNemar **p = 0.0078125**. Every task scored 3/3; all 21 list addresses and host routes were correct; every executed relative anchor passed current-document validation; and there were zero destructive, collateral, or refusal-safety outcomes. Mean completion fell from 117 to 68 tokens despite the two model phases. Every preregistered gate passed. This licenses an opt-in MiniCPM list pipeline with host-owned routing; it does not change the default Gemma schema, establish model-owned relation routing, or generalize beyond the measured add-item requests. Artifacts use bench/results/minicpm5_list_integrated*_20260922.

Pi profile preflight, invalid pool: the first 21-row adapter run passed `tools: []` to Pi 0.85.1. That value is an empty allowlist, so the runtime filtered out every dynamically registered list tool; all 21 active-tool traces were empty, all 21 responses made no recognized call, and all documents remained byte-identical. This is not a 0/21 model result. The immutable original-name pool and analysis record the harness failure. Before any valid treatment sample, the worker allowlist was corrected to the four dynamic profile tools and the valid pool was assigned a `_v2` suffix.

Real-Pi list-profile result (`_v2` valid pool): active-tool restriction did not reproduce the forced-call direct arm. The profile scored **16/21**, versus 13/21 generic routed control; discordants were three control-only and six treatment-only, exact McNemar p = 0.5078125. Sixteen validated mutations ran and all sixteen final documents were correct. Four failures answered in prose instead of invoking the sole active `list_select`; one selected the correct list and then answered in prose instead of invoking `list_append_item`. Every refusal/no-call case was byte-identical, every successful address and anchor was validated, and no turn executed more than one successful mutation. Mean completion fell from 117 to 85 tokens. The 19/21, per-task, no-regression, and all-route gates failed, so the Pi profile remains opt-in and is not adopted as measured. The gap is now narrow and adapter-specific: Pi needs a preregistered forced-choice follow-up, not another schema or executor change. Artifacts use `bench/results/minicpm5_pi_list_profile_20260922_v2*`.

## F-minicpm-pi-force — exact tool choice was transmitted and ignored

The real-Pi forced-tool follow-up was preregistered at `4ae14da`; the treatment implementation and passive outgoing-request audit were frozen at `08b65e2`, and the analyzer at `0d9caa2`, before sampling. The same 21 MiniCPM5 pairs scored **16/21**, exactly matching the unforced Pi control: zero discordant pairs and exact McNemar **p = 1.0**. Against the generic routed control it remained 13/21 to 16/21, with three control-only and six treatment-only pairs (**p = 0.5078125**).

The transport audit observed 39 requests while one pipeline tool was active. Every one advertised the expected tool and carried the exact OpenAI-compatible forced function name. MiniCPM nevertheless answered in prose on four first-phase requests and one second-phase request. Those are the same five failures as the unforced control; completion-token means were also identical at 85.19. The local llama.cpp path therefore accepted `tool_choice` in the request but did not enforce it for this model/runtime.

Safety held: all 16 executed edits were correct, used validated current structure, and stopped after one successful mutation; no refusal changed a file and there were no destructive or collateral outcomes. The preregistered adoption gate still failed correctness, per-task, generic-no-regression, route-coverage, and two-phase-request criteria. Exact forced choice is therefore removed from the product profile rather than shipped. The opt-in unforced Pi pipeline remains at its measured 16/21, while the adapter-independent forced-phase ceiling remains 21/21. Default Gemma schemas stayed byte-identical. Artifacts use `bench/results/minicpm5_pi_list_profile_20260922_v3*` and `minicpm5_pi_list_force_analysis_20260922_v3.json`.

## F-minicpm-pi-prompt — invocation rose, content fidelity fell

The final Pi list-profile follow-up was preregistered at `733678f`; treatment `f5a9d24` replaced only the opt-in profile system prompt with compact list-specific framing, and analyzer `640511c` was frozen before sampling. The treatment reached **19/21**, up from the unforced Pi control at 16/21. Five control failures became correct and two control-correct pairs regressed (exact paired McNemar **p = 0.453125**). Against the generic routed control it moved 13/21 to 19/21 with six treatment-only and no control-only pairs (**p = 0.03125**).

The mechanism moved exactly as predicted: all 21 trials invoked `list_select`, all 21 reached the content tool, and all 42 active-phase requests carried the compact prompt with automatic tool choice. The five prior prose-only failures disappeared. But two `add-item-nested-asterisk` trials selected the correct list and exact `after="beta-two"` anchor, then wrote `text="delta"` instead of the requested `beta-three`. That task scored only 1/3. Mean completion increased from 85 to 94 tokens and turns from 2.62 to 3.0.

All writes remained structurally validated and limited to one mutation; there were no destructive or collateral outcomes, and default schemas stayed byte-identical. The preregistered gate nevertheless failed the per-task and no-Pi-control-regression rules. The compact prompt is removed rather than shipped. Under the stopping rule, Pi list prompt/schema tuning ends here: the unforced opt-in profile remains at its measured 16/21, while further improvement requires a different runtime/model or deterministic host-derived list selection rather than another wording variant. Artifacts use `bench/results/minicpm5_pi_list_profile_20260922_v4*` and `minicpm5_pi_list_prompt_analysis_20260922_v4.json`.

## F-gemma-profile — production routing reproduces the candidate gains

The production `safe-routed` Pi profile was frozen with its preregistration in commit `db66b43` before any new samples. The confirmation reused the four supported Gemma tasks, seeds 0 through 9, the existing prompts and graders, and the same local `gemma4-direct-q8` endpoint.

All 40 trials were correct: exact section rename and body replacement were 20/20, compared with 17/20 in the matching historical baseline; constrained table reads were 20/20, compared with 9/20. There were zero destructive, collateral, unfiltered, or misreported outcomes and zero regressions among baseline-correct pairs. Every first provider request advertised exactly the single action-specific tool chosen by the production classifier; `route_errors` is empty. Both preregistered arms pass.

The result reproduces the isolated benchmark-extension result through real target discovery, dynamic tool activation, content-hash writes, and the production one-success latch. It licenses continued opt-in use of `safe-routed`. It does not license changing the package default or enabling a general MiniCPM profile; those still require full-composition evidence. `auto` therefore maps Gemma to the routed capabilities and conservatively maps MiniCPM and unknown model families to `standard`.

Artifacts: `gemma_safe_routed_profile_20260922.jsonl` (SHA-256 `7091806c341e68a0c1dd4a98ce480aa6110f43e7a6bc93eda253177a9da49165`), its graded pool (SHA-256 `a74c63319e18fcb76e24e9c6701801666b64f5d7193100743960196056512466`), and analysis (SHA-256 `0eb6db69e2ad57f02daf1f9338ecdcde04de1510827958cf9e112a424b1d51ed`).

## F-gemma-full — the narrow routes pass and the generic classifier does not

The full production-profile plan and harness were frozen at `3aba17f`. It ran all 480 Gemma/Pi trials and then repeated the two transport rows once. Both `rename-setext` retries hit the same 240-second generation timeout, leaving 478 usable pairs and independently failing the all-pairs gate.

Among usable pairs, control was 389/478 correct and treatment 390/478. There were 35 control-only and 36 treatment-only wins, exact paired McNemar `p = 1.0`. Harmful outcomes fell from 40 to 23, but that safety movement did not become an accuracy gain. Every family cleared its noninferiority floor except table reads, which fell to 43/60.

The full run found two classifier defects outside the narrow confirmation. First, `List every component ... with its status and owner` was misread as an `Owner` predicate because `and Owner` counted as a filter. All ten whole-table reads received `table_query` instead of the standard tools and returned no rows. Second, `what is the Value cell ... whose Case is escaped pipe` incorrectly treated the requested output column `Value` as another required filter because `is the Value` matched the predicate heuristic. That route reached only 7/10; three trials failed schema validation after correctly supplying `Case`. The newly reached single-column priority route scored 6/10 because four calls changed prompt value `high` to `High`, and exact table matching returned no rows.

The two previously confirmed table routes remained 20/20 and the two section routes remained 20/20. The result therefore rejects default `auto`, not routed execution itself. `safe-routed` remains opt-in. The next treatment must replace loose column-word detection with explicit column/value predicate extraction, leave output-only and whole-table reads on fallback, and make parsed filter values host-owned before another targeted confirmation.

Artifacts: `gemma_safe_routed_full_20260922.jsonl` (SHA-256 `eb904c98063a3038bb1a0dcffeccdc5afed58325eb3fc5afa023c59d17ac7446`), its graded pool (SHA-256 `cba00a29684bd4b09fa63d5637f372065b1abd3a7b953426a2646dcb02f4b4d4`), and analysis (SHA-256 `2ba88dce7e0c9431188d316d7c47cdaf6c24c7074dee45dbc9c7ded4e5b186d9`).

## F-gemma-table-v2 — predicates belong to the host

The table-route v2 implementation and preregistration were frozen at `8583b43`. The treatment replaced loose column-word detection with explicit column/value predicate extraction and made the parsed filter values host-owned. Filtered reads received a zero-argument `table_query`; whole-table and ordinal reads retained the standard eight tools.

The full six-task table-read population reached 60/60 correct. Each task was 10/10, every first provider request carried exactly the preregistered routed or fallback tool surface, and every routed execution recorded filter arguments byte-for-byte equal to the task ideal filter. There were no transport, malformed, misreported, unfiltered, destructive, collateral, or tool-error outcomes.

This closes all three defects from F-gemma-full: whole-table projection no longer becomes an `Owner` filter, output column `Value` no longer becomes a predicate, and the model can no longer change request value `high` to `High`. The gate passes and licenses a second full-composition run; it does not yet license default `auto`.

Artifacts: `gemma_table_route_v2_20260922.jsonl` (SHA-256 `ec140500b442351ef4247733760112d427af9955fe4e8c15a2b8a847fa08ce68`), its graded pool (SHA-256 `9c3820e78f0dea7deec8f6ed5ee6de047534b4d91597c1a626db0b880abb1b3f`), and analysis (SHA-256 `f9759e2ba4ab43f7e7c433202b8f5753a97789e0d216aec678c067f4281eed3c`).

## F-gemma-full-v2 — explicit predicates pass the full Pi gate

The second full production-profile plan and harness were frozen at e30b1d2 after the targeted v2 table gate passed. It ran the same 480 Gemma/Pi pairs as F-gemma-full. One set-build-target trial hit the 240-second transport deadline and succeeded on its single preregistered retry, leaving all 480 usable pairs.

The treatment improved correctness from 390/480 to 406/480. Discordants were 36 treatment-only and 20 baseline-only, for exact paired McNemar p = 0.0440465461. Harmful outcomes fell from 40 to 28. Every family cleared its floor: tables 60/60, lists 93/100, sections 107/150, frontmatter 86/110, and table reads 60/60.

All 60 planned routed trials were usable and correct, with no forbidden calls, route errors, or filter errors. The remaining 420 fallback trials preserved the standard tool surface. Host-owned explicit table predicates fixed all three defects in the first full run: whole-table and ordinal reads stayed on fallback, output-column words were not treated as predicates, and the model could not rewrite exact filter values.

The full gate passes. This licenses recommending INCISE_PROFILE=auto for Gemma in Pi while retaining standard as the package compatibility default for one release cycle. It does not license a general MiniCPM profile. The next measured opportunities are host-resolved section insertion and host-resolved nested frontmatter paths; the full run exposed repeated safe refusals and harmful wrong-target edits in those fallback families.

Artifacts: gemma_safe_routed_full_v2_20260922.jsonl (SHA-256 bc027cd8a5a043c01ae16f8f8dd278b2c502da861029d457dff9b25655224c57), its graded pool (SHA-256 af00ca67c1c2dba25e42e2490c4b8d2ac7acf708bd4857706f3fb5b06e85df54), and analysis (SHA-256 8b71674779b9cc9aa819b1910d74322f2a6111ce46c71fd04385aca5446209c8).

## F-gemma-section-insert-v1 — structure is solved; literal content is not

The production candidate was preregistered at 65282bb and implemented at cc6d1b6. It routed the four frozen insertion tasks through one host-resolved anchor and relation, a content-hash precondition, one atomic section-insert call, and a one-success latch.

The gate failed despite a large improvement: the full-profile-v2 control scored 4/40 and treatment scored 28/40, with 24 treatment-only wins, no control-only regression, and exact paired McNemar p = 0.00000011920928955078125. There were zero destructive or collateral outcomes, zero route or structural-anchor errors, and zero multiple mutations. FreeBSD scored 10/10, nested Rate limits 8/10, and Troubleshooting 10/10; release insertion scored 0/10, below both the 32/40 overall gate and its 7/10 task floor.

All ten release calls supplied the correct host-owned anchor and before relation, but seven copied an outline path into new_heading and three supplied Changelog. The two Rate limits misses prefixed the exact quoted body with redundant Headers text. This isolates the remaining failure to literal content copying: the host can derive the new headings and quoted bodies unambiguously from these explicit request forms, just as it already owns table filter literals. A v2 treatment may therefore expose a zero-argument confirmation tool only when every insertion field parses exactly; ambiguous wording must fall back.

Artifacts: gemma_section_insert_route_v1_20260922.jsonl (SHA-256 e841ccbe684bc26390e888e097a43a5af0dab449490ec4df4fcfd019f856e2ff), its graded pool (SHA-256 9ae076d174e2f8248691f170928fc4796b334355e849817ecdc6e50d6d606b14), and analysis (SHA-256 db44577643a7ab49cdabc340e1eb0678d00e45ba2ed24747b81ce8ba0cf7314b).

# Lists — the second op family

That signal was acted on. The list family exists to ask two questions the table
family could not answer from inside itself:

1. **Does the design transfer?** Content addressing, one broad tool with an
   `action` enum, an executor that owns all formatting — do these hold up on a
   vocabulary the model has never seen?
2. **Was B7 real?** B7 adopted a schema on the strength of 3/60 trials. Porting
   the same change to a new family is the cheapest available replication.

The answer to (1) is yes, emphatically. The answer to (2) is no — and the way it
fails is the most useful thing measured so far.

Lists were chosen because ordered-list renumbering is the direct structural
analogue of table re-padding, the operation Arm A never once got right. The task
set is built around **paired traps**, so that no single rule can pass: inserting
into `1. 2. 3.` *must* renumber, while adding to `1. 1. 1.` and removing from
`1. 3. 7.` must *not*. A model or implementation that always renumbers and one
that never renumbers both fail.

Unlike the table family, list tasks are graded against **exact goldens** scoped
to the target list. This is not a stricter standard applied selectively; it is
forced by the subject matter. A list's correctness *is* its formatting — marker
character, delimiter, indent width, blank-line convention, and the number on
each item — so a predicate for "numbered the way this list is numbered" is a
golden written less legibly. The reasoning is in `make_list_tasks.py`, all ten
goldens are committed in full in `tasks/lists.json`, and
`test_incise_ops.py::test_list_goldens` asserts the reference still produces
them so the benchmark cannot silently re-baseline itself.

Raw trials in `results/trials_lists.jsonl` and `results/armb_lists.jsonl`,
grades in `results/graded_lists.jsonl` and `results/armb_lists_graded.jsonl`.
600 trials: 100 Arm A, 500 Arm B across five schemes.

## L1 — The design transfers, and the headline is the failure *class*

| | Arm A (direct edit) | Arm B (best list scheme) |
| --- | --- | --- |
| correct | 63.0% (53.2–71.8) | **94.0%** (87.5–97.2) |
| **silent corruption** | **30.0%** (21.9–39.6) | **0.0%** (0.0–3.7) |
| data loss | 2.0% | 0.0% |
| loud, recoverable failure | 7.0% | 6.0% |
| mean completion tokens | 58 | 60 |

Paired over the same 100 (task, seed) trials, Arm A vs the best list scheme:
37 trials only Arm B got right, 6 only Arm A, **McNemar exact p = 1.6 × 10⁻⁶**.

The correctness gap matters less than the composition. Across **500 Arm B list
trials in five schemes, silent corruption was 0** — not low, zero. Every single
Arm B failure was an `op_error` or a `malformed` call: incise refused, said why,
and left the document untouched. Arm A's 30% is the number this project exists
to move, and it is the same 30% the table family produced.

Arm A's failure modes are worth naming individually, because they are the
argument for the project:

- **`add-item-ordered-renumber`: 0/10.** The renumbering task. This is the exact
  replication of the table family's re-pad task, also 0/10 (F1). One model
  output invented `2.5.` as a list number. The best Arm B scheme is 10/10.
- **Line numbers written into the document.** `runner.py` presents the file
  `cat -n` style, mimicking a real `read_file` tool. The model built an
  `old_string`/`new_string` pair *including the line-number prefixes*, the fuzzy
  matcher matched anyway, and `28\t1) first` was written into the markdown. This
  is a hazard of the whole read-then-patch idiom, not of markdown.
- **2% outright data loss.** `remove-item-mixed` deleted three items it was not
  asked to touch, including `[ordinary bracket text] also not a task`.

## L2 — B7 did not replicate. It inverted

`list_f` is B7's adopted change ported verbatim: one sentence of prose naming
the address argument on every action line. Against `list_naive`, which lacks
that sentence and is otherwise identical:

| scheme | correct | 95% CI |
| --- | --- | --- |
| `list_naive` | 80/100 | 71.1–86.7 |
| `list_f` | **61/100** | 51.2–70.0 |

Paired: 25 trials only `list_naive` got right, 6 only `list_f`,
**McNemar exact p = 0.00088**. The change that took the table family to 60/60
cost the list family 19 points.

Reading the calls shows it is not an addressing failure at all. `list_f`
supplied the `list` address correctly in almost every trial — the sentence did
its job. What broke is *where the model put the new item's content*: it wrote
`item` where the tool wanted `text`, 39 times.

## L3 — Parameter naming beat every description change measured

`text` and `item` are synonyms in English. The table family never had this
problem and structurally could not: its payload is `values` and its selector is
`where`, two words that cannot be mistaken for one another. The list vocabulary
was named without noticing, and that naming did more damage than any schema
structure measured in the entire project.

`list_g` is `list_f` with **one** change — the selector renamed `item` →
`match`, prose and action lines held fixed:

| scheme | correct | 95% CI |
| --- | --- | --- |
| `list_f` | 61/100 | 51.2–70.0 |
| `list_g` | **91/100** | 83.8–95.2 |

Paired: **30 trials only `list_g` got right, 0 only `list_f`**, McNemar exact
p = 1.9 × 10⁻⁹. A strict domination — the rename cost nothing anywhere and
recovered every failure the collision caused.

## L4 — The two factors interact; neither has a clean main effect

`list_i` fills the missing cell, giving a complete 2×2:

| | selector `item` | selector `match` |
| --- | --- | --- |
| **no address prose** | `list_naive` 80% | `list_i` 84% |
| **address prose** | `list_f` **61%** | `list_g` **91%** |

| contrast | change | McNemar exact p |
| --- | --- | --- |
| rename alone (`naive` → `i`) | +4 | 0.29 — not significant |
| prose alone, colliding names (`naive` → `f`) | **−19** | 0.00088 |
| prose alone, distinct names (`i` → `g`) | +7 | 0.016 |
| rename alone, with prose (`f` → `g`) | **+30** | 1.9 × 10⁻⁹ |

The same sentence costs 19 points in one column and gains 7 in the other. This
is an interaction, not two effects to be added, and it explains L2 without
appealing to anything mysterious about prose: the sentence prepends `list,` to
every action line, pushing the distinguishing field name into second position —
where two of the three lines say the selector's name. That amplifies an existing
collision. Remove the collision and the sentence helps.

**The practical rule this yields is about ordering, not prose.** B7's conclusion
("the description is the interface") is too strong as written: a description
change is only as good as the parameter names it is describing. Get the names
mutually exclusive first; then the description earns its place.

## L5 — A description cannot stop the model inventing a selector. B2, answered

Every one of `list_g`'s nine remaining failures has one cause, and it is B2
again in a new family: the model invents the text of an item it was never shown.
The list summary deliberately withholds item text, and the model asked for
`after: "* current item"`, `after: "third child"`, `after: "* First asterisk
item"` — plausible strings, none of them in the document.

B2 left open whether a schema description could prevent this in the *first*
turn; B3's 13/13 recovery used the improved error message on the second turn
only. `list_h` is `list_g` plus one sentence in `after`'s description telling
the model to omit the field rather than guess, and never to guess an item's
text:

| scheme | correct | 95% CI |
| --- | --- | --- |
| `list_g` | 91/100 | 83.8–95.2 |
| `list_h` | 94/100 | 87.5–97.2 |

Paired: 7 only `list_h`, 4 only `list_g`, **McNemar exact p = 0.55 — not
significant.** The warning did not reliably work. All six of `list_h`'s
remaining failures are still invented `after` values, in the same shape.

So: **a description can move where the model puts a value (L3, B7); it cannot
stop the model manufacturing one it does not have.** For incise this is a design
constraint rather than a wording problem. The optional `after` field is what
invites the guess — the model reaches for it even when `position: "end"` fully
expresses the task — and one trial's leaked reasoning shows the model talking
itself out of it and getting the answer right. The candidate fixes are structural
(drop `after`, or make it accept an ordinal rather than text), and both are
unmeasured.

`add-item-mixed-markers` is the task this bites hardest: 5–9 failures in every
scheme, always an invented `after`. It is the one task where the instruction
("the list that contains the star item") names an item the summary does not
show — so it is also the task that most resembles real use.

## L6 — Lists are the harder family for a model, and easier for an executor

Arm A scores 63% on lists against 60% on tables — statistically
indistinguishable. But the reference implementation has to carry substantially
more per-list state to reach 0% corruption: marker character, marker delimiter
(`.` vs `)`), indent width, loose/tight blank-line convention, checkbox spelling
(`[x]` vs `[X]`), and three distinct numbering styles that demand three distinct
behaviours. None of this is optional, and all of it is invisible in a diff until
it is wrong.

The §5.2 table rule ("widen when necessary, never shrink") has a direct list
analogue that is worth stating as its own principle: **read every convention off
the list as found; never normalize to house style.** A `+` marker stays `+`, a
four-space indent stays four, `1. 1. 1.` stays all ones. The full set is
asserted in `test_incise_ops.py` — 51 corpus lists round-trip byte-identically
through add-then-remove.

## S1 — Sections are the hardest family measured, and the first Arm B family with data loss

`section_naive`, 100 trials, 10 tasks, mock executor, no document in the prompt.
Read as first run — S8 re-grades these same trials under the S2/S3 guards, and
S9 is the fix arm. The Arm A baseline for this family is S7.

| | `list_naive` | `section_naive` |
| --- | --- | --- |
| correct | 80.0% (71.1–86.7) | **58.0%** (48.2–67.2) |
| **silent corruption** | 0.0% | **29.0%** (21.0–38.5) |
| data loss | 0.0% | **6.0%** (2.8–12.5) |
| loud, recoverable (`op_error`) | — | 13.0% (7.8–21.0) |
| mean completion tokens | 60 | 75 |

The two rows that matter are the third and fourth. Across **500 Arm B list
trials in five schemes, silent corruption was zero** (L1) — every failure was a
refusal. The section family broke that in its first hundred trials, with six
trials of outright data loss and twenty-two more that changed the document into
something other than what was asked. Nothing in L1–L6 predicted this, and the
generalization warning in caveat 4 is now a measured fact rather than a
precaution.

The cause is structural, not incidental. A table op cannot reach outside its
table and a list op cannot reach outside its list, so a mis-addressed call
lands on a construct that does not exist and incise refuses. A section op is
*designed* to rewrite arbitrary spans — `section-delete` on `Install` removes
thirty-two lines and six subsections legitimately — so a mis-addressed call is
indistinguishable, at the executor, from a correct one. **The executor cannot
be the whole defence for this family the way it was for the other two.**

## S2 — The data loss is one confusion: `replace-body` used for "add a line"

All six destructive trials come from two tasks, and five of them are a single
substitution. `notes-second-ordinal` says *"Add the line "Superseded." to the
second of the three Notes sections"*:

| call | n | outcome |
| --- | --- | --- |
| `action=append`, `ordinal=1` | 4 | correct |
| `action=replace-body`, `ordinal=1` | **5** | **destructive** |
| `action=append`, `text="\nSuperseded."` | 1 | collateral:formatting |

Every one of the five named the right file, the right section, the right
ordinal — the addressing this arm was built to test was perfect — and then
destroyed the section's existing body because it picked the wrong verb. The
model was not confused about *where*. It was confused about *what*.

This is a different failure class from anything in the table or list families,
where the destructive-capable action (`remove-row`, `remove-item`) has a name
no one would reach for when asked to add something. `append` and `replace-body`
are both "put this text in that section", and one of them silently discards
what was there.

Three candidate responses, none yet measured:

1. **Rename**, as in L3, which beat every description change: `replace-body` →
   `overwrite-body` or `discard-and-set-body`, so the destructive one reads as
   destructive.
2. **Make it refuse by default** — `replace-body` on a section with a non-empty
   body requires an explicit acknowledgement field. This is the only option that
   does not depend on the model reading anything.
3. Description prose. L2 and L5 both measured prose as inert or harmful here;
   it is listed for completeness, not as a recommendation.

**Measured since: option 2, in S8.** It removes five of the six destructive
trials at a cost of zero correct answers, and it does so on the trials already
collected — the fix is executor-side, so it needed no GPU time to evaluate.
Option 1 remains untested and is not needed if 2 holds.

Note what the reference implementation gets right and wrong at once: the op did
exactly what it was told, byte-perfectly. §5.2 preservation does not help when
the destructive act *is* the request.

## S3 — `after` and `last-child` are the same word to the model

`insert-subsection-last` — *"add a `FreeBSD` subsection at the end of Install"*
— scored **1/10**, the worst single task in any Arm B family:

| call | n | result |
| --- | --- | --- |
| `insert` + `position=last-child` | 1 | correct |
| `insert` + `position=after` | 4 | sibling of `Install`, not a child |
| `append` + `position=after` | 4 | no section created at all |
| `append` + `position=last-child` | 1 | no section created at all |

Two separate mistakes, both about vocabulary rather than the document. Nine
trials in ten either put the new heading at the wrong level or used an action
that does not create headings while passing `position` and `heading` arguments
that action ignores.

The `position` enum already spells out the distinction — *"before/after make it
a sibling; first-child/last-child make it a subsection. after and last-child go
past the whole subtree"* — and it did not take. This is the section family's
version of the `after` liability in §12.10: an argument whose value the model
must infer from a spatial word, in a family where getting it wrong is invisible
until someone reads the file.

The five `append`-with-`heading` trials point at a second problem: **the model
treats `append` as generic "add", including "add a section".** If `insert` were
the only action that takes `heading`, and `append` refused loudly when handed
one, four of these five become `op_error` — a loud failure — instead of `wrong`.
That is a schema change to measure, not to assume.

**Measured since: S8 and S9.** The guard converted the `append`-with-`heading`
trials to `op_error` as predicted, and naming `insert` *the only action that
creates a section* in the schema took this task from 1/10 to **8/10** — the
largest single-task gain in the family.

## S4 — Three grader defects, found by the runs and not by the ceiling

All three were live for a section grading pass and are fixed in
`grade.check_section_result`. They are recorded because the ceiling check —
every ideal call grading `correct` — did **not** catch any of them, and knowing
why matters more than the fixes: a ceiling check exercises only the path a
correct call takes, so every defect in the *failure* ladder is invisible to it.

1. **Section paths were compared as a set against a list.**
   `duplicate-siblings.md` holds three sections whose path is identically
   `Notes`, so `len(set(after)) - len(list(before))` read as −4 on a document
   nothing had removed. One trial that appended a stray blank line — pure
   whitespace — was reported as `wrong: section delta -4`. Worse, and not
   observed only because no trial did it: deleting one of three identical
   siblings would have passed the disappearance check entirely, because the
   path was still in the set. Now compared as multisets.
2. **Visible content damage was filed as `collateral:formatting`.** The final
   rung of the ladder caught every remaining difference from the golden, so a
   payload containing a literal backslash-n — the model double-escaping its own
   JSON, 6 trials on `append-after-fence` — was reported as a cosmetic miss.
   §5 reserves `collateral:formatting` for *"intended change correct, content
   intact"*; the rung now splits on whether the difference survives whitespace
   normalization, and content differences grade `wrong`.
3. **The reverse mistake, found by the Arm A run: whitespace damage filed as
   `collateral:content`.** Ten trials on `notes-second-ordinal` put the right
   sentence in the right section joined to the paragraph above it instead of
   separated by a blank line. That moves a line *before* the golden window, and
   the window rungs — which are statements about line numbers — reported "text
   before the edited region changed", i.e. that content had been altered. It had
   not: the document's visible text was byte-for-byte the golden's. The grader
   now checks whole-document whitespace normalization ahead of the window rungs,
   so a lost paragraph break grades `collateral:formatting` — still corruption
   under §5.1, but not a claim that content changed. Arm A's silent-corruption
   total is unaffected at 62%; 11 trials moved between the two `collateral`
   rows. `test_section_grader` pins it in both directions, including the
   negative control: text *added* outside the window is still
   `collateral:content`.

Note the shape of all three: each was found by a run, none by the ceiling, and
each mislabelled failures that were already counted as failures. They changed
what the failures *say*, which is the only reason to have a taxonomy.

## S5 — The `heading` rename fixed exactly what it targeted, and nothing else

`section_p` is `section_naive` with one field renamed: the new-heading payload
is `new_heading` instead of `heading`. The hypothesis was L3's — that a payload
name colliding with the address is a naming problem, not a prose problem.

| scheme | correct | 95% CI | data loss | silent corruption |
| --- | --- | --- | --- | --- |
| `section_naive` | 58/100 | 48.2–67.2 | 6% | 29% |
| `section_p` | 63/100 | 53.2–71.8 | 4% | 26% |

Paired: 11 trials only `section_p` got right, 6 only `section_naive`,
**McNemar exact p = 0.33 — not significant.** On the headline the rename is a
null result, and it should be reported as one.

On its own mechanism it is not:

| | `section_naive` | `section_p` |
| --- | --- | --- |
| calls omitting the `section` address entirely | **4** | **0** |
| `promote-api` (a `set-level` task) | 7/10 | **10/10** |

Every naive call that dropped the address had passed `heading` in its place —
the model used the payload field to say *which* section, because in English a
heading names a section. Renaming it removed the collision and the failure
mode, cleanly, in the one task where that failure dominated. The reason the
headline barely moves is that only 4% of trials were failing this way; the
other 37% fail for the reasons in S2, S3 and S6, which a field name cannot
touch.

This is L3 replicating in a third family — **naming beats description** — with
the honest addition that a naming fix is worth only as much as the failure mode
it targets. It also introduced one:

- **The `new_` prefix generalized.** Three trials invented `new_text` for the
  body payload of `replace-body` (`section_naive`: zero), and all three were
  `op_error`. Renaming one field taught the model a pattern it applied to a
  field that was not renamed. If `new_heading` is adopted, `text` should
  probably become `new_text` for consistency rather than be left as the odd one
  out — a cheap follow-up to measure.

Adopt `new_heading` on the mechanism, not on the headline: it strictly removes
a failure mode, costs nothing measurable, and its one side effect points at a
further rename rather than a retreat.

## S6 — The body payload is a hole in the promise the schema makes

`insert-release-at-top` scored **0/10 in both schemes** — the only task in any
family with a zero in every condition. It is worth reading closely, because the
model is not failing at addressing:

```
{"action":"insert", "new_heading":"[1.5.0] - 2026-09-06",
 "position":"before", "section":{"path":"Changelog > [1.4.2] - 2026-08-14"}}
```

That call is right. Right file, right anchor, right position, right heading
text, seven times out of ten. What it is missing is the task's second half —
the new release needs an `### Added` subsection — and the only way to express
that in one call is to write raw markdown into `body`:

```
"body": "### Added\n\n- `plan --explain` flag."
```

The model must decide, by hand, that the subsection of a level-2 release is
level 3. One trial tried and wrote `#### Added`. Most simply omitted it.

The tool's own preamble says: *"heading level ... maintained automatically; you
do not need to format anything or count levels."* For the `heading` field that
is true and measurably works — `rename` and `set-level` score 18–20/20 across
both schemes. For `body` it is false: the field takes markdown source, so every
guarantee the schema advertises stops at its boundary, silently, in the one
place the model is most likely to need it.

Two ways out, and this needs deciding before the Rust freezes the op set:

1. **Make it two calls.** `insert` the section, then `insert` its child with
   `position=first-child`. Levels stay derived, the promise holds everywhere,
   and the cost is a round trip. Arm B cannot currently measure this — it grades
   one call per task — so the harness needs a multi-call task before the claim
   can be tested.
2. **Make `body` structured** — a list of `{heading, body}` children whose
   levels are computed from the parent. Keeps one call, and the schema grows a
   shape the model has to get right instead of a level it has to count.

Until one is chosen, `insert` should at minimum refuse a `body` that starts with
an ATX heading whose level does not follow from the anchor, rather than writing
it. That converts the whole class from `wrong` to `op_error`: the difference
between a changelog with a malformed release and a calling agent that knows it
needs a second call.

**Both were built and measured; see S13.** The refusal shipped (widened from
"starts with a heading" to "contains one anywhere, parsed rather than
pattern-matched") and cost zero correct answers on re-grade. Of the two ways
out, the structured payload wins on the tasks it addresses — 12/30 → 26/30 —
and charges 12 points to the twelve tasks that never use it. Read S10's
correction first: the mechanism described here was overstated at five trials of
ten and is two, and this task's zero was mostly the single-turn harness, which
S13 replaces.

## S7 — The sections Arm A baseline: 19% correct, 28% data loss

The gap S1 could not state. 100 trials, `reasoning_off`, the same ten tasks and
the same goldens, hermes-style `patch` with the document in context.

| | Arm A | `section_naive` | `section_p` |
| --- | --- | --- | --- |
| **correct** | **19.0%** (12.5–27.8) | 58.0% | 63.0% |
| silent corruption | **62.0%** (52.2–70.9) | 29.0% | 26.0% |
| — data loss | **28.0%** (20.1–37.5) | 6.0% | 4.0% |
| failed to apply | 19.0% (18 `no_match`, 1 `malformed`) | 13.0% | 11.0% |
| completion tokens | 186 | 75 | 82 |
| wall clock | 5.9 s | 2.5 s | 2.7 s |

This is the worst Arm A result in the project — worse than tables (60.0%) and
worse than lists — and the reason is visible in the per-task breakdown:

| Task | correct | what happened instead |
| --- | --- | --- |
| `append-hotfix-note` | **10** | — |
| `replace-install-preamble` | 5 | 4 `no_match`, 1 wrote `// Choose your platform below.` |
| `delete-install-macos` | 3 | 4 collateral:content |
| `insert-release-at-top` | 1 | 4 destructive, 3 collateral:content |
| `insert-subsection-last` | 0 | 6 wrong |
| `notes-second-ordinal` | 0 | 10 collateral:formatting |
| `append-after-fence` | 0 | 4 collateral:content, 3 `no_match`, 2 destructive |
| `promote-api` | **0** | **8 destructive** |
| `rename-closed-atx` | **0** | 7 `no_match`, 3 destructive |
| `rename-setext` | **0** | **10 destructive** |

`rename-setext` is the clearest single number in the family. Asked to rename a
setext heading, the string-editing arm destroyed a *different* section
(`Setext H1 Title > Setext H2 > ATX level 3`) in **ten trials out of ten** — the
old_string it matched on ran past the heading it was aiming at. `promote-api`
is the same shape: promoting `Reference > API` to level 2 means rewriting four
headings, and in eight trials the model rewrote enough of them to delete
`Reference` itself.

Both are ops incise does with an address and an integer. This is the family
where the argument for the tool is strongest, and it is also the family where
the tool is furthest from safe (S1). Those are not in tension: the baseline is
terrible *because* section edits span many lines, which is the same reason a
mis-addressed section op is dangerous.

**Caveat 5 is resolved.** One condition only (`reasoning_off`) — F5 measured
reasoning as a 16× token tax for zero net gain on tables, so the untested
condition is the expensive one, not the favourable one.

## S8 — The S2/S3 guards, re-graded at zero GPU cost

Both fixes are executor-side, so the counterfactual is exact: the same 200 model
outputs, re-executed and re-graded, with no new sampling. Nothing here is a
sampling comparison — every difference is a decision the executor made
differently about a byte-identical tool call.

Two guards were added to `incise_ops.py`:

- `replace-body` refuses a section whose own body is non-empty unless the call
  passes `overwrite=true`. An empty body is unprotected — there is nothing to
  lose, and there `append` and `replace-body` produce identical documents.
- `append` and `replace-body` refuse a `heading` argument, naming `insert` and
  `rename` as the actions that take one.

| | naive v1 | naive v2 | | `p` v1 | `p` v2 |
| --- | --- | --- | --- | --- | --- |
| correct | 58 | 49 | | 63 | 54 |
| **destructive** | **6** | **1** | | **4** | **1** |
| wrong | 22 | 17 | | 21 | 17 |
| `op_error` (loud) | 13 | 33 | | 11 | 28 |

The correctness column looks like a nine-point regression and is not one. All
ten of naive's lost trials and all ten of `p`'s are the single task
`replace-install-preamble`, where the correct answer *is* a body replacement —
and neither scheme has an `overwrite` field to acknowledge it with. The guard
did not make the model worse at that task; it made the right answer
inexpressible in those two vocabularies. `bench/ceiling.py` reports this
directly now (`scheme cannot express: ['overwrite']`) instead of aborting, which
is why it is a line in a table rather than a stack trace.

On the nine tasks all three schemes can express, paired by (task, seed):

| | naive | `p` |
| --- | --- | --- |
| correct, old executor | 48/90 | 53/90 |
| correct, guarded executor | 49/90 | 54/90 |
| McNemar (b, c) | 1, 0 | 1, 0 |

**The guards cost zero correct answers and converted five of six destructive
trials into loud, recoverable refusals.** (The +1 each is S10's whitespace fix,
not the guards.) `notes-second-ordinal` — the task that produced every
destructive trial in S2 — went from 5 destructive to 0 in `section_naive`, with
its four correct trials untouched.

### The one thing the guards got wrong, and how it showed up

The first version of the heading guard turned six previously-*correct* trials
into `op_error`. All six were the same shape:

```
{"action":"replace-body", "new_heading":"[1.4.2] - 2026-08-14",
 "section":{"path":"Changelog > [1.4.2] - 2026-08-14"}, "text":"..."}
```

The model echoed the section it was already addressing back into the heading
field. That requests no rename — rename X to X — and the unguarded executor,
which ignored the argument, produced exactly the right document. A guard that
refuses this costs correct calls to catch nothing, so an echo of the addressed
section's own name (leaf or full path) now passes through; anything else is a
second intent riding on an op that cannot serve it, which is what S2 and S3 were
made of. One character of difference still refuses.

This is worth recording as method, not just as a bug: **the re-grade found it in
seconds and it would have cost 130 GPU trials to find in the fix arm**, where it
would have read as the model getting worse.

## S9 — `section_g`: 80% correct, one-eighth the silent corruption

The fix arm. 130 trials, 13 tasks. `section_g` is `section_p` plus an
`overwrite` boolean and three rewritten action descriptions:

| action | description |
| --- | --- |
| `append` | Adds to the section's existing text, keeping it. Cannot create a section. |
| `replace-body` | DISCARDS the section's existing text… also requires `overwrite`=true if it has any. |
| `insert` | The only action that creates a section; use `position=last-child` for a new subsection. |

| | Arm A | naive (guarded) | `p` (guarded) | **`section_g`** |
| --- | --- | --- | --- | --- |
| **correct** | 19.0% | 49.0% | 54.0% | **80.0%** (72.3–86.0) |
| silent corruption | 62.0% | 18.0% | 18.0% | **7.7%** (4.2–13.6) |
| — data loss | 28.0% | 1.0% | 1.0% | **0.8%** (0.1–4.2) |
| loud, recoverable | 19.0% | 33.0% | 28.0% | 12.3% |
| completion tokens | 186 | 75 | 82 | **60** |

Restricted to the ten tasks the other schemes ran: **74/100**. Restricted
further to the nine every scheme can express: 64/90 (71.1%) against `p`'s 54/90
and naive's 49/90.

The two tasks the guards were built for:

| Task | naive v1 | `p` v1 | **`section_g`** | |
| --- | --- | --- | --- | --- |
| `notes-second-ordinal` | 4 (**5 destructive**) | 3 (**3 destructive**) | **10** | S2 |
| `insert-subsection-last` | 1 | 1 | **8** | S3 |
| `replace-install-preamble` | 10 | 10 | **10** | the destructive op still reachable |
| `append-atx-line` | — | — | **10** | new, S2's clean discriminator |
| `append-macos-note` | — | — | **10** | new |
| `replace-linux-body` | — | — | **10** | new, the reverse direction |

`insert-subsection-last` was the worst task in any Arm B family at 1/10 (S3).
Naming `insert` as *the only action that creates a section* took it to 8/10.

**Read the headline carefully.** Against `section_p` on the shared nine tasks
the correctness gain is not significant (McNemar b=24, c=14, p=0.14); against
`section_naive` it is (b=26, c=11, p=0.02). What is not a sampling question at
all is the corruption column: the guards are deterministic, and the drop from
six destructive trials to one is a property of the executor, not of the sample.
The defensible claim is **"the guards remove the data loss for free, and the
descriptions probably help"** — not "the tuned schema is worth 26 points".

## S10 — What is left is addressing and payloads, and none of it is data loss

The 26 non-correct `section_g` trials, by mechanism:

| n | mechanism | outcome |
| --- | --- | --- |
| 12 | spurious `ordinal` on a path with one match | `op_error` |
| 5 | release created, then the subsection never arrived — see S6 | wrong |
| 3 | `insert` targeted `[Unreleased]` and created only its `Added` child | wrong |
| 2 | `path` given a *section* path instead of a file path | `op_error` |
| 2 | malformed JSON (`"body=\"Use pkg.\",new_heading"`) | `op_error` |
| 1 | `new_heading` given the full path, not the leaf | wrong |
| 1 | wrong ordinal chosen for a rename | destructive |

**S6 is confirmed by mechanism — but not the mechanism first written here.**
`insert-release-at-top` scored 9/10 wrong, and dumping the ten raw call lists
gives the reason exactly:

| n | what `section_g` actually emitted |
| --- | --- |
| 3 | release created in the right place, **and the trial stops** |
| 2 | release created, `## Added` written into the payload |
| 1 | release created, a *table row* written into the payload |
| 1 | release created with the whole path as its heading text |
| 3 | release abandoned; `Added` inserted under `[Unreleased]` |

The payload-shape failure is real and looks exactly as predicted — `## Added`
where `### Added` was needed, so the subsection lands as a *sibling* of the
release it belongs to:

```
## [1.5.0] - 2026-09-06

## Added
* New `plan --explain` flag
```

— but it is **2 trials, not 5**. The largest single group is three trials that
address the anchor perfectly, create the release, and then simply stop, with the
subsection never attempted at all. Every one of those is a trial the harness
gave a single turn to do a two-call job.

So the sentence this section originally closed on ("the failure is invisible in
the call: every argument is right") was true of two trials and asserted of five.
The correction matters because it changes what S6 is a question about. The
payload shape is a genuine hole in the vocabulary — a field where a model that
was promised it would never count levels has to count one — and it is worth
closing on its own terms. But it is not what is holding this task down. The
single-turn harness is, and that is a fact about the *measurement*, which S6
itself flagged and which no schema change can fix:

> Arm B cannot currently measure this — it grades one call per task.

Which makes the multi-turn loop mandatory rather than optional, and makes any
S6 arm run without one a measurement of the harness.

**The spurious ordinal is new and is `section_g`'s own cost.** Calls carrying an
`ordinal` rose from 33 (naive) and 27 (`p`) to 55, and the number that are wrong
rose with them — `ordinal: 1` on a path with exactly one match, twelve times,
six on `rename-closed-atx`, five on `append-hotfix-note`, one on
`insert-release-at-top`. In the `rename-closed-atx` group the model truncated
the path to the parent and used the ordinal to pick a child, which is a coherent
misreading of what an ordinal indexes. Describing the actions in more detail
made the model reach for the addressing extras more often. The executor refuses
with `Valid ordinals: 0`, which B3 measured as recoverable in one turn, so this
costs a round trip and no bytes — but it is a real regression and the first
candidate for the next fix. It was measured, and the fix is worse than the bug:
see S11.

### The payload's whitespace was being read as an instruction

Four trials in the fix arm sent `"\nSuperseded."` or `"\n\nNone of the above is
parsed as markdown."` — correct prose, correct section, with the blank-line
separator the op already inserts supplied a second time by hand. `_block` had
been stripping trailing blank lines and keeping leading ones, so the document
ended up with two blank lines where it uses one: `collateral:formatting`, a
document damaged in a way nobody asked for, because the executor took a guess
about whitespace as an instruction. Both ends are now stripped. Re-grading the
same trials: `notes-second-ordinal` 8→10, `append-after-fence` 9→10,
`append-hotfix-note` 4→5, and **all four of `section_g`'s `collateral:*` trials
became `correct`** — the family's only remaining silent failures are now `wrong`
and the one destructive rename.

## S11 — The obvious next fix is wrong, and now measurably so

S10 named the spurious `ordinal` as "the first candidate for the next fix": 12
of `section_g`'s 26 failures are `ordinal: 1` on a path that resolves to exactly
one section, refused for an ambiguity that does not exist. The fix writes
itself — if the path resolves uniquely, ignore the ordinal — and the same
re-grade trick that measured S8 can measure it before a line of it is committed.

It was implemented as a throwaway monkeypatch on `resolve_section` (on an
`OpError` beginning `"no section"`, retry with `ordinal` dropped) and all three
section trial files were re-executed against it. `incise_ops.py` is unchanged.

| scheme | correct | destructive | wrong | `op_error` |
| --- | --- | --- | --- | --- |
| `section_naive` | 49 → **51** | 1 → 1 | 17 → 20 | 33 → 28 |
| `section_p` | 54 → **57** | 1 → **2** | 17 → 19 | 28 → 22 |
| `section_g` | 104 → **107** | 1 → **7** | 9 → 12 | 16 → 4 |

Three more correct answers in the fix arm, and **six more destroyed sections**.
Every one of them is the same trial group:

```
section disappeared: 'Setext H1 Title > Setext H2' (1 before, 0 after)
```

`rename-closed-atx` t0, t1, t2, t4, t5, t7 — the six trials S10 described as the
model "truncating the path to the parent and using the ordinal to pick a child".
The call says `section: "Setext H1 Title > Setext H2"`, `ordinal: 1`, meaning
*the second thing under Setext H2*. The path resolves — to `Setext H2` itself.
Ignoring the ordinal therefore does not relax an over-strict check; it renames
the parent and takes its child's heading with it.

**The ordinal is the only evidence that the path is wrong.** It is not a
redundant argument on a good address, it is a contradiction inside a bad one,
and a contradiction is exactly the signal an executor should refuse on. The
generalisation: when two arguments disagree, dropping the one that does not
resolve keeps the one that resolves *to the wrong thing*. `p` shows the same
sign at smaller n (+3 correct, +1 destructive); `naive` gains 2 correct with no
new data loss only because it emits far fewer ordinals to begin with.

So the S10 open item closes as a decision rather than a fix: **keep refusing.**
What is left is a message problem, not a resolution problem — see S12.

## S12 — Loud failures recover in sections too: 75%, and one recovers destructively

The whole S8/S9 argument rests on a premise imported from another family: that
converting a silent failure into an `op_error` is a win because `op_error` is
recoverable in one turn. B3 measured that at 13/13 — **on tables**, where the
executor absorbs most mistakes. Sections are the family where it cannot. The
premise was never tested where it matters most.

`armb.py --retry` replays each `op_error` trial with the tool's error message
appended as one extra turn. All three section arms:

| scheme | `op_error` trials | recovered | still `op_error` | wrong | destructive |
| --- | --- | --- | --- | --- | --- |
| `section_naive` | 33 | 21 (63.6%) | 9 | 3 | 0 |
| `section_p` | 28 | 22 (78.6%) | 4 | 2 | 0 |
| `section_g` | 16 | **12 (75.0%)** | 2 | 1 | **1** |

Folded back into the headline, on the 10 tasks all three arms share:

| scheme | correct (1 turn) | correct (+1 retry turn) | destructive |
| --- | --- | --- | --- |
| `section_naive` | 49% | **70%** | 1 |
| `section_p` | 54% | **76%** | 1 |
| `section_g` | 74% | **86%** | 2 |

Over all 130 `section_g` trials: 104 → **116 correct, 89.2%**, with two
`op_error` left. The premise holds for sections, at 75% rather than tables'
100%, and the ordering of the arms is unchanged — the retry turn does not let
the weaker schemes catch up, it lifts all three by roughly the same 12–22
points. S9's claim survives the test that could have broken it.

**But the error message can invite the wrong repair.** `rename-closed-atx` t7
is the single destructive retry in the project. First turn:

```
no section "Setext H1 Title > Setext H2" with ordinal 1.
  Valid ordinals: 0
```

Five of its six siblings read that, dropped the truncated path, and got the
rename right. t7 read it as an instruction about the *ordinal* — which is
literally what it says — kept the wrong path, sent `ordinal: 0`, and destroyed
`Setext H2`. The message reports the fact that is easy to compute (which
ordinals exist) instead of the fact that is wrong (the path). This is S11's
finding from the other side: the executor knows the two arguments contradict
each other, refuses correctly, and then names the wrong one in the explanation.
`"Valid ordinals: 0"` should be something closer to *"this path names exactly
one section, so an ordinal cannot apply — did you mean a child of it?"*, and
that rewrite is now the concrete S10 successor.

**Two mechanisms account for 12 of the 15 trials still `op_error`** after the
retry turn (the other 3 each traded one refusal for a different one; the 6 that
came back `wrong` are S6's `body` payload, unrelated).

1. **`path` and `section` are the same word to the model** — 6 of the 15, and
   the only ones that produce the *identical* error twice. `promote-api`
   t1/t4/t6 and `append-hotfix-note` t4 in `naive`, `promote-api` t8 in `g`: the
   section path goes into `path` (the file argument), `section` is left unset,
   and being told `` `section` is required`` with all 18 candidates listed does
   not dislodge it. A name collision does not respond to a better error message;
   it responds to a different name.
2. **The retry bounced off a second guard, correctly.** All three still-erroring
   `append-after-fence` trials in both `naive` and `p` follow the same arc:
   turn 1 `` `text` is required and must not be empty`` → turn 2 the model
   switches from `append` to `replace-body` → S3's overwrite guard stops it.
   That is a data-loss attempt caught on the recovery turn, filed as
   unrecovered. Counting it as a failure understates the guards: without S8
   these six trials — three in each arm — would have been six destroyed section
   bodies.

The retry pass also confirms caveat 7 in the direction that matters. The
`naive`/`p` retries are *live* second turns against the guarded executor, and no
retry in either arm produced a destructive outcome — the only such result in the
retry set is `section_g`'s t7, above.

## S13 — S6, answered: `children` wins where it was aimed and taxes everything else. And the redundant turn is where documents die

S6 named `body` as a hole in the schema's promise and said Arm B could not
measure it, because Arm B graded one call per task. This closes both halves:
`armb.py` grew a multi-turn loop (up to four turns; the model sees each call's
result and may call again), and two candidate closures were run against the
unchanged vocabulary as a control.

| scheme | `body` | `children` | turns |
| --- | --- | --- | --- |
| `section_g` | raw markdown, undocumented | — | 4 |
| `section_2call` | documented "prose only", executor refuses a heading in it | — | 4 |
| `section_kids` | same as `2call` | `[{heading, body, children?}]`, levels derived | 4 |

Fifteen tasks × 10 trials × 3 schemes = **450 trials**, plus 60 re-runs of two
corrected tasks. The executor refuses a heading anywhere in `body` in all three
arms — that guard was re-graded against the 330 existing single-turn section
trials first and cost **zero** correct answers while converting four silent
failures (one destructive) into `op_error`, so it is not a confound.

### Two broken tasks, found by giving the model enough turns to disagree

Before any of it means anything: the multi-turn arm immediately exposed two
tasks whose answer key was wrong. Both had been in the set for a whole arm and
scored 0/10 in all three schemes, and neither defect was visible while the model
could only make one call — it never got far enough to contradict me.

- **`insert-troubleshooting` asked for a level nobody stated.** The instruction
  said "at the end of the document"; the ideal call made `Troubleshooting` a
  *sibling* of the H1. **All 30 trials, across all three schemes, chose
  `last-child` of the H1 instead.** Both readings put the bytes in the same
  place — the H1's subtree is the whole file — so the only difference is the
  level, and the instruction never named one. This was the family's one insert
  task that did not name its anchor, and an anchor-relative op cannot be graded
  on an unstated anchor. 30/30 is not a model failure.
- **`insert-release-at-top` graded prose the instruction only paraphrased.** It
  said "listing a new `plan --explain` flag" against a golden reading
  `` - `plan --explain` flag. `` — the only paraphrased payload in a family
  where the other fourteen quote their text. Single-turn, this never surfaced,
  because the trials failed earlier for other reasons. Multi-turn, four
  `section_g` trials derived the child's level *correctly* and still graded
  wrong, for writing `` * New `plan --explain` flag ``. A whole-document golden
  cannot express "any bullet to this effect"; the instruction has to be the
  specific thing.

The fixes are asymmetric and the difference matters. `insert-release-at-top`'s
golden is **byte-identical** — only its reachability changed. `insert-troubleshooting`'s
golden **moved**, one heading level, which is the answer key yielding to the
trials. That is the move the honesty conditions exist to make expensive, so it
is recorded as what it is: the task was under-specified, 30/30 said so, and the
correction names the anchor rather than the level so that deriving the level is
still the thing under test.

Both were re-run from scratch across all three schemes. Every number below uses
the thirteen unchanged tasks from the first run plus the two corrected tasks
from the second.

### The result

| task | `section_g` | `section_2call` | `section_kids` |
| --- | --- | --- | --- |
| insert-release-at-top | 4/10 | 8/10 | **9/10** (1 destructive) |
| insert-nested-ratelimits | 7/10 | 5/10 | **9/10** |
| insert-troubleshooting | 1/10 | 1/10 | **8/10** |
| insert-subsection-last | 10/10 | 10/10 | 10/10 |
| append-hotfix-note | **10/10** | 7/10 | 7/10 |
| rename-setext | 10/10 | 10/10 | 10/10 |
| rename-closed-atx | 8/10 (2 dest) | 9/10 (1 dest) | 9/10 (1 dest) |
| delete-install-macos | 10/10 | 10/10 | 10/10 |
| promote-api | **8/10** | 8/10 (2 dest) | 4/10 (1 dest) |
| replace-install-preamble | 10/10 | 10/10 | 10/10 |
| notes-second-ordinal | 10/10 | 10/10 | 9/10 |
| append-after-fence | **9/10** | 8/10 (1 dest) | 5/10 |
| append-atx-line | 10/10 | 10/10 | 9/10 |
| append-macos-note | 10/10 | 10/10 | 10/10 |
| replace-linux-body | 10/10 | 10/10 | 10/10 |
| **total** | **127/150 (84.7%)** | 126/150 (84.0%) | **129/150 (86.0%)** |
| destructive | 2 | 4 | 3 |
| `wrong` | 14 | 11 | 5 |
| `malformed` | 0 | 1 | 3 |

**On the aggregate, nothing happened.** Three points spread over 150 trials, in
both directions, is noise. Read only the totals and the correct conclusion is
"S6 does not matter", and that conclusion is wrong — the same way B3's aggregate
was wrong about narrow versus broad tools.

### Split the tasks by whether the field is for them

| | the three multi-section tasks (30) | the twelve others (120) |
| --- | --- | --- |
| `section_g` | 12 | 115 |
| `section_2call` | 14 | 112 |
| `section_kids` | **26** | 103 |

`children` more than doubles the score on the tasks it exists for — 12 → 26 —
and costs 12 points on the tasks that never touch it. `insert-troubleshooting`
goes from 1/10 to 8/10, in **one call** where the vocabulary without it needs
three. `insert-nested-ratelimits`, where the two new headings are levels 4 and 5
and neither number is in the instruction, goes 7 → 9.

The tax is real and is not confined to insertion. `promote-api` drops 8 → 4 and
`append-after-fence` 9 → 5 under `section_kids`, and neither task can use
`children` at all. `malformed` output — JSON the model could not close — rises
0 → 1 → 3 with the nesting in the schema. Single-call correctness falls from 98%
(`g`, `2call`) to 94% (`kids`). **A field costs something to every task in the
tool, including the ones that ignore it.** That is a design constraint on the op
vocabulary, not an argument against `children`: it says a nested payload belongs
on a tool narrow enough that the tasks paying for it are the tasks using it.

Splitting the two changes apart: documenting `body` as prose-only and refusing a
heading in it (`g` → `2call`) is worth **+4 on `insert-release-at-top`** and −1
overall. Adding `children` on top (`2call` → `kids`) is worth **+12 on the three
target tasks** and −9 on the other twelve. The payload hole S6 named is real and
both closures reach it; what neither closure does is come out ahead on a
fifteen-task average.

### The redundant turn is where documents die

The larger result is about turns, not payloads. Two thirds of every arm stops
after a single tool call — 104/150 in `section_g` and `section_2call`, 114/150
in `section_kids` — and those trials are 98%, 98% and 94% correct. Trials that
made two or more calls are 54%, 52% and 61% correct. The extra turn is not
neutral.

But the interesting cut is not "one call versus many" — three of the fifteen
tasks legitimately need two or three calls, and on those the model continues
after a success 85% of the time, correctly. The cut is **a further call after a
call that had already succeeded, on a task that was finished**:

| twelve single-call tasks, 360 trials | n | correct | destructive |
| --- | --- | --- | --- |
| stopped, or first call failed | 349 | 326 (93%) | 4 (1.1%) |
| **continued after a success** | **11** | 4 (36%) | **4 (36%)** |

Fisher exact **p = 3.2 × 10⁻⁵**, a **32×** relative risk. The model almost never
does this — 11 times in 360, 3% — and when it does, it destroys the document a
third of the time. Every one of the four has the same shape: the first call was
right, the model could not tell, and it escalated.

```
promote-api t6   set-level Reference > API  -> level 2      [correct]
                 set-level Reference > API  -> level 2      [op_error: path is gone]
                 rename    Reference        -> "API"        [Reference destroyed]
                 set-level API ordinal 1    -> level 2
```

```
append-after-fence t9   append "None of the above…"          [correct]
                        replace-body overwrite:true          [fenced block lost]
```

The second one is the cleanest: `append` succeeded, and the tool result the
harness returns is the document's heading outline — which an append does not
change. The model read "nothing happened" and reached for the destructive verb.

The tempting generalization from that trial is wrong, and worth recording
because it was tested. *Do outline-invisible edits get retried more?* Grouping
the 450 first calls by whether the outline could show their effect:
`section-append` 2%, `section-replace-body` 5%, `section-rename` 2%,
`section-delete` 0%, `section-set-level` 25%, `section-insert` 64%. The
retry-heavy ops are the ones whose effect **is** visible. The variable is not
visibility, it is whether the task needed more calls — and `set-level`'s 25% is
`promote-api`, the one single-call task with a multi-heading effect, which is
also where two of the four destructions are.

So the requirement this produces is narrower and better founded than "return a
better outline":

- **A tool result must state what changed, not what the document now looks
  like.** `promote-api` t6 repeats an identical call after it worked; an outline
  that already reflects the change does not tell the model it made the change.
  An explicit "promoted `API` and 2 descendants from level 3 to level 2" does.
- **The destructive verbs are what a confused model reaches for.** All four
  escalations end in `delete`, `rename` over a wrong anchor, or `replace-body`
  with `overwrite: true`. The S2/S3 guards work on the first turn (S8); they do
  not fire when the model has *acknowledged* the overwrite because it has
  decided the document is wrong. Acknowledgement is not consent when the model's
  model of the document is stale.

None of this was visible in 1720 single-turn trials, because a single-turn
harness cannot produce a redundant turn.

**Both requirements were tested in S14.** The first one holds, with a
correction that matters: the tool result has to state what changed *and stop
showing the outline* — a result carrying both measures the same as the outline
alone. The second is still open; the guard question needs its own arm.

## S14 — the redundant turn, fixed: say what changed, and say *only* that

S13 left a requirement written on one observation and a plausible mechanism:
the tool result showed the model the document's new outline, and an outline
that already reflects an edit cannot testify that the edit happened. Replacing
it with a statement of what changed should stop the model second-guessing a
call that already worked.

That is a hypothesis about a behaviour that occurs in about 3% of trials, and
re-running the arm to test it would spend almost all of its sampling
re-deriving first calls that were never in question — while letting the two
arms differ in those first calls by chance as much as by treatment.

### Re-run only the turn under test

So the harness grew a `--replay` mode. It takes trials already on disk, keeps
the prefix — system prompt, user turn, and an assistant message containing a
first call that applies cleanly — and re-samples everything after it, with
**one string different**: the tool result. Every prefix is replayed under every
shape, so the comparison is paired by prefix and the test is McNemar's rather
than Fisher's. The ~97% of prefixes that stop under every shape correctly carry
no weight.

Three shapes, on 393 prefixes drawn from all three S13 schemes (1179 replays):

| shape | the tool result after a successful call | mean length |
| --- | --- | --- |
| `outline` | `Applied.` + the document's new heading outline — every arm before S14 | 702 chars |
| `delta` | `describe_change(before, after)` — what the bytes did, and nothing else | **63 chars** |
| `both` | the delta, then the outline | 758 chars |

`describe_change` is derived from the two documents, not from the call. Echoing
the arguments back would be cheaper and worthless for exactly the case that
matters: a model wondering whether its call landed learns nothing from being
told what it asked for. It lives in `incise_ops.py`, not the harness, because
§6.3.2 makes it a requirement on the response shape — the Rust has to produce
it too.

**The `outline` arm is a replication check, and it passed.** On the same 310
single-call prefixes S13 measured, the original run saw 11 continuations and
the replay saw 9 (2.9%). The replay is sampling the state it claims to be.

### The result

Restricting to the population the claim is about — 300 prefixes where the first
call had *already produced the right document*:

| shape | continued after a correct call | destructive | correct |
| --- | --- | --- | --- |
| `outline` | 8/300 (2.7%) | 3 | 295 |
| `delta` | **0/300 (0.0%)** | **0** | **300** |
| `both` | 6/300 (2.0%) | 3 | 297 |

McNemar, paired on prefix: `outline` → `delta` on whether the model continued
is 8 discordant one way and 0 the other, **p = 0.0078**. `outline` → `both` is
5 and 3, p = 0.73.

**`both` is indistinguishable from `outline`.** That is the finding with the
most teeth in it, and it is not what the S13 requirement said. Adding a
statement of what changed buys nothing while the outline is still there; the
outline has to *go*. A model handed both reads the one that looks like ground
truth. This is why the third arm was run — "state what changed" and "stop
showing the document" sound like one requirement and measure as two, and only
the second one is doing any work.

### It stops the wrong turns and keeps the right ones

A result shape that suppressed *every* second call would score well here and be
useless, so two controls:

**The three multi-call tasks, where a second call is required** (83 prefixes):
continuation is 63 / 61 / 63 out of 83 for outline / delta / both — unchanged
(p = 0.5) — and correctness is 46 / 48 / 45. `delta` does not make the model
lazy. It is 91% shorter than the outline and costs nothing on the tasks that
need the extra turn.

**The ten prefixes whose first call applied cleanly but was *wrong*** — the
model renamed the wrong section, and continuing is the right thing to do:

| shape | continued when the first call was right | when it was wrong | Fisher |
| --- | --- | --- | --- |
| `outline` | 8/300 | 1/10 | p = 0.26 |
| `delta` | **0/300** | **3/10** | **p = 2.4 × 10⁻⁵** |
| `both` | 6/300 | 3/10 | p = 0.0018 |

Under `outline` the decision to keep going is unrelated to whether it should
(p = 0.26). Under `delta` it is almost perfectly aligned with it. The model was
not being random; it was reading the only evidence it had, and the outline is
not evidence.

Ten prefixes is a small cell and the direction is what to trust here, not the
exact rate. But the zero in `delta`'s 300 is not small, and it is the cell the
requirement rests on.

### The definition that had to be reported both ways

S13 counted a prefix as "already succeeded" when the call applied without an
error, because that is what an executor can see. A call can apply cleanly and
still rename the wrong section. Both populations are above:

| population | outline | delta | both | McNemar |
| --- | --- | --- | --- | --- |
| first call applied cleanly (S13's definition), n=310 | 9 | 3 | 9 | p = 0.11 |
| first call was already right, n=300 | 8 | **0** | 6 | **p = 0.0078** |

The looser figure is the honest headline for "does this change the behaviour
S13 measured", and it is not significant on its own. The stricter one is the
population the *requirement* is about, and the gap between them is the whole
result: all three of `delta`'s continuations are prefixes where the model was
right to continue. Narrowing the population after seeing the data would be
choosing the definition that flatters the answer, so both are reported and the
primary endpoint stays the one S13 defined.

### The three that still went wrong

`delta`'s three continuations are two trials of `rename-closed-atx` and one of
`append-atx-line`. The rename pair are the same failure: the first call renamed
the wrong section — `Setext H2`, ordinal 0, when the task named
`Closed ATX level 3` — and the model then renamed twice more trying to undo it.
It noticed. It could not recover, because `rename` has no inverse it can
address and the ordinal message is the one S12 already flagged as misleading.
That is §6.3.1's open message problem, arriving from a second direction.

`promote-api` accounts for six of `outline`'s nine escalations and disappears
entirely under `delta`. It is the one single-call task whose effect spans
several headings, which is exactly the case where an outline is least able to
say *who* changed it.

### What this costs

Nothing, and it refunds. The delta averages 63 characters against the outline's
702 — a 91% cut in the tool result, on the family with the largest summaries —
while removing every measured redundant turn on a correct call. §5.4's
token-frugality requirement and §6.3.2's safety requirement turn out to be the
same edit.

## S15 — one word meaning two things: `path` was both the file and the heading

S12's largest unrecovered failure bucket was the model putting the heading path
into the file argument, and it was the only failure that reproduced
*identically* on the retry turn. That is what a name collision looks like:
`section_edit` spells the file `path` and the heading path `section.path` — one
word, two meanings, one call — and a better error message cannot move it,
because the model is not confused about what it wants, only about where to put
it.

Three arms, one factor each, every description string byte-identical across all
three so that only the key moves:

| arm | file argument | address argument |
| --- | --- | --- |
| `section_g` (control) | `path` | `section.path` |
| `section_g_file` | **`file`** | `section.path` |
| `section_g_hpath` | `path` | **`section.heading`** |

Running both single-factor arms rather than only the one that would ship is
what makes the result readable: if only `section_g_file` moves, the top-level
name is pulling the value; if both move, the collision itself is the problem
and either disambiguation buys it. Ceiling 45/45 on all three before the run.

### The first pass was underpowered, and said so

15 tasks × 10 trials × 3 arms found the misfiling in **2 of 150** control
trials — 0 in both renames, p = 0.5. Not a null result, an unreadable one.

The base rate is the reason, and it is a lesson about reading one's own
findings. S12's "6 of 15" is 6 of the fifteen *unrecovered failures*, not 6 of
150 trials. Applying the detector to every section trial ever run — 4137 rows —
gives **10 hits, which dedupe to 3 distinct trials**, all on one task, all with
the identical value `'Deep heading nesting > Reference > API'`. The behaviour
is not rare-and-diffuse. It is ~0% on fourteen tasks and ~20% on `promote-api`.

So the extra sampling went there rather than spreading thin — the same move as
S14, one level over: spend trials where the behaviour lives. 50 more trials per
arm on `promote-api` alone, taking it to 60.

### The result

On `promote-api`, 60 trials per arm:

| arm | correct | misfiled | `op_error` | destructive |
| --- | --- | --- | --- | --- |
| `section_g` | 53/60 (88.3%) | **9** | 5 | 2 |
| `section_g_file` | **60/60 (100%)** | **0** | 0 | 0 |
| `section_g_hpath` | **60/60 (100%)** | **0** | 0 | 0 |

McNemar, control → either rename: misfiling 9 → 0, **p = 0.0039**; correctness
0 → 7, **p = 0.0156**. The two renames are not merely both significant, they
are *identical* — same cells, same discordant pairs. **The collision itself was
the problem, and disambiguating either side removes it.**

*Later, and it does not disturb this: the two renames are identical on
**misfiling** and are not identical on **whether the model named a file at
all**, which this arm could not grade. On insert only `section_g_file` moves
(0–16, p = 3.1e-5, against `section_g_hpath`'s 0–5, p = 0.063) — which is the
other branch of the inference rule stated above, reached by applying it to an
endpoint that was invisible here. See F-fileblind. `section_g_hpath` remains the
better of the two arms pooled; it was adopted for a different reason. The fourth
cell — both renames at once — was later run as S16 and is **not** adoptable: it
buys insert and sells rename at the same size.*

Every one of the control's seven failures on this task is a misfiled trial.
The misfiling explains 100% of the task's failure, and the two misfiled trials
that still graded `correct` recovered by accident, not by design.

### The loop cannot repair it, which is the point

What the control does with a wrong filename, across four turns:

```
t5, t8, t18   set-level, set-level, set-level, set-level   -> op_error
t46, t58      set-level, rename, set-level, rename         -> op_error
t11           set-level, rename, rename, set-level         -> destructive
t24           set-level, rename, replace-body, set-level   -> destructive
```

Three trials spend all four turns re-issuing the identical call that cannot
work. Two escalate to `rename` and `replace-body` and destroy the document.
This is S12's "reproduces identically on the retry turn" seen at full length,
and it is why the fix has to be in the schema: an error message is advice, and
the model is not failing to take advice.

It also separates two problems that both live on this task. S14 found
`promote-api` responsible for six of nine redundant escalations *after a call
that had already succeeded*, and fixed those with the result shape. These are
the opposite population — calls that never succeeded at all — and the result
shape cannot touch them, because a call that errors produces no delta to
report. `promote-api` needed both fixes and each addresses the other's blind
spot.

### Which rename to adopt

`section.path` → `section.heading`, not `path` → `file`. The measurement does
not choose between them, so the argument is about the rest of the surface:

- **It is the minimal change.** `path` is the file argument on every table and
  list tool too (§6.2, §6.4), and those families are frozen at measured numbers
  — 60/60 and 94/100. Renaming their file argument would invalidate those
  results, or require re-running them to keep §9's "match, not beat" bar
  honest, to buy a collision they do not have.
- **It makes sections match the other two families rather than diverge.**
  Tables address by `table`, lists by `list`, and in both `path` uniquely means
  the file. Sections were the anomaly. The schema deliberately mirrors §6.2 and
  §6.4 "so the model does not learn a third habit"; this is that principle
  applied to the one field where it had been broken.

One caveat carried forward: with the address named `heading`, the *payload*
must stay `new_heading` (S5). `section_naive` spells the payload `heading`,
so that historical scheme would reintroduce a collision one level over. The
adopted pairing is `section.heading` + `new_heading`, which is what ran.

### The free result: caveat 13, closed

This run is the first full arm at the `delta` result shape, and S13 ran the
same 15 tasks at the same seeds at `outline`, so the control pairs directly
against it:

| result shape | correct | destructive |
| --- | --- | --- |
| `outline` (S13) | 127/150 (84.7%) | 2 |
| `delta` (S15) | 127/150 (84.7%) | 2 |

McNemar p = 1 (2 discordant each way). **The S14 fix costs nothing on first
calls in a fresh arm**, which is the one thing S14's replay could not see —
it only ever showed the model a `delta` *after* a first call it had inherited.
Caveat 13 is closed as a null, which is the outcome it needed.

### What the balanced arm still says

On the 15-task balanced set (10 trials each), where the collision is nearly
absent, the renames cost nothing and possibly help: on the twelve single-call
tasks the control is 115/120, `section_g_file` 117/120, and `section_g_hpath`
**120/120** (p = 0.0625, 0 discordant against 5). Suggestive, not significant,
and not the basis of the decision — but it rules out the failure mode that
would have killed the rename, which is a name that fixes one task by confusing
eleven others.

## F-args — the executor's argument layer, surveyed and fixed

Not a trial result. This is a code finding: a survey of what `incise_ops.py`
does when an argument arrives in the wrong *shape* rather than naming the wrong
row. Every Arm B number above is about addressing — the model naming the right
table, list or section (caveat 11). The layer underneath, the one that decides
whether the arguments are even well-formed, had never been examined, because
across all 4009 trials and 7129 records **no model ever sent an argument that
reached it**. Zero exception-shaped strings in the whole corpus of results.

That is a real fact about the model and a bad reason for confidence. The
schemas are replicated verbatim from hermes and the trials all ran one model
family; a different model, a hand-written call, or a schema-less client reaches
these paths on the first try. So the survey ran the executor against ill-typed
arguments directly. It found three classes of defect.

**Crashes.** `table` as a number raised `AttributeError` straight out of
`apply_op`, whose `except` names four exception types and not that one. The
process dies rather than refusing.

**Leaks.** A missing `column` surfaced as `TypeError: 'NoneType' object is not
iterable`; `where` as a list of otherwise-*valid* column names reached
`where.items()` and raised `AttributeError`; `where: 5` reached `for c in where`
and raised `TypeError: 'int' object is not iterable`. These are the exact
opposite of §5.3, which exists because B3 and S12 measured recovery against
messages that say what to send next. A Python traceback says what the executor
was doing.

**Silent defaults — the serious one.** `position: "0"` appended at the **end**
of the table and reported success, because the string failed an `isinstance`
check and fell through to the default. A nested object in `values` was written
into the cell as a Python `repr` — `{'a': 1}`, in the document, graded as
applied. The same coercion in a `where` selector produced
`no row where Component="{'a': 1}"`, which explains the consequence and hides
the cause. Silent corruption reported as success is the single failure this
project exists to remove (F2), and the executor did it too.

### The fix, and the proof it changed nothing measured

Seven `_check_*` functions now sit in front of the ops, following the rule
`_unstring` already established: **parse what parses, refuse the rest.**
`ordinal: "0"` and `position: "0"` are accepted and mean what they say —
`position: "0"` now inserts at index 0 rather than appending — while
`position: "middle"`, `ordinal: 1.5`, booleans where text belongs, and nested or
null cell values are refused in §5.3's voice. The survey of eleven ill-typed
calls that previously produced crashes and tracebacks now produces **0 crashes,
0 leaks**, and every refusal names the field and the expected shape.

Changing a graded executor is how a result quietly becomes a different result,
so the claim that the numbers above still stand is evidence rather than
argument. `bench/regrade_snapshot.py` replays **all 5674 recorded tool calls**
from every results file through `armb.normalize` + `apply_op` against all 26
corpus fixtures and hashes the outcome vector. Before and after the change:
*identical to /tmp/before.json: no recorded call changed behaviour*. The fix
touched only paths no trial ever took.

### Why this is in FINDINGS and not just in the commit

Two reasons. First, it is the answer to an obvious objection to the whole Arm B
design: if the executor owns correctness, the executor's own defects are the
ceiling, and "the executor round-trips the corpus byte-identically" (caveat 11)
is a claim about well-typed input only. It now has a second half.

Second, the argument layer was the part of the port with no differential-test
coverage, and could not have had any by the existing method. `difftest.py`
generates its arguments *from the document* — the address from `list_tables`,
the column from the header row — so every generated call is well-typed by
construction and none of this code was on the path. `mutate.py` inherited the
same blindness.

### Closing it, and the three things that fell out

Two hand-written case families now cover it: `check_args`, a cross product of
40 JSON values against 14 validation functions, and `py_repr`, which checks the
JSON reader and the Python-`repr` writer that writes every `Got:` line. The
suite was 3501 cases at this point and `mutate.py` carried nine mutations aimed
at the new layer, because a green differential test is not evidence until it
goes red. Both numbers grew again when the dispatch was ported; see below.

The port had passed its own unit tests. The cross product found three
divergences those tests had asserted away, each of them a place where Rust's
types quietly disagree with Python's:

1. **`Infinity`, `-Infinity` and `NaN`.** CPython's `json` accepts all three by
   default; they are not JSON. The Rust reader rejected them, so a serialized
   argument containing one was refused where the oracle recovered it.
2. **Python integers have no width.** `ordinal: 12345678901234567890123456789`
   is accepted, and its digits are quoted back in
   `no table with ordinal 12345678901234567890123456789` — a value no `i64` can
   carry as far as the message. Hence `args::PyInt`, whose `Big` variant holds
   the digits and never does arithmetic on them.
3. **`list.insert` clamps at both ends and counts negatives from the right.**
   `position: -1` inserts before the last row, `position: -99` at the front,
   `position: 10**28` at the end. Ported by resemblance this comes out wrong in
   three different ways; it is now ported explicitly.

None of the three would have been found by reading, and the port's unit tests
could not have found them because their expectations were transcribed by the
same hand that wrote the code. That is the general lesson and it is worth more
than the three bugs: **a test whose expected values you wrote is a test of your
beliefs.** The oracle is the only thing here that is not.

One divergence is known and left open: Python's `int()` accepts non-ASCII
decimal digits (`int("١٢") == 12`) and `args::py_int_from_str` does not, because
matching it means shipping a Unicode numeric table in a crate with no
dependencies to serve an ordinal no model will send. Recorded rather than
hidden, and it is the only one.

The other thing the port has to reproduce is the **order** of the checks, which
in Python is made by the language rather than by the code: every `OPS` lambda
argument is evaluated before the call, so `_unstring` refusals precede
`resolve_table`, and a malformed `values` outranks a nonexistent table while a
malformed `position` does not. Rust has no such rule, so the ordering is written
out in `args.rs` and read off the Python rather than inferred.

### The fourth defect, found after the section was written

Writing the Rust dispatch meant deciding what each raw argument means, and one
of them had no answer: `table-update-cell` never validated `value` at all. The
op body was `body[idx][cols.index(column)] = str(value)`, and `str` accepts
everything.

```
absent   APPLIED | widget      | None    | peter   |
null     APPLIED | widget      | None    | peter   |
nested   APPLIED | widget      | {'a': 1} | peter   |
bool     APPLIED | widget      | True    | peter   |
array    APPLIED | widget      | [1]     | peter   |
```

This is the same silent-default class as `position: "0"`, in the op whose entire
purpose is to write one cell: a model that forgets the field is told the edit
succeeded and the document now contains the word `None`. It is worse than the
crashes in the survey above, because a crash is at least visible.

Fixed with `_check_value`, which needs a `_MISSING` sentinel — `a.get("value")`
cannot tell an absent field from an explicit null, and the two want different
sentences ("`value` is required" versus "send `""` for an empty cell"). Rust
gets that distinction free from `Option<&Value>`. Neutrality re-proved the same
way as the other batches: 5674 recorded calls replayed, **no recorded call
changed behaviour**.

### The ordering was asserted by a comment, and the comment was wrong twice

`ops/dispatch.rs` transcribes the evaluation order above, and until it was
tested the transcription rested on a comment plus unit tests whose expected
values were written by the same hand — the failure mode this section already
names. So `difftest.py` grew an `apply_op` family: whole dispatch calls, real
JSON argument objects, compared on the message a model would actually receive.
The suite went from 3501 to **6561 cases**. Three beliefs died:

1. **`check_column` does not belong to the dispatch.** In the oracle it is the
   first statement *inside* `table_update_cell`, after the columns are read, so
   a missing table outranks a missing `column`. Hoisting it — the natural Rust
   shape — inverted 120 cases.
2. **`values: 7` is not refused by the extraction layer.** `_unstring` only
   rejects a *string* that fails to decode, so a bare number reaches the op and
   gets `` `values` must be an object keyed by column name, or an ordered array
   of 3 values``. Collapsing it to an empty row answers "a row is required" to a
   model that plainly supplied one. Hence `Values::Other`, and `json::py_truthy`
   underneath it, because the oracle asks `if not supplied` *before* it asks
   what shape the row is: `values: 0` is a missing row and `values: 7` is a
   misshapen one.
3. **`check_heading` and `check_ordinal` belong to `resolve_table`, not to the
   address.** `_address(a)` only unstrings, de-quotes the keys, and checks the
   outer shape; the two field checks are statements inside the resolver. So
   `{"table": {"heading": 1}, "values": "not json"}` is a `values` refusal, and
   checking the fields at extraction made it a `heading` refusal.
   `TableAddress` now carries raw JSON in both fields.

Every one was a mistake careful reading had already failed to prevent — I had
read the Python, written the order down, and still got it wrong three times.

The third is the one worth dwelling on, because of *how* it was found. It was
not found by the cases; it was found by a **mutation that survived**.
`disp-values-late` swaps `address` and `values` in the dispatch and nothing
failed, which meant no case had two arguments failing at the extraction layer at
once — with one bad argument the message is the same whichever order runs. Cases
were added to close that gap, and closing it exposed the heading defect
immediately. A survived mutation is a coverage fact, and this is what acting on
one buys: the mutation testing found a hole in the differential test, and the
differential test then found a bug in the code. Neither would have found it
alone.

Seven mutations now target the dispatch, four of them reproducing exactly these
errors — including `disp-values-late`, which now fails on 51 cases where it used
to fail on none. The suite is 28 mutations at this point, all caught.

Two divergences from the oracle are deliberate and stay open. The oracle's `OPS`
has twelve entries because it also carries the list and section families, so its
"unknown operation" refusal names twelve where the crate names the three it
implements; and the oracle keeps `row` as a legacy alias so `scheme_d`'s trials
stay regradable, which §6.2 rejected for the shipping schema after measuring it.
Both are excluded from the `apply_op` cases by name rather than skipped quietly.

## F-pipes — a cell is not "the text between two `|` characters"

Found while designing `table-realign`: the op re-renders every row of a table, so
the first question was which tables it must refuse, and the answer sent me to
`corpus/tables/cell-edge-cases.md`. That fixture states its own requirement in
prose — "Any operation on this table must round-trip every cell exactly" — and
Tier 1 had never met it.

GFM lets a cell hold a literal pipe by escaping it. This row

```
| escaped pipe    | a \| b                   | literal pipe, backslashed  |
```

has three cells. `line.split("|")[1:-1]`, which is what both implementations
used, reads four. The mistake runs in both directions and both are silent.

### Reading: the wrong cell, and a row that grew a column

```
table-update-cell  where={"Case": "escaped pipe"}  column="Note"  value="CHANGED"

| escaped pipe | a \ | CHANGED | literal pipe, backslashed |
```

Two failures in one line, reported as success. `Note` is column index 2, which
under the naive split is the fragment `b` rather than the note — so the value
landed in the wrong cell and the real note survived at the end. And the rebuilt
row was emitted with the four cells the parser thought it had, so a three-column
table acquired a four-column row.

`table-add-row` and `table-delete-row` escaped this by luck rather than by
design: the loose renderer re-emits existing lines verbatim from a map keyed by
cell tuple, so neither ever rewrites a row it did not touch. Only the op that
rewrites an *existing* row was exposed.

### Writing: values that break out of the cell

The same assumption on the other side. Measured, all four reported as success:

| sent | written |
|---|---|
| `{"A": "x \| y"}` | `\| x \| y \| z \|` — a three-column row in a two-column table |
| `{"A": "has\nnewline"}` | the table ends at the break; the rest is a second, headerless table |
| `value: "p\|q"` | a line that looks like three cells and parses as four |
| `where: {"A": "x \| y"}` | matched nothing, for a reason the message could not explain |

A cell holds **source markdown** here — `**bold**` in a cell is bold, and a
selector matches the source text — so the fix refuses rather than escaping on the
caller's behalf. Escaping silently would make the stored text differ from the
text that was sent, and `where` matches the stored text; the model would then be
unable to select the row it had just written. The refusal names the escape to
write instead, which is what §5.3 is for.

### The decision the fixture asked for

`corpus/tables/cell-edge-cases.md` also contains a table whose rows genuinely
disagree with its header, and states the question directly: "incise must decide
explicitly: normalize to the header's column count, or fail loudly. It must not
silently drop the extra cell." It is now a refusal, in every write op, naming the
row that disagrees. Padding a short row invents a cell and truncating a long one
destroys bytes GFM hides but does not delete; neither is a formatting change, and
the only reformatting operation in this tool is one the caller asks for by name.
Before the guard, a short row indexed past the end of itself — an `IndexError`
out of the executor's backstop, which is an exception repr where a repair belongs
— and a long row was rewritten at its own width.

### Why nothing caught it

Three defences were in place and all three were structurally blind to it.

1. **Differential testing cannot see a shared assumption.** The Rust port
   transcribes the oracle, so both sides split on `|` and both sides agreed,
   perfectly, on the wrong answer. This is the case §9 names — "if both
   implementations ate a row they would still agree" — showing up in practice
   rather than in the abstract.
2. **The add-then-delete round-trip never rewrites an existing row.** It is the
   project's strongest single invariant and it passed on all 81 corpus tables
   throughout, because the row it adds and deletes is one it created itself.
3. **The mutation suite tests the differential harness, not the parser's
   premise.** No mutation of a line that is wrong in both implementations can
   fail a comparison between them.

What was missing was an invariant about reading back what is already there.
`test_identity_update_roundtrip` is that invariant: write every cell of every
corpus table back to its own current value and require the file to be
byte-identical. **974 cells**, and it fails on the escaped-pipe row under the old
parser. It is cheap, it is general, and it did not exist.

The finding was made by reading a fixture's prose. That is worth recording as a
property of the corpus rather than as luck: these files were written to state
what they are for, and one of them had been asserting an unmet requirement in
plain English for the entire life of the project.

### What changed

Both implementations share one splitting rule (`mdtable.split_row`,
`table::split_row`): a backslash consumes the character after it, so `\|` is
content and `\\|` is a literal backslash followed by a real separator. Only
consuming the escape pair distinguishes those, which is why it is a scan and not
a regex. Identical to the naive split on every corpus line but two.

- Differential suite **6561 → 7686 cases**, over 30 fixtures. Two synthetic
  documents were added — the corpus is frozen — one carrying escaped pipes in
  both an aligned and a ragged table, one non-rectangular in all three ways
  (short row, long row, delimiter disagreeing with the header). The aligned
  re-pad path over a `\|` cell is reachable nowhere in the corpus, because its
  one document with an escaped pipe is ragged for an unrelated reason: CJK cells
  padded to display width rather than character count.
- Nine mutations added (28 → 37): three on the splitter, three on the
  not-rectangular guard, three on the cell check. One of the three makes a
  backslash escape only a pipe — the `\\|` boundary, which is the case the scan
  exists for, and the only one of the three that the other two do not subsume.
- Proven grade-neutral by replaying all **5674** recorded tool calls: no
  recorded call changed behaviour. No trial ever sent a pipe or a newline in a
  cell, and no graded task touches the two affected tables.

## F-realign — the ratchet's repair, and the tables it must decline to repair

`table-realign` is the fourth op and the only one licensed to rewrite lines
nobody named. §5.2 explains why it has to exist: alignment is detected binary
from the table as found, so one bad edit by anything else flips a table to
"ragged" and every later incise edit preserves that raggedness faithfully and
forever. The ratchet only turns one way, and realign is the pawl.

Design followed from that scope rather than from the other three ops. One
argument, `table`, and no others — an operation whose entire effect is "make this
look right" has nothing left to parameterize, which also makes it the only op in
the family with no argument-ordering contract to transcribe (the reason
`dispatch.rs` exists at all). Already-aligned is a silent no-op returning the
input unchanged, not a refusal: realign is the op a caller reaches for when they
are unsure, and punishing them for asking would push them back to editing by
hand.

### The refusal: a table incise cannot measure

The interesting decision was which tables realign must decline. §5.2's tabs rule
already says incise counts width in **characters**; the general problem is that
characters and display columns are different quantities, and they disagree for
CJK, fullwidth forms, combining marks, zero-width joiners and emoji.

For add, update and delete that costs nothing — they preserve existing lines and
pad only what they write, so a mis-measured column is at worst a new row that
does not line up. Realign is the case where it is fatal, because realign's entire
purpose is appearance. Run on such a table it would rewrite every line to be
aligned by a count nobody can see and ragged on the screen, which is exactly
backwards, applied maximally.

So it refuses, and names what it found:

```
this table contains "日", which does not occupy one display column, and incise
counts column width in characters.
  Re-padding it would produce a table that is aligned by that count and ragged
  on screen, which is the opposite of what realign is for.
  First such cell: "日本語テキスト"
  Realign is refused. Add, update and delete still work on this table and leave
  its existing lines byte-for-byte intact.
```

The last line matters more than the first three. A refusal that only says no
leaves the caller believing the table is unusable; this one says which of the
four ops are still available and what guarantee they still carry.

The corpus supplies the case unprompted. `corpus/tables/cell-edge-cases.md`
"Hazardous cells" is ragged *by incise's count and aligned on screen* — its
author padded `日本語テキスト` to display width. It is the one document in the
corpus with an escaped pipe, and F-pipes had already noted in passing that it is
ragged "for an unrelated reason". The unrelated reason is this finding.

### The first rule was too blunt, and the corpus said so

The first draft refused any non-ASCII character. That is trivially safe and it
refused `corpus/documents/project-readme.md` "Feature status", whose only
non-ASCII content is em dashes — one display column each, and the single most
realistic ratchet-repair target in the corpus: a real README table, ragged, that
a user would plainly want fixed.

Refusing to repair the tables that most need repairing is a worse failure than
the one the rule prevents. The check is now a 20-entry range table covering the
Unicode blocks that are genuinely not one column wide. That is a **narrowing,
not a solution** — the real answer is a Unicode width table, which the crate's
no-dependencies rule puts out of reach — and the narrowing is written down here
so it is revisited rather than inherited.

### Verification

- Differential suite **7686 → 9453 cases** over **31 fixtures**: a realign call
  on every table in every fixture, plus one synthetic document
  (`realign-targets.md`, the corpus being frozen) carrying the three ragged
  shapes realign must handle and no corpus table combines — CRLF line endings
  throughout, over-padding that must widen and never shrink, and a table
  indented inside a list item. All agree with the oracle byte-for-byte.
- Six mutations added (37 → **43**): the minimum-width floor, the no-op
  early return, the tabs case, and three on the width computation.
- Three property invariants in `crates/incise-core/tests/invariants.rs`
  (9 total): after any realign that changed the document the table is aligned
  and tab-free; realign is idempotent; and every cell, row and byte outside the
  table survives it.

**Green is a claim, so the invariants were checked for sensitivity** by hand —
each was made to fail by a targeted mutation. Widths that ignore the body, and
widths that ignore the header, both fail `realign_leaves_the_table_aligned`;
dropping the last row fails `realign_preserves_every_cell`; re-padding the padded
text instead of the stripped cell fails `realign_is_idempotent`.

Two probes survived all nine invariants, and both are worth recording because
neither is a hole:

1. **Widths in bytes, fill in characters.** Every cell in a column is still
   padded to the same *character* count, so the table is aligned by incise's own
   measure and the invariant is right not to fire. It is caught by the
   differential suite instead (mutation `width-bytes`), because the oracle
   counts characters.
2. **A naive `\|` split.** The invariants read the table back with the *same*
   mutated splitter, so they agree with themselves — the self-consistency limit
   of any property test, and the same shape of blindness F-pipes found in
   differential testing. Caught by `split-naive`, `split-one-byte` and
   `split-escape-pipe-only`.

Recorded because it makes the layering explicit: property invariants catch what
differential testing cannot see (a shared assumption), differential testing
catches what invariants cannot see (a self-consistent one), and neither ranks
above the other.

### The regrade was not identity, and that is not a regression

`regrade_snapshot.py` over all **5674** recorded calls reported **387 changed**.
F-pipes had set the expectation that the number should be zero, so the
difference was chased rather than accepted.

All 387 are unknown-operation refusals for names no version of the tool has ever
implemented — `patch`, `list_edit`, `section_edit`. The refusal message names the
valid ops, and that list gained `table-realign`, so the *sentence* changed. The
outcome cannot: a refusal writes no document, so there is no grade to move. The
387 were enumerated and every one confirmed to be of that class, rather than
argued from the shape of the change.

Worth keeping as a rule: **identity is the expectation, not the requirement.**
The requirement is that every difference is explained. A harness that only
answers yes/no would have forced either a false alarm or a suppressed check.

## F-dupcol — a header that names the same column twice, answered three ways

Found while porting `table-get`, not by any test. GFM permits a table whose
header repeats a name:

```
| Name | Value | Name |
| ---- | ----- | ---- |
| a    | 1     | z    |
```

Nothing can then say which cell `{"Name": "a"}` means, and three places in this
project answered that unanswerable question three different ways:

| Site | Resolves to |
| --- | --- |
| oracle `dict(zip(cols, row))` — used by `resolve_row` to match | the **last** such column |
| oracle `cols.index(name)` — used by `table_update_cell` to write | the **first** |
| crate `cell_of` — used for both | the **first** |

So on the write path the oracle *matched a row against the last column and then
wrote into the first*, while the port matched and wrote against the first. Both
reported success. Both produced a document. The documents differed.

### Why nothing caught it

The same shape as F-pipes, one layer along. The differential suite could not see
it because **no corpus table repeats a header** — 81 tables across the 26 corpus
files, checked, not assumed. The input that distinguishes the two
implementations occurs in none of them.
The invariants could not see it either: `add_then_delete_is_byte_identical`
round-trips a row the test itself created, and
`no_op_removes_a_row_it_was_not_asked_to_remove` counts rows rather than reading
cells by name.

This is the layering lesson from S8.1 again, and it is worth being precise about
which layer was blind and why, because they fail differently:

- **Differential testing** cannot see an assumption the two implementations
  *share* (F-pipes: both split on `|`).
- **Property invariants** cannot see an assumption an implementation shares
  *with itself* (F-realign: realign checked its own output).
- **Both** are blind to an input the corpus does not contain. That is this one,
  and it is the cheapest of the three to fix: add the input.

### The decision: refuse, rather than pick a winner

Picking the first column would have made the two sides agree, closed the ticket,
and left the tool quietly writing into a cell the caller did not name. §5.3's
rule decides it — the refusal is the product — and `check_rectangular` had
already set the precedent for the same situation one level down: *incise does
not guess which cell the caller meant.*

```
the column "Name" appears 2 times in this table's header, so it does not identify one cell.
  Columns: Name | Value | Name
  Rename one of them in the document, then retry.
```

Scoped deliberately to **name resolution**, which is where the ambiguity lives:

- Refused: `where`, `column`, named `values`, and `filter`.
- Unaffected: ordered `values`, `table-realign`, `table-delete-row` by a
  selector on an unrepeated column, and every read of a table whose header
  happens to be fine.

A table with a repeated header is therefore still fully editable positionally
and still repairable. What is refused is exactly the operation that cannot be
carried out truthfully, and nothing else — the narrowing F-realign argued for,
applied a second time.

### Verification

- One synthetic fixture (`duplicate-columns.md`, two tables: one wide and
  aligned, one narrow and ragged). The corpus is frozen, so this lives in
  `difftest.py` with the others. It costs **352 cases** and it makes every
  name-resolving path in the generator run against a repeated header: the
  `where`, `column`, named-`values` and `filter` emissions all become refusals
  there, while the ordered-`values` and `table-realign` emissions go on
  succeeding — which is the scoping claim above, measured rather than asserted.
- Three mutations, all caught: `dupcol-off` (the guard never fires, 48
  mismatches), `dupcol-threshold` (it fires on every column, 2106),
  `dupcol-count` (the number in the sentence is wrong, 48). The third exists
  because §5.3 makes
  the sentence the product; a guard that refuses correctly and then miscounts is
  still telling the model something false about the document.
- Grade-neutral over all **5674** recorded tool calls: **0 changed**. Predicted
  before it was run, and worth stating either way — F-realign moved 387 calls
  because it added an entry to `OPS` and every unknown-operation refusal names
  that list. `table-get` is a read op and deliberately *not* an `OPS` entry
  (§6.1), so no recorded call could move; the guard is the only other change,
  and no fixture a recorded call touches repeats a header. A prediction that
  matches is weaker evidence than a surprise, but an unexplained zero would have
  been worth chasing just as hard as F-realign's unexplained 387.

### The harness had to be corrected first

The wire format `difftest.py` uses builds an argument dict on the Python side
and a `Vec<(String, String)>` on the Rust side. Both stand in for one JSON
*object*, but only the Python one collapsed a repeated key. A duplicate-column
fixture would therefore have failed on a difference between the two *harnesses*
rather than between the two implementations — the most expensive kind of false
positive, because it looks exactly like the bug you are hunting. The Rust
`indexed` now overwrites in place, keeping insertion order: Python `dict`
semantics, stated as such in a comment.

Worth keeping as a rule: **before trusting a fixture that finally distinguishes
two implementations, check that the harness does not distinguish them by
itself.**

## F-fence — one document, two answers to "is this line code?"

Found by *prediction*, which is the only entry in this file that can say so. The
F-dupcol taxonomy above says the cheapest blindness to close is the third one —
an input the corpus does not contain — so before porting the list parser the two
Python fence scanners were read side by side looking for a point they could
differ on. They had one:

| Scanner | `` ``` trailing words `` closes the block? |
| --- | --- |
| `mdsection.fence_mask` | no — CommonMark: a closing fence carries nothing else |
| `mdlist.find_lists`'s inline copy | yes |

So the same document had two answers to "is this line code?", and which answer
you got depended on which op you called. `find_lists` read the lines after such
a fence as prose and offered them to the model as a list; `find_sections` read
them as code and refused to touch them.

The prediction was written down, the fixture that would expose it
(`bench/synthetic/list-fences.md`) was added, and the suite went to 10542 cases
with **exactly one mismatch** — case 9150, the one predicted: Python reported
`gamma`/`delta` as a second list, Rust reported them as inside an unclosed
fence. CommonMark makes the strict reading correct, so **the port was right and
the oracle was wrong**, and `bench/mdlist.py` was fixed.

### The test that documented its own blind spot

`test_fence_scanners_agree` already existed and already held the two scanners
together over the whole corpus. It also said, in its own docstring, that no
corpus file distinguishes them on the closing-fence rule and that it would
therefore not catch a divergence there. That is exactly what happened. A test
that names its limit is doing the right thing; it is still a limit, and the
limit is closed by supplying the missing input, not by trusting the green.

### The structural fix, not just the behavioural one

Two copies of a rule held together by a test is the arrangement that produced
this, and the arrangement survived the bug fix in the first draft — the rule was
corrected in both copies. That is the same bet again. `fence_mask` now lives
once, in `bench/mdlist.py` with the other bottom-layer scanners, and
`mdsection.py` imports it; the historical note stays in `mdsection.py` because
it explains the shape of the mistake rather than the code.

The same reasoning moved the synthetic fixtures out of `difftest.py`. They had
been string constants in Python, and the Rust invariants that also needed them
would have taken copies. They are now files in `bench/synthetic/`, read by both
harnesses — one copy, two readers. `bench/synthetic/README.md.txt` carries the
per-file rationale, because a fixture cannot carry a header comment: its bytes
are the input.

## F-mixnum — a bullet among ordered siblings, and arithmetic on `None`

Found by reading, in the same pass. A marker change ends a *top-level* run, so
`1. x` and `- y` cannot be siblings at depth 0 — but nothing stops them being
siblings *under a parent*:

```
- a
  - y
  1. x
```

`_numbering_style` asked `all(n == nums[0] + k for k, n in enumerate(nums))`,
and the bullet's `number` is `None`. `None + 0` raises, `apply_op`'s backstop
caught it, and the model was told:

```
TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'
```

Confirmed on the document above: both `list-add-item` (after `x`) and
`list-remove-item` (`x`) returned that sentence instead of a document. §5.3
makes the refusal the product, and a Python exception repr is not a repair — it
is the F-args failure mode, in a family that had already shipped.

### The answer is that such a group is irregular

Not "renumber it somehow". A group that mixes ordered and unordered items is
already something no renumbering scheme describes, which is the same argument
1,3,7 gets: leaving it alone is the only answer that does not invent a change.
Three changes, applied to both implementations at once:

- any group containing a `None` number is `irregular`;
- the renumbering origin is the group's first *real* number, falling back to the
  anchor's own — `_group_start(nums, fallback)` — so sequential and constant
  behaviour is unchanged, all their numbers being non-`None`;
- on the irregular add-branch, only *numbered* predecessors count, because a
  bullet sibling has no number to follow.

### Verification, and why the corpus was silent

No corpus file contains such a group — checked. So the fix was **grade-neutral
by construction**, and that was confirmed rather than assumed: all **5674**
recorded tool calls replayed with 0 changed.

`bench/synthetic/list-mixnum.md` is the missing input. Its three sections are
the three positions the bullet can hold in the group, and they are not
interchangeable: a bullet in the middle breaks the sequential comparison
partway, a bullet at the end breaks its last step, and a bullet *first* makes
the group's leading number `None`, which is a second defect only that ordering
reaches. Measured, not assumed — the three produce `[None,1,2]`, `[1,None,2]`
and `[3,4,None]`, all classified irregular.

## Tier 2b — the list family ported

Three ops (`list-add-item`, `list-remove-item`, `list-set-checked`), the summary
(`list-lists`) and the two resolvers, in `crates/incise-core`. F-fence and
F-mixnum came out of it. Three smaller things are worth recording.

**The list address was unchecked, and the table address was not.** `resolve_list`
read `address.get("heading")` and `.get("ordinal")` raw, so `{"list": {"heading":
7}}` reached the backstop as `AttributeError: 'int' object has no attribute
'strip'` and `{"list": {"ordinal": "0"}}` failed to coerce where the table
family's identical-looking address coerces. `_list_address`'s own comment had
recorded the debt. Both resolvers now run `_check_heading`/`_check_ordinal` up
front, as `resolve_table` does — §6.4 makes the two addresses one habit, and a
habit that refuses differently depending on the family is two habits.

**`position` is compared only against `"start"`.** Every other value means
"end", including `0`, `null`, `true`, and the ones `check_position` refuses
outright on the table family. This is a real divergence between two families
that are meant to teach one addressing habit; it is recorded here **as
measured** rather than silently tightened, because §1.3's list numbers were
produced by this executor and changing what it accepts changes what those
numbers describe. Tightening it is a decision for the shipping schema, made
deliberately and re-measured, not a bug fix.

**Two invariants were stated more strongly than they were true**, and widening
the fixtures said so within one run. `add_then_delete_is_byte_identical` failed
three times as `bench/synthetic/` joined the corpus in
`crates/incise-core/tests/invariants.rs`: on a duplicate-column table (the
round-trip's `add` is correctly *refused*, so there is nothing to delete), on a
table narrower than its own delimiter (`|A|B|` is aligned by character count,
the insert widens it to the delimiter's floor of 5, and no delete can un-widen
it), and on a genuinely ragged table (edits preserve bytes, so realign was the
wrong thing to compare against). It is now
`add_then_delete_loses_nothing_and_only_ever_widens`: same columns, same rows,
same bytes outside the table, and widths that never narrow. A list invariant
failed the same way — `no_op_removes_an_item_it_was_not_asked_to_remove`
re-resolved the address after the edit, and removing the only item of a list
deletes that list, so `ordinal 0` then named a *neighbour's* items as
survivors; it compares the document-wide sequence of item texts now.

Both invariants were green on the 26-file corpus alone, for the same reason: no
corpus document reaches the case. That is the third blindness class landing on
the property tests rather than on the differential ones, and it is the argument
for `bench/synthetic/` being on the invariants' fixture list and not only on the
differential harness's.

### Verification

- **30085 differential cases over 39 fixtures** (13 synthetic), all agreeing —
  from 10482 over 32 at the end of Tier 2. The list ops contribute a
  cross-product of ~60 argument shapes against the three ops for every list in
  every fixture, plus a per-item loop that adds after, removes and re-checks the
  first four items of each list, which is where the conventions actually live.
- **93 mutations, all caught, none stale.** 37 are the list family's, aimed at
  the layers that can be wrong independently: the run parser (six), the two
  scanners under it (three), the conventions an inserted item copies — numbering
  style, line ending, marker gap, checkbox inference (eight) — the three edits
  and the truthiness of `checked` (ten), the resolvers and summary (six), and
  the dispatch's argument ordering (four).
- **19 property invariants**, seven of them new and list-shaped: add-then-remove
  is byte-identical, adding preserves every existing item, removing takes only
  what was named, bytes outside the list are untouched, an inserted item
  inherits its neighbour's conventions, `set-checked` changes exactly one line
  and toggles back, and no op adds a lone LF to a CRLF list.
- **Grade-neutral: 5674 recorded tool calls replayed, 0 changed.** The oracle
  moved three times in this port — the fence rule, the F-mixnum fix, and the
  address checks — and no recorded call took any of those paths.

Two mutations survived the first full run, and both were the same finding a
third time: an input nothing had. Nothing in the corpus *or* in the twelve
synthetic documents contained a list-shaped line indented four columns outside a
list, or two lists separated by exactly two blank lines — so "four or more is
code" and "two blank lines end a run" were both untested. `list-runs.md` is that
input, and both are caught now. A third ended the run with a Rust panic instead
of a mismatch count, which `mutate.py` reported as `NOBUILD` — a verdict meaning
"this proves nothing". It is `crashed` now and counts as caught: a build failure
proves nothing about the corpus, but a panic proves the corpus reaches the line.

## Tier 2c — the section family ported

Six ops (`section-append`, `section-replace-body`, `section-insert`,
`section-delete`, `section-rename`, `section-set-level`), the outline
(`section_outline` / `render_section_outline`) and the four-pass resolver, in
`crates/incise-core/src/ops/section.rs`. The parser under them —
`crate::heading` — was already ported and already differentially covered, so
this tier is entirely about what the ops do with it, which is where the
difficulty was.

**A section has two ends, and that is the whole family.** `own_end` is where a
section's own prose stops; `end` is where its subtree stops. `append` uses the
first, `delete` uses the second, `replace-body` uses both in one function, and
swapping them anywhere is not a crash or a mangled line — it is a plausible
edit in the wrong place. Appending to `## [1.4.2]` in `changelog.md` with `end`
puts the paragraph after `### Changed` instead of before `### Fixed`; deleting
with `own_end` orphans six subsections. Both write a file that parses, and both
report success. Six of the section mutations do nothing but swap the two, and
each has to be caught by name, because the differential suite is structurally
incapable of noticing two implementations picking the same wrong one.

**`describe_change` is deliberately absent.** The oracle has it; nothing in
`OPS` calls it, and it needs `difflib.SequenceMatcher.get_opcodes` where
`similar.rs` ports only the ratio. It is not an op — S14 adopted it as the tool
*result* shape — so it belongs to the CLI/MCP front end, and porting it here
would have put an unused diff engine in a crate whose no-dependencies rule is
the reason `similar.rs` exists at all.

**The dispatch's first documented divergence is closed.** `OPS` now carries the
oracle's thirteen names in the oracle's order. The only remaining divergence in
`dispatch.rs` is the table family's `row` alias.

**The port's one real defect was found by reading, and the case list could not
have caught it.** `section_insert` was written with `if let Some(c) = children`
where the oracle has `if children:`. That looks equivalent, and for every
argument shape but one it is. The exception is Python's `or` returning its
*last* operand when every one of them is falsy: `a.get("children") or
a.get("subsections") or a.get("sections")` on `{"sections": []}` is `[]`, not
`None`, so the op receives an empty list and has to re-test it. Every case in
`SECTION_DISPATCH_ARGS` either found a truthy operand or ended on an absent
one, so the harness would have agreed with itself all the way through.

That is the third blindness class — an input the corpus does not contain —
landing on the *case list* rather than on the corpus, and the distinction is
worth keeping because the two are closed differently: a corpus gap needs a
document, a case-list gap needs an argument shape. Four shapes were added
(`{"sections": []}`, `{"sections": 0}`, and two chains ending in a falsy last
operand); the suite went 62648 → 63584 cases, and `section-children-truthy` is
only a meaningful mutation because of them.

**Two round-trips are conditional, and both conditions are findings rather than
concessions.** They surfaced in `tests/invariants.rs`, where the property was
stated at full strength first and the corpus argued.

*`rename` normalizes whitespace inside the heading span.* `heading_text` trims
what it is given, on purpose: a model handed a rename quotes the line (`"##
Fixed"`) as often as it names the text, and stripping the marker and its
padding is the tolerance that makes that work — measured at 18–20/20 on rename
and set-level. The cost is that `### Setup ` in
`corpus/sections/duplicate-siblings.md`, whose verbatim span is not its
addressing form, cannot be restored through the op's own vocabulary: the
trailing space is not expressible in the argument. This is the one place in the
family where §5.2's "match what was found" does not hold, and it is recorded as
measured rather than fixed, because the tolerance was measured and the
whitespace was not.

*`set-level` is not invertible when the level change moves the subtree
boundary.* In `bench/synthetic/duplicate-columns.md`, promoting `## Repeated
header` to level 1 makes its former sibling `## Repeated, and ragged` a child of
it; demoting it back to 2 with `subtree=true` therefore takes that sibling to
level 3. Nothing is wrong: subtree membership is *derived from the document*,
which is the same property that makes the level derived rather than passed
(S6/L4). But it means "undo the last level change" is not itself a level change,
and a front end must not offer it as one.

**The section ordinal is raw Python `==`, and the three families now disagree
three ways.** F-args gave `resolve_table` and `resolve_list` a shared
`check_ordinal`; the section resolver compares the argument against the entry's
ordinal directly, so `{"ordinal": "0"}` addresses a table and a list and refuses
a section, while `{"ordinal": true}` and `{"ordinal": 0.0}` address all three.
Recorded as measured. It joins `list-add-item`'s `position` and the list/table
ordinal note above as the third place where §6.4's "one addressing habit" is
really two, and all three are one decision for the shipping schema — made
deliberately and re-measured — rather than three quiet edits.

### Verification

- **66127 differential cases over 40 fixtures** (14 synthetic), all agreeing —
  from 30085 at the end of Tier 2b. The section family contributes ~46k: a
  cross product of 114 argument shapes against the six ops for every section in
  every fixture, an 8-case `resolve_section` ladder per section (path, leaf,
  case-folded, `>`-only, ordinal shapes), a 20-entry per-section op loop with
  real arguments, a two-case query for every *inert* heading, and the outline
  dumped field-by-field and rendered once per fixture.
- **26 property invariants**, seven of them new and section-shaped:
  insert-then-delete is byte-identical, an inserted heading is a section at the
  level the position implies, no op removes a section it was not asked to
  remove, `append` adds to the body and replaces none of it, `rename` round
  trips and touches only the heading, `set-level` round trips and moves only
  headings, and `replace-body` keeps the heading and every subsection. Four of
  the seven assert on bytes *outside* the section as well, because that is where
  an `own_end`/`end` mistake shows up.
- **150 mutations, 150/150 caught in one full run** — no survivors, no `STALE`,
  no `NOBUILD`, against the re-baselined 66127-case suite. `-k section-` selects
  58 of them, 57 written for this tier and one (`section-end`) already guarding
  the parser. That single run cost five and a half hours, and it replaced an
  argument with a measurement: before it, 150/150 was *assembled* from three
  runs against a growing case set — valid, because a mutation caught by a set of
  cases is caught by any superset of it, but reasoning rather than evidence.
  The first pass over the section block was not clean; it caught 52 of 58 and
  left six survivors, and what they were is the finding below.
- **Eleven mutations are caught by five cases or fewer**, out of 66127. That is
  the number to watch rather than the 150. `filter-empty-null`, `json-infinity`
  and `near-cutoff` are each caught by a **single** case; `arg-bigint`,
  `cell-newline-off`, `realign-floor` and `section-unique` by two. Each of those
  is one fixture edit away from being a survivor, and a survivor is how a defect
  stops being reported. They are the thin end of the same distribution the six
  section survivors came off, and the cheap read on any future run is to sort by
  mismatch count and look at the bottom, not the total.
- **Cost.** `difftest.py` went from ~60 s to ~2 m 20 s, and `mutate.py` now
  holds 150 mutations, so a full run is roughly five to six hours rather than
  ninety minutes. `mutate.py -k section-` runs the new block alone, and `-k`
  now takes a comma-separated list so the survivors of a run can be re-run
  together over one baseline instead of six. This is worth recording rather
  than absorbing: the suite is approaching the point where it is run per-family
  and in the background, not per-commit.

### Six mutations survived, and five of them were the harness's fault

The section block's first full run caught 52 of 58. That number is the useful
one — not because six defects were found, but because **only one of the six was
a missing document.** The other five were things the harness could not ask, and
one was a question with no answer at all.

| survivor | what it was |
| --- | --- |
| `section-pred-order` | corpus gap — no fixture had a path that was also a longer path's tail |
| `section-ordinal-bool` | case gap — `ordinal: true` never met a path with an ordinal 1 |
| `section-inert-case` | case gap — the inert-heading branch was reached **zero** times |
| `section-type-name` | case gap — no `children` value whose Python type name differs from its JSON one |
| `section-insert-body-alias` | case gap — `text` and `body` together, but never with the `heading` needed to reach them |
| `section-children-chain` | equivalent mutant — no input can distinguish it |

**A feature can have prose, a mutation, and no coverage at all.**
`section-inert-case` is the one to remember. `no_section` consults every inert
heading by name before it reports "not found", because §5.3's rule is that a
heading the user can see on their screen being called absent is worse than a
refusal. It has a doc comment saying so, it has four distinct message endings,
and in 63584 differential cases **it ran zero times** — every query the harness
made was built from a real section's path, a lowercasing of it, or a deliberate
misspelling, and none of those is ever an inert heading's text. The corpus
already contained the input (six inert headings across all four reasons, all
mixed case); nothing asked for it. Two lines in the per-file loop fixed it.
The general lesson is that a mutation surviving is evidence about the *harness*
at least as often as about the code, and the cheapest thing it tells you is
which branches are never entered.

**`section-children-chain` is an equivalent mutant, and it was removed rather
than fixed.** The dispatch spells Python's `a.get("children") or
a.get("subsections") or a.get("sections")` as a `find_map` over the three keys
with an `.or_else(|| a.get("sections"))` tail, so a falsy last operand arrives
as `[]` rather than as absent — faithful to Python, and unobservable, because
`section_insert` takes `children` through `.filter(py_truthy)` at its single
use. `Some(falsy)` and `None` are the same value from there on. The tail and
the re-test are belt and braces for one `or`, and only one of them can be
tested; `section-children-truthy` tests the re-test, so the tail's mutation was
replaced with `section-children-order`, which asks the question the falsy cases
cannot — whether `children` really outranks `sections` when a model sends both.
Deleting a mutation is the right move exactly when no input can distinguish it,
and saying which one and why is the difference between that and quietly
lowering the bar.

**The blindness taxonomy needed a fourth row, and this run wrote it.** Three
of the six survivors were argument shapes rather than documents. A missing
document and a missing argument are the same class of blindness one level
apart, and they are closed differently: a document gap gets a file in
`bench/synthetic/`, an argument gap gets entries in the case list. Tier 2c
found both, and the ratio was 1 to 4.

All six are now caught (`6/6`, over a re-baselined 66127-case suite), and the
one corpus gap became `bench/synthetic/section-repeats.md`: a document where
`Notes` is the full path of one section and the tail of three, so the
resolver's `exact`-before-`suffix` ordering is finally observable. Nothing in
26 corpus documents repeats a top-level heading's text further down — which is
a fair description of most real markdown, and exactly why the fixture had to be
written rather than found.


## Tier 2c addendum — `describe_change`, the result shape, ported

Tier 2c shipped six section actions, the outline and the four-pass resolver, and
left one requirement outside the crate: `describe_change`, the one line a
successful edit returns *instead of* the outline. §5.4, §6.3.2 and §9 criterion
11 all state it, and S14 is what put it there — a derived description in place
of the document took redundant continuation from 8/300 to 0/300 (McNemar
p = 0.0078) and destructive outcomes from 3 to 0, while the same description
*alongside* the outline did nothing at all (6/300, p = 0.73). The omission is
the requirement.

The recorded reason for leaving it out was that it is not an op and that it
needs `difflib`'s `get_opcodes` where `similar.rs` ported only `ratio`. The
first half is true and stayed true — `describe.rs` is not in `OPS` and not in
`dispatch.rs`, for the same reason `table-get` is not: it returns text about a
document rather than a document. The second half was a cost, not a reason, and
the cost was the wrong thing to weigh. **The core is the only place
`difftest.py`, `mutate.py` and `invariants.rs` can reach.** A requirement parked
in a front end that does not exist is a requirement with no oracle, no mutation
and no invariant behind it — which is precisely the state this project spends
its effort getting things out of. It is now a module, held to
`bench/incise_ops.py` byte-for-byte like every op.

One detail of the port is a deliberate divergence rather than a slip: the
oracle's `_describe_change` takes a third parameter, `path`, which appears in
the signature and **nowhere in the body**. The Rust signature is
`describe_change(before, after) -> String`. Porting a parameter no code reads
would have been faithful in the way that matters least and misleading in the
way that matters most — the whole point of criterion 11 is that the description
comes from the bytes and never from the call's arguments, and a `path` argument
sitting in the signature is an invitation to eventually use one.

### Verification

- **77580 differential cases over 43 fixtures** (17 synthetic), all agreeing —
  from 66127 over 40 at the end of Tier 2c proper. `describe_change` contributes
  3343 of them, **226 of which are refusals**: the op-derived cases run a real op
  against a real fixture and describe before-vs-after, so a refused op is a
  refused case, and those messages are compared like any other.
- **29 property invariants**, three of them new: every heading a description
  claims it *added* is present in the after-document; the no-op sentence appears
  exactly when `before == after` and never otherwise; and the response is a
  single line that does not contain the after-document's body — criterion 11's
  "must not return the document or an outline of it", written as a test rather
  than as prose.
- **172 mutations, 172/172 caught in one full run** — no survivors, no `STALE`,
  no `NOBUILD`, against a clean 76352-case baseline. 22 are new: 15 `describe-*`
  over the port and 7 `difflib-*` over the machinery underneath it, which is the
  part of this work worth reading (see F-extend below). That run is also what
  proves the `similar.rs` change did not disturb the 150 that were already
  green — the extension loops are a real behaviour change to code every op
  family reaches, and "the refusal messages did not move" is a claim, not a
  measurement, until the mutations that guard them are re-run.
  **F-autojunk briefly removed two of the seven `difflib-*` and then put them
  back; the count is 172 again, and why is the more useful half of that entry.**
- **Re-run after F-autojunk: 172/172 caught again**, baseline clean, no
  survivors, no `STALE`, no `NOBUILD` — this time against 77580 cases over 43
  fixtures, in 8 h 04 m. `list-subtree-span` is `crashed`, which counts as
  caught for the reason recorded above: a panic proves the corpus reaches the
  line. This is the run that shows `long-cells.md` and its 168 probes disturbed
  none of the other 149 mutations.
- **The thin tail got one entry longer, then two entries shorter.** At the first
  full run, eleven of the 172 were caught by five cases or fewer and three by
  exactly one — the same shape as Tier 2c, but not the same eleven, because
  `difflib-purge` entered at **three cases**. It now stands at **nine of 172,
  two of them by a single case** (`filter-empty-null`, `json-infinity`). Two
  mutations left the tail, and both left it the same way — because the suite
  gained a document it did not have:

  | mutation | before | after |
  | --- | --- | --- |
  | `difflib-purge` | 3 | **14** |
  | `near-cutoff` | 1 | **31** |

  `near-cutoff` is the one worth noticing. It was the most fragile mutation in
  the suite — one case standing between "near-match suggestions get stricter"
  and a silent survivor — and nothing in this work was aimed at it.
  `long-cells.md` was built to reach autojunk; the 0.4 cutoff is simply the
  other thing a long address runs into. A fixture added for one branch paying
  out on an unrelated one is the ordinary case, not a lucky one, which is the
  argument for adding the document rather than narrowing the probe.
  **That payout was not durable, and F-nearmatch records why: these probes were
  near the cutoff only because the purge was pushing them there. Removing the
  heuristic took `near-cutoff` straight back to one case.**
- **Cost.** `difftest.py` went from ~2 m 20 s to ~2 m 45 s — most of that is one
  new 232-line fixture, and the describe cases themselves are nearly free
  because they reuse ops the suite already runs. A full `mutate.py` is now 172
  baselines rather than 150, which at ~2 m 45 s each is eight hours rather than
  five and a half. `-k describe,difflib` runs the new block alone.
  **Both numbers are now historical: see F-harness, which took the full run to
  35 m without changing a single case.**

### Which sentences the corpus actually produces

Counting the phrase each of the 3117 *successful* describe cases came back with
(a description can carry several notes, so the column sums past the total):

| phrase | descriptions |
| --- | --- |
| added the section | 1069 |
| changed the body of | 787 |
| removed the section | 400 |
| …and N nested under it | 381 |
| promoted | 347 |
| renamed | 322 |
| demoted | 200 |
| …and N descendant(s) | 103 |
| a singular line tally (`+1 line`) | 85 |
| changed text outside any heading | 43 |
| the no-op sentence | 42 |

This is phrase presence, not branch execution: one description can carry several
notes, and a phrase can be reached by more than one branch. It bounds nothing
from below — read it as which sentences the fixtures are capable of producing at
all, which is the question the two bottom rows answer.

The two at the bottom are the point of the table. Neither existed before this
work and neither could have. `"changed text outside any heading"` fires only
when the note list comes back empty on a document that *did* change, and **every
one of the 26 corpus files has at least one heading, before any table or list in
it** — no op on any fixture could reach it. This is `section-inert-case` a
second time: a branch with a message, a doc comment and zero executions. It took
two things to close: a synthetic fixture with no heading anywhere
(`bench/synthetic/no-headings.md`), and a second case family that supplies the
after-document inline as JSON rather than deriving it from an op, because some
branches no op produces.

That second family earned its place twice over. The rename guard —
`i2 - i1 == 1 && j2 - j1 == 1`, one heading swapped for one — can be widened to
`||` and no op-derived case notices, because no op *can* produce an asymmetric
replace: `rename` is 1:1 by construction and `insert` leaves the old heading
standing. Two spliced after-documents per fixture, one heading becoming two and
two becoming one, are what make the guard observable.

### Two branches that are provably unreachable, and are therefore not mutated

`_lines_delta` has a `"same line count"` arm for when the tally comes back
`(0, 0)`. It is dead in the oracle, and the argument is short: the tally is
`(0, 0)` exactly when the two line lists are equal, `split("\n")` is injective,
so the lists are equal exactly when the strings are — but the only caller guards
the call with `b[i][2] != a[j][2]`, which says they are not. The two conditions
cannot both hold. 200000 random pairs produced no counterexample.

`get_matching_blocks`' **adjacent-block collapse** is the second, and it is dead
for a more interesting reason: *the extension loops F-extend restored are what
kill it.* Two blocks abut only when `a[i-1] == b[j-1]` holds at the second
block's start — which is exactly the condition the left-extension loop tests,
inside exactly the same region bounds, so the loop would have absorbed the block
rather than leave it adjacent. The collapse is reachable only through an
`isjunk` predicate, which this port never passes. 0 firings in 20000 trials
above the autojunk threshold, with the extension loops present *and* with them
removed. `difflib-collapse` was written, survived a full run, and was then
deleted rather than left in the survivor list.

Both are recorded here and **not** given mutations, under the same rule that
keeps `filter-value-typed` and `section-children-chain` out of the list: a
mutation known in advance to be unreachable measures the harness's patience, not
the code. Both arms stay in the port, because the port's contract is
byte-agreement with an oracle that has them and an unreachable arm costs
nothing; what the suite does not do is pretend they are tested.


## F-extend — two of difflib's four extension loops, and the comment that justified dropping them

Found while completing `similar.rs` for `describe_change`, which is the only
reason it was found at all.

`find_longest_match` in CPython's `difflib` ends with **four** loops that grow a
match outward from the DP result. The first pair extends while the neighbouring
elements are equal and `not isbjunk(...)`; the second pair extends while they
are equal and `isbjunk(...)`. `similar.rs` ported neither, under a comment
saying they are "guarded by `isbjunk`, which is empty". That is true of the
second pair and **false of the first**: with an empty junk set, `not isbjunk(x)`
is always true, so the first pair always runs.

The loops are inert whenever nothing has been purged, which is why three op
families and 66127 cases never saw it:

- **Verified inert:** 0 mismatches in 20000 random `find_longest_match` trials
  with `len(b) < 200`.
- **Verified live:** difflib's autojunk purges popular elements at
  `len(b) >= 200`, and once `b2j` is missing entries the DP finds a shorter
  match that the loops are supposed to grow back. On a synthetic 241-line diff,
  the unfixed algorithm gives a matching total of **120** against Python's
  **240** — half.
- `corpus/documents/api-reference.md` is **821 lines**. Every existing caller
  was `get_close_matches` over heading texts and column names, none of which
  approaches 200 elements. `describe_change`'s line tally is the first caller
  that crosses the threshold, on that one file.

**The finding is not about diffing.** Before this work `similar.rs` had exactly
one mutation, `difflib-tiebreak`, and it only reaches the ranking in
`get_close_matches`. `matches`, `longest_match` and the autojunk branch had **no
mutation and no invariant between them**. A file with no mutation is a file the
differential suite has never been given a chance to check, and this defect sat
in one for three tiers — not because the discipline failed but because it was
never pointed at that file. The gap was in the mutation list before it was in
the code. Seven `difflib-*` mutations now cover both extension loops, the
`n >= 200` boundary, the purge comparison, the block sort, the terminating
sentinel and the insert/delete direction. *(Five, since F-autojunk: turning the
heuristic off for the line diff removed the only caller through which a case
could observe the boundary or the comparison. The rest of this section is left
as written, because the fixture argument below is what F-autojunk then had to
weigh against.)*

**Two of those seven needed a document that did not exist, and the arithmetic
wrote it.** `difflib-autojunk` (move the threshold from 200 to 2000) and
`difflib-purge` (shift the purge comparison by one) both survived their first
run, because below 200 elements the heuristic is not merely unused but
*unobservable* — nothing any test can see changes. So the fixture's constraints
are arithmetic rather than stylistic: `bench/synthetic/repeated-lines.md` is 232
lines and mostly duplicates, and the paragraph repeated three times in it is
there because deleting `Release 3` leaves exactly three copies in the
after-document, while `232 // 100 + 1` is three — the one element sitting
precisely on the boundary between `<=` and `<`. Three ops distinguish the
threshold and two distinguish the comparison. A fixture designed to a modular
arithmetic constraint reads as over-fitting; the alternative was two mutations
recorded as caught by nothing.

Two things make this cheap to under-react to, and both are worth stating. The
fix is **inert for every measured output**: `similar.rs` feeds the "Near
matches:" refusals that Arm B measured recovery against, and the full 76352-case
differential run passes with those messages byte-identical, which is the proof
rather than the argument. And the omission was *reasonable* — the comment
was not careless, it was a correct observation about the second pair of loops
applied to the first. A justification that is half true is harder to catch on
review than one that is simply wrong, which is the case for not relying on
review.

While fixing it, `matches()` was re-expressed as the sum of `matching_blocks`'
sizes rather than kept as a separate faster path. Two code paths for one
question is the bet that produced F-fence — two scanners, one test holding them
together, drift on the point the test could not see.

### The heuristic being faithfully ported is itself wrong, and that is open

`repeated-lines.md` also shows what autojunk *costs*. Deleting an 18-line
section from it makes the oracle report:

```
Applied: removed the section "Release 3" (level 2). (+71 lines, -89 lines.)
```

+71 lines, for a delete. The true diff is `(0, 18)`; `difflib` returns
`(71, 89)` because purging every line that occurs more than three times leaves
it unable to see the document's structure. This is CPython's documented
behaviour, `autojunk=True` is its default, the oracle takes the default, and the
port therefore reproduces it byte-for-byte — that is the contract and it is being
honoured.

It is also **misinformation aimed at a model**, which is the one thing §5.4 was
adopted to stop. A description exists so a model can tell whether its call
landed; a tally that says a deletion added 71 lines is worse than no tally,
because it is specific. Recorded as open rather than fixed, for the same reason
the section ordinal's raw `==` was: passing `autojunk=False` is a one-word change
on the Python side and a one-line change on the Rust side, it moves measured
output, and S14's numbers were collected with the current behaviour. It is one
decision about the shipping response shape, re-measured — not a quiet edit to
whichever implementation is easier to reach. The documents it bites are long and
repetitive, which is a fair description of a changelog and of every generated
reference table in the corpus.

**That decision was taken; it is F-autojunk below. The premise in the paragraph
above — "it moves measured output" — was wrong, and measuring it is what showed
that.**


## F-autojunk — the heuristic came off the line diff, and the reason it was cheap

`autojunk=False` on both matchers in `describe_change`, on both sides. The
`(+71 lines, -89 lines)` above is now `(-18 lines.)`.

What made this look like a hard decision was the belief that it moved measured
output, so it was written up as one requiring a re-measurement of the shipping
response shape. **It does not**, and the way to find that out was to run it
rather than to reason about it. Forcing `autojunk=False` through every
`difflib` call and re-running the whole differential suite:

| | |
| --- | --- |
| cases whose output changes | **7 of 76352** |
| fixtures affected | 1 — `bench/synthetic/repeated-lines.md` |
| corpus documents affected | **0** of 26 |
| refusal messages affected | **0** |
| changes that move *toward* the true minimal edit | 7 of 7 |

Every one of the seven is a line tally, and every one gets smaller and truer:
`(+71, -89)` → `(-18)`, `(+1 line, -9 lines)` → `(-8 lines)`, `(+3, -1)` →
`(+2)`. There is no case where autojunk's answer was better and none where it
was merely different. S14's 300 trials ran on corpus documents, all of which
produce byte-identical descriptions either way, so nothing it measured is
disturbed.

The heuristic is a **speed guard**, not an accuracy feature — difflib purges
elements occurring in more than 1% of a long `b` to keep `find_longest_match`
from going quadratic on popular elements. On a document's line list the popular
elements are the blank line, the table delimiter and the repeated bullet, which
are exactly the anchors a line diff needs. That is the whole finding: the
heuristic's cost model assumes popular elements are noise, and in markdown they
are structure.

### What it cost, and the mistake that followed

The first version of this entry said the change cost two mutations and left the
autojunk branch permanently uncoverable. Both halves were wrong, and the error
is more instructive than the change.

`difflib-autojunk` and `difflib-purge` were caught by 7 and 3 cases, every one
of them a `describe_change` case on `repeated-lines.md` — the only caller
through which any case observed the branch. Turning autojunk off there took
those to zero, so both mutations survived the next run and were deleted with a
written argument: that covering them needed a 200-character address *and* a
candidate near the 0.4 cutoff simultaneously, and that a fixture balanced on a
knife-edge would be brittle.

The argument was untested, and it did not survive being tested. It also took
two more mutations with it that nobody had decided to remove: with autojunk off,
`difflib-extend-left` and `difflib-extend-right` — the loops that exist to
recover matches *through* purged elements — had nothing to recover, and they
survived too. Four mutations, one of which was the fix F-extend had just made.

`get_close_matches` diffs the caller's value against the candidates **by
character**, so `n` counts characters of the value and the heuristic engages at
a 200-character address. Nothing in the corpus is a tenth of that; that is the
whole reason the branch was uncovered, and it is a missing *input*, which is the
cheapest of the three blindnesses to fix. `bench/synthetic/long-cells.md` is a
table with a long prose column, two of whose rows are deliberate paraphrases —
that second row is what sits near the cutoff, so a purge decision moves it
across the line and into the message instead of being taken invisibly.
`difftest.py` probes each such cell with itself one word short. That produces
168 probes, and `mutate.py -k describe,difflib` comes back **23/23 caught**:

| mutation | cases that catch it |
| --- | --- |
| `difflib-extend-left` | 33 |
| `difflib-extend-right` | 29 |
| `difflib-autojunk` (the `n >= 200` boundary) | 46 |
| `difflib-purge` (the `n // 100 + 1` threshold) | 14 |

All four are back. 76352 cases → **77580**, 170 → **172**.

`repeated-lines.md` keeps its place. It was built to a modular-arithmetic
constraint (232 lines, `232 // 100 + 1 == 3`, three copies of one line on the
boundary) that no longer has anything to catch, but it is still the only long
repetitive document in the fixture set and it is what the seven corrected
tallies are measured on. A fixture whose purpose changes is worth keeping; a
fixture with no purpose is not.

### The part worth generalizing

This entry exists because the *previous* entry got it wrong in a specific,
recoverable way. F-extend recorded "it moves measured output, and S14's numbers
were collected with the current behaviour" as a reason to defer — a plausible
claim, never tested, that turned a twenty-minute change into a blocked decision
about re-running 300 trials. The cost of checking was one scripted sweep of a
suite that already existed. Where a finding says "this would move measured
output", that sentence is a hypothesis and the suite can usually decide it.

Then this entry made the same mistake in the opposite direction, which is worth
stating plainly because the rule it broke is the one written at the top of
`bench/mutate.py`. **A surviving mutation is evidence about the harness before
it is evidence about the code** — and that holds just as much when the survivor
appears right after a deliberate change as when it appears out of nowhere. The
tempting reading is the self-serving one: *I changed this code, so of course the
mutation no longer applies; retire it.* Four mutations went that way on an
argument that took one afternoon to disprove. The discipline only works if a
survivor is allowed to be inconvenient, so the order is: assume the cases are
missing something, and make deleting a mutation the last resort rather than the
first explanation. The precedents for genuine deletion — `section-children-chain`,
`filter-value-typed`, `difflib-collapse` — all rest on an argument that the
mutant is *unobservable in principle*, not on the observation that no case
currently reaches it.


## F-harness — the eight-hour run was 93% one serial loop

A full `mutate.py` took **8 h 04 m**, which sets the tempo of everything built
on top of it: one attempt a day, and a survivor found in the last ten minutes
costs a second day. Before treating that as the price of the discipline, it was
worth measuring where the time actually went. One `difftest.py` run, 77580 cases
over 43 fixtures:

| phase | time |
| --- | --- |
| generate the case list | 0.2 s |
| **the Python oracle loop** | **156.2 s** |
| the Rust port, all 77580 cases in one process | 10.8 s |
| `cargo` rebuild after a mutation | 4.5 s |

The port is not the slow half and never was. 93% of the run is `py_run` called
77580 times in a single process, and a full pass calls it 173 times — 13.4
million invocations, of which 13.3 million recompute an answer that was already
computed.

**Two facts make that avoidable, and both are properties of the code rather than
assumptions about it.** `py_run` is pure: it takes a document string and an
argument dict, and `incise_ops` holds no mutable module state — `_WIDE_RANGES`,
`_MISSING`, `POSITIONS` and `OPS` are all read-only — and no RNG. And every one
of the 172 mutations rewrites a file under `crates/incise-core/src/`; not one
touches Python, so the oracle's answers are *identical* across all 173 runs.

So: run the oracle loop across a process pool, and let `mutate.py` compute it
once. Measured, on ten cores:

| | before | after |
| --- | --- | --- |
| `difftest.py`, standalone | 2 m 43 s | **37 s** |
| `difftest.py`, oracle reused | — | **8 s** |
| full `mutate.py` | 8 h 04 m | **35 m 08 s** |

Not one case changed, and not one comparison was skipped. What changed is how
the *expected* side is obtained, never what it is compared against — and the
evidence for that is not the argument above but the run itself: 172/172 caught,
and **every one of the 172 per-mutation mismatch counts byte-identical to the
eight-hour run's**. A cache that had gone stale would show up there first, as a
count that moved or a mutation that stopped being caught.

### The part that needed care

The parallel half is dull — `imap` preserves order, the cases are independent,
and the proof is that `-j 1` and `-j 10` produce byte-identical output over all
77580 cases.

The reuse half is the dangerous one, and it is dangerous in the specific way
this project is supposed to defend against. A stale expected-file does not
produce a wrong answer; it produces a **clean run for a reason unrelated to the
port**, and reports 172/172 caught. It is the surviving-mutation problem
inverted: instead of a green test that has never been shown to go red, a green
test that *cannot* go red. Being fast is worth nothing next to that.

So the file is keyed on a SHA-256 of everything the answers depend on — the
generated case blob, the source of **every module loaded out of this
repository**, and the bytes of every fixture. The module set is discovered by
walking `sys.modules` rather than listed, because a list of filenames is exactly
the thing that silently stops covering a new import. A key that does not match
is not an error: it recomputes and rewrites, so the worst a stale file can cost
is time.

Verified rather than argued, before the first run that depended on it:

| perturbation | key must | result |
| --- | --- | --- |
| append a comment to `bench/incise_ops.py` | move | moved |
| append a comment to `bench/difftest.py` | move | moved |
| append a line to a corpus fixture | move | moved |
| append a comment to `crates/…/similar.rs` | **hold** | held |

— plus the end-to-end version: with the oracle edited, a run that would
otherwise have hit the cache printed `expected: computed` against a new key.

One hole is left, and it is closed in `mutate.py` rather than in the key:
editing the oracle *while* a pass is in flight saves answers from the old code
under the new code's key. `difftest.py` therefore prints its key on every run,
and `mutate.py` records the baseline's and aborts the whole pass if it ever
moves — a run whose later mutations were judged against a different oracle than
its earlier ones is void, and the only honest thing to do with it is say so.
`k is None` is explicitly *not* that case: a `NOBUILD` or a panic kills the run
before it reaches the oracle and prints no key at all, and both keep their own
verdicts. That path was tested by breaking the crate on purpose, not reasoned
about.

### What it is evidence of

The eight hours were never a property of the differential method. They were one
serial loop and 172 recomputations of a constant, and nobody had looked because
the run was unattended and the number was tolerable. The generalizable form:
**an unattended cost is an unmeasured cost.** The same discipline that says a
green test is not evidence until it has been shown to go red says a slow run is
not a necessary cost until someone has timed its phases.


## F-nearmatch — the heuristic came off the near-match list too, and it took code away

F-autojunk turned difflib's autojunk heuristic off for the line diff and left it
on in the one place the oracle could not pass the flag: stdlib
`difflib.get_close_matches` builds its own `SequenceMatcher` and takes no
`autojunk` argument. That left an Open item, and the item sat open for a bad
reason — a cost estimate written without reading the function.

**What the item got right: the severity.** `get_close_matches` calls
`set_seq2(word)`, so the *caller's value* is the indexed side, and it diffs by
character — the 200-element threshold counts **characters of the string a model
sent**, not candidates. Above it, difflib drops every character occurring more
than `len / 100 + 1` times, which for a sentence means the spaces and the
vowels. The comparison stops being a string similarity. On
`bench/synthetic/long-cells.md`, of 168 probes **46 lost a match**, and a value
one word short of the D-1 cell — which scores 0.98 against that cell and 0.71
against its paraphrase — came back as:

```
no row where Rationale="…".
  Near matches: none
```

§5.3 makes that sentence the product. It tells a model there is nothing like
what it sent while a 98% match sits in the column, and S12 measured that loud,
wrong failures are the ones models recover from destructively.

**What the item got wrong: the cost.** It said fixing this "means reimplementing
a stdlib function inside the oracle, which is a larger claim than passing a
flag". `get_close_matches` is 48 lines, of which ~15 are body, and the only
change is `SequenceMatcher()` → `SequenceMatcher(autojunk=False)`. The hard part
— `SequenceMatcher` itself — stays stdlib, so the oracle keeps its authority
exactly where the authority matters. An estimate made by looking at a function's
reputation rather than its source is how a half-day change gets filed as a
research question.

### The fix deletes more than it adds

Turning the heuristic off makes three things in `similar.rs` dead, not merely
unused:

| what | why it goes |
| --- | --- |
| the `n >= 200` purge in `Matcher::build` | nothing asks for autojunk any more |
| the two non-junk extension loops | they can only fire on a match the DP failed to find, and an unpurged index makes that impossible |
| the `autojunk` parameter and `without_autojunk` | one constructor, one behaviour |

The second row is the argument that had to be earned. `j2len` carries the length
of the run ending at each `(i, j)`; with a complete index every matching pair is
visited, so the longest run in the region is found exactly. A left extension
needs `a[besti-1] == b[bestj-1]`, which would mean a strictly longer run ending
at the same `(i, j)` — and the DP would have recorded *that*. Same argument at
the other end. difflib needs the loops precisely because it purges; this port
does not have them because it does not.

That also re-grounds a comment that would otherwise have quietly become false.
`matching_blocks`' adjacent-block collapse was documented as unfireable *because
the left-extension loop tests the same condition*. Remove the loop and the
sentence is a claim with nothing behind it. The property survives — it now rests
on the DP's maximality directly — but the note had to be rewritten to say so,
and finding that was a matter of reading every comment that mentioned the code
being deleted rather than only the code.

### Four mutations retired, and the distinction that permits it

`difflib-autojunk`, `difflib-purge`, `difflib-extend-left` and
`difflib-extend-right` were caught by 46, 14, 33 and 29 cases. Nothing about
them was weak; their subject no longer exists. **A mutation may be retired when
its subject is unobservable in principle or has been deleted — never because the
cases stopped reaching it.** The first is a fact about the code; the second is a
fact about the corpus, and the corpus is the thing under test. Two of these four
were deleted once on the second, wrong ground, and had to be brought back.

They are replaced by one mutation that is strictly stronger than the four:
`difflib-autojunk-back` reinstates the heuristic exactly as difflib writes it,
which is the one state of this file that has been wrong twice. It is caught by
**618 cases** — more than the four it replaces put together, because reinstating
the purge breaks `get_close_matches` and `describe_change`'s line tally at once.
169 mutations, 169 caught.

### The evidence a differential test cannot supply

This change moves *both* implementations, so `difftest.py` keeps agreeing and
the agreement proves nothing about it. That is the first of the three
blindnesses stated in F-args: **a differential test cannot see an assumption
both implementations share.** Being green here was never going to be evidence.

So the oracle is pinned to something that did not move. Below 200 characters the
new keyword provably cannot do anything, so `_close_matches` must be stdlib
exactly; above it, purging can only remove entries from the index, so it can
only lower a ratio and shrink the qualifying set. `test_close_matches_tracks_stdlib`
checks both, over probes built from every heading and every table column in the
corpus:

| property | result |
| --- | --- |
| identical to stdlib below 200 characters | **0 differ of 22818** |
| stdlib's matches are a subset of ours above it | **0 violations of 105** |
| the two actually diverge above it (not vacuous) | **26 of 105 moved** |
| a value one word short of its cell finds the cell | ours `[cell]`, stdlib `[]` |

The third row is the one that keeps the other two honest. A probe set where
nothing diverged would pass rows one and two while testing nothing about the
change, which is the same shape of vacuity as a mutation that was never shown to
go red.

Two unit tests in `similar.rs` cover the port's half, and both were shown to fail
with the purge reinstated before being trusted.

### What it cost, and what it did not

**46 of 77580 differential cases move.** All 46 are `resolve_row` on
`long-cells.md`, and every one has an argument of 200+ characters; **not one case
whose arguments are all shorter changes at all.** Every address Arm B ever sent
was a real heading or column name, orders of magnitude below the threshold, so
nothing S14 or S12 measured is affected. This was always a question about
addresses a model might invent, not about a result anyone has — which is why it
could wait, and also why doing it now was nearly free. Once a front end exists
and something depends on message text, the same change stops being free.

`bench/synthetic/long-cells.md` keeps its place for a reason worth stating: it
was built to reach a branch that no longer exists, and it is now the only
document in the suite that exercises near-match ranking at a length where
ranking was ever wrong. A fixture outliving the defect it was written for is the
ordinary case.

### It also took coverage away, on a mutation nobody was aiming at

The full run came back **169/169 caught**, baseline clean, no survivors, no
`STALE`, no `NOBUILD` — and the thin tail had moved the wrong way. `near-cutoff`,
which raises `resolve_row`'s near-match cutoff from 0.4 to 0.6, fell from **31
catching cases back to 1**. A clean sweep read only on its total would have
reported this change as pure gain.

It is the exact mirror of the gain recorded two paragraphs up. `long-cells.md`'s
probes — each cell one word short of itself — used to be scored *through the
purge*, which pushed them down near the cutoff, which is why raising the cutoff
changed their answer. With the purge gone they score ~0.98 against their own cell
and ~0.71 against the paraphrase beside it. Both are above 0.6, so the mutant now
returns the same list the original does. Nothing about the cutoff got safer; the
one accident that made it observable went away with the heuristic.

That is the same lesson as the retirement rule, arriving from the other side. The
four retired mutations lost their *subject*; `near-cutoff` kept its subject and
lost its *witness*. Only the first is a reason to delete a mutation — and the
second is a reason to go find a better witness, because a mutation caught by one
case is one fixture edit from surviving.

The better witness is arithmetic rather than luck. A prefix holding fraction `f`
of a cell scores `2f / (1 + f)` against it, so a third of a cell lands at ~0.5 —
inside the 0.4–0.6 gap **by construction, from any cell**, with no threshold
written into the harness. `difftest.py` now emits that probe for every table cell
of three words or more: 225 new cases, of which 95 land strictly inside the gap.

| | catching cases |
| --- | --- |
| `near-cutoff` before `long-cells.md` | 1 |
| with the one-word-short probes (autojunk on) | 31 |
| after F-nearmatch removed autojunk | 1 |
| with the one-third-of-a-cell probes | **76** |

Two things are worth separating here. A value taken out of a document either
matches its own cell near 1.0 or is unrelated to every cell and scores near 0;
almost nothing lands in between by accident, which is why this mutation was ever
thin. And the harness had been *reading the gain* — 1 → 31 — as evidence the tail
was shortening, when it was evidence that one fixture happened to sit in the gap.

The re-run with the new probes is **169/169 caught** again, baseline clean, no
survivors, no `STALE`, no `NOBUILD`, over **77805 cases across 43 fixtures**. The
tail is back to the shape it had before this change — nine mutations caught by
five cases or fewer, two by exactly one (`filter-empty-null`, `json-infinity`) —
and `near-cutoff` is no longer in it.


## F-front — the front end exists, and it is where a measured result can be undone

Everything above this line was measured against a Python executor calling
`incise_ops.py` in-process. `crates/incise-cli` and `plugins/hermes/` put the
real binary behind real tool calls on real files, which unblocks Arm C. It also
creates the first place in this repo where a number can be lost without any test
failing, because none of the measured results are properties of `apply_op`
alone — several of them are properties of *what the caller does with the return
value*.

Four of those are now enforced in code rather than in prose.

**A successful edit prints one sentence, and `describe_change` finally has a
home.** S14's result was a subtraction: returning the outline in place of a
description cost 8/300 redundant continuations and three destroyed documents,
and returning *both* measured identically to the outline alone. So the CLI's
success path prints `describe_change` and nothing else — not the document, not
an outline, not a diff. `out.rs` says so in a comment with the numbers attached,
because a future reader adding "just the outline too, for context" would be
re-running S14's losing arm.

**The read renderers' output is byte-identical to the oracle's.**
`render_table_list` is not a convenience view; it *is* the Arm B prompt (§11
Tier 2). The §5.5 content hash therefore goes beside it — stderr in human mode,
a sibling JSON field otherwise — never appended to the string. Verified the
cheap way: `incise tables <f>` against `python3 bench/incise_ops.py <f>` for all
25 corpus fixtures, identical after dropping the oracle's per-file separator.

**The published schema is generated from `bench/armb.py`.** §6 makes the tool
description a requirement surface — B7 moved the table family by rewording one
paragraph, L3 moved the list family 61% → 91% by renaming one property — and
the failure mode is silent: a hand-copied schema is right the day it is written
and says nothing about any day after. `incise schema` emits `scheme_f`,
`list_g` and `section_g_hpath`, and the new `bench/schematest.py` asserts they
are still byte-identical to those three entries, reporting *every* divergence
with a path rather than the first. **Zero departures were needed.** The plan
anticipated two — the section address spelled `heading`, and `values` left
untyped — and both were already true of the adopted schemes.

**Nothing is validated before the core sees it.** The order arguments are
checked in is part of the contract: a malformed `values` outranks a nonexistent
table, and a malformed `position` does not, because the Python `OPS` lambda
evaluates its arguments left to right before the op runs. A front end that
rejected either early would answer the same call with a different sentence, and
§5.3 counts that as a regression. So `--args '[1, 2]'` is passed through to be
refused by the core, and an unknown op name goes to `apply_op` rather than to
clap, so the `unknown operation "x". Valid: ...` sentence is the one a typo
produces.

### Two front-end refusals that the oracle has no opinion about

Encoding is unspecified everywhere in REQUIREMENTS.md, so the front end decides
and says so rather than absorbing it. **Not UTF-8** is exit 2 — the core's
signature cannot accept it. **A leading U+FEFF is refused by name.** The core
*would* accept it, as an ordinary character in front of the first `#`; the
document would parse with no first heading, every address into it would miss,
and the refusal the model read would be about a section that is plainly there.
§5.5 says refuse and explain rather than produce a plausible-but-wrong edit.
Neither is under differential test, and neither pretends to be.

### The Hermes plugin, and two divergences from what was measured

`plugins/hermes/` registers `table_edit`, `list_edit`, `section_edit` and four
read tools, fetching the three edit schemas from `incise schema` at registration
so there is one copy of that text in the tree. Verified live through Hermes's
own loader: the tools appear in toolset `incise`, and one real edit applied to a
scratch copy of `corpus/tables/aligned.md`.

The plugin's `normalize` is a transcription of `armb.normalize`
(`bench/armb.py:890-922`), because the 5674 graded calls went through that
function. One of its renames is load-bearing rather than cosmetic:
**`new_heading` → `heading` is mandatory.** `section_g_hpath` publishes the new
name as `new_heading`; the core reads `["heading","title","text"]` for
`section-rename` and `["heading","title"]` for `section-insert`, and
`new_heading` is in neither. Without the rename, every rename and every insert
refuses for a heading the model did supply — a defect that would have looked
like a core bug.

Two divergences are recorded rather than assumed inert:

1. **Refusal framing.** §5.3's recovery rates (100% one-turn for tables in B3,
   75% for sections in S12) were measured with the tool result `"Error: " +
   message`, a plain string. Hermes's `tool_error` yields `{"error":
   "<message>"}`. The content is identical; only the framing moves.
2. **A long refusal is truncated at 2048 characters by the host.**
   `tools.registry.tool_error` bounds an error body before it reaches model
   context. incise's "no table under heading X" ends in a list of every heading
   that has a table, so a document with enough tables crosses that line:
   `corpus/documents/api-reference.md` produces 2200 characters and loses the
   last ~150 to a `… [truncated]` marker. **This is the first measured refusal
   in the project that does not arrive whole.** The plugin does not route around
   it — the cap is the host's policy applied to every tool it runs — but it also
   does not truncate or re-word on its own account, and `test_plugin.py` asserts
   the cut is the host's, at the host's threshold, with everything below it
   verbatim. The exposure is one corpus file in 25, and it costs the tail of a
   candidate list rather than the refusal itself.

### Four live runs, and the two things they changed

Not a measurement. One model (gemma4 via `custom:litellm`), one fixture, one
prompt, n=1 per condition, graded by reading the transcript and diffing the
file. It is recorded because two of the four runs found defects that no test in
this tree would have found, and both defects were in the front end.

The fixture is a v2.4 release-notes document: an aligned six-row table with a
`\|` in one cell, a five-item task list, nested `## Upgrading` subsections, a
fenced block containing a fake table, and a `## Known issues` section. The
prompt asks for six changes across all three families.

| | condition | edits via incise | document |
|---|---|---|---|
| R1 | no `AGENTS.md`; one read tool, `md_view(path, view)` | 4/6 | correct |
| R2 | `AGENTS.md` added | 5/6 | correct |
| R3 | read tool split four ways; prompt gained "Don't touch anything else" | **0/6** | **damaged** |
| R4 | `AGENTS.md` names the whole bypass class | **6/6** | correct |

R1 and R2 are the same session with the file read in between, so the only
variable is the instruction. R3 changed two things at once — the schema and the
prompt — and is not a clean step; what it establishes is a defect, not a
comparison.

**R1 → R2: a refusal recovered for the first time.** Both runs produced the same
refusal, from a byte-identical malformed call. In R1 the model abandoned the
family and finished with `patch`; in R2 it came back, took two more refusals,
and landed the edit. The intervening refusal said `Near matches: run the
differential suite` and the next well-formed call used that string verbatim —
§5.3's mechanism working outside the benchmark. One instance, one model.

**The read tool's `view` was absorbed by `list_edit`, deterministically.** R1 and
R2 both produced, byte-identically:

```json
list_edit {"list": {"heading": "Release checklist"}, "path": "…", "view": "lists"}
```

`action` missing, `view` in its place, refused as `list-None`. `list_edit`
requires `path`, `action`, `list`; the model filled the third required slot from
the wrong tool, because the toolset published two required enum discriminators
and one of `md_view`'s enum values named the list family. This is L3 again —
`item` and `text` were near-synonyms and the payload landed in the selector 39
times out of 60 — and it takes L3's remedy: remove the absorbable property
rather than describe it better. `AGENTS.md` was in context for R2 and did not
help, which is the expected result; the model was not disregarding guidance, it
was mis-binding a parameter.

`md_view` was therefore split into `md_tables`, `md_lists`, `md_outline` and
`md_rows`, each taking the path it reads and nothing else — no enum anywhere in
the read family. The renderers' output is unchanged and each tool returns its
renderer's string byte for byte, `md_tables` included, so merging the reads into
one call that concatenated them was rejected: that string *is* the Arm B prompt.
`test_plugin.py` now asserts the invariant structurally — no read tool may
publish a property an edit tool wants, and no read tool may publish an enum.

**`md_rows` is since retired — see F-rows.** The split stands and so does
everything above it; what did not stand is the one of the four that took
arguments. `table_get` renders `rows` now, and the invariant asserted here is
checked over it too, since it is published by the binary and would otherwise sit
outside the check written to catch its shape.

In R4 the absorption is gone. No call contained `view`.

**R3: an instruction that forbids one bypass routes to the next one.** The
`AGENTS.md` text said to use the tools "not `patch`" and named no other route.
The model obeyed the letter — it did not call `patch` — and went
`read_file` → `execute_code` → `write_file`, rebuilding the file's lines in
Python and writing all 1475 bytes back. All six content changes landed and it
reported success. It also returned a `Status` cell one space narrow, breaking the
table's alignment, and destroyed the file's trailing newline. The prompt for
that run said *"Don't touch anything else in the file."*

This is Arm A's failure mode arriving through the front end: the damage is
real, silent, and outside the edited range, and it was produced by a model that
had all seven tools available and ranked ahead of `patch` and `read_file`.
Naming one tool is not a policy. `AGENTS.md` now states the rule as a class —
never emit a whole markdown file that contains a table, a list or a section, by
`write_file`, by `execute_code`, or by any other route — and R4 used no rewrite.

**R4, and what is still wrong.** Six of six edits through incise, no rewrite
tool touched, and the document byte-correct apart from the delimiter row, which
is F-realign. Both new read tools were called, and `md_rows` was called *as
recovery from a refusal* — the read-after-refusal loop the descriptions ask for,
closing on its own for the first time.

That observation is the one that cuts against F-rows and it is left standing:
`md_rows` did work, live, in the loop it was written for. F-rows does not claim
otherwise. What it claims is narrower — there is an address `md_rows` could not
spell — and the loop survives the swap intact, because the sentence that asks
for it (*"and again if an edit is refused for a table or column that is not
there"*) is in `md_tables`, which did not change.

`section_edit` with `replace-body` took
the `## Known issues` change that R1-R3 all gave to `patch`.

`list_edit` still omits `action`, three times, now for a different reason: plain
omission, `{"match": …, "path": …}` with no verb. `table_edit` and
`section_edit` never did this in any run. One observation that may bear on it:
**`list` is declared required and was never supplied in any call, including the
successful one** — the core resolves without it. The one family whose required
set the model does not satisfy is the one family where it drops the verb.
Suggestive, not established.

Both levers on that are measured artifacts and neither is free. `unknown
operation "list-None". Valid: …` never says `action` is missing, and rewording it
is a change to a refusal §5.3 measured; the `list_edit` description is `list_g`,
which won 91% against `list_f`'s 61%. It belongs in the Open list with the rest
of the addressing decisions, to be settled once and re-measured — see
`REQUIREMENTS.md:1660`.

Two model-side defects, recorded because they shaped the transcripts and are not
incise's: gemma4 twice leaked tool-call syntax into a JSON string value
(`"renderer\"},value:"` as a `where` value; a path ending
`…notes.md`}<tool_call|>…`), and Hermes's loop guard fired twice on identical
repeated calls. incise refused the malformed calls cleanly, and in R4 the
`Near matches: renderer` line is what got the model back on track.

### What this is not

`bench/PLAN.md:1577-1591` closed "run real hermes" as won't-do and made the
limitation permanent: Arm A is a replication of hermes's edit path, never "the
hermes baseline". Driving the plugin is a product activity. Nothing that comes
out of it may be reported alongside an Arm A or Arm B number.


## Arm C — the same tasks and seeds, executed by the real binary on real files

Every rate above it was measured with `incise_ops.apply_op` called in-process,
on a string. Arm B reads a fixture from disk and never writes one. The shipping
artifact is a Rust core behind a binary that does, and §9's bar
(`REQUIREMENTS.md:1229-1250`) is written against that gap: Arm B's rates are the
bar the Rust must match, not beat — a regression is a bug in the port.

`bench/armc.py` is Arm B with one line replaced. `armb.run_trial:1041`

```python
after, err = apply_op(doc, op, op_args)        # in-memory string
```

becomes argv, a subprocess, a real file and an exit code. Everything else is
held fixed by *importing* it: the schemes, the system prompts, `build_payload`,
`normalize`, `runner.call`/`record` and `grade.check_result` all come from the
Arm B modules, because a transcribed copy of any of them would make this a
comparison between two harnesses. Per trial the fixture is mirrored into a temp
root at its **repo-relative** path and the binary is invoked with `cwd` set
there, so the model emits `corpus/tables/aligned.md` exactly as in Arm B, the
prompt is byte-identical, and the write lands in the sandbox. The corpus is
frozen; this protects it by construction rather than by care.

Ceiling first, as always: `ceiling.py --arm c` reads **31/31** across all three
task files. Six `ideal_call` fields were added to `tasks/tables.json` to get
there — checked under `--arm b` first (6/6), so the calls were known good under
the executor the numbers came from before Arm C was allowed to depend on them.

### The headline

Adopted schemes, 10 trials per task, paired on `(task_id, trial)` — the seeds
are identical, so every comparison below is a paired test on the same trials.

| family | scheme | Arm B correct | Arm C correct | Arm B silent | Arm C silent | McNemar |
| --- | --- | --- | --- | --- | --- | --- |
| tables | `scheme_f` | 60/60 (100%) | **60/60 (100%)** | 0 | 0 | p = 1 |
| lists | `list_g` | 91/100 (91.0%) | 86/100 (86.0%) | 0 | 0 | p = 0.0625 |
| sections | `section_g_hpath` | 130/150 (86.7%) | 120/150 (80.0%) | 14 (9.3%) | **2 (1.3%)** | p = 0.00195 |
| pooled | — | 281/310 (90.6%) | 266/310 (85.8%) | 14 (4.5%) | **2 (0.6%)** | p = 6.1e-05 |

Fifteen trials moved, all in one direction, and the discordance is significant.
Read alone that is a port regression. It is not one.

### Every trial that moved was missing `path`

The executor is not what changed. Each of Arm C's 410 recorded trials was
re-graded through *both* executors on its own recorded calls — the in-process
Python on a string, and the binary on a file — and the outcomes compared:

| | trials | executor disagreements |
| --- | --- | --- |
| every call carried a usable `path` | 351 | **0** |
| at least one call did not | 59 | 57 |

On every trial where the model named a file, the Rust binary writing to disk and
the Python reference editing a string produced the same graded outcome. Zero
divergences. That is the port result, and it is what §9's bar was asking about.

The other 59 are one thing: `path` is a required property in all three schemas,
and the model sometimes omits it. Arm B could not see that. The document was
already in memory, so `apply_op` never read `path` and a call without one
applied normally. The CLI has nothing to open and exits 2, which is why Arm C
carries an outcome class Arm B has no rows in:

| | tables | lists (`list_g`) | sections |
| --- | --- | --- | --- |
| `usage_error` (exit 2) | 0/60 | 5/100 | 27/150 |

All fifteen paired regressions are that class. Not one is a document incise
edited differently.

**So Arm B's list and section rates are optimistic by the size of that class,**
and this is the first measurement of by how much. The tables family is
unaffected — `scheme_f` supplied `path` on all 60 trials and Arm C reproduces
100% trial for trial.

### The direction the summary hides: silent becomes loud

Sections lost 10 correct trials and lost **12 of its 14 silent corruptions**:

| | Arm B | Arm C |
| --- | --- | --- |
| `wrong` | 12 | 1 |
| `destructive` | 1 | 1 |
| `collateral:formatting` | 1 | 0 |
| **silent corruption** | **14/150 (9.3%)** | **2/150 (1.3%)** |

McNemar on silent corruption: 12 discordant to 0, p = 0.00049. The mechanism is
the same missing `path`. In Arm B a path-less call *applied* — often to the
wrong place, in a sequence where a later call then compounded it — and the
document came back damaged with nothing raised. In Arm C that call cannot
execute, so a trial that used to end in a quietly broken document now ends in a
turn spent on an error message.

That is the trade §1.3 exists to make, and it is the one place Arm C is
unambiguously *better* than the reference it was built to match. The correctness
bar and the silent-corruption bar move in opposite directions here; the second
is the one the project is for.

### The port reverses a scheme ranking

`list_h` was re-run under Arm C for this reason. In Arm B it was the best list
scheme; under a real binary it is not:

| scheme | Arm B | Arm C | `usage_error` | McNemar |
| --- | --- | --- | --- | --- |
| `list_h` | **94/100** | 77/100 | 19 | p = 1.5e-05 |
| `list_g` (adopted) | 91/100 | **86/100** | 5 | p = 0.0625 |

`list_h` wins in memory and loses on disk, because it draws the model away from
`path` almost four times as often. The adopted schema is `list_g`, which is the
right answer for a reason nothing measured until now — the ranking Arm B
produced was an artifact of an executor that did not need the file argument.
This is the strongest case in the document for running an arm end to end:
a scheme comparison decided on an executor that ignores an argument is deciding
on a schema whose most-omitted required field is invisible.

### Recovery from a usage error is much worse than from a refusal

Of the 35 section trials whose first call exited 2, **8 recovered** within the
four-turn budget — 23%, against the **75%** §5.3 measured for one-turn recovery
from incise's own refusals. Every one of the 35 had it on the first call; no
trial supplied `path` and then stopped supplying it.

The message is the difference. A incise refusal names near matches, the headings
that do exist and the next call to make. What the model gets here is clap's:

```
error: the following required arguments were not provided:
  <FILE>

Usage: incise section-insert --args <JSON> --json <FILE>
```

That is the CLI's own words about its own argv, handed to a model that never saw
an argv — it describes a positional parameter in a call the model made as JSON.
It is correct, and it is not actionable in the way §5.3 means. **This is a
finding about the front end, not about the core**, and it is left open rather
than fixed here: `crates/incise-cli/src/main.rs` deliberately validates nothing
before `apply_op`, and a missing-file message that reads like a refusal is a
change to the front end's contract, to be decided once and re-measured.

One trial (`insert-release-at-top` t1) ends in an HTTP 500 rather than a grade,
reproducibly, at the same seed. It is downstream of the same cause: the usage
error cost two turns, the model then ran away to the 8192-token output cap and
emitted 29678 characters of truncated tool-call JSON, and llama-server rejects
its own unterminated argument string when that assistant message is echoed back.
Graded `malformed`, and counted against Arm C, which is what the taxonomy does
with an Arm B trial that errors too.

### What held

- **0 sandbox escapes** across 410 trials. No call named a path outside the
  temp root; `git status corpus/` is clean after every run.
- **Determinism across the process boundary.** Every multi-turn trial records
  the sha256 of the file it left behind; re-executing the same calls in a fresh
  sandbox at grade time reproduced it **149/149 times**. The same calls, a new
  process and a new filesystem, and the same bytes.
- **`difftest.py` unchanged** — 77805 cases still agree with the oracle. Arm C
  adds no core surface, and nothing leaked downward.

### What Arm C did not measure

It drives `crates/incise-cli` directly, not `plugins/hermes/`. That keeps it a
single-variable change from Arm B and keeps the numbers comparable —
`plugins/hermes/README.md:153-158` and `bench/PLAN.md:1577-1591` both forbid
reporting a plugin-driven result beside an Arm A or Arm B number, and they still
do. So the plugin's two recorded divergences — refusals framed as
`{"error": ...}` rather than `"Error: " + message`, and one corpus file's
refusal truncated at the host's 2048-character cap — are **not** what this arm
compared across. They remain open and unmeasured.

Raw trials in `results/armc_{tables,lists,sections}.jsonl`, graded siblings
beside them, regradable without re-spending GPU time.

## F-nofile — clap's largest failure class, and a wording fix that did not fix it

Arm C's largest single failure class was not in the core. A missing `FILE` was
answered by clap, not by incise: `error: the following required arguments were
not provided: <FILE>`, plus a `Usage:` line describing an argv the model never
wrote, on stderr, as prose, whatever `--json` said. Fifty-nine first calls
arrived that way and few recovered. The obvious fix is to take the sentence back
— drop `.required(true)`, check the path after `Format` is known, route it
through `out::usage` — and the obvious prediction is that recovery moves toward
the 75% section 5.3 measured for a refusal in incise's own voice.

**That prediction was pre-registered and it was wrong, twice.**

### The replay

S14's machinery one level over again: take the 59 prefixes whose first call
exited 2, hold everything before that turn fixed, and vary only the sentence the
tool result carries. Paired by construction, so McNemar. `armc.py --replay
--select usage`, three conditions, four turns each, same tasks and seeds:

| tag | the bytes the model was shown |
| --- | --- |
| `clap` | today's clap text — the replication check |
| `incise` | `` `path` is required, but no file was given.`` |
| `filefirst` | `no file to edit was given.` + `` `path` is the markdown file itself, not a heading path inside it.`` |

`clap` reproduced Arm C's rate (25.7% against 23%), which is `armb.replay`'s own
precondition for reading anything else in the table.

Primary endpoint, pre-registered: **does the very next call carry a non-empty
`path`?** Secondary: the graded outcome.

| | n | `clap` | `incise` | `filefirst` |
| --- | --- | --- | --- | --- |
| sections, next call has a file | 34 | **8 (23.5%)** | 3 (8.8%) | 4 (11.8%) |
| lists, next call has a file | 24 | 22 (91.7%) | 20 (83.3%) | **23 (95.8%)** |
| sections, graded `correct` | 35 | **9 (25.7%)** | 4 (11.4%) | 6 (17.1%) |
| lists, graded `correct` | 24 | 21 (87.5%) | 20 (83.3%) | **24 (100%)** |
| pooled, graded `correct` | 59 | 30 (50.8%) | 24 (40.7%) | 30 (50.8%) |

Against `clap` on the sections, both incise wordings are *behind*, and the
discordant pairs run one way: `incise` 5–0, `filefirst` 4–1 (p = 0.06, 0.38).
Pooled, `filefirst` ties clap exactly — 30/59 either way, discordant 4–4,
p = 1.0.

### What it actually says

**The family moves the number by seventy points and the wording moves it by
five.** Lists recover at 83–96% under every message including clap's; sections
recover at 9–26% under every message including incise's. No sentence tested
closes a gap that size, and the second wording was written specifically to
attack the mechanism the first one seemed to hit — it named the collision
outright ("not a heading path inside it") and bought nothing.

This is **S15's result arriving a fourth time**: *"an error message is advice,
and the model is not failing to take advice."* S15 proved it for a misfiled
heading path and fixed it in the schema, where it belonged. The same holds for
an absent one. Free evidence from the same rows: on the sections the model
answers the failure by editing `section`, `text`, `new_heading` and `position` —
anything but supplying the file — on 26/35, 29/35 and 28/34 trials respectively.
Two `filefirst` trials pasted the filename *into* `section.heading`, which is
the S15 misfiling surviving in the arm that was supposed to have removed it.

### The change was kept anyway, for a reason the replay cannot see

The harness frames stdout and stderr alike, so it scored clap's prose as though
a caller could read it. A `--json` caller cannot:

```
$ incise section-insert --args '{"section":"X"}' --json   # before
exit=2  stdout: <empty>  stderr: error: the following required arguments ...
$ incise section-insert --args '{"section":"X"}' --json   # after
exit=2  stdout: {"ok": false, "usage": true, "error": "no file to edit ..."}
```

clap exits before `--json` is parsed, so the plugin's `error` field is not wrong
but **absent**. That is a contract defect independent of which words win, and
`crates/incise-cli/README.md:113-127` already licensed fixing it: *"Only faults
the core can never see are answered here … a missing file."* Exit code stays 2
and the `incise:` prefix stays; `tests/cli.rs` pins both, plus the empty stderr
under `--json`.

`filefirst` is the adopted wording on the evidence that it is the better of the
two candidates and costs nothing pooled — not on evidence that it beats clap,
which it does not. **Whether incise's words are worth more than clap's here is
open.** What is closed is the idea that this bucket is a wording problem.

Raw and graded trials in `results/armc_replay_path{,_lists}{,_graded}.jsonl`.
The two plugin divergences (`{"error": ...}` framing, the 2048-character cap)
remain unmeasured; `armc.replay` now carries the `--framings` axis to do it.
*Both were run — F-framing. The pool for the cap turned out to be 1 refusal in
353, and the framing costs a turn rather than an outcome.*

*Later, and it sharpens this section rather than correcting it: "the family
moves the number by seventy points" is true but coarser than the data. It is not
the family. It is **one argument on one action** — 33 of these 35 section
prefixes are `section-insert`, whose adopted schema omits the file on 92% of
opening calls, and the 114 Arm C section trials that did name a file finished
`correct` 112 times. See F-fileblind. The conclusion here is unchanged and
better supported: the gap a sentence was being asked to close is 75 points
wide.*

## F-fileblind — the schema that stopped naming the file was chosen by an arm that could not see it

F-nofile left the section family's 9–26% as *"an S15-shaped problem — the
schema, not the sentence."* That was right and understated. Locating it needed
no new trials, only the ones on disk: `bench/file_argument.py`.

### Arm B does not grade the file argument. At all.

`run_trial` opens `task["fixture"]` itself and hands the **content** to
`apply_op` (`armb.py:1494-1533`). The model's `path` rides along inside
`op_args` and the core ignores it — which `plugins/hermes/README.md:109` already
records, as a reason to leave it there. The consequence was not recorded. One
`section-insert`, three ways:

| the call said | error | resulting document |
|---|---|---|
| no `path` at all | none | identical |
| the right file | none | identical |
| `/nowhere/absent.md` | none | identical |

Not merely blind to an omission — blind to a **wrong** filename. Every Arm B
number in this document was produced by an executor for which the file argument
is decorative. That is not a defect in the harness: Arm B is a schema
comparison, and pointing every trial at a known fixture is what makes the
comparison fair. It is a defect in what was concluded from it.

**S15 is unaffected, and the reason bounds this.** Its misfiled calls put the
heading path in `path` *and carry no `section` key at all* — 62 such calls in
the `section_g` control, every one of the shape `{"action": "set-level",
"level": 2, "path": "Deep heading nesting > Reference > API"}`. They fail
because the required address slot is empty, which Arm B can see perfectly well.
So S15 measured a real thing and its fix worked. What Arm B could never have
seen is the other half of the same class: a call that misfiles the heading into
`path` **and** fills `section` correctly would have graded `correct`. How large
that half is, is unknown, and it is unknowable from Arm B by construction.

### And the adopted schema drifted into omitting it

Every recorded opening tool call, by action:

| tool/action | calls | named no file |
|---|---|---|
| `section_edit/insert` | 1038 | **929 (89.5%)** |
| `section_edit/set-level` | 360 | 81 (22.5%) |
| `section_edit/append` | 1047 | 219 (20.9%) |
| `list_edit/set-checked` | 102 | 22 (21.6%) |
| `list_edit/add-item` | 820 | 129 (15.7%) |
| `list_edit/remove-item` | 189 | 17 (9.0%) |
| `section_edit/rename` | 433 | 38 (8.8%) |
| `section_edit/delete` | 240 | 17 (7.1%) |
| `section_edit/replace-body` | 623 | 33 (5.3%) |
| `table_edit/*`, `frontmatter_edit/*` | 1370 | **1 (0.1%)** |

One action, off the scale. It is not an argument-count effect —
`table_edit/update-cell` carries *more* arguments than `insert` and omits the
file 0 times in 70. And it is not an era effect, which is the check that
matters, because `section_g` is the *tuned* scheme:

| section action | `section_naive` / `section_p` | the `section_g` family |
|---|---|---|
| append | 13/38 (34.2%) | 206/1009 (20.4%) |
| delete | 7/20 (35.0%) | 10/220 (4.5%) |
| rename | 1/40 (2.5%) | 37/393 (9.4%) |
| replace-body | 8/51 (15.7%) | 25/572 (4.4%) |
| set-level | 2/20 (10.0%) | 79/340 (23.2%) |
| **insert** | **3/31 (9.7%)** | **926/1007 (92.0%)** |

Five actions got *better* or held; `insert` went from one-in-ten to nine-in-ten.
Paired by (task, trial) the way S15 pairs — same task, same seed, one schema
factor — `section_p` against `section_g` on the 16 shared insert trials:
**15–0, McNemar exact p = 6.1e-5**, across two tasks.

### What the two halves are together

The schema comparisons that selected `section_g` — S6 through S15 — scored a
call naming no file as `correct`, because they could not do otherwise. So the
selection pressure on the file argument was **zero**, and the winning schema
drifted off it on the one action where the model has four other slots to fill
and a new thing to name. Arm C is the first arm that can see the omission, and
Arm C is exactly where the 9–26% was measured. F-nofile's replay then varied
the *sentence* against a population whose fault was upstream of any sentence.

That is caveat 18's shape (*"a paired arm showing no discordant pairs may not
have exercised the change"*) with the sign flipped: **an arm can show a
difference on an argument it never evaluated.** It joins the caveat list.

### What it cost, in the arm that could see it

Arm C drives the real binary, which reads `path`, so it is the only arm on disk
that ever scored this argument. It scored it as **the entire difference between
a working section family and a broken one.**

Every one of the 149 section trials falls on one side of a clean line, and the
line is the file argument:

| opening call | first exit | n | `correct` after four turns |
| --- | --- | --- | --- |
| named a file | 0, all 114 | 114 | **112 (98.2%)**, 95% CI 93.8–99.5 |
| named none | 2, all 35 | 35 | **8 (22.9%)**, 95% CI 12.1–39.0 |

(`armc_sections.jsonl` holds 151 lines and 150 distinct `(task, trial)` keys:
`insert-release-at-top` trial 1 is recorded twice, both times as an
`HTTPError: 500` with no tool call at all. It is excluded from every count here
because there is no opening call to classify — a server fault, not a model
behaviour.)

Both columns are total, and only one of them is tautological. Omitting a
required argument failing is by construction. **114 of 114 first calls that
named a file exiting 0 is not** — it says no other fault in the family cost a
single opening call: not a heading that missed, not a `position`, not an
`action`. After S15, the file argument is the only first-call fault the section
family has left. 33 of the 35 omissions are `section-insert`, which is F-nofile's
"largest single failure class" and F-fileblind's 92% turning out to be one
population counted twice.

This also prices the three findings against each other. F-nofile moved this
bucket by **five points** by rewriting the sentence, and recorded that as a
failure to reproduce a pre-registered prediction. The gap the sentence was
being asked to close is **75 points**, and it is not a sentence-shaped gap.

**The split is observational and is not reported as causal.** Nothing assigned
`path`; the model chose, and `insert` is both the action that omits it and
plausibly the harder action. Holding the task fixed is the most this data
supports, so:

| | named a file | named none |
| --- | --- | --- |
| `append-after-fence` | 9/9 | 1/1 |
| `append-atx-line` | 9/9 | 1/1 |
| `insert-release-at-top` | 1/3 | 0/6 |
| `insert-subsection-last` | 2/2 | 5/8 |
| `insert-troubleshooting` | 1/1 | 0/9 |
| **total** | **22/24 (91.7%)** | **7/25 (28.0%)** |

Exact stratified (Cochran–Mantel–Haenszel) over the five strata, **p = 0.016**.
McNemar is deliberately not used and `stats.mcnemar_exact` is not reused: every
other paired comparison in this project *assigned* the thing under test, and
this one is a split on the model's own behaviour. The contrast is thin — 49 of
149 trials survive the stratification — and it is thin for the reason that is
itself the finding: the omission is so near-total on insert that
`insert-troubleshooting` offers exactly one trial that named the file against
nine that did not. That is reported rather than smoothed.

Regenerate both tables with `python3 bench/file_argument.py`.

### The cause was already measured, in S15, on an endpoint S15 could not grade

S15 ran the experiment. It just asked it a different question.

S15's three arms were assigned and paired by `(task, trial)`, with every
description string byte-identical across all three so that only one key moved:
the control calls the file `path` and the address `section.path`;
`section_g_file` renames the file to `file`; `section_g_hpath` renames the
address to `section.heading`. S15's endpoint was **misfiling** — does the
heading end up in the file slot — and on that endpoint the two renames came out
*identical*: 9 misfilings to 0, same cells, same discordant pairs. It concluded
that the collision itself was the problem and either disambiguation removes it.

That conclusion is correct and this does not disturb it. But S15 wrote its
inference rule down in advance —

> if only `section_g_file` moves, the top-level name is pulling the value; if
> both move, the collision itself is the problem and either disambiguation buys
> it

— and the arm could not grade *whether the model named a file at all*. So the
rule was never applied to that endpoint. Applied now, to the same rows, it does
not return the same answer:

| action | n | `section_g_file` vs control | `section_g_hpath` vs control |
| --- | --- | --- | --- |
| `append` | 44/45 | 0–9, p = 0.0039 ✓ | 0–9, p = 0.0039 ✓ |
| `delete` | 10 | 0–0 | 0–0 |
| **`insert`** | 40 | **0–16, p = 3.1e-5 ✓** | 0–5, p = 0.063 |
| `rename` | 20 | **10–1, p = 0.012** | 0–3, p = 0.25 |
| `replace-body` | 25 | 0–0 | 0–0 |
| `set-level` | 60 | 0–7, p = 0.016 | 0–7, p = 0.016 |
| **pooled** | | 10–33, p = 6.1e-4 | **0–24, p = 1.2e-7** |

Cells read *control-only – arm-only*; ✓ marks the ones that clear Bonferroni at
12, which is the honest bar here because this is 6 actions × 2 arms of
comparisons on an endpoint chosen *after* seeing the Arm C split above.

**On insert, only `section_g_file` moves.** By S15's own rule, that makes the
top-level name the thing pulling the value — 1/40 under the control, 17/40 when
the file slot is called `file`, against 6/40 when the *address* is disambiguated
instead. It is not slot-stuffing: all 17 values are `.md` paths and all 17 are
the task's own fixture.

So the suspect named in the previous section — `section_g`'s added insert clause
— is not exonerated, but it is no longer the leading explanation. A competing
cause has been demonstrated on assigned, paired data: **two arguments called
`path`, one of which is not a path.**

### What it costs, which is why this is not simply a fix

`section_g_file` is not free. It is the only cell in the table that moves
*backwards*: rename 10–1 against the control, concentrated on two tasks (8 of
the 10 on `rename-closed-atx`). At p = 0.012 it does **not** clear Bonferroni at
12, so it is reported as suggestive rather than established — but it is legible
in a way that discourages dismissing it. Under `section_g_file` the model stops
filling the file slot on rename and starts filling `text` instead, and in one
trial it narrates the problem into that slot verbatim:

```
"text": "File not provided for rename operation directly if it had bo…"
```

The model knows the file is missing and writes a sentence about it into the
wrong key. Whatever `file` buys on insert, it appears to cost somewhere, and a
schema decision that ignored the backwards cell would be doing the thing this
finding exists to warn about.

**The adopted schema is the better of the two on the pooled endpoint** —
`section_g_hpath` is 24–0 with no action worse anywhere, p = 1.2e-7 — and S15
adopted it, on a different endpoint, for a different reason. That is luck rather
than method, and it still leaves insert at 15%.

### What is not established

*(Written before S16. The first item below is the one S16 went and measured;
the rest still stand.)*

~~The combination.~~ `file` at the top level **and** `section.heading` for the
address is the obvious candidate — it is the only cell of S15's 2×2 that was
never run, because S15 deliberately ran single factors, which was the right
design for its question. Whether the two effects add, or whether `file`'s rename
cost follows it into the combination, is unmeasured. **Measured in S16 below:
they do not add, and the rename cost does follow.**

Nor is the counterfactual from the Arm C split established. That the 35 omitters
would reach 98.2% *if* the schema made them name the file assumes the two groups
differ in nothing else, which is exactly what an observational split cannot
show. The stratified table is consistent with it and does not demonstrate it.

The insert clause also remains untested as such. All three S15 arms carry it, so
nothing here varies it.

**What the experiment should be has changed, and got cheaper.** The previous
section pre-registered an Arm C A/B on the insert clause. That is now the wrong
experiment on two counts: the clause is no longer the leading suspect, and Arm C
is not required. The endpoint — *did the opening call name a file* — is recorded
in Arm B's `tool_calls` even though Arm B does not **grade** it, which is the
whole mechanism of this finding and is what made every number above readable off
trials that are already on disk. So the next run is **Arm B**, a fourth arm
carrying both renames, paired against `section_g_hpath` on the section tasks,
with rename watched as the pre-registered harm. Arm C is worth spending only
after that, to confirm the outcome consequence the Arm C split above predicts.

### S16 — pre-registration

Written and committed **before the arm was run**, so the registration is
checkable against the commit that carries it rather than asserted afterwards.
Everything above this line was read off trials already on disk; everything below
it costs GPU time.

**The arm.** `section_g_both` = `_section_tool("new_heading", guard=True,
file_arg="file", addr_arg="heading")` — the empty cell of S15's 2×2. Checked
before running that only the two keys move: property order preserved, both
`required` lists updated, and every description string byte-identical to
`section_g`'s, *including the two renamed slots*, which carry the control's own
text. `normalize` already maps `file` → `path` and `section.heading` →
`section.path`, so the executor sees arguments byte-identical to the control's —
this is a front-end rename and nothing else. Ceiling **60/60** across all four
section arms before any GPU time.

**Control.** S15's stored `section_g_hpath` rows — the adopted schema, same
model (`gemma4-direct-q8`), same 15 tasks, same 4 turns, same `--result-shape
delta`. Re-running it would buy nothing and cost half the GPU time; pairing is
by `(task, trial)` against what is already there.

**Primary endpoint.** Does the opening call name a file, on `insert`. Paired
McNemar. Predicted direction: `section_g_both` ≥ `section_g_hpath`, because the
effect `file` carries on insert (0–16) is larger than the one `heading` carries
(0–5), and this arm has both.

**Pre-registered harm: `rename`.** `section_g_file` was 10–1 *backwards* there.
If that cost follows the top-level rename into the combination, it shows in this
cell, and the arm must not be adopted on the insert win alone. It is named in
advance precisely so a good insert number cannot be reported without it.

**Secondary.** Pooled across all six actions; and the graded outcome, reported
with the standing caveat that the grade cannot see the file argument at all, so
it is not the endpoint and is not evidence about it.

**What would falsify the account above.** If `section_g_both` does not beat
`section_g_hpath` on insert, then `file`'s advantage is not additive with the
address rename, and the single-factor reading — that the top-level name is what
pulls the value — is wrong or incomplete.

### S16 — the result

150 trials, 15 section tasks × 10, paired by `(task, trial)` against
`section_g_hpath`'s stored rows. Reported in the registered order.
`python3 bench/file_argument.py` regenerates every number below.

**Primary: held.** On `insert`, the opening call named a file in **6/40 (15%)**
of control trials and **19/40 (48%)** under `section_g_both` — paired **3–16,
p = 0.004425**. All 19 named the task's own fixture; none named a file that was
not the document under edit. The falsifier named in advance did not fire.

**Pre-registered harm: confirmed.** On `rename`, the arm is **10–0 backwards,
p = 0.001953**. Ten trials named a file under the control and named none under
the arm; zero moved the other way. The harm is not diffuse — it is all ten
trials of **`rename-closed-atx`**, and `rename-setext` is 0–0.

The mechanism is `section_g_file`'s, unchanged, and it is checkable rather than
inferred: in all ten rows the argument keys are exactly
`action, new_heading, section, text`. The address survived the rename; the
**file slot emptied and `text` appeared in its place** — eight `null`, one `"}"`,
one a decoder spill (`"\"}<tool_call|><|thought|>…`). S15's `section_g_file`
rename losses have the *same* key set in all ten of its rows, with one of them
carrying the model's own account of it as the value:
`"File not provided for rename operation …"`.

**Pooled: a wash.** Across all six actions, **13–17, p = 0.5847**. The insert win
and the rename loss are the same size.

**Secondary, graded.** `section_g_hpath` **130/150 = 86.7%** (95% CI 80.3–91.2),
`section_g_both` **126/150 = 84.0%** (77.3–89.0); discordant 8–4, McNemar exact
**p = 0.3877**. Reported because it was registered, and with the caveat it was
registered under: the grade cannot see the file argument at all, so this is not
the endpoint and is not evidence about it.

**The decision: not adopted. `section_g_hpath` stays.** The combination buys
insert and sells rename at roughly one-for-one, and the registration said in
advance that the arm must not be adopted on the insert win alone. It was not.
This also settles the 2×2: the two renames are not additive, they are in
tension, and F-fileblind's remaining lever is not a third schema variant.

**The methodological result is the more durable one.** The rename harm was a
**post-hoc** signal in the S15 re-read — p = 0.012 on an endpoint chosen after
seeing the Arm C split, one of twelve comparisons, and it does **not** survive
Bonferroni at 12. It was named in advance anyway, as the thing that would block
adoption, and it replicated independently at **p = 0.002** on the same task with
the same mechanism. A signal failing a correction is not a signal shown to be
absent; it is a signal the study was not powered to assert. Pre-registering it
is what turned the question into an answer, and the answer is the one that cost
the arm its adoption.

## F-address — one addressing habit, and the bug a lockstep pair cannot see

`REQUIREMENTS.md` §6.4 says the three families teach one habit. They taught
four, and the open item named three of them. The fourth was worse than any of
the three and was found by reading `resolve_section` next to `resolve_table`
rather than by any test, because **no test could have found it**: `difftest.py`
compares the port against the oracle, the oracle had the same defect, and two
implementations agreeing is not the same as two implementations being right.

| | before | after |
| --- | --- | --- |
| **A** `{"ordinal": "0"}` | addressed a table and a list, **refused a section** | addresses all three |
| **A′** `{"path": 1}` | stringified to `"1"` and hunted for as a heading | typed refusal naming the key the caller sent |
| **B** `position` | see below | one parser, in the list family's own nouns |
| **C** ordinal refusal | `Valid ordinals: 0` in answer to `ordinal: 1` | names the rule, the real ordinals, and the repair |

A′ is not in the open item and is the same line as A: `resolve_section` never
called the per-field checks its two siblings both call.

### B: `position`, measured against the pre-change binary

The open item said the list family compared `position` against the literal
`"start"` while the table family trimmed and case-folded. That understates it.
Same fixture family, same argument, both binaries, insertion point read off the
resulting file:

| `position` | table, before | list, **before** | list, after |
| --- | --- | --- | --- |
| `"start"` | start | start | start |
| `"Start"` | start | **end** | start |
| `"  START  "` | start | **end** | start |
| `0` | start | **end** | refused |
| `"end"` | end | end | end |

Three values meant **start on a table and end on a list**, silently, reported as
success. That is F-pipes/B6's shape of defect — not a refusal the model can act
on but a wrong document the model is told is right — and it sat behind an
argument name the two families share.

`0` is refused rather than reconciled, which is a decision and not a
consequence. A table row index is an address into an ordered set of rows;
`list-add-item` has no index at all, only start, end, and `after`. Accepting an
integer would have to mean start-or-end by a rule the caller cannot see, so the
list family refuses it and the refusal points at `after` — the argument that
actually expresses "put it there".

### C: the message, and why running it mattered

With `check_ordinal` in the path the old refusal became legible, and legible is
how it was caught. `resolve_section` was refusing `ordinal: 1` with
`Valid ordinals: 0` — the f-string interpolated a `str` and an `int`
identically, so a rejected `"0"` was told `0` was valid. That is the message
S11/S12 asked to be rewritten, and it is the same code path, so it was rewritten
here.

The rewrite was then **run**, against `api-reference.md`, and printed this:

```
no section "Errors" with ordinal 9.
  Ordinals count sections that share a heading path, starting at 0.
  This one has ordinals 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  0, 0, 0. Send ordinal 0 or 0 or 0 or ... , or drop it.
```

`"Errors"` is twenty-one sections with twenty-one **different** paths, each
ordinal 0 within its own group. An ordinal cannot tell them apart, so the repair
the message offers cannot be taken — §5.3's failure, in a sentence written to
satisfy §5.3. `difftest.py` passed 82809/82809 with this in place, because the
oracle said it too. Both sides were changed in lockstep, which is the rule that
keeps the pair honest and is exactly what makes the pair blind to a shared
mistake. **A differential suite proves agreement. It does not proof-read.**

The resolver's *no-ordinal* branch already made the right distinction — distinct
paths mean "use a longer path", a shared path means "pass an ordinal". The fix
was to compute that split before the ordinal branch so a **missed** ordinal
makes it too:

```
no section "Errors" with ordinal 9.
  These 21 sections have different paths, so an ordinal does not tell them
  apart. Use a longer path.
  Candidates: "API reference > Accounts > list > Errors"; ...
```

and, where an ordinal really is the tool:

```
no section "Notes" with ordinal 9.
  Ordinals count sections that share a heading path, starting at 0.
  This one has ordinals 0, 1, 2. Send ordinal 0 or 1 or 2, or drop it.
```

### Grade-neutral, enumerated

`regrade_snapshot.py` against the tree at `2fd063f`: **156 of 6678 recorded
calls moved.** The snapshot hashes a 26-file vector per call, so the digests
were replayed element-wise, old executor and new, in separate interpreters:

**4056 vector elements compared across the 156 moved keys. 216 differ. Zero
involve a document on either side** — every difference is a refusal string, and
a refusal writes no document, so no grade can move. The 216 fall into two
families and nothing else:

- **164** are C, the ordinal refusal (`Valid ordinals: 0` → the three-line
  message). Every one of them is the `just ordinal 0` shape.
- **52** are A′: `{"path": ["Changelog", "[1.4.2] - 2026-08-14"]}`, which used
  to be stringified to `"['Changelog', '[1.4.2] - 2026-08-14']"` and hunted for
  as a heading path — producing a not-found refusal that listed candidates — and
  is now a typed refusal naming `section.path`.

The table family's `position` messages were separately proven **byte-identical**
against the pre-change binary on nine values, a check `difftest.py` structurally
cannot make: it compares the two implementations to each other, not either to a
golden.

### Three coverage gaps, all of them found by this change

1. **`ops/list.rs`'s `position` had no mutation at all.** `grep position` in
   `mutate.py` returned only table-family entries. Tightening an untested line
   is how a fix becomes a regression nobody sees; the family now has four.
2. **`difftest.py` emitted no section case for a headingless document.** A
   `if outline:` guard skipped the whole section-dispatch block, so
   `"this file has no headings, so no section can be addressed."` was reached by
   nothing, and `section-ordinal-late` survived on that gap before the guard was
   widened.
3. **No document could reach the valid-ordinal list's `dedup`.** It needs a leaf
   that repeats under one parent *and* appears under another, so the hits carry
   ordinals 0, 1 and 0. `section-repeats.md` gives three distinct paths (the
   ambiguity branch); `duplicate-siblings.md` gives one shared path (ordinals
   0, 1, 2, never colliding). `section-ordinal-dedup` survived, and the fix is
   `bench/synthetic/section-ordinal-mix.md` rather than deleting the dedup —
   correct code no document exercises reads identically to dead code from a
   mutation run, and they are opposite problems.

`difftest.py` 77805 → **84267** cases over 44 fixtures; `mutate.py` 169 → **180**.

### Re-measured — and the reason the result is weaker than it looks

*"One decision on the shipping schema, re-measured, not a quiet edit."* The
first attempt at that re-measurement was **circular, and reported as a result
before that was noticed.** Re-running the arm at the stored seeds reproduced the
baseline exactly, which was read as end-to-end confirmation. It was not: ignoring
the random call IDs, the model's calls came back **250/250 identical** in name and
arguments. Same seeds, same prompts, same temperature — a replication, not a
sample. It could not have disagreed.

The redesign uses the S8 property that grading is a separate pass over raw
trials, so one arm run can be graded through two executor trees. Fresh seeds
**10–19**, which the change has never seen, run once; the *same* model calls
then graded through the pre-change worktree at `2fd063f` and through the new
tree. Pairing is by construction — not by seed alignment, but because both
graders read one set of calls.

| family | seeds | n | pre-change | post-change | discordant |
|---|---|---|---|---|---|
| lists | 0–9 | 100 | 91 | 91 | 0 |
| lists | **10–19** | 100 | **87** | **87** | 0 |
| lists | pooled | 200 | 178 | 178 | **0** |
| sections | 0–9 | 150 | 130 | 130 | 0 |
| sections | **10–19** | 150 | **129** | **129** | 0 |
| sections | pooled | 300 | 259 | 259 | **0** |

500 trials, zero discordant pairs, and the outcome *labels* are identical too —
the `op_error`, `wrong`, `destructive` and `collateral:formatting` counts match
exactly, not just the `correct` totals. McNemar is undefined on a table with no
discordant pairs, which is the strongest form the answer can take. The 87-vs-91
and 129-vs-130 gaps are what confirm seeds 10–19 are a genuine second sample
rather than another replication.

**The caveat that makes this honest: none of those 500 trials exercises the
fix.** Inspecting every tool call in both result files — 616 of them, including
the calls inside multi-turn section trials — for an argument that would reach a
changed path returns **zero**. Every list `position` the model sent was the
canonical `"end"` (72 of them); every section `position` was one of the four
anchor relations, which this change deliberately does not touch; not one
`path`, `heading` or `ordinal` arrived with a non-canonical type. So the arm
establishes that the change **costs nothing** on these tasks, which is what a
tightening most needs to show, and it establishes nothing whatever about the
change **working**. That evidence is entirely in `difftest.py`'s 84267 cases and
the 180-of-180 mutation run.

That is not a flaw in the experiment so much as a measurement of the task set:
the tasks were built to be answerable, so the model is never pushed into the
argument shapes where addressing diverged. A task set that provoked them would
be a different instrument, and is the honest prerequisite for any claim that
this change helps rather than merely not-hurts.

**Arm C has not been run.** Only Arm B. Divergence **C**, the missing `action`
(`unknown operation "list-None"`), is taken up separately in F-action below —
where reading the recorded population first turned out to change what the fix
had to say.

## F-action — divergence C was two faults, and the one in the arm files is not the documented one

Divergence **C** has stood as: *a missing or misspelled `action` is answered
with thirteen op names and never the word `action`*. The plan was to add the
check to `armb.normalize` behind a default-off flag, measure it as a condition,
and adopt it into `plugins/hermes/__init__.py` only if it won. The flag and the
check exist. The measurement does not, and the reason is that reading the
recorded population first changed what the fix had to say.

### What the recorded calls actually contain

Every edit-tool call in every file under `bench/results/`, from
`bench/action_sizing.py`, which replays each one through `_action_of` and sorts
the outcome into the four messages that function can raise:

| | count |
|---|---|
| `action` arrived as its own key, holding a valid op name | 7522 |
| `action` misspelled | **0** |
| `action` a non-string | **0** |
| `action` genuinely absent | **0** |
| `action` fused into the next key's name | **11** |
| *(arguments did not parse at all — the check never sees these)* | 2 |

**7535 calls, and three of the four messages have no caller anywhere.** The
first figure published here was 6678, computed once into prose; by the time
anything recomputed it the directory held 2145 more calls. That is the same
failure mode F-framing's population figure had twice, so the number is now a
command rather than a sentence, and this table is its output.

> **This table was published as 21 of 8823 and the fused-key count is really
> 11.** The other ten are the same calls counted twice: `bench/results/` holds
> replay output, a replay pins its prefix's first call and re-executes it, and
> all ten duplicates sit at call index 0 — checked, not assumed. Corrected when
> `bench/population.py` took over the selection; see F-unique. The finding is
> unchanged in kind and smaller in degree, which is the direction that matters
> here: there are **fewer** independent events, not more.

The 11 are one shape — the key is `"action=add-item,item"`, or `,after`,
`,list`, `,last_item`, or `"action=set,key"`. The model wrote `action=add-item,`
in a syntax that is not JSON and the following key name fused onto it. **It sent
`action`.**

So for every case in the arm files, the documented fix would have been false:
telling a caller that `action` is required when `action` is the one thing it
supplied. That is F-address's twenty-one zeroes again, one layer further out —
advice that cannot be taken, generated by a message that assumed the shape of
the fault instead of reading it.

### But the omission is real — it is just not in the arm files

The zero above is a property of `bench/results/`, not of the world, and reading
it as the latter would be the same error in the other direction. The live
hermes runs found genuine omissions twice, and they are recorded above in
F-front:

- **R2** produced `list_edit {"list": …, "path": …, "view": "lists"}` —
  `action` absent, with `view` in the third required slot, absorbed from the
  read tool's enum.
- **R4** cost `list_edit` three refusals and an extra `read_file` on the same
  fault before it recovered.

Those are n=1 hand-graded transcripts, not in the tree and not replayable, and
`plugins/hermes/README.md` forbids quoting them beside an Arm A or Arm B
number. They cannot size the population. They are enough to establish that it
is not empty, which is all that is needed here: **both sentences have a real
caller**, and a check with only one of them would be wrong for somebody. That
is why the implementation branches four ways instead of one.

### The fused population is two sampling trajectories, not twenty-one events

| family | scheme | calls | fused |
|---|---|---|---|
| lists | `list_naive` | 100 + 86 replayed | 3 + 6 |
| lists | `list_i` | 100 + 62 replayed | 2 + 4 |
| lists | `list_g` (adopted), `list_h`, `list_f` | 1107 | **0** |
| frontmatter | `front_naive` | 372 | 3 |
| frontmatter | `front_p` | 364 | 3 |
| frontmatter | `front_r` | 240 | **0** |
| everything else | | 6392 | **0** |

**Every list fusion is at trial 5; every frontmatter fusion is at trial 8.** In
each family the two schemes with near-identical prompts produced it and the
family's third scheme — more calls than either, same `action=X` prose in its
tool description — never did. The prose is therefore not the cause, and the 21
are not 21 independent observations: the list rows are three tasks at one seed,
sampled twice and then replayed by F-framing at both framings; the frontmatter
rows are **one task at one seed** (`add-build-cache`), the same scheme/seed run
three times as `_v2`/`_v3`. Effective n is **two** — one degenerate generation
per family.

That is caveat 2 (*"seeds collapse where the model is confident"*) arriving from
the other direction. F-frontread spotted the frontmatter half while the family
was being built and called it a replication; what the regenerable scan adds is
the count — **six** occurrences, not the four recorded there, which counted the
`_v2` and `_v3` re-runs and missed the two base files — and the confirmation
that the signature is complete: same seed, same task, only the two
near-identical prompts, never the family's third scheme. Whatever produces a
JSON-syntax collapse is a property of the decode trajectory, not of the
vocabulary being decoded.

That is what blocks the measurement, not the absence of machinery. The fused
pool is two seeds, and no task can be written to provoke a JSON-syntax collapse
on demand; the omission pool is two live runs that may not be put beside an arm
number. A replay condition over either cannot distinguish a better sentence from
a different sample. The condition stays built and unrun, the same standing as
workstream 1's `json` and `cap`.

### What was built

`normalize` gains four branches under `CHECK_ACTION`, one per fault shape,
because the shapes need different repairs: the fused key is **named** (the
first line quotes it, and no `Got:` line follows — the value belongs to
whichever key it was meant for and runs to hundreds of characters, so quoting
it truncated would put a broken JSON fragment in a refusal); a genuine omission
gets the generic sentence; a typo gets the spelling and no diagnosis of *why*
it differs, since `setlevel` and `set_level` reach it alike and only one is an
underscore; a non-string gets `Got:`.

Two supporting pieces:

- **`ACTIONS` is derived from the schemes' own published `action` enums**, so
  the names offered are exactly the names the calling tool offered. The list is
  **family-scoped** — a model that called `list_edit` is shown three names, not
  thirteen across three families. The core is right to name all thirteen,
  because the CLI is given an op directly and any of them could have been meant;
  only the front end knows which tool called.

  It was derived from `OPS` first, on the stated grounds that naming what the
  executor accepts was *"the lesser evil — the alternative is a list that can be
  wrong."* That was a false choice and it had a cost: `OPS` contains
  `table-realign`, which **no** published `action` enum offers, so the refusal
  would have handed the model a capability the tool did not have — the condition
  would have changed the offered surface as well as the sentence, confounding
  the one thing it was built to measure. All 24 scheme entries publish exactly
  one enum per tool name, so the list can be both correct and confined to what
  was offered; two assertions in `_actions_from_schemes` stop the harness if a
  scheme ever disagrees with another or publishes an action the executor cannot
  run.
- **`ArgError` + `err_text`.** Every call site rendered a `normalize` exception
  as `f"{type(e).__name__}: {e}"`, so a refusal raised here would have reached
  the model as `ArgError: ...` — a Python type name in a §5.3 sentence. The
  three model-facing sites now use `err_text`, which drops the class for a
  written refusal and keeps it for a crash, where it is the useful part.

### Rendering the unrun messages found two defects in them

An unrun condition's messages have never been read by anything. Printing all
four — which `action_sizing.py` now does for every shape with a caller — found
that **the only reachable message was the defective one**:

- **It read as four instructions.** It ended `Send \`action\` as add-item,
  remove-item, set-checked, and repeat the other arguments.` — a list and an
  instruction fused into one clause, on the tool whose fault is precisely that
  two things were fused into one. On `table_edit` it ran to four values before
  the comma that meant something else. It now says `Valid: …` like the other
  three messages, then the instruction as its own sentence.
- **It could contradict itself.** It echoed the value the model *sent*
  (`"action": "add-row"`) and then listed the *calling tool's* valid values, so
  a cross-family fusion would have told the model to send a value the next line
  declared invalid. Latent, not observed — all five recorded messages fuse a
  value their own tool accepts — but reachable from any cross-family confusion,
  which is exactly what F-front's R2 was. The example is now echoed only when
  this tool would accept it.

Neither was findable without rendering the strings; both are §5.3 faults in
sentences that no test asserted the text of, because nothing had produced them.

### The replay-fidelity bug this turned up

Proving the flag inert meant snapshotting, and the snapshot with the flag **on**
moved seven keys, not five. The extra two were section calls, and they were an
artifact: `regrade_snapshot.py` replayed arguments that **fail to parse** as
`{}`, so it was hashing what `section-None` does to 26 corpus files — a vector
belonging to no real call — and those keys responded to any change in how a
missing field is handled.

They never reach `normalize` in a real trial. `armb.run_trial` calls
`json.loads` inside the same `try`, so the model is answered with the decode
error and no op runs. The snapshot now records `arguments-did-not-parse`
instead. Four keys move, all confirmed individually:

| key | bytes | parses | `action` in the text |
|---|---|---|---|
| `arma_sections.jsonl:7:0` | 31873 | no | n/a (Arm A's `new_string` tool) |
| `armb_s6_section_2call.jsonl:25:3` | 35783 | no | yes, `"replace-body"` |
| `armc_replay_path.jsonl:79:3` | 32199 | no | yes, `"insert"` |
| `s14_source_section_2call.jsonl:25:3` | 35783 | no | yes, `"replace-body"` |

Three of the four carry a valid `action` and were lost to the token budget
mid-string, 32–36 kB into a document written inside a tool call. Under the
check they would have been told `action` is required — wrong for the same
reason the original plan was wrong, and now unreachable.

### Grade-neutrality, both halves separately

| change | calls replayed | moved |
|---|---|---|
| the fidelity fix, flag off | 7294 | **4**, enumerated above |
| the check, flag on vs off | 7294 | **5**, the five fused keys |
| flag off, vs `c9f6fdf` before any of this | 7294 | **0** |

Re-run after the two message fixes and the `SCHEMES` derivation, over the
directory as it now stands:

| change | calls replayed | moved |
|---|---|---|
| the check, flag on vs off | 9455 | **21** |
| flag off, vs `5074736` before this pass | 9455 | **0** |

The 21 are the 21 fused keys and nothing else — six `armb_front_*` at line 38,
five `armb_lists` (lines 5, 25, 65, 405, 425), ten `armc_framing_lists` — which
is the same set `bench/action_sizing.py` reaches by a completely different
route. Two independent enumerations agreeing is the F-dupcol standard (`:2318`)
met rather than argued. The shipped default still moves nothing at all.

> **Correction (caveat 20).** This said the two routes agreed *"key for key"*,
> and they no longer report the same total: `action_sizing.py` now says **11**,
> not 21. Neither number moved by accident and neither is wrong — they answer
> different questions, and the 21 above is the right one for *this* table.
> `regrade_snapshot.py` asks "does any recorded call's behaviour move when the
> flag flips", so a replay's re-execution of a call is a recorded call and its
> behaviour does move; it reads `bench/results/` directly and should.
> `action_sizing.py` asks "how many calls did models actually produce", so it
> reads `bench/population.py` and drops replay rows. The difference is exactly
> the replay's copies: 21 − 11 = the ten `armc_framing_lists` enumerated above,
> which are the five `armb_lists` calls re-executed under two framings each
> (`add-item-tight-dash` 2→4, `add-item-loose` 2→4, `add-item-mixed-markers`
> 1→2). The six `armb_front_*` and five `armb_lists` are common to both, file
> for file. So the cross-check is stronger than when it was written: the two
> routes agree on the distinct calls *and* their difference is accounted for.
>
> The `9455` in the table is likewise an as-of figure, not a population claim —
> that directory only grows. What the row asserts is the paired comparison
> (flag on vs off, same snapshot both sides), which is unaffected by later rows
> landing.

`plugins/hermes/__init__.py` is **untouched**. Its comment — *"Rejecting it
here would replace a measured refusal with an unmeasured one"* — is still the
correct position, and is now better supported than when it was written.

### The design question, answered without code

The open item below has stood on a §5.3 complaint, not on a measurement: the
sentence a tool-armed model draws is
`unknown operation "table-None". Valid: table-add-row, … frontmatter-delete`,
and the model cannot act on any of it. The question that framing invites is
*does the core learn who called it, or does the front end rewrite what the core
said?* Both halves are refused by something already in the tree, and the third
answer is the one that has been sitting behind `CHECK_ACTION` all along.

**The defect is vocabulary, not count.** Narrowing fifteen names to the calling
family's three would not repair the sentence, because a model holding
`table_edit` has never been shown the string `table-add-row` anywhere. It was
given an `action` enum and speaks `add-row`. Every one of the fifteen names is
unreachable for it, including its own family's, and one of them —
`table-realign` — is unreachable for *every* tool caller, since no published
enum offers it. That last part is F-remedy's class: a refusal whose named
remedy no caller can perform. It is correct for Arm C, which is handed an op
name directly and could have meant any of the fifteen, and wrong for every model
holding a tool. `schematest.py`'s `refusal_backticks` cannot see any of it — the
names are unbackticked and the list is joined from `OPS` at runtime, so the lint
that exists for exactly this class is blind to the largest instance of it.

**The core cannot learn its caller.** `crates/incise-cli/src/main.rs` opens on
the contract that nothing is validated before `apply_op` sees it, and the
fifteen-name sentence is that contract's visible end — the core names what
exists because clap would otherwise say *"unrecognized subcommand"*. Adding a
caller identity would also add an axis to `difftest.py`, which compares two
executors byte for byte on the premise that they receive the same thing.

**The front end may not rewrite it.** §5.3 governs a refusal's text, and
`main.rs` states the consequence in its own words: *"a refusal, just a different
one"* is a regression. Catching the core's sentence and re-spelling it is that,
exactly.

**The third answer answers first.** `armb.normalize` refuses *before* the core
runs, in the caller's own vocabulary, which is what `_action_of` does behind
`CHECK_ACTION`. It is not a rewrite — the core's sentence is never produced —
and not a layering breach, because the front end knows which tool called for the
only reason that matters: it published the tool. `ACTIONS` is derived from the
schemes' own enums, so the names offered are the names offered. The design was
right when it was built. What has never been true is that it could be measured.

**`bench/headroom.py` now prices it, and the answer is no.**

| | |
|---|---|
| reachable trials over the five adopted schemes | **k = 1** of n = 2041 |
| the floor (`mcnemar_exact(b, 0) < 0.05`) | **6** |
| best achievable p, every discordant pair falling the same way | **1.0000** |

Fifteen further reachable trials exist under schemes that do not ship, and a
rate over them describes the schema they were run under. So the condition is
**UNDERPOWERED at any effect size** — not close, not pending a longer run.
`CHECK_ACTION` is an executor-side change, so that bounds the loss as well as
the gain: it is safe to leave off and it is also unprovable to turn on.

And unlike F-address's gap, this is not a task set to build. The fault is a
JSON-syntax collapse on particular seeds — F-frontread showed `add-build-cache`
t8 producing it deterministically across six pools, in two families — and no
instruction can ask a model to fuse two keys.

**What the sentence costs where it ships is, as far as this corpus can say,
nothing.** There are 21 recorded fused-key calls, which the survey's per-scheme
pairing collapses to 16 reachable trials. Graded, after F-terminal credited the
recovery: **16 of the 21 end in a correct document, 5 in `op_error`**. All five
failures are trial 5 of the list family, under `list_naive` and `list_i`,
neither of which ships. Every fused-key call under an adopted scheme recovered.

**Decision: `CHECK_ACTION` stays off, and the measurement half of the open item
closes as undecidable on this corpus rather than pending.** The reopening
condition is mechanical rather than remembered: `headroom.py` recomputes `k` on
every run, so a sixth family or a larger list pool that carries it past 6 will
say so by itself. That is why the finding is an entry in the survey and not a
number in a comment — F-action's own lesson about the figure that went stale by
two thousand calls.

Shipping `table-realign` (F-realign) would remove one of the two ways the
sentence misleads a tool caller, for free, by putting the name in an enum. The
vocabulary half would remain.

### Pricing it found the same fidelity bug twice

`headroom.py`'s `replay` had `regrade_snapshot.py`'s defect, in two places, and
this candidate is what exposed them — every earlier predicate matched a
*specific* refusal, and this one matches the sentence the artifacts wear:

- **Arm A's `patch` was being fed to `apply_op`**, yielding
  `unknown operation "patch"` 380 times and counting **260 Arm A trials** as
  reaching a branch no model in that arm can reach. Arm A is executed by
  `arma.py`. Calls now have to name a tool some scheme published.
- **Arguments that fail to parse were replayed as `{}`**, inventing a
  `section-None` — the identical mistake the snapshot made, corrected above for
  the identical reason. Two of this candidate's hits were `replace-body`
  payloads truncated by the token budget, which is not an `action` fault.

The first fix was written as *"has an `action` enum"* and silently deleted
`scheme_a`, whose three tools are one op each, turning B2's **CLOSED** verdict
into **UNTESTED**. Caught by diffing the whole survey rather than the new block:
the other four candidates' output is byte-identical before and after.

## F-read — the first read tool a model has ever been given, and the argument that doubles it

Every number in this file before now was produced by a model that was **handed
the table list for free**. `render_table_list` is injected as prompt context
(`armb.py:977-984`) and the system prompt says so outright: *"You do NOT have
the file contents, and you do not need them."* All 17 schemes offer writes only.
So `table-get` — shipped, differentially tested, 2724 difftest cases — had never
been reachable by a model, and §6.1's choice of the word `filter` over `where`
was an argument nobody had checked against a model.

### The result

Six read tasks, ten trials each, two schemes, paired on task and seed.

| scheme | the narrowing argument | correct | 95% CI |
|---|---|---|---|
| `table_read_naive` | `where`, described as on the write ops | 27/60 = **45.0%** | 33.1–57.5 |
| `table_read_g` | `filter`, described as *"narrows the rows"* | 58/60 = **96.7%** | 88.6–99.1 |

31 trials moved to correct, **0** moved the other way; McNemar exact
**p = 9.3e-10**. No trial in either arm lost a byte: a read writes nothing, and
`check_table_read_result` checks that before it checks anything else.

### It is the argument, not the answer

The two arms did not fail differently on the question. They failed at reaching
for the tool's second argument at all:

| | trials that narrowed |
|---|---|
| `table_read_naive` (`where`) | **7 / 60** |
| `table_read_g` (`filter`) | **40 / 60** |

The tuned arm's 40 are exactly the four tasks that need narrowing, all ten
trials each, and its 20 bare calls are exactly the two tasks that do not. It
never once filtered a table it should have read whole. The naive arm's 7 are all
on **one** task, `get-escaped-cell` — whose instruction hands over the column
and the value as a literal pair (*"the row whose Case is `escaped pipe`"*). On
the three `sortable.md` tasks, which require turning *"are priority high"* into a
column and a cell, it narrowed **0 times out of 30**. That reading of why is not
measured; the distribution is.

The naive arm's 27 correct answers are 20 filterless trials + 7 `where` calls.
**Every correct answer it gave on a filtering question came from the 7 times it
used the argument.** There is no third path: a model that does not narrow gets
the whole table back and answers from it.

### `unfiltered` — a deviation from the plan, and why

The plan specified one new outcome class. There are two, because pooling them
makes this table unreadable. `misreported` is *the document is intact and the
answer is false*. `unfiltered` is *the right table, nothing untrue, no
narrowing* — the model did the filtering in its own head. Those are the two
answers the `filter`-vs-`where` question has, and "asked about the wrong table"
and "did not narrow" need different remedies.

`unfiltered` is **not scored as correct**, and that is a judgement worth stating:
on a five-row fixture it is a working strategy, and on a five-hundred-row
document it is the exact failure `table-get` exists to prevent. All 33 of the
naive arm's failures are this class. Every one of them would have "answered the
question" to a human reading the transcript.

### The two failures in the tuned arm

Both are `get-filter-two-columns`, and both are the model adding a **third**
constraint the question did not ask for — `{"Name": "*"}` in one trial and a
value mangled by a quoting slip in the other. Neither is a incise fault: `*` is
a literal, correctly, and the filter matched nothing. It is a candidate for the
next tune (say that values match exactly, not as patterns) and it is recorded
here rather than fixed, because a schema edit that has not been re-measured is
the thing S15 and F-action both warn about.

### Grading a read at all

A read's failure mode is a **false report, not a damaged document**, and
`destructive`/`collateral:*` are about bytes on disk. The new predicate grades
the structured rows `table_get` returns — heading, columns, `matched`, `total`,
rows — and **never the rendered string**. A grader that matched
`render_table_get`'s output would be a golden for the renderer, and the renderer
is not what is under test. `armb.read_call` returns both forms for the same
reason: a renderer change cannot move a grade, and a grader change cannot move
what the model saw.

`table_get` stays out of `OPS`. Every entry there takes a document and returns a
document or a refusal; this returns text *about* a document. Adding it to reach a
model's hands would also move the `unknown operation "..." Valid: ...` sentence,
which is measured data — F-dupcol is the precedent for what proving that
harmless costs. Reads route through `armb.READS`, keyed on tool name.

### The two harness gaps this closed, and the one it did not

1. **`difftest.py` could not send a typed `filter` value.** The wire format is
   flat text, so `check_cell`'s refusals on a boolean, a null, an array or an
   object *inside* a filter were reached by nothing. `table_get` now rides the
   same JSON escape hatch `apply_op` and `check_args` already use. 84267 →
   **86229** cases; `table_get` 2724 cases, 1882 of them refusals. **No
   divergence was found** — the port already answers typed filter values
   identically. That is the honest result and it is worth recording as one:
   the gap was in the evidence, not in the code.
2. **`filter-value-typed` was absent from `mutate.py` because it was
   unreachable** — *"a mutation known in advance to be unreachable measures the
   harness, not the code."* It is now in, and it was proven reachable by
   experiment rather than by argument: with the new cases it catches **530**
   mismatches, and with the new cases disabled it **SURVIVES**. The first draft
   of the mutation did not do that (it coerced every filter value and was caught
   by 207 cases without them, because `py_repr` quotes a string and ordinary
   filters then stop matching) — so it was measuring the string path, and the
   comment claiming otherwise was false until the mutation was narrowed to the
   non-`Str` arms. `mutate.py` 180 → **181**, all caught, no survivors.
3. **Arm C still cannot run a read, and now says so for the right reason.**
   `_check_turns` refused `--turns > 1` for tables and lists because the CLI
   returns `describe_change` where `armb.tool_result` returns a renderer
   summary. That is an **edit-only** divergence: a read's tool result is
   `render_table_get`'s string in both arms, verified byte-identical against
   `incise rows --json` on four corpus tables. The guard is now two guards, and
   the read one names what is actually true — `execute` runs `incise <op>` and a
   read is `incise rows` with its own flag set, and `rows --json` returns the
   rendered text where the grader wants the rows. Both are buildable; neither is
   built, and the plan did not budget them. Arm B measures the read tasks.

The tasks live in **`bench/tasks/tables_read.json`**, not in `tables.json` —
also a deviation. A read task carries five expectation fields no edit task has,
and `--tasks` selects a file, so the split is what lets the read schemes be run
without also re-running the edit tasks. No instruction in it is answerable from
the injected table summary, which is the only way to find out whether a model
reaches for the tool or asks for the file.

Ceiling 12/12 on both read schemes before any GPU time. `regrade_snapshot.py`
against `b580fed`: 7294 calls, **0 moved**.

## F-frontmatter — the fourth family, and the verb that deleted the version

The family whose specification is a corpus file rather than a requirement.
`corpus/frontmatter/rich.md:37-43` names five things that must be byte-identical
after `frontmatter-set build.jobs 8` — key order, the leading comment, the inline
comment on `build.target`, two block scalar styles, and the quoting of
`quoted_key` — and says outright that *"most YAML libraries destroy at least
three of those on a load/dump round trip. This file is the test that incise does
not."* Nothing in `mdfront.py` loads a value into a Python object and writes it
back: every entry records the byte pieces of its own line (prefix, key text,
gap, value, pad, comment) and an edit rewrites one piece. Lines no edit names
are never touched, which is why comments and blank lines survive without any
code that knows they exist.

### The result, and why the headline p-value does not survive inspection

Eleven tasks, ten trials each, two schemes, paired on task and seed. Naive
first, per PLAN §12 — the order that stopped the list family adopting prose
worth −19 points.

| scheme | the `key` description | correct | 95% CI |
|---|---|---|---|
| `front_naive` | *"Which frontmatter key to edit."* | 87/110 = **79.1%** | 70.6–85.6 |
| `front_p` | names the dotted path, says to copy it from the summary, gives `authors[0].role` | 94/110 = **85.5%** | 77.7–90.8 |

7 trials moved to correct, **0** moved the other way; McNemar exact p = 0.0156.

> **Correction (F-terminal).** Re-graded: `front_naive` **88/110 = 80.0%**,
> `front_p` **95/110 = 86.4%**. The pair test is **unchanged — still 7–0,
> p = 0.0156** — because the one trial that moved is `add-build-cache` trial 8
> in *both* schemes: that seed fuses `action` into the next key regardless of
> how `key` is described, so it was concordant before and is concordant after.
> The same +1/+1 applies to the v2 re-run quoted below, which is why its
> "reproduced exactly" claim survives the regrade intact.

**That p-value should not be quoted.** 4 of the 7 come from `set-dana-role`, and
`set-dana-role` is not answerable from what the model is shown. The task says
*"Dana has taken over as a maintainer"* and the mapping from `Dana` to index 1
lives in the document — but `render_frontmatter` omits scalar values on purpose,
because Arm B's premise is that the model addresses an edit it cannot see. The
injected summary lists `authors[0].name` and `authors[1].name` and never says
which is Dana. There is no read tool in either scheme. The model is guessing,
and the two arms guessed in mirror image:

| | `authors[1]` (right) | `authors[0]` (wrong) |
|---|---|---|
| `front_naive` | 3 | 7 |
| `front_p` | 7 | 3 |

Drop that one task and the arm reads:

| | correct | moved to correct | moved away | McNemar |
|---|---|---|---|---|
| all 11 tasks | 79.1% → 85.5% | 7 | 0 | p = 0.0156 |
| without `set-dana-role` | 84.0% → 87.0% | 3 | 0 | **p = 0.25** |

So the defensible claims are narrower than the headline: the tuned `key`
description **never made a trial worse**, and its only unambiguous gain is
`set-draft-true` (7/10 → 10/10, where `front_naive` invented a `status` key
three times). This arm does not establish the tuned schema as better at p < 0.05.
`set-dana-role` needs rebuilding before it measures anything — either the
summary has to carry something that distinguishes the two authors, or the task
has to stop depending on a value the model cannot see — and rebuilding it after
seeing this result and re-running is a separate, named change, not part of this
commit.

### Where the rest of the difference is, and is not

**Bracket addressing was never the problem.** `set-dana-role` is the only task
needing an index, and in both arms the model produced syntactically valid
`authors[N].role` on 10/10 trials. The index syntax cost nothing to teach; only
the index *choice* failed, and that failed for lack of information rather than
for lack of a schema.

**The two `wrong` trials on `add-build-cache` are the same shape in both arms:**
the model invented `build.caching` rather than `build.cache`. Nothing in the
instruction ("Turn on caching for the build") supplies the key name, so this is
the family's version of the naming question the section family met at S15, and
it is not something a tool description can fix.

### `release-bump`: 10/10 destructive, in both arms, on one word

Every trial in both schemes emitted exactly this pair:

    frontmatter_edit {"action":"delete","key":"version"}
    frontmatter_edit {"action":"set","key":"release_date","value":"2026-09-12"}

The instruction was *"Cut version 0.5.0, and record 2026-09-12 as the release
date."* **"Cut a release" is release-engineering idiom for making one**; next to
an `action` enum containing `delete`, the model read "cut" as the verb it names.
It never wrote `0.5.0` anywhere.

This is recorded, not fixed, and the distinction matters. The answer key is
correct and the golden reassembles; what is ambiguous is the *instruction*, and
the ambiguity is identical in both arms, so it is a constant in the paired
comparison and does not touch the p-value. Rewriting the instruction after
seeing the result and re-running would be re-baselining a task on its own
outcome. **The honest statement is that `release-bump` currently measures a
verb collision rather than the two-call edit it was written for**, and the
9.1% data-loss figure in both arms is one task, ten times.

It is also the sharpest available evidence for something §6.3 has only argued:
an instruction verb that collides with a destructive `action` name is a route to
data loss that no argument-level guard can see, because every argument in that
call is well-formed and the op did exactly what it was told.

### Decisions taken here, so they are not discovered later

1. **Bracket indices extend the promised contract.** `REQUIREMENTS.md:405`
   promises dotted paths only; `rich.md:50` names `authors[0].role` as one of
   its own cases. `mdfront.parse_path` supports both, deliberately, and the two
   documents should be reconciled — the requirement is the one that is behind.
2. **`describe_change` was left alone, and the family got its own.** The first
   draft folded frontmatter notes into `describe_change`. That function is
   `difftest.py`'s oracle for the Rust one, and the Rust has no frontmatter
   parser, so teaching the oracle a sentence the port cannot say turned 6 of
   3440 differential cases into a recorded divergence. They are now
   `describe_frontmatter_change`, a bench-side function beside
   `render_frontmatter` and `frontmatter_get` — the family's other two
   Python-only surfaces — and `armb.tool_result` calls it for this family only.
   `render_frontmatter` omits scalar values on purpose, so without it a
   `frontmatter-set` produces a byte-identical summary and the tool result
   cannot testify that anything happened.
3. **TOML is refused with a conjugated verb.** `_front(verb=…)` used to append
   an `s`, which wrote *"incise delete froms YAML"*. A refusal is the product
   (§5.3); the parameter now carries the conjugated form.
4. **The grading ladder borrows the section family's golden and the list
   family's order.** The golden is the minimal changed window, as for sections.
   The *ladder* tests outside-the-window first, as for lists, because a
   frontmatter op provably cannot touch a byte below the closing delimiter — so
   a changed body means the trial edited some other construct. Sections
   deliberately do not, because a section op legitimately rewrites arbitrary
   amounts of a file. The last rung is the one the family exists for: every key
   right and the bytes still differ is `collateral:content`, not
   `collateral:formatting`, because a YAML round trip that keeps every key and
   drops every comment passes every structural check.

### Verification, with the two deltas enumerated

Ceiling **22/22** on both schemes before any GPU time.

- `test_incise_ops.py`: five new frontmatter invariants. Set-then-delete is
  byte-identical over all **5** editable blocks; every one of **41** settable
  keys moves its own line and no other and leaves key order unchanged; **20**
  keys refuse — 19 containers, plus `"dotted.key"` in `front-shapes.md`, a
  scalar whose quoted name contains the path separator and which therefore no
  path can reach; absent/empty/present and null/empty-string stay
  distinct; TOML is refused by set, delete, get and the renderer while sections
  in the same file keep working.
- `difftest.py`: **86229 → 88049**, and the whole delta is the three new
  fixtures. Removing `bench/synthetic/front-{shapes,crlf,edges}.md` and
  re-running gives 86229 over 44 fixtures exactly, so the **1820** new cases are
  the three files and nothing else. `difftest.py` itself is unmodified. All
  88049 agree.
- `mutate.py`: **181/181 caught, no survivors.** Unchanged, as planned — this
  workstream adds no Rust surface.
- `regrade_snapshot.py` against `d65047f`: **504 of 7414 calls moved**, and
  every one was enumerated rather than argued from the shape of the change,
  following F-dupcol. All 504 are unknown-operation refusals — `patch` ×379,
  `table_get` ×120, `list-None` ×5 — and in each, on each of the 26 corpus
  files, the before string begins `unknown operation` and the after string is
  that string plus exactly `, frontmatter-set, frontmatter-delete`. Checked
  element by element: 0 exceptions. A refusal writes no document, so no grade
  can move, and no recorded call in any results file names a frontmatter op, so
  nothing went from refused to applied.

*Both of the rebuilds this section calls for were done, and both of the tasks
turned out to be wrong in ways it had not seen: F-frontread, immediately below.
It re-ran `front_naive` and `front_p` first, and reproduced 87/110 and 94/110
exactly on the ten tasks it did not touch, so the numbers above stand.*


## F-frontread — the read tool the family already had, and two broken tasks

F-frontmatter ended with a result it could not defend and two named reasons.
This closes both, and the honest summary is that **one of the two reasons was a
measurement bug and the other was two measurement bugs stacked**.

The premise that makes this worth reading: every number below was produced with
the **naive scheme re-run first**, and the re-run of `front_naive` and `front_p`
reproduced F-frontmatter's totals **exactly** — 87/110 and 94/110, identical
task by task on all ten tasks whose instruction did not change. That is the
`clap` rule (`armb.py:1215-1217`) applied to a whole arm: if the control does
not reproduce, nothing else in the table means anything. It reproduced.
*(F-terminal re-graded both pools to 88/110 and 95/110, moving the same trial
in each of the four pools involved; the reproduction is still exact, at the new
number.)*

### `set-dana-role` was not a broken task. The schemes were incomplete.

The task asks which of two authors is Dana. `render_frontmatter` omits scalar
values by design — Arm B's premise is that the model addresses an edit it cannot
see — so the summary lists `authors[0].name` and `authors[1].name` and no more.
F-frontmatter recorded the consequence (3/10 and 7/10 in mirror image) and
proposed either enriching the summary or changing the task.

Both proposals were wrong, and the third option was sitting in the tree. **The
family has had a read op since the day it was built** — `frontmatter_get`, off
`apply_op`, on `table-get`'s pattern — and **no frontmatter scheme published
it**. That is verbatim the defect 3b opened with for tables (*"No scheme has
ever offered a model a read tool"*), reappearing in the family built
immediately after, which is the argument for why it is worth its own finding
rather than a line in the previous one.

`front_r` is `front_p` plus `frontmatter_get`, asserted byte-identical in the
edit tool so the pair isolates one variable, with the system prompt's
load-bearing sentence inverted the way `table_read` inverts it. It needed one
new bench-side surface, `render_frontmatter_get`: `frontmatter_get` returns
structure, and `render_frontmatter` is the *value-less* summary, so without a
renderer of its own a read would have answered with the thing the model already
had.

### The result

Eleven tasks, ten trials, three schemes, paired on task and seed, four turns
each. Naive first.

| scheme | correct | 95% CI |
|---|---|---|
| `front_naive` | 97/110 = **88.2%** | 80.8–93.0 |
| `front_p` | 104/110 = **94.5%** | 88.6–97.5 |
| `front_r` | 106/110 = **96.4%** | 91.0–98.6 |

| comparison | moved to correct | away | p |
|---|---|---|---|
| `front_naive` → `front_p` | 7 | 0 | **0.0156** |
| `front_p` → `front_r` | 4 | 2 | 0.6875 |
| `front_naive` → `front_r` | 11 | 2 | **0.0225** |

> **Correction (F-terminal), and the headline is untouched.** Re-graded with the
> `unknown operation` branch removed: `front_naive` **98/110 = 89.1%**,
> `front_p` **105/110 = 95.5%**, `front_r` 106/110 unchanged. `front_naive` →
> `front_p` is **still 7–0, p = 0.0156** — both pools gained the same trial, so
> the comparison this finding turns on is byte-identical. `front_naive` →
> `front_r` becomes 10–2, p = 0.0386 (still significant); `front_p` →
> `front_r` becomes 3–2, p = 1 (still nothing). The caveat below on the
> headline's 7 wins applies unchanged, because the 7 are the same 7.

**The read tool is not a general improvement, and the table above is the wrong
place to look for what it did.** `front_p` → `front_r` is p = 0.6875. Ten of
the eleven tasks do not need a read, and on those the tool is at best inert.

### What it did do, which is the finding

The read tool was called in **10 of 110 trials. All ten were `set-dana-role`.
Zero of the other hundred.**

| task | reads | correct |
|---|---|---|
| `set-dana-role` | 10/10 | 10/10 |
| the other ten tasks | 0/100 | 96/100 |

On `set-dana-role` the score goes **3/10 → 7/10 → 10/10**, and the mechanism is
in the transcripts rather than inferred: all ten trials read first (seven with
`key: "authors"`, three with no key at all — which is why `key` is optional on
the read tool and required on the edit tool), and all ten then addressed
`authors[1].role`. Not one addressed `authors[0]`, the off-by-one that would
have made Peter a second maintainer.

That perfect discrimination is the result worth keeping, and it cuts directly
against the standing worry. S14 measured what an unnecessary extra call costs:
a further call after a call that had already succeeded was **32× more likely to
destroy the document**, and the whole `delta` result shape exists to suppress
it. Handing the model a *second tool* is the obvious way to reawaken that, and
the system prompt was written to say *when* to read rather than to read first,
precisely so this would be a measurement and not an instruction. The model read
on the one task whose instruction depends on a value it could not see, and never
otherwise. **0/100 spurious reads.**

The two trials `front_r` lost are both `add-build-cache`, which uses no read
tool in any scheme; see below.

### `release-bump` was wrong twice, and the first bug hid the second

F-frontmatter reported the first: the instruction opened *"Cut version 0.5.0"*
and 10/10 trials in **both** arms read `Cut` as `action=delete` on `version`.
Release-engineering idiom colliding with an `action` enum. It stands as the
clearest evidence in the project that an instruction verb colliding with a
destructive action name is a data-loss route **no argument-level guard can
see** — every argument in that call is well-formed, every check F-args added
passes, and the document loses its version key.

`Cut` → `Update` fixed exactly that, and the size of it is worth stating
plainly: **20 destroyed documents became 0.**

It also exposed a second defect the first had been masking. With the verb fixed,
the task still scored **0/30** — and the transcripts showed all thirty trials
making both calls, writing both values bare (`0.5.0` unquoted, the date
unquoted: the trap the task was actually built for), and naming the new key
`release_date`. Unanimously. The expectation demanded `released`, and the
instruction — *"record 2026-09-12 as the release date"* — named neither.

The task's own note had been asserting the contradiction all along: *"the key it
becomes is the model's choice"*, beside a `keys_present` that pinned `released`
and a golden that pinned its line. Both cannot be true. **The expectation is the
half with teeth, so the instruction now names the key**, and loosening the
expectation was rejected for a reason specific to this family: the
whole-document golden is its entire point, and a task that accepts two different
documents cannot pin the bytes `rich.md:37-43` exists to protect.

With the key named, `release-bump` is **10/10 in all three schemes**.

Three versions of one task, all three kept on disk:

| | instruction | outcome |
|---|---|---|
| v1 | *"Cut version 0.5.0, and record…"* | 20/20 **destructive** |
| v2 | *"Update the version to 0.5.0, and record…"* | 30/30 `wrong`, 30/30 chose `release_date` |
| v3 | *"Update the version to 0.5.0, and set `released` to…"* | 30/30 **correct** |

### The defensible claims, and the one that is still not

Stated as narrowly as the data supports:

1. **The read tool closes `set-dana-role` completely**, 3/10 → 10/10, by a
   mechanism visible in every transcript. It is **not** shown to help anywhere
   else, and `front_p` → `front_r` overall is p = 0.6875.
2. **A model given a read tool beside a write tool used it exactly when the
   instruction required it**, 10/10 and 0/100. This is the S14 worry not
   materialising, measured rather than assumed.
3. **One word of instruction was worth 20 destroyed documents**, and no
   argument-level guard could have caught it.
4. **The tuned `key` description is still not established at p < 0.05.** With
   `set-dana-role` excluded — the task neither edit-only scheme can answer
   except by guessing — `front_naive` → `front_p` is **+3 −0, p = 0.25**,
   exactly as F-frontmatter reported. Repairing the task set did not rescue it,
   and it should not be reported as a win. Its unambiguous gain remains
   `set-draft-true` (7/10 → 10/10), and it has still **never made a trial
   worse** across 220 paired trials in two independent runs.

### Two things found on the way, reported rather than fixed

- **`add-build-cache` has `release-bump` v2's defect, in a milder form.** *"Turn
  on caching for the build"* names no key; across the 30 v3 trials the model
  wrote `build.cache` 22 times and `build.caching` 8. Unlike `release-bump`,
  where the instruction unanimously determined a key the expectation did not
  expect, this one is genuinely underdetermined and mostly resolves the expected
  way — so it is a real if small signal rather than a broken instrument, and it
  is **not** being fixed and re-run. Two rounds of fix-and-re-run on one task
  set is the limit at which repair stops being repair; a third would be tuning
  the tasks until the number is agreeable.
- **The fused-key JSON failure is not a list-family quirk.** F-action records
  `list-None` calls that were really `{"action=add-item,item": ...}` — one
  malformed key instead of two — and treated them as a single seed's accident.
  The same failure appears here on `frontmatter_edit`:
  `{"action=set,key": "build.cache", ...}`, on `add-build-cache` t8, in
  `front_naive` **and** `front_p`, in the base run **and** both the v2 and v3
  re-runs — **six** occurrences, not the four first counted here, which missed
  the base files; `bench/action_sizing.py` enumerates them. Same seed, two
  families, deterministic. It is a seed-correlated generation failure that
  reproduces across families, which is a better description than "one seed" and
  narrows what a front-end `action` check could possibly buy: in none of these
  cases is `action` missing, it is fused.

### Verification

- `test_incise_ops.py`: **all invariants hold**, with 28 new checks in
  `test_frontmatter_read` and `test_frontmatter_read_scheme` — the read supplies
  the author names the summary withholds, every scalar renders as stored with
  its quoting intact, a block scalar's body is shown rather than its `|`, the
  read leaves the document alone, and `front_r` differs from `front_p` by
  exactly one tool.
- **`test_tasks_are_regenerable` is new, and it caught a live drift.** Nothing
  had ever compared the three generated task files to their generators.
  `frontmatter.json` had been committed at `9fe7bbc` from a script that no
  longer existed: a late fix to `delete-draft`'s note was never regenerated. The
  drift was in a note and moved nothing — which is exactly why it is worth a
  test, since the next one lands in a `golden`.
- `schematest.py`: **3 tools, byte-identical.** `front_r` is unpublished.
- `difftest.py`: **88049/88049**, unchanged. No core surface moved;
  `render_frontmatter_get` is bench-side, like `render_frontmatter` before it.
- `regrade_snapshot.py` against `9fe7bbc`: **7658 calls replayed, 0 moved.**
  Unlike 3a this workstream adds no `OPS` entry, so the `unknown operation`
  sentence does not move and the snapshot is identical rather than enumerated.
- `ceiling.py`: **33/33** on all three schemes, before any GPU time.


## F-framing — the plugin's two divergences, sized before they were run

`plugins/hermes/README.md:134-152` records two places where the plugin is not
the thing the numbers describe: refusals reach the model as `{"error": "…"}`
rather than `"Error: " + …`, and a refusal over 2048 characters is truncated by
the host. F-path built the axis to measure them (`armc.replay --framings`) and
did not run it. Running it started with reading the code and the population,
and **that alone changed what there is to measure.**

### The `cap` condition was measuring a program nobody runs

Three defects in the unrun code, all found before any GPU time:

1. **The cut was in the wrong place and said nothing.** `frame("cap", err)` was
   `("Error: " + err)[:2048]`. The host's `_bound_error_text` caps the
   *message* — before the JSON encoding, with no prefix in front of it — and
   appends `"… [truncated]"`. The old form cut seven characters early and gave
   the model no sign that anything had been cut, which is a strictly harsher
   condition than the host's and not one anybody ships.
2. **`cap` was offered as an alternative to `json`, and the host composes
   them.** `tool_error` bounds the body and *then* encodes it, so a truncated
   bare string does not exist anywhere. `cap` is `json` plus the bound.
3. `json` omitted `ensure_ascii=False`, which `tool_error` passes. This one
   changes nothing here — none of the recorded refusals contains a
   non-ASCII character — and is fixed anyway, because a condition that exists
   to state what a host does is worth running only while it is accurate.

`armc.bound` is now the host's function transcribed, and `test_framings` asserts
the transcription **against the real `tools.registry`** when hermes-agent is
installed: `frame("cap", err) == tool_error(err)`, byte for byte, on the corpus
refusal this exists for.

### The cap fires on 1 refusal in 353

`bench/results/` holds 1727 first tool calls that the release binary answers
with exit 1, and **1374 of them are not refusals anybody was shown.** They are
the harness pointed at the wrong executor:

| op | n | why the binary does not know it |
| --- | --- | --- |
| `patch` | 380 | Arm A's tool — the string-replacement baseline |
| `frontmatter-set` / `-delete` | 854 | `incise_ops.py` implements these; the Rust port is open |
| `table_get`, `frontmatter_get` | 140 | reads, off `apply_op` by design |

All 1374 answer `unknown operation "X"`. The rule that separates them is not a
file-name blocklist: **an unknown-operation result is an artifact exactly when
the executor that produced the row implemented the op and the release binary
does not.** That distinction earns its keep immediately — `unknown operation
"list-None"` (5 rows) and `"frontmatter-None"` (6) are implemented by *nobody*,
so they are genuine refusals real models read, and they are the only rows in the
project that measure the missing-`action` failure. A blocklist would have
deleted them.

The real population is **353 refusals** — tables 61, lists 112, sections 174,
frontmatter 6 — from **61 distinct strings**. Crossing the 2048-character cap:
**one**, at 2057 characters, **9 over** (`armb_lists.jsonl`,
`add-item-mixed-markers`). `bench/refusal_pool.py` is the count, so the figure
is regenerable rather than quoted.

> **As of S16 the command says 360**, not 353 — tables 61, lists 112, sections
> **181**, frontmatter 6, still 1 over the cap and still 9 characters over. The
> seven are S16's own trials, which landed after this was written: the directory
> grows, so a census of it is dated the day it is run. Every conclusion below
> was computed on the 353 that existed then and none of them turns on the seven.
> Read `353` here as the denominator of *this* experiment, not as a current
> census. (The command was also briefly wrong in the other direction — see
> F-unique, where it reported 525, because its replay exclusion was a file-name
> prefix and the next two replays were named something else.)

So the `cap` condition cannot be sized. A framing arm with n = 1 and a
9-character delta is not an experiment, and on the other 352 prefixes
`frame("cap", …)` and `frame("json", …)` are byte-identical — asserted in
`test_framings` rather than argued. **The plugin's two documented divergences
are, on every distribution this project has measured, one divergence.**

The refusal the cap exists for is real: `table-add-row` against an unmatched
`table` on `corpus/documents/api-reference.md` is 2200 characters and loses 152.
The README's numbers are exactly right. What it loses is worth stating precisely,
because `armc.py`'s own comment had it wrong — it claimed the tail is "where
§5.3 puts the repair line." It is not. The message is three lines:

```
no table under heading "zzz".
  Near matches: none
  Headings with tables: API reference > Accounts, … (49 of them)
```

§5.3's repair line is `Near matches:`, which is line 1 and survives whole. The
cap takes four entries off the end of a list whose opening still reads as
exhaustive — a quieter failure than losing the advice, and a different one.

### What the JSON framing actually does

Not "the framing moves." Two specific transformations, measured across the 353:

| | of 353 real refusals |
| --- | --- |
| multi-line, so `\n` becomes a two-character escape and the message arrives as **one line** | **286 (81.0%)** |
| contains a quoted identifier, backslash-escaped | **246 (69.7%)** |
| both | 235 (66.6%) |
| unchanged but for the wrapper | 56 (15.9%) |

```
plain:  Error: no section "Setup" with ordinal 0.
          Valid ordinals: 0, 1

json:   {"error": "no section \"Setup\" with ordinal 0.\n  Valid ordinals: 0, 1"}
```

§5.3 is a specification of a *shape* — statement, then `\n  ` continuations —
and every recovery rate in it (B3's 100% one-turn on tables, S12's 75% on
sections) was measured on the top form. The plugin ships the bottom form. That
is a sharper hypothesis than the README's "only the framing moves", and it
predicts a direction.

### Pre-registered, before the run

Written here before any trial was graded, and committed before the results
existed, so the record is checkable rather than asserted:

> **Primary endpoint:** graded `correct` under `json` versus `plain`, paired per
> prefix. **Prediction:** `json` ≤ `plain` — the escaping destroys §5.3's shape
> on 39.4% of refusals and mangles the identifier on 85.3% — but the effect is
> small and most likely **not** significant at this n. **Secondary:** whether
> the next call repeats the same mistake.
>
> The reason to expect small: F-path already found that on this failure class
> *"an error message is advice, and the model is not failing to take advice"* —
> the family moved recovery by seventy points and the wording by five. A framing
> change is a weaker intervention than a wording change, and the wording change
> bought nothing.

The two percentages inside that block are **quoted as pre-registered and are
wrong** — they were computed over a 726-row count that was both padded with
harness artifacts and, as it turned out, an incomplete scan. The block is left
byte-identical because a pre-registration that gets edited after the results
arrive is not a pre-registration. The
corrected figures are 81.0% and 69.7%, above; both are *larger*, so the
prediction's reasoning — "the escaping destroys §5.3's shape on most refusals"
— is if anything better supported than when it was written. The predicted
direction, and the expectation that it would not reach significance, do not
depend on either number.

### The result

202 prefixes whose first call was refused — 77 lists, 64 sections, 61 tables —
replayed under both framings at four turns, held fixed in every other byte. 404
trials, paired by construction, so McNemar.

| | n | `plain` | `json` |
| --- | --- | --- | --- |
| lists, graded `correct` | 77 | **61 (79.2%)** | 60 (77.9%) |
| sections, graded `correct` | 64 | **49 (76.6%)** | 46 (71.9%) |
| tables, graded `correct` | 61 | 40 (65.6%) | **43 (70.5%)** |
| **pooled, graded `correct`** | 202 | **150 (74.3%)** | 149 (73.8%) |
| lists, recovered in **one turn** | 77 | **46 (59.7%)** | 40 (51.9%) |
| sections, recovered in **one turn** | 64 | **51 (79.7%)** | 46 (71.9%) |
| tables, recovered in **one turn** | 61 | 36 (59.0%) | 36 (59.0%) |
| **pooled, recovered in one turn** | 202 | **133 (65.8%)** | 122 (60.4%) |

> **The two `correct` rows for lists have moved since, and with them the pooled
> row and the primary endpoint below.** F-terminal removed a grading convention
> that ended a trial on `unknown operation` where every other refusal class is
> allowed to recover; 10 of these 404 trials were subject to it, all in lists.
> Re-graded: lists **plain 66 (85.7%) / json 63 (81.8%)**, pooled **plain 155
> (76.7%) / json 152 (75.2%)**, primary endpoint **20–17, p = 0.743**. The
> one-turn rows do not move — those trials already counted as not recovering in
> one turn — and neither does any sections or tables cell. The table is left as
> measured and the correction stated beside it, because the conclusion drawn
> from it does not change: the primary endpoint was flat at 18–17 and is flat at
> 20–17. `bench/framing_report.py` prints the current figures from the graded
> pools.

| endpoint | plain-only | json-only | p |
| --- | --- | --- | --- |
| graded `correct` (primary) | 18 | 17 | 1.00 |
| recovered in one turn (secondary) | 28 | 17 | 0.135 |

**Read the order these were run in, because it changes what the numbers mean.**
Lists and sections were run first, as planned — 141 prefixes, primary 13–9
(p = 0.52), secondary 22–11 (**p = 0.080**). Tables was added *afterwards,
because of that 0.080*, to settle it. That is a decision made after seeing the
result, so the two-family p-value is not a number this document may quote as a
finding, and the three-family pool is the one that counts.

Tables did not settle it in the direction the extension was hoping for. It is a
clean null on both endpoints: the primary runs the *other* way (40 plain against
43 json, 5–8), the secondary is dead level at 36–36, 6–6, p = 1.00, and mean
calls per trial are 2.56 against 2.57. Pooled, the one-turn signal weakens
rather than sharpens — 22–11 at p = 0.080 becomes 28–17 at **p = 0.135**.

So the honest summary is narrower than the two-family run suggested:

- **The primary endpoint is flat, and now flat on three families.** 18–17,
  p = 1.00, rates 74.3% against 73.8%. At four turns the framings are
  indistinguishable, and this is the best-supported claim here. *(20–17,
  p = 0.743, rates 76.7% against 75.2% after F-terminal's regrade. Still flat,
  and the claim is unchanged.)*
- **The one-turn signal is real in lists and sections and absent in tables.**
  Lists 11–5, sections 11–6, tables 6–6. Two families leaning one way and a
  third sitting exactly on zero is what a small effect looks like, and it is
  also what noise looks like. **At n = 202 this cannot be told apart from
  chance**, and adding the third family moved it away from significance, which
  is the outcome that should update the reader most.

What survives: the plugin's framing is **not shown to cost an outcome**, and the
suggestion that it costs a first repair attempt is **weaker than it looked at
141 prefixes** and should not be quoted as a cost.

One thing the tables column raises that this replay cannot answer. §5.3
publishes **100% one-turn recovery** for tables (B3); the `plain` column here is
**59.0%**. Those are not the same population — every prefix here was *selected*
for having been refused on its first call, which conditions on the hard cases,
and B3's rate is over its whole run. But the gap is large enough that "what
one-turn recovery rate does a refused tables prefix actually have" is now an
open question rather than a settled one, and §5.3's number should not be read as
answering it. The sections `plain` column, **79.7%** against S12's 75%, is the
one place the two line up.

### Answered: the tables gap is one stratum, and the stratum is an artifact

> **Corrected.** The first version of this section, committed in `bddc7af`,
> read the stratum below as models obeying a refusal that gave them bad advice,
> and published a cost for it. The stratification is right and the bad advice is
> real, but the cost is not: those 38 prefixes were **not refused in the arm at
> all**. The measurement that found it is below, and it changes the answer from
> "tables recover at 34%" to "tables recover at 100%."

Stratifying the same prefixes by the refusal the model actually read — no new
trials, `python3 bench/framing_report.py` — the selection story is wrong. The
tables family is not uniformly worse. It is perfect everywhere but one message:

| tables refusal, `plain` framing | one-turn recovery | |
| --- | --- | --- |
| `a row is required: either \`values\` … or \`row\` as an ordered array.` | 13/38 = 34.2% | ← **not a recovery rate; see below** |
| `table address required: this file has 2 tables.` | 8/8 = 100% | |
| `no row matches all of {…}` (four variants) | **13/13 = 100%** | |
| `a \`where\` selector is required to identify the row.` | 1/1 = 100% | |
| `\`values\` arrived as a string, but must be an object or an array.` | 1/1 = 100% | |

Two things fall out. **B3 replicates exactly**: its 13/13 was the `no row
matches all of {…}` message, and that message is 13/13 here too, in a different
run over a different pool. §5.3's 100% was never wrong — it was never a claim
about the family, and the pooled 59.0% is a property of the *mix*, not of
tables. **And the remaining message is 62% of the pool**, which is the whole
gap.

That much stands, and the rest of this section is about the 38.

#### The 38 were never refused in the arm

Replay each prefix's first call through **the oracle** — Arm B's own executor,
the one that produced the trial the prefix was taken from — and ask whether it
was actually an error:

| family | prefixes | first call the **oracle accepts** | genuinely refused |
| --- | --- | --- | --- |
| lists | 77 | 0 | 77 |
| sections | 64 | 0 | 64 |
| **tables** | **61** | **38** | **23** |

All 38 are the `a row is required` stratum, exactly — every prefix in every
other tables stratum is refused by the oracle too. The partition the table
above found by refusal sentence and the partition by "did this call actually
fail" are **the same partition**.

So the 38 are not models that failed and then failed to recover. They are
models whose first call **worked**, replayed in front of a binary that could
not run it. Five facts, each measured, together leaving no other reading:

- **All 38 first calls are accepted by the oracle**, row added.
- **All 38 are `scheme_d`** — 38 of the 39 `scheme_d` prefixes in the pool.
- **`scheme_d` is the only scheme in the project that declares `row`**, and it
  declares it as *"The row's values in column order, one per column, all columns
  required."* The models were using their tool correctly.
- **All 38 sent `row` on their first call**, before reading any message:
  argument keys `('action','path','position','row','table')` ×31 and
  `('action','path','row','table')` ×7. The published claim that "31 of 38 take
  the advice" mistook persistence with their own schema for obedience to the
  refusal — they had sent it before the refusal existed.
- Census-wide, **all 41 `row`-as-array calls are `scheme_d`**, and **no recorded
  table call in the project has ever drawn `a row is required` from the oracle**
  (480 table calls replayed). Models follow the schema, not the message.

**Corrected answer to the open question.** A genuinely refused tables prefix
recovers in one turn **23/23 = 100%** — replicating §5.3's B3 a second way. The
question this experiment raised is closed, and closed in §5.3's favour. Lists
and sections are unaffected (0 phantom prefixes each), so their 59.7% and 79.7%
stand as published.

#### The defect is in `armc.replay`, and its docstring names the rule it broke

`replay` selects prefixes by **re-executing the first call against `--binary`**
rather than reading the recorded `exit_codes`, and the comment at `armc.py:497`
argues for it: the single-turn arms record no codes, and *"the code a current
binary returns is the one the replay will actually send, which is the thing
being selected on."* That reasoning is sound for the replay's own mechanics —
the continuation genuinely is executed by that binary, so the prefix genuinely
is refused *within the replay*.

What it does not survive is a **retired scheme**. `scheme_d` was measured, lost,
and was not adopted; the binary implements `scheme_f`. Re-executing a `scheme_d`
prefix against it asks a model to recover from a refusal it would never have
seen, for using an argument its own tool declares. The population is not
"prefixes that were refused" but "prefixes the current binary refuses," and for
a retired scheme those are different sets.

The same docstring already states the constraint that would have caught the
error, for a different reason — `_check_supported` is skipped because the
executor divergence is held constant across framings, and so:

> It does mean a replay's absolute rate is not comparable to a list or table
> rate in FINDINGS, only to its own pair.

The first version of this section compared the tables `plain` column to §5.3's
B3 — precisely the comparison that sentence forbids — and then explained the
difference. **A caveat that is written down is not the same as a caveat that is
applied.**

**What this does not touch.** F-framing's actual endpoints are *paired*
plain-vs-json within each prefix, and the executor is identical on both sides of
every pair. A prefix the binary should not have refused is refused the same way
in both conditions, so it cannot move a paired difference. The primary and
secondary results, the mechanism stratification and the single-turn table all
stand exactly as published. What moves is one **absolute** rate, read across
populations, which is the one thing the harness said not to do.

**Fixed.** `armc.replay` now replays every selected first call through the
oracle and **aborts** if any of them succeeded, naming the count and the
schemes; `--allow-executor-mismatch` proceeds for a run where only a paired
contrast will be read. Details and the verification in the Open list.

#### The message really was wrong, and is fixed anyway

The refusal those 38 read is still a defect, independent of what it cost here:

```
a row is required: either `values` keyed by column name, or `row` as an ordered array.
  Columns: Component | Status | Owner
```

The shipping schema declares `values` and nothing else, and its own description
already says the right thing — *"Either an object keyed by column name, or an
array of values in column order."* The core rejects `row` **deliberately**:
`ops/dispatch.rs:19-23` records that the oracle keeps it as a legacy alias so
`scheme_d`'s trials stay regradable, while §6.2 rejected it for the shipping
schema after measuring it. So a shipping-schema model that omits `values` is
told to send an argument it does not have and the crate refuses — §5.3's rule
(*a wrong suggestion is worse than none*) broken by a §5.3 message, the third
time that rule has been the finding after S11/S12's `Valid ordinals: 0` and
F-unique's single-match branch.

**Its cost is unmeasured and there is no population to measure it on.** No
recorded call from any shipping scheme has ever produced this refusal. It is
fixed below on the argument that a refusal must describe the schema in force,
not because a number says it is expensive — and the section says so rather than
borrowing the 13/38.

**Why it survived everything.** The sentence is byte-identical in both
implementations, so `difftest.py` agrees; the oracle really does accept `row`,
so the sentence is *true of the oracle* and false of the shipping binary. The
suite proves the two agree on what they say, not that what they say is
takeable. *A differential suite proves agreement; it does not proof-read.*

And the gap is not a missing case — it is the boundary of the method. A
`table-add-row` case can express `{"row": [...]}` perfectly well: the family
rides `apply_op` with full JSON arguments (`difftest.py`'s `DISPATCH_ARGS`
already sends `"values": ["only-one"]`), so nothing prevents one. Adding one
would **fail**, because the thing the sentence is wrong about — whether `row`
works — is a *sanctioned* divergence: the oracle keeps the alias so `scheme_d`
regrades, and `ops/dispatch.rs` refuses it on purpose. **A suite that compares
two implementations is blind exactly where they are allowed to differ**, and
that is where a message can recommend something only one of them accepts. The
check has to be one-sided — against the schema, not against the other
implementation.

**Fixed — F-rowarg**, in the section below. Three sentences moved, not one; the
change is grade-neutral against every recorded call, confirmed rather than
argued; and the guard that would have caught it is a schema check, not a
differential one, for the reason just given.

#### Answered: the weak list stratum is L3, re-measured

The same cut puts lists at 59.7% pooled with one stratum low: `` `text` is
required: the content of the new list item. `` at **16/37 = 43.2%**. First
recorded here as an observation with a guess attached — *a one-line refusal
under-specifies the repair*. The guess was wrong, and checking it is what
produced the rule in the next subsection.

**The refusal is not the cause; the schema is.** All 37 prefixes are `list_f`
(31) and `list_naive` (6). The adopted `list_g` contributes **zero**, and the
census says why:

| lists scheme | calls drawing `` `text` is required `` |
| --- | --- |
| `list_f` | **39 of 100** |
| `list_naive` | 7 of 100 |
| `list_g` — **adopted** | **0 of 400** |
| `list_h` | 0 of 200 |
| `list_i` | 0 of 100 |

`list_f` declares `item` (the selector) *and* `text` (the payload), and **12 of
its 31 retries put the payload back into `item`** — which is L3's finding
verbatim: *"`item` and `text` are synonyms and the model wrote the payload into
the selector 39 times."* L3 renamed the selector to `match` and the refusal
stopped being reachable: **0 in 700 calls** across the three post-rename
schemes. The stratum is that defect being measured a second way, a year later,
in a pool that still contains the schema it was found in.

**So there is nothing to fix and nothing to run.** The repair shipped as
`list_g`. What the shipping schema's own 9 prefixes do is 5/9 — the only
lists number here that bears on the product, and far too few to read.

#### The second hazard: a genuine refusal that still says nothing

This is the same root as the tables correction above, and it is worth separating
because **the guard that catches one does not catch the other.**

| | tables, `a row is required` | lists, `` `text` is required `` |
| --- | --- | --- |
| was the call really refused? | **no** — the oracle accepts it | **yes** |
| caught by `executor_mismatch`? | yes | **no, and it should not be** |
| what the rate is really about | the harness | a **retired schema** |
| bears on what ships? | no | no |

`executor_mismatch` detects a *contradiction* — two executors disagreeing about
whether there was a fault at all. Attribution is a different failure and has no
mechanical tell: these 37 models genuinely failed, and the transcript looks
exactly like a shipping-schema model failing. Only the scheme label says
otherwise.

> **A prefix pool inherits the schema its trials were run under.** A rate over
> it describes the schema the prefixes came from, not the one under test — and
> that is true whether or not the refusals in it were real.

Three instances now: this, the tables artifact, and S15's pool predating the
adopted section spelling. The standing consequence is that a stratum from a
replay needs its scheme composition printed beside it before it is read, which
`framing_report.py` now does.

#### Tested and not established: that one-line refusals recover worse

Worth recording because it looked strong and is the obvious thing to conclude
from the table above. Across all 164 phantom-free prefixes, refusals with a
continuation line recover **101/118 = 85.6%** and single-line ones **19/46 =
41.3%**, with non-overlapping intervals — which would be a design rule for every
message in the project if it held.

It does not hold up. **40 of the 46 single-line prefixes are the two `` `text`
is required `` messages**, so the contrast is one sentence wearing a shape's
clothing, and that sentence is now known to be a retired schema's problem. Leave
those out and single-line recovery is **3/6**. That is Caveat 2 in a new costume:
*a rate carried by one message is one message sampled repeatedly.*

Not claimed, and deliberately not fixed — flattening or padding refusals on this
evidence would be exactly the move the mechanism section above already warns
against.

### The mechanism prediction failed, and the data says so

The pre-registered mechanism was that escaping destroys §5.3's shape. Stratify
the one-turn endpoint by what the framing actually does to each refusal:

| what `json` changes about this refusal | n | plain-only | json-only | p |
| --- | --- | --- | --- | --- |
| newline **and** quote escaped | 105 | 15 | 8 | 0.21 |
| newline only | 51 | 6 | 7 | 1.0 |
| **nothing but the `{"error": …}` wrapper** | 41 | **7** | **2** | 0.18 |
| quote only | 5 | 0 | 0 | 1.0 |

**The effect does not concentrate where the escaping is.** The 41 prefixes whose
refusal is a single line with no quote in it — where the two conditions differ
by the wrapper and by nothing else — move 7–2 in `plain`'s favour, a *larger*
proportion than the 105 where both escapes fire (15–8). The stratum where only
the newline is escaped, which the prediction says should behave like the
first, instead runs backwards at 6–7. Whatever is happening is not the loss of
the indented continuation line. It is the wrapper, or it is noise, and this n
cannot tell those apart.

So the prediction was wrong on cause, which is the more useful half to have been
wrong about: it rules out the fix that would otherwise look obvious. Flattening
incise's refusals to one line to survive the escaping would be work spent on the
stratum that shows the *least* effect. It was also right on direction at 141
prefixes and is no longer clearly right on direction at 202 — see the tables
column above.

### The single-turn caller, which needed no new trials

This was written up as open and as "a different experiment rather than more n
for this one." The first half was right and the second was wrong, which is worth
recording because the reason is reusable.

`--turns N` counts the whole trial, and the prefix's refused call is turn 1
(`armc.py:599` passes `max_turns - 1` on). So a host that grants one attempt
after a refusal gets exactly the trial's **second** call — and the turn budget
never reaches the model, because nothing in the payload mentions it. The second
call in a four-turn transcript is therefore byte-identical to the only call a
single-turn caller would have got. Grading `tool_calls[:2]` is the single-turn
experiment, not an estimate of it, and it costs no GPU time at all. The check
that this is sound is that grading the *untruncated* list reproduces the
four-turn column exactly, which it does.

| endpoint | n | `plain` | `json` | discordant | p |
| --- | --- | --- | --- | --- | --- |
| **one turn, graded `correct`** | 202 | **123 (60.9%)** | 113 (55.9%) | 25–15 | 0.154 |
| four turns, graded `correct` | 202 | 150 (74.3%) | 149 (73.8%) | 18–17 | 1.00 |

*(After F-terminal's regrade: 125 / 115, 25–15, p = 0.154 and 155 / 152, 20–17,
p = 0.743. Both discordant pairs and both p-values on the one-turn row are
unchanged; only the totals move. See F-terminal.)*

The same shape as every other endpoint here: `plain` leads by about five points,
it is not significant, and **tables is again exactly level** (36–36, 6–6,
p = 1.00) while lists (11–5) and sections (8–4) lean. A single-turn host is not
the case where the small effect becomes a large one.

What the pair of rows does give is the mechanism, measured rather than inferred:

| | one turn | four turns | later turns repaired | destroyed |
| --- | --- | --- | --- | --- |
| `plain` | 123 | 150 | 27 | **0** |
| `json` | 113 | 149 | **36** | **0** |

`json` starts **10 behind** and finishes **1 behind**. The extra turns do not
merely dilute the difference — they spend themselves on it, repairing 36 trials
against `plain`'s 27, which is almost exactly the deficit. "The framing costs a
turn, not an outcome" was a reading of two endpoints; this is the same claim
with the turns' work shown.

And the zero is worth its own line. **Across all 404 trials, not one document
that was correct after the first repair was broken by a later turn.** That is
not what §6.3.2 found — S14 measured 36% destruction from an extra call against
1.1% without one. The populations differ in the way that matters: S14's extra
call lands on a task that was already done, while every turn here follows a
refusal and has visible work to do. **An unnecessary turn is dangerous; a turn
granted after a refusal, on this evidence, is free.** That is a narrower claim
than S14's and does not soften it.

### What this closes and what it does not

- **Divergence 2 is not a live risk.** 1 refusal in 353 crosses the cap, by 9
  characters, and the condition cannot be sized. It should be recorded as
  measured-and-inert rather than unmeasured. The 2200-character refusal remains
  reproducible on demand, so a corpus that grew more tables would revive it.
- **Divergence 1 does not change the outcome.** Three families, 202 paired
  prefixes, 18–17, p = 1.00 (20–17, p = 0.743 after F-terminal). This is the
  claim that is actually established, and
  it is the one the plugin needs: following the host's convention costs nothing
  measurable in what the model ends up doing.
- **The one-turn cost is not established, and is weaker than it first looked.**
  22–11 (p = 0.080) on lists and sections became 28–17 (**p = 0.135**) once
  tables was added, because tables is dead level at 6–6. An effect that shrinks
  when you add data is the shape of noise at least as much as the shape of a
  small effect. It may not be quoted as a cost.
- **The README's refusal to assume the difference inert was still the right
  call** — not because the difference turned out to matter, but because that is
  the only reason it got measured. What it bought is a measured null on the
  endpoint that matters, in place of an assumed one.
- **Single-turn callers: measured, and it is the same answer.** 60.9% against
  55.9%, 25–15, **p = 0.154**, with tables level again. Granting one attempt
  does not turn the small lean into an outcome cost. This needed no new trials —
  the second call of a four-turn transcript *is* the single-turn caller's only
  call, because the budget never reaches the model.
- **Answered: what one-turn recovery does a refused prefix get?** Not a family
  rate at all — and the first answer here was wrong twice over. Split by the
  sentence the model read, every tables refusal recovers at 100%, including
  B3's own message at 13/13 again. The one exception, ``a row is required``, is
  62% of the pool and recovers at 13/38 — **because those 38 were never refused
  in the arm.** They are `scheme_d` prefixes whose first call Arm B's executor
  *accepts*, re-executed by a binary that does not implement `scheme_d`. Over
  the 23 genuinely-refused tables prefixes the rate is **23/23 = 100%**. So:
  selection was not the explanation, the refusal was not either, and the answer
  is §5.3's number. See the correction above and the `armc.replay` item in Open.
- **Closed, and not worth re-opening: more n from this pool.** 353 recorded
  refusals exist, 202 are used, so the ceiling without generating new trials is
  about 1.7× what has been run — and the direction of travel from 141 to 202 was
  toward the null, not away from it.

- **A turn after a refusal is free; an unnecessary turn is not.** Zero of 404
  trials had a correct first repair broken by a later turn. §6.3.2's 36%
  destruction figure is for an extra call on a task that was already done, which
  is a different thing, and this does not soften it.

Raw and graded trials in
`results/armc_framing_{lists,sections,tables}{,_graded}.jsonl`. Every number in
this section is recomputed by `python3 bench/framing_report.py`, and the refusal
population by `python3 bench/refusal_pool.py` — quoted-but-never-recomputed is
how the figure above went wrong twice.


## F-rowarg — a refusal that advertised an argument the product refuses

`table-add-row`'s empty-row refusal named `row`:

```
a row is required: either `values` keyed by column name, or `row` as an ordered array.
  Columns: Component | Status | Owner
```

`table_edit` has never declared `row`. `scheme_d` did, was measured, and was not
adopted; §6.2 rejected the alias for the shipping schema. `ops/dispatch.rs:14-32`
records the resulting divergence as deliberate — the oracle keeps `row` so
`scheme_d`'s recorded trials stay regradable, the crate refuses it — which means
the message told a shipping-schema model to send the one thing the product is
built to reject.

**Fixed without a number, and the section says so.** The cost this was first
written up with (13/38 one-turn recovery) was the `armc.replay` artifact and is
withdrawn. The honest position is that the cost is *unmeasured and unmeasurable
from what exists*: across 480 recorded table calls, **zero** ever drew this
refusal, and all 41 `row`-as-array calls in the census come from `scheme_d`, the
one scheme that declares it. The argument for changing it is §5.3's own rule —
*a wrong suggestion is worse than none: it is authoritative and the model will
follow it* — applied to a branch no arm has reached. That is a weaker warrant
than a measurement and it is the only one available, which is itself the finding:
**a defect on a branch the measured schemes never take is invisible to every arm,
and will ship.**

### Three sentences, not one

The `row` in the refusal was the visible one. Two more were in `values_to_row`,
reached by a model that had used the **correct** argument:

| | before | after |
|---|---|---|
| empty row | ``a row is required: either `values` keyed by column name, or `row` as an ordered array.`` | ``a row is required: `values`, either an object keyed by column name or an array of values in column order.`` |
| wrong length | ``\`row\` has 1 values but the table has 3 columns: …`` | ``\`values\` is an array of 1, but the table has 3 columns: …`` |
| bad cell | `check_cell(v, &cols[i], "row")` → *the value for "X" in `row` must be text* | `check_cell(v, &cols[i], "values")` |

The wrong-length one also loses a subject-verb disagreement (`has 1 values`) that
had been there since the family was written. The third is `_check_cell`'s label,
which is interpolated at runtime — it is why the guard below needed a second,
different check.

**One sentence deliberately left alone.** ``\`values\` and `row` describe
different rows`` still says `row`, because it fires only when the model sent
both, so it names what arrived rather than recommending what to send. That
distinction is the whole design of the guard's allowlist.

### Grade-neutral, confirmed rather than argued

The F-dupcol standard (`FINDINGS:2318-2330`): enumerate every moved digest and
replay it, never reason from the shape of the change.

`python3 bench/regrade_snapshot.py --compare` — **29 of 10072** recorded calls
change sentence. `--explain` over those keys gives **125 differing corpus
results, 100% ERR → ERR**, in four transitions: 48 + 48 + 24 wrong-length
variants across three column layouts, and 5 empty-row. A refusal writes no
document, so no grade can move — and rather than stop there, all 29 affected
trials were re-graded before and after: **identical, 16 `correct` and 13
`op_error`**. The `_check_cell` label change is reached by **zero** recorded
calls, which is consistent with the census above.

### The guard is one-sided, because a differential one cannot work

Nothing caught this for the life of the family, and the reason bounds the method
rather than blaming it. The sentence was byte-identical in `incise_ops.py` and
`ops/table.rs`, so `difftest.py` agreed on the string. And the thing it was wrong
about — whether `row` is accepted — is a **sanctioned** divergence. A difftest
case sending `{"row": [...]}` is perfectly expressible (the family rides
`apply_op` with full JSON arguments; `DISPATCH_ARGS` already sends
`"values": ["only-one"]`) and would **fail by design**.

> **A suite that compares two implementations is blind exactly where they are
> allowed to differ** — and that is precisely where a message can recommend
> something only one of them accepts.

So `bench/schematest.py` gains two checks against the **schema**, not against the
other implementation:

- `refusal_backticks` — walk every `raise` in `incise_ops.py`, collect backticked
  literals, and fail on any token no adopted scheme declares. F-strings are read
  whole with their holes replaced by a sentinel, so `` `{field}` `` is not
  mistaken for a literal argument name.
- `check_cell_labels` — the same rule for `_check_cell`'s third argument, which
  becomes a backticked name at runtime and is therefore invisible to the first
  check. This is the one that catches the third defect.

`ALLOWED_BACKTICKS` is the audit: every exception is a claim with a reason, and
it is short on purpose, since growing it is how the check stops checking.

**The guard failed its own mutation test, which is why it works.** Reintroducing
the original sentence, `schematest.py` printed `3 tools, byte-identical…` and
exited 0. The cause: `row` was allowlisted as a bare token, so permitting the one
refusal that may legitimately name it had switched the check off for `row`
*everywhere* — disabling it for exactly the token it was written to catch. Every
allowance is now a `(reason, required_context)` pair scoped to one message. All
three defects were then reintroduced one at a time and all three are caught, with
the clean tree passing. *A guard that passes on a clean tree proves nothing until
you reintroduce the defect and watch it fail.*

### Verification

| | |
|---|---|
| `cargo test` | 14 / 16 / 45 / 29, 0 failed |
| `difftest.py` | 89177 cases, all agree with the oracle |
| `test_incise_ops.py` | all corpus-wide invariants hold |
| `mutate.py` | 185/185 caught, no survivors; tail read (1, 1, 2, 2, 3, 4, …) |
| `schematest.py` | 3 tools byte-identical, and all three defects caught when reintroduced |
| `regrade_snapshot.py --compare` | 29 calls moved, 125 results ERR → ERR, 29/29 trials re-grade identically |

`dispatch.rs`'s test assertion moved with the message and now pins the argument
name as well as the count, so the divergence stays asserted from the crate's
side.


## F-unique — the rewritten refusal was measured, and every caller was in the branch nobody wrote

F-address left one line open: *"Not yet re-measured on the 16 `section_g`
retries."* Sixteen retries is a small enough population that the obvious move is
to look at them and decide. Sizing it first — F-action's lesson, that reading the
recorded calls changes what the fix has to say — found something else entirely.

`bench/ordinal_sizing.py` replays all 12,615 recorded trials in
`bench/results/`, in trial order, carrying each trial's document forward across
its own calls, and collects every call the section resolver refuses on an
ordinal. There are **140**, not 16, and **111** of them are first calls, where
the document is the pristine fixture and `grade.check_result` means what it means
everywhere else.

> **These six figures were published wrong for one commit, and the reason is in
> this file twice already.** The first version of the sizing counted every row in
> `bench/results/`, including the replays' own output — whose first call is
> *pinned*, so each one is a call already in the population. Published as 206 /
> 155 / 53 / 64 / 119 / 78; the true values are 140 / 111 / 37 / 52 / 91 / 62.
> **Nothing below changes direction or sign.** F-framing recorded this exact
> failure (*"`results/` is not one population. Any future count over it has to
> select on arm before it counts"*) and this instrument was written afterwards
> and did not. The fix is `refusals()` skipping any row with a `tag` field —
> which every replay row carries and no other row does. Keying on the *scheme
> string* instead, the obvious move, was tried and is wrong: it also discards
> S14's `section_g:delta` and `section_kids:both`, which are genuine trials at a
> different result shape, and would have thrown away eleven real samples to
> remove sixty-six duplicates.

### Both branches of the rewrite have zero callers

F-address's whole content was a split: sections with **different** paths cannot
be told apart by an ordinal, so the repair is a longer path; sections **sharing**
a path are what ordinals are for, so name the real ones. That split was right,
and it fixed the twenty-one zeroes. It is also answering a question no recorded
caller asked. All 140 messages offered exactly one ordinal — `0` — which is the
resolver's own statement, read back off its own sentence rather than recomputed,
that **the path matched exactly one section**. Not one caller had a tie. A
message explaining how to disambiguate tied sections was sent 140 times to
callers with nothing to disambiguate.

### Its advice destroyed the document 52 times

The two repairs the old message offered — `Send ordinal 0` and `or drop it` —
are the same repair under two names, and the grades prove it rather than the
reading: applied to the 111 first calls they produce identical outcome
distributions, 37 `correct` and **52 `destructive`** each.

All 52 are `rename-closed-atx`. The model sends the parent path
(`Setext H1 Title > Setext H2`) with `ordinal: 1`, meaning *the second child*.
Dropping the ordinal renames the **parent** and reports success. That is the
destructive retry S11 and S12 traced to `Valid ordinals: 0` — surviving the
rewrite that was written to answer it, because the rewrite changed the sentence
in the branch that fires for ties and left the single-match branch alone. It is
also §5.3's own rule failing on its own terms: *a wrong suggestion is worse than
none: it is authoritative and the model will follow it.* The old message
satisfies the letter of §5.3 — its suggestion does match exactly one row — and
violates the reason for it, because it is the **wrong** row 41% of the time.

`difftest.py` could not have caught this and should not be expected to. It
passed 88049/88049 on a message giving advice nobody could take, for F-address's
own reason: the oracle said it too. A differential suite proves agreement; it
does not proof-read.

### The third branch

The single-match case now says the thing that is true and load-bearing, in the
order S11's own reasoning gives. S11 kept this refusal at all because **the
ordinal is the only evidence the path is wrong** — a caller who sends one has
asserted there are several of these, and there is one, so the caller's own call
is the evidence. "You probably meant this one, drop the ordinal" throws that
evidence away. So the path reading leads, and the sections nested under the
match are quoted:

```
no section "Setext H1 Title > Setext H2" with ordinal 1.
  Only one section matches `section.path`. Sending an ordinal says you expected several, so it may not be the section you meant.
  If you meant a section inside it, send one of these as `section.path`: "Setext H1 Title > Setext H2 > ATX level 3"; "Setext H1 Title > Setext H2 > Closed ATX level 3"; "Setext H1 Title > Setext H2 > Extra leading spaces in text"; "Setext H1 Title > Setext H2 > Indented three spaces"
  If you did mean this one, send it again without an ordinal.
```

`section.path` is `want_label` — the key the caller actually sent — not a fixed
word, and the arm below is what put it there.

Nothing here scores or ranks the two readings. The resolver cannot tell them
apart, and guessing would be the invention §6.4 forbids. Both lines are
conditionals for that reason, and `Send ordinal 0, or drop it.` was not.

Two builds, `git stash` apart, same script:

| on the 140 / 111 | before | after |
|---|---|---|
| repairs offered | `ordinal 0` ×140 and `drop` ×140 — one repair, two names | `drop` ×140, `longer path` ×453 |
| a correct repair is offered **anywhere** (111) | **37** | **91** |
| refusal quotes the address the task wanted (140) | **0** | **62** |
| …on the 52 calls the old advice destroyed | 0 / 52 | **52 / 52** |
| taking the first repair offered, blind (111) | 52 destructive | **62 destructive** |

The last row is the honest one and it moved the wrong way. It is an upper bound
on damage, not a prediction: a list of longer paths is a **menu**, and scoring it
by taking the first item treats the menu as an order. For the old message the two
readings coincided, because it *was* an order. For this one they do not, so both
get reported. What is established is that the right address is now **in** the
sentence — 91 of 111 against 37, and 52 of 52 on exactly the calls that used to
be destroyed. What is **not** established is that a model picks it. That needs an
arm, and the instrument already exists: `armc.replay --select refusal` across two
`--binary`s with `--tag`, which compares two programs instead of transcribing a
message into the harness.

### Verification

- `cargo test` 104 tests, `difftest.py` **88613** cases agree — up 564, from
  three new addresses that reach all three arms of the branch, including
  `API reference` with 93 descendants, the only case in the file that crosses
  the eight-path cap. A cap no case crosses is a cap two implementations can
  disagree about silently.
- `mutate.py` **184/184 caught, no survivors**. Three are new, and until they
  landed the only mutation that could reach this branch was one deleting it
  outright: `section-unique-branch` (381 mismatches), `section-unique-inner`
  (118), `section-unique-cap` (18). Read at the tail, as the rule requires — the
  thinnest entries are still the pre-existing single-case guards.
- `regrade_snapshot.py`: **219 of 9670 calls moved**, and all 219 are enumerated
  rather than argued. 231 corpus results differ across them and every one is
  `ERR → ERR` with an **identical first line** and the new second line in all
  231 — the same address refused for the same reason, in different words. A
  refusal writes no document, so no grade can move. This is the third time a
  moved-digest enumeration has been needed (F-dupcol, F-action, here), so it is
  now a command: `--moved-out`, `--keys`, `--vectors`, `--explain`.
- `test_incise_ops.py` and `schematest.py` unchanged; `corpus/` clean.

Regenerate with `python3 bench/ordinal_sizing.py`, at the commit before and
after — the two outputs are the before and the after.

### The arm, and the prediction it falsified

The open item above — *which reading does a model take* — was run rather than
left open, because the instrument existed and the sample turned out to be small.
`ordinal_sizing.py --emit-prefixes` selects the prefixes whose **first call**
reaches this branch and hands them to `armc.replay --select refusal`; `--select`
alone would have sampled every exit-1 refusal, and the builds emit the same
sentence for nearly all of them, which is caveat 18 by construction — pairs that
*cannot* differ are dilution, not evidence of a null.

That selection is also the first honest number here. The 140 refusals are **56
prefixes over 27 distinct (scheme, task, first call) situations**. 140 counts
recorded calls; the sample is 27 situations wide, and every figure in the section
above should be read with that in mind.

Three builds, `--tag before|after|labelled`, 54 prefixes present in all three,
four turns, `plain` framing:

| n = 54 | before | after | labelled |
|---|---|---|---|
| `correct` | 42 | 43 | 42 |
| `destructive` | **5** | 2 | **0** |
| `usage_error` | **0** | 2 | **4** |
| the agent is not misled | 49 (90.7%) | 51 (94.4%) | **52 (96.3%)** |

- **The endpoint does not move.** 42 / 43 / 42, and `p = 1` on every pairwise
  comparison. The rewrite is not an outcome win and this section does not claim
  one.
- **Destructive falls monotonically to zero**, all of it on `rename-closed-atx`,
  the task named in advance: 4 → 0 → 0 within that subgroup. before-vs-labelled
  is discordant **5–0, p = 0.0625** — which is the *exact floor* of the two-sided
  exact test at five discordant pairs. This sample cannot produce significance
  here however large the effect is; six would be needed. S16's rule applies with
  the sign flipped: a signal failing a threshold is not a signal shown to be
  absent.
- **A new failure mode appears, and it is the better one.** `usage_error` goes
  0 → 2 → 4. By this file's own dividing line — *`op_error` tells the agent the
  edit did not happen; `wrong`, `destructive` and `collateral` leave it believing
  the edit succeeded* — that is the safe side, which is why the last row is the
  one to read: 90.7% → 96.3%.

**The prediction that failed.** The two `usage_error`s under `after` both put the
section address into the tool's `path` argument — the **file** —
`"path": "corpus/sections/setext-and-atx.md/Setext H1 Title/Setext H2/Closed ATX
level 3"`, and one of the two had recovered correctly under the old message. The
stated diagnosis was the wording: the draft said *"send the longer path"*, and
`path` names the file on every tool. So the message was changed to quote
`want_label` — the key the caller actually sent — which is the convention the
resolver already states six lines above the branch, and which the first draft
had simply broken.

It did not work. `usage_error` went **2 → 4**, and two of the four still fuse the
file path with the section address *under a message that correctly says
`section.path`*. The wording was never the mechanism. In these schemes the two
arguments are genuinely both called `path`, and no refusal sentence can rename an
argument. That is S15's collision, structural, and S15 already fixed it the only
way it can be fixed — by renaming the address to `section.heading`.

Which leads to the limit on all of the above: **every prefix in this pool predates
S15.** The five schemes represented (`section_kids`, `section_g`, `section_2call`,
`section_p`, `section_naive`) all address sections by `section.path`, so the
adopted schema `section_g_hpath` — the one that does *not* have the collision —
is not in the sample at all. What was measured is recovery under the schema S15
replaced.

The `labelled` build is kept, and the measurement is not the reason. It is best
on both safety columns and flat on the endpoint, but at these widths that is a
lean, not a result. It is kept because quoting the caller's own key is the rule
the family already wrote down, and because in `section_g_hpath` the alternative
names the file argument and nothing else.

Raw and graded trials in `results/armc_ordinal{,_graded}.jsonl`. Rebuild the
sample with `python3 bench/ordinal_sizing.py --emit-prefixes …`, then
`armc.py --replay … --binary … --tag …` once per build.

### Why the pool predates S15: the shipping schema barely reaches this branch

The limitation above reads like an accident of scheduling — the arms that
produce ordinal refusals happened to run before S15. It is not. S15's own rows
answer it, at no cost, because all three of its arms ran the same 15 tasks at
the same trials and the same result shape in one batch:

| S15 arm, 200 trials each | address | spurious `ordinal` | ordinal refusals |
|---|---|---|---|
| `section_g` (control) | `section.path` | **59** of 190 | **12** |
| `section_g_file` | `section.path` | **0** of 190 | **0** |
| `section_g_hpath` **(ships)** | `section.heading` | **1** of 190 | **0** |

Paired by `(task, trial)` and excluding `notes-second-ordinal` — the one task in
the family whose own note says *"an ordinal is the answer rather than a longer
path"* — the control sends a spurious ordinal 59 times and the shipping schema
once: discordant **58–0**, `p = 6.9e-18`. `section_g_file` is 59–0,
`p = 3.5e-18`.

**And it costs nothing.** On the task that genuinely needs an ordinal all three
arms are **10/10**. The renames did not suppress ordinals; they removed only the
spurious ones. That is the rare shape where there is no trade to weigh.

**The mechanism is not the word `heading`.** `section_g_file` leaves the address
spelled `section.path` and renames only the *file* argument, and it shows the
same effect — slightly larger. What both renames share is the removal of the
collision, where `path` meant the file at the top level and the section address
one level down. The reading this supports: a model unsure which `path` it is
looking at reaches for `ordinal` as a disambiguator. Remove the ambiguity and it
addresses by name and stops. That is a hypothesis the data is consistent with,
not one it establishes — nothing here manipulates the disambiguator directly.

So the consequence for the branch F-unique rewrote: under the schema that ships
it fires **0 times in 400 trials**, against 12 in 200 under the spelling S15
replaced. The prefix pool predates S15 because the shipping schema does not
produce these refusals, not because nobody has run the arm yet.

This does **not** retire the rewrite. 12-in-200 is a real rate for any caller on
the old spelling, the plugin exposes its own schema, and the destructive edits
the rewrite eliminated were real. What it retires is the plan to buy the missing
cell with GPU time: an arm sized to detect recovery on a branch that fires twice
per thousand trials is not a study anyone can afford.

**Caveats.** This is a **post-hoc endpoint** — S15 was pre-registered on
outcomes, and "did the model send an ordinal" is read off its stored rows after
the fact; it is exploratory whatever the p-value says. One run, 15 tasks, one
model. The 59 spurious trials spread across 10 distinct tasks, which is the
check caveat 2 asks for, but not evenly: `promote-api` alone contributes 19.
Every figure here is from `bench/population.py` over `armb_s15_*` and no new
trial was run.

### Writing the arm's rows into `results/` broke three published numbers

Committing `armc_ordinal.jsonl` added 165 rows to `bench/results/`, and every
script that counts over that directory moved. This is worth its own heading
because it is the **third** time, the rule was already written down twice, and
both existing implementations of it were wrong in a way that only shows up when
someone adds a file.

| command | published | after the 165 rows | after the fix |
|---|---|---|---|
| `ordinal_sizing.py` | 206 refusals / 155 first calls | 385 | **140 / 111** |
| `refusal_pool.py` | 353 real refusals | 525 | **360** |
| `action_sizing.py` | 21 fused keys of 8823 | 21 of 9440 | **11 of 7535** |

The right-hand column is not the middle column minus my rows. Two separate
defects were sitting underneath:

- **`ordinal_sizing.py` never excluded replay output at all.** So its published
  206 already contained F-framing's replayed first calls. Correct figure 140.
- **`refusal_pool.py` excluded it by file-name prefix**, `armc_framing_`, under
  a comment that explicitly claimed the rule was general: *"not as a blocklist
  of arms: the same applies to any future replay output."* It was a blocklist.
  The next two replays were named `armc_replay_path*` and `armc_ordinal*` and
  walked straight past it. Its 353 → 360 is **not** this defect — that is S16's
  genuine trials, landing after the number was written.
- **`action_sizing.py`'s 21 was double-counted**, and this is the one that
  changes a finding: ten of the twenty-one fused keys are the same calls seen
  twice, all ten at call index 0, which is the index a replay pins. Eleven
  independent events, not twenty-one.

`bench/population.py` now holds the rule once and all four callers use it. The
test is the row's **`tag`** field, which `armb.replay` and `armc.replay` stamp
and nothing else in `results/` carries — a property of the row, so a replay
written tomorrow under any name is excluded the day it is written.

The attempt that did not work is worth recording, because it is the obvious one:
key on the **scheme string**, since replay rows carry compound schemes like
`section_g:before:plain`. So do S14's `section_g:delta` and `section_kids:both`,
which are genuine trials at a different result shape. That rule discards eleven
real samples to remove sixty-six duplicates, and it was caught only by
enumerating what it dropped instead of checking that the total looked better.

**And the instrument's own guard failed open, which is the more transferable
half.** `ordinal_sizing.repairs()` parses the repairs back out of the refusal's
text rather than recomputing them, and promised to stop rather than under-report
if the parse ever fell behind the message. It parsed *some*: when the message
was reworded to quote the caller's key — `send one of these as \`section.path\`:
"…"` — the longer-path regex stopped matching, every longer-path repair silently
vanished, and `drop` still parsed, so the run completed and reported a smaller
population. A guard on "did anything parse" is not a guard. It now also checks
that **every address quoted below the first line is an address some parsed
repair actually sends**, which fails on exactly the drift that got through, and
`BRANCHES` no longer keys on a clause containing an interpolated value.

Nothing above changes a direction, a sign, or a conclusion. What it changes is
six figures, and the reason to write it down is that three separate commits
each added a file to `results/` and each silently moved numbers in documents
nobody re-ran.

### A fourth instance, and the first that made a script stop working

Auditing the above turned up the same defect once more, in a different shape
and with a louder failure. `s15_analyse.py` globs `armb_s15_*.jsonl` and keys
rows by `(scheme, task_id, trial)`. That glob also matches
`armb_s15_section_g_hpath_graded.jsonl`, written later as S16's control. A
graded row carries the same key, reports an `outcome`, and **has no
`tool_calls`** — and `_graded.jsonl` sorts after the raw file, so every
`section_g_hpath` trial was overwritten by a call-less stub.

The script therefore reported the **shipping schema at 0/150 correct**, with a
McNemar of `p = 1.2e-38` against the control. Every hpath figure it prints goes
through `tool_calls`, so all of them were affected at once.

Three things worth keeping:

- **Loud beats silent, and this was luck.** The first three instances moved a
  number by a few percent and nobody noticed for three commits. This one moved
  it to zero, which is why it was caught on the first run. The class of defect
  is identical; only the blast radius differed.
- **The published numbers were never wrong.** With the fix,
  `section_g_hpath` is **130/150 = 86.7%, CI 80.3–91.2** — matching what S15
  published to the digit, including the interval. The graded file landed after
  those numbers were computed. What broke was not the result but the
  *command that regenerates it*, which by this project's own standard is the
  same thing one commit later.
- **Shadowing, not double counting.** The first three instances inflated a
  denominator. This one substituted rows. A rule written only against double
  counting would not have caught it, which is why `population.py` now excludes
  grading records as well as replays — 5768 rows that every existing caller
  happened to survive by skipping rows with no calls, i.e. by luck rather than
  by rule. Excluding them moves no published figure.

`file_argument.py` was already immune, though by filename (`endswith
("_graded.jsonl")`) — a blocklist of exactly the kind that let the replay rows
through, saved here only because it also skips call-less rows.
`regrade_snapshot.py` is immune for a real reason: it keys on
`file:line:call-index`, so a graded row contributes no keys rather than
displacing one.


## F-headroom — three pending re-measurements, priced before the GPU, and all three already answered

Three of the open items ask for a re-measurement. None of them can return
anything, and that is knowable from calls already on disk.

The question is not whether the change is good. It is **how many of the trials
the run would execute can the change touch at all** — and the project has now
answered that question late three separate times, each after the GPU was spent:
F-framing priced a refusal no shipping schema draws, the lists `` `text` ``
stratum described a scheme L3 retired, and F-address re-measured an addressing
fix against tasks that never enter the argument shapes it changed.

`bench/headroom.py` asks it first.

    python3 bench/headroom.py

### Why this keeps happening, which is not bad luck

**The fix that motivates a re-measure is usually the fix that retires its own
population.** A refusal message gets rewritten because some measured scheme
provoked it; the same measurement generally also produces the *schema* change
that stops it being provoked. By the time the message fix is ready to test, the
failure it answers no longer occurs. A re-measure proposed against yesterday's
failure is aimed, by default, at a branch nothing takes any more.

### The arithmetic that makes it decidable

These comparisons are paired and scored with McNemar, where only discordant
pairs carry information. If a change can only move the trials that reach its
branch, the discordant count is at most the reachable count `k`, and
`stats.mcnemar_exact(k, 0)` — every pair falling the same way, the most
favourable outcome that exists — is `2^(1-k)`:

| `k` | best achievable p |
| --- | --- |
| 1 | 1.0000 |
| 5 | 0.0625 |
| **6** | **0.0312** |

**Six reachable trials is a hard floor.** Below it the run cannot reach p<0.05
even if the change is perfect. This is not a power calculation with assumptions
in it; it is the smallest p the test can emit.

**And the bound is one-sided for a description change.** An executor-side change
cannot alter a trial that never reaches it — paired at (task, seed), the
non-reaching trials replay identically — so `k` bounds it both ways. A *schema
description* is in the prompt for every trial, so it can move trials that never
had the failure, which is exactly what S14 measured when an unneeded extra call
destroyed the document 36% of the time. For those, `k` bounds the **gain** and
nothing bounds the **loss**. A description tune at k=1 is not merely
underpowered: it is an uncapped downside bought for a capped upside.

### The three results

| open item | side | adopted scheme | n | k | verdict |
| --- | --- | --- | --- | --- | --- |
| Re-measure B2 with the improved error text first | description | `scheme_f` | 120 | **0** | closed |
| Re-run `section_naive`/`section_p` guarded, live | executor | `section_g_hpath` | 651 | **0** | closed |
| Say in the description that `filter` is literal | description | `table_read_g` | 120 | **2** | underpowered |

**B2.** The confabulated-selector refusal (`no row matches all of {…}`) fires 13
times in `scheme_a`'s 60 trials — the published figure — and **0 times in
`scheme_f`'s 120**. B6/B7's description rewrite already removed the failure a
warning would have been written to prevent.

**S8's guards.** The two guards are tripped by 20 `section_naive` trials and 20
`section_p` trials, and by **0 of the 3470** trials from every later section
scheme, `section_g_hpath` included. The later schemas carry `overwrite` and
spell the address `heading`, so neither guard has a caller any more.

**`filter`.** One glob-shaped filter in 60 `table_read_g` trials, and
`table_read_naive` sends `filter` not once in its 60. k=1 gives p=1.0000. The
prior question is not the wording but whether the read tool ships at all.

**The `filter` row has since moved, and the way it moved is the argument for
this tool.** When F-headroom ran, no adopted scheme had ever been run on the
table-read family, so the row read *none / n=0 / k=0 / dead* — and the verdict
function said so in those words: "no adopted scheme has ever been run on this
family… whether the tool should ship is the prior question." That question was
then answered (F-compose): `table_get` ships, `table_read_g` is in `ADOPTED`,
and `compose_solo_tables_read` added 60 more trials to its pool. The row is now
`table_read_g` / n=120 / **k=2** / underpowered — still unbuyable, and for a
better-stated reason. It went from "there is no population" to "the population
exists and is two trials deep, against a floor of six." Nothing about the
`filter` question changed; what changed was that something shipped, which is
precisely the dependency the `DEAD` verdict was written to name rather than to
hide. The numbers above are left as F-headroom printed them.

### `k=0` has two meanings and they demand opposite work

The check that makes the verdicts trustworthy is the one that nearly went
unmade. A reachable count of zero can mean the schema fixed the failure, or it
can mean **the adopted scheme was never run on the task that provokes it** —
F-address's failure, where the re-measure reproduced its baseline exactly
because no task went near the change. Those look identical in the totals and
call for opposite responses: one is a question already answered, the other is an
instrument to build.

So the tool counts how often the adopted scheme ran the *provoking* tasks:

- `scheme_f` ran `delete-row-aligned` and `update-cell-multi-table` **40 times**
  and confabulated a selector zero times.
- `section_g_hpath` ran `replace-install-preamble`, `notes-second-ordinal` and
  `insert-subsection-last` **120 times** and tripped a guard zero times.

Both are `closed`, not `untested`. Had either come back zero, the verdict would
have been the opposite one and the work would have been a task set.

### Validation, against a published column rather than by assertion

A counting tool that reports zero everywhere is indistinguishable from a broken
one, so its non-zero counts are tied to something already in this file. The S8
candidate finds 20 guard-tripping trials in each scheme; re-grading those same
outputs against the guarded executor moves `op_error` by **+21 and +20**
(`armb_sections_*_s6guard_graded.jsonl`). S8's table prints +20 and +17 because
its v2 column also carries S10's whitespace fix, which moves three `section_p`
trials back out of `op_error`. The B2 candidate reproduces the published 13.

### What it deliberately does not price

Two open items need an **instrument**, not a count, and are reported as out of
scope rather than as dead — a tool that silently omits what it cannot judge is
worse than one that says so. `children` on a narrower tool is a new tool and a
new scheme; S13's tax is measured, but whether narrowing removes it is a fresh
arm. And the JSON-framing mechanism needs n rather than reach: its strata are
already discordant (7–2, 15–8, 6–7), and separating the wrapper from the
escaping needs a designed contrast.

This does not say a re-measure is worthless — a bounded null is still a result,
and "the guards cost nothing" was worth having. It says what a run can and
cannot return, before the GPU rather than in the write-up.


## F-armcread — Arm C can execute a read, and the recorded reads survive the port exactly

F-read gave a model a read tool for the first time and measured it at Arm B.
Arm C refused the same tasks, for a reason that was true when it was written:
the arm had no way to run a read at all. Both halves of that are now built, and
the answer they produce costs no GPU, because Arm B's 120 recorded read trials
are 120 model outputs that can simply be re-executed through the binary.

**Arm C reproduces Arm B's read grades on 120 of 120 trials**, with zero hash
mismatches:

| scheme | trials | agree | Arm B | Arm C |
|---|---|---|---|---|
| `table_read_naive` | 60 | 60 | 27 correct, 33 unfiltered | identical |
| `table_read_g` | 60 | 60 | 58 correct, 2 misreported | identical |

That is the direction REQUIREMENTS §7.4 asks for — Arm B's rates are the bar the
port must match, not beat — and it is the first time the read path has been held
to it. It is also a *regrade*, not a new arm: no new trial was sampled, so the
rates themselves are F-read's and are not restated here as if they were new
evidence.

The table above is regenerated by `armc.py --cross`, which grades each recorded
trial through both arms' graders and prints the outcome *pair*:

```
python3 bench/armc.py --cross bench/results/armb_read_naive.jsonl \
    --tasks bench/tasks/tables_read.json
python3 bench/armc.py --cross bench/results/armb_read_g.jsonl \
    --tasks bench/tasks/tables_read.json
```

It exits non-zero on any disagreeing pair or any trial that fails to reproduce
its recorded hash, so it is a check and not only a report. It pairs against the
recorded row rather than a fresh run, which is why `--tasks` must be the file
those trials were sampled on, and why a task id absent from it is a hard error:
a mismatched pairing would otherwise report perfect agreement over nothing.

A checker that has only ever printed `0 differ` is indistinguishable from one
that cannot count, so it was also run on a pool with known disagreements — the
500 recorded `armb_lists.jsonl` trials, which are writes and not reads. It
reports **439 agree, 61 differ**, and all 61 are a single cause already on the
record: the model omitted `path`, which Arm B cannot see because `grade_one`
opens `task["fixture"]` and never reads the argument. That is F-front's result
above, reproduced from the other arm's trials — the 439 where a path was given
agree exactly, so the finding is about the schema, not the port.

The harness check runs first and says the same thing from the other side.
`ceiling.py --arm c` on the six read tasks was **0/6** before this and is **6/6**
after — every ideal call was landing as `malformed`, because `incise table-get`
is an external subcommand that reaches `apply_op` and draws `unknown operation`.
A read task handed to this arm would have been graded as a failure of the model.

### Two blockers, and neither was a measurement question

**argv.** `execute` builds `[binary, op]`, and `table-get` is not a subcommand —
§6.1 keeps the reads out of `OPS`, so it is `incise rows`, which took only
`--table`, `--ordinal` and `--filter COLUMN=VALUE`. Those flags cannot carry a
nested address: `{"table": {"heading": …, "ordinal": …}}` is reachable only
because `collect_rows_args` knows to build that one nesting, and a filter value
that is not a string has no spelling at all, so `check_cell`'s refusals for a
boolean, a number or a null inside a filter were unreachable through that door.

The tempting fix — translate the model's argument object into flags inside the
harness — is the one this arm exists to avoid. *Nothing is checked before the
binary sees it*: the order arguments are checked in is part of the contract
(§5.3), and a harness that unpacked the object first would be measuring its own
translation. So `rows` gained `--args` and `--args-file`, with the same
`per-key` conflict group `op_subcommand` already had, so the canonical spelling
means the same thing on a read as on an edit.

**The grader.** `rows --json` returned `{"ok", "text", "hash", "path"}` — the
rendered markdown, inside a JSON string. `check_table_read_result` grades
`TableRows`'s five fields and deliberately never grades the renderer's string,
because a grader that matched rendered text would fail every read task if a
separator changed and could not tell a renderer bug that dropped a row from a
model that never asked for it. Parsing the text back would have reintroduced
exactly that.

So `rows --json` now carries the structure beside the string.
**This is not §6.1's deferred item.** What §6.1 defers is a model-facing
`format` *argument*, on the same reasoning §6.2 measured — an extra field is a
field the model fills in wrongly. It says in the same breath that the
structured/renderer split gives both for free at the call site, and the call
site is where this is. No schema changed, and the `text` field is byte-identical
to what it always was, so nothing a model reads moved.

### What was reused rather than transcribed, and the one thing that was not

Arm C's rule is that everything it shares with Arm B is *imported*. The read
path needed one thing that lived inside a function rather than beside it: the
`where` → `filter` rename, which `table_read_naive` needs because the scheme
publishes one word and the op takes another. It was inline in `armb.read_call`,
so it became `armb.read_args` and both arms now call it. A rename that drifted
between the arms would have put the difference in the harness and reported it as
a fact about the port.

`render_table_get` was split in the Rust so the CLI can have the structure and
the string from one read instead of two. The split is Rust-side only — the
oracle's is still one function — which is safe for the reason that makes it
worth stating at all: it adds no behaviour to compare. Every byte
`render_table_rows` returns reaches `render_table_get`, which `difftest.py`
runs 2724 times against the oracle, so a divergence introduced there fails
there. `difftest` reports all **89177** cases agreeing and `mutate.py`
**185/185** caught, unchanged.

### The coverage gap this opened, named

`difftest.py` drives the core through `cargo run --example oracle_cases`, **not
through the CLI**. Nothing it runs can see the JSON envelope, so `rows --args`
and the structured payload are covered by `crates/incise-cli/tests/cli.rs` or by
nothing at all. Two cases were added there: that `--args` and the flags produce
the same read, that a typed filter value now reaches the core's refusal rather
than being unspellable, that mixing the two spellings is a usage fault, and that
the structure equals `table_get`'s while `text` equals `render_table_rows`'s.

### What is still refused, and it is a different sentence now

`_check_supported` no longer refuses reads. It refuses `frontmatter-get`, and
the reason is the true one: that family has no Rust port, so there is no
subcommand to run — it is measured at Arm B only, by decision. The turns guard
was narrowed at the same time. It is about a divergence between the two arms'
*edit* results (`describe_change` against the renderer summary) and had nothing
to say about reads, but `family_of` files a `table-get` task under `table`, so
it would have caught one anyway. Read tasks are now excluded from it rather than
by it, which matters because "does the model reach for the read tool at all" is a
multi-turn question by definition.

**Superseded by F-frontport.** The reason was true and the guard built on it was
not: it matched `frontmatter-get`, the task file holds only `frontmatter-set` and
`frontmatter-delete`, and those went through to `apply_op` and graded
`malformed`. The family is ported and the guard is gone.


## F-frontport — the fourth family ships, and Arm C's 0/33 was never the model's

F-armcread's closing paragraph said `_check_supported` still refuses
`frontmatter-get` because "that family has no Rust port". That sentence was true
and the guard built on it was not. The guard matched on families whose name
starts with `frontmatter-get`, and `bench/tasks/frontmatter.json` contains none
— it is 9 `frontmatter-set` and 2 `frontmatter-delete`. So every edit call sailed
past the guard, reached `apply_op`, drew `unknown operation`, and graded
`malformed`. **Arm C scored 0 on the frontmatter family and reported it as a
failure of the model.** It is the same defect F-armcread found for the read half,
in the half F-armcread did not look at.

The fix is the port the guard was describing. `crates/incise-core/src/front.rs`
and `crates/incise-core/src/ops/frontmatter.rs` are the ports of `bench/mdfront.py`
and `incise_ops.py:2675-3250`; the crate and the oracle now name the same fifteen
ops in the same order, and `difftest.py`'s unknown-op exclusion is gone with the
divergence it described.

**The headline: `ceiling.py --arm c --tasks bench/tasks/frontmatter.json
--schemes front_naive,front_p,front_r` goes from 0/33 to 33/33 ideal calls.**
The before figure was measured by stashing the change, not asserted, which is
the method F-armcread used for its 0/6 → 6/6. Both numbers are about the
*executor*: an ideal call is the task's own recorded arguments, so 33/33 says the
binary can now run what the model was already being scored on, and says nothing
about any model.

### The port matches Arm B, which is the only bar it is allowed to clear

§7.4 makes Arm B's rates the bar a port must match rather than beat.
`armc.py --cross` pairs each recorded Arm B trial's grade against Arm C's:

| pool | trials | agree | differ |
|---|---|---|---|
| `armb_front_naive_v3.jsonl` | 110 | 110 | 0 |
| `armb_front_p_v3.jsonl` | 110 | 110 | 0 |
| `armb_front_r_v3.jsonl` | 110 | 110 | 0 |

330 of 330, including the 21 wrong and 2 malformed trials — a port that only
reproduced the correct ones would be a port that had quietly fixed something.
No GPU was spent: these are F-frontmatter's and F-frontread's recorded outputs
re-executed, so the rates remain theirs and are not restated here as new
evidence.

`READ_SUBCOMMANDS` had to grow a second field on the way. It mapped an op to a
subcommand and the grader read `out["rows"]`; `incise keys` returns a
`frontmatter` object, not rows, so a one-field table would have handed the
grader `None` for every frontmatter read — a bug with the shape of a model
failure, which is the shape this whole finding is about.

### Not a YAML parser, and the tests that hold it to that

`corpus/frontmatter/rich.md:37-43` is the specification, and it forbids the
obvious implementation: after `frontmatter-set build.jobs 8`, key order, the
leading comment, the inline comment on a sibling, two block scalar styles and one
quoted key must all be byte-identical. **A parse-and-serialize design passes
every differential case and fails that**, because the oracle would destroy the
same bytes in the same way. So each `Entry` records the pieces of its own line
and an edit rewrites one piece, and the claim lives in
`crates/incise-core/tests/invariants.rs` — where an implementation is checked
against a property rather than against its twin — and not in `difftest.py`.

Three suites, each answering something the other two cannot:

- **`difftest.py`: 107581 cases over 52 fixtures, all agree.** 7881 are
  frontmatter-specific (`describe_front` 6424, `frontmatter_get` 1307,
  `find_frontmatter` / `render_frontmatter` 52 each, `parse_path` 46), plus an
  unseparated share of `apply_op`. **5209 of the 6424 and 1170 of the 1307 are
  refusals**, which is the point rather than a gap: §5.3 makes the message the
  product, so a refusal generated only against the file it was written for has
  been read and not tested.
- **`mutate.py`: 212/212 caught, no survivors**, 27 of them new. Read by
  mismatch count rather than by total, the thinnest frontmatter margins are
  `front-parent-indent` at 2 and `front-comment-sq-escape` at 3.
- **`invariants.rs`: 35 tests, 6 new.** Set-then-delete is byte-identical;
  a set moves exactly one line; absent, empty and null stay three distinct
  states; TOML is refused while the other three families keep working on the
  same file; the read supplies what the summary omits; and the description
  names the key where `describe_change` cannot.

### What the tests found, which is the only reason to report their sizes

**One defect, in the port.** `by_path` returned the *first* entry for a repeated
key. Python's `{e.path: e for e in entries}` keeps the last, so a set on a
twice-written key must rewrite the second line; taking the first rewrites a line
the address does not name and leaves the effective value untouched.
`bench/synthetic/front-dupes.md` is the fixture that caught it, and it falsified
an over-strong assertion in `test_incise_ops.py` at the same time — that suite's
"one line moved" check compared against `e.line` instead of the line the
*address* resolves to, and had been true only because nothing in the corpus
writes a key twice. That is one assertion corrected in the oracle's test suite;
`incise_ops.py` itself did not move.

**Four coverage gaps, found by mutations that survived.** The first
`mutate.py -k front` run caught 21 of 25. All four survivors were the third row
of the blindness taxonomy — an input neither tree contained — and all four are
now closed by `bench/synthetic/front-escapes.md`, `front-absent-blank.md` and
`front-absent-crlf.md` plus two dispatch arguments:

- a backslash-escaped quote in a **value** meeting a `#`. `front-scalars.md` has
  one in a *key*, and that line has no `#`, so dropping the escape rule flips the
  quote state twice and lands back where it started.
- a quoted value containing a backslash. The existing case holds both characters
  the escaping touches and quotes neither — `" ` is not `: `, so the predicate
  says bare and the doubling never runs.
- a created key holding a bare `:`. A key is quoted on `:` and a value on `: `;
  every created key in the suite was clean, so the two predicates were
  indistinguishable.
- a document whose first byte is a newline. A created block omits its trailing
  blank line when the document already opens with one, and **no file in either
  tree opened with one**, in either line ending — the branch was unreached
  twice over.

The re-run is 27/27, the two extra being mutations the new fixtures made
reachable.

### Controls, and what was deliberately not done

The oracle did not move, so three things had to not move either, and did not:
`regrade_snapshot.py` is **identical over all 10072 recorded calls**,
`schematest.py` still reports **3 tools, byte-identical to the schemes they were
measured as**, and `git status --porcelain corpus/` is clean.

That third one is a decision and not an omission. `schema.rs` stays pinned at
three published tools so that **"should the read tool ship" remains a live
question** rather than one settled as a side effect of a port — and it is now
answerable on its own evidence, which it was not while the family existed only in
Python. `describe_frontmatter_change` also stays a sibling of `describe_change`
rather than being folded into it: the stated reason for the split has expired,
but folding is a behaviour change with its own `regrade_snapshot` enumeration,
not a port.


## F-compose — the shipping set has never been measured as a set

Every scheme in `armb.SCHEMES` publishes one tool or two. `scheme_a` publishes
three, and it lost. The product publishes a **set**: `schema.rs` ships three
today and would ship five once the frontmatter family is published alongside
the table read. Each of those five has a number, and every one of those numbers
was measured with that tool **alone in the request**.

So the question the ship decision actually turns on is not whether
`frontmatter_edit` works — `front_p` is 104/110 and the port reproduces it
(F-frontport) — but whether five tools in one request cost anything that one
tool does not. Nothing in this directory answers that. `headroom.py` cannot
price it either, and for an unusual reason: a composition is in the prompt of
*every* trial, so `k = n` and it is the opposite of underpowered — but no
recorded call reaches a five-tool prompt, so a reach survey has nothing to
count. It needs an arm, which is what this is.

### The instrument

`compose_5` publishes the five tools in the order `schema.rs` would, and does
it by **referencing** the winning schemes rather than copying them
(`armb.py`, after `front_r`): `scheme_f` + `list_g` + `section_g_hpath` +
`front_p` + `table_read_g`. A copy would let the composition drift from the
schemes whose numbers license it, and the claim under test is that these exact
five sit together.

One variable moves: **how many tools are in the request**. The task, its
fixture, its injected summary, its system prompt, its seed, the result shape and
the turn cap are all held at the task's own family. The control (`solo`) is the
same 48 tasks under their own adopted tool alone.

Two harness facts had to be fixed first, and both are the kind that would have
produced a number rather than an error:

1. **`prompt_of` selected the read-capable prompt from the scheme's toolset.**
   A scheme publishing `table_get` *beside* the edit tools would have handed a
   table **edit** task `SYSTEM_PROMPTS["table_read"]`, whose last line is
   *"Answer from what the tool returns and nothing else … do not edit the
   file."* The composition would have been measured under an instruction not to
   do the task, and scored as if the model had declined. The selection is now by
   scheme name (`READ_PROMPT_SCHEMES = {"front_r"}`), which is what was always
   meant: `front_r`'s result is the read tool *and* that sentence, measured
   together. The swap is inert — over the **247 distinct (scheme, task) pairs
   that appear in any recorded pool, zero change prompt.** The 34 pairs that do
   change are table-read schemes crossed with edit tasks, a combination never
   run and now answered correctly.

2. **No row recorded `--result-shape` or `--turns`.** `armb.jsonl` (scheme_f),
   `armb_lists.jsonl` (list_g) and `armb_read_g.jsonl` (table_read_g) predate
   S6/S14 and are single-turn; the v3 frontmatter pools and `s15_section_g_hpath`
   are not. Nothing in any of them says so — an absent `turns` field was the only
   clue, and that is an accident of when multi-turn landed rather than a record.
   `run()` now stamps both on every row. A pool that cannot say which condition
   it ran under cannot be the control for a later one, which is the whole reason
   the control below is re-run rather than read off disk.

Ceiling before any GPU time: **48/48 under `compose_5`** (6 tables, 10 lists,
15 sections, 11 frontmatter, 6 table-read), and 48/48 under the five solo
schemes. The executor is not what limits either arm.

### Pre-registered, before the run

Written here before any trial was run, and committed before the results existed:

> **Design.** 48 tasks × 10 trials = 480 paired trials per condition, paired on
> `(task_id, trial)`; seeds are the trial index, so the pairing is exact.
> `--turns 4 --result-shape delta` in **both** conditions. 4 because
> `section_g_hpath` was recorded at 4 and **10 of its 200 trials hit that cap
> still calling**, so a different cap would change them; frontmatter was
> recorded at 3 but **zero of its 330 v3 trials hit it**, so 4 is inert there.
>
> **Clap rule.** `solo` runs first. Two families have a comparable recorded
> pool and must reproduce: **`front_p` 104/110 = 94.5%** (CI 88.6–97.5) and
> **`section_g_hpath` trials 0–9, 130/150 = 86.7%** (CI 80.3–91.2). Tables,
> lists and table-read have no comparable pool — theirs are pre-S6 single-turn
> — so a shift there is the harness era and is **not** evidence about
> composition. If the two comparable families do not reproduce, nothing else in
> this run means anything.
>
> **Primary endpoint:** graded `correct` under `compose_5` versus `solo`,
> pooled, exact McNemar. **Prediction: no significant loss.** The five tools
> carry disjoint vocabularies, every task's summary names its own family, and
> the one measured multi-tool result that lost — `scheme_a` — lost to a
> *narrower* schema for that family, not to the presence of others.
>
> **Decision rule, fixed now.** p ≥ 0.05 pooled and no family losing more than
> 5 points → the composition holds and the two tools ship. A significant loss →
> nothing ships, and a third arm `compose_4` (the four edits, no `table_get`)
> localizes it to the fourth edit family or to the read. A significant **win**
> → still ship, recorded as a surprise rather than as a prediction confirmed.
>
> **Secondary:** per-family slices, and whether any trial calls a tool from a
> family the task does not belong to — the failure mode the composition is
> suspected of and the one `solo` cannot exhibit at all.

Caveat 21 applies and is not weakened by any of this: these trials are evidence
for the schemes they were shown.

### The control reproduced exactly, which is worth more than it usually is

Both comparable families came back **trial-for-trial identical** to their
recorded pools — `front_p` 104/110 with all 110 trials matching, and
`section_g_hpath` 130/150 with all 150 matching. Not "within the interval":
identical, outcome by outcome. The clap rule has never passed this hard before,
and it settles three things at once that would otherwise each be an assumption:

the server is deterministic at a fixed seed, `--result-shape delta` was indeed
what the v3 and S15 pools ran at, and `--turns 4` is inert for frontmatter
exactly as the zero-trials-at-cap check predicted.

It also means every difference below is the composition and nothing else.

### The prediction was wrong

**`compose_5` loses, and not marginally.** Pooled over all 480 paired trials:

| | correct | 95% CI |
|---|---|---|
| `solo` | 452/480 = **94.2%** | 91.7–95.9 |
| `compose_5` | 426/480 = **88.8%** | 85.6–91.3 |

31 trials correct only under `solo`, 5 only under `compose_5`, **McNemar exact
p = 1.29e-05**. The pre-registered prediction of no significant loss is refuted,
and the reasoning behind it — disjoint vocabularies, family-specific summaries —
did not survive contact.

> **Correction (F-terminal).** Every table in this finding was graded with
> `armb.grade_one`'s `unknown operation` branch still in place, which ended a
> trial on the one refusal class the model recovers from 71% of the time. That
> branch is gone and the pools are re-graded; the tables below are left as
> measured, with the post-regrade value stated beside each. Here it is
> **453/480 (94.4%) → 429/480 (89.4%), 28–4, p = 1.93e-05.** The loss is real,
> it is still overwhelmingly significant, and it is half a point smaller.

Per family, the loss is not spread evenly:

| family | `solo` | `compose_5` | discordant | p |
|---|---|---|---|---|
| lists | 100/100 | 100/100 | 0–0 | — *(trial-for-trial identical)* |
| tables | 60/60 | 57/60 | 3–0 | 0.25 |
| table-read | 58/60 | 57/60 | 3–2 | 1 |
| **frontmatter** | 104/110 = 94.5% | 95/110 = **86.4%** | 14–2 | **0.022** |
| **sections** | 130/150 = 86.7% | 117/150 = **78.0%** | 15–1 | **0.00098** |

Lists is completely immune — 100 trials, not one of them moved. The two families
that lose are the two whose tasks are hardest in the first place.

> **Correction (F-terminal), and it changes this table's shape rather than its
> size.** Post-regrade: **tables 60/60 → 60/60, 0–0** — tables joins lists as
> completely immune, in all three composed arms. **frontmatter 105/110 (95.5%)
> → 95/110 (86.4%), 11–1, p = 0.0063.** sections and table-read are unchanged.
> "The two families that lose are the two whose tasks are hardest" becomes
> literally true: sections and frontmatter, and nothing else.
>
> The two rows printed above with a `b` that does not reconcile with its own
> margins — sections 15–1 for a net 13, frontmatter 14–2 for a net 9 — are an
> erratum independent of the regrade, recorded under F-terminal. The p-values
> printed here are the ones the recomputed pairs give.

Three mechanisms, all visible in the calls rather than inferred:

1. **The discriminator gets dropped.** Six `compose_5` trials emitted
   `table-None` — `action` omitted entirely — against one in the whole 480-trial
   control. Every one of the three tables losses is this.

   *(F-terminal: `action` is fused into the next key rather than omitted, and
   all three of those trials go on to produce the correct document in a later
   turn. The mechanism is real and still worth fixing; it costs a turn, not an
   outcome, which is why the tables row above becomes 0–0.)*
2. **The model keeps going.** 1.18 calls per trial under `solo`, 1.27–1.34 under
   the composed arms. Of the 31 lost trials, 16 made strictly more calls under
   `compose_5` than under `solo`, and 8 of those went from one call to two.
3. **Cross-family calls, which `solo` cannot exhibit at all.** 14 of them:
   `list_edit` on section and frontmatter tasks (9), `table_get` on frontmatter
   tasks (4), `table_edit` on a frontmatter task (1). Zero under `solo`, by
   construction.

### Localizing it: the read is free, and so is the fourth edit tool

The pre-registered rule bought one arm on a loss, and `compose_4` — the four
edits, no `table_get`, on the four edit task files — says the read is not what
costs:

| (420 paired trials, edit families only) | correct | vs previous |
|---|---|---|
| `solo` | 394/420 = 93.8% | — |
| `compose_4` | 372/420 = 88.6% | 31–9, **p = 0.00068** |
| `compose_5` | 369/420 = 87.9% | 13–10, p = 0.68 |

Adding `table_get` on top of four edit tools moves nothing. Whatever the
composition costs, it is not the read tool.

> **Correction (F-terminal).** Post-regrade: `solo` 395/420 (94.0%),
> `compose_4` 374/420 (89.0%) at **29–8, p = 0.00075**, `compose_5` 372/420
> (88.6%) at **11–9, p = 0.82**. The read is still free, and by a wider margin
> — 11 against 9 out of 420.

### The pre-registration asked the wrong question, and the answer flips

`solo` is one tool. **The product ships three.** `schema.rs` has published
`table_edit`, `list_edit` and `section_edit` together since they were adopted,
and that set of three has never been measured either — each of the three has a
number from a scheme that published it *alone*. So `solo` is not the status quo.
It is a condition the product left behind before any of this started, and the
comparison that was pre-registered is one-tool against five, which is not a
choice anyone is making.

The ship decision is **three against five**. That arm is `compose_3`, run on the
three shipping families. It is **post-hoc** — added after seeing the
`compose_5` result, not pre-registered, and labelled as such wherever it is
quoted:

| (310 paired trials, the three shipping families) | correct | vs previous |
|---|---|---|
| `solo` (one tool) | 290/310 = 93.5% | — |
| **`compose_3`** (ships today) | 276/310 = **89.0%** | 15–1, **p = 0.00052** |
| **`compose_5`** (ships after) | 274/310 = **88.4%** | 6–4, **p = 0.75** |

**The product is already paying it.** Publishing three tools instead of one
costs 4.5 points, p = 0.00052, and that cost is in production now and has been
since the first family shipped. Going from three to five costs **6 trials
against 4 out of 310, p = 0.75** — nothing that 310 trials can see.

> **Correction (F-terminal), and this is the headline number that moves.**
> Post-regrade: `solo` 290/310 (93.5%), **`compose_3` 280/310 = 90.3%, 11–1,
> p = 0.0063**, **`compose_5` 277/310 = 89.4%, 6–3, p = 0.51** against
> `compose_3`. **Publishing three tools instead of one costs 3.2 points, not
> 4.5** — a quarter of the measured cost was one refusal class graded as
> unrecoverable. Every conclusion in this section survives: the step from one
> tool to more than one is the step that costs, it is significant, and the
> fourth and fifth tools are still free. What changes is the size of the bill
> and which families it lands on.

The mechanism counts say the same thing. Cross-family calls: 0 under `solo`, 9
under `compose_3`, 16 under `compose_4`, 14 under `compose_5`. Calls per trial:
1.18, 1.32, 1.34, 1.27. The step that costs is the step from **one** tool to
more than one. The fourth and fifth are free.

### What this means for the two open items, and for `schema.rs`

- **The pre-registered rule says nothing ships.** It is honoured as written: the
  rule was "a significant loss under `compose_5` → nothing ships", `compose_5`
  lost, and the arm that reverses the reading is post-hoc. Overriding a
  pre-registered rule on a post-hoc endpoint is a decision to be taken openly,
  not absorbed into a write-up.
- **The post-hoc arm is the one that matches the decision**, and it says the two
  tools are free to add. Both readings are recorded here rather than one being
  presented as the result.
- **`schema.rs`'s contract sentence is narrower than it reads.** "The schema a
  model is shown in production is the schema the number was measured on" is true
  of each tool's *text* and false of the *condition*: every number was measured
  with that tool alone, and the product has published three at once the whole
  time. The 4.5-point gap between `solo` and `compose_3` is the size of that
  gap, and it was invisible until something went looking for it. This is a
  finding about what already ships, not about what might. *(F-terminal: 3.2
  points, p = 0.0063. Smaller, still there, still unguarded by anything.)*
- **If the family does ship, its rate is 86.4%, not 94.5%.** §7.4 makes Arm B's
  rate the bar a port must match — but the bar is the rate in the condition the
  tool ships in, and for `frontmatter_edit` that is `compose_5`'s 95/110, not
  `front_p`'s 104/110. *(F-terminal: 86.4% against 95.5%, `front_p` being
  105/110 after the regrade. The shipping rate is the one that does not move,
  so the gap widens by a point.)*

Pools: `bench/results/compose_{solo,3,4,5}_*.jsonl` and their `_graded`
siblings, 1690 trials across four arms.

### The decision taken, and the fact that it overrides the rule

**Both tools ship.** `schema.rs` publishes five. This **overrides the
pre-registered decision rule**, and the override is recorded here rather than
justified away, because a pre-registration that can be reinterpreted after the
fact is not one.

The case for overriding is that the rule's endpoint does not describe any
decision anyone can make. It compared one tool against five; `schema.rs` has
published three since the first family shipped and cannot go back to one, so no
available action follows from that comparison losing. The endpoint that matches
the decision is three against five, and it is 6–4 of 310, p = 0.75. The
pre-registration named the wrong contrast, which is a defect in the
pre-registration and not a result.

What that argument does **not** license, stated because it is the tempting
over-read: it does not retire the loss. `compose_5` really is 5.4 points below
`solo` at p = 1.3e-05, and the ship does not recover any of it — it establishes
that the fourth and fifth tools are not where it is spent. The loss is the third
tool, and it was already being paid before this run. Shipping is a decision that
the marginal cost of two more tools is zero, not a decision that the
compositional cost is zero. *(F-terminal: 5.0 points, p = 1.9e-05. The
sentence stands word for word.)*

Three things follow, and all three are done rather than promised:

- `schematest.ADOPTED` grows to five, and the `key` and `filter` entries come
  off `ALLOWED_BACKTICKS` exactly as their own comment predicted. Both words
  were load-bearing: with the exceptions deleted and `ADOPTED` rolled back to
  three, the check fails on both, so they are now carried by the schema rather
  than excused.
- `schema.rs`'s contract sentence gains its second half, and says which half is
  guarded. `schematest.py` watches each tool's text; nothing watches the set,
  and its docstring now says so. A sixth tool would pass that check on the day
  it is added while being, again, unmeasured as a set.
- The plugin registers `frontmatter_edit` and **declines `table_get`**, keeping
  `md_rows`. Not a claim that `md_rows` is better — `table_get` is the measured
  text and `md_rows` is not measured at all — but publishing one op under two
  argument spellings is the shape L3 and the `view`-enum incident both charge
  for, and a read routed through `_handle_edit` would ask `safety.check_write`
  for write permission before raising out of `normalize`. Which of the two reads
  should survive is a live open item and wants a number.

  **Reversed by F-rows, and it did not want a number after all.** `md_rows`
  could not address a table sharing its heading with another, which one corpus
  file and one already-graded task settle without a run. The first reason above
  was right about the shape and wrong about which of the two to keep; the second
  was a property of the routing, not of the tool, and `READ_SUBCOMMAND` now
  decides it.

**`frontmatter_edit` ships at 86.4%, not 94.5%.** §7.4 makes Arm B's rate the
bar a port must match; the bar is the rate in the condition the tool ships in,
and that is `compose_5`'s 95/110, not `front_p`'s 104/110. The same correction
applies to every other published tool and has not been made for them, because
`compose_5` is the only arm that has ever run the shipping composition.
*(F-terminal: 86.4% against 95.5%. The shipping rate is the one that does not
move — `compose_5`'s 95/110 is unchanged — so the gap this paragraph is about
widens by a point rather than narrowing.)*


## F-rows — the tool that actually shipped could not address three of one file's four tables

`plugins/hermes` registered eight tools. Seven came from `incise schema`, where
`bench/schematest.py` compares them byte for byte against the schemes that won
their comparisons. One did not: `md_rows`, hand-written in `schema_cache.py`,
the same `table-get` op behind a `table` that was a plain string —

> The heading the table sits under, spelled as `md_tables` shows it.

— rather than the `{"heading": …, "ordinal": …}` object every other table tool
in the tree takes. It was chosen on shape, over `table_get`, and recorded at the
time as *"a judgement call, not a derivation"*. This is the derivation, and it
goes the other way.

### One corpus file settles it, and no GPU was spent

`corpus/tables/multiple-per-section.md` puts three tables under one heading.
`md_tables` — the plugin's own read, the one whose description says to call it
*"before a `table_edit` to get the exact `table` heading"* — prints them like
this:

```
  heading "Multiple tables per section > Environments"  ordinal 0  labelled "Production hosts"
  heading "Multiple tables per section > Environments"  ordinal 1  labelled "Staging hosts"
  heading "Multiple tables per section > Environments"  ordinal 2  labelled "Scratch hosts"
```

A model handed those three lines has exactly one way to distinguish them, and
`md_rows` published no argument that could carry it. The heading alone refuses:

```
ambiguous: 3 tables under "Environments". Pass an ordinal.
  Candidates: ordinal 0 ("Production hosts") …
```

**A refusal naming a remedy absent from the schema that provoked it.** That is
F-rowarg's defect with the sign reversed — there, a message advertised an
argument the product refuses; here, a message named the one argument the schema
did not declare. §5.3 makes the refusal the product, and this is the worst case
it admits: the sentence is correct, actionable, and unreachable.

All three tables were unaddressable, not two: the ambiguity is in the
heading, so it refuses for every table under it. `"2"` does not help — it is read as
a heading, and answers `no table under heading "2"`.

### The bound, which is the whole result

`bench/tasks/tables_read.json` has a task for exactly this shape,
`get-ordinal-table`, whose `ideal_call` is `{"heading": "Environments",
"ordinal": 1}`. Under `md_rows` it is not merely hard, it is **unreachable**:
`check_table_read_result` grades a read on the structured report, every read
`md_rows` can spell either refuses or names the wrong table, and there is no
temperature at which a missing argument appears. Its ceiling on that task is
0/10.

`table_read_g` answers it **10/10** (`armb_read_g_graded.jsonl`), and did so
again in both arms of F-compose. So the paired comparison is bounded before it
is run: `b ≥ 10` discordant pairs fall against `md_rows`, and `c ≤ 2`, because
`table_read_g`'s only two failures in 60 are `misreported` on
`get-filter-two-columns`.

| | b | c | exact McNemar |
|---|---|---|---|
| every ordinal trial lost, nothing recovered | 10 | 0 | p = 0.00195 |
| and `md_rows` wins both of `table_read_g`'s failures | 10 | 2 | p = 0.0386 |

The second row is the most favourable arithmetic that exists for the shipping
tool, and it is still significant. **An hour of GPU could not have changed the
decision, so it was not spent.** `headroom.py` prices a re-measurement by what
it could return; this is the same question asked of a *new* arm, and what
settled it is `ceiling.py`'s question — can the schema express the right answer
at all — rather than a model's answer to it.

### The narrowing was in the handler too, and cost a second refusal

`_handle_view` did not pass `md_rows`'s arguments to the binary. It pulled
`table` out as a string, flattened each `filter` entry to `COLUMN=VALUE`, and
answered a missing `table` itself:

> md_rows needs `table`, the heading the table sits under. `md_tables` lists them.

`crates/incise-cli/src/main.rs` had already written down why that door is wrong,
at `rows_subcommand`: `rows` takes `--args` precisely so that *"a harness
translating a model's argument object into flags would be pre-validating it —
and measuring its own translation rather than incise's answer."* The plugin's
own README claimed **No pre-validation** in the same breath; that paragraph was
written about the edit path and was false of the read path.

What the pre-validation replaced is worse than the principle suggests. The
core's refusal for a read with no address is:

```
table address required: this file has 4 tables.
  Candidates: "Multiple tables per section > Environments" ordinal 0; …
```

— every table in the file, with the ordinals. The plugin answered first, with a
shorter sentence pointing at another tool.

### What was done

`md_rows` is retired. `table_get` is registered, routed to the read handler by
`schema_cache.READ_SUBCOMMAND` — so it gets `safety.check_read` and never the
write guard, which was the other reason it had been declined — and its arguments
go to the binary as `--args`, unread, the same door the edits use.
`NOT_REGISTERED` is now empty and is still asserted in both directions, since
the check that the registered set matches the published set would also pass if
the binary stopped publishing a tool.

`table_get` ships with its copy-paste wart intact: a `table` described as *"Which
table to edit"*, in a read. Rewording measured schema text is a behaviour change
with no number behind it. The open item stays open.

> **Closed since, by F-wart.** Not because a number arrived but because it was
> shown that none can: the arm's gain is bounded at zero, so the phrase is
> permanent rather than pending.

The guard that generalizes is a shape, not a warning: **a schema written in the
plugin may take nothing but `path`.** A hand-written argument is one nothing
compares against the op it reaches. The three reads that remain — `md_tables`,
`md_lists`, `md_outline` — enumerate rather than address and take `path` alone,
so the rule costs nothing today and is what `test_plugin.py` asserts. Anything
that takes arguments has to come from `incise schema`, where `schematest.py` is
watching it.

### Why nothing already in the tree caught this

Two independent reasons, and both are worth keeping:

1. **`schematest.py` only sees published schemas.** Its `ALLOWED_BACKTICKS`
   audit is exactly the invariant that was violated — a refusal may not
   recommend an argument the shipping schema does not declare — but
   `declared_arguments()` reads `incise schema`, and `md_rows` was never in it.
2. **Even in scope it would have missed.** The remedy here is prose. `Pass an
   ordinal.` carries no backticked token, and the audit keys on backticks. A
   lexical check cannot see a capability named in English.

### What this does not license

It is not a finding that `md_rows` was worse at the five tasks it *could*
express. That was never measured and now never will be: the two schemas differ
in the address shape and in two paragraphs of description, so a rate comparison
would not have localized anything anyway. The claim is narrower and does not
need a rate — one tool can express an address the other cannot, and the corpus
contains that address.

Nor is frequency the argument. One task in six provokes it, and a corpus of
documents with no repeated headings would show nothing. Three tables under one
heading with captions above them is ordinary release-notes markdown, and the
tool is shipped against documents nobody has surveyed.

**The generalizable part is the order of the checks.** `md_rows` shipped for 37
commits, passed every structural test in `test_plugin.py`, and was the *only*
tool in the plugin a live model could reach that had never been compared to
anything. The unmeasured tool is the one to look at first, and "does it pass the
tests" is not the question — `md_rows` passed all of them.

## F-remedy — the sweep for F-rows' defect, and the different one it found

F-rows was found by accident. Its defect has a shape — **a refusal naming a
remedy the tool that provoked it cannot perform** — and a shape can be swept
for on purpose, which is what this is. The sweep's headline result is negative,
and the negative result is most of its value: **no second instance of F-rows'
defect exists in the shipping five.** What it did turn up is the same sentence
one level up, about *actions* rather than *arguments*.

### Method, and what it can and cannot see

Two passes, because neither alone is sound.

**Empirically**, `difftest.py`'s own generator supplies the adversarial
arguments: 83526 of its 107581 cases are `apply_op` calls, and replaying them
through `incise_ops.apply_op` yields **4990 distinct refusals across the
fourteen published ops** (5080 counting `table-realign` and the deliberately
malformed op names, neither of which any tool can reach). `table-get` is not
among them — it is off `apply_op` by design, the same structural blind spot
`refusal_pool.py` and `headroom.py` both record — so it was swept separately
through `armb.read_call`, every corpus and synthetic table against every
`difftest.ARG_VALUES` entry as address and as filter: **958 more**. 5948 over
what ships.

**Statically**, because a refusal's own words have to be separated from the
document's. Refusals quote the file back — headings, list items, column names —
and the corpus contains the words *table*, *list* and *section*, so a scan of
rendered messages drowns. The literal segments of each f-string, holes blanked,
are the tool's own vocabulary; this is the discipline `schematest._backticked`
already uses, extended per-op by walking the call graph out of the `OPS` dict.

The per-tool attribution is the part that matters, and it is what
`schematest.py` does not do. Its `declared_arguments()` is the **union** over
all five adopted schemes, so `ordinal` counts as declared because `table_edit`
declares it — and `md_rows`, which did not, would have passed. Run per-tool with
`md_rows`'s vocabulary restored (`path`, `table`, `filter`), the sweep flags
`ordinal` and `heading` on `table-get` and flags nothing on the five that ship.
That is the check discriminating on the one case whose answer is already known,
which is the only evidence a sweep like this can offer about itself.

### The negative result

Nothing. Every backticked and `key=value` remedy reachable from each of the five
tools is declared by that tool. The bare-English class — the class that catches
`Pass an ordinal.` — is too noisy to be a lint: `text`, `match`, `before`,
`level`, `value` and `column` are all ordinary English *and* argument names, and
every hit was the English one. `overwrite=true` and `subtree=false` flag only
because the boolean is not a declared token; both properties are declared.

**No lint was added, and that is deliberate.** F-rows' class is already closed
upstream of where a lint would sit: a hand-written schema may take nothing but
`path`, which `test_plugin.py` asserts, so the plugin can no longer publish an
address at all. A second check keyed on the same defect would be a check that
cannot fire.

### What it found instead: a remedy the product cannot execute

Six refusals in the tree instruct a change to the **document** rather than to
the argument object. Three are reachable on a file that exists here:

| refusal | reachable on | remedy | performable? |
|---|---|---|---|
| `the column "X" appears N times in this table's header, so it does not identify one cell.` → *"Rename one of them in the document, then retry."* | `table-update-cell`, `table-delete-row`, **`table-get`** | rename a column header | **no** |
| `this section mixes CRLF and LF line endings, so there is no convention to match.` → *"Normalize the section's line endings first, then retry."* | `section-append`, `-insert`, `-replace-body` | rewrite line endings | **no** |
| `refusing to insert "…": at line N it would land inside a fenced code block that is never closed…` → *"Close the block first, or edit the section's body instead."* | `section-insert` (19 distinct) | close a fence **or** edit the body | **partly** — the second clause is `section_edit` `action=replace-body` |

The other three — the table's line endings, the table's indentation, the list's
line endings — are not provoked by any of the 83526 generated cases and not by
any corpus or synthetic file. They are the same sentence on a branch nothing in
the tree reaches.

Both of the unperformable ones are byte-identical in the shipping core
(`ops/table.rs:304`, `ops/section.rs:461`), so this is the product and not the
oracle.

**No shipping tool can do either thing, and that is checked rather than
assumed.** `table_edit`'s action enum is `add-row | update-cell | delete-row`;
`where` selects among body rows, so `update-cell` cannot reach the header at all
— on the duplicate-column fixture it answers `no row where Value="Name"`.
`table-realign` is the one op in `OPS` no published action reaches, and it is
itself what refuses on mixed endings. Nothing in the five touches line endings.

The sharpest case is the read. `table_get` draws the rename refusal on
`bench/synthetic/duplicate-columns.md`:

```
the column "Name" appears 2 times in this table's header, so it does not identify one cell.
  Columns: Name | Value | Name
  Rename one of them in the document, then retry.
```

Under `table_read_g` — the scheme this tool was measured as, which publishes
`table_get` alone — the remedy is not merely absent from the tool that provoked
it. It is absent from **every tool the model has**. And a remedy that *is*
expressible goes unsaid: `filter` is optional, and dropping it returns every row
positionally, which is precisely the shape `table_get` already returns for the
stated reason that a table may legally repeat a header.

**Where the named remedy actually routes the model.** A model holding only these
five tools and told to normalize a file's line endings has one move left, which
is to rewrite the document as free text. That is Arm A: 19%, with 28% of touched
rows silently lost. The refusal is correct to refuse and it points at the one
behaviour the whole project exists to replace.

### Not fixed here, and what it would take

Rewording a refusal is a behaviour change with no number behind it — the same
rule that ships `table_get`'s *"Which table to edit"* wart intact. Unlike
F-rows, there is no ceiling argument available: no schema is unable to express
anything, so `ceiling.py` has nothing to decide and the question is what a model
does with a better sentence.

`headroom.py` prices it as a new candidate and returns **UNTESTED**: across all
five task files, zero adopted trials reach the branch, and the adopted schemes
were never run on a provoking task because **no task fixture provokes one** —
none of the seventeen has a repeated header or mixed line endings. This is
F-address's failure rather than F-framing's: a task set to build, not a result.

### The instrument, built — and the half of it that cannot be built

`bench/tasks/tables_read_remedy.json`, three `table-get` tasks on
`bench/synthetic/duplicate-columns.md`. `ceiling.py` is **3/3** under
`table_read_g`, which is the pre-flight gate.

The fixture is reused rather than written fresh, and the reason is worth
stating: `difftest.py` globs both `corpus/` and `bench/synthetic/`, so *any*
new document invalidates its cached expected-output snapshot and costs a full
recompute. An existing fixture that already has the shape costs nothing.

What the three tasks measure, stated so the rate is not over-read. The expected
answer for the first two is the **whole table**, because no filter can narrow a
table addressed by a repeated column — so `unfiltered` cannot fire and the
correct-rate is not a filtering score. The contrast is recovery, and it is an
outcome rather than a turn count, which is the distinction F-framing had to make
the hard way:

| trial does | grade |
|---|---|
| filters on the repeated column, follows the named remedy, retries | `op_error` |
| filters, then drops `filter` and reads both rows | `correct` |

Both halves verified rather than assumed: a filtering call grades `op_error`,
and the ideal call grades `correct`. `get-repeated-control` filters on `Value`,
which is *not* repeated, so it never reaches the branch — without it, a drop on
the other two could be a model that stopped filtering rather than one that could
not.

**The section half is not a wording arm and cannot be made one.** Building it
is what showed this. A task asking for an append to a mixed-ending section has
a ceiling of **zero** — `section-append` and `section-replace-body` both refuse
on `corpus/hazards/mixed-endings.md`, at any argument — so it fails the
pre-flight gate by construction, and no rewritten sentence changes that. The
refusal is terminal for those two ops and only those: `section-delete` and
`section-rename` succeed on the same section. So the section instance is a
**capability** question — should these ops pick a convention instead of
refusing? — and the table instance is the only one a description arm can reach.
Recorded here rather than left as an empty task file.

> **Wrong, and the fixture is why — F-provoke.** The ceiling is 3/3, not zero.
> `section-delete` is the one body-touching op that does not call
> `_section_eol`, so deleting the section and re-inserting it against a
> uniform-ending sibling performs the named remedy in two calls, at the price of
> retyping the body. "At any argument" was true of
> `corpus/hazards/mixed-endings.md`'s root section — whose span is the whole
> document, so deleting it deletes everything — and false of its three
> subsections, all of which append fine. Testing the claim against the only file
> that existed, rather than against a fixture built for it, is what let it
> stand. `bench/tasks/sections_mixed_endings.json` is the arm this paragraph
> says cannot exist. What survives is narrower and still true: *unperformable*
> holds for any single op and fails for the tool set.

It shares an arm with the *"Which table to edit"* item if either is ever run:
both are `table_get` description text, both want `table_read_g` on the same six
tasks and seeds, and headroom's one-sided rule applies to both — a description
reaches every trial, so `k` bounds the gain and nothing bounds the loss.

> **Two errors in that paragraph, found by F-wart.** The sharing no longer
> holds: the *"Which table to edit"* item is closed, and closed as unmeasurable
> rather than as measured. And this half was never description text — the
> rename remedy is a refusal in `incise_ops.py`, which is why `headroom.py`
> classifies this candidate `executor`-side and the one-sided rule does **not**
> apply to it. `k` bounds it in both directions, which is the better position of
> the two and was given away by a sentence written in a hurry.

### Pre-registration: the control arm, before any reworded sentence

Written before the run, and not edited after it.

A reworded refusal is the treatment, and there is no case for spending GPU on a
treatment before knowing what the branch costs. So the first run is the **shipped
sentence on the built instrument** — one arm, no contrast, which is the F-realign
discipline of pricing the gain before buying it.

> **Condition.** `bench/tasks/tables_read_remedy.json`, 3 tasks × 10 trials =
> **30**, `--scheme table_read_g --turns 4 --result-shape delta`. Those are the
> conditions `compose_solo_tables_read.jsonl` records for this exact scheme,
> which is the most recent pool it was run in; the turn cap has to exceed 1 or
> recovery is unmeasurable by construction. Pre-flight `ceiling.py` is **3/3**.
>
> **What it returns that nothing else can.** `headroom.py` says **UNTESTED at
> k = 0** for this candidate — not "no effect", but "no recorded trial has ever
> reached the branch", because no fixture in any task file repeats a header
> name. This run replaces that with a real `k` and a real recovery rate.
>
> **Prediction.** `get-repeated-control` filters on `Value`, which is not
> repeated, and should land at or near 10/10 — if it does not, the fixture and
> not the sentence is what the other two tasks are measuring. The two provoking
> tasks draw the refusal and their only performable move is to drop `filter`,
> which the sentence does not name; they are predicted to land **below** the
> control. No rate is predicted for them: three prior findings in this file
> talked themselves into one and two were wrong.
>
> **Decision rule, fixed now.**
>
> * **Both provoking tasks ≥ 9/10** → the sentence is a §5.3 defect the model
>   routes around. The most a rewording could buy is ≤ 2 of 20, below the floor
>   of 6, so **no treatment arm** — the item closes as priced, the way F-action
>   just did, and the wording stays as measured.
> * **Recovery below that, with k ≥ 6 trials drawing the refusal** → a treatment
>   arm is powered. Pre-register the reworded sentence and run it paired on task
>   and seed, and only then.
> * **The control itself below 9/10** → the instrument is measuring the fixture.
>   Nothing about the refusal is claimable and the task set needs rebuilding.
>
> Both provoking tasks expect the **whole** table, so `unfiltered` cannot fire
> and this is not a filtering score. It is recovery, as an outcome and not a
> turn count.

### The result: the sentence is terminal, 10 times out of 10

`bench/results/armb_remedy_read_g.jsonl`, run at the pre-registered condition.

| task | reaches the branch | correct |
|---|---|---|
| `get-repeated-control` — filters on `Value`, not repeated | no | **10/10** |
| `get-repeated-both` — question names no cell, so no filter is attempted | no | **10/10** |
| `get-repeated-name` — question names a cell under `Name`, which repeats | **10/10** | **0/10** |

The control passes its gate, so the fixture is not what the third row measures.

**Every one of the ten drew the refusal on its first call and then stopped.**
Not one retried without `filter`. The shape is identical in all ten: a
`filter: {"Name": "b"}` call, the rename refusal, and then a turn of prose to
the user saying the question cannot be answered —

```
I cannot answer your question because the table "Duplicate columns > Repeated
header" has duplicate column names ("Name"), which prevents me from identifying
specific cells within it.
```

The model had three turns left and used none of them. It did not invent a
rename; it did not reach for a tool it does not have; it read a correct refusal,
believed it, and reported the remedy as impossible — which, for the toolset it
holds, it is.

**This is not a model that gives up after a refusal.** The internal control is
in the same pool. `get-repeated-both` made an address error twice
(`table: "Key"`, then `{"heading": "Key"}`), drew a refusal that names something
it can do, retried with the full heading path, and answered — 10/10 on the
harder question, on the same fixture, in the same run. The difference between
0/10 and 10/10 is whether the sentence named a move the caller could make.

And the answer was available the whole time. `ceiling.py` is 3/3: the ideal call
for `get-repeated-name` is the same call `get-repeated-both` makes, `filter`
omitted. `table_get` returns a duplicate-header table positionally, for the
stated reason that GFM permits one. The tool could answer; the sentence stopped
it.

**Under the pre-registered rule this licenses the treatment arm.** k = 10 trials
reach the branch, above the floor of 6, and recovery is 0/10 rather than the
≥ 9/10 that would have closed the item. A reworded sentence that names the
performable remedy has a ceiling of 10–0, p = 0.00195, against a control arm
that is now on disk. The rewording itself is not written here: it is a §5.3
change to a sentence shipping in `ops/table.rs` as well as the oracle, and
F-action's line applies to it — the core may name the argument it *received*,
because that is quoting its input, and may not name the tool that sent it.

`headroom.py`'s **UNTESTED at k = 0** for this candidate was an artifact of the
survey and not of the tree, and pricing this run exposed it. `replay` skipped
read ops — `table-get` is off `apply_op` by design, so feeding it there
manufactures `unknown operation` — and yielded `error=None`, an undercount its
own docstring called safe *"because the verdict is already UNTESTED at k=0"*.
That held only while no candidate's branch lived behind a read. This one's does,
and it is the sharpest instance: the survey still said UNTESTED with the 10/10
pool on disk. `replay` now executes reads through `armb.read_call`, which
returns the refusal the model actually read, and the verdict is

```
POWERED: k=10, best achievable p=0.0020 ... reaches significance only if the
effect is near-total.
```

arrived at by a route entirely independent of the grader — which is the
agreement F-dupcol set as the standard. The section half stays unpriceable, for
the capability reason above.

### What this does not license

Frequency is not the argument here any more than in F-rows, but it is not
nothing either: the rename refusal needs a table that repeats a header name, and
**no file in `corpus/` has one** — the only instance in the tree is a synthetic
fixture written to test exactly this. A finding whose only witness is a fixture
built for it should be read as a defect in the sentence, not as a measured cost.

Nor is it a claim that refusing is wrong. All six refusals are correct: the
document really is in a state the op cannot safely edit, and B6 and F-pipes are
both findings about what happens when incise proceeds anyway. §5.3's claim is
narrower and survives — the sentence is the product, and a correct refusal whose
only named remedy is outside the toolset is the case §5.3 is worst at.

### Pre-registration: the treatment arm, and why only one of four sentences moves

Written before the sentence was changed and before the run, and not edited after
either.

**The remedy has to be argument-specific, because there is no remedy that is
performable for all four callers.** `_check_unambiguous` is reached from four
places, and what the caller can do about it differs at each:

| reached from | is a performable move available? |
|---|---|
| `filter` (`table-get`) | **yes** — omit it and read every row; that is `ceiling.py`'s ideal call |
| `where` (`update-cell`, `delete-row`) | yes in principle — select on a column whose name appears once |
| `values`, keyed (`add-row`) | yes — send it as an array in column order, which the guard is already scoped to allow |
| `column` (`update-cell`) | **no.** Nothing addresses a repeated column, so renaming really is the only way out and the shipped sentence is right |

So the shipped sentence is not uniformly wrong. It is wrong for one of the four
and correct for at least one other, which is why the change is scoped to a
single call site.

> **What changes.** The `filter` call site only. `_check_unambiguous` takes an
> optional remedy line; three of the four callers pass nothing and their
> messages stay byte-identical to what was measured. The new line is
>
> ```
>   Omit `filter` to read every row, and pick the one you want from the result.
> ```
>
> The diagnosis above it does not move. F-action's line holds: this names
> `filter`, an argument the core *received*, and does not name the tool that
> sent it.
>
> **Why not the other three.** `headroom.py` reaches them **0 times in 2071
> recorded trials** — no fixture provokes a repeated header through `where`,
> `values` or `column`. Rewriting those is an unmeasured §5.3 change riding
> along on a measured one, which is the thing this file keeps refusing to do.
> They go on the open list with the wording above recorded, not into this diff.
>
> **Both executors move together.** `bench/incise_ops.py` and
> `crates/incise-core/src/ops/table.rs` hold this sentence byte-identically and
> `difftest.py` compares them, so a one-sided edit is a failing build rather
> than a silent divergence.
>
> **Condition.** `bench/tasks/tables_read_remedy.json`, 3 tasks × 10 trials =
> **30**, `--scheme table_read_g --turns 4 --result-shape delta` — the
> pre-registered control's condition exactly, paired on `(task_id, trial)`
> against `bench/results/armb_remedy_read_g.jsonl`, which is already on disk.
> No new control is run: this is an **executor**-side change, so a trial that
> never draws the refusal replays identically and `k` bounds the result in both
> directions. That is the F-wart asymmetry used in the favourable direction for
> once.
>
> **Blast radius, stated in advance.** The 10 reachable trials are all
> `get-repeated-name` under `table_read_g` and every other pool is 0.
> `regrade_snapshot.py` is expected to move **those calls and nothing else**; if
> it moves anything else, the scoping is wrong and the run is void.
>
> **Prediction.** `get-repeated-name` goes from 0/10 to at or near 10/10. The
> two non-provoking tasks do not move at all — they never reach the branch, and
> under an executor-side change that is a guarantee rather than a hope, so any
> movement there is a bug in the scoping and not a result.
>
> **Decision rule, fixed now.**
> - **`get-repeated-name` improves, p < 0.05** (needs ≥ 6 of the 10 to flip) →
>   the sentence ships in both executors, and §5.3 gains its first *measured*
>   remedy rewrite rather than an argued one.
> - **p ≥ 0.05** → reverted in both executors, and recorded. A performable
>   remedy the model does not take is a more interesting result than the defect
>   was, and it is not an argument for keeping the sentence because it reads
>   better.
> - **Either non-provoking task moves at all** → void, scoping bug, nothing is
>   claimed from the run.
>
> **Caveat 21 applies and is stated in advance**, with the sharper form F-remedy
> already recorded: no file in `corpus/` repeats a header name, so the only
> witness is a fixture written for this. That makes it evidence about the
> sentence, not a measured cost of shipping it.

### The result: 0/10 → 10/10, one call apart, and an instrument that could not see it

Run 2026-09-17. `bench/results/remedy_treat_read_g.jsonl`, paired against the
control already on disk. Both arms `--scheme table_read_g --turns 4
--result-shape delta`, the condition recorded in the control's own rows.

| task | control | treatment |
|---|---|---|
| `get-repeated-name` | **0/10** | **10/10** |
| `get-repeated-both` | 10/10 | 10/10 |
| `get-repeated-control` | 10/10 | 10/10 |

Paired on `(task_id, trial)`: both correct 20, neither 0, only control 0, **only
treatment 10**. McNemar exact **p = 0.001953**, which is `2**(1-10)` — the
floor for 10 discordant pairs, so this is the largest effect the design could
have produced. Branch one of the decision rule fires: **the sentence ships in
both executors**, and §5.3 has its first measured remedy rewrite.

Two routes agree on the number, per the F-dupcol standard: `stats.py --compare`
and a direct count over the graded rows both give 10-0 of 30.

**The mechanism is the sentence, and nothing else.** Every trial in both arms
opens with the identical call —

```
table_get {"filter":{"Name":"b"}, "table":{"heading":"Duplicate columns > Repeated header","ordinal":0}, …}
```

— 10 of 10 in the control and 10 of 10 in the treatment. The two arms are
therefore *identical up to the refusal string*, which is as close to isolating a
sentence as this benchmark can get. What follows differs completely:

* **Control, 10/10:** no second call. The model reports the question
  unanswerable — *"I cannot answer your question because the table … has
  duplicate column names"* — which is what the sentence told it, since the only
  move named was a document edit it has no tool for.
* **Treatment, 10/10:** a second call with `filter` omitted, then the answer off
  the full table. Unanimous; not one trial found a different route, and not one
  tried the rename.

So the 0/10 was never a reasoning failure. The model did the right thing with
the information it was given both times, and the refusal was the whole variable.

**The blast radius came back wrong, and the instrument was the reason.**
`regrade_snapshot.py --compare` reported *"no recorded call changed behaviour"*
— the pre-registered void condition inverted: not too much movement, none at
all, for a change ten recorded trials read. Two independent structural causes,
either sufficient on its own:

1. **Reads were never replayed.** `table_get` is not an `apply_op` entry (§6.1),
   so every recorded read hashed the same `unknown operation "table_get"` vector.
   The instrument was blind to the entire read family, not to this line.
2. **The replay globbed `corpus/` only.** No corpus file repeats a header — the
   same absence that hid F-dupcol from `difftest.py` — so the branch under test
   was unreachable even after reads were routed correctly.

Both fixed before the run, not after it: reads go through `armb.read_call`, the
entry point the trials themselves took, and `bench/synthetic/*.md` joins the
replay because those are the documents the trials ran against. The fix is in the
same commit as the executor change (`97ad6f5`), ahead of any trial.

**Cause 1 had already been found once, in the other replay.** F-remedy's own
control arm hit it in `headroom.py` — *"they used to be skipped instead… an
undercount that was safe only while no candidate's branch lived behind a
read"* — and that module was fixed then, on this same refusal. `headroom.py`
and `regrade_snapshot.py` are two independent replays of the same recorded
calls, and only one of them was repaired. There is no mechanism that would have
carried the fix across; it was noticed here because the second instrument
happened to be pointed at the same branch a second time. Worth stating plainly:
the project has two replays, they have drifted apart before, and nothing checks
that they agree about which calls are executable.

With the instrument able to see it, the pre-registered answer appears exactly:
**10 of 13267 calls move**, all ten `get-repeated-name`, `ERR → ERR` on both
sides, **1 of 52 fixtures** differing, and only the last line of the string. The
two non-provoking tasks in the same file do not move. Not void.

**What this says about the other three call sites.** Nothing, and deliberately.
The result is evidence that *a performable remedy gets performed*, at one call
site, on one fixture, under one scheme. `where` and keyed `values` have
performable remedies too and are still reached 0 times in 2071 trials; `column`
has none and keeps the shipped sentence because it is correct there. The open
item stays open with the wording recorded, because the thing just demonstrated
is that the sentence matters enough to measure rather than to argue.

**The general form, stated as narrowly as it deserves.** A refusal that names a
move the caller cannot make is not merely unhelpful — here it converted a
recoverable situation into a reported impossibility 10 times out of 10, with the
model's own first move already correct. That is the same shape as F-action's
line about naming the argument the core received. It is one instance, and the
claim is bounded by Caveat 21: this is evidence about this sentence.

### The section half, settled as a capability question rather than a wording one

The table above leaves the mixed-line-endings refusal on three call sites —
`section-append`, `-insert`, `-replace-body` — with the remedy marked **not
performable**. That was measured against the tool surface. The residual question
is different and was never asked: not *"can the model normalize the file"* but
*"should `_section_eol` have needed a convention at all"*, since refusing is
only right if picking one is wrong.

**The dead end is a property of the op table, not of any model.** Every one of
the fifteen ops was driven against a section holding one CRLF line and one LF
line:

| op | result |
|---|---|
| `section-append`, `section-replace-body`, `section-insert` | refused, the mixed-endings sentence |
| `section-rename` | **OK** — heading line only, endings left mixed |
| `section-set-level`, `frontmatter-set` | OK, endings left mixed |
| `section-delete` | OK — the mixture goes because the content goes |

No op normalizes line endings, so the remedy has a ceiling of zero in the
strongest sense available: it is not that a model fails to find the move, it is
that the move is absent from the set. The only route that ends in a successful
append is `section-delete` followed by `section-insert` with the body retyped by
hand — which relocated the section from first to last in the document, added a
blank line it did not have, and required the model to reproduce the entire body
from a summary. That is the free-text rewrite this project exists to replace,
reached by a different road.

**One fact the earlier table did not record: `section-rename` succeeds.** The
refusal is not a claim that a mixed section is unaddressable; it is scoped to
writes that must emit a line ending of their own, which is the correct scope. It
also means the op is *already* deciding a convention question — `_block`
normalizes the payload's own CRLFs away and re-applies `eol` — so the refusal is
not "this tool does not choose endings", it is "this tool does not choose
between the document's two".

**Decision: `_section_eol` keeps refusing, and the sentence keeps its wording.**
A local rule was available and defensible — match the last line of the section's
own body — and it was rejected for three reasons. It writes bytes into user
files, in two implementations, on a branch `headroom.py` prices at **k = 0**, so
nothing could ever check it. A section with two conventions is usually a symptom
of damage that happened earlier, and silently picking one makes the tool a
participant in the damage instead of the thing that surfaces it; §6.3 says the
convention is the document's, and this document has no single one to defer to.
And F-remedy already ruled on this exact sentence, above: *"the refusal is
correct to refuse."*

This lands the same way as the `table-realign` width refusal (F-width) and for
the same reason, which is worth saying once rather than twice: a refusal at
k = 0 that is *correct* keeps its wording, because changing model-facing text
with no number is the thing being avoided, and an unmeasurable branch is where
that rule binds hardest rather than least. What separates these from F-rows —
which *was* fixed without a number — is that F-rows' sentence was factually
wrong about the tool's own arguments. These two are factually right about a
capability the product does not have.

**What stays open, and it is not nothing.** The *remedy* sentence is still
unperformable, and F-remedy's own general form says what that costs: a refusal
naming a move the caller cannot make converted a recoverable situation into a
reported impossibility 10 times out of 10. The difference is that F-rows had a
performable alternative going unsaid — drop `filter` — and this one has none, so
the best an edit could do is replace a false hint with an honest dead end and
recover zero calls. That is still an improvement in honesty, it is still a
wording change with no number, and it stays parked under "Not fixed here" above
rather than being smuggled in as a capability decision. What this subsection
settles is only the capability half: **the op should not pick.**

## F-terminal — one refusal class is graded as unrecoverable, and it is a quarter of the composition cost

Setting out to design the re-measurement the 4.5-point composition item asks
for, the first job was to see which of F-compose's three mechanisms a change
could reach. Pairing `compose_solo` against `compose_3` and attributing each of
the 15 lost trials to a mechanism answered a different question instead.

**All four table losses are the same call, and the model fixed it itself.**

```
call 1   table_edit {"action=add-row,path":"corpus/tables/ragged.md", …}
call 2   table_edit {"action":"add-row","path":"corpus/tables/ragged.md", …}
```

`action` fused into the next key — `action_sizing.py`'s fused-`action` call,
which that module found and sized and which nothing had yet caught in an arm.
It resolves to `table-None`, the executor answers

```
unknown operation "table-None". Valid: table-add-row, table-update-cell,
table-delete-row, table-realign, …, frontmatter-delete
```

and the model reads it, corrects, and produces the right document. The trial is
graded `malformed`.

### The run loop and the grader disagree

`run_trial` has no special case: every error, this one included, goes back to
the model as `"Error: " + err` and the loop continues (`armb.py:1621`). The
grader has one:

```python
op, op_args = normalize(fn.get("name"), args)
after, err = apply_op(doc, op, op_args)
if err:
    if err.startswith("unknown operation"):
        return "malformed", err        # the only terminal refusal class
    errors.append(where + err.replace("\n", " | "))
    continue
```

It is the only refusal `grade_one` treats as terminal, and its own docstring
twelve lines above says it should not:

> A call that errors leaves the document untouched — that is the op's contract,
> and the multi-turn loop hands the model the error and lets it try again — so
> an error is collected and the sequence continues rather than aborting.

The two returns above it, `unparseable arguments` and `arguments not an object`,
*are* properly terminal: no refusal is produced, so there is nothing for the
model to read. This one produces a sentence, hands it over, and gets acted on.

### What crediting the recovery moves, measured over every recorded trial

Re-graded with that branch removed and nothing else changed, over all 8577
tool-arm trials on disk (Arm A is excluded — `grade.py` grades it, and it has no
`action` to fuse):

**31 trials change grade. Exactly the 31 that ever drew the sentence.** 22 go to
`correct` and 9 to `op_error` — a **71% one-turn recovery rate**, which is not
an outlier but the house number: B3 measured 13/13 for tables and S12 75% for
sections. This class was being denied the credit every other class gets.

| | as recorded | recovery credited |
|---|---|---|
| `solo` → `compose_3` (3 families, 310) | 276/310, 15–1, p = 0.00052, **4.5 pts** | 280/310, 11–1, p = 0.0063, **3.2 pts** |
| `solo` → `compose_5` (5 families, 480) | 426/480, 31–5, p = 1.3e-05, 5.4 pts | 429/480, 28–4, p = 1.9e-05, 5.0 pts |
| `compose_3` → `compose_5` | 6–4, p = 0.75 | 6–3, p = 0.51 |

Per family against `solo`, the shape changes rather than the size:

| family | as recorded | recovery credited |
|---|---|---|
| tables | 57/60, 3–0 | **60/60, 0–0** |
| lists | 100/100, 0–0 | 100/100, 0–0 |
| sections | 117/150, 14–1, p = 0.00098 | unchanged |
| frontmatter | 95/110, 11–2, p = 0.022 | 95/110, 11–1, p = 0.0063 |
| table-read | 57/60, 3–2 | unchanged |

**Tables joins lists as completely immune to composition**, at 60/60 in all
three composed arms (`compose_3` 93.3% → 100%, `compose_4` 96.7% → 100%,
`compose_5` 95.0% → 100%). F-compose's "the two families that lose are the two
whose tasks are hardest" becomes literally true: sections and frontmatter, and
nothing else.

Four published rates outside the composition arms move too, and they are named
because the convention is load-bearing wherever it fires:

| pool | as recorded | recovery credited |
|---|---|---|
| `armb_front_p_v3` (`front_p`, adopted) | 104/110 = 94.5% | 105/110 = 95.5% |
| `armb_front_naive_v3` | 97/110 = 88.2% | 98/110 = 89.1% |
| `armc_framing_lists` `list_i` | 26/30 = 86.7% | **30/30 = 100%** |
| `armc_framing_lists` `list_naive` | 30/36 = 83.3% | 34/36 = 94.4% |

The Arm C pair is the largest single move and lands in F-framing, where the
lists row goes from plain 61 / json 60 to **plain 66 / json 63** and the pooled
primary endpoint from 18–17, p = 1.00 to **20–17, p = 0.743**. The conclusion
there is unchanged and if anything better supported: the primary endpoint was
flat and is still flat. The one-turn secondary does not move at all (28–17,
p = 0.135), because the trials that changed were already counted as failing to
recover in one turn.

Arm C carries the identical branch (`armc.py`, three lines above a comment
reading *"the sequence continues rather than aborting, as in Arm B"*), so the
same fix applies there. It is also the one place the *sentence* is not at fault:
Arm C is handed an op directly, so naming all fifteen ops is correct there in a
way it is not for a model with three tools (see the `table-realign` open item).

Two things make the regrade checkable rather than asserted. Every pool was
re-graded from disk with no GPU and **exactly the 31 predicted trials moved** —
no pool drifted anywhere else. And `armc_framing_sections` and
`armc_framing_tables`, which have no instance of the refusal, were re-graded
through the same binary and reproduced all 250 recorded grades identically,
which is what rules out executor drift as the cause of the 10 that did move.

### The decision: credit the recovery

The branch is gone from both `armb.grade_one` and `armc.grade_one`, and every
affected pool has been re-graded on disk. The case each way, recorded so the one
not taken is legible rather than absent:

- **Credit the recovery** *(taken)*. The grader contradicted its own docstring
  and the run loop it grades; the refusal is read and acted on like every other;
  71% recover; and the convention was deciding 1.3 of the 4.5 points that the
  composition item exists to attack. Under this reading one of F-compose's three
  mechanisms — the dropped discriminator — costs **nothing**, because every
  instance of it recovered.
- **Keep it terminal** *(not taken)*. `malformed` means the model did not
  produce a usable call, and `{"action=add-row,path": …}` is a malformed call by
  any reading. The document ending correct on a later turn does not make the
  first call well-formed.

The second reading is coherent, and the reason it lost is narrower than "it is
wrong": it describes a property of the *call*, and every outcome class in this
ladder describes a property of the *trial*. `op_error` already covers a
well-formed call that named a thing which does not exist and was then recovered
from; an op name that does not exist is the same failure one level up. What
`malformed` is for is a trial that produced nothing to recover *from*, which is
exactly what the two returns above the branch still catch.

**What this does not do is retire the defect.** The fused `action` is still a
defect, it is still worth fixing, and `action_sizing.py` still prices it — it is
just priced as a turn rather than as an outcome, which is what B3 and S12 say a
loud failure costs. That distinction is §5.3's whole subject.

### Two errata found on the way

- **Two rows of F-compose's per-family table print a `b` that does not
  reconcile with its own margins**, both in the same direction and both in the
  multi-turn families. The sections row prints 15–1 where 130/150 against
  117/150 is a net 13, which is (14, 1); the frontmatter row prints 14–2 where
  104/110 against 95/110 is a net 9, which is (11, 2). In both cases the
  published p is the one the *recomputed* pair gives — `mcnemar_exact(14, 1)`
  = 0.00098 and `mcnemar_exact(11, 2)` = 0.022 — so the p-values corroborate
  the counts rather than the printed pairs, and every other row in that table
  (tables 3–0, table-read 3–2, lists 0–0) reconciles exactly. No conclusion
  moves: both rows are significant either way. It is recorded because a
  discordant pair that does not reconcile with its own margins is exactly the
  kind of thing this file should not let stand silently, and because the two
  affected rows are the two the re-measurement below leaves standing.
- **The fused-`action` call is now witnessed in an arm.** The `action` open item
  says *"in none of these calls is `action` missing, it is fused, and a check
  that asks is `action` present cannot see any of them"*, and sizes it at 11 of
  7535 edit-tool calls. Those four `compose_3` trials are the same defect
  arriving in a graded arm, on the tool family that is otherwise perfect, in the
  condition that ships.

### What this leaves for the composition re-measurement

The residue after the grading question is decided either way is **sections
(14–1) and frontmatter (11–1)**, both above `headroom.py`'s floor of 6, so a
targeted intervention on those two is powered. Tables and lists are immune and
contribute nothing; `table_get` was already shown free (`compose_4` → `compose_5`,
p = 0.68). That is a much narrower and cheaper arm than "re-measure the
composition", and it is the one worth pre-registering — after the branch above
is settled, because 4 of the trials it would be scored on are currently graded
by a convention nobody has agreed to.

> **Half of this was wrong, and F-anchor says which half.** "A targeted
> intervention on those two is powered" reads a *family's* discordant count as
> if it were an *intervention's* reach. Decomposed, frontmatter's 11 are 4 + 4 +
> 3 across three mechanisms and none of them clears the floor; sections' 14 is
> 13 once a transport failure is dropped, and splits four ways. What survives is
> a mechanism this paragraph did not know about — `section_edit` called with no
> address, 0 of 150 under `solo` and 8 of 150 under `compose_5` — and it is the
> only thing in the residue with a k above 6. The arm is sections alone.

## F-realign — the gain from the unreachable op, priced without a GPU

`table-realign` is the one op in `OPS` that no published `action` enum offers.
The open item records the state; this prices the **gain** side of the ship
decision, which `ceiling.py` can do for free, and turns up two facts that were
not in the item and that move the recommendation.

### The instrument

`bench/tasks/tables_realign.json` — three tasks on
`bench/synthetic/realign-targets.md`, one per shape raggedness arrives in: a
table whose lines end CRLF, a table with an over-padded header and one narrow
row, and a table nested inside a list item behind two spaces of continuation
indent. All three are chosen because realign has to **preserve** something
while rewriting every line of the table, and a ceiling that only covers the
easy shape is not a ceiling.

`scheme_f_realign` is `scheme_f` with `realign` appended to the enum and one
action line appended to the description, in the same format as the other three.
Nothing else differs.

### The ceiling: 3/3, in both arms

| arm | executor | result |
|---|---|---|
| B | `incise_ops.apply_op` | **3/3 ideal calls grade `correct`** |
| C | the release binary, real files, sandbox | **3/3 ideal calls grade `correct`** |

CRLF survives on all four rewritten lines; the two-space continuation indent
survives and the list item does not silently end; the over-padded table comes
back aligned. The Python oracle and the shipping Rust agree. The capability is
real and it is not what limits anything.

The other half of the pair is settled by reading rather than running, and the
distinction matters. `ceiling.py`'s `as_tool_call` builds the tool call from the
ideal op **without consulting the enum**, and the executor runs `table-realign`
whether or not a schema published it — so running these tasks under today's
`scheme_f` also grades 3/3, and that number means nothing. That a model cannot
emit `action: "realign"` when the enum does not contain it is a fact about the
schema. Same shape as F-rows: `ceiling.py` proves the reachable side, the schema
settles the unreachable one, and the discordant count is forced before a model
is asked anything.

### First new fact: this cannot be A/B'd in one process

`_actions_from_schemes` builds `ACTIONS` from **every** scheme in `armb.py` and
raises if one tool name publishes two different enums. That is right —
`ACTIONS` is where the `action` refusal reads its list of valid actions, and a
tool with two enums has no one list to name. Nine scheme entries publish
`table_edit` (`scheme_b` through `scheme_g`, plus the three `compose_*` that
hold references to `scheme_f`'s object), so a realign candidate cannot be one
more entry beside them. Defining it unconditionally breaks the import for the
whole benchmark, `ceiling.py` and `schematest.py` included.

So `scheme_f` and `scheme_f_realign` are not two schemes, they are **two
worlds**, and the candidate lives behind `INCISE_BENCH_REALIGN=1`. Every other
schema decision in this file was settled by running two schemes against the same
seeds in one process; this one cannot be. The measurement is still available —
the seeds are stored and F-compose established that the server reproduces
trial-for-trial across runs — but it is two processes that share no state, and
that is a property of the decision rather than an inconvenience of the harness.

Flipping the flag also makes `schematest.py` fail with exactly the two
divergences that would have to ship (`table_edit.description` and a 4-entry enum
against 3 shipped). That is the guard working: this is a schema change and it
cannot reach production without a recorded run.

### Second new fact: the display-width defect is already a refusal

The neighbouring open item is titled "`table-realign` cannot measure display
width, and **narrows instead**", which reads like silent corruption waiting for
a CJK table. Its body says otherwise and its body is right; the title is the
part that misleads, and this is the direct test. On
`| 設定ファイル | rowan |` the op refuses:

```
Error: this table contains "設", which does not occupy one display column, and incise counts column width in characters.
  Re-padding it would produce a table that is aligned by that count and ragged on screen, which is the opposite of what realign is for.
  First such cell: "設定ファイル"
  Realign is refused. Add, update and delete still work on this table and leave its existing lines byte-for-byte intact.
```

Exit 1, document untouched. That is a §5.3 refusal doing its whole job: it names
the character, states the consequence in terms of what the caller wanted, and
says what still works. It lands in `op_error`, the one failure class the grading
ladder calls safe, and F-terminal has just measured that class at 71% one-turn
recovery.

This is the fact that moves the recommendation. An op that silently narrows a
CJK table is not safe to hand a model; an op that refuses loudly is.

### The prevalence the pawl is up against

**13 of 81 corpus tables are already ragged**, across 6 files
(`corpus/tables/ragged.md`, `cell-edge-cases.md`, `alignment-markers.md`,
`hazards/nested-blocks.md`, `documents/project-readme.md`, and `README.md`). The
state realign exists for is not a corner: about one table in ten arrives in it.

And §5.2's ratchet is confirmed by direct test, in a stronger form than it
states. An edit to a ragged table preserves the raggedness — and `add-row`
writes its **new** row ragged too, because it matches the table's existing
style, which for a ragged table is "narrow":

```
| Name             | Value            | Owner            |
| ---------------- | ---------------- | ---------------- |
| AAA | b | c |
| dd               | ee               | ff               |
| zzz | yy | xx |          <- written by incise, matching the ragged row
```

Into a *well-aligned* table the same call pads correctly. So incise does not
merely decline to fix raggedness, it propagates it into bytes it writes itself,
and realign is the only op licensed to stop that.

### The recommendation: ship it, gated on one cheap run

The gain is proven and forced, the one known defect is a loud refusal rather
than corruption, the op takes a single argument so there is no property for a
payload to land in (L3's collision mode does not apply), and the state it
repairs is present in a tenth of the corpus.

What is still unpriced is the cost, and `headroom.py`'s one-sided rule is why it
cannot be waved through: a description change is in the prompt of **every**
trial, so the three realign tasks bound the gain and nothing bounds the loss on
the six existing table tasks. S14 is the precedent — an unneeded extra call
destroyed the document 36% of the time.

So: **120 trials, two worlds.** `tables.json` and `tables_realign.json`, each
under `scheme_f` and under `scheme_f_realign`, same seeds. The realign half is
forced (0/30 against an expected 30/30) and is there to confirm the ceiling
holds with a model in the loop rather than an ideal call. The *tables.json* half
is the measurement that matters: if the existing six tasks do not move, ship;
if they do, the fourth action costs more than the repair is worth and the op
stays an operator's tool. Roughly ten minutes of local GPU.

Recorded here rather than taken now, because the ship decision is a schema
change and §6 says those belong with a run.

### The pre-registration, written before the run

The paragraph above fixes the design and the decision rule; it does not fix the
*conditions*, and per F-compose's fact 2 a shape difference between two halves is
a second variable. So, pinned here and committed before a single trial:

> **Conditions.** `--turns 4 --result-shape delta`, both worlds, all four cells.
> That is what every tables-family pool on disk since S14 ran at
> (`compose_5_tables`, `anchor_control_compose_5`, `remedy_treat_read_g`), so the
> control half is comparable to them as well as to its own treatment.
>
> **Cells.** Four, not the three the paragraph above implies:
> `tables.json` × {`scheme_f`, `scheme_f_realign`} and `tables_realign.json` ×
> {`scheme_f`, `scheme_f_realign`}, 10 trials each. **180 trials, not 120** — the
> control realign cell is *run* rather than assumed. Its 0/30 is a construction
> fact (the enum has no `realign`), and a construction fact that is never
> executed is how F-framing's void condition got inverted. The extra 30 trials
> cost three minutes and convert an assumption into a measurement.
>
> **Predictions.** (1) `tables.json` does not move: McNemar p ≥ 0.05, and the
> discordant pairs are not lopsided against the treatment. (2)
> `tables_realign.json` under `scheme_f` is 0/30. (3) `tables_realign.json` under
> `scheme_f_realign` is ≥ 24/30 — the ceiling is 3/3 ideal calls, and the margin
> is for a model in the loop rather than for the op.
>
> **Decision rule.** Ship iff *all three* hold:
> **(a)** the `tables.json` half loses no more than **5** discordant pairs
> one-way, **(b)** the control realign cell is 0/30, and **(c)** the treatment
> realign cell is ≥ 24/30. Any other outcome: the op stays an operator's tool
> and the enum keeps three actions.
>
> **What this run cannot do.** 60 pairs and a floor of 6 mean a loss of five
> trials in sixty is indistinguishable from none. Clause (a) is therefore a
> bound of ~8 points, not a claim of zero cost, and the write-up says so
> whichever way it lands.

Pre-flight, before any GPU: `ceiling.py` under `scheme_f_realign` is **6/6** on
`tables.json` and **3/3** on `tables_realign.json`, so every cell has an
executor that can reach the answer and nothing below is an op defect wearing a
model's clothes.

### The result: it ships, and the absence of the op was never neutral

180 trials, four cells, `--turns 4 --result-shape delta` throughout.

| cell | tasks | world | correct |
|---|---|---|---|
| control | `tables.json` | `scheme_f` | **60/60** |
| treatment | `tables.json` | `scheme_f_realign` | **60/60** |
| control | `tables_realign.json` | `scheme_f` | **0/29** |
| treatment | `tables_realign.json` | `scheme_f_realign` | **30/30** |

All three predictions hold and the decision rule's three clauses are met, so the
op ships.

**The `tables.json` half did not move at all.** Not "not significantly" — the
two arms are *trial for trial identical*, 60 concordant pairs, zero discordant,
and `stats.py` says so in its own words: *"the two arms were trial-for-trial
identical: the change moved nothing, and n is irrelevant to that."* The bound
clause (a) bought is ~8 points; what was observed is the degenerate case inside
it. The reason is visible in the calls: across 62 treatment calls on those six
tasks the new action was reached for **zero times**. 41 `add-row`, 10
`delete-row`, 10 `update-cell`, one with `action` missing. A fourth enum entry
that no task wants is not a distraction the model has to price — it is a line it
does not read.

That is not the same as *no* movement. 9 of 60 call sequences differ between the
arms, and two treatment trials on `add-row-alignment-markers` took a second call
where the control took one — one of them after sending `values` nested one level
too deep. The description is in the prompt of every trial and it perturbed nine
of them; the perturbation cost 116 completion tokens across the pool and zero
outcomes. That is what the one-sided rule looks like when the uncapped downside
does not materialise, and it is worth recording in that shape rather than as a
clean zero.

**The control cell is the finding nobody pre-registered.** It was run rather
than assumed precisely because an unexecuted construction fact is how F-framing
inverted a void condition — and running it turned "0/30 by construction" into
something the construction does not predict. The thirty trials that could not
say `realign` did not decline: they said `update-cell` **54 times**, `add-row` 8
and `delete-row` once, across 63 calls, and the outcome is 13 `op_error`, 8
`malformed` and **8 `destructive`** — 27.6% silent corruption, the same class
S14 measured when an unneeded extra call destroyed the document 36% of the time.
A model asked to repair raggedness without the op does not do nothing; it
rewrites cells by hand and damages the table about a quarter of the time. §5.2
called realign the pawl of the ratchet. The control cell says the missing pawl
is not a gap in capability but an invitation to improvise, and the improvisation
is destructive.

Paired, the realign half is 0 of 29 against 29 of 29, McNemar exact
**p = 3.7 × 10⁻⁹**, with one pair dropped for an `HTTPError: HTTP Error 500` —
F-transport's instrument firing on its first live arm, counted and excluded
rather than charged to the control as `malformed`.

### What shipping it cost, stated rather than buried

`INCISE_BENCH_REALIGN` is gone; the augmentation in `armb.py` is unconditional
and `scheme_f_realign` survives only as an alias so this run's result files
still resolve by name. The enum invariant admits no half-measure — one tool
name, one enum — so **every** scheme's `table_edit` now carries a line the pools
recorded before 2026-09-17 were not shown, `compose_5` included. The harness
holds one world, and after a ship that world is the shipped one. The text a
given pool was shown is in git beside the commit that ran it, and that is the
only place it is.

`schema.rs` publishes four actions, `schematest.py` passes byte-identical at
five tools, and `table-realign` stops being the one op in `OPS` that no
published `action` reaches. Fifteen ops, fifteen reachable.

## F-anchor — the composition residue is one mechanism on one family, and it is not the one that was named

F-terminal left the composition item with a residue and a recommendation:
*"sections (14–1) and frontmatter (11–1), both above `headroom.py`'s floor of 6,
so a targeted intervention on those two is powered … that is the one worth
pre-registering."* Writing that pre-registration means naming the intervention,
and naming it means asking what the 25 lost trials actually are. They are not
one thing. Decomposing them removes most of the arm and finds a better one
underneath it, on one family, with a control that exhibits the defect **zero
times in 150 trials** — and, once `headroom.py` was asked the same question over
every pool on disk, twice in 801.

Nothing here was run. Every number below is read off pools already on disk —
`compose_{solo,3,4,5}_*.jsonl` — which is the same discipline F-realign used and
the reason this section ends in a pre-registration rather than a result.

### The cross-family mechanism cannot be the arm

F-compose named three mechanisms. The first, the dropped discriminator, costs
nothing once the recovery is credited (F-terminal). The third — *"cross-family
calls, which `solo` cannot exhibit at all"* — is the one the open item called
visible and cheap to attack.

It is real: **14 cross-family calls under `compose_5`, 0 under `solo`, by
construction.** What it is not is powerful. Of the 25 discordant losses, only
**5** involve a cross-family call at all — 3 frontmatter (`set-dana-role`) and 2
sections (`insert-nested-ratelimits` t4, `insert-troubleshooting` t4). The other
20 are the model reaching for exactly the right tool and getting the call wrong.

**k = 5 is below the floor of 6.** An intervention aimed at tool confusion has a
best achievable p of 0.0625 even if every single one of those five flips, so it
cannot return a significant result at this n at any effect size. The mechanism
being real and the mechanism being attackable are different claims, and this is
the distinction `headroom.py` exists to enforce — the first is visible in the
calls, the second is arithmetic and says no.

### Frontmatter's eleven do not decompose into an arm either

| the 11 lost trials | n | what they are |
|---|---|---|
| `add-build-cache` | 4 | the instrument, not the composition |
| `set-draft-true` | 4 | real, description-reachable, **k = 4 < 6** |
| `set-dana-role` | 3 | the cross-family mechanism above |

**`add-build-cache` is excluded, and it was already excluded.** The open item
says so: *"Turn on caching for the build"* names no key, the expectation wants
`build.cache`, and across 30 F-frontread trials the model wrote `build.cache` 22
times and `build.caching` 8. Both keys are absent from the file and from the
injected summary, so the model is choosing between two spellings on no evidence.
A composed arm losing 4 of them is that coin landing differently, not a cost of
publishing five tools. No description sentence can carry the missing
information, because the information does not exist.

**`set-draft-true` is the real one, and it is too small.** `draft: false` sits in
the frontmatter and in the summary; the model writes `status: draft` instead,
inventing a key rather than copying the one it was shown. That is precisely the
failure `front_p`'s `key` sentence — *"Copy it from the frontmatter summary in
the request"* — was adopted to prevent, and F-front calls this task
`front_p`'s *"unambiguous gain (7/10 → 10/10)"*. Under five tools it is back to
6/10. **Composition takes back the single clean win the adopted frontmatter
schema was chosen for**, which is worth recording precisely because the arm to
fix it is not available: k = 4.

So frontmatter's 11–1 is a measurement of what composition costs and not a
target. Nothing in it is both real and powered.

### Sections has one, and it is a hole in the schema text

The one mechanism that survives is not in F-compose's list of three, because
nobody had looked for it: **under composition, `section_edit` is called with no
address at all.**

| arm | trials with a `section_edit` call carrying no address | of which failed |
|---|---|---|
| `compose_solo` | **0 / 150** | — |
| `compose_3` | 10 / 150 | 7 |
| `compose_4` | 7 / 150 | 5 |
| `compose_5` | **8 / 150** | **8 / 8** |

Under `compose_5` every one of the eight is `op_error` and **not one recovers**,
across 34 offending calls in 25 trials over the three composed arms. Three
shapes, and `action=insert` is 16 of the 17 calls under `compose_5`:

| shape | calls | what the executor answers |
|---|---|---|
| `section` omitted entirely | 9 | `` `section` is required: the heading path of the section to act on. `` |
| `"section": {}` | 5 | the same |
| `"section": {"ordinal": 0}` | 3 | the same |

Two shapes that *look* wrong are not, and were checked against `apply_op` rather
than assumed: a bare string `"section": "Changelog > [1.4.2] - 2026-08-14"` and
`"section": {"path": …}` both resolve correctly, so neither counts here. That
check is what took the candidate from 15 trials to 8, and 8 is the number the
arm is priced on.

### It is not composition-only, and the survey is what said so

Adding the branch to `headroom.py` as a candidate — mechanically, over every
recorded trial rather than over the four pools this finding started from —
corrected the first draft of it. The rate is not zero outside the composed arms;
it is small:

| scheme | tools | trials | with an address-less call | rate |
|---|---|---|---|---|
| **`section_g_hpath`** (adopted) | 1 | 801 | 2 | **0.25%** |
| `section_kids` | 1 | 680 | 5 | 0.74% |
| `section_2call` | 1 | 737 | 8 | 1.1% |
| `section_g` | 1 | 1052 | 17 | 1.6% |
| **`section_naive`** | 1 | 100 | 5 | **5.0%** |
| `compose_4` | 4 | 150 | 7 | 4.7% |
| **`compose_5`** | 5 | 150 | 8 | **5.3%** |
| `compose_3` | 3 | 150 | 10 | 6.7% |

So **"zero" was a property of the 150-trial `compose_solo` pool, not of the
scheme.** The designed contrast is still the designed contrast — `compose_solo`
and `compose_5` are the same 15 tasks at the same seeds, turns and result shape,
differing only in tool count, and it is 0 against 8 — but the honest statement of
the adopted scheme's rate is 2 in 801, not 0. The rows in between are confounded
by turn caps (more turns, more calls, more chances) and are not a ladder.

The row that is not confounded, and that was not being looked for, is
**`section_naive` at 5.0% on one tool** — the same rate as the composed arms.
That reframes the mechanism and improves the case for the treatment rather than
weakening it: the address goes missing when the *description does not hold the
model's attention*, and a bare description under one tool does that just as
effectively as a good description under five. One cause with two routes to it,
and the same sentence closes both.

**The survey's own reporting was wrong for this candidate, and is fixed.** Its
summary line read *"N further reachable trials exist, all under schemes that do
not ship"*, which lumps the `compose_*` arms in with retired single-tool schemes.
`compose_5` is not an adopted scheme and it is also not a dead one — it is the
five-tool condition `schema.rs` actually publishes, and F-anchor's 25 composed
trials were being described by a sentence that says they do not ship. The count
is now split and named. It moved no `k` and no verdict: the only other
candidates with composed reach are S8 (6 trials) and F-action (9), both already
decided on other grounds.

### Why `section_edit` and not the other three

The difference is in the published text, which is the only thing an arm can
change. `table_edit` opens with

> `table` says WHICH table in the file and is **required for every action**.
> Copy it from the table list in the request …

and then names it again on every action line — `action=add-row requires
` `` `table` `` `, ` `` `values` `` `. `list_edit` does the same for `list`.
`frontmatter_edit` names `key` on both of its action lines.

**`section_edit`'s description never names `section` as an argument.** The word
appears in it as English — *"the section's existing text"*, *"cannot create a
section"* — and never once in backticks as a thing to send. Its action lines list
what each action needs *besides* the address, and `action=delete` says *"requires
nothing else"*, which read by a model that is skimming is an invitation. Checked
mechanically across all five adopted schemes: `` `table` ``, `` `list` ``,
`` `key` `` and `` `table` `` again are each present in their tool's
description; `` `section` `` is the only one that is absent.

| tool | description names its address argument | composed trials | address-less calls |
|---|---|---|---|
| `table_edit` | yes, and on every action line | 180 | **0** |
| `list_edit` | yes, and on every action line | 300 | **0** |
| `frontmatter_edit` | yes, on every action line | 220 | **0** |
| **`section_edit`** | **nowhere** | 450 | **34, in 25 trials** |

This is not proof — sections' tasks are the hardest in the set, and three of the
four tools have fewer actions to skim. It is the one difference that lives in
the schema, which makes it the one an arm can test. What the composed contrast
adds is that the same 15 tasks at the same seeds, turns and result shape lose
the address 8 times under five tools and 0 times under one, so whatever the
description is failing to do, crowding it makes it fail twenty times harder.

### The treatment, transcribed rather than invented

`section_h` is `section_g_hpath` with two changes, both copied from schemes
already adopted:

```
Edit a markdown document's sections. Heading syntax, heading level, blank-line
spacing and the boundaries of each section are all maintained automatically;
you do not need to format anything or count levels.
`section` says WHICH section in the file and is required for every action. Copy
it from the outline in the request; the last heading segment on its own is
enough (e.g. "macOS"). For action=insert it is the EXISTING section the new one
goes relative to, not the new one.
  action=append        requires `section`, `text`. ...
  action=replace-body  requires `section`, `text`. ...
  action=insert        requires `section`, `position`, `new_heading`. ...
  action=delete        requires `section` and nothing else -- takes the subtree with it
  action=rename        requires `section`, `new_heading`
  action=set-level     requires `section`, `level`
```

Everything after each `...` is `section_g_hpath`'s existing text, unchanged.
Nothing else in the tool moves — S15's decision that the address is spelled
`heading` and that `path` means the file is untouched, and the added sentence
says *outline*, not *path*, for that reason. The one sentence that is not a
transcription is the `action=insert` clause, and it is there because 16 of the
17 offending calls are `insert`: the model that omits `section` on an insert is
not forgetting an argument, it is failing to see that a creation has an anchor.

### Pre-registration: `section_h` inside the shipping composition

> **Condition.** `bench/tasks/sections.json`, all 15 tasks, **20 trials**,
> `--turns 4 --result-shape delta` — the condition `compose_5_sections.jsonl`
> records in its own rows, now that rows carry `result_shape` and `max_turns`.
> Two arms, same seeds, same session:
> **control** `--scheme compose_5`, **treatment** `--scheme compose_5h`, which
> is `compose_5` with `section_h` substituted for `section_g_hpath` and the
> other four tools byte-identical. 300 paired trials per arm, ~40 minutes of
> local GPU. `ceiling.py` must be 15/15 under both before a model is asked
> anything.
>
> **What has to be built first**, and it is additive so no recorded path moves:
> `section_h` in `armb.SCHEMES`, and `compose_5h` built by *referencing* the
> other four schemes' tool objects exactly as `compose_5` does, so the two
> compositions cannot drift apart in anything but the one description.
>
> **Transport failures are handled in advance.** A trial whose `error` is an
> `HTTPError` is dropped from **both** arms and reported as a count, not graded
> `malformed` — see the erratum below. Deciding that after seeing which arm the
> 500s landed in is exactly the move a pre-registration exists to prevent.
>
> **Why 20 trials and not 10.** At 10 the control shows k = 8, a ceiling of
> p = 0.0078 that tolerates only two of the eight failing to flip. 20 doubles
> the expected reach to ~16 and buys a margin the conclusion can survive.
>
> **Caveat 17, applied in advance.** The control's t0–t9 are the same seeds
> `compose_5_sections.jsonl` already holds under the same scheme, so they are a
> replication and cannot disagree. They are the clap rule: if they do not
> reproduce the recorded 117/150 the run stops there and nothing else in it
> means anything. The power comes from t10–t19, which are fresh, and from the
> control-versus-treatment contrast at every seed — a real contrast, because the
> two arms are shown different schema text.
>
> **Prediction.** The treatment removes the address-less call. Concretely:
> **fewer than 3 treatment trials carry a `section_edit` call with no address**,
> against ~16 in the control, and the sections family gains.
>
> **Decision rule, fixed now.**
> - **The control shows fewer than 6 address-less trials** → the arm is
>   under-powered, full stop. It is reported as UNDERPOWERED and *not* as a
>   null, no matter what the treatment does. This branch is written first
>   because it is the one that is tempting to reinterpret afterwards.
> - **Treatment beats control, p < 0.05** → `section_h` replaces
>   `section_g_hpath` in `schema.rs`, in `schematest.py`'s `ADOPTED`, and in the
>   docstring's tool/scheme table with this run named as what it settled.
> - **p ≥ 0.05, and the address-less count does not fall** → the hole in the
>   description is not the cause; the item closes and the composition cost stays
>   unattributed. `section_h` is not shipped on the strength of being tidier
>   than what it replaces.
> - **Treatment loses** → not shipped, and recorded. This is a description
>   change, so `headroom.py`'s one-sided rule is in force: the 8 reaching trials
>   bound the **gain**, and nothing bounds the loss on the other 142. S14 is the
>   precedent for a change that helped where it was aimed and cost more
>   elsewhere.
>
> **Caveat 21 applies and is stated in advance:** this is evidence about
> `section_h` against `section_g_hpath` for this model at this condition.

Frontmatter is deliberately **not** in the arm. Its three mechanisms price at 4,
4 and 3, and adding a second family to a run would only make the pooled number
look better than any of its parts deserve.

**Both arms are run — F-reach.** The clap rule passed exactly (117/150, and 149
of 150 cells identical), the control showed the 16 address-less trials this
predicted, the treatment cut them to 7 — and the outcome did not follow:
14–9, p = 0.4049. `section_h` is **not shipped**. The decision rule's third
branch turned out to be a conjunction that cannot fire, which is recorded there
rather than argued away.

### The erratum found on the way: a transport failure is charged to the model

`grade_one`'s first line is

```python
if trial.get("error"):
    return "malformed", trial["error"]
```

and `trial["error"]` is set from any exception the run loop catches, including
the ones that never reached a model. **10 trials on disk are graded `malformed`
for `HTTPError: HTTP Error 500: Internal Server Error`** — an empty `turns`
list, no tool call, nothing the schema could have changed — across five pools:
`armb_s6_section_kids` (4), `armc_sections` (2), `armc_replay_path` (2),
`compose_4_sections` (1), `compose_5_sections` (1).

This is F-terminal's defect one level further out: a class of trial the model is
not responsible for, charged to the model. The remedy is different, though.
F-terminal's class produced a sentence the model read and acted on, so it was
**re-classed**. A 500 produces nothing, so the pair should be **dropped** —
both arms' trial, since an unpaired trial is not evidence either.

Exactly one published number moves, and its conclusion does not:

| | as recorded | 500 dropped |
|---|---|---|
| sections, `solo` vs `compose_5` | 130/150 vs 117/150, **14–1**, p = 0.00098 | 129/149 vs 117/149, **13–1**, p = 0.00183 |

`compose_4`'s dropped trial was concordant, so that row is unchanged. The other
three pools are named above and not restated here; they are outside this
finding's subject and re-grading them is a separate pass.

**Not fixed in the grader**, on purpose. `malformed` with a `HTTPError` detail is
at least visible and greppable, which is how these ten were found; a silently
dropped trial is not. What the pre-registered arm above does instead is state
the handling in advance — a 500 drops the pair from both arms and is reported as
a count, so the decision is made before the data rather than after it.

## F-wart — the phrase is wrong, and the arm that would fix it can only lose

`schema.rs`'s docstring preserves three warts on the ground that the text is
what was measured. The second of them is `table_get`'s `table`, described as
*"Which table to **edit**"* — copied from `table_edit` into a tool that cannot
edit anything, and measured in place at 58/60. The open item asked for an arm:
`table_read_g` against a copy differing in that one phrase, on the same six
tasks and the same seeds.

Priced, the arm returns nothing. The number is small and dull; what it does to
the contract is not.

### The two harms it is accused of, counted as two

A phrase on a read tool's address saying *edit* can do harm in two places, and
they are different failures with different populations. Both are on disk.

**Tool choice.** The accusation only exists where both tools are published, and
the only condition that does that is `compose_5` — which is the condition
`schema.rs` ships, and the distinction F-anchor had to make the hard way.

| composed trials | wrong tool reached for |
|---|---|
| 60 `table-get` tasks, `table_edit` also published | **0** |
| 60 `table-*` edit tasks, `table_get` also published | **0** |

Zero of 120, so the 95% one-sided upper bound on the misroute rate is **2.5%**.
Not proof of zero, and not claimed as such; it is the bound the recorded
condition supports.

**The argument itself.** The phrase is on `table`, so if it misleads inside the
tool it does so by producing a `table` that does not resolve. `headroom.py`
counts every refusal `resolve_table` can return, across every pool:

```
F-wart: `table_get`'s address says "Which table to edit"
  table_read_g       yes    150    2    2
  compose_5           --     60    1    1
  table_read_naive    --     60    0    0
  over the adopted scheme(s) ['table_read_g']: k=2 reachable of n=150
  UNDERPOWERED: k=2 ... below the floor of 6
```

### Every reachable trial is already a win, which takes the bound to zero

Three trials in the whole directory. All three are graded `correct`.

| trial | what was sent | recovered |
|---|---|---|
| `get-repeated-both` 4 | `"table": "Key"` — the repeated *column* name as the table address | yes, next call |
| `get-repeated-both` 8 | `{"heading": "Key", "ordinal": 0}` — same mistake, object-shaped | yes, next call |
| `get-whole-table` 4 (`compose_5`) | `{"\"heading": "Components", ...}` — a mangled JSON key | yes, next call |

The third is not a wording failure at all; it is F-framing's escaping artifact
wearing an addressing refusal. The first two are a model reaching for a column
name after the repeated-header refusal sent it groping — F-remedy's task, doing
exactly what it was built to do — and neither has anything to do with the word
*edit*.

This is what tightens the bound past what the survey prints. The one-sided rule
says `k` bounds the **gain**: at most 2 trials can be moved in the favourable
direction. All 2 are already correct, and a trial that already wins cannot be
won. So the gain is **0**, the loss is unbounded in the usual way, and the arm's
best possible outcome is that nothing happens.

### Where the read tool *is* misused, and it is not this

Worth recording because it is the honest counterexample and it makes the claim
sharper rather than weaker. Under `compose_5`, `table_get` is called on
`set-dana-role` — a **frontmatter** task on `corpus/frontmatter/rich.md`, which
has no tables at all — 4 calls across 4 of 10 trials, addressed at `"Authors"`
and `"Addressing"`.

That is a model that wants to *read* something before editing it, and finds one
read tool published. It is the cross-family mechanism F-anchor priced at k = 5,
below the floor. It is caused by `table_get` being the only read in the set, not
by its address saying *edit* — the model is not confused about what `table_get`
edits, it is confused about what it reads. The frontmatter read is out of scope
by decision (F-frontport), so this stays where F-anchor left it.

### What this does to the contract, stated rather than worked around

The rule is that a description is a requirement surface: changing it is a
behaviour change and belongs in a benchmark, not a docs commit. Applied here it
produces a phrase that is **wrong and permanent**. There is no number available,
so there is no licensed fix, so the text ships as it is indefinitely.

That is the rule working, not failing, and the alternative is worse: a standing
exception for "obviously safe" wording is exactly the door S14 came through,
where an extra sentence that read as an improvement destroyed the document 36%
of the time. The cost of the rule is one wrong word in one description. The cost
of the exception is unmeasured schema drift, which is the thing the whole
contract exists to prevent.

There is one legitimate way out, and it is not an arm for this. If `table_get`
is re-measured for some *other* reason — a new read family, a sixth tool, a
change to `filter` — the scheme under test has to be written anyway, and the
reworded address can be in it from the start. The phrase is then measured, not
excepted. Three open items already sit on `table_get`'s description (this one,
F-read's `filter`-is-literal, F-remedy's rename remedy), and bundling them is
what makes any of them affordable while making none of them attributable. This
wart is the one item that can safely ride in a bundle, because it is the one
with nothing to attribute: its gain is already bounded at zero.

### The decision

**Closed, not deferred.** The phrase ships as measured, and the open item comes
off the list. Re-opening it requires a `table_get` re-measurement that exists
for some other reason — not a new argument about the word.

### What this does not license

It does not say the phrase is harmless. 0 of 120 bounds the misroute at 2.5%,
not at 0, and none of the six read tasks asks a model to choose between reading
and editing the same table — the one prompt that would put the phrase under
load. Caveat 21 applies: these trials are evidence for the schemes they were
shown. What is settled is narrower and is the only thing that was asked: **the
arm proposed for this cannot return a gain**, so it should not be run.

## F-reach — the hole was real, closing it halved the mechanism, and the document came out worse

F-anchor pre-registered `section_h` against `section_g_hpath` inside the
shipping composition. Both arms are run, at the pre-registered condition and
nowhere near it in outcome: the mechanism moved almost as far as predicted, the
result did not follow it, and the treatment's losses are somewhere the
pre-registration never looked.

`bench/results/anchor_control_compose_5.jsonl` and
`bench/results/anchor_treat_compose_5h.jsonl`, 300 paired trials each,
`--turns 4 --result-shape delta`, 15 tasks × 20 trials.

### The clap rule, and it is the strongest this file has recorded

The control's t0–t9 are the same seeds `compose_5_sections.jsonl` already holds
under the same scheme, so they are a replication and were pre-registered as the
gate. They reproduce **117/150** — not approximately, exactly — and **149 of the
150 individual cells carry the identical outcome**. The one that moved is
`insert-nested-ratelimits` t1, `wrong` → `op_error`, a failure either way.

t10–t19, which are fresh, land at 114/150. No regime shift, so the extra seeds
are poolable with the recorded ones, which is what the doubling from 10 trials
was bought for.

### Transport failures, handled as pre-registered

One `HTTPError` in each arm — control `promote-api` t5, treatment `promote-api`
t0. Both pairs dropped from **both** arms and reported here as a count, per the
pre-registration and F-anchor's erratum. 298 pairs remain. Deciding this after
seeing where the 500s landed is the move the pre-registration existed to
prevent, and the rule was written before they landed.

### The primary result is a null

| | control `compose_5` | treatment `compose_5h` |
|---|---|---|
| correct | **231/298 = 77.5%** | **226/298 = 75.8%** |
| silent corruption | 23 = 7.7% | **39 = 13.1%** |
| `op_error` | 42 | 32 |
| `wrong` | 11 | 21 |
| `destructive` | 3 | 10 |

Paired: both correct 217, neither 58, **only control 14, only treatment 9**,
**McNemar exact p = 0.4049**. The treatment does not beat the control and does
not significantly lose to it.

### The mechanism did move, and not as far as predicted

Address-less trials, counted by `headroom.py`'s own predicate over the raw rows
so the count is independent of the grader:

| | trials with a `section_edit` call carrying no address | calls |
|---|---|---|
| control | **16** of 298 | 27 |
| treatment | **7** of 298 | 8 |

Paired, that is 14–5, **p = 0.0636** — a fall, and not a significant one. The
pre-registered prediction was *"fewer than 3 treatment trials"*; the answer is
7. So the prediction is wrong twice: the mechanism did not go away, and the
outcome did not follow the part of it that did.

The control's 16 are on two tasks, both `insert` — `insert-release-at-top` 9 and
`insert-troubleshooting` 7 — which is F-anchor's "16 of 17 offending calls are
inserts", reproduced at double the trials.

### Where the treatment's losses are, which is the interesting half

**`promote-api`, 16/18 → 9/18.** It is a `set-level` task. It has never had an
address-less call in either arm, it is not an `insert`, and it is the single
biggest mover in the run. Five of its seven lost trials are `destructive`, all
the same way: `Reference > API > Endpoints` gone.

The transcripts say exactly what happened. Both arms open with the same mistake,
a `set-level` missing its `level`:

```
CONTROL  t11
  set-level  section={"heading":"Reference > API"}            <- no `level`, refused
  set-level  section={"heading":"Reference > API"} level=2    <- fixed, correct

TREAT    t11
  set-level  section={"heading":"Deep heading nesting > Reference > API"}   <- refused
  rename     section={"heading":"Deep heading nesting > Reference > API"}
  insert     section={"heading":"Deep heading nesting > Reference"} position=after
  delete     section={"heading":"Deep heading nesting > Reference > API"}   <- subtree gone
```

The control supplies the argument it forgot and stops. The treatment abandons
the action and walks the action list instead. And the action list is what
changed: every line now ends in an argument the model is already holding, so
every action reads as one step from being callable — including

```
  action=delete        requires `section` and nothing else -- takes the subtree with it
```

which is now, to a model holding a `section`, a complete call.

`action=delete` calls on `promote-api`: **control 1 trial, treatment 6**, and
**all 6 are graded `destructive`**. Total calls across the run rise 483 → 529,
+9.5%. The anchor sentence was aimed at the one action that omits its address
and it landed on all six.

**`insert-troubleshooting`, 0/20 → 0/20, and the failure changed kind.** Of the
7 control trials that lost their address, 5 come back in the treatment as
`wrong` rather than `op_error`. The model now supplies an address — and supplies
the address of the section it is *creating*:

```
missing section 'Deep heading nesting > Troubleshooting > Logs'
```

That is precisely what the added sentence warns against — *"For action=insert it
is the EXISTING section the new one goes relative to, not the new one"* — so the
sentence was read, understood as "put something in `section`", and not obeyed in
the part that mattered. The refusal it replaced was at least loud.

### Post-hoc, and labelled as such: the corruption metric is the one that moved

Silent corruption (`wrong`, `destructive`, `collateral:formatting`) paired
control → treatment is **b = 31, c = 15, p = 0.0259**. This was not
pre-registered as an endpoint and is reported as an observation, not a result.
It is quoted because it is the direction of travel the primary null hides: the
treatment did not lose trials so much as convert loud failures into quiet ones,
which is the trade §5.2 cares about most and the one a correct-rate cannot see.

### The decision, and an admission about the rule

The pre-registered rule has four branches and the outcome fits none of them
cleanly. It was written assuming the mechanism count and the outcome move
together; branch three says *"p ≥ 0.05, **and** the address-less count does not
fall"*, and the count did fall. That conjunction is a defect in the rule, and
naming it is cheaper than arguing the result into a branch.

What is not ambiguous is the action. **Only branch two ships `section_h`, and
branch two requires p < 0.05 in the treatment's favour, which did not happen.**
Every other reading — null, loss, mis-specified — lands in the same place:

> **`section_h` is not shipped.** `schema.rs`, `schematest.ADOPTED` and the
> docstring's tool/scheme table are untouched; `section_g_hpath` remains the
> adopted scheme. The composition cost stays **unattributed**.

The schemes stay in `armb.SCHEMES`. A scheme that lost is a measurement
condition with a number attached, and deleting it would make this finding
unreproducible.

### What this buys, since the null is not nothing

`headroom.py`'s one-sided rule has been stated in this file five times and
demonstrated once, by S14. This is the second demonstration and a cleaner one,
because the gain and the loss are visible in the same run:

- the **gain** was bounded at the reaching trials, and came in under the bound —
  9 of 16 recovered their address, none of which was worth a point;
- the **loss** landed on `promote-api`, a task in none of the 16, by a route
  nobody proposed — the sentence that named the address on every action line
  also made the destructive action look reachable.

A description change is not a local edit. It is in the prompt of every trial,
and it is read by a model that is looking for *any* action it can complete.

### What this does not license

It does not say the hole is not real. `section_edit` is still the only published
tool whose description never names its own address, and it still loses that
address where the others do not — the treatment cut that 16 → 7 and the cut is
the one thing that went as designed. What is refuted is the inference from it:
that closing the hole buys the composition's lost points. It does not, for this
sentence, on this model, at this condition. Caveat 21, stated in advance and
still governing.

Nor does it license a second attempt with a tidier sentence. The next candidate
would be chosen by looking at this run's losses, which is how a pre-registration
becomes decoration. If `section_edit`'s address is attacked again it needs a
mechanism nobody has looked at yet and a rule written before the looking.

## F-transport — a server fault was a model outcome for seventeen trials, and the census was short

`grade_one`'s first line mapped any `trial["error"]` to `malformed`, and
`trial["error"]` is whatever exception the run loop caught — including
`HTTPError: HTTP Error 500` from the model server, where `turns` is empty and no
schema could have changed anything. The open item that named this said **10
trials on disk**, over the five pools it had checked, and explicitly left the
other three unchecked. A sweep of every `*.jsonl` in `bench/results/` finds
**17**, and every single one is the same string:

| pool | n | published number it feeds |
|---|---|---|
| `armb_s6_section_kids` | 4 | S6's three-scheme table (3 of the 4; the fourth is superseded) |
| `s14_source_section_kids` | 3 | none on disk — no graded counterpart |
| `armc_sections` | 2 | Arm C sections |
| `armc_replay_path` | 2 | F-framing's replay pool |
| `armb_s14_section_kids` | 1 | none on disk |
| `armb_s15_section_g_file` | 1 | none on disk |
| `compose_4_sections` | 1 | F-compose's localization table |
| `compose_5_sections` | 1 | F-compose's sections row |
| `anchor_control_compose_5` | 1 | F-reach (already dropped, pre-registered) |
| `anchor_treat_compose_5h` | 1 | F-reach (already dropped, pre-registered) |

Seventeen rather than ten is not a new defect; it is the item's own "plus a pass
over the other three pools", done. Worth stating anyway, because the shape
recurs in this file: **a count in an open item is a count over the pools that
were checked, and it ages.**

### The fix, and why it is a class rather than a drop

`transport` is an outcome, not a silent exclusion. The item was right that a
dropped trial is invisible and these were found by grepping for `malformed` with
an `HTTPError` detail — so the class keeps them greppable and adds a count to
every report. `stats.py` drops the **pair** from both arms, because a fault on
one side says nothing about the other, and prints which trials it dropped.
`armc.grade_one` shares `armb.TRANSPORT_ERRORS` rather than reimplementing the
test, since "byte-identical criteria" has to hold for this class too.

The type list is explicit rather than a catch-all. Anything raised *after* a
completion arrives is a fault in the harness or in what the model sent, and both
belong in `malformed`. A 4xx would be a harness fault rather than a server one,
which is why the detail string is printed beside the count instead of being
absorbed into it.

### What moved, and what did not

**One published discordant count, and it was already known.** F-reach recorded
the corrected sections row by hand; the instrument now produces it:

| | before | after |
|---|---|---|
| sections, `solo` vs `compose_5` | 130/150 vs 117/150, 14–1, p = 0.00098 | 129/149 vs 117/149, **13–1, p = 0.001831** |

Two routes agree, which is what the number needed.

**Nothing else changes a discordant count.** Both rows of F-compose's
localization table keep theirs exactly — `solo` vs `compose_4` is 29–8,
p = 0.00075 over 419 pairs instead of 420, and `compose_4` vs `compose_5` is
11–9, p = 0.82 over 418. The dropped trials happened to be concordant. The
conclusion the table exists for — *"whatever the composition costs, it is not the
read tool"* — is untouched.

**S6's table restates, and its finding does not.** Three of the four transport
trials are in the published merge, so under the drop rule all three schemes lose
the same three trials:

| | published | pair-dropped |
|---|---|---|
| `section_g` | 127/150 = 84.7% | 125/147 = 85.0% |
| `section_2call` | 126/150 = 84.0% | 123/147 = 83.7% |
| `section_kids` | 129/150 = 86.0% | 129/147 = 87.8% |

The spread widens from 2.0 points to 4.1 and is still noise, which is what S6
said. What S6 is actually *for* — `children` doubling the score on the three
multi-section tasks, 12 → 26 of 30 — does not move at all: all three dropped
trials (`promote-api` ×2, `notes-second-ordinal`) are in the twelve others.

**Arm C moves by denominator only**: sections 120/151 → 120/149, the replay pool
19/106 → 19/104. Those two files were flipped row-wise rather than re-graded,
deliberately — `armc.grade_one` re-executes every call through a built binary,
so a full re-grade answers a different question than this one and would mix the
two.

### Two things found on the way, neither of them this defect

**The S6 graded pool on disk does not reproduce S6's table on its own**, and
that is correct rather than broken: `armb_s6fix_section_kids` re-ran two tasks,
and the published table is the merge with the re-run overriding. Re-grading the
base pool today moves four `insert-troubleshooting` rows from `wrong` to
`correct` — rows the merge discards, so no published number depends on them. The
cause is not recoverable from git (both files predate the baseline squash) and
is not pursued; what matters is that the merge is 129/150 before and after,
identically.

**`armc_sections_graded.jsonl` has 151 rows for a 150-trial arm** — one
duplicated `(insert-release-at-top, 1)`. This is the population-counting hazard
`bench/population.py` exists for, showing up in a file rather than in a census.
Recorded, not fixed here.

## F-agree — two replays of the same calls, and nothing asked whether they agreed

`headroom.py` and `regrade_snapshot.py` both replay every recorded tool call.
They were written months apart for different questions — one prices a pending
re-measurement, the other proves an executor change disturbed no grade — and
until now nothing compared them.

That is not a hypothetical. The same defect was in both, and was fixed in one
and left in the other, inside a single release:

| | `headroom.py` | `regrade_snapshot.py` |
|---|---|---|
| the defect | reads skipped, yielding `err=None` | reads fed to `apply_op`, yielding `unknown operation "table_get"` |
| what it cost | F-remedy's candidate reported **UNTESTED at k=0** with ten reaching calls on disk | **"no recorded call changed behaviour"** for a change that rewrites the refusal those ten calls draw |
| when it was fixed | during F-remedy's control arm | a week later, one command before the treatment arm would have shipped on it |

One replay knew and the other did not, and the only reason the second was found
is that its answer was implausible enough to look at twice. A defect that hides
behind a *plausible* zero survives.

### The check, and why it is not a shared function

`bench/replaycheck.py`. Each module exposes `disposition(name, raw_args)` — its
own rules, in its own file — and the checker walks every recorded call and asks
both. The obvious alternative, factoring the routing into one function both
call, is the wrong fix here: two copies that call one function cannot drift, but
they also cannot *demonstrate* agreement, and the value of a second
implementation is that it was written by someone asking a different question.
The extraction is a pure refactor in both, so `regrade_snapshot.py`'s recorded
strings (`arguments-did-not-parse`, `normalize-raised …`) are byte-identical and
no snapshot key moves.

**13361 recorded tool calls, both replays asked about each:**

| `headroom` | `regrade_snapshot` | calls |
|---|---|---|
| edit | edit | 12629 |
| skip | edit | 379 |
| read | read | 344 |
| skip | skip | 9 |

The 379 are Arm A's `patch`, and the asymmetry is correct in both directions:
`headroom.py` counts a population and must not manufacture `unknown operation
"patch"` 380 times as a sentence some model read, while `regrade_snapshot.py` is
a regression corpus over calls and what the executor does with an unknown name
is a real signal. That reasoning is now in `EXPECTED_ONE_SIDED` with the
sentence attached, so the list is the difference between a justified asymmetry
and an unnoticed one. Everything else agrees, and a `read`/`edit` split — the
class that cost two findings — fails the check outright.

### The load-bearing coincidence nobody had written down

The two modules do not test the same thing. `headroom.disposition` asks
`op in armb.READS`; `regrade_snapshot.disposition` asks `name in armb.READS`.
Those agree **only** because `READS` is keyed by tool name and `armb.normalize`
returns the tool name unchanged for a read. The day a read is given an op name
of its own, the two modules disagree on every read call and neither would say
so. `replaycheck.check_reads_keying` asserts it instead: for every name in
`READS`, `normalize(name, {})[0] == name`.

This is the finding under the finding. The read-blindness bug was two instances
of one mistake; what made it survivable was that the invariant tying the two
replays together lived in nobody's head and no file's assertion.

## F-narrow — S13 ended on a design constraint nobody tested, and this tests it

S13 measured `children` on `section_edit` and found it paying for itself twice
over on the three tasks it exists for (12 → 26 of 30) while costing twelve
points on the twelve that ignore it (115 → 103), with `malformed` rising 0 → 3
and single-call correctness falling 98% → 94%. The conclusion it drew was a
sentence about design rather than about `children`:

> **A field costs something to every task in the tool, including the ones that
> ignore it.** That is a design constraint on the op vocabulary, not an argument
> against `children`: it says a nested payload belongs on a tool narrow enough
> that the tasks paying for it are the tasks using it.

That sentence has been carried in the open list since, unmeasured. A tool narrow
enough is `section_create`, and this is the arm.

### The pre-registration, written before the run

**Condition.** `bench/tasks/sections.json`, 15 tasks × 10 trials, seed = trial
index, `--turns 4 --result-shape delta`, three cells, 450 trials.

| cell | `section_edit` | second tool |
| --- | --- | --- |
| `section_g_hpath` (control) | adopted, unchanged | — |
| `section_kids_hpath` | `body` documented prose-only, `children` added | — |
| `section_split_hpath` | `body` documented prose-only, no `children` | `section_create`, carrying `children` |

All three at the adopted address spelling. S13 ran before S15, so `section_kids`
spells the section address `path`; re-running that schema as it stands would
answer a question about a schema that has since lost its own comparison. Both
new cells are `section_g_hpath` plus a stated delta, and both document `body` as
prose-only — so S13's other change is held constant and is not re-measured.
`section_create` is derived from `section_g_hpath`'s tool by three mechanical
transforms, listed in `bench/armb.py` beside the code that applies them.

**The two routes are both offered, on purpose.** The enum invariant — one tool
name, one action enum, across every scheme in the file — means dropping `insert`
from `section_edit` is a new world for all of them, which is what F-realign
spent two runs learning. So the treatment publishes `section_create` *beside* a
`section_edit` that still inserts, which is what shipping it would publish, and
the question it asks is whether the narrow tool gets found.

**Endpoints.**

- **Primary: the twelve non-target tasks, 120 pairs, `split` against `kids`.**
  This is where S13's tax was, and it is where the design constraint is either
  true or false.
- **Secondary: the three target tasks** (`insert-release-at-top`,
  `insert-nested-ratelimits`, `insert-troubleshooting`), 30 pairs, `split`
  against `kids`.
- **Tertiary:** `split` against the control, all 150.
- **Reproduction (the clap rule):** the control against S15's recorded 127/150,
  same tasks, same seeds, same shape.

**Predictions.**

1. The control lands within 10 of S15's 127/150. If it does not, nothing else in
   this run is readable and the run stops there.
2. `split` beats `kids` on the twelve non-target tasks, recovering most of
   S13's twelve-point tax, because the field the model pays for is no longer in
   the tool those tasks call.
3. `split` is within a few points of `kids` on the three target tasks. This is
   the prediction with the risk in it: the gain is only collected if the model
   reaches for the narrow tool, and nothing in the schema tells it to.
4. `malformed` on the twelve returns to the control's level.

**Decision rule.** Recommend a `compose_6` arm — the only thing that could put
a sixth tool in `schema.rs` — iff *all three* hold: **(a)** the control
reproduces per prediction 1, **(b)** `split` loses no more than **3** points to
the control across the twelve non-target tasks, and **(c)** `split` scores
**≥ 20/30** on the three target tasks, against the control's 12/30 and `kids`'
26/30 in S13. Anything else is a finding, not a ship: in particular, `split`
clearing (b) and failing (c) is the result "a narrow tool is not found", which
settles the open item in the opposite direction and is worth the GPU either way.

**Transport faults** are dropped from the pairing and reported as a count, per
F-transport. **Caveat 21 applies**: these trials are evidence for the schemes
they were shown.

**What this run cannot do.** The secondary endpoint has 30 pairs against a floor
of 6, so an effect there smaller than about six points is indistinguishable from
none, and prediction 3 can be confirmed only weakly. The ceiling check is
45/45 across the three cells, but the ideal calls for the target tasks are
multi-call and do not use `children`, so it proves both routes are expressible
and does not price the payload — S13 and the differential suite do that.
`section_create`'s own wording cannot move the primary endpoint, because the
twelve tasks never call it; it can move the secondary, which therefore reads as
"a narrow tool, described for its one job".

### The result: the narrow tool is found every time, and the tax it was built to remove is not there

450 trials, three cells, **zero transport faults**, all at `--turns 4
--result-shape delta`, `gemma4-direct-q8`. Per task, out of 10:

| task | control | `kids` | `split` |
|---|---|---|---|
| `insert-release-at-top` | 4 | **9** | **3** |
| `insert-nested-ratelimits` | 4 | 5 | **9** |
| `insert-troubleshooting` | 2 | 7 | **10** |
| `insert-subsection-last` | 10 | 10 | 8 |
| `append-hotfix-note` | 10 | 8 | 10 |
| `promote-api` | 10 | 7 | 9 |
| `append-after-fence` | 10 | 10 | 9 |
| the other eight | 10 each | 10 each | 10 each |
| **total** | **130** | **136** | **138** |

**Prediction 1 holds and the clap rule is satisfied.** The control is 130/150
against S15's recorded 127/150, well inside the ±10 band, so the rest of the run
is readable.

**Prediction 2 fails, and it fails vacuously.** The primary endpoint —
`split` against `kids` on the twelve non-target tasks — is **5–4, p = 1.0000**
over 9 discordant pairs. Nine is above the floor of 6, so this is a *readable*
null rather than an underpowered one: a total effect would have been visible and
there is none. The reason is upstream of the comparison. S13's twelve-point tax
does not exist on today's schema: `kids` costs the twelve **5 points** against
the control (120 → 115, 5 discordant, p = 0.0625) and `split` costs **4**
(120 → 116, 4 discordant, p = 0.1250), both *below* the floor. The arm was built
to recover a tax that, restated at the adopted address spelling and the
four-turn delta shape, is already too small for the instrument to see.

**Prediction 3 holds, and the risk it named is decisively resolved.** `split` is
22/30 on the three targets against `kids`' 21/30 — 8–7, p = 1.0000 — and both
are far above the control's 10/30 (`split` against control: 14–2,
**p = 0.0042**). The pre-registration's stated risk was that *"the gain is only
collected if the model reaches for the narrow tool, and nothing in the schema
tells it to."* It reaches for it **30 times out of 30**. Leakage the other way is
almost nil: `section_create` appears in 10 of 120 non-target trials, 9 of them
`insert-subsection-last`, which is a `section-insert` task and therefore correct
use. **The genuine cross-family misuse is one trial in 120 — `promote-api`, a
`set-level` task — and it was destructive.** That is the sixth tool's cost,
visible in the calls and below any floor, which is the F-anchor shape exactly.

**Prediction 4 has no population.** It predicted `malformed` on the twelve
returning to the control's level; `malformed` occurs **zero times in all 450
trials**, control included. Nothing to return to.

### The decision rule, applied as written

- **(a)** the control reproduces — **yes**, 130 against 127.
- **(b)** `split` loses no more than 3 points to the control across the twelve —
  **no**. It loses **4** (120 → 116).
- **(c)** `split` scores ≥ 20/30 on the three targets — **yes**, 22/30.

All three were required. **No `compose_6` arm is recommended, and
`section_create` does not ship.**

It failed by one trial, and the rule stands anyway — that is what pre-registering
is for. Worth recording *about the rule* rather than about the result: (b) was
calibrated expecting a control near S15's 127/150, and the control came in at
**120/120** on the twelve. A perfect control turns "loses no more than 3" into a
bar that any four-loss arm fails regardless of what the treatment did, which is
a tighter test than was intended. This is stated **post-hoc and changes
nothing**; it is guidance for writing the next rule, not grounds for reading
this one differently.

### What the aggregate hides, and it is the most interesting thing here

22 against 21 on the three targets looks like a tie. It is a complete reshuffle:

| | `insert-release-at-top` | `insert-nested-ratelimits` | `insert-troubleshooting` |
|---|---|---|---|
| `kids` | 9 | 5 | 7 |
| `split` | 3 | 9 | 10 |

`split` is *better* on two of the three — 10/10 on the one the control scored
2/10 on — and collapses on the third. That collapse is one mechanism, and it is
clean:

| cell | anchor chosen for the new release | n |
|---|---|---|
| control | `Changelog > [1.4.2] - 2026-08-14` | 10/10 |
| `kids` | `Changelog > [1.4.2] - 2026-08-14` | 10/10 |
| `split` | **`Changelog > [Unreleased]`** | **7/10** |

The instruction says *"immediately above the [1.4.2] release."* Both cells
holding `children` on `section_edit` anchor on `[1.4.2]` every time. The cell
holding it on `section_create` anchors on `[Unreleased]` seven times out of ten
— the top-most section, not the named one. The executor is blameless: replaying
the failing call produces a clean additive diff that does exactly what it was
asked, six lines inserted, nothing else touched. **This is a targeting error
with a tool-shaped cause, and this run cannot say which part of the tool caused
it.** The candidates are its name, its one-job framing (*"Create a new section in
a markdown document"*), and the `section` description rewritten to *"Which
EXISTING section the new one goes relative to"* — all three arrived together and
would need their own arm to separate. It goes on the open list as a mechanism,
not as a verdict.

**A grading observation, worth one line.** All seven of those trials grade
`collateral:content` — *"text before the edited region changed"* — because the
section landed higher than the golden, so the golden's leading region differs. A
wrong-anchor insert is therefore reported in the outcome table as content
collateral rather than as `wrong`, which makes a targeting miss look like
corruption. It is the only `collateral:content` in the run, and it is not
corruption.

### What this settles

S13's closing sentence — *"a nested payload belongs on a tool narrow enough that
the tasks paying for it are the tasks using it"* — comes off the open list, not
confirmed and not refuted but **dissolved**. Its premise was a twelve-point tax
that the current schema does not carry; what remains is 4–5 points on either
design, below the floor, and moving the payload to a narrow tool moved none of
it. The sentence's *other* half, the one that sounded like the risky part, is
the half that held: a narrow tool is found, 30 times out of 30, without a word in
the schema telling the model to prefer it.

**Caveat 21 applies**: these trials are evidence for the schemes they were shown.

## F-mirror — the plugin's tool list is built at runtime, and a grep said otherwise

F-realign's closing paragraph said the plugin does not offer realign, and gave
its evidence: *"`realign` appears nowhere in `plugins/hermes/`."* The grep is
still accurate today. The conclusion was wrong the moment it was written.

`plugins/hermes/schema_cache.py:edit_tools()` does not contain a tool list. It
shells out to `incise schema` and registers what comes back, and
`plugins/hermes/__init__.py:normalize` composes the op name generically —
`"table-" + str(args.get("action"))`. Neither file can mention `realign` and
both route it. Driven end to end:

```
plugin publishes 5 tools: table_edit, list_edit, section_edit, frontmatter_edit, table_get
  table_edit ['add-row', 'update-cell', 'delete-row', 'realign']
normalize: ('table-realign', {...})
```

and `incise table-realign --json` on the result returns `ok: true` with the
table re-padded. **The plugin gained realign in the commit that shipped it to
`schema.rs`, with no plugin edit, no review, and nothing that would have said
so.** The "separate decision" F-realign left open had already been taken by the
architecture.

### What this is an instance of

A reachability claim about a component that constructs its surface at runtime
cannot be answered by reading the component. Every previous reachability
argument in this file is about `armb.SCHEMES` or `schema.rs`, which are
literals, so grep-shaped evidence was sound and the habit transferred to a place
where it is not. The 27.6% silent-corruption mechanism F-realign's control cell
measured was, on this reasoning, believed to still apply to plugin callers for
as long as the paragraph stood.

### The check that replaces the grep

`plugins/hermes/test_plugin.py` gains
`test_every_published_action_can_be_invoked()`. It asks the **binary** for its
own op list rather than hardcoding one — `incise table-frobnicate` answers
`unknown operation "table-frobnicate". Valid: …`, the same sentence the
`table-realign` open item is about — then asserts that every action in every
published enum normalizes to an op on that list. It asserts the control op is
absent from the list, so a parse that silently returned everything would fail,
and it writes nothing, so it needs no fixture and cannot trip `safety.py`.

It passes, including `table_edit action=realign reaches table-realign`.

The gap it closes is not realign specifically. Nothing anywhere asserted
**action-level** reachability through the plugin: an enum entry whose CLI
subcommand did not exist would have been forwarded and failed at the user, and
the existing structural invariants — every renderer has a tool, no read
publishes an edit property — all check shape rather than reach.

### Not fixed here

`table-realign`'s success line reads *"Applied: changed text outside any
heading. (+3 lines, -3 lines.)"* — `describe_change` derives its sentence from
the two documents rather than from the op, so the one op that changes no cell
text is reported as changing text. It is the same mechanism as the open
`describe_frontmatter_change` item and is recorded there rather than as a new
one; fixing it inside this finding would be a model-facing wording change with
no number behind it.

## F-asrun — the shipped composition drifted by one enum entry, and the guard could not see it

`schema.rs`'s contract has two clauses. Each tool's text is byte-identical to
the single-tool scheme that won its comparison, **and** the set of five has been
run end to end. `schematest.py` has only ever checked the first. Its own
docstring said so — *"the set is a separate claim with a separate measurement …
and nothing here watches it"* — and the gap turned out not to be hypothetical.

F-realign made the realign augmentation unconditional. The augmentation mutates
`scheme_f`'s `table_edit` **in place**, and `compose_5` holds that object by
reference rather than copying it, so the shipped composition gained a fourth
action the composition arm never ran. Every per-tool check still passed, because
both halves of `ADOPTED` moved together: the shipped `table_edit` and the
adopted `scheme_f` are the same object.

### What actually drifted, located rather than estimated

`compose_5` at `df247d4` (F-compose) is byte-identical to `01da741` (F-anchor),
so there is one unambiguous as-run composition and not a range of them. Against
today's it differs in exactly two places, both the same change:

| path | measured | shipped |
|---|---|---|
| `table_edit.description` | three action lines | four — one appended realign line |
| `table_edit.parameters.properties.action.enum` | 3 entries | 4 |

Nothing else in the five tools moved. The 3.2-point composition cost is
therefore quoted for a set one enum entry away from the one that ships, which is
a smaller discrepancy than "unmeasured" and a larger one than "guarded".

### The record, and why it is generated once

`bench/compose_5.measured.json` is `armb.SCHEMES["compose_5"]` as it stood at
`df247d4`, written out once from git. `check_composition` walks the shipped set
against it and requires every difference to be listed in `COMPOSITION_DRIFT`
with a justification. Regenerating the file would turn the check into a
comparison of the shipped set with itself, so the file says so in a `_comment`
and names the two runs it is the record of.

**The listing is keyed on the message, not the path.** Keying on the path alone
would let any future change to `table_edit.description` inherit realign's
justification — the `ALLOWED_BACKTICKS` mistake in a new place. `allowed_matches`
pins each entry to the specific text it excuses; verified by fabricating a
second description change and confirming the check still fires.

`schema.rs`'s contract paragraph now says which clause each guard covers, and
the three-claims sentence reads *"the set of five has been run end to end modulo
the one listed line"* rather than claiming a clean set.

### What this does not do

It does not re-measure anything. A composition arm is the only thing that can
retire the drift, and this finding deliberately does not recommend one: the
table family was 60/60 both ways under `scheme_f_realign`, so the best available
estimate of this line's composed cost is zero, and spending an hour of GPU to
confirm a prediction of no change is the arm F-wart's rule exists to refuse.
What was missing was not the number but the **record** that the number is owed.

## F-width — an operator's refusal became product text, and no arm can price it

Shipping `action=realign` (F-realign) changed the class of a sentence without
changing a byte of it. Until then `table_edit` published three actions, realign
was not one of them, and the width refusal —

```
this table contains "値", which does not occupy one display column, and incise counts column width in characters.
  Re-padding it would produce a table that is aligned by that count and ragged on screen, which is the opposite of what realign is for.
  First such cell: "値"
  Realign is refused. Add, update and delete still work on this table and leave its existing lines byte-for-byte intact.
```

— had exactly one caller: a human at a CLI. Publishing the fourth action made
the same bytes **model-facing**, which puts them under §5.3, on a path no arm
has ever run. That is the whole finding: not that the refusal is wrong, but that
it quietly acquired a contract nobody checked it against.

### Priced with the instrument rather than argued about

`headroom.py` gains a candidate, `side: "executor"` — the refusal cannot alter a
trial that never reaches it, so `k` bounds the result in **both** directions,
unlike a description change where `k` bounds only the gain. The verdict is
**UNTESTED at k = 0 of n = 2341** adopted trials: no recorded call in any pool
draws it, because no task fixture and no corpus file has a table containing a
character wider than one column. Against a floor of 6 discordant pairs this is
not "nearly unmeasurable", it is unmeasurable by any paired run of any size, and
the reason is the same one F-remedy hit — this is a **task set to build**, not a
result to interpret.

### The decision

**The wording ships unmeasured, and that is recorded rather than repaired.** A
re-wording here would be model-facing text with no number behind it, on a branch
where no number can be obtained, which is F-wart's rule at its sharpest. The
refusal is also correct on the merits — it refuses rather than writing a
misaligned table, exits 1, names the offending character, and says what still
works — so the change on offer is a preference, not a fix.

What has been added instead is a test, because an unmeasured promise should at
least be a kept one. `test_realign_width_refusal_keeps_its_promise` in
`bench/test_incise_ops.py` asserts the refusal fires on a ragged table
containing `値`, that it names the character, that it ends with the exact remedy
sentence, and — the part that matters — that `table-add-row`,
`table-update-cell` and `table-delete-row` all still **succeed** on that same
table and leave every line they did not edit byte-identical. The refusal's
promise is that only realign is unavailable; nothing checked that promise
before.

This is the same disposition as the mixed-line-endings refusal in F-remedy, and
the two are cross-referenced there: at k = 0, a correct refusal keeps its
wording.

## F-valid — the fifteen-name refusal became honest by capability, not by wording

Two open items make the same complaint about one sentence. The `table-realign`
item: the `unknown operation "table-None". Valid: …` refusal "is wrong for a
model, which has three tools and cannot reach twelve of the names it is being
offered". F-terminal's closing line: "naming all fifteen ops to a model that can
reach fourteen is still a §5.3 defect — see the `table-realign` item". Both are
now false of the product, and neither was closed by touching the sentence.

### The surface grew out to meet the sentence

`schema.rs` publishes five tools carrying fifteen `action` entries between them,
and `armb.normalize` — the executor's own tool-call-to-op mapping — sends those
fifteen to fifteen distinct ops:

| tool | actions | ops reached |
|---|---|---|
| `table_edit` | 4 | `table-add-row`, `table-update-cell`, `table-delete-row`, `table-realign` |
| `list_edit` | 3 | the list family |
| `section_edit` | 6 | the section family |
| `frontmatter_edit` | 2 | `frontmatter-set`, `frontmatter-delete` |
| `table_get` | — | a read; no `action` enum, and `table-get` is not an op |

Fifteen ops, fifteen reachable, none unreachable. `table-realign` was the last
name in `OPS` no published action could reach (F-realign), and frontmatter was
the last family in `OPS` that no tool published at all (F-frontport). Neither
was undertaken to fix this sentence; both fixed it anyway. That is F-wart's rule
landing on the useful side for once — the re-wording these items kept asking for
would have been model-facing text with no number behind it, and waiting turned
it into no edit at all.

### No recorded trial has ever read the honest version

`headroom.py`'s `F-action` candidate counts **26 calls across 21 trials** that
draw the sentence, in nine schemes. Every one of them read a version that was
lying, and the interesting part is which lie:

| schemes | trials | ops reachable, as run |
|---|---|---|
| `front_p`, `front_naive` | 2 | 2 of 15 |
| `list_naive`, `list_i` | 5 | 3 of 15 |
| `scheme_f_realign` | 1 | 4 of 15 |
| `compose_3` | 4 | 12 of 15 |
| `compose_4`, `compose_5`, `compose_5h` | 9 | 14 of 15 |

The last row is F-asrun's drift showing up in a second place. The composition
arms **are** the five-tool condition `schema.rs` ships, but they ran before
realign was in the enum, so the closest any recorded trial came to the shipped
sentence was fourteen names of fifteen. There is no pool to re-grade here and
nothing to recover: the honest version has never been in front of a model.

Every call arrives the same way — `action` fused into the next JSON key, so the
op resolves to `table-None`, `list-None`, `section-None` or `frontmatter-None`.
That is `action_sizing.py`'s fused-`action` call, which is the only route to
this refusal that a tool-armed model has.

### The residue, priced rather than argued

Over the five adopted schemes the candidate is **k = 1 reachable of n = 2341**,
against `headroom.py`'s floor of 6 discordant pairs: **UNDERPOWERED, best
achievable p = 1.0000**. It is an executor-side change, so the one-sided rule
applies in its strong form — a refusal cannot alter a trial that never reaches
it, and `k` bounds the result in both directions, not just the gain. Re-wording
the sentence now is not merely unnecessary, it is unmeasurable.

### What was actually missing was the converse invariant

The forward direction is asserted twice. `armb._actions_from_schemes` raises if
a scheme publishes an action the executor cannot run — "a refusal naming them
would send the model somewhere that refuses again" — and
`test_every_published_action_can_be_invoked` in `plugins/hermes/test_plugin.py`
invokes all fifteen published actions for real. The converse — every op in the
binary's own `Valid:` list is reachable from some published action — was
asserted nowhere, which is how it stayed false for months without anything
noticing. A sixteenth op added without an enum entry would reinstate the defect
in exactly the same silence.

`check_every_op_is_reachable` in `bench/schematest.py` closes that. It makes the
binary read its own op table aloud (`incise table-frobnicate … --json`, the same
probe the plugin's forward check uses), maps every shipped `action` enum entry
through `armb.normalize`, and reports both directions. Negative-controlled in
both: deleting `realign` from the shipped enum reproduces the historical defect
by name, and adding an action the executor has no op for is caught as the
mirror-image fault.

### What stays open, narrowed to what it is

For a **single-tool Arm B scheme**, the sentence still names fifteen ops to a
model holding two or three, and 8 of the 21 recorded trials read it that way.
That claim survives, but it has shrunk from "the product misleads" to "Arm B's
schemes mislead", and Caveat 21 already covers it: trials are evidence for the
schemes they were shown. The fix there is the front-end scoping the
`table-realign` item names — a refusal that lists what *this caller* can reach —
which is a change to Arm B's executor that would move every recorded digest, so
it is not something to do incidentally. Nothing about the shipped five-tool
product depends on it.

## F-provoke — two refusals nothing could reach, and the harness defect that building the reach exposed

`headroom.py` returned **UNTESTED at k = 0** twice in one session, for F-width
and for F-remedy's section half, and both times for the same reason: *"no
adopted trial reaches the branch… This is a task set to build, not a result."*
That verdict is not a finding about the product. It is the instrument reporting
a missing input, and the only thing that answers it is the input.

Two synthetic fixtures and two task sets. Neither has been run; both are
pre-flight-gated and one of them deliberately fails that gate. The finding is in
what building them settled — one of F-remedy's two claims is now false, one of
my own premises was false, and ten fixture reads in the harness were not reading
the fixture.

### The section half was called unbuildable, and it was buildable

F-remedy's disposition was explicit: *"The section half is not a wording arm and
cannot be made one… A task asking for an append to a mixed-ending section has a
ceiling of **zero** — `section-append` and `section-replace-body` both refuse…
at any argument — so it fails the pre-flight gate by construction."* It
concluded the case was a **capability** question and closed it.

The ceiling is not zero. `section-delete` is the one body-touching op that never
calls `_section_eol`, and a section deleted and re-inserted against a sibling
whose endings are uniform comes back written in one convention with the edit
applied. So the remedy the refusal names — *"Normalize the section's line
endings first, then retry."* — **is performable, in two calls**, and the price
is that the model must retype the body it deleted. `bench/ceiling.py` on the new
set is **3/3** under `section_g_hpath`, verified end to end rather than argued:

| task | route | calls |
|---|---|---|
| `append-mixed-body` | delete, re-insert with the body retyped plus the new line | 2 |
| `replace-mixed-body` | delete, re-insert with the replacement the instruction supplied | 2 |
| `append-crlf-control` | `section-append`, one call, the section next door | 1 |

That narrows F-remedy's title rather than overturning it. *Unperformable* holds
for any **single op** — nothing in the five normalizes line endings — and fails
for the **tool set**, which is the unit the model actually holds. The refusal
still does not say any of that, which is the open question the set exists to put
a number on. A trial that reads the refusal and stops grades `op_error`, the
loud failure and the outcome most trials should be expected to reach; a trial
that finds the route grades `correct`. The pair separates discovery from cost:
`replace-mixed-body` is handed its replacement text, `append-mixed-body` has to
retype three lines it was never given, so if the two come apart the expensive
part is the retyping and not the insight.

**Why a new fixture and not `corpus/hazards/mixed-endings.md`.** F-remedy's
"at any argument" was true of that file's root section and false of its three
subsections — `section-append` succeeds on `LF section`, `CRLF section` and `LF
again`, and refuses only on `Mixed line endings`, whose span is the whole
document. The remedy is unavailable there for a reason that has nothing to do
with line endings: deleting the root deletes everything, and the root has no
sibling to anchor a re-insert against.
`bench/synthetic/mixed-endings-section.md` puts the mixing inside one leaf
section — a CRLF body with a single LF line in it — and gives it a uniform CRLF
sibling to anchor on. Without that shape the route does not exist and the
ceiling really would have been zero, which is how the earlier reading survived.

`bench/make_mixed_endings_tasks.py` generates the goldens the way
`make_section_tasks.py` does, and asserts more than it does: the window is
reassembled and compared byte for byte with `\r` intact, because these documents
differ from each other in line *endings* as well as in content and a window
computed on `\r`-stripped lines would rebuild into a document that looks right
and is not the one the reference produced.

### The width half has an instrument whose ceiling is zero on purpose

`bench/synthetic/wide-ragged.md`: three ragged tables, one with a CJK cell, one
with an emoji cell, one ASCII throughout. `bench/tasks/tables_realign_width.json`
asks for the same tidy-up on each.

**Raggedness is the whole design.** My stated premise for this work — that no
corpus or synthetic file has a table with a wide character — was wrong:
`corpus/tables/cell-edge-cases.md` has both CJK and emoji cells and `realign`
refuses it today. But that table is *already aligned*, so the refusal there
costs the model nothing and a task over it measures nothing. A ragged table with
a wide cell is the only shape where the refusal denies something the model was
asked for.

`ceiling.py` returns **1/3**, and that is the construction rather than a broken
instrument. `armb.grade_one`'s ladder reads `if doc == before: if errors: return
"op_error"` — an unchanged document can never grade `correct` for an edit
family, so a task whose correct outcome is *a refusal honoured* has a ceiling of
zero by definition. The two provoking tasks fail the gate; the control passes.
The task file says so in its own `_comment` rather than leaving a future reader
to discover it against the gate.

So the endpoint is the **failure class**, not the correct-rate — the same
endpoint F-realign's control cell used, where 30 trials that could not say
`realign` said `update-cell` 54 times and destroyed the document 8 times:

| outcome | reading |
|---|---|
| `op_error` | the model drew the refusal and stopped. The good outcome |
| `destructive` / `wrong` | it re-padded or rewrote the table by hand |
| `collateral:formatting` | it prettified the ragged table as a side effect |

The provoking tasks set `require_aligned: false` so that last row can fire:
`grade.check_table_result` reports a ragged table that comes out aligned as
`collateral:formatting — "ragged table was prettified"` rather than passing it.
The control sets the inverse.

`headroom.py` no longer mislabels either of these. Both candidates gain an
`instrument` key and the `k = 0` verdict splits in two: **UNRUN** — *"the
instrument exists… This is GPU to spend, not a task set to build"* — where one
does. `provoking` is derived from recorded trials, so it stays empty until a
pool runs and can never see a task set that has been built and not yet spent GPU
on; the candidate has to say so itself. The third refusal in F-remedy's table,
the repeated header, needed nothing new: `duplicate-columns.md` and
`tables_read_remedy.json` were built for it there.

### What building the fixtures found: ten reads that were not reading the file

`mixed-endings-section.md` had to be written byte-exactly, which meant checking
what the harness did with it, which found this:

```python
before = open(os.path.join(ROOT, task["fixture"])).read()
```

Plain `open()` is universal-newline mode. Every `\r\n` in a fixture became `\n`
on the way in. **Ten sites** — four in `armb.py` (`build_payload`, `run_trial`,
`grade_one`, `replay`), one each in `armc.py`, `grade.py` and `runner.py`, three
in `test_incise_ops.py` — all now `open(..., newline="")`, the convention the
rest of the tree already used.

Nothing failed, and the reason it did not is the interesting half: **both** ends
were wrong in the same direction. The document handed to the model and the
`before` the grader compared against came through the same converting read, so
they agreed with each other perfectly. The harness was self-consistent and
measuring a document that was not the fixture on disk.

**Blast radius, bounded exactly rather than estimated.**
`bench/synthetic/realign-targets.md` is the only task fixture in the tree
containing a `CR`; `realign-crlf`, `realign-overpadded` and `realign-indented`
are the only tasks addressing it; `realign_ctl_realign` and `realign_trt_realign`
are the only pools that ran them — 60 trials. And the impact is measured, not
reasoned about, because the harness is deterministic under replay:

- Re-grading every Arm B row with the fixed reader: **0 of 6690 changed.**
- `regrade_snapshot.py` over **14095 recorded tool calls**: byte-identical, from
  a shadow copy of the HEAD arms against the fixed working tree.

Why no number moved: stripped to LF the table is still ragged, `realign` still
had work to do, and every mechanical check still applied. The fixture remained a
valid realign task. It just stopped being the **CRLF** task. What the defect
actually cost is the thing `realign-crlf`'s own note says it is for — *"Realign
rewrites all four lines, so it has to carry the file's per-line ending through
rather than normalizing it — the byte-preservation contract at its narrowest"* —
and that property was never exercised in Arm B. It stayed covered the whole
time by `difftest.py`, which reads with `newline=""`, which is why this is a
measurement gap and not a shipped bug.

### The cost of two new fixtures, paid

F-remedy reused `duplicate-columns.md` specifically to avoid this: `difftest.py`
globs `corpus/` and `bench/synthetic/`, so any new document invalidates its
cached snapshot and costs a full recompute. Here it was unavoidable and the
recompute is the entire price. **110406 cases over 54 fixtures (28 synthetic),
all agree with the oracle**, up from 107581 over 52; `cargo test` is 35 passed,
0 failed, with `crates/incise-core/tests/invariants.rs` globbing both new files
too. `plugins/hermes/README.md` and `test_plugin.py` quoted the old count and
now quote this one.

### Status

Neither set has been run, and this finding claims no rate. What it claims is
that two branches priced UNTESTED for want of an instrument now have one, that
one of the two was declared unreachable on a premise that does not hold, and
that the harness reading those instruments was quietly discarding the bytes one
of them exists to test.

## F-describe — the success line, counted instead of argued, and one of the two complaints does not survive

Two open questions had been sitting on `describe_change` for months, both
argued from single observed sentences and neither counted. `regrade_snapshot.py`
cannot settle either — it hashes the resulting document and the error string,
and the success line is in neither — so the item asked for "its own
`regrade_snapshot` enumeration over the calls that would move".
`bench/describe_census.py` is that enumeration. It borrows
`regrade_snapshot.disposition` rather than keeping a fourth copy of the rules
for what a recorded call executes.

### `table-realign`'s success line: the observation is real and the diagnosis is not

The complaint: `table-realign` succeeds with *"Applied: changed text outside any
heading. (+3 lines, -3 lines.)"* on the one op that changes no cell text — *"a
sentence that contradicts the op's guarantee, to a model that has just been told
realign is the safe repair."*

Every table in every corpus and synthetic fixture, realigned, addressed the way
`list_tables` reports it:

| | count |
|---|---|
| realigns to a changed document | **36** |
| of those, name their section — `changed the body of "Repeated header" (+2, -2 lines)` | **35** |
| of those, say "changed text outside any heading" | **1** |
| already aligned, described as a no-op | 70 |
| refused (3 non-rectangular, 3 wide-character) | 6 |

The one is `bench/synthetic/no-headings.md`, and it has no headings. The
sentence is not vague there, it is the only true thing available. `describe_change`
reaches its outside-any-heading fallback only when the heading-derived notes are
empty, and a table inside a section produces one. **The observed sentence was
real, the generalisation from it was not**, and the item's stronger claim — that
this is the stronger argument for doing the fold — falls with it.

What survives is smaller and is not a defect: realign is described as *"changed
the body of X"*, which is true of the bytes and silent about the guarantee that
no cell text moved. Vaguer than it could be, not contradictory, and changing it
would mean deriving the sentence from the op name — which is the property this
function was built not to have, because it is what keeps it correct for an op it
has never heard of.

### The fold: 36 pairs move, all of them true, and all of them worse

`describe_frontmatter_change` and `describe_change` are dispatched on the op
name in both implementations (`armb.py:1818`,
`crates/incise-cli/src/main.rs:451`). The stated reason for the split — the Rust
had no frontmatter parser — expired when F-frontport ported
`describe_frontmatter_change` into `ops/frontmatter.rs`; the docstring in
`incise_ops.py` still gives it and is stale.

"Which calls would move" is not answerable without a concrete fold, so the
census defines one in the smallest shape that could be correct: compute the
block's notes for **every** op (`_front_notes` already returns nothing when the
block's text is unchanged, so it is inert elsewhere), and compute the heading
notes on the body with the block stripped, so a block that grows is not also
reported as a change to the text before the first heading.

Over **1888 distinct recorded edit calls × 54 fixtures**, 1431 pairs apply and
change the document, and **36 are described differently**. Every one is a
`frontmatter-set` — 1950 recorded calls by weight — every one is true of the two
documents, and every one moves the same way:

```
now:    Applied: added a frontmatter block with 1 key; changed text outside the frontmatter block. (+4 lines.)
folded: Applied: added a frontmatter block with 1 key; changed text outside any heading. (+4 lines.)
```

That is the whole measured effect of the fold, and it is a **loss**. The
frontmatter-specific fallback names the region the model just edited; the
general one names a region the model was not asking about. It is S14's finding
in miniature — *"`describe_change` alone reports every frontmatter edit as
'changed text outside any heading', which is true and useless"* — surviving the
fold at exactly the one clause the fold reaches.

### The predicted hazard is real in the function and unreachable through the product

The dispatch comment predicts one specific fault: prepending text to a file that
opens with `---` moves the delimiter off line 0, `find_frontmatter` stops finding
a block, and the fold reports it as **removed**. A branch nothing reaches is
exactly what `headroom.py` spends its time distinguishing from a branch that is
safe, so it gets its own probe, in two parts, because the two answers differ:

- **Handed the document pair directly**, the fold lies, and the census catches
  it structurally rather than by reading the sentence — the block's bytes are
  still in `after`: `Applied: removed the frontmatter block; changed text
  outside any heading. (+2 lines.)` → `FALSE: block still present, reported as
  removed`.
- **Through a published op**: `section-insert position=before` against the first
  heading is the only call that writes above every heading, and on all 9
  frontmatter fixtures it displaces nothing. The block sits above every heading,
  so inserting before the first one still lands below it.

### The disposition

**No fold, and now for a reason with a count behind it rather than a stale one.**
The measured effect on the recorded population is 36 sentences that get vaguer
and none that get better; the hazard that justified the split is unreachable
today but would become reachable the moment any op learns to write above line 0,
and nothing asserts that none does. A fold that is worth taking would have to
keep the frontmatter-specific fallback wording and carry a displaced-block
guard — at which point it is two functions sharing a caller, which is what
exists.

The item's two halves separate cleanly and both are now closed: the realign
complaint is **withdrawn** (1 instance, on a document with no headings, where
the sentence is correct), and the fold is **declined on evidence**. What is left
open is one stale docstring in `incise_ops.py:2963-2971`, which still says the
Rust has no frontmatter parser.

## Measurement caveats

Recorded so later readers do not over-trust these numbers.

1. **The three families are graded differently, and the reports must say so.**
   For **tables** there are no goldens: `correct` means "passes every mechanical
   check" (row presence, column widths, delimiter bytes, byte-identity outside
   the target table), which is strict but is not the same claim as
   byte-identical. For **lists** there *are* goldens, exact and scoped to the
   target list, because a list's correctness is its formatting (L1). For
   **sections** the golden is the whole document, stored as a minimal changed
   window, because a section op can legitimately rewrite any part of the file.
   That makes the list and section ceilings 100% by construction, which is
   honest only because every golden was read line by line before being
   committed and `test_incise_ops.py::test_list_goldens` and
   `::test_section_goldens` assert the reference still produces them.
   S4 is the standing warning about what a ceiling check cannot see.
2. **Effective N is below nominal N.** Trials differ only by seed, and seeds
   collapse where the model is confident: 1–8 distinct outputs per 10 trials,
   and `update-cell-multi-table` produced byte-identical output all 10 times.
   The Wilson intervals above therefore understate uncertainty. B6 sharpened
   this: `scheme_c` and `scheme_e` differ in the schema text yet produced
   byte-identical arguments in 60/60 trials. Where two conditions agree that
   completely, "p = 1.000" is not a null result from independent samples — it
   means the model emitted the same tokens, which is a stronger claim than the
   test can express, and one that may not hold for a different model.
3. ~~Repeat penalty is uncontrolled.~~ **Resolved — see F7.** The baseline runs
   at the server default `1.15`; a matched 60-trial control at `1.0` moved the
   result by +1/60 (p = 1.000) and left the re-pad task at 0/10. No longer a
   confound.
4. ~~**Six tasks, one family.**~~ **Partly resolved — L1–L6, S1–S14.** Three
   families now, 31 tasks. That was worth doing twice: the second family
   *inverted* a conclusion the first had reached (L2), and the third broke the
   strongest claim either had produced — "Arm B silent corruption is zero" —
   with 26–29% (S1). Frontmatter (PLAN.md §4.4) remains unmeasured and nothing
   here should be generalized to it.
5. ~~**Sections have no Arm A baseline yet.**~~ **Resolved — S7.** 19.0%
   correct, 28.0% data loss, one condition (`reasoning_off`). The 58%/63% in
   S1 can now be read against something. One condition is a real limit, but F5
   measured reasoning as a 16× token tax for zero net gain, so the untested
   condition is the expensive one rather than the favourable one.
6. ~~**Two section tasks measure less than they appear to.**~~ **Resolved —
   three tasks added, see S9.** The original problem: `append-hotfix-note`
   cannot distinguish `append` from `replace-body`, because the `[1.4.2]`
   release has no body of its own and the two produce byte-identical output —
   so the append/overwrite distinction was measured by exactly one task,
   `notes-second-ordinal`, which is where all six data-loss trials came from
   (S2). `append-atx-line`, `append-macos-note` and `replace-linux-body` now
   pull in both directions: two where `append` is right and overwriting loses
   prose, one where replacing is right, so a fix for S2 cannot be "remove
   `replace-body`". All three score 10/10 in `section_g` — which means they add
   no discrimination *at this scheme's competence level* and their value is as a
   regression floor, not as evidence for the 80%.
7. **`section_naive` and `section_p` were never run against the guarded
   executor.** S8's v2 column is a re-grade of the v1 trials, not a new sample.
   That is exactly right for measuring an executor change — same tool calls,
   different execution — and exactly wrong for anything else: a model given the
   guard's error message might have retried differently, and a re-grade cannot
   see that. Where the guard makes the correct call *inexpressible*
   (`replace-install-preamble`, no `overwrite` field), the v2 number is a
   statement about the vocabulary, not about the model. **Partly answered by
   S12:** the retry pass *is* a live second turn against the guarded executor
   for every `op_error` trial in both arms, and none of those 61 turns produced
   a destructive outcome — three of them are models bouncing off the S3 guard
   on the way to a data loss. That covers the trials the guards changed; it
   still does not cover a first turn taken with a guarded schema in context.
8. ~~**`insert-release-at-top` is really a test of S6.**~~ **Resolved — S13**,
   in the opposite direction from the one this caveat assumed. It was never
   solved by any scheme, and the reason turned out to be two defects rather than
   one difficulty: the single-turn harness (a two-call task graded on one call)
   and an instruction that paraphrased the body text a whole-document golden
   pins exactly. Both fixed, it scores 4/10, 8/10 and 9/10 across the three S13
   schemes. It does still test the payload — that is what separates 4 from 9 —
   but it was reading mostly as a harness result.
9. **One answer key moved to agree with the trials, once.**
   `insert-troubleshooting`'s ideal call made the new section a sibling of the
   H1; all 30 trials made it a child. Both put the bytes in the same place, and
   the instruction named no level, so the task was under-specified and the
   correction names the anchor (S13). This is the one place in the project where
   a golden changed after seeing model output, and it is called out here rather
   than folded into the task note because "the model disagreed, so the task was
   wrong" is exactly the reasoning that re-baselines a benchmark to whatever the
   model does. The defence is that the levels are still derived and still absent
   from the instruction — but a reader should weigh `insert-troubleshooting`'s
   numbers knowing this.
10. **Not hermes.** The schema is replicated verbatim, but the surrounding
   system prompt is not hermes's (PLAN.md §2.4). This measures hermes-*style*
   editing.
11. **Arm B measures addressing, not formatting.** By design the executor owns
   formatting, so Arm B's `correct` rate is the rate at which the model *names*
   the right table, list, row or item. Formatting correctness is verified
   separately and must be, or the two claims get conflated: `bench/ceiling.py`
   confirms every ideal tool call grades `correct` in every scheme (12 for
   tables, 50 for lists, 45 across the three S13 section schemes on 15 tasks,
   multi-call tasks expressed and graded as whole sequences; `section_naive` and
   `section_p` reach 11 of 13, the two `overwrite` tasks being inexpressible in
   those vocabularies — S8), and `incise_ops.py` round-trips all
   15 table-bearing corpus files, all 49 corpus lists and 755 section
   insert↔delete probes byte-identically, preserving alignment markers, CRLF,
   final-newline state, list markers, indent width, loose/tight spacing,
   checkbox capitalization, all three numbering styles and all three heading
   syntaxes. S6 was the one place this division of labour leaked: `body` took
   markdown source, so for that field the executor did not own formatting and
   the model did. It now refuses a heading in `body` outright (S13), which
   closes the leak by making it unexpressible rather than by handling it.
12. **Arm B's executor is Python, not the shipping Rust.** It is the intended
   differential-testing oracle, so the risk is that Rust diverges from it — not
   that these numbers are wrong, but that they describe a system not yet built.
   **Weaker than it was for every family.** Arm C runs the same ideal calls
   through the real binary and now covers all four: tables and lists from the
   start, the table read from F-armcread, and frontmatter from F-frontport,
   whose 3×110 `--cross` against Arm B's recorded frontmatter trials agreed on
   every pair. The caveat is now about the parts of a trial Arm C does not
   replay, not about whether the family exists in Rust.
13. **S14's prefixes are not a fresh sample.** The 393 replay prefixes are
   first calls the model produced in S13, so they inherit S13's distribution of
   tasks, seeds and mistakes — the replay measures what happens *after* those
   calls, not what a model does from scratch under a `delta` result. Two things
   bound the risk. The `outline` arm reproduces the original run on the same
   prefixes (9 continuations vs 11), so the state is being sampled faithfully;
   and the treatment is applied entirely after the prefix ends, so nothing
   about the prefix can differ between arms by construction. What it cannot
   see is whether a `delta` result changes the *first* call — it is only ever
   read after one. ~~A full arm at the adopted result shape would close
   that.~~ **Closed by S15**, which is that arm: `delta` and `outline` both
   score 127/150 on the same tasks and seeds, McNemar p = 1. `armb.py
   --result-shape` now defaults to `delta`, so reproducing S1–S13 requires
   passing `--result-shape outline` explicitly.
14. **The population S14's headline uses was not the one S13 defined.** S13
   counted "already succeeded" as "the call applied without an error"; the
   S14 effect is significant on "the call already produced the right document"
   (p = 0.0078) and not on the looser one (p = 0.11). Both are reported in S14
   and the looser one is named as primary, but a reader quoting the 0/300
   should quote the definition with it.
15. **S15's headline rests on one task.** The collision is ~0% on fourteen of
   the fifteen section tasks and ~20% on `promote-api`, so the powered arm is
   60 trials on that task rather than a broad sweep — which is the right place
   to spend sampling, and also means the effect size is measured on a single
   fixture and a single op (`set-level` on a three-segment path under an H1).
   What generalizes is the mechanism, not the 20%. The balanced 15-task arm
   bounds the other direction: the rename costs nothing anywhere else
   (115/120 control vs 120/120), so adopting it risks little even if
   `promote-api` turns out to be the only place it ever pays.
16. **S15 chose between two equally-measured renames on argument, not data.**
   `section_g_file` and `section_g_hpath` produced identical cells — 60/60,
   9 → 0 misfilings, the same discordant pairs. `section.heading` was adopted
   because it is the smaller change and matches the other two families, not
   because it measured better. Anyone who prefers `file` should know the
   measurement does not object.
17. **Re-running an arm at the same seeds is a replication, not a sample.**
    F-address's first re-measurement reproduced its baseline exactly and was
    briefly read as confirmation; the model's calls were in fact **250/250
    identical** in name and arguments once the random call IDs were ignored.
    Same seeds and same prompts cannot disagree, so the comparison had no power
    to detect anything. Two fixes, both used there: draw **fresh seeds**, and
    grade **one** set of calls through two executor trees, which pairs by
    construction rather than by seed alignment.

The raw trials are `bench/results/armb_faddress_{list_g,section_g_hpath}.jsonl`,
all twenty seeds in each. The committed `_graded` files are the **post-change**
column, reproducible with `armb.py --grade`; the pre-change column came from
grading those same files inside a worktree at `2fd063f` and is not separately
stored, since it is identical row for row. The second is only possible
    because S8 made grading a separate pass over raw trials.
18. **A paired arm showing zero discordant pairs may not have exercised the
    change at all.** F-address's 500 trials moved nothing, and inspecting all
    616 tool calls showed **none reached a changed code path** — the tasks are
    built to be answerable, so the model never sends the malformed argument
    shapes the change is about. Such a result bounds the *cost* of a change and
    says nothing about its benefit. Before reading a null as reassurance, count
    how many calls could have differed.
19. **An arm can also show a difference on an argument it never evaluated.**
    Caveat 18 with the sign flipped, and the harder direction to notice.
    `armb.run_trial` opens the task's fixture itself and passes the content to
    `apply_op`, so the model's `path` is inert — a call naming the wrong file
    grades identically to one naming the right file (F-fileblind). Every section
    schema comparison therefore applied *zero* selection pressure to the file
    argument, and the adopted schema drifted to omitting it on 92% of `insert`
    calls without any number moving. Before reading a schema comparison as a
    verdict on an argument, check that the executor reads that argument.

20. **A count over `bench/results/` is dated the day it is run, and the
    directory contains its own replays.** Every arm appends here, so a census
    grows as legitimately new trials land (`refusal_pool.py`'s 353 is 360 after
    S16). Worse, a replay appends here too, and a replay *pins* its prefix's
    first call — so its rows are copies of calls already in the count. Three
    commits have now added a file and silently moved a published number. A
    census of what models did must go through `bench/population.py`, and any
    figure quoted from one should say which question's denominator it is rather
    than reading as a current census.

    **Adding a file can also *replace* rows, not just add them.** A fourth
    instance worked the other way: `armb_s15_section_g_hpath_graded.jsonl`
    shares its `(scheme, task_id, trial)` keys with the trials it grades, has
    no `tool_calls`, and sorts after the raw file, so a reader keyed on that
    tuple silently swapped every shipping-arm trial for a call-less stub and
    reported the arm at 0/150. A rule written only against double counting does
    not catch substitution; `population.py` now excludes grading records too.

    **The converse is a trap of the same size.** Not every count over this
    directory is a census, and routing them all through `population.py` would
    quietly break the ones that are not. `regrade_snapshot.py` reads the
    directory whole, deliberately: it asks whether any *recorded call's*
    behaviour moves under a change, which makes it a regression corpus rather
    than a sample. A replay's re-execution of a call is a recorded call whose
    behaviour moves too, so dropping replay rows there would shrink coverage to
    no benefit — duplicates cost it runtime, not validity. `s15_analyse.py` and
    `framing_report.py` are the same case from the other side: both name their
    files, and `framing_report.py` exists to report *on* a replay. The test is
    what the denominator means, not which directory it came from. Where the two
    kinds of count meet they should be reconciled rather than made to match —
    F-action's `21` and `11` differ by exactly the replay's copies, and that
    difference is now the cross-check (`:4701`).

21. **A trial is evidence for the schema it was shown, and 80% of this
    directory was shown one that does not ship.** `python3
    bench/population.py` — of **6430 trials**, 911 (14%) are on the three
    adopted schemes, 5139 (80%) are on schemes that do not ship (4019 in
    pre-adoption files, 1120 in files that mix both), and 380 (6%) are Arm A,
    which is shown no tool at all and correctly records no scheme.

    Nothing in a transcript records this. A pre-adoption trial looks exactly
    like a shipping one, so an absolute rate over a pool inherits the schema
    its trials were run under without saying so. It has cost two published
    numbers, and the two failed differently:

    - F-framing's tables recovery, **13/38**. All 38 were `scheme_d` sending
      `row`. Arm B's own executor *accepts* all 38 — they were never refused in
      the arm. The two executors contradict each other, which is mechanically
      detectable, and `armc.executor_mismatch` now detects it.
    - Lists' `` `text` is required ``, **16/37**. All 37 are `list_f` and
      `list_naive`; `list_g` draws that refusal **0 times in 400 calls**,
      because L3 renamed the selector and the collision stopped existing. These
      refusals are real — the models genuinely failed — so there is nothing for
      a guard to detect. Only the scheme label distinguishes it.

    The second kind has no mechanical tell and will recur. The rule is
    therefore a reading habit with tooling behind it: **print the scheme mix
    beside any stratum before reading it** (`framing_report.py` now does) and
    check the file before quoting an absolute rate from it (`population.py`).

    This is not a reason to distrust the directory. A pre-adoption file is not
    wrong, most of the project's evidence is in one, and **paired contrasts
    within such a file are unaffected** — the schema is held constant across
    conditions, which is the same argument `armc.replay` makes for skipping
    `_check_supported`. It is absolute rates, read as describing the product,
    that need the label. A third instance is already recorded: S15's prefix
    pool predates the section spelling it adopted, and that one cannot be fixed
    at all, because the shipping schema reaches the branch 0 times in 400.

22. **Six discordant pairs is the floor, so a comparison can be ruled out
    before it is run.** These endpoints are paired and scored with McNemar,
    where only discordant pairs carry information, and the smallest p the exact
    test can emit for `k` pairs all falling the same way is `2^(1-k)` — 0.0625
    at k=5, 0.0312 at k=6. So if a change can only move the trials that reach
    its branch, counting those trials bounds the whole result. `python3
    bench/headroom.py` does the counting; F-headroom rules out three pending
    re-measurements on it, all three because the schema change that motivated
    the fix had already retired the population that motivated the change.

    Two qualifications, both load-bearing. The bound is **one-sided for a
    schema description change**: a description is in the prompt for every trial,
    so it can move trials that never had the failure — `k` caps the gain and
    nothing caps the loss. And `k=0` is **two different findings**: the adopted
    scheme ran the provoking task and no longer fails (closed), or it was never
    run on that task at all (untested, and the work is a task set). They look
    identical in a total and demand opposite responses.

## Server facts worth keeping

- **`required` is not enforced.** With `--jinja` native tool calling, this server
  will happily emit a tool call missing a property listed in the schema's
  `required` array — measured in B6, where the model dropped the required
  `table` address in 3/60 trials. The schema is a *hint to the model*, not a
  grammar constraint on the output. **Every required field must be validated at
  runtime with a recoverable error message**; incise cannot assume a field
  arrives just because the schema demands it.
- Type constraints are similarly advisory: deleting a `oneOf` union from a
  property changed the model's output in 0 of 60 trials (B6).
- `reasoning_budget: 0` is **silently ignored** by this server — the request
  succeeds and returns a full ~3000-token reasoning trace. Only
  `chat_template_kwargs: {"enable_thinking": false}` actually disables thinking
  (111 tokens / 5.1 s versus 3070 tokens / 93.2 s on the same prompt).
  Any config or harness relying on `reasoning_budget` is not doing what it says.
- Prompt caching is near-worthless for this workload: 518 prompt tokens against
  3070 completion tokens with reasoning on, `cached_tokens` 0.

## Taxonomy change

`PLAN.md` §5 gains one class, adopted after the first grading pass:

| Class | Definition |
| --- | --- |
| `destructive` | An existing row disappeared that the task never asked to remove |
| `op_error` | Arm B only. The op was well-formed but named something that does not exist — wrong heading, wrong column, no matching row. incise refuses and the document is untouched. Tracked apart from `malformed` because the fix differs: better error text versus a better schema |

`destructive` is checked **before** `wrong`, because every `wrong` trial in the
first pass was actually a lost row and merging them concealed it. `destructive`
counts toward the silent-corruption headline alongside the two `collateral`
classes **and `wrong`** — the last added in B6, after the original narrow
definition was found to report `scheme_b` as 0% when its seven B4 failures were
silently wrong rows. `op_error` deliberately does **not** count — it is a loud
failure, and B3 measured it as recoverable in one turn.

The dividing line is what the calling agent believes afterwards. `op_error`
tells it the edit did not happen; `wrong`, `destructive`, and `collateral` all
leave it believing the edit succeeded. Only the first is safe.

## Open

- ~~**The set of three that ships today costs 3.2 points, and nobody knew.**~~
  **Decided: the contract disclaims rate-transfer, and the cost is accepted.**
  F-compose, incidentally: `solo` 290/310 = 93.5% against `compose_3`
  280/310 = 90.3%, **11–1, p = 0.0063**. (F-compose measured it as 4.5 points,
  15–1, p = 0.00052; F-terminal's regrade took 1.3 points off and the corrected
  figure is the one above.) Every published tool's number was
  measured with that tool alone in the request; the product has published three
  at once since the first family shipped. This is not a reason to publish fewer
  — a one-tool product cannot do three families — but it means `schema.rs`'s
  contract sentence is true of each tool's *text* and false of the *condition*,
  and that every rate quoted for a shipping tool is from a condition the tool is
  not used in. What it wants is not another arm but a decision about what the
  contract should claim. The mechanism is visible and cheap to attack: 0
  cross-family calls under one tool against 9 under three, and `action` dropped
  entirely 1 time in 480 against 4 in 310.

  The contract sentence has been amended rather than left false — `schema.rs`
  now states both halves and says which one `schematest.py` can guard — but the
  3.2 points are priced, not recovered, and recovering them is still open.

  **F-terminal took 1.3 points off the figure before any GPU was spent**, and
  narrowed what is left. Four of the fifteen discordant trials were a fused
  `action` the model corrected on the next turn, graded `malformed` by the one
  refusal class `grade_one` aborted on; crediting that recovery makes it 11–1,
  p = 0.0063, **3.2 points**, and makes the table family immune at 60/60 like
  lists. The residue is sections (14–1) and frontmatter (11–1), both above the
  floor of 6 — which is the arm worth pre-registering, and it is much narrower
  than the one this item originally implied.

  **F-anchor found the arm, and it is narrower again.** Reading a *family's*
  discordant count as an *intervention's* reach was the error in the paragraph
  above. Decomposed: frontmatter's 11 are 4 (an under-determined task, already
  an open item), 4 (real, description-reachable, k = 4) and 3 (cross-family),
  and no mechanism in it clears the floor; the cross-family mechanism this item
  calls *"visible and cheap to attack"* accounts for **5 of the 25 losses across
  both families, k = 5, below the floor** — real in the calls, unattackable in
  the arithmetic. What does clear it was not in F-compose's list of three:
  `section_edit` is called with **no address at all** — 0 of 150 trials under
  `solo`, 8 of 150 under `compose_5`, none recovered — and `section_edit` is the
  one published tool whose description never names its address argument, where
  the other four name theirs on every action line and lose it zero times in 700
  composed trials. The rate is not zero elsewhere, just small: 2 of 801 across
  every `section_g_hpath` pool on disk, and 5 of 100 under `section_naive`,
  whose bare description reaches the composed rate on one tool. The arm is
  sections alone, `section_h` against `section_g_hpath` inside `compose_5`,
  pre-registered in F-anchor. **Run, and it did not pay** — F-reach: the
  address-less count halved and the outcome did not move (p = 0.4049), so the
  4.5 points stay unattributed and this item stays open with one fewer
  candidate.

  **The decision, taken here rather than deferred to a fourth arm.** This item
  asked for *"a decision about what the contract should claim"*, and every
  candidate for recovering the points is now spent: one credited away by
  re-grading (F-terminal), one at k = 5 against a floor of 6 and therefore
  unresolvable by any paired run however large the effect (F-anchor), one run
  and failed (F-reach). A residue of losses remains, but no *mechanism* remains
  that an arm could attack — and an item that stays open on the strength of an
  unnamed mechanism is a wish, not a plan. So the claim is settled instead of
  the cost: `schema.rs` now states three things and disclaims a fourth. Each
  tool's text is the text that won its comparison; the set of five has been run
  end to end; the composition costs 3.2 points and that is accepted as the price
  of a multi-family product. The disclaimer is the new part — **the rates in
  that table are the comparisons that selected each text, not the rate that text
  achieves as shipped.** 96.7% is what `table_get` did alone against `where`; it
  is not what `table_get` does in the product, and nothing in this repository
  could have stopped someone quoting it as though it were. `schematest.py`
  guards the first clause, a `compose_*` arm guards the second, and the third
  and fourth are guarded by nothing, which is why they are written down.

  What stays open is narrower and now named as itself: the 3.2 points are
  unattributed, and re-opening this needs a *new* mechanism, found the way
  F-anchor found `section_edit`'s missing address — by decomposing losses, not
  by proposing an arm.

- ~~**`grade_one` treats `unknown operation` as terminal and everything else as
  recoverable.**~~ **Decided: credit the recovery.** F-terminal. The run loop it
  graded had no such case: every error goes back to the model as
  `"Error: " + err` (`armb.py:1621`) and the loop continues, and `grade_one`'s
  own docstring said errors are collected rather than aborted on. 31 recorded
  tool-arm trials ever drew the sentence and **22 of them went on to produce the
  correct document** — 71%, against B3's 13/13 and S12's 75% for every other
  refusal class. The branch is gone from `armb.grade_one` and `armc.grade_one`,
  every affected pool is re-graded on disk, and the published numbers it moved
  are corrected beside the tables that state them (`front_p` 94.5% → 95.5%,
  F-framing's `list_i` 86.7% → 100%, the composition cost above). Exactly the 31
  predicted trials moved and nothing else did. ~~What is *not* closed is the
  refusal itself: naming all fifteen ops to a model that can reach fourteen is
  still a §5.3 defect — see the `table-realign` item.~~ **Closed for the product
  — F-valid.** The fifteenth became reachable when realign shipped, so the
  sentence is now true of every model the product hands it to; it stays a defect
  only for the single-tool schemes that ran here, where it is Caveat 21 rather
  than a bug. `check_every_op_is_reachable` keeps it true.

- ~~**`section_edit`'s description never names `section`, and the arm to fix it
  is pre-registered and unrun.**~~ **Run, and `section_h` is not shipped** —
  F-reach. The hole is real and the treatment halved it: address-less trials
  16 → 7 of 298, the sharpest confirmation the mechanism exists. The outcome did
  not follow — 14–9, **p = 0.4049**, correct 231 → 226 — and the losses landed
  where nothing predicted them: `promote-api`, a `set-level` task with no
  address-less call in either arm, 16/18 → 9/18, five of the seven
  `destructive`. Naming `section` on every action line made every action read as
  one argument from callable, `action=delete` included: 1 delete-calling trial
  became 6, and all 6 destroyed a subtree. Silent corruption 7.7% → 13.1%,
  p = 0.0259 **post-hoc**. `section_g_hpath` stays adopted, the composition cost
  stays unattributed, and the one-sided rule has its second demonstration.

- ~~**`grade_one` charges a transport failure to the model.**~~ **Done —
  F-transport.** Its first line maps
  any `trial["error"]` to `malformed`, and `trial["error"]` is set from any
  exception the run loop catches — including `HTTPError: HTTP Error 500` from
  the model server, where `turns` is empty and no schema could have changed the
  outcome. **10 trials on disk are graded this way**: `armb_s6_section_kids` (4),
  `armc_sections` (2), `armc_replay_path` (2), `compose_4_sections` (1),
  `compose_5_sections` (1). One published number moves and its conclusion does
  not — F-compose's sections row is **13–1, p = 0.00183** rather than 14–1,
  p = 0.00098, the compose_4 instance being concordant. This is F-terminal's
  defect one level further out, but the remedy is different: F-terminal's class
  produced a sentence the model read and acted on, so it was re-classed; a 500
  produces nothing, so the **pair should be dropped from both arms** rather than
  re-graded into a new class. Left unfixed in the grader on purpose —
  `malformed` with an `HTTPError` detail is visible and greppable, which is how
  these ten were found, and a silently dropped trial is not. What the fix wants
  is a `transport` outcome that is reported as a count and excluded from the
  pairing, plus a pass over the other three pools; F-anchor's pre-registration
  states the handling in advance so at least the next arm does not inherit it.

  **Built exactly as described, and the pass found seven more.** The census is
  **17, not 10** — the three unchecked pools plus F-reach's two, which were
  already dropped by hand. `transport` is a class in both graders, `stats.py`
  drops the pair from both arms and names what it dropped, and the one published
  discordant count that moves is the one this item predicted: 13–1, p = 0.001831,
  now produced by the instrument rather than by hand. S6's table restates to
  /147 without its finding moving, and Arm C moves by denominator only.

- ~~**Two tools are now the same op, and the unmeasured one is the one that
  ships to models.**~~ **Closed by F-rows, and not by the arm this item asked
  for.** The instrument named here — a scheme publishing `md_rows` against
  `bench/tasks/tables_read.json`, paired with `table_read_g` on the same seeds —
  was never built, because the result it would return is bounded before it runs.
  `md_rows` took `table` as a plain string and `tables_read.json`'s
  `get-ordinal-table` needs an ordinal, so ten of its sixty trials were
  unanswerable at any temperature while `table_read_g` answers them 10/10:
  b ≥ 10, c ≤ 2, p ≤ 0.0386 with no GPU spent. `md_rows` is retired and
  `table_get` is registered as a read. What stays open is `table_get`'s own
  copy-paste wart, below.

- **`table_get`'s `table` is described as *"Which table to edit"*.** **Closed —
  F-wart.** It is a read, the words came from `table_edit`, and they ship byte
  for byte because that is what 58/60 was measured on. The arm the item asked
  for was priced and it cannot return a gain: `headroom.py` is **UNDERPOWERED at
  k = 2 of n = 150**, and both reachable trials are already graded `correct`, so
  the one-sided gain bound tightens from 2 to **0** against an unbounded loss.
  The misroute it is actually accused of is **0 of 120** composed trials in both
  directions (upper bound 2.5%). The phrase is wrong and permanent, which is the
  contract working rather than failing; the only licensed fix is to carry the
  rewording inside a `table_get` re-measurement that exists for another reason.

- **Two refusals name a remedy no shipping tool can perform** — F-remedy.
  *"Rename one of them in the document, then retry."* (`table-update-cell`,
  `table-delete-row`, `table_get`) and *"Normalize the section's line endings
  first, then retry."* (the three section body ops). Both diagnoses are right;
  both remedies are outside the five-tool set, and the move they leave a model
  is free-text rewriting — Arm A, at 19%. `headroom.py` prices this **UNTESTED**
  at k=0 of n=2041: no task fixture repeats a header name or mixes line endings.
  **The table half of the instrument is now built** —
  `bench/tasks/tables_read_remedy.json`, three tasks, `ceiling.py` 3/3 — so this
  is runnable as a description arm against `table_read_g`. The **section** half
  is not: an append to a mixed-ending section has a ceiling of zero, so it is a
  capability question (should the op pick a convention?) rather than a wording
  one. If the table arm is ever run it shares one with the wart above — same
  tool, same seeds — and both are one-sided, bounding the gain only.

  **The control arm is run, and the sentence is terminal.** 30 trials,
  `table_read_g` at the pre-registered condition. `get-repeated-control` 10/10
  and `get-repeated-both` 10/10, neither reaching the branch;
  `get-repeated-name` **0/10**, all ten drawing the rename refusal on the first
  call and all ten stopping to tell the user the question cannot be answered,
  with three turns unused. The same pool holds the internal control: on
  `get-repeated-both` the model drew a *different* refusal, one naming something
  it could do, retried, and answered. `headroom.py` now prices this **POWERED at
  k = 10, best achievable p = 0.0020** — the verdict was UNTESTED with the pool
  on disk, because `replay` skipped reads; it executes them through
  `armb.read_call` now. **What stays open is the treatment**: the reworded
  sentence, which F-action's line constrains — the core may name the argument it
  received, and may not name the tool that sent it.

  **Run, and it ships.** `get-repeated-name` 0/10 → **10/10**, the two
  non-provoking tasks unmoved, McNemar exact **p = 0.001953** — the floor for 10
  discordant pairs. Both arms open with the *same* first call; the refusal is
  the only variable, and the treatment's second call is the one the new sentence
  names. The `filter` half of this item is **closed**: `Omit \`filter\` to read
  every row, and pick the one you want from the result.` ships in
  `bench/incise_ops.py` and `crates/incise-core/src/ops/table.rs`. **The other
  three call sites stay open** at k=0 — `where` and keyed `values` have
  performable remedies nothing provokes, and `column` has none, so its shipped
  sentence is correct and stays. The **section** half is untouched and still a
  capability question, not a wording one.

- ~~**Should `describe_frontmatter_change` fold into `describe_change`?**~~
  **Closed — declined on evidence, F-describe.**
  `incise_ops.py:2949-2954` keeps them apart only because the Rust had no
  frontmatter parser, and F-frontport retired that reason without taking the
  fold — which is a behaviour change, not a port. The measured contrast is the
  case for folding: on one edit, "Applied: set `build.jobs` to 8." against
  "Applied: changed text outside any heading. (+1 line, -1 line.)". The case for
  care is that `describe_change` is derived from the two documents and not the
  op name, so a fold re-describes existing cases — prepending text to a file
  that opens with `---` moves the delimiter off line 0, `frontmatter_span`
  returns `None`, and the block reads as *removed*. It needs its own
  `regrade_snapshot` enumeration over the calls that would move.

  **The enumeration was done — `bench/describe_census.py`.** Over 1888 distinct
  recorded edit calls × 54 fixtures, **36 pairs move, all `frontmatter-set`, all
  true, and all worse**: the closing clause goes from "changed text outside the
  frontmatter block" to "changed text outside any heading", which is S14's
  finding surviving the fold at the one clause the fold reaches. The displaced
  block is real in the function and reached by no published op — `section-insert
  position=before` on all 9 frontmatter fixtures displaces nothing, because the
  block is above every heading. No fold. What is left is the docstring at
  `incise_ops.py:2963-2971`, which still gives the expired reason.

  ~~**A second op is mis-described by the same mechanism, found in F-mirror.**~~
  **Withdrawn — the observation was real and the generalisation was not.**
  `table-realign` succeeds with *"Applied: changed text outside any heading.
  (+3 lines, -3 lines.)"* — on the one op in the set that changes no cell text
  and exists precisely to change nothing but padding. **Counted: 36 tables in
  the tree realign to a changed document, 35 name their section, and the one
  that does not is `bench/synthetic/no-headings.md`, which has no headings.**
  The fallback fires only when there is no heading to name, so it never
  contradicts the guarantee. What remains is that realign describes as "changed
  the body of X" — true of the bytes, silent about the guarantee — and fixing
  *that* means deriving the sentence from the op name, which is the property
  this function was built not to have.

- ~~**`armc.replay` will select a prefix whose scheme the `--binary` does not
  implement.**~~ **Fixed — `armc.executor_mismatch`.** It picks prefixes by
  re-executing the first call against the binary rather than reading recorded
  `exit_codes` (`armc.py:497`, and the reasons given there are good ones). For a
  **retired** scheme that silently changes the population from "calls that were
  refused" to "calls this binary refuses." F-framing: **38 of 61** tables
  prefixes are `scheme_d` calls that Arm B's own executor *accepts* — the models
  used `row`, which `scheme_d` declares and no shipping schema does. They were
  counted as failures to recover, and they dragged tables' absolute one-turn
  rate to 59.0% when the genuinely-refused 23 recover **23/23 = 100%**. Paired
  endpoints are immune (the executor is constant across framings) and none
  moved.

  `replay` now replays each selected first call through the oracle and **aborts**
  if any succeeded, printing the count and the schemes; `--allow-executor-mismatch`
  proceeds for a run where only a paired contrast will be read. The test is
  direct evidence, not a scheme-name lookup — a name check would reject every
  non-adopted scheme, which is most of the prefix corpus and nearly all of it
  legitimately. It applies only to `--select refusal`: a usage fault is
  argv-level, `apply_op` is handed content directly and cannot see one, so the
  same check under `--select usage` would reject the entire Arm C population.
  Verified by running it over all three F-framing pools — fires on tables
  (76 = 38 × 2 framings), silent on lists and sections, silent under
  `--select usage`.

  This is the same shape as the S15 item below — **a prefix pool inherits the
  schema its trials were run under, and nothing checks that against the schema
  under test.** Two instances now; the second was an artifact, and the first is
  why the first version of this finding was wrong. The S15 case is not caught by
  this guard and cannot be: there the schema changed the *spelling* of an
  address, so the old prefixes are genuinely refused by the new binary. A pool
  can be stale without being contradictory.

- ~~**`table-add-row`'s refusal recommends an argument the shipping schema does
  not have.**~~ **Done — F-rowarg.** ``a row is required: either `values` keyed
  by column name, or `row` as an ordered array.`` named `row`, which `table_edit`
  has never declared and the core refuses on purpose (`ops/dispatch.rs:19-23`).
  Three sentences moved in lockstep across `bench/incise_ops.py` and
  `crates/incise-core/src/ops/table.rs`; 29 of 10072 recorded calls changed
  sentence and **all 29 re-grade identically**. The measured cost this entry
  originally claimed (13/38, `31 of 38 take the advice`) was **withdrawn** — it
  was the harness artifact in the item above, not the message. No recorded call
  from any shipping scheme has ever read this refusal, so its cost is unmeasured
  and there is no population to measure it on; it was fixed on the argument that
  a refusal must describe the schema in force. `difftest.py` could not see it and
  structurally cannot: both sides carry the identical sentence, and what it is
  wrong about is a *sanctioned* divergence. `bench/schematest.py` now checks it
  one-sidedly, against the schema.

- ~~**Which reading of the single-match ordinal refusal a model takes.**~~
  **Run — three builds, 54 paired prefixes, and it answers less than it was
  asked.** Neither reading is what happened. `destructive` falls 5 → 2 → 0 and
  the adversarial "take the first item blind" prediction of 62 did not
  materialise at all, but `correct` is 42 / 43 / 42 with `p = 1` throughout, so
  there is no outcome win to claim either. The safety axis moves — 90.7% →
  96.3% not misled — and five discordant pairs floor the exact test at
  `p = 0.0625`, which no result at this width can beat. What stays open is
  narrower and new: **the adopted `section_g_hpath` schema is not in the prefix
  pool.** All 27 situations predate S15 and address sections by `section.path`,
  so what was measured is recovery under the schema S15 replaced. The shipping
  schema's version of this branch is untested — and will stay that way, because
  S15's own rows show it fires **0 times in 400 trials** there against 12 in 200
  under the old spelling. The gap is real; buying it with an arm is not
  affordable. See *"Why the pool predates S15"* above.

- ~~`describe_change`'s line tally is wrong on long repetitive documents.~~
  **Done — F-autojunk.** `autojunk=False` on both of `describe`'s matchers. The
  premise that made it a *decision* rather than a fix turned out to be wrong:
  it does not move measured output. Seven of 76352 cases change, all seven on
  the one fixture built to expose it, and every one moves to the true minimal
  edit. No corpus document and no refusal message moves, so S14's numbers stand
  untouched.

- ~~**`get_close_matches` loses near matches on addresses of 200+ characters, and
  cannot opt out.**~~ **Closed by F-nearmatch.** The cost estimate in this item
  was wrong and is the reason it sat open: "reimplementing a stdlib function
  inside the oracle" is a fifteen-line wrapper, `SequenceMatcher` stays stdlib,
  and the fix *removes* code from the port rather than adding it. What the item
  got right was the severity — of the 168 probes on
  `bench/synthetic/long-cells.md`, **46 lost a match**, and a value one word
  short of the D-1 cell scored 0.98 against that cell and 0.71 against its
  paraphrase while stdlib answered **"Near matches: none"**.

- ~~**`table-get`'s `filter` argument is unmeasured.**~~ **Closed by F-read**,
  and it was worth more than the item assumed: the naive scheme publishing
  `where` scores **45.0%** against **96.7%** for `filter` described as narrowing
  the rows, p = 9.3e-10, with the whole gap in whether the model reaches for the
  argument at all (7/60 against 40/60). The other half of the item — whether a
  model that has the table list reaches for `table-get` or just asks for the
  file — is answered for the tool itself: 120 of 120 trials called it. The
  treatment was the whole argument, name *and* description, not the word alone;
  a name-only arm is not run.
- ~~**A `filter` value that is not a string is never exercised differentially.**~~
  **Closed by F-read.** `table_get` now rides the JSON escape hatch, 84267 →
  86229 cases, and `filter-value-typed` is in `mutate.py` — proven reachable by
  running it with the new cases disabled, where it survives.
- **`table-get` renders markdown only *to a model*.** REQUIREMENTS §6.1 says "as
  JSON or markdown" and defers the second renderer until there is evidence a
  model wants to choose. The structured `TableRows` is already there, so the cost
  is a renderer and not a redesign — but the argument that selects between them
  is exactly the kind of extra field §6.2 measured the model filling in wrongly.
  F-armcread narrowed what remains: `rows --json` now returns the structure
  beside the text, so a *caller* has both. That is the split §6.1 says gives both
  for free at the call site, and it is deliberately not a `format` argument. What
  stays open is only the model-facing choice, and it needs evidence a model wants
  it rather than a renderer.
- ~~**`table-realign` is the one op no model can invoke.**~~ **Shipped —
  F-realign's gate.** It is in `OPS`, it is
  in `dispatch.rs`, the CLI has a subcommand and a one-line `op_about` for it —
  and no `action` enum in any of the 24 scheme entries publishes it, so no tool
  that ships offers it. The plugin does not either: `realign` appears nowhere in
  `plugins/hermes/`. Fifteen ops, fourteen reachable from a tool, and the
  fifteenth is the one §5.2 calls the pawl. The ratchet turns when anything
  other than incise leaves a table ragged; every later incise edit then
  preserves the raggedness faithfully and forever, and realign is the only op
  licensed to undo it. A model working through the tools can produce the state
  the pawl exists for and has no way to release it. A CLI caller does.

  **It is also a §5.3 defect, and models have already read it.** The first pass
  of this item said the opposite — that the gap costs capability and not
  honesty — on the strength of a by-op refusal harvest in which every "realign"
  mention reachable from the fourteen was the fixture name `realign-targets.md`
  quoted back (`Headings with tables: Realign targets > …`), the same
  interpolation noise F-remedy's sweep had to filter out. That harvest keys on
  the op name, and the refusal that matters is drawn by a call that **has no
  valid op name**:

  ```
  unknown operation "table-None". Valid: table-add-row, table-update-cell,
  table-delete-row, table-realign, list-add-item, …, frontmatter-delete
  ```

  `dispatch.rs:86` composes it from its own `OPS`, all fifteen, and
  `incise_ops.py:3317` does the same byte for byte. That is right for the CLI,
  which is handed an op directly and where any of the fifteen could have been
  meant. It is wrong for a model, which has three tools and cannot reach twelve
  of the names it is being offered — the same mistake `_actions_from_schemes`
  was built to stop in the `action` refusal, in the one sentence that was never
  routed through it.

  **21 recorded Arm B and composition trials have read it, 16 of them since
  `table-realign` joined the list** (the other 5 are `armb_lists`, which
  predates it). It is not rare in the arm that ships: **4 of 60** `compose_3`
  table trials, 3 of 60 under `compose_5`, 2 of 60 under `compose_4`. Every one
  arrives the same way — `action` fused into the next key,
  `{"action=add-row,path": "corpus/tables/ragged.md", …}`, which resolves to
  `table-None`. That is `action_sizing.py`'s fused-`action` call, and this is
  where it lands.

  So the sentence is reachable, is drawn, and offers a model an op no tool
  publishes. Fixing the *sentence* is the front-end scoping `armb.py:1190`
  already argues for and is independent of the ship question above: name the ops the
  caller can actually reach, which for a model is its own tool's enum and for
  the CLI is all fifteen. Fixing it does not decide whether `table-realign`
  should be one of them.

  The choice is therefore between two defensible positions and not between a bug
  and a fix. **Ship it** in `table_edit`'s enum and the family gains a repair, at
  the cost of a fourth action on the tool B7 moved by rewording one paragraph —
  and `_actions_from_schemes`' assertions mean the `unknown operation` refusal's
  offered surface changes with it, which F-framing already found confounds a
  wording measurement. **Leave it out** and realign stays an operator's tool,
  which is a coherent reading of an op whose whole argument list is `table`. What
  is not defensible is the present state being unrecorded, which is why this is
  here. Deciding it is a schema change, so it belongs with a run; `ceiling.py`
  can price the gain first, for free, on a task set that needs one
  (`bench/synthetic/realign-targets.md` already exists and is not frozen corpus).

  **The gain is now priced — F-realign — and it recommends shipping, gated on
  one run.** `bench/tasks/tables_realign.json` and `scheme_f_realign` exist; the
  ceiling is **3/3 in both Arm B and Arm C** across all three shapes raggedness
  arrives in, so the capability is real and the discordant count against today's
  enum is forced rather than measured. Two facts turned up that were not in the
  paragraphs above. The display-width concern in the item below is **already a
  refusal**, not silent corruption — realign exits 1 on a CJK cell with a
  sentence naming the character and what still works — which is what makes the
  op safe to hand a model. And the A/B cannot be run in one process at all:
  `ACTIONS` is global, nine scheme entries publish `table_edit`, so the
  candidate is a second *world* behind `INCISE_BENCH_REALIGN=1` rather than a
  second scheme. What is still unpriced is the cost, and `headroom.py`'s
  one-sided rule forbids waving it through: 120 trials over `tables.json` and
  `tables_realign.json` in both worlds settles it, and the `tables.json` half is
  the one that decides.

  **Run, and it ships.** 180 trials, four cells. `tables.json` is **60/60 both
  ways, trial for trial** — zero discordant pairs, and the new action reached
  for zero times in 62 calls on those six tasks. `tables_realign.json` is
  **0/29 against 30/30**, p = 3.7 × 10⁻⁹. The control cell was run rather than
  assumed and returned something the construction does not predict: the thirty
  trials that could not say `realign` said `update-cell` 54 times instead and
  **destroyed the document 8 times**, 27.6% silent corruption. The missing pawl
  was never a neutral absence. `action=realign` is in `schema.rs`, the env var
  is gone and the augmentation is unconditional, and **fifteen ops are fifteen
  reachable**. What the ship cost is that every scheme's `table_edit` now
  carries a line the pools recorded before 2026-09-17 were not shown — one tool
  name, one enum, one world.

  ~~The plugin still does not offer it: `realign` appears nowhere in
  `plugins/hermes/`, and that stays a separate decision, since the plugin
  publishes one tool per op rather than an `action` enum and has never been in
  an arm.~~ **Both halves of that were false when written — F-mirror.** The
  grep is accurate and the inference from it is not: `schema_cache.edit_tools()`
  shells out to `incise schema` and registers whatever comes back verbatim, so
  the plugin publishes the same five tools with the same four-entry enum, and
  `normalize("table_edit", {"action": "realign", …})` returns `table-realign`
  end to end. The plugin gained realign in the same commit `schema.rs` did, with
  no plugin edit and no way to notice. There was never a separate decision to
  take.

  **The §5.3 half of this item is closed too, and not by anything done to the
  sentence — F-valid.** The paragraphs above argue for front-end scoping because
  a model "has three tools and cannot reach twelve of the names it is being
  offered". Shipping realign and publishing frontmatter made all fifteen names
  reachable from the five tools, so the refusal is true as served and the
  re-wording was never performed. What the arms recorded is not recoverable:
  `compose_5` as measured reached 14 of 15, so none of the 21 trials that drew
  the sentence read the honest version, and the residue prices at k = 1 of
  n = 2341. The invariant the closure rests on is now asserted by
  `check_every_op_is_reachable` in `schematest.py`, which reads the op table out
  of the binary's own refusal rather than trusting `OPS`.
- **`table-realign` refuses rather than narrowing, on any width it cannot
  measure.** F-realign: width is counted in characters, so realign refuses any
  table containing a character that is not one display column wide (CJK,
  fullwidth, combining marks, emoji) rather than aligning it to a count nobody
  can see. *(Retitled. This bullet used to read "cannot measure display width,
  and narrows instead", which its own body contradicted; the direct test in
  F-realign confirms the body — exit 1, document untouched, a refusal naming the
  character. The old title made the op look unsafe to publish, which is the
  opposite of what it is.)*
  Correct, and it costs coverage — those tables can never be repaired, and the
  ratchet §5.2 describes is exactly the thing they cannot escape. The real fix
  is a Unicode width table, which the crate's no-dependencies rule rules out
  today. Revisit when either the rule or the cost changes; the range table in
  `incise_ops.py` and `ops/table.rs` is the thing to replace, and it is
  duplicated across the two implementations by design.

  **It became product text when realign shipped, and it cannot be priced —
  F-width.** `table_edit`'s fourth action turned an operator-facing refusal into
  a model-facing one under §5.3 without changing a byte. `headroom.py` prices it
  **UNTESTED at k = 0**: no recorded call draws it, because no fixture or corpus
  file has a wide character in a table, so no paired run of any size can move
  it. The wording therefore ships unmeasured, deliberately, and is now covered
  by `test_realign_width_refusal_keeps_its_promise` — which checks the promise
  the last line makes, that add, update and delete still work on the same table
  and leave its lines byte-identical. The Unicode-width fix above is unchanged
  and is still what would actually close this.
- ~~A cell is the text between two pipes.~~ **Done — F-pipes.** It is not: GFM
  escapes a literal pipe as `\|`, and splitting naively made
  `table-update-cell` write into the wrong cell and emit a row with an extra
  column, while an unescaped `|` or a newline in a *value* was written straight
  into the document. Both silent, both reported as success, both invisible to
  differential testing because the two implementations shared the assumption.
  Closed with one shared splitting rule, two write-side refusals, a
  not-rectangular guard, and the invariant that was missing —
  `test_identity_update_roundtrip`, 974 cells.
- ~~Ill-typed arguments reach the executor.~~ **Done — F-args.** Eight
  `_check_*` functions; 0 crashes and 0 leaks on the survey; proven
  grade-neutral by replaying all 5674 recorded tool calls, twice. Differentially
  tested at both layers: a cross product of values against functions
  (`check_args`, `py_repr`), which found three port divergences on its first
  run, and whole-dispatch calls (`apply_op`), which found two more and a fourth
  executor defect — `value` was never checked, so a missing one wrote the
  literal string `None` into the cell and reported success. 6561 cases, 28
  mutations, all caught. (Both counts have since grown — see F-pipes.)
- ~~Repeat-penalty control.~~ **Done — F7. The premise survives.**
- ~~Arm B: op vocabulary against a mock.~~ **Done — B1–B7.** Addressing works;
  the scheme choice does not resolve on correctness (B5).
- ~~Measure `scheme_b` + array-form `values`.~~ **Done — B6.** Silent corruption
  7/60 → 0/60 (p = 0.0156). Adopt `scheme_e`: one untyped `values` accepting an
  object or an ordered array.
- ~~Make the `table` address harder to drop.~~ **Done — B7.** Naming it on every
  per-action line took the adopted schema to 60/60; the heading-string shorthand
  was measurably inert and was not adopted.
- ~~**Re-measure B2 with the improved error text in the first turn.**~~
  **Closed without spending it — F-headroom.** The confabulated-selector refusal
  fires 13 times in `scheme_a`'s 60 trials and **0 times in the adopted
  `scheme_f`'s 120**, on the same six tasks — `scheme_f` ran the two that
  provoked it 40 times and never confabulated. B6/B7's description rewrite
  already removed the failure a warning would have been written to prevent, so
  there is no population left to move.
- ~~Extend to sections.~~ **Done — S1–S6.** The result is not a scheme choice
  but three design problems: `append`/`replace-body` is a data-loss pair (S2),
  `after`/`last-child` does not survive contact with the model (S3), and `body`
  takes raw markdown (S6). Adopt `new_heading` on the mechanism in S5.
- ~~**Sections: Arm A baseline.**~~ **Done — S7.** 19.0% correct, 28.0% data
  loss. The worst Arm A result in the project.
- ~~**Sections: measure the S2 fix.**~~ **Done — S8, S9.** Made `replace-body`
  refuse a non-empty body without `overwrite=true` and `append` refuse a
  `heading`. Re-grading the existing 200 trials: destructive 6→1 and 4→1, at a
  cost of zero correct answers. `section_g` (guards + rewritten action
  descriptions, 130 trials) reaches 80.0% correct and 0.8% data loss.
- ~~**Add section tasks that separate `append` from `replace-body`.**~~ **Done —
  caveat 6.** Three added; all three score 10/10 in `section_g`, so they now
  serve as a regression floor rather than as discrimination.
- ~~**Sections: stop refusing a spurious `ordinal`.**~~ **Done — S11. Decided
  against.** Measured as a monkeypatch and re-graded across all 330 section
  trials: `section_g` gains 3 correct and **6 destructive**, all six the same
  `rename-closed-atx` group where the model truncates the path to the parent.
  The ordinal is the only evidence the path is wrong. The refusal stays.
- ~~**Sections: rewrite the ordinal refusal message.**~~ **Done — F-address.**
  S11 and S12 converged on this: `"Valid ordinals: 0"` named the argument that
  is easy to compute rather than the one that is wrong, and `rename-closed-atx`
  t7 followed it literally into the only destructive retry in the project. The
  rewrite came free with routing sections through `check_ordinal`, and the first
  draft of it was itself wrong in the same way — against a file with twenty-one
  distinct sections named `Errors` it offered twenty-one zeroes, advice that
  cannot be taken, and `difftest.py` passed 82809/82809 because the oracle said
  it too. It now makes the distinction the no-ordinal branch already made:
  distinct paths mean "use a longer path", a shared path means "these are the
  ordinals". ~~Not yet re-measured on the 16 `section_g` retries.~~
  **Re-measured — F-unique, and there are 140 of them, not 16.** Every one landed
  in the *third* branch, the one neither half of the rewrite touched: the path
  matched exactly one section. Its advice was `correct` 37 times and
  **destructive 52** on the 111 first calls, all 52 `rename-closed-atx`. Rewritten
  again, and the correct address is now in the sentence 91 times against 37, and
  52 of 52 on the calls that were being destroyed. Which reading a model takes is
  **unmeasured** — that needs `armc.replay --select refusal` across two builds.
- ~~**Sections: rename `path`.**~~ **Done — S15. Adopted:
  `section.path` → `section.heading`.** The collision is real and concentrated:
  ~20% of `promote-api` trials, ~0% elsewhere, and it accounts for 100% of that
  task's failures. Either side of the collision can be renamed and both work
  identically (60/60, misfiling 9 → 0, p = 0.0039); the address was chosen over
  the file argument because `path` means the file on every table and list tool
  too, and those are frozen at measured numbers. L3 measured renaming as the
  strongest lever available; this is the same shape of fix, and the same size.
- ~~**Sections: decide S6 before the Rust freezes the op set.**~~ **Done —
  S13.** The harness grew a multi-turn loop and both candidates ran: 450 trials
  plus 60 re-runs. `body` now refuses a heading anywhere in it (parsed, not
  pattern-matched), at zero cost on re-grade. `children: [{heading, body}]`
  takes the three multi-section tasks from 12/30 to 26/30 and charges 12 points
  to the twelve tasks that cannot use it — so it is adopted, but on a narrower
  surface than `section_edit`. Read with S10's correction: the mechanism S6
  described was two trials, not five.
- ~~**Sections: the redundant turn. S13's real result, and nothing acts on it
  yet.**~~ **Half done — S14.** A further call after a call that had already
  succeeded, on a task that was finished: 11 times in 360, and 4 of those 11
  destroyed the document (36% vs 1.1%, Fisher p = 3.2 × 10⁻⁵, 32×). The first
  fix works and is adopted: a tool result stating what changed, *replacing*
  the outline rather than joining it, takes it to 0/300 (p = 0.0078) at 91%
  fewer characters. The second is untouched — whether `overwrite: true` should
  still be honoured on a turn where the model has already edited the same
  section. That one needs its own arm, because S14 held the executor fixed.
- ~~**Sections: run a full arm at the `delta` result shape.**~~ **Done —
  S15.** 127/150 at `delta` against 127/150 at `outline`, same tasks and seeds,
  McNemar p = 1. The S14 fix costs nothing on first calls. Caveat 13 closed.
- ~~**Sections: `children` on a narrower tool.**~~ **Run, and `section_create`
  does not ship — F-narrow.** S13's premise was a twelve-point tax on the tasks
  that ignore the field; restated at the adopted address spelling and the
  four-turn delta shape, that tax is **4–5 points on either design** (control
  120/120 on the twelve, `kids` 115, `split` 116), below the floor of 6, and
  moving `children` to a narrow tool recovered none of it — 5–4, **p = 1.0000**
  over 9 discordant pairs, which is a readable null and not an underpowered one.
  The pre-registered rule fails on (b) by one trial and stands.

  The half that *did* answer is the half that sounded risky: **the narrow tool is
  found 30 times out of 30** on the tasks it exists for, with one cross-family
  misuse in 120 non-target trials — `promote-api`, and it was destructive. And
  the aggregate 22/30 against `kids`' 21/30 hides a complete reshuffle: `split`
  is 10/10 where the control managed 2/10, and 3/10 on `insert-release-at-top`
  where both `section_edit` cells are perfect, because it anchors the new
  release on `[Unreleased]` rather than the instructed `[1.4.2]` seven times out
  of ten. That is the residue below.

- **`section_create` picks the top-most section as its anchor, and nothing says
  which part of the tool does it.** F-narrow: 7 of 10 `insert-release-at-top`
  trials anchored on `[Unreleased]` against 0 of 20 for the two cells holding
  `children` on `section_edit`, on an instruction that names `[1.4.2]`
  explicitly. The executor is blameless — the failing call replays to a clean
  six-line additive diff — so this is targeting, and the three candidates
  arrived together and cannot be separated by this run: the tool's name, its
  one-job framing (*"Create a new section in a markdown document"*), and
  `section` rewritten to *"Which EXISTING section the new one goes relative
  to"*. Only worth an arm if a narrow create tool is ever reconsidered, which
  F-narrow's decision says it should not be; recorded so the next person to
  propose one starts from the failure rather than from the idea.

  Two smaller things found beside it. `section_create`'s `body` description
  still ends *"To give the new section a subsection, insert that separately"* —
  inherited from `section_edit` and flatly contradicted by the `children`
  argument sitting next to it, which the model used correctly anyway. And a
  wrong-anchor insert grades `collateral:content` (*"text before the edited
  region changed"*), because the section lands higher than the golden; a
  targeting miss therefore reads as corruption in the outcome table, and those
  seven trials are the only `collateral:content` in the run.
- ~~**Sections: is `op_error` actually recoverable here?**~~ **Done — S12.**
  B3's 13/13 was measured on tables, where the executor absorbs mistakes.
  Sections: 75.0% for `section_g` (63.6% naive, 78.6% `p`), taking `section_g`
  to 116/130 = 89.2% correct with one extra turn. The premise S8 and S9 rest on
  holds in the family that could have broken it.
- ~~**Sections: re-run `section_naive` and `section_p` against the guarded
  executor.**~~ **Closed without spending it — F-headroom.** The live re-run
  would measure how a model responds to a guard message no shipping scheme ever
  reads: the two S8 guards are tripped by 20 `section_naive` and 20 `section_p`
  trials and by **0 of the 3470** trials from every later section scheme,
  `section_g_hpath` included — which ran the three provoking tasks 120 times.
  The later schemas carry `overwrite` and spell the address `heading`, so
  neither guard has a caller. Caveat 7 stays open in principle; this particular
  answer to it cannot be bought.
- ~~Extend to frontmatter (PLAN.md §4.4) before Tier 3 of the build order is
  designed on assumption.~~ **Done for Arm B — F-frontmatter.** The family is
  built, tested and measured: `mdfront.py`, two ops plus a read, three synthetic
  fixtures, eleven tasks, a grading ladder, two schemes, 220 trials. The Rust
  port, `difftest.py` cases, mutations, `invariants.rs`, CLI subcommands and Arm
  C are the later decision REQUIREMENTS.md:1716-1724 reserves, and they are now
  a decision made against measured numbers rather than on assumption. Two items
  it opened are below, both now closed by F-frontread.
- ~~**`set-dana-role` measures a coin flip.**~~ **Done — F-frontread.** Neither
  of the two proposals in this item was the fix. The family has had
  `frontmatter_get` since the day it was built and **no scheme published it** —
  the same defect 3b opened with for tables, one family later. `front_r` is
  `front_p` plus that read tool, and the task goes 3/10 → 7/10 → **10/10**, with
  all ten trials reading first and all ten then addressing `authors[1].role`.
  The read fired in **10 of 110 trials, all of them this task, 0 of the other
  100**. This item's closing sentence stands unchanged and is now measured
  twice: the tuned description still has no effect established at p < 0.05 once
  this task is excluded (+3 −0, p = 0.25), and still has never made a trial
  worse across 220 paired trials.
- ~~**`release-bump` measures the word "cut", not the edit.**~~ **Done —
  F-frontread**, and it was wrong in a second way this item could not see.
  `Cut` → `Update` took **20 destroyed documents to 0**, and the task then
  scored **0/30**: all thirty trials made both calls with both values bare and
  named the new key `release_date`, which the instruction permitted and the
  expectation forbade. The instruction now names `released` — chosen over
  loosening the expectation, because a task that accepts two different documents
  cannot pin the bytes `rich.md:37-43` exists to protect — and the task is
  **10/10 in all three schemes**. The evidence about verb collision this item
  called the clearest yet is unchanged and is now quantified.
- **`add-build-cache` is under-determined, and is being left that way.** *"Turn
  on caching for the build"* names no key; across 30 F-frontread trials the model
  wrote `build.cache` 22 times and `build.caching` 8. This is `release-bump` v2's
  defect in a milder form — genuinely ambiguous rather than unanimously resolved
  the other way — and it is **not** being fixed and re-run, because two rounds of
  fix-and-re-run on one task set is where repair stops being repair. Reported so
  that the 6/10 to 7/10 scores on this task are read as an instrument limit and
  not as a scheme difference. Deciding it needs a *paired* run of the two
  phrasings, not another edit.
- ~~**Should the read tool ship in the published frontmatter schema?**~~
  **Closed by F-compose. `table_get` ships; no frontmatter read ships anywhere.**
  `schematest.py` still pins three tools; `front_r` is bench-only. The evidence
  for shipping it is the discrimination result — used on the one task that
  needed it, never on the other hundred — and the evidence against is that the
  overall gain is not significant (p = 0.6875) and S14 measured what an extra
  call costs when it is not needed. **Unblocked by F-frontport**, which was the
  thing this was downstream of: `frontmatter_get` now exists in the crate and
  `incise keys` publishes it on the CLI, so shipping it is one `schema.rs` entry
  rather than a port. Deliberately left undecided there so the decision rests on
  its own evidence; what it still wants is a measurement of the cost side, since
  everything above is about the benefit.

  **Superseded in scope by F-compose, and the premise was wrong.** There is no
  published frontmatter schema for the read to ship "in" — `schema.rs` publishes
  no frontmatter tool at all, so the prior question was whether the family ships
  at all. F-compose measured that, and found the two questions have different
  answers depending on which baseline is taken: against one tool the composition
  costs 5.4 points (p = 1.3e-05); against the three tools the product already
  publishes it costs nothing (6–4 of 310, p = 0.75, post-hoc). The read that
  F-compose priced is `table_get`, not `frontmatter_get` — the frontmatter read
  is **not** a candidate and the reason is now sharper than "cost unmeasured":
  `front_r`'s result is the tool *and* `SYSTEM_PROMPTS["frontmatter_read"]`'s
  extra sentence, measured together, and `schema.rs` ships no system prompt. The
  tool without the sentence is a condition nobody ran.

  **Settled.** `schema.rs` publishes five tools: `frontmatter_edit` from
  `front_p` and `table_get` from `table_read_g`. `frontmatter_get` ships
  nowhere, for the reason above. The pre-registered rule was overridden to do
  it — see "The decision taken, and the fact that it overrides the rule" in
  F-compose, where the override and its limits are written down.
- ~~**`REQUIREMENTS.md:405` is behind the implementation on addressing.**~~
  **Done.** It promised dotted paths only; `corpus/frontmatter/rich.md:50` names
  `authors[0].role` and `mdfront.parse_path` has supported both since the family
  was built, so the requirement was the document that had to move. §5.1's row now
  names bracket indices, and **§6.5 grew from two lines to the contract the
  fixtures already state** — the preservation clause with `rich.md:37-52` named
  as its acceptance test, the four distinctions the fixtures pin (absent vs
  empty; `set` on an absent block creating `---` at the top with the rest
  byte-identical; deleting the last key leaving the empty block; TOML refused by
  name while the other three families keep working on the same file), the note
  that `frontmatter_span` accepts `+++` so a frontmatter op has to re-inspect the
  delimiter itself, and `frontmatter-get` being a read and therefore off
  `apply_op`. All four were re-run against `incise_ops` before being written down
  rather than transcribed from the fixtures' prose.
- ~~**`describe_change` has no home yet.**~~ **Done — F-front.** It was ported
  into the crate with Tier 2c's addendum, and `crates/incise-cli` is now the
  caller that prints it: a successful edit emits the one sentence and nothing
  else, which is the result shape S14 adopted. The Rust side can now both
  perform every measured edit and return it the way it was measured.
- ~~**The three families disagree three ways about addressing.**~~ **Done —
  F-address**, and there were four, not three: `{"ordinal": "0"}`, `{"path": 1}`,
  `position`, and the ordinal refusal that answered `ordinal: 1` with `Valid
  ordinals: 0`. Reconciled in one decision on the shipping schema and re-measured
  together, as this asked. **What the re-measure can and cannot carry is stated
  there and is the part still open**: the existing tasks never push a model into
  the argument shapes where the addressing diverged, so Arm B bounds the harm at
  nothing and cannot show a gain, and **Arm C has not been run at all**. A task
  set built to provoke these shapes is the honest prerequisite for any positive
  claim, and does not exist.
- ~~**A missing `action` is answered with thirteen op names and never with the
  word `action`.**~~ **Built, unrun — F-action.** The check exists in
  `armb.normalize` behind `CHECK_ACTION`, default off, and moves nothing with
  the flag off across 9455 replayed calls. Reading the population first changed
  what it had to say: in `bench/results/` there are **no** missing or
  misspelled `action` values at all — three of the check's four messages have no
  caller anywhere — and the `*-None` calls are a JSON
  failure — `"action=add-item,item"` as one fused key — where the caller did
  send `action` and the documented message would have been false to it. The
  omission is real in the live hermes runs (R2, R4) but not in any arm file, so
  both sentences were written and neither pool can size a condition, and the
  live runs may not be quoted beside an arm number.
  **F-frontread corrected one half of that.** The fused-key failure is not a
  list-family quirk and not one seed's accident: it recurs on `frontmatter_edit`
  as `{"action=set,key": "build.cache", ...}`, on `add-build-cache` seed t8, in
  `front_naive` *and* `front_p`, in the base run *and* both the v2 and v3
  re-runs — six occurrences, two families, deterministic on one seed. So it is a
  seed-correlated generation failure that reproduces across families. What that
  narrows is the mechanism,
  not the case for measuring it: in none of these calls is `action` missing, it
  is fused, and a check that asks *is `action` present* cannot see any of them.
  A check that could would have to notice a key containing `=`, which is a
  different sentence from the one this item was built to measure.
  **The sizing is now a command**, `bench/action_sizing.py`: 11 of 7535
  edit-tool calls reach the check, from two seeds, and it prints every message
  it can still raise. Rendering them that way found two §5.3 defects in the one
  reachable message (an instruction fused onto a list; an example that could
  recommend an action the same message declares invalid), both fixed, and
  retired the `OPS`-derived `ACTIONS` that would have offered `table-realign` —
  an op no tool publishes — as part of the condition.
  **What stays open is the measurement**, not the mechanism — same standing as
  the two plugin divergences below. The two observations that may bear on it
  still hold: `list_edit` declares `list` required and the core resolves without
  it — no live call ever supplied one, including the successful one — so the one
  family whose required set the model does not satisfy is the one family where
  it drops the verb; and `table_edit` and `section_edit` did not make the
  mistake in any of the four runs.
  **Now closed as undecidable rather than pending** (F-action, *"The design
  question, answered without code"*). The design was the easy half and the
  answer is neither of the two the question offered: the core cannot learn its
  caller without breaking `main.rs`'s contract and `difftest.py`'s premise, the
  front end may not re-spell a refusal under §5.3, and `normalize` refusing
  first — which is what `CHECK_ACTION` already is — is neither. The hard half is
  arithmetic. `headroom.py` prices the branch at **k = 1 reachable of n = 2041**
  over the five adopted schemes against a floor of 6, so best achievable
  p = 1.0000; the fault is a seed-correlated JSON collapse, so no task set can
  raise `k` on purpose; and of the 21 recorded fused-key calls, 16 already end
  in a correct document, with all five failures under two schemes that do not
  ship. `CHECK_ACTION` stays off. The survey recomputes `k` every run, so the
  item reopens itself if the corpus ever carries it past the floor.
- ~~**Arm C (end-to-end, real incise binary) is now runnable, and has not been
  run.**~~ **Done — Arm C.** 410 trials against the release binary on real
  files, ceiling 31/31. On the 351 trials where the model named a file the two
  executors disagreed **zero** times, so §9's bar is met; the 15 paired
  regressions are all `usage_error`, a class Arm B could not produce because it
  never read `path`. Sections lost 12 of their 14 silent corruptions in the
  process. Two things that item assumed turned out not to hold: Arm C drives
  `crates/incise-cli`, **not** `plugins/hermes/`, because a plugin-driven result
  may not be reported beside an Arm B number (`plugins/hermes/README.md:153-158`,
  `PLAN.md:1577-1591`) — so the plugin's `{"error": ...}` framing and the host's
  2048-character cap are **not** what Arm C measured across. Both stay open,
  below.
- ~~**The plugin's two divergences from what was measured are still
  unmeasured.**~~ **Done — F-framing**, and there turned out to be one of them,
  not two. Re-executing the first call of every trial in `bench/results/` gives
  353 real refusals, of which **one** crosses the host's 2048 cap — by 9
  characters. The cap condition cannot be sized, and on the other 352 prefixes
  it is byte-identical to the JSON framing, because the host composes them
  (`tool_error` bounds the body and *then* encodes it). Divergence 2 is
  measured-and-inert on every distribution this project has, rather than
  unmeasured; it revives if the corpus grows more tables.
  Divergence 1 was run over 202 refused prefixes — lists, sections and tables —
  at four turns: **no effect on the graded outcome** (18–17, p = 1.00). A
  one-turn cost that looked consistent on the first two families (22–11,
  p = 0.080) did not survive the third: tables is level at 6–6, and the pool
  goes to 28–17, **p = 0.135**. Recorded as a measured null on the endpoint that
  matters, with the one-turn question unresolved and not quotable as a cost.
- ~~A missing `path` is answered by clap, not by incise.~~ **Half done —
  F-nofile.** The mechanism is fixed: `file` is no longer `required` in the
  command tree, the check runs after `Format` is known, and a missing file now
  exits 2 through `out::usage` — so a `--json` caller gets an `error` field
  where clap gave it an empty stdout. But the *measured* premise did not hold. A
  three-condition replay over all 59 failed prefixes found the wording channel
  nearly inert: lists recover at 83–96% under every message including clap's,
  sections at 9–26% under every message including incise's, and neither incise
  wording beat clap on the sections. **What stays open is the section family's
  9–26%**, which is an S15-shaped problem (the schema, not the sentence) and not
  a wording one — the same rows show the model editing `section`/`text`/
  `new_heading` rather than supplying a file on ~28 of 34 trials.
  **Located — F-fileblind.** It is one action, not the family:
  `section-insert` names no file on **92%** of 1007 calls under the adopted
  `section_g` family against 9.7% of 31 under its untuned predecessors (paired
  on the 16 shared insert trials, **15–0, p = 6.1e-5**), while every other
  section action got better or held across the same transition. And the reason
  it could drift is that **Arm B cannot grade the file argument at all** — the
  harness opens the fixture and the core ignores `path`, so a call naming
  `/nowhere/absent.md` grades exactly like a correct one. **Sized, in the arm
  that can score it:** all 149 Arm C section trials split on this one argument
  and nothing else — the 114 that named a file exited 0 every time and finished
  `correct` 112 times (98.2%); the 35 that did not exited 2 every time and
  finished `correct` 8 times (22.9%), four turns of recovery included. Holding
  the task fixed leaves 91.7% against 28.0%, exact stratified **p = 0.016**. The
  split is the model's own choice rather than an assignment, so the
  counterfactual is not established — but the design that would settle it is now
  specified and cheap: a single-factor **Arm C** A/B on `section_g`'s insert
  clause, with these 149 trials as the control and an endpoint (*did the opening
  call name a file*) that reads straight off `exit_codes` with no grading pass.
  `bench/file_argument.py` is the sizing.
  **Cause found, and the experiment above is superseded — it was the wrong one.**
  S15 already ran the assigned, paired test: three arms, one key moved each,
  descriptions byte-identical. On insert, renaming the *top-level* slot to
  `file` moves file-naming 1/40 → 17/40 (**0–16, p = 3.1e-5**, clears Bonferroni
  at 12 comparisons; all 17 are the task's own fixture), while disambiguating
  the *address* instead moves it only to 6/40 (p = 0.063). By S15's own
  pre-registered rule that makes **the top-level name the thing pulling the
  value** — two arguments called `path`, one of which is not a path. S15 could
  not see this because its endpoint was misfiling, on which the two renames are
  exactly identical. Not free, and the cost is the reason to test rather than
  adopt: `section_g_file` is 10–1 *worse* on rename (p = 0.012, does not clear
  Bonferroni, 8 of 10 on one task), with the model filling `text` instead —
  once with the literal words *"File not provided for rename operation"*. The
  adopted `section_g_hpath` is the better of the two pooled (24–0, nothing worse
  anywhere, p = 1.2e-7) and still leaves insert at 15%. ~~**Open: the
  combination**~~ **Closed — S16 ran it and it is not adoptable.** The empty cell
  of S15's 2×2 (`file` *and* `section.heading`) was pre-registered in a commit
  before the arm ran, then run as 150 Arm B trials against `section_g_hpath`'s
  stored rows. The primary held — insert file-naming 15% → 48%, **3–16,
  p = 0.0044**, all 19 the task's own fixture — and the **pre-registered harm
  fired**: rename **10–0 backwards, p = 0.0020**, all ten on `rename-closed-atx`,
  all ten with the same key set and `text` filled where the file should be.
  Pooled **13–17, p = 0.58**: the win and the loss are the same size. The two
  renames are in tension rather than additive, `section_g_hpath` stays, and the
  remaining lever is not a third schema variant. The methodological result is
  that a post-hoc signal which **failed** Bonferroni at 12 (p = 0.012) was named
  in advance as the blocker and replicated at p = 0.002.
- ~~**Is the JSON framing's one-turn cost real?**~~ **Asked and answered, in the
  direction that closes it.** Extending F-framing from 141 to 202 prefixes with
  the tables family moved it from 22–11 (p = 0.080) to 28–17 (**p = 0.135**).
  More n from this pool is not worth spending: the ceiling is 353 prefixes,
  about 1.7× what has been run, and the trend from adding data was toward the
  null. The live version of the question is **single-turn callers**, below,
  which is a different experiment rather than more of this one.
- **A population figure published here was wrong for one commit.** F-framing
  originally reported 726 refusals. The true exit-1 count over `bench/results/`
  is 1727, of which **1374 are the harness pointed at the wrong executor** — Arm
  A's `patch`, the frontmatter ops the Rust core has not got, and the two reads
  that are off `apply_op` by design. Corrected above to 353, and made
  regenerable by `bench/refusal_pool.py` rather than left as a number this
  document quotes and nothing recomputes. The
  experiment itself is unaffected — its prefixes contain only `list_edit`,
  `section_edit` and `table_edit` first calls, no `patch` — and the over-cap
  numerator survives unchanged. The lesson is the reusable half: **`results/` is
  not one population.** Any future count over it has to select on arm before it
  counts, the way the replay's own `--tag` does.
- ~~**The framing was only ever measured at four turns.**~~ **Closed, without
  new trials.** A single-turn caller's only attempt is the trial's second call,
  and the turn budget never reaches the model, so grading `tool_calls[:2]` over
  the same rows *is* the experiment. 60.9% against 55.9%, 25–15, p = 0.154 —
  the same non-significant lean, with tables level again. It also shows the
  mechanism directly: `json` starts 10 behind at one turn and finishes 1 behind
  at four, because turns 2–4 repair 36 of its trials against `plain`'s 27.
- **What the JSON framing damages is not what was predicted.** F-framing
  pre-registered that escaping destroys §5.3's shape — statement plus indented
  continuations — and the stratified result does not support it: the 41 prefixes
  where nothing but the `{"error": …}` wrapper changes move 7–2, a *larger*
  share than the 105 where both escapes fire (15–8), while the newline-only
  stratum runs backwards at 6–7. So flattening incise's refusals to one line,
  the fix that would otherwise look obvious, would be aimed at the stratum
  showing the least effect. Whether the wrapper itself is the mechanism or this
  is noise is not answerable at this n.
- ~~**`list-add-item`'s `position` accepts anything and means "end".**~~
  **Closed by F-address.** `list_add_item` routes `position` through
  `_check_position_in(..., "list")` (`incise_ops.py:1612`, `ops/list.rs`), so
  `0`, `null` and `true` are refused on both families and `"Start"` no longer
  means *start* on a table and *end* on a list. The schema decision was made and
  re-measured rather than edited quietly, which is what this item asked for.
- ~~**Arm C cannot execute a read.**~~ **Done — F-armcread.** Both halves were
  buildable and both are built: `rows` takes `--args`, so a model's argument
  object reaches the binary untranslated, and `rows --json` returns the
  structured rows beside the rendered text, so the grader scores `TableRows`
  rather than a golden for the renderer. Arm C then reproduces Arm B's grades on
  **120 of 120** recorded read trials, zero hash mismatches. The tool result was
  never the open part — it is `render_table_get`'s string in both arms — and that
  is now true by construction rather than by a check on four files.
- **A `filter` value is matched literally, and one trial in 60 assumed globs.**
  `{"Name": "*"}` matched nothing, correctly. Saying so in the argument
  description is the obvious next tune and it is not measured; F-read's 96.7% is
  the number a new description would have to beat. **F-headroom prices it and it
  cannot be bought as stated**: k=1 gives a best achievable p of 1.0000, and a
  description reaches every trial, so the one-in-sixty gain is capped while the
  loss is not. `table_read_naive` never sends `filter` at all. This stays open
  behind the prior question — whether the read tool ships — rather than as a
  wording decision.

  **The prior question is answered and it made this one harder, not easier.**
  `table_get` ships (F-compose), so `filter`'s description is now published
  contract under REQUIREMENTS §6 and `bench/schematest.py` asserts it byte for
  byte against `table_read_g`. Rewording it is no longer a tune to a bench-only
  scheme; it is a schema change that needs a run, and F-headroom has already
  priced that run at a best achievable p of 1.0000. So it is not blocked any
  more — it is **closed to a description change** and open only to a different
  instrument: a task set where a glob-shaped filter is worth sending more than
  once in sixty. Shipping the word is also what put `filter` into
  `declared_arguments()`, which retired its `ALLOWED_BACKTICKS` exception.

- ~~**Nothing checks that the two replays agree about which recorded calls are
  executable.**~~ **Done — F-agree.** `headroom.py` and `regrade_snapshot.py`
  both replay every recorded tool call, were written months apart for different
  questions, and carried the *identical* read-blindness defect — fixed in one
  during F-remedy's control arm, still in the other a week later, where it came
  one command from voiding F-remedy's treatment. `bench/replaycheck.py` walks all
  **13361** recorded calls and asks each module's own `disposition()` what it
  does with each; they agree on 12982 and differ on 379, all Arm A's `patch`,
  which is on `EXPECTED_ONE_SIDED` with the reason attached. A `read`/`edit`
  split fails the check outright. It also asserts the coincidence the two rested
  on without anyone writing it down: `headroom` tests `op in armb.READS` and
  `regrade_snapshot` tests `name in armb.READS`, and those are the same test only
  while `normalize` returns the tool name unchanged for a read.

## F-pi-live — the published Pi package clears its live composition gate

The package-level question was narrower than F-compose and closer to what a user installs: does adding the three structural discovery tools to the five established tools change correctness when the actual published `pi-incise@0.1.1` extension runs through Pi 0.85.1? The plan was committed at `455ffda` and posted as issue 10 before a live-model outcome existed. It fixed 48 tasks, ten paired seeds, four turns, Pi default prompt construction, the historical Gemma 4 26B server condition, and a two-part gate: pooled exact McNemar must not show a loss at 0.05, and no family may lose more than 5.0 percentage points.

The answer is yes: this measured package condition passes. This result does not replace F-compose. That finding remains current for its original five-tool schema, injected summaries, and executor. The lower baseline here is evidence about the Pi prompt and validation path used here, not a regrade of a historical pool.

### The package and harness passed their claps before treatment

The manifest pins Pi 0.85.1, `pi-incise@0.1.1`, package integrity `sha512-1CmFNYv5Ko1GcZjqdp70PFdFYKxK7TwfzUGx035wkF4zDSWvwdPRKehXVwVAl+QWPEVKp9oacj5HDmznkC7hnQ==`, the packaged `incise 0.1.1` Darwin arm64 binary, system-prompt and schema hashes, task hashes, model hash, and server flags. Both ideal-call ceilings were 48/48. The control determinism clap then matched all 48 seed-zero trials on both graded outcome and normalized call sequence; each repeat was 42/48 correct.

An earlier clap attempt was invalid because the custom provider had not been registered in Pi’s `ModelRuntime`. Every row failed before inference. Those records are retained under the `pi_0_1_1_clap_auth_failure` prefix, the provider wiring fix is a separate commit, and no invalid row entered the control or treatment pool.

### The preregistered gate passes

One treatment pair, `rename-setext` trial 1, hit the fixed 900-second worker timeout on its initial attempt and its one retry. Both attempts remain in the raw pool. The pair is excluded under the preregistered transport rule, leaving 479 complete pairs.

Control was 397/479 correct, 82.9%, and treatment was 393/479, 82.0%. Of the discordant pairs, 28 succeeded only in control and 24 only in treatment; two-sided exact McNemar p = 0.677809. The pooled endpoint therefore does not show a significant loss.

The family guardrail also holds. Tables stayed 60/60 to 60/60. Lists improved from 91/100 to 96/100, plus 5.0 points. Sections moved from 106/149 to 102/149, minus 2.7 points; frontmatter from 91/110 to 88/110, minus 2.7; table-read from 49/60 to 47/60, minus 3.3. The worst loss is inside the fixed 5.0-point boundary. The package passes the rule as written.

### The reads move work, failure class, and cost more than correctness

Silent corruption, defined as `wrong`, either collateral class, or `destructive`, moved from 31/479, 6.5%, to 28/479, 5.8%. Loud `op_error` outcomes rose from 40 to 45. Pi schema-validation error results fell from 178 to 163, while handler refusal results rose from 60 to 75. This is not an accuracy win, but it is a small movement from silent damage toward visible refusal.

The model used a new structural read in 54 distinct trials: `md_lists` in 28 trials with 24 correct, `md_outline` in 25 with 10 correct, and `md_tables` in one with one correct. The reads were not confined to their intended edit families. Ten frontmatter trials called `md_outline`, and cross-family calls rose from 57 in control to 87 in treatment. That is the clearest compositional weakness left by the pass.

The extra surface also costs work. Mean calls rose from 1.52 to 1.69, mean turns from 2.52 to 2.68, mean completion tokens from 141.1 to 150.9, and mean elapsed time from 6.48 to 7.81 seconds. The gate deliberately judged correctness, not efficiency; these secondary movements are real and should constrain any claim that the discovery tools are free.

### The stable claim is deliberately bounded

`pi-incise@0.1.1` is stable for the measured Pi 0.85.1, Gemma 4 26B, macOS arm64, frozen 48-task population. This is direct evidence from the package users install, not from a mock schema or a repository binary. It licenses the stable designation fixed in the plan.

It does not license a claim about Windows, which is out of scope; other operating systems or architectures; other models; later Pi releases; or a larger tool surface. It also does not erase the efficiency cost or the `md_outline` cross-family behavior. A later package or Pi version needs a new named run rather than overwriting this pool.

Pools are `bench/results/pi_0_1_1_{control,treatment}.jsonl` and their graded siblings. The primary decision is `pi_0_1_1_analysis.json`, secondary diagnostics are `pi_0_1_1_secondary.json`, and `pi_0_1_1_run_manifest.json` pins exact execution and artifact hashes. Historical F-compose remains current within its stated condition.

## F-gemma-roadmap — narrow routing wins; generic atomic insertion does not

The preregistered current-checkout Pi refresh ran all 480 frozen Gemma 4 26B pairs with no transport exclusions. It scored 390/480 (81.3%): tables 60/60, lists 93/100, sections 109/150 (72.7%), frontmatter 79/110 (71.8%), and table reads 49/60 (81.7%). This is a new current-checkout condition, not a replacement for the published Pi 0.1.1 package claim.

Four paired, evaluation-only treatments followed. A host-resolved section target with action-specific content fields improved the two destructive target-selection tasks from 17/20 to 20/20, with no regressions or damage. A constrained one-shot table query improved the two filtered-read tasks from 9/20 to 20/20 (exact McNemar p = 0.0009765625), eliminating ten unfiltered results and one destructive wrong-family action. Both preregistered gates passed.

Typed existing-key frontmatter moved 26/50 to 45/50 (p = 0.0000209808349609375) and eliminated all destructive outcomes, but failed its strict gate: one baseline-correct `clear-title` pair became a no-tool prose response. The other four misses were also no-tool responses, not bad writes. This licenses a forced-tool-choice follow-up, not adoption of the measured treatment.

The atomic section-tree treatment failed: 7/40 to 1/40, with seven baseline-correct regressions and one collateral-content result. Gemma understood `children` but invented body prose, selected the wrong placement anchor, or reconstructed existing outline sections. Structured children alone must not ship for Gemma. The next section experiment should split planning from content: host-resolve the literal anchor and relation, then expose a required-slot content tool whose schema contains only the requested heading/body/child fields.

The plan and harness were committed at `a69fc62` (dispatch-only no-sample correction at `71ce41c`). Raw, graded, and paired artifacts use `bench/results/gemma_roadmap_20260921_*`; `gemma_roadmap_20260921_analysis.json` records the gates.
