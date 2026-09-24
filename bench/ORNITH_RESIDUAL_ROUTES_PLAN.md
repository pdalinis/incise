# Ornith residual-route closure

Recorded 2026-09-23 after freezing the second held seeds 20 through 29 and
before implementing or sampling the residual treatment.

## Evidence and changes

The expanded shared profile scored 477/480 on the second holdout. The three
misses were narrow and independently actionable:

- `add-item-ordered-renumber` supplied an invalid position, then appended the
  item at the wrong location;
- `delete-draft` abandoned frontmatter tooling and destructively rewrote the
  Markdown body; and
- `rename-setext` activated the route but sometimes described success without
  calling it because the model still had to repeat the replacement heading.

Add a strict exact parser and inspected host-owned arguments for the ordered
between-items insertion. Extend the guarded frontmatter deletion route to the
exact scalar-leaf request. Make literal section renames zero-argument by
host-owning both the resolved target and parsed replacement heading. The last
change also affects `rename-closed-atx`, so it is included in compatibility
confirmation. Fall back on every parse, inspection, uniqueness, or
precondition failure. Core and CLI behavior remain unchanged.

## Paired treatment and compatibility gate

Rerun the three residual tasks at Ornith seeds 20 through 29 using the identical
second-holdout configuration. Require 30/30 correct, zero harmful, malformed,
transport, framing, reasoning-leak, or excess-mutation outcomes, exact
zero-argument calls and host-resolved arguments, mean latency at most 20
seconds, and no completed trial above 60 seconds.

Then run `add-item-ordered-renumber`, `delete-draft`, `rename-setext`, and
`rename-closed-atx` against Gemma seeds 0 through 9 with its normal provider
defaults. Require 40/40 correct and the same safety and exact-route properties.

The 184.7-second `notes-second-ordinal` trial is retained as an observed
correctness-preserving inference outlier. Audit its framing and call count, but
do not change the route unless repeated calls or protocol drift are found.

## Final unseen validation

After both targeted gates pass, run all 48 tasks at unused Ornith seeds 30
through 39 with the same reasoning-off, 2,048-token,
`parallel_tool_calls: false`, four-turn configuration. Apply the unchanged
release gate: at least 478 usable, at least 472 correct, zero harmful final
documents, lists 100/100, sections at least 140/150, frontmatter at least
105/110, each table family at least 57/60, and zero route, framing,
reasoning-leak, or excess-mutation errors.
