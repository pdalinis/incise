# Gemma table-route v2 confirmation

Date: 2026-09-22

## Question

Does explicit predicate extraction with host-owned values fix the full-run table-read regressions while leaving projection-only and ordinal reads on the standard Pi surface?

## Frozen treatment

- Product profile: `INCISE_PROFILE=safe-routed` in the Pi extension.
- A table route now requires an explicit, unambiguous column/value predicate. The host extracts the exact value and executes it; the model receives a zero-argument `table_query` tool.
- `get-filter-one-column`, `get-filter-two-columns`, `get-filter-no-match`, and `get-escaped-cell` must route.
- `get-whole-table` and `get-ordinal-table` must fall back to the standard eight tools.
- Model/runtime, prompts, graders, ten seeds, and Pi 0.85.1 match the failed full run.
- Population: all six table-read tasks, ten seeds each, 60 trials.
- Outputs use the immutable prefix `gemma_table_route_v2_20260922`.

## Gate

The treatment passes only if:

1. All 60 trials are usable and correct.
2. Every first provider request exposes exactly `table_query` for the four filtered tasks and exactly the standard eight tools for both fallback tasks.
3. Every routed execution records filter arguments byte-for-byte equal to the task ideal filter.
4. There are zero malformed, misreported, unfiltered, destructive, collateral, or tool-error outcomes.

A pass licenses a second full-composition run. It does not by itself license default `auto`. A failure keeps the broad table route out of the profile; the already confirmed two-column and no-match routes may then be preserved only through a narrower classifier.
