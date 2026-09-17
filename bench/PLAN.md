# Benchmark plan

Status: three families run — tables 613 trials, lists 600 trials, sections 430
(both arms plus a fix arm) + 77 retries + 510 multi-turn + 1179 replay
+ 600 rename, **4009 total** ·
frontmatter not started · 2026-09-07
Resolves: `REQUIREMENTS.md` §12.1 (partially — see §12.1's own list of what
remains open)

The purpose of this harness is to produce the number that justifies (or kills)
the project: **how often does a local small model corrupt a markdown file when
editing it directly, and does incise meaningfully reduce that?**

Both halves of that question now have an answer for **two** op families. The
second family is what makes the first interpretable: it inverted one of the
table family's conclusions outright (B7 vs L2), which is the evidence that these
results are schema-and-family-specific and must be measured per family rather
than generalized.

> **Results live in `FINDINGS.md`.** This file is the method; that file is what
> was measured. Read `FINDINGS.md` before designing anything.
>
> **Arm A** (F1–F7, 180 trials): **60% correct** in both reasoning conditions,
> 30–37% silent corruption, 7–20% outright data loss. Alignment maintenance is
> isolated as the cause, reasoning does not fix it (McNemar p = 1.0 at 16× the
> tokens), and the repeat-penalty confound was tested and closed.
>
> **Arm B** (B1–B7, 433 trials): incise ops with **no document in context**
> score **60/60 — 100%** on the adopted schema (Wilson 94.0–100), with **zero**
> data loss and **zero** silent corruption. The forced re-pad task went
> 0/10 → 10/10. Getting there took three measured changes and cost 433 trials:
> op naming did not resolve on correctness (p = 0.167) but the two schemes fail
> at different things, and the tiebreak went to the loud failure mode; accepting
> ordered row values removed the last silent failure class outright — 7/60 →
> 0/60, p = 0.0156; and one sentence of tool *description* naming the `table`
> address on every action line closed the last refusal, 57/60 → 60/60. The
> settled schema is one tool with one untyped `values` argument taking an object
> or an array. **100% is not "always"** — see B7's caveat and caveat 2 in
> `FINDINGS.md`; it is a signal to extend the benchmark, not to stop.
>
> **Lists** (L1–L6, 600 trials): the extension that signal called for, and the
> reason to read the table results narrowly. The design transfers — Arm A
> **63/100** with **30% silent corruption** against Arm B's best **94/100** with
> **zero** silent corruption across all 500 tool trials (McNemar
> p = 1.6×10⁻⁶). But two table-family conclusions did not survive it. B7's
> address-naming prose, ported verbatim, *lost* 19 points (80 → 61,
> p = 0.00088). Renaming one parameter — `item` → `match`, so the selector no
> longer looks like the payload — gained 30 with **0/30 discordant,
> p = 1.9×10⁻⁹**, the single largest effect measured anywhere in this
> benchmark. A 2×2 shows the two factors *interact*: neither has a main effect.
> **Name the parameters before writing the descriptions.**

Sections below are the original plan. Where a section has been overtaken by a
measurement, it says so and points at the finding.

## 1. What the running server tells us

Read from the process table only — no requests were made.

```
llama-server -m gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf --alias gemma4-direct-q8
  --jinja --ctx-size 65536 --parallel 1 --n-gpu-layers 999
  --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on --cache-ram 8192
  --temperature 1.0 --top-k 64 --top-p 0.95 --min-p 0.05
  --repeat-penalty 1.15 --repeat-last-n 256 --presence-penalty 0
  --reasoning-budget 3000 --reasoning-format deepseek -n 8192
  --host 127.0.0.1 --port 8081
  --slot-save-path ~/.local/share/llama-models/slot-cache/
```

Hermes does not override any of these per request, so **these launch flags are
the condition under test.** That is unusually convenient: the baseline arm needs
to send no sampling parameters at all to be faithful.

Six consequences, in descending order of how much they change the plan.

### 1.1 The repeat penalty will corrupt table output — and may already be doing so

`--repeat-penalty 1.15 --repeat-last-n 256` penalizes tokens that appeared in
the last 256. Markdown tables are almost entirely repeated tokens: `|`, `---`,
recurring column values, aligned padding runs. A repetition penalty is actively
hostile to reproducing them verbatim.

This is a plausible and previously invisible contributor to the "small models
mangle tables" observation that motivated the project. It has to be isolated
before anything else, because if it explains most of the baseline error rate,
the honest answer is "fix your sampling params" and the project is much smaller
than we thought.

Therefore:

- **As built, the runner sends no sampling parameters and inherits the server
  defaults.** This reverses the original intent stated here, deliberately: the
  baseline's job is to measure the operator's *real* configuration, and hermes
  overrides nothing, so pinning parameters would measure a setup that does not
  exist. The cost is that the confound is inherited rather than controlled.
- **RESOLVED — the confound is dead (`FINDINGS.md` F7).** A matched 60-trial
  control at `repeat_penalty: 1.0` scored 37/60 against the baseline's 36/60
  (McNemar p = 1.000), and the forced re-pad task stayed at **0/10 with the
  penalty removed entirely**. The corruption is a capability limit, not a
  sampling artifact. The suspicion in this section was reasonable and wrong.
- `CONDITIONS` in `runner.py` is the hook for this: adding
  `{"repeat_penalty": 1.0}` as a condition is a one-line change, and results are
  keyed by condition so the arms stay comparable.

### 1.2 64k context means the premise needs restating

`REQUIREMENTS.md` §1 argues from "small context." At 65536 tokens that is not
this model's constraint — `api-reference.md` is ~7.5k tokens and fits eleven
times over. Context *overflow* is not the story here.

The real costs remain, but they should be named accurately:

- **Token cost.** Re-reading a 7.5k-token file to change one cell is 7.5k tokens
  of prefill per edit, plus output.
- **Latency.** Prefill plus a long verbatim rewrite dominates edit time.
- **Long-context degradation.** Accuracy at 8k of in-context document is not
  accuracy at 500 tokens, even when both fit.

All three are measurable by this harness, and the measurement should decide the
wording of §1 rather than the other way round. If the corruption rate turns out
to be flat with document length, the token-and-latency argument still stands on
its own and §1 should be rewritten to lead with it.

### 1.3 `--parallel 1` — the harness is strictly serial

One slot. No concurrency to exploit, and every request the harness makes is a
request the machine is not spending on your other work. So:

- Runs are serial, one in-flight request, no exceptions.
- `trials.jsonl` is append-only and every run is resumable, so a run can be
  killed mid-flight and continued later without losing completed trials.
- The runner takes `--max-trials` and `--time-budget` so a run can be boxed into
  a known window.
- The runner never starts a server and never assumes a URL — the endpoint is a
  required argument.

### 1.4 `--jinja` is on — native tool calling is available

The chat template is active, so both arms use the server's OpenAI-compatible
`tools` parameter. This matters more than it first appears: hermes edits files
*via a tool call*, not via prose edit blocks (§2.1), so tool calling is the
baseline mechanism, not just incise's.

### 1.5 Reasoning tokens dominate the cost

`--reasoning-budget 3000 --reasoning-format deepseek` means the model emits a
thinking trace, returned in a separate `reasoning_content` field. The pilot in
§2.3 spent **3000 of its 3070 completion tokens on reasoning** to add one table
row. Reasoning, not the edit, is the cost.

Consequences: the harness records `reasoning_content` length separately from the
answer; token-cost comparisons between arms must report reasoning and answer
tokens separately, or Arm A's cost will look like an artifact of verbosity
rather than of the task; and the reasoning traces are worth keeping, because
they show *how* the model gets alignment wrong, not just that it does.

**Measured:** reasoning does not improve editing accuracy on these tasks — both
conditions scored exactly 60% correct, with 18 discordant paired trials split
9/9 (`FINDINGS.md` F5). The traces did prove worth keeping, exactly as predicted
here: they show the model deriving the re-padding rule correctly and then
miscounting the columns (F6), which is the finding that most directly justifies
the tool.

**And a trap:** a `reasoning_budget: 0` request parameter is
**silently ignored** by this server — the request succeeds and still returns the
full ~3000-token trace. Only `chat_template_kwargs: {"enable_thinking": false}`
actually disables thinking: 111 tokens / 5.1 s versus 3070 tokens / 93.2 s on
the identical prompt. This was found by `runner.py --probe-conditions` and is
why that probe exists; it would otherwise have invalidated a 90-minute run.

### 1.6 `-n 8192` caps output — whole-file rewrites of long fixtures cannot fit

The output cap is 8192 tokens and roughly 3000 are consumed by reasoning,
leaving ~5000 for the answer. A whole-file rewrite of `api-reference.md` needs
~7500. **It cannot complete.** That is not a harness limitation to work around;
it is a measured result about this configuration, recorded as `malformed`
(truncated) and reported.

## 2. Experimental design

Three arms. The third cannot run until incise exists; the first two can run now
and are where the decision-relevant information is. (All three have now run —
the "Runnable" column records where each ended up.)

| Arm | What the model is asked to do | Measures | Runnable |
| --- | --- | --- | --- |
| **A** | Edit the file directly | The baseline error rate | **Done** — F1–F7 |
| **B** | Emit a incise tool call, validated against a mock | Whether the op vocabulary is usable | **Done** — B1–B7 (tables), L1–L6 (lists) |
| **C** | Emit a tool call, executed by real incise | End-to-end truth | **Done** — `bench/armc.py`, see FINDINGS "Arm C" |

**Arm B is the one worth emphasizing.** It runs against a mock that validates
the call and applies a hand-written reference implementation of the op — so it
measures whether the model can *address* the edit correctly, independent of
whether incise implements it correctly. That means the op naming and addressing
scheme (`REQUIREMENTS.md` §12.7, §5.1) can be settled with data *before* any
Rust is written, and competing naming schemes can be A/B'd for a few hours of
GPU time instead of a rewrite.

This worked, with one refinement worth recording. Arm B is only interpretable if
the mock's own ceiling is known, so the executor is validated first — twelve
hand-written ideal tool calls (six tasks × two schemes) must grade `correct`
before any model trial is run. Without that, a mock bug is indistinguishable
from a model failure and the whole arm reads as a capability result. The mock
(`incise_ops.py`) is also the differential-testing oracle for the Rust, so this
validation is not throwaway work.

