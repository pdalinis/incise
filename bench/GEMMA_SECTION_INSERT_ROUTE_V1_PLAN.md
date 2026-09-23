# Gemma host-resolved section insertion route v1

Date: 2026-09-22

## Question

Can the production Pi `safe-routed` profile recover Gemma section insertions by
letting the host own the existing anchor and placement relation, while exposing
only the content slots that the request actually needs?

The earlier generic atomic-tree treatment scored 1/40 because the model still
selected the parent and relation, could add unrequested root prose, and could
reconstruct existing sections. The full production-profile v2 run then scored
4/40 across the same insertion population on the standard fallback. This
treatment removes those decisions without changing Incise core behavior.

## Frozen conditions

- Control is the 40 matching pairs in
  `gemma_safe_routed_full_v2_20260922_graded.jsonl`.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint,
  Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: `insert-release-at-top`, `insert-subsection-last`,
  `insert-nested-ratelimits`, and `insert-troubleshooting`, seeds 0 through 9,
  with frozen prompts, fixtures, and whole-document graders.
- Treatment uses the production `safe-routed` profile and a single dynamic
  `section_insert_target` tool. The adapter reads the outline, resolves exactly
  one existing anchor, owns `before` or `last-child`, and supplies the content
  hash. The model can provide only the requested new-heading/body/subsection
  slots. A tree request cannot add unrequested root body text.
- The adapter converts those slots into one existing `section-insert` call with
  structured children and permits at most one successful mutation.
- Ambiguous or unsupported wording falls back to the standard profile outside
  this frozen population.
- Outputs use the immutable prefix
  `gemma_section_insert_route_v1_20260922`.

Transport rows may be retried once. At most one persistent transport pair may
be excluded and must be reported by identity; transport is never semantic
success.

## Adoption gate

The route passes only if all conditions hold:

1. At least 39 usable pairs remain, at least 32 are correct, and treatment
   correctness exceeds paired control.
2. Every task scores at least 7/10 among its usable pairs.
3. There are zero destructive or collateral outcomes and at most two
   regressions among control-correct pairs.
4. Every usable first provider request exposes only `section_insert_target`.
5. Every successful call uses the preregistered existing anchor and placement
   relation, and no turn performs more than one successful mutation.

A pass licenses adding this route to the Gemma `auto` composition and then
running a new full 480-pair confirmation. A failure leaves production behavior
unchanged and requires diagnosis before another treatment.
