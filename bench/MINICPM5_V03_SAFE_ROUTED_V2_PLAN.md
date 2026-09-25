# MiniCPM5 v0.3 safe-routed v2 transfer plan

Recorded 2026-09-25 after the immutable v1 smoke was merged at `e92e470` and
before implementing this treatment or sampling any v2 outcome. Tracking issue:
https://github.com/pdalinis/incise/issues/32.

## Question

Can four strict, model-agnostic host-owned routes eliminate every unsafe or
non-canonical MiniCPM outcome from the v1 48-task smoke without regressing the
released Gemma and Ornith profiles?

The v1 treatment improved MiniCPM from 17/48 to 41/48, but the gate stopped on
four harmful outcomes, one multiple-mutation fallback, and routed calls whose
model-supplied arguments were not canonical. Three additional tasks ended in
safe loud refusals. Even perfect repair of the targeted residue therefore has
an immediate expected ceiling near 45/48; v2 is a transfer and safety gate, not
the 480-pair adoption run.

## Treatment

Change only the shared Pi `safe-routed` layer:

1. Parse both the target and exact quoted replacement body for explicit
   `Replace the text/body/content under X with "Y"` requests. Expose the
   existing section replacement tool with an empty schema and supply both
   values from the host.
2. Recognize the two exact list-at-end phrasings observed in the frozen tasks,
   including the explicit loose-list qualifier. Inspect lists and items,
   resolve a unique heading/ordinal, and keep the existing host-owned empty
   mutation schema.
3. Recognize the two exact named table-row request families in the frozen
   population: named Component/Status/Owner values and an explicit ordered
   `values ...` list. Inspect tables, require a unique address and compatible
   columns, then expose a new empty-schema `table_add_row_target` whose row and
   address are host-owned and hash-guarded.
4. Replace model-owned key/value selection for the five already recognized
   typed frontmatter intents with strict semantic parsing plus structured-read
   validation. Existing keys, types, old values when stated, and the named
   author entry must resolve uniquely. Retain the existing typed tool names,
   but expose empty schemas and host-own the canonical key and typed value.

These routes must decline negated, incomplete, ambiguous, duplicate, wrong-type,
or near-match requests. Core operations, refusal text, standard schemas,
`standard`, Gemma/Ornith family detection, and the one-success latch do not
change. MiniCPM remains mapped to `standard` in `auto`.

## Deterministic gate

Before live sampling:

- add positive parser and resolver tests for every new shape;
- add near-match and negation tests demonstrating conservative fallback;
- verify dynamic provider surfaces, canonical resolved arguments, stale hashes,
  and at most one changed mutation through Pi adapter tests;
- run the complete Pi test/type-check suite and benchmark schema/invariant tests.

Failure stops before live inference.

## Live populations

All runs use the official local Q8 checkpoints and the previously measured
settings for each model. Pi permits four turns; provider requests, active tools,
calls, results, final documents, and framing are recorded. Result files are
append-only and use new `*_v2_20260925` names.

### MiniCPM transfer

Run all 48 frozen tasks once at seed 0 under explicit `safe-routed`, paired for
analysis with the immutable v1 treatment at the same seed. MiniCPM retains
65,536 context, 8,192 maximum completion tokens, temperature 0.7, top-p 0.95,
thinking disabled, and the prior default parallel-call setting.

The transfer passes only if:

1. all 48 trials are usable with exact provider framing;
2. correctness is at least 45/48, all four previously harmful task IDs are
   correct, and no v1-correct task regresses;
3. there are zero harmful final outcomes, reasoning leaks, or trials with more
   than one changed mutation;
4. all affected routes expose their exact single-tool surfaces and every
   successful call has canonical host-resolved arguments.

### Gemma and Ornith retention

For each model, run the 12 affected tasks at seeds 0 through 2 under explicit
`safe-routed`: four table additions, two list additions, one section body
replacement, and five typed frontmatter updates. Use each model's released Pi
settings and verify the exact changed route surfaces.

Each retention arm must be 36/36 correct with zero harmful outcomes, exact
provider framing, canonical resolved arguments, no reasoning leakage, and no
multiple changed mutation. Any model failure blocks adoption of the shared
change and requires narrowing or model-family isolation before resampling.

## Stopping and next decision

Run deterministic tests first, then MiniCPM, then Gemma and Ornith only if the
MiniCPM gate passes. Do not run a 480-pair MiniCPM campaign under v2. A complete
pass licenses merging these shared routes and planning a v3 treatment for the
three remaining MiniCPM loud refusals (`update-cell-multi-table`,
`append-hotfix-note`, and `delete-install-macos`). Only a later full-composition
gate can change MiniCPM `auto` or trigger Hermes parity work.

Preserve every valid or invalid instrument attempt under a distinct filename.
Never replace the v1 artifacts.