**That check is now a script, not a habit.** `bench/ceiling.py` reads each
task's `ideal_call`, re-expresses it in every scheme's vocabulary — via its own
mapping table, deliberately not by reusing `armb.normalize`, so a mapping bug
cannot cancel itself out — and grades it through the real trial path. It read
50/50 across the five list schemes before any GPU time was spent. Two rules it
enforces that the hand check did not: it must be re-run after **every** schema
or executor change, and tasks with no `ideal_call` are **named in the output**
rather than silently skipped (the table task set predates the field, so its
ceiling is still only the hand-checked B1 result).

### 2.1 Arm A is hermes's `patch` tool, replicated exactly

Read from `~/.hermes/hermes-agent/tools/file_tools.py`. Hermes exposes
`read_file`, `write_file`, `patch`, and `search_files`. Editing goes through
`patch`:

```
patch(path, old_string, new_string, replace_all=false)
```

`patch` also has a V4A multi-file mode, but `_is_openai_family_main()` gates it
to the OpenAI/codex family — **gemma gets the replace-only schema**, so the
baseline must too. The harness embeds the schema and its description strings
verbatim; `bench/probe.py` already does.

Two further details that shape the baseline:

- `read_file` returns **line-numbered** content, so the model must strip line
  numbers when constructing `old_string`. That is a known error source and the
  harness reproduces it rather than feeding clean content.
- The `patch` description advertises **"fuzzy matching (9 strategies) so minor
  whitespace/indentation differences won't break it."** This makes the baseline
  considerably stronger than an exact-match editor, which is good for fairness —
  and introduces a failure mode of its own (§2.2).

So the sub-arms are:

- **A1 — `patch` tool call.** The primary baseline. Hermes's real edit path.
- **A2 — `write_file` whole-file rewrite.** Reference point only, and per §1.6
  it cannot even complete on the long fixtures.

### 2.2 Fuzzy matching is a hazard, and markdown is adversarial for it

Nine-strategy fuzzy matching is tuned for source code, where lines are mostly
distinctive. Markdown is the opposite: `| --- | --- | --- |` delimiter rows
recur, `### Fixed` appears under every release in a changelog, and table rows
share long runs of identical padding. A fuzzy matcher that tolerates whitespace
drift is precisely a matcher that can land on the wrong one of several
near-identical anchors — and it does so silently, which puts the result in the
`collateral` class rather than the `wrong` class.

This deserves its own task family (§4.7): edits where the `old_string` a model
would naturally choose is *not* unique. If fuzzy matching mismatches on
markdown at any appreciable rate, that alone is a strong argument for
content-addressed operations (`REQUIREMENTS.md` §5.1).

Corroboration that this is a live problem in practice: hermes carries a
dedicated `_record_patch_failure` tracker that escalates hints after repeated
failures on the same path, commented as "stale view of file contents, ambiguous
`old_string`, or the file was modified externally." It also tracks read
timestamps for external-edit detection — independently arriving at the
stale-read problem that `REQUIREMENTS.md` §5.5 solves with `--if-match`.

### 2.3 Pilot trial — one run, already suggestive

`bench/probe.py` ran a single Arm A1 trial: add a row to the 3-row table in
`corpus/tables/aligned.md` (576 bytes), using the exact hermes schema and no
sampling overrides.

| | |
| --- | --- |
| Wall-clock | **92.1 s** |
| Completion tokens | **3070** (≈3000 reasoning, ~70 answer) |
| Prompt tokens | 518 |
| Generation speed | 33.3 tok/s |
| `old_string` chosen | unique — correct |
| Result | **misaligned by one space** |

The model emitted `| sprocket     | active  | rowan   |` — 14 characters in the
first cell where every other row has 13. Its reasoning trace shows it explicitly
enumerating column widths and still getting the count wrong.

This is the predicted failure, on the easiest task in the corpus, in a file
small enough to fit in any context. Under the §5 taxonomy it grades
`collateral:formatting` — see the ruling in §5.1, which this trial prompted.

Do not over-read this. **N=1 at temperature 1.0 is an anecdote, not a rate.**
It establishes that the pipeline works end-to-end and that the failure mode is
real; it says nothing yet about frequency. That is what Phase 2 is for.

### 2.4 Do not run hermes itself — replicate its schema instead

You asked whether SOUL.md and the other context files can be suppressed. There
is a profile mechanism (`~/.hermes/profiles/`) that could probably be pointed at
a stripped-down bench profile, but I recommend against it, for a reason
independent of context contamination:

**The repeat-penalty sweep (§1.1) requires per-request sampling control, and
hermes does not override sampling.** Running through hermes makes the single
most important early experiment impossible.

Contamination is the secondary argument, and it is still substantial: a hermes
run would inject SOUL.md, memories, the skills prompt
(`.skills_prompt_snapshot.json` is 61 KB), MCP tool discovery, and session
state — none of it relevant to markdown editing, all of it varying between runs
and inflating prompt tokens in a way that would wreck the token-cost comparison.

So the harness talks directly to `127.0.0.1:8081` and embeds hermes's tool
schemas verbatim. The tradeoff is honest and worth stating: this measures
*hermes-style editing*, not *hermes exactly*. Anything in hermes's system prompt
that helps the model edit better is not credited to the baseline.

Mitigation, cheap and worth doing once: run three or four smoke tasks through
real hermes on a scratch copy of the corpus and check the outcome classes are
comparable. If they diverge, the replication is missing something and the
system prompt needs to be brought closer. That validation is the only thing
hermes needs to be run for.

## 3. Task definition

One task is one YAML record. Tasks live in `bench/tasks/*.yaml`, grouped by
family.

```yaml
- id: table-add-row-aligned
  family: table-add-row
  fixture: corpus/tables/aligned.md
  instruction: >
    Add a row to the Components table for a component named "sprocket"
    with status "active" and owner "rowan". Put it at the end of the table.
  golden: bench/golden/table-add-row-aligned.md
  # Arm B: the tool call considered correct, for mock validation
  expect_call:
    op: table-add-row
    args:
      section: Components
      values: {Component: sprocket, Status: active, Owner: rowan}
      position: end
  notes: >
    Aligned table — "sprocket" is longer than any existing Component value,
    so a correct edit re-pads every line of the table (REQUIREMENTS §5.2).
```

Design rules for instructions:

- Phrased as a user would phrase them, not as a tool call in prose. "Mark the
  `plan` feature as stable" — not "set the Status cell of the row where
  Feature=`plan` to `stable`." Leaking the tool's own vocabulary into the
  instruction rigs Arm B.
- Identical instruction text across all arms. Only the system prompt differs.
- Unambiguous, except for the deliberately ambiguous tasks in §4.5.

### 3.1 Golden files

`bench/golden/<task-id>.md` holds the expected output byte-for-byte.

**Goldens are never generated by the model under test.** They are hand-authored
or produced by a scripted transform and then read by a human. A golden is the
definition of correct; deriving it from a model's output defines correctness as
whatever the model did. Changes to a golden are reviewed like code.

Where more than one output is genuinely correct — for example, whether a new
changelog bullet goes first or last within its subsection — the task lists
`accept_alternates` with additional golden paths rather than loosening the
comparison.

**The two families run are graded to different standards, deliberately.** Tables
have no goldens: `correct` means "passes every mechanical check" (§5). Lists
have exact goldens, scoped to the target list, because a list's correctness *is*
its formatting — marker character, marker delimiter, indent width, loose/tight
spacing, checkbox spelling, numbering style — and a predicate for "numbered the
way *this* list is numbered" is a golden written less legibly. The list goldens
are generated by the reference implementation and then reviewed, which violates
§3.1's letter, so the honesty condition is enforced as a test:
`test_list_goldens` in `test_incise_ops.py` asserts the reference still produces
all ten committed goldens byte-for-byte. If the reference drifts, the test fails
rather than the goldens quietly following it. **Every report must state which
standard it is quoting** — "no goldens" is now false of half the corpus.

## 4. Task inventory

Roughly 40 tasks, each anchored to a corpus fixture. Two tiers: a **smoke** set
(~12 tasks, marked in the YAML) for iterating on prompts, and the **full** set
for headline runs.

### 4.1 Tables — the core case

| Task | Fixture | Trap |
| ---- | ------- | ---- |
| add row, aligned | `tables/aligned.md` | New value is longest; must re-pad the whole table |
| add row, ragged | `tables/ragged.md` | Must *not* prettify |
| add row, alignment markers | `tables/alignment-markers.md` | `:---:` must survive |
| add row, second of three | `tables/multiple-per-section.md` | Must pick the right table |
| update cell | `documents/project-readme.md` | Mark `plan` stable |
| update cell, deep in a long doc | `documents/api-reference.md` | 7.5k-token document |
| delete row | `documents/project-readme.md` | Composite key — `Platform` alone is not unique |
| sort numeric | `tables/sortable.md` | `1000` vs `9` |
| sort semver | `tables/sortable.md` | `1.10.0` vs `1.9.2` |
| sort stable | `tables/sortable.md` | Within-group order must survive |
| add column | `tables/aligned.md` | Every row and the delimiter row change |

### 4.2 Sections

Insert a new release section above the newest one (`changelog.md` — the
insert-at-top pattern); append a bullet to an existing `### Fixed`; add an
`### Added` subsection to a release that lacks one; replace a section body;
rename a heading in `sections/deep-nesting.md` where the leaf name repeats
under three different parents.

### 4.3 Lists — **run** (L1–L6)

Ten tasks, in `tasks/lists.json`, generated by `make_list_tasks.py` against the
51 lists `mdlist.py` finds in the corpus. The families as originally sketched
all survived, and the ordered-numbering pair turned out to carry the family's
headline the way the re-pad task carried the table family's.

| Task family | Trap |
| ----------- | ---- |
| add item, alphabetical position | Position is content-derived, not stated |
| toggle a nested checkbox | Indent and `[x]`/`[X]` spelling must survive |
| add to an all-ones ordered list | Renumbering **is** the bug |
| add to a sequential ordered list | Renumbering **is** required |
| add to an irregular list (`1. 3. 7.`) | Neither rule applies; leave it alone |
| add after a named item | Marker and indent copied from the sibling |
| remove an item | Loose/tight spacing must not flip |
| mixed markers (`-`, `*`, `+`) | Must not normalize to house style |

`add-item-ordered-renumber` replicated the table family's re-pad result exactly:
**0/10 Arm A, 10/10 Arm B.** One Arm A output invented `2.5.` as a list number.

Three numbering styles have to be distinguished, and this is the finding that
most constrains the implementation: a rule that *always* renumbers and a rule
that *never* renumbers are both wrong. See `REQUIREMENTS.md` §6.4.

### 4.4 Frontmatter

