# Gemma safe-routed full Pi composition v8 plan

Date: 2026-09-22

## Question

Does adding host-owned list selection by an exact contained item eliminate the
last harmful Gemma outcome while preserving the passing v7 behavior?

## Frozen conditions

- Treatment code is frozen at `66baf19`; targeted evidence is frozen in the
  containing-item list v1 pool before this full run begins.
- Paired control is full profile v7. Its complete 480-row latest-attempt pool
  contains 473 correct results, one harmful list result, five loud operation
  errors, and one persistent transport.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint,
  Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks and seeds 0 through 9, original prompts and
  graders, isolated file reset, and four-turn cap.
- Routed population: the prior 190 trials plus ten containing-item list trials,
  200 total.
- Remaining usable trials must retain the exact standard eight-tool surface.
- Outputs use `gemma_safe_routed_full_v8_20260922` and are append-only.

Transport rows may be retried once. At most two persistent transport pairs may
be excluded and must be reported by identity.

## Adoption gate

The profile passes only if:

1. At least 478 usable pairs remain, treatment correctness is no lower than the
   matching v7 control, and treatment has at least 472 correct results.
2. Treatment has zero destructive, wrong, collateral-content, or
   collateral-formatting outcomes.
3. All 200 routed trials are usable and correct with exact single-tool provider
   surfaces. Existing route arguments plus containing-item list
   model/resolved arguments must be canonical; no routed task may mutate twice.
4. All ten `add-item-mixed-markers` trials expose `list_append_target`, call it
   once with `{}`, resolve ordinal 1 and exact text, and grade correct.
5. Every usable fallback trial advertises exactly the standard eight tools.
6. Family floors hold: tables 57/60, lists 100/100, sections 140/150,
   frontmatter 105/110, and table reads 57/60.

The paired McNemar value is reported but is not a full-run gate. This run tests
composition-wide safety and retention; the ten-pair targeted arm could not
establish statistical significance from one possible recovery.

A pass licenses retaining containing-item list routing in Gemma `auto` and
documenting the measured profile as harm-free on the usable full-v8 population.
A failure removes only the new route; full v7 remains current.
