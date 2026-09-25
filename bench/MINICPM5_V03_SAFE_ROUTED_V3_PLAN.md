# MiniCPM5 v0.3 safe-routed v3 completion plan

Recorded 2026-09-25 after the immutable v2 transfer was committed at
`a01338e` and before implementing v3 or sampling a v3 outcome. Tracking issue:
https://github.com/pdalinis/incise/issues/32.

## Question

Can five additional strict host-resolved routes eliminate the complete
MiniCPM seed-0 residue while retaining every v2 repair and preserving the
released Gemma and Ornith profiles?

V2 made all 12 targeted tasks correct with an exact route audit, but finished
43/48 because unsupported fallbacks changed sampling trajectory and exposed
five unambiguous residual tasks. Three wrote the wrong file content, one
returned a wrong no-edit answer, and one refused loudly. V3 treats unsupported
structural mutations as the safety boundary rather than assuming a prior loud
refusal will repeat.

## Treatment

Build on the frozen v2 candidate and add only these shared `safe-routed`
capabilities:

1. Parse `Remove the X row from the Y table`, inspect the uniquely resolved
   table and current rows, require exactly one matching value in a uniquely
   named column, and expose an empty-schema host-owned row deletion.
2. Parse the exact staging-host resize request, use table labels plus a
   structured row read to resolve the staging table and unique host, validate
   the requested output column, and expose an empty-schema host-owned cell
   update.
3. Parse the explicit release-itself hotfix sentence, resolve the unique
   bracketed release heading from the outline, and host-own the exact append
   target and quoted text.
4. Parse `Delete the macOS section under Install, including everything in it`,
   inspect and resolve the exact outline path, and expose an empty-schema
   deletion with `subtree=true` and the preceding outline hash.
5. Parse the labelled staging-table read, inspect table labels, resolve ordinal
   1, and expose the existing empty-schema `table_query` with a host-owned
   unfiltered table address.

The table summary parser may retain an optional label only when the CLI reports
one. All mutation routes must read before writing, carry the read hash, and
permit one changed mutation. Negated, incomplete, ambiguous, duplicate, wrong-
column, missing-label, and wrong-current-value requests fall back unchanged.

Core operations, standard tools, refusal wording, model-family detection, and
MiniCPM `auto` selection do not change.

## Deterministic gate

Add positive, near-match, negation, ambiguity, label, row-validation,
canonical-argument, stale-hash, subtree, and one-success tests. Run Pi tests and
type checking, Rust workspace tests, benchmark invariants, schema parity,
recorded-call replay agreement, and Hermes adapter tests before live sampling.

## Live gates

All result names are new, append-only, and end in `_v3_20260925`.

1. Run all 48 frozen tasks once at seed 0 with MiniCPM under explicit
   `safe-routed`. Retain the v2 MiniCPM settings and pair against the immutable
   v2 pool. The gate requires 48/48 usable and correct, zero harmful outcomes,
   no v2-correct regression, no reasoning leakage, no multiple changed
   mutation, exact provider framing, and exact canonical route audits for all
   17 v2+v3 affected tasks.
2. Only if MiniCPM passes, run the 17 affected tasks at seeds 0 through 2 for
   Gemma and Ornith using each released model's Pi settings. Each 51-trial arm
   must be 51/51 correct with zero harm, exact framing and arguments, no
   reasoning leakage, and no multiple changed mutation.

A failure stops subsequent arms. A complete pass licenses merging the shared
routes and preregistering the 480-pair MiniCPM composition gate. It does not by
itself change MiniCPM `auto` or license Hermes parity.