Set `build.jobs` in `frontmatter/rich.md` — the comments, key order, and block
scalars must survive. Create a block in `frontmatter/absent.md`. Set a key in
`frontmatter/empty.md`.

### 4.5 Ambiguity and no-op tasks

These two families are where the arms are expected to diverge most, and neither
is a normal "did it edit correctly" measurement.

- **Ambiguous.** "Update the Notes section" against
  `sections/duplicate-siblings.md`, which has three. The correct behavior is to
  refuse and ask. A model editing directly will almost always just pick one
  silently; incise fails with a candidate list by construction (§5.3). Measured
  as *refusal-when-ambiguous rate*.
- **No-op.** "Sort the Group column" on a table already sorted by it. The
  correct output is byte-identical to the input. Models are strongly biased
  toward making *some* change; this measures gratuitous edits directly.

### 4.6 Hazards

Edit a table two paragraphs below a fenced block that contains a fake table
(`hazards/code-fences.md`); add a row to the CRLF table inside
`hazards/mixed-endings.md`; add a bullet to `hazards/whitespace.md` without
adding a final newline or stripping the hard-break spaces; add a row to the
blockquoted table in `hazards/nested-blocks.md`.

### 4.7 Uniqueness traps — targeting hermes's fuzzy matcher

New family, added after reading the `patch` schema (§2.2). Each task is an edit
where the `old_string` a model would naturally reach for is **not unique**, so
either the model must work to disambiguate or the fuzzy matcher must pick, and
picking wrong is silent.

| Task | Fixture | Why the natural anchor is ambiguous |
| ---- | ------- | ----------------------------------- |
| add a bullet under the newest `### Fixed` | `documents/changelog.md` | `### Fixed` appears under several releases |
| add a row using the delimiter row as context | `tables/aligned.md` | `\| ----------- \| ------- \| ------- \|` is not unique across the corpus doc |
| edit the second of three identical `## Notes` | `sections/duplicate-siblings.md` | Three byte-identical headings |
| edit `### macOS` under Upgrade, not Install | `sections/deep-nesting.md` | Same leaf name under three parents |
| edit a row in the staging table | `tables/multiple-per-section.md` | Three tables share a column header row |

These are scored with special attention to `collateral`: an edit applied to the
*wrong* correct-looking location is the worst outcome in the taxonomy, and this
family is designed to provoke exactly that.

### 4.8 Does raggedness actually degrade model lookups?

Optional cell, testing an assumption rather than incise itself. The claim that
misaligned tables make lookups "slower and more difficult" is obvious for human
readers and merely plausible for models — aligned tables give regular, repeated
padding runs, and whether losing that regularity hurts a model's ability to
associate a value with its column is an empirical question.

Design: one lookup question ("what is the Owner of `widget-core`?") against two
byte-different, semantically identical fixtures — an aligned table and the same
table ragged. 2 conditions × 10 trials ≈ 30 minutes. Read-only, so it needs no
goldens and no grader beyond string matching.

Worth running because it either substantiates a rationale currently taken on
faith, or tells us the rationale is human-ergonomics only — which would still
justify the §5.1 ruling on the ratchet argument alone, but should change how the
report words it. Ranked below the reasoning-budget cell (§10) for GPU time.

## 5. Outcome taxonomy
Binary pass/fail throws away the finding that matters. Every trial is graded
into exactly one class:

| Class | Definition |
| ----- | ---------- |
| `exact` | Byte-identical to a golden |
| `semantic` | Intended change correct; only incidental formatting differs (compare parsed structure) |
| `destructive` | **An existing row or line disappeared that the task never asked to remove** |
| `collateral:formatting` | Intended change correct, but alignment or whitespace elsewhere was damaged; content intact |
| `collateral:content` | Intended change correct, **but content outside the target region changed** |
| `wrong` | Intended change absent or incorrect |
| `malformed` | Unparseable output, no edit block, truncated, or invalid tool JSON |
| `refused` | Model declined and asked for clarification |
| `overflow` | Prompt exceeded the context budget for that run |

`destructive` was added after the first graded pass and is graded **before**
`wrong`. It is not a refinement for its own sake: every one of the six `wrong`
trials in that pass turned out to be the same failure — the model overwrote a
neighbouring row while adding a new one — and the generic class concealed it
completely. See `FINDINGS.md` F2. Data loss is the worst outcome available here
and must never again aggregate with "didn't make the edit."

The `collateral` classes **and `destructive`** together are the headline metric.
They are the silent-corruption rate — the cases where a model reports success
and has damaged the document — and they are the specific harm incise's §5.2
byte-preservation invariant exists to prevent. A high combined rate in Arm A is
the strongest possible justification for the project; a low one is the strongest
argument against it.

**They are reported separately, always.** Breaking table alignment is
corruption (§5.1), and it is expected to be the more common of the two, so a
single merged number would be dominated by one-space padding errors while
reading as though content were being destroyed. Splitting them means the
`collateral:content` and `destructive` rates stand on their own evidence, which
makes the case stronger rather than weaker. Reporting only the merged figure —
or quietly dropping the formatting class to make the content number look purer —
are both failures of §11.

### 5.1 Ruling: breaking table alignment is corruption

Decided, not provisional. Two reasons, the second stronger than the first:

1. `REQUIREMENTS.md` §5.2 makes staying aligned a correctness property, so a
   misaligned table is a wrong result by the spec the tool is written to.
2. **It ratchets.** incise detects alignment from the table as found, and the
   detection is binary. A single introduced misalignment flips that table to
   "ragged" permanently: every later incise edit will faithfully preserve the
   raggedness, because that is the rule, and incise will never restore it
   because it is not a formatter (§3 non-goals). One bad edit therefore does not
   just damage a document — it silently downgrades the document class and
   changes the tool's own future behavior on that file forever.

Consequence for the tool, not just the grader: incise needs an explicit
`table-realign` operation (`REQUIREMENTS.md` §6.2) as the repair path, since
nothing else in the design can ever undo this damage.

A third rationale — that ragged tables make lookups harder — is clearly true for
human readers and plausible for models, but is currently an assumption. §4.8
turns it into a measurement.

`refused` is correct on §4.5 ambiguous tasks and a failure everywhere else, so
it is scored per-family rather than globally.

Grading is mechanical: `exact` by byte comparison, `collateral` by diffing the
output against both the input and the golden and checking whether any hunk falls
outside the golden's changed region. No model-graded judging anywhere in the
pipeline.

## 6. Metrics recorded per trial

Outcome class · prompt tokens · completion tokens · wall-clock ms ·
tokens/sec · collateral line count (lines changed beyond the golden's diff) ·
output truncated (bool) · full raw response · seed · every sampling parameter ·
SHA of the prompt template · SHA of the fixture · git rev of the repo.

Everything needed to explain a number six weeks from now is in the record.

## 7. Sampling and statistics

The server's `--temperature 1.0` default is high enough that variance will be
substantial, which forces real trial counts.

- **Pinned per request**, never inherited: `temperature`, `top_k`, `top_p`,
  `min_p`, `repeat_penalty`, `repeat_last_n`, `seed`, `n_predict`.
- **Primary condition:** the sampling settings you actually use in your agent
  setup, since that is what the baseline claim is about. Default assumption is
  the server's current values with `repeat_penalty` as the swept variable.
- **Reference condition:** `temperature: 0`. Not truly deterministic under
  llama.cpp (batching and MoE routing introduce variation), so still N=3.
- **N = 10** trials per task per arm in the primary condition, with seeds
  `0..9` reused across arms so comparisons are paired.
- Report **Wilson intervals**, not bare proportions. At N=10 a per-task rate has
  a granularity of 0.1 and enormous error bars; only family-level and
  arm-level aggregates should carry a headline claim.
- Compare arms with **McNemar's test** on the paired per-trial outcomes, not a
  two-proportion test on independent samples. Same task, same seed, two arms is
  a paired design and treating it otherwise overstates significance.

**This arithmetic is now a script.** `bench/stats.py` does Wilson intervals and
exact McNemar over graded `.jsonl`. It was done by hand for every result up to
B7 — fine once, a liability by the fourth op family. It exists to stop two
specific errors: reporting a proportion without an interval (60/60 and 6/6 are
both "100%"; their intervals are 94.0–100 and 61.0–100), and comparing two
paired schemes with two independent intervals (overlapping intervals do not
answer whether the disagreements are lopsided). Exact binomial tail sums, not a
chi-square approximation, because the discordant counts are routinely single
digits — 0/30 and 4/7 are both real results from the list family and neither is
in asymptotic territory. `--key scheme,condition` lets one invocation span Arm A
and Arm B files without a relabel collapsing several schemes onto one trial key.

## 8. Harness layout

```
bench/
  PLAN.md                  # this file — the method
  FINDINGS.md              # what was measured; read it first
  tasks/*.json             # task definitions by family (JSON, not YAML)
  make_list_tasks.py       # generates tasks/lists.json + its goldens
  golden/<task-id>.md      # expected outputs (lists only; see §3.1)
  mdlist.py                # list parser: finds every list in the corpus
  incise_ops.py            # reference implementation of every op
  test_incise_ops.py       # invariants over the whole corpus, not examples
  runner.py                # Arm A: renders prompts, calls the server, appends
  armb.py                  # Arm B: tool schemas, normalize, grade_one
  ceiling.py               # harness ceiling (§2) — run before every arm
  grade.py                 # classifies Arm A outcomes from trials.jsonl
  stats.py                 # Wilson intervals + exact McNemar (§7)
  s14_analyse.py           # S14 only: pairs replayed prefixes by result shape
  s15_analyse.py           # S15 only: three renames, stratified by task
  difftest.py              # Rust core vs incise_ops.py, byte-for-byte
  mutate.py                # proves difftest.py can fail (§8.1)
  probe.py                 # one-off pilot probe (§2.3); seed of runner.py
  results/*.jsonl          # append-only, one record per generation

crates/incise-core/        # the shipping implementation (Phase 2, started)
  src/{scan,heading,table,list}.rs # parsers
  src/ops/{table,list,section}.rs  # the three op families — all thirteen ops
  src/ops/dispatch.rs              # `OPS`, and which argument wins
  src/args.rs                      # the JSON argument layer (F-args)
  src/{similar,json}.rs            # ports of difflib and two Python str forms
  tests/invariants.rs              # §11's structural rules, over the corpus
  examples/oracle_cases.rs         # the Rust half of difftest.py
```

Two departures from the sketch above it, both worth naming. Tasks are JSON, not
YAML — no third-party parser for a format the harness only reads. And there is
no `mock/` directory: `incise_ops.py` is a single reference implementation
shared by Arm B, the goldens, and the invariant tests, so all three are
constrained by the same code rather than three drifting copies.

`test_incise_ops.py` earns its place. It asserts invariants over the **entire**
corpus, not hand-picked examples: add-then-remove is byte-identical across all
51 lists; untick-then-retick is byte-identical; every numbering style survives;
`+` is never normalized to `-`; a bare-string address produces output identical
to the object form. Those are the properties the Rust core is differential-
tested against (§8.1), so the tests are not throwaway either.

Python for the harness. It is analysis tooling that will never ship in the
binary, iteration speed matters more than runtime, and the plotting and stats
libraries are there. The cost is a second toolchain in a Rust repo — worth it
here, but `mock/apply.py` should be understood as a throwaway reference
implementation, not a second source of truth once the Rust core exists.

### 8.1 Differential testing, and testing the differential test

The Rust core is checked against `incise_ops.py` rather than against expected
outputs. `difftest.py` generates ~2900 cases from the corpus — every table in
every fixture, added to at three positions in both row shapes, updated,
deleted, and pushed down each refusal path, plus a structural dump of every
file's sections, tables and inert headings — runs both implementations, and
compares **byte-for-byte, including the refusal message**. §5.3 makes the
message part of the contract and Arm B measured recovery against those exact
sentences, so a reworded refusal is a regression, not a cosmetic change.

The cases are generated rather than written because hand-written cases test
what the author thought of. That is also the limit of the method: they test
what the *corpus* contains.

It agreed 2738/2738 on the first run, which is not evidence. A suite that has
never failed is equally consistent with a faithful port and with a harness that
compares nothing, so `mutate.py` settles it: it injects one deliberate fault
into the Rust core at a time — an off-by-one in a pad width, a byte count where
a character count belongs, a reworded refusal, a reversed tie-break in the
difflib port — and asserts the fault is caught.

Two of the first twelve mutations **survived**, and both were real gaps rather
than harness bugs:

- *Byte width for character width.* The corpus does hold non-ASCII cells in
  aligned tables, but only short ones (`—`, `–`) that are never the widest in
  their column — so the two counts agree everywhere it matters. A source
  comment claimed those fixtures covered it; they do not, and it claimed byte
  widths would *shorten* those rows when in fact they over-pad. Both wrong,
  both now fixed.
- *The minimum column width.* The floor exists so a centred delimiter (`:-:`)
  still fits. The only corpus column narrow enough to reach it is in
  `hazards/whitespace.md`, whose cells contain tabs — which make the table
  ragged, so it is never re-padded and never reaches the floor.

Both were closed without touching the corpus. **The corpus is a measured
artifact**: FINDINGS quotes per-file results against those 26 files, so it stays
frozen and coverage gaps get a synthetic document instead. Those documents live
in `bench/synthetic/` as files — one copy, read by both the differential
harness and the Rust invariants — for the reason given under F-fence below.

#### The layer the corpus cannot reach

Generating cases from documents has a second limit, sharper than "what the
corpus contains": every generated argument is **well-typed by construction**.
The address comes from `list_tables`, the column name from the header row. So
the validation layer — the code that decides whether the arguments are even the
right shape — was never on the generated path, in either implementation. That
is how three op families shipped with an executor that crashed on
`table: 5` and silently appended on `position: "0"` (FINDINGS F-args).

Two hand-written case families close it: `check_args` runs every value in
`ARG_VALUES` through every function in `ARG_FNS`, and `py_repr` checks the JSON
reader and Python-`repr` writer underneath. Hand-written, but as a **cross
product** rather than a list, which is the same defence the generated cases
have — it covers combinations nobody chose.

It paid immediately. Three divergences the port's own unit tests had asserted
away, all found by the machine:

- CPython's `json` accepts `Infinity`, `-Infinity` and `NaN` by default. The
  Rust parser did not, so a string containing one was refused where the oracle
  recovered it.
- Python integers have no width. `ordinal: 12345678901234567890123456789` is
  accepted and its digits are quoted back in the refusal, which an `i64` cannot
  carry — hence `args::PyInt`, and a `Big` variant that does no arithmetic.
- The same value as a `position` clamps to the end via `list.insert`'s
  semantics, which also count negatives from the right. Both now ported
  explicitly rather than by resemblance.

None of the three would have been found by reading, and the unit tests could
not have found them because their expectations were transcribed by the same
hand that wrote the code.

There is a third family, `apply_op`, and it exists because those two are still
one layer short. They check each validation function in isolation; what neither
can check is the **order** the dispatch runs them in — and that order is the
part Rust cannot derive, because in Python it is made by the language rather
than by the code. `ops/dispatch.rs` transcribes it, and the transcription rested
on a comment and on unit tests I had written the expectations for, which is the
failure mode this whole section is about. So `apply_op` cases are whole dispatch
calls with real JSON argument objects, compared on the message a model would
actually receive.

It caught three errors. `check_column` belongs *inside* `table_update_cell`,
after the table resolves, not at the dispatch — hoisting it, which is the
natural Rust shape, inverted 120 cases. `values: 7` is not refused by the
extraction layer at all: `_unstring` only rejects a string that fails to decode,
so a bare number reaches the op and gets a refusal naming both shapes, which
forced `Values::Other` and `json::py_truthy`. And `check_heading`/`check_ordinal`
are statements inside `resolve_table` rather than part of the address, so
`TableAddress` has to carry raw JSON in both fields.

The third one is the argument for keeping mutation testing in the loop rather
than treating it as a one-off audit. It was not found by the cases. It was found
by a **survived mutation**: swapping `address` and `values` in the dispatch
changed nothing, which meant no case had two arguments failing at the extraction
layer at once — and with one bad argument the message is identical either way.
Adding those cases exposed the heading defect on the next run. The mutation
found a hole in the test; the test then found a bug in the code.

Writing the dispatch also surfaced a fourth executor defect, the worst of the
family: `table-update-cell` never checked `value`, so a missing one wrote the
literal string `None` into the cell and reported success. Fixed, and re-proved
grade-neutral over the same 5674 recorded calls.

At that point the suite was 6561 cases and mutations ran 28/28, seven of them
aimed at the dispatch ordering and four reproducing exactly the errors above, so
the family that caught them is itself shown to go red. `disp-values-late` is in
that count now on 51 cases; before the gap was closed it was the survivor that
started this.

`crates/incise-core/tests/invariants.rs` carries what differential testing
structurally cannot. If both implementations ate a row they would still agree;
these assert the properties that must hold regardless — no op removes a row it
was not asked to remove, bytes outside the target range are unchanged, the
blank line after a table survives, re-padding widens and never shrinks, and a
ragged table is never prettified — over every table in the corpus. They were
themselves checked by mutation: a delete that removes an extra row fails two of
them by name, and an insert that swallows the following line fails three.

#### The assumption both implementations shared

Everything above finds divergences. None of it can find an **agreement that is
wrong**, and Tier 1 shipped with one: both sides read a cell as "the text
between two `|` characters". GFM says otherwise — a cell may hold a literal pipe
written `\|` — so `corpus/tables/cell-edge-cases.md` was read as four columns
where it has three. `table-update-cell` on that row overwrote a fragment and
emitted a four-column row, reported as success, on the fixture whose stated
purpose is "Any operation on this table must round-trip every cell exactly."
The write direction was the same hole from the other end: nothing stopped a
`value` containing a bare `|` or a newline from splitting one cell into two, or
one row into two.

Three defences were in place and all three were blind to it, each for a
different structural reason, which is why it is worth recording rather than just
fixing:

- **The differential suite** compares two implementations. Both split naively.
  They agreed, perfectly, on the wrong answer. A shared assumption is exactly
  the class of defect this method cannot reach — the same reason §2 needs
  `ceiling.py` and not just arm-vs-arm comparison.
- **The invariants** assert what must hold regardless, but the round-trip they
  carried was add-then-delete, which restores the *document*. The stronger
  claim — update a cell to the value it already has and the document is
  unchanged — was the one that would have failed, and it was not there.
  It is now: `test_identity_update_roundtrip`, 974 cells.
- **The mutation suite** validates the differential test, not the code. A
  mutation of a line that is wrong in both implementations can never fail a
  comparison between them. Mutating the naive split changed both sides
  identically, or changed neither.

Fixed in both directions — one shared splitting rule (`mdtable.split_row`,
`table::split_row`) that consumes the escape pair, plus a not-rectangular
refusal on read and pipe/newline refusals on write. The fixture asks its
question in prose ("normalize... or fail loudly"); the answer is fail loudly.
Suite 6561 → **7686 cases** over 30 fixtures (two synthetic documents — the
corpus is frozen), mutations 28 → **37**, all caught, and grade-neutral over the
same 5674 recorded calls. Full account in FINDINGS F-pipes; the reading and
writing rules are REQUIREMENTS §5.2.

One operational note, because it cost an hour and would cost it again. `mutate.py`
edits the crate's sources in place and restores them in a `finally`, which a
SIGTERM does not run and which two concurrent runs get wrong in a worse way:
each restores the *other* run's mutation as if it were the original. Two
overlapping full runs produced eight bogus `STALE`s and left four mutations
applied to the tree, so the next run's baseline was dirty. **A `STALE` is not a
pass** — the anchor did not match, so nothing was tested — and a dirty baseline
can make a real mutation look caught. Runs now take an exclusive lock
(`crates/.mutate.lock`), SIGTERM is turned into an exception so the restore
fires, and a failed baseline check names any mutation that still looks applied.

There is a second way to lose to the same in-place edit, and it is quieter:
**`git add -A` during a run commits whichever mutation is live.** It happened
twice on the Tier 2c branch. Both commits were doc-only in intent, both swept
in a one-line change to `crates/incise-core/src/ops/section.rs`, and the suite
could not notice, because `mutate.py` restores the source before it reports —
the working tree is clean by the time anyone looks. One of the two committed
`unique: true` into `section_outline`, which is precisely the defect its own
mutation exists to describe. `crates/.mutate.lock` is now in `.gitignore`, which
removes the visible half; the other half is a rule with no automation behind it:
**name paths explicitly when staging while a run is in flight.**

The lesson, stated once so it is not relearned: **a green suite is a claim, not
a result, until it has been shown to go red.** This is the same discipline
`ceiling.py` applies to the benchmark arms (§2), one level down. And its
corollary, from F-pipes: **agreement is not correctness.** Every method above
compares two things; none of them can see what both of them get wrong. Only an
invariant stated against the specification — not against the other
implementation — can.

**Applied, on the next op.** `table-realign` shipped with three property
invariants and six mutations rather than on a first-run-green differential
suite, and each invariant was then made to fail by hand before being trusted
(FINDINGS F-realign). Two of those probes survived all nine invariants, and the
survivors are the interesting result: byte-counted widths still pad every cell
in a column to the same *character* count, so the table is aligned by the tool's
own measure and the invariant is correctly silent; and a naive `\|` split is
invisible to invariants that read the table back with the same mutated splitter.
Both are caught by the differential suite. So the corollary above gets a second
half — **self-consistency is not correctness either.** An invariant compares an
implementation against itself, which is why the two methods are layered rather
than ranked, and why neither is allowed to be the only one guarding an op.

**Applied again, on the op after that.** `table-get` shipped the same way, and
the read op needed invariants of a different shape than the edit ops: an
unfiltered read reports every row unchanged, a filter returns a subsequence
whose rows actually match, and — the one that closes F-pipes' loop from the
other side — the rendered result parses back as a table with the same cells. A
read cannot corrupt a document, so its failure mode is a *false report*, which
is worse than a refusal and much harder to notice because the output still looks
like a table.

The port also turned up a divergence no layer above could see: a header naming
the same column twice, resolved to the last column by the oracle's matching code
and to the first by its writing code. Not a shared assumption (F-pipes) and not
a self-consistency gap (F-realign) but a third thing — **an input the corpus does
not contain**. Both other blindnesses are structural and expensive to fix; this
one is cheap, because the fix is to add the input. One synthetic fixture, 352
cases, and every name-resolving path in the generator now runs against a
repeated header. FINDINGS F-dupcol.

**Applied a third time, on the family after that — and used to predict.** The
list family (`list-add-item`, `list-remove-item`, `list-set-checked`,
`list-lists`) was ported the same way, and the third blindness class was for the
first time worked *forwards*: before writing any list code, the two Python fence
scanners were read side by side looking for an input that would separate them.
They had one — whether a closing fence may carry trailing words — and the
fixture written to expose it turned the suite red on exactly the predicted case
and nothing else (FINDINGS F-fence). Reading found a second defect the same day:
a sibling group mixing `1. x` with `- y` made the oracle do arithmetic on `None`
and report a `TypeError` to the model (F-mixnum). Both were invisible to a green
29k-case suite for the same reason, and both were closed by adding the input.

Two structural consequences, neither of them about lists:

- **Synthetic fixtures are files, not string constants.** They had lived in a
  Python dict inside `difftest.py`; the Rust invariants needed them too, and
  would have taken copies. Two copies of a fixture is the same bet that produced
  F-fence — two scanners, one test holding them together, drift on the one point
  the test could not see. They are now `bench/synthetic/*.md`, read by both
  harnesses, with the per-file rationale in `bench/synthetic/README.md.txt`
  because a fixture cannot carry a header comment. **One copy, two readers.**
- **The invariants' fixture list was widened to include them, and two invariants
  immediately failed.** Both had been green over the 26-file corpus for the same
  reason the differential suite was green about F-fence: no corpus document
  reaches the case. `add_then_delete_is_byte_identical` is not true of a table
  whose `add` is correctly refused, nor of one narrower than its own delimiter;
  it is now `add_then_delete_loses_nothing_and_only_ever_widens`. And
  `no_op_removes_an_item_it_was_not_asked_to_remove` re-resolved the address
  after the edit, which names a *neighbour's* items once removing the last item
  deletes the list. The third blindness class lands on property tests exactly as
  it lands on differential ones, and the fix is the same: give them the input.

Two operational notes from the same stretch, both cheap to prevent and both
expensive to hit:

- **A stale anchor is a silent gap, and it stays silent until the next full
  run.** `mutate.py`'s `rect-off` stopped matching the moment
  `check_rectangular` grew a `read` parameter — the mutation was still in the
  list, still counted, and testing nothing. It would have reported `STALE` at
  minute 29 of a 35-minute run, which is exactly when a `STALE` is most likely
  to be read as noise. The list is now checked up front, in seconds, before any
  mutation is applied: anchors must match exactly once, `after` must differ from
  `before` (a null entry was found doing the rounds, reporting `SURVIVED`), and
  names must be unique.
- **This repository is not under version control, and `rm -rf` is therefore
  final.** *(It is now — a git repository was initialized before the section
  port, with the Tier 2b state as the first commit. The incident below happened
  before that and the lesson outlives it.)* A `mkdir -p` + `cp` + `rm -rf` sequence aimed at a temporary copy
  deleted `crates/incise-core/examples/oracle_cases.rs`, the driver the entire
  differential suite runs through. It was recovered — the compiled binary was
  still on disk and was preserved *first*, to serve as a byte-level oracle, then
  the original `Write` and ten subsequent patches were replayed out of the
  session transcripts. Two facts made the recovery checkable rather than
  hopeful: the preserved binary, and the differential suite itself. The
  reconstruction differed from the preserved binary in two places, and both were
  explained rather than accepted — one was a genuinely missing dispatch arm, the
  other a lib fix the stale binary predated. It then ran 9453/9453 against the
  oracle. **Preserve the artifact before repairing the source**; a reconstruction
  you cannot check is a guess.

**Applied a fourth time, on the section family — and the blindness landed on the
case list instead of the corpus.** The section ops were ported by reading the
oracle function by function rather than by trusting a draft against a green
suite, which is what turned up the family's one real defect: `if children:` in
Python is not `if let Some(c) = children` in Rust, because `or` yields its *last*
operand when every one of them is falsy, so `{"sections": []}` reaches the op as
`[]` and not as absent. Every generated case either found a truthy operand or
ended on an absent one, so the suite would have agreed with itself.

That is the third blindness class again — an input nothing has — but one level
in from where it kept landing before. F-dupcol and F-fence were missing
*documents*; this was a missing *argument shape*, in a case list that is
hand-written precisely because the corpus cannot reach the validation layer. The
distinction matters operationally: a corpus gap is closed with a synthetic
fixture, a case-list gap with four more strings, and only the first has a
standing rule (`bench/synthetic/`) telling you where to put it. The second now
has this paragraph.

**The mutation run then measured that ratio, and it is 4 to 1 the other way.**
Six of the 58 section mutations survived a full run. One was a corpus gap
(`section-pred-order`: no fixture had a path that was also a longer path's
tail, so the resolver's `exact`-before-`suffix` ordering was unobservable —
now `bench/synthetic/section-repeats.md`). Three were case-list gaps. One was
a case-list gap of a subtler kind: the argument shape was present but never
paired with the `heading` needed to reach the code that reads it. And one was
an **equivalent mutant**, which is the fourth answer and needs its own rule:
when no input can distinguish a mutation, delete it and say why, because the
alternative — leaving it in the survivor list forever — teaches everyone who
reads the output that a survivor is normal.

The most useful of the six was `section-inert-case`. The branch it mutates
answers "that heading is inside a code fence" instead of "not found", it is the
concrete implementation of §5.3's rule about refusals, and it had run **zero
times** in 63584 cases. The corpus held the input; nothing queried it. Read
survivors as evidence about the harness first: the cheapest thing a mutation
run tells you is which branches are never entered.

The family also has a failure mode neither earlier one could have: a section has
**two ends** — its own prose and its subtree — and every op picks one. Both are
correct answers to different questions, so a swap produces a plausible edit in
the wrong place rather than a mangled line, and two implementations that swap
them together agree. Six mutations do nothing but swap the two, and four of the
seven new invariants assert on the bytes *outside* the addressed section, which
is where the mistake shows. FINDINGS Tier 2c.

Current totals: **84267 differential cases** over **44 fixtures** (18
synthetic), **180 mutations** and **29 invariants**. Tier 2c proper reached
66127 / 40 / 150 / 26, the `describe_change` addendum took it to 77580 / 43 /
172 / 29, F-nearmatch retired four mutations whose code it deleted, added
one stronger replacement, and added the 225 cases that tell two near-match
cutoffs apart (77805 / 43 / 169 / 29), and F-address added eleven mutations,
`section-ordinal-mix.md`, and the section, list and `position` case families.
The full run at 169 caught 169/169, no survivors and no `STALE`.
The 5674-call
grade-neutrality replay was not re-run for Tier 2c and did not need to be: that
tier did not move the oracle at all — `incise_ops.py` and the corpus are
byte-identical to their Tier 2b state, so every recorded call takes the same
path it took then. The addendum did not move it either. **F-address did**, and
is the first change since Tier 2b to move it: 156 of 6678 calls, enumerated
element-wise, 216 differing vector elements, every one a refusal string and none
a document.

The clean sweep is worth exactly one sentence and the tail underneath it is
worth more: **nine of the 169 are caught by five cases or fewer, two of them by
one**. Watch one mutation's whole history before trusting a tail number.
`near-cutoff` was caught by one case; `long-cells.md` took it to thirty-one
without being aimed at it; F-nearmatch removed the heuristic that had been
holding those probes near the cutoff and it fell back to one; a probe derived
from `2f / (1 + f)` rather than from luck took it to seventy-six. The tail
shortens and lengthens for reasons that are about the corpus, not about the
mutations in it. A mutation caught once is a mutation one fixture edit away from
surviving, and a survivor is how a defect stops being reported.
Sort a run's output by mismatch count and read the bottom; the total only ever
says "no worse than last time".

A cost note that goes with those totals: a full `mutate.py` run was eight hours
at these counts, and is now **~35 minutes**. 93% of that eight hours was one
serial Python loop recomputing an answer that had not changed — the oracle's,
which every mutation leaves alone because every mutation is on the Rust side.
`difftest.py` now runs that loop across cores (`-j`) and caches its result under
a content key (`--expected`), taking a single run from 2 m 43 s to 37 s, or to
8 s on a cache hit. The suite is back to being runnable per-commit. Per-family
(`mutate.py -k section-`) is still the right move while iterating; `-k` takes a
comma-separated list, which is what re-running a run's survivors wants: six
unrelated names over one baseline rather than six. FINDINGS F-harness.

One of the 93 is caught by a *panic* rather than a mismatch count, and that is
now its own verdict. `mutate.py` had two ways to end without a comparison —
"did not compile" and "the port crashed partway" — and reported both as
`NOBUILD`, whose docstring says a mutation that does not build proves nothing
about the corpus. That reading is right for a build failure and wrong for a
crash: a panic is evidence the corpus *reaches* the mutated line, and a
differential run that dies is a run that does not pass. `crashed` counts as
caught and says, in its own name, that it cannot tell you which case saw the
difference.

## 9. llama.cpp integration

- **Endpoint:** OpenAI-compatible `POST /v1/chat/completions`. Required CLI
  argument; no default, no autodiscovery, no starting a server.
- **Model identity** is read from `/props` at run start and stamped into
  `run.json` rather than hardcoded, so a run always records the model that
  actually served it.
- **`cache_prompt: true`** — the system prompt and fixture are identical across
  the 10 trials of a task. Prompt caching turns 10 prefills into 1 for most of
  the context and is the single largest runtime saving available. Order trials
  task-major to exploit it.
- **Tool calling (Arm B):** use the native `tools` parameter, enabled by
  `--jinja`. Run Arm B in two variants:
  - *unconstrained* — measures real-world reliability including malformed JSON;
  - *grammar-constrained* (GBNF or `json_schema`) — forces syntactically valid
    calls, isolating "picked the wrong op or args" from "emitted bad JSON."

  Reporting only the constrained variant would overstate how well tool calling
  works in practice; reporting only the unconstrained one confounds two
  different failure modes. Both are cheap.
- **`n_predict` cap** sized per arm. Truncation is graded `malformed`, not
  discarded — running out of output budget mid-table is a real failure mode.
- **Token counts** come from the response `usage` fields. The offline dry-run
  estimates with a local tokenizer instead, so it needs no server contact.

## 10. Runtime budget

No longer an estimate. The pilot (§2.3) measured **92 s and 3070 completion
tokens for one trivial edit**, at 33.3 tok/s. Reasoning is ~97% of the tokens,
so trial cost is roughly constant regardless of task size — every trial spends
its ~3000-token reasoning budget whether the file is 576 bytes or 30 KB.

At ~92 s/trial the matrix as originally scoped is **~33 hours**:

| Run | Trials | At 92 s/trial |
| --- | ------ | ------------- |
| Smoke (12 × 3, A1) | 36 | 55 min |
| Repeat-penalty sweep (§1.1) | 80 | 2.0 h |
| Full A1 (40 × 10) | 400 | 10.2 h |
| Full B, both variants (40 × 10 × 2) | 800 | 20.4 h |
| A2 whole-file | — | cannot complete on long fixtures (§1.6) |

That is too much for a machine you also use. Four levers, in the order I would
pull them:

1. **Add a reasoning-budget cell — do this first.** Reasoning is 97% of the
   cost. A cell at `--reasoning-budget 0` (or a low cap) on the smoke set
   answers whether reasoning buys any accuracy on this task class. If it does
   not, every subsequent run gets ~30× cheaper and the whole matrix becomes
   affordable. If it does, that is itself a headline finding about what small
   models need in order to edit markdown. Either outcome is worth an hour.
2. **N = 5, not 10,** for most families; keep N = 10 for the two that carry
   headline claims (tables, uniqueness traps). Halves the matrix. Widens the
   confidence intervals, which §7 already requires reporting honestly.
3. **Trim the full set to ~30 tasks**, keeping full coverage of tables,
   uniqueness traps, and hazards, and sampling the rest.
4. **Run Arm B constrained-only** if time is short, and label the omission.

Prompt caching turns out to be nearly worthless here, contrary to §9: the pilot
prefill was 518 tokens against 3070 generated. Caching only helps the handful of
`api-reference.md` tasks with ~7.5k prompts. Task-major ordering is still free,
so keep it, but do not count on it for savings.

Whatever coverage gets dropped is logged in the report. A silently truncated
matrix reads as full coverage when it is not.

## 11. Integrity notes

Recorded here because the failure mode is subtle and we are grading our own
project:

1. Arm A gets the strongest reasonable prompt, iterated on the smoke set until
   it stops improving. Under-tuning the baseline is the easiest way to
   manufacture a favorable result.
2. Instructions never use incise's op vocabulary (§3).
3. Goldens are never model-generated (§3.1).
4. Prompt-template SHAs are recorded, and a prompt change invalidates
   comparisons against earlier runs. No mixing runs across template versions.
5. A negative result is a real result. If Arm A's `collateral` rate is low once
   the repeat penalty is fixed, that belongs in the report in the same size
   type as a favorable one.

## 12. Phases

**Phase 0 — offline, zero model contact.** Harness skeleton, task YAML, prompt
templates, grader, `--dry-run` that renders every prompt to disk and reports
token estimates and a projected runtime. This validates the entire pipeline
without sending a single request, and can be built while the server is busy.

**Phase 1 — goldens.** Hand-author and review ~40 golden files. This is the
labor-intensive step and it also front-loads the §11 open questions: writing the
golden for the ragged-cell-count task forces that decision.

**Phase 2 — baseline.** In order, cheapest and most plan-changing first:
(a) the **reasoning-budget cell** (§10 lever 1) — an hour that may make
everything after it 30× cheaper; (b) the **repeat-penalty sweep** (§1.1), which
may reframe the project; (c) the full Arm A1 run. Output: the number
`REQUIREMENTS.md` §12.1 asks for.

**Phase 3 — Arm B against the mock.** *Done — `FINDINGS.md` B1–B7.* Ran both
naming schemes against identical tasks and seeds. The first pass cost **four
minutes of GPU time**, not the few hours budgeted, and returned four things the
design needed: the op vocabulary works (88.3% first call, 98.3% within two),
errors are recoverable (13/13), the model invents selector values it cannot see,
and the named-`values` shape is worse than direct editing on positional
instructions. Two of those were unanticipated, which is the argument for having
run it before writing Rust rather than after.

Three further passes (B6, B7) took the schema from 88.3% to **60/60** for
another ~120 trials of GPU time. The plan did not anticipate needing them, and
the reason is worth recording: each pass fixed a failure the *previous* pass
made visible, and none of the three fixes would have been guessed from the
first result. Budget for iteration on a tool schema, not a single A/B.

Op naming (§12.7) did **not** resolve on correctness — p = 0.167. It resolves on
failure mode instead, which the plan did not anticipate measuring. The same
happened again at B7: the two candidate fixes were separated by 3/60, and the
losing one was *trial-for-trial identical* to no change at all. Paired seeds,
not aggregate rates, are what made that legible.

**Phase 3b — the second op family (lists).** *Done — `FINDINGS.md` L1–L6, 600
trials.* Run because B7's own caveat argued for it: 60/60 is not "always", it is
"no failure remains *that this benchmark can see*", and the way to test that is
a family the schema was not tuned on. It cost about a day and returned the two
most useful results in the project.

The plan's structure held — ceiling first, paired seeds, both arms — and its
*conclusions* did not. Read the order of operations as the transferable part:

1. **Build the parser and the reference op before designing any schema.**
   `mdlist.py` + `incise_ops.py` + the corpus-wide invariant tests came first.
   The three-numbering-styles finding fell out of writing the reference, not out
   of any model trial, and it is the single hardest constraint on the Rust.
2. **Run `ceiling.py`.** 50/50 across five schemes, no GPU time spent.
3. **Run the naive schema before the tuned one.** `list_naive` scored 80/100.
   Had the B7-derived schema been adopted on the strength of the table result
   and run alone at 61/100, the family would have read as "lists are hard for
   the model" instead of "that prose hurts here."
4. **Diagnose failures by dumping the actual arguments, not by theorizing.**
   `list_f`'s 19-point loss looked like an addressing failure and was not: the
   address was supplied correctly every time, and the model was writing the
   *payload* into the selector field. That dump is what produced `list_g`.
5. **Run the 2×2 before claiming a main effect.** `list_i` exists only to check
   whether the prose and the parameter name are separable. They are not — the
   factors interact and neither has a main effect on its own.

Budget note: all five schemes together were a small fraction of the day. Arm B
is cheap (§13.1). The expensive part is the reference implementation and its
goldens — and that work is not benchmark overhead, it is the Rust core's oracle.

**Phase 4 — after incise v1.** Arm C end-to-end **done** (`bench/armc.py`, 410
trials, ceiling 31/31): on every trial where the model named a file the binary
and the reference agreed, and the only class that moved is a missing `path`,
which Arm B could not see. Full re-run and final report still outstanding.

Two families are enough to start the Rust. A third (sections, or frontmatter)
is the alternative to starting it, not a prerequisite — see §13.

**The build — the op set is complete, after Tier 2c.** `crates/incise-core` is a
zero-dependency crate carrying the scanner, the heading/table/list parsers, all **thirteen** ops of the
three families (tables including `table-realign` and `table-get`, lists,
sections), the JSON argument layer, `describe_change`, and ports of
`difflib.get_close_matches`, `get_opcodes` and
the two Python string forms reachable inside refusal messages. It agrees with
`incise_ops.py` byte-for-byte on 84267 cases including every refusal path
(§8.1), and `cargo test` carries §11's structural invariants over the whole
corpus and `bench/synthetic/`.

`OPS` now matches the oracle's thirteen names in the oracle's order, which was
the last documented divergence in the dispatch apart from the table family's
`row` alias. `describe_change` is in the crate but deliberately **not** in
`OPS`: it is not an op — S14 adopted it as the *result* shape — and it returns
text about a document rather than a document, which is the same reason
`table-get` sits off `apply_op`. It was originally left to the front end on the
grounds that it also needed `difflib.SequenceMatcher.get_opcodes`; that was a
cost rather than a reason, and parking it outside the crate meant parking it
outside `difftest.py`, `mutate.py` and `invariants.rs`. Completing `similar.rs`
to build it found a real defect in the port — FINDINGS F-extend. The front end
has since been built — `crates/incise-cli` and `plugins/hermes/`, FINDINGS
F-front — and Arm C has since run over it, on the same tasks and seeds as Arm
B, executed against real files: the core and the oracle agreed on every trial
where the model named a file, and the one class that moved belongs to the front
end rather than the crate.

The order was chosen by measured harm (REQUIREMENTS §11), not by the shape of
the op list: the three table operations the model actually failed, plus
`list_tables`, because it is the prompt. Sections were measured last and were
built last, even though S13–S15 are the most recent work.

One deliberate departure from the oracle: the Python side has three copies of
the fence-scanning logic (`mdtable`, `mdlist`, `mdsection`), held together by
`test_fence_scanners_agree`. That duplication is historical. The Rust has one
scanner, and the test that existed to stop the copies drifting has nothing to
guard on this side.

**Phase 3c — the third op family (sections).** *Done, both arms, a fix arm, a
multi-turn arm, a replay arm and a rename arm. `mdsection.py`, six reference
ops, fifteen tasks with whole-document goldens, eleven corpus-wide invariants
(32 tests, 241 assertions, green), ceiling 45/45 across the three S13 schemes
and again across the three S15 schemes, 100 Arm A trials and 330 Arm B trials
in three schemes, plus 77 retry turns, 510 multi-turn trials, 1179 replays of
turn 2 onward at three result shapes, and 600 trials across three
single-factor renames of the colliding `path` argument.*

Executed under Phase 3b's order of operations, and step 1 paid for itself
before a single token was spent. The insert↔delete round trip — insert a probe
section at every `before`/`after`/`last-child` position of every section in the
corpus, delete it, demand byte-identity — is 755 probes, and its first run
failed 113 of them across three distinct defects that hand-smoke-testing the
six ops had not surfaced:

- **The document's final newline was deleted** whenever the insertion point was
  the end of the file (100 failures — every last-section-and-its-ancestors chain
  in 26 files). `split("\n")` represents a trailing newline as a final empty
  element; skipping trailing blanks to find the insertion point consumed it.
  One byte, invisible in a terminal, `collateral:formatting` by §5.1.
- **An existing separator was rewritten rather than stepped over.** Insert put
  its gap *before* the new block, overwriting whatever blank lines were already
  there; `whitespace.md` separates two of its sections with two blank lines and
  `mixed-endings.md` with a CRLF one, so both lost a byte. The deeper problem
  is that it did not compose: `section-delete` takes a section's *trailing*
  gap, so insert-then-delete left a blank line behind. Fixed by putting the gap
  on the far side of the block, which makes the two ops inverses and stops
  rewriting bytes nobody asked to change.
- **Insert into an unclosed fence succeeded.** `hazards/code-fences.md` ends
  inside one, so by CommonMark the anchor's last line is code; the op wrote
  `## Heading` there, changed the file, reported success, and created no
  section. Now `_verify_heading` re-parses the output and refuses if the
  heading it just wrote is not a heading. This is §12's `wrong` vs `op_error`
  distinction, and `op_error` is the loud one.

The first two are the same class of bug the table and list families were built
to avoid and did not have, because neither family's edits touch the boundary
between two constructs — a row goes inside a table, a list item inside a list.
A section's edits are *all* boundary. Note for the Rust: insert and delete must
be tested as inverses, not each against a golden.

A fourth defect was found afterwards, by reading the delete op's output on a
real file rather than by any invariant:

- **`section-delete` on the oldest release in `changelog.md` deleted all six
  link reference definitions** at the bottom of the file, including the ones
  belonging to releases that were still there. By CommonMark this is correct —
  nothing follows the block, so it is inside the last section, `[1.2.0] >
  Security` — and it is corruption by any reading a user would recognise. That
  pairing (structurally defensible, silently destructive) is the thing this
  project exists to eliminate, so the reference now treats a trailing
  link-reference block as document-level: `mdsection._footer_start` caps every
  section's span. The rule is kept narrow on purpose — the run must be at the
  very end, every line in it a link reference definition, and a blank line must
  separate it from what precedes — because inventing markdown semantics is how
  a tool starts being wrong in ways nobody predicted. `test_link_reference_footer`
  pins both halves: that it fires on `changelog.md`, and that it fires on
  *nothing else* in the corpus. Orphaned refs are left alone; the op deletes
  what it was asked to delete and does not guess at cleanup. Goldens regenerate
  byte-identically and the ceiling is unmoved, so **no measured result moves**.

Building the section parser also exposed two latent defects in the **existing**
families, both from the same cause — nobody had told either parser that
frontmatter is not content:

- `find_lists` read YAML block sequences as bullet lists, so
  `render_list_summary` offered the model two "lists" in `frontmatter/rich.md`
  that were the document's metadata.
- `_headings` read that file's YAML comment as an H1.

`frontmatter_span` now lives in `mdlist.py` (the leaf layer, which imports
nothing) and both parsers consult it. Blast radius was checked before the fix,
not after: no task or golden uses `rich.md`, exactly two corpus files change,
and both changes are strict improvements. **No measured result moves.** The
corpus list count goes 51 → 49.

**Step 3 — the arm, run naive first.** Both schemes measured, 100 trials each:
`section_naive` 58/100, `section_p` 63/100, McNemar p = 0.33. Full results in
`FINDINGS.md` S1–S6. Three things are worth recording here as *method*, not
result:

- **Running the naive schema first was again the right call, for the opposite
  reason this time.** With lists it prevented adopting a prose change that cost
  19 points. Here it established that the tuned scheme's +5 is not significant,
  so the family's headline is "sections are hard", not "this schema is good".
  Had only `section_p` been run, 63% would have been reported as a schema
  result.
- **The run found two grader defects the ceiling could not** (S4). A ceiling
  check walks only the path a *correct* call takes, so the whole failure ladder
  below `correct` is unexercised by it. Both defects were in that ladder. The
  transferable rule: a ceiling of 100% licenses the arm, it does not validate
  the grader. Adversarial cases for each rung need their own tests, and the
  section grader now has them.
- **Two tasks measure less than they look like they do**, found by reading the
  calls rather than the scores: `append-hotfix-note` cannot tell `append` from
  `replace-body` because its target has no body, and `insert-release-at-top`
  needs markdown inside `body` and so tests S6 instead of insertion. Both are
  written up as caveats rather than quietly fixed, because regenerating a task
  after seeing the trials is how a task set drifts toward flattering itself.

**Step 4 — the fix arm, and the counterfactual that cost nothing.** S1–S6 named
three design problems; two of them (S2, S3) are executor-side, and grading is a
separate pass over raw trials. So the fix could be measured on the 200 trials
already collected, by re-executing byte-identical tool calls under a guarded
executor. Method notes, in order of how much they generalize:

- **Fix the executor first, re-grade, and only then spend GPU time.** The
  re-grade took seconds and answered the question the fix arm was for —
  destructive 6→1 and 4→1 at a cost of zero correct answers (S8). It also
  caught a defect *in the guard*: the first version refused a `heading` argument
  that merely echoed the section being addressed, turning six correct trials
  into `op_error`. Found in a re-grade it is a two-line exception; found in the
  fix arm it would have read as the model getting worse, at 130 trials of GPU
  time.
- **Freeze the schemas that produced the published numbers.** `section_naive`
  and `section_p` were left exactly as run and the guard was put behind a flag,
  with the fix arm as a new scheme (`section_g`). S1–S6 stay reproducible.
- **A guard can make the right answer inexpressible, and that must not read as a
  model failure.** `replace-install-preamble` went 10/10 → 0/10 in both old
  schemes, not because the model got worse but because neither vocabulary has an
  `overwrite` field to acknowledge the guard with. `ceiling.py` now *reports*
  inexpressibility per task instead of aborting, so this is a line in a table
  rather than a stack trace.
- **The Arm A run found a third grader defect** (S4.3), the mirror image of the
  second: whitespace damage filed as content damage. Two families of grader bug,
  both in the failure ladder, both invisible to the ceiling. The rule from
  Step 3 held a second time.
- **Report the new failure modes the fix introduces.** `section_g` is 80%
  correct, and it also made the model reach for `ordinal` twice as often, twelve
  times wrongly (S10). Recorded as the next thing to fix rather than folded into
  the headline — each executor change is measured on its own, or a net gain
  hides a regression.

**Step 5 — measure the obvious fix before writing it, and test the premise the
last two steps stood on.** Two items came off the Open list, both cheap because
Step 4 had already established that an executor change is measurable against
raw trials. Method notes:

- **Measure the fix you are confident about, not just the one you doubt.** S10's
  spurious `ordinal` looked like a free win: refuse nothing when the path
  already resolves uniquely. Implemented as a throwaway monkeypatch and
  re-graded, it bought 3 correct answers for **6 destroyed sections** (S11),
  because the ordinal is the only evidence that a truncated path is wrong. The
  fix was never written. The general form: *when two arguments contradict each
  other, dropping the one that fails to resolve keeps the one that resolves to
  the wrong thing.*
- **A monkeypatch is the right resolution for a counterfactual.** It answered
  the question without touching `incise_ops.py`, without a new scheme, and
  without a schema change that would need freezing. Only fixes that survive
  measurement get committed.
- **Test the imported premise in the family that could break it.** S8 and S9
  both argue that converting silent failure to `op_error` is a win *because*
  `op_error` is recoverable — a claim measured in B3 on tables, where the
  executor absorbs mistakes. Re-running it on sections (S12): 75% for the fix
  arm, 89.2% correct with one retry turn. It held, but it was the load-bearing
  assumption under two published findings and had never been checked where it
  was weakest.
- **Read the retry failures, not just the recovery rate.** The 15 trials still
  erroring after the retry turn are two mechanisms, and both are actionable in a
  way the rate is not:
  a `path`/`section` name collision that reproduces *identically* on the second
  turn, and an error message that names the computable argument instead of the
  wrong one — which walked one trial into the only destructive retry in the
  project. A message defect and a naming defect, neither visible in "75%".

**Step 6 — the multi-turn harness, and the two things it broke.** S6 had been
open since the first section arm with a stated blocker: "Arm B cannot currently
measure this — it grades one call per task." Closing it meant a real change to
the harness (`armb.py --turns N`: the model sees each call's result and may call
again) and two new tasks that legitimately need two and three calls. 450 trials
across three schemes, plus 60 re-runs. Result in `FINDINGS.md` S13. Method notes:

- **Grade the document, not the call count.** A task that needs three calls is
  graded exactly like a task that needs one: apply every call in order to one
  working document, then compare against the golden. `--turns 1` reproduces the
  old behaviour byte-for-byte, so 1720 existing trials stayed valid and
  `ceiling.py` learned to express a whole sequence as one synthetic trial rather
  than gaining a second grading path.
- **A refused call in the middle of a sequence is not the sequence's outcome.**
  Errors are collected and the run continues, because the op contract is that a
  refused call leaves the document untouched. If the final document is `wrong`
  *and* the model was told about an error, the trial is re-filed as `op_error` —
  it is a loud failure. `destructive` and `collateral:*` are **never**
  downgraded that way: an error message on call 3 does not give back bytes lost
  on call 1.
- **Adding a turn is a change to the executor's threat model, not just to the
  harness.** Every guard in §6.3 was justified on single-turn evidence. S13's
  four destructive escalations all happen on a turn the model did not need, and
  three of them go through a verb the guards permit *because the model
  acknowledged it* — `overwrite: true` set by a model whose picture of the
  document is one edit stale. A guard that reads consent from an argument cannot
  tell fresh consent from stale.
- **A single-turn harness cannot show you a broken task.** Two tasks had a wrong
  answer key for an entire arm, and both surfaced within minutes of the model
  being able to take a second turn — because only then did it get far enough to
  disagree. `insert-troubleshooting` was contradicted 30 times out of 30. The
  transferable rule is uncomfortable: *a task nobody ever passes is evidence
  about the task, and the cheapest way to get that evidence is to let the model
  finish.*
- **Distinguish "the golden moved" from "the golden became reachable."** The two
  fixes look alike and are not. `insert-release-at-top`'s golden is byte-identical
  — only the instruction stopped paraphrasing text a whole-document golden pins
  exactly. `insert-troubleshooting`'s golden changed by one heading level, which
  is the answer key yielding to the trials, and that is written up as its own
  measurement caveat rather than as a task note. The first kind is free; the
  second kind should always cost something to do.
- **Split the aggregate before believing it.** The three schemes land within 3
  points of each other on 150 trials — read as a total, S6 does not matter.
  Split by whether the task can use the new field and it is 12 → 26 out of 30 on
  the three that can, and −12 on the twelve that cannot. Same shape as B3's
  narrow-vs-broad result: the aggregate was the least informative view of it.
- **Test the mechanism you are about to write down.** The first explanation for
  the escalations was "an outline cannot confirm a body edit, so the model
  retries." Checkable in one query, and false: outline-*invisible* ops
  (`append`, `replace-body`) are retried 2–5% of the time and outline-*visible*
  ones up to 64%. The real variable was whether the task needed more calls. The
  finding survived; the explanation did not.

**Step 7 — replaying one turn instead of re-running the arm.** S13's redundant
turn had a fix and no way to test it that was worth the GPU: the behaviour
appears in ~3% of trials, so a fresh arm spends nearly all of its sampling
re-deriving first calls that were never in question, and the two arms differ in
those first calls by chance as much as by treatment. `armb.py --replay` fixes
the prefix instead. 1179 replays, three result shapes, 393 prefixes. Result in
`FINDINGS.md` S14. Method notes:

- **The unit of reuse is the prefix, not the trial.** S8 established that
  grading is a separate pass, so an executor change is measurable against every
  trial ever run. S14 is the same move one level up: the messages before the
  turn under test are also reusable, so a change to what a tool call *returns*
  costs only the turns after it. The comparison becomes paired by construction
   — same document, same first call, same seed, one string different — which
  is McNemar rather than Fisher and needs a fraction of the samples.
- **Run the unchanged condition as a replication check.** The `outline` arm is
  the behaviour S13 already measured, re-sampled from the same prefixes: 9
  continuations against the original 11. That is the only evidence that the
  replay is sampling the state it claims to be, and it is worth a third of the
  run. Without it a null result would be unreadable — a broken prefix and a
  working fix look identical.
- **Include the arm you expect to be redundant.** `both` — the delta *and* the
  outline — was run because "state what changed" and "stop showing the
  document" sound like one requirement. They measure as two: `delta` is
  0/300 and `both` is 6/300, statistically the same as changing nothing. The
  requirement S13 wrote down would have been implemented as `both` by anyone
  reading it, and would have bought nothing.
- **A fix that suppresses the behaviour is not the same as a fix that suppresses
  the *wrong* behaviour.** Two controls, both necessary: the three multi-call
  tasks, where a second call is required and must survive (63 → 61 of 83, p =
  0.5), and the ten prefixes whose first call applied cleanly but was wrong,
  where continuing is correct. Under `delta` the model continues 0/300 when it
  should not and 3/10 when it should. Reporting only the first number would
  have made a muzzle look like a cure.
- **Report both definitions when the population is a judgement call.** S13
  defined "already succeeded" as "applied without an error", which an executor
  can see; S14's effect is significant on "already produced the right document"
  (p = 0.0078) and not on the looser one (p = 0.11). Narrowing after seeing the
  data is choosing the flattering definition. Both go in the table, the
  original stays primary, and the gap between them is itself the finding.
- **Derive the message from the artifacts, not from the call.** `describe_change`
  diffs the two documents. Echoing the arguments back would be cheaper and
  would fail exactly where it matters — a model wondering whether its call
  landed learns nothing from being told what it asked for — and it could report
  a change that did not happen, which is the one output worse than silence.
  `test_incise_ops.py::test_describe_change` asserts that every heading the
  message claims to have added is in the resulting document.
- **The harness default is now the shipping behaviour.** `--result-shape`
  defaults to `delta`; every arm through S13 ran at `outline`, so reproducing
  any of them requires passing `--result-shape outline` explicitly. A default
  that reproduces old numbers is the wrong default once the old behaviour is
  known to be harmful — but the flip has to be written down in both directions,
  because it silently changes what a re-run measures.

**Step 8 — sizing an arm against a base rate you have actually read.** S12
named the colliding `path` argument as its largest unrecovered bucket, "6 of
15". S15 set out to fix it, ran 150 control trials, found the misfiling twice,
and measured p = 0.5. The arm was not wrong; it was aimed at the wrong
denominator. Result in `FINDINGS.md` S15. Method notes:

- **Read your own prior number before you size the arm.** "6 of 15" was six of
  the fifteen *unrecovered failures*, not six of 150 trials. The true base rate
  is ~1.3% pooled, so 150 trials buys about two events and no power at all. The
  fix cost nothing but attention: applying the detector to all 4137 section
  trials ever run — free, because S8 made grading a separate pass — showed
  every hit landing on one task. A rate quoted as a fraction of failures and a
  rate quoted as a fraction of trials look identical in prose and differ by
  more than an order of magnitude.
- **Spend the sampling where the behaviour lives.** ~20% on `promote-api`, ~0%
  on the other fourteen tasks. 50 extra trials per arm on that one task moved
  the same question from p = 0.5 to p = 0.0039 for less GPU than the balanced
  arm had already spent. This is S14's lesson again in a different costume:
  concentrate on the cell under test, not on the surface around it.
- **Then stratify, because the arms are no longer balanced.** Once one task has
  60 trials and the rest have 10, any pooled table is that task wearing the
  family's name. The analysis reports the balanced 15-task prefix, the
  single-call subset, and the provoking task separately, and never sums them.
  A concentrated arm and an honest headline are compatible only if the
  concentration is visible in the table.
- **Run both single-factor arms, not just the one you would ship.** Renaming
  the file argument and renaming the address are two different hypotheses about
  *which side* the model is confused about. Both were run; both scored 60/60
  with the same discordant pairs. That is the finding — the collision itself is
  the defect, so either disambiguation buys it — and one arm could not have
  produced it. The adoption decision then falls to cost, and `section.heading`
  wins because `path` already means the file on every table and list tool whose
  numbers are frozen.
- **Hold every other string byte-identical.** §1.3 result 8 says names outweigh
  prose, which is only usable if nothing else moves. The three schemes were
  diffed to confirm each differs by exactly one property name plus its
  `required` entry, at the same position, with every description unchanged. The
  ceiling script's inverse mapping had to learn the nested rename separately
  from the top-level one, or `heading` at either depth would have satisfied the
  other and hidden a schema that could not express the correct call.
- **An errored row is not a completed row.** The smoke test hit a transient HTTP
  500 and exposed a real bias: `run()`'s resume treated a row with an `error`
  as done, so a lost trial would permanently thin one arm of a paired design —
  precisely the arm that happened to be running when the server hiccuped.
  Fixed to retry error rows, which means a key can now have two rows, which
  means every reader must take the last one. `s15_analyse.load()` does; anyone
  writing a new analysis script has to.

## 13. Decisions needed before Phase 2

Resolved from the process table and your answers:

- **Sampling condition** — hermes does not override, so the server's launch
  flags are the condition under test. The baseline sends no sampling params.
- **Edit format** — hermes's `patch` tool, replace-only variant, schema
  embedded verbatim (§2.1). Not a prose SEARCH/REPLACE dialect.
- **GPU access** — free when you run the tests; harness is serial, resumable,
  and time-boxed regardless.

- **Alignment damage is corruption** — ruled in §5.1, on the ratchet argument.
  Graded `collateral:formatting`, always reported separately from
  `collateral:content` so the headline number is not carried by padding errors.

Still open:

1. ~~**How much runtime are you willing to spend?**~~ *Answered by measurement.*
   The §10 estimate of ~33 hours was wrong by an order of magnitude for Arm B.
   933 Arm B trials have now been run (433 tables + 500 lists) and the arm is
   cheap: B1's first pass cost **four minutes**, because Arm B carries no
   document in context and no reasoning trace to pay for. The levers were never
   needed there. Arm A is the expensive arm (~92 s/trial, 280 trials so far) and
   it is the one to budget. Restate §10 in those terms before the next run.
2. ~~**Should Arm A get a system prompt closer to hermes's?**~~ *Closed as
   won't-do, 2026-09-06 — and the caveat stands permanently as a result.* The
   §2.4 validation would require running real hermes once on a scratch corpus
   copy, which injects SOUL.md, memories and the 61 KB skills prompt; the
   operator's standing preference is not to, and that preference is upheld.

   **So this is the honest statement of the limitation, and it belongs in every
   report of the Arm A vs Arm B gap:** Arm A measures *hermes-style* editing —
   hermes's `patch` schema and description strings verbatim (§2.1), a minimal
   generic system prompt — not hermes exactly. Anything in hermes's real system
   prompt that helps the model edit markdown is **not** credited to the
   baseline, so the measured gap is an **upper bound** on incise's advantage.
   The size of that overstatement is unknown and will remain unknown. Nothing
   downstream may describe Arm A as "the hermes baseline"; it is "a replication
   of hermes's edit path."
3. **Is the §4.8 raggedness-lookup cell worth 30 minutes?** *Still open.*
   Optional; it substantiates a rationale currently taken on faith.
4. ~~**A third op family, or start the Rust?**~~ *Decided 2026-09-06:
   **sections next**, before the Rust.* The argument that won: two families were
   measured and they disagreed with each other, so a third is more likely to
   return something unguessable than to confirm what is already known — and the
   cost of learning it after the core crate exists is a rewrite rather than a
   day. Recorded against the alternative, which was to freeze the list schema at
   94/100 and start implementing; that remains the fallback if sections returns
   nothing new.

   Two consequences follow and are not optional:

   - **The `after` question (`REQUIREMENTS.md` §12.10) is deferred, not
     dropped.** It is still the last known silent-failure source in the best
     list schema, and the list ops must not be frozen until it is measured.
   - **Sections must not be scoped to what tables and lists made us expect.**
     The value of a third family is entirely in what it contradicts, so the
     tasks are designed from the corpus fixtures and §6.3, not by analogy —
     see §4.2.
