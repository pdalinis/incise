# Gemma safe-routed full Pi composition v7 plan

Date: 2026-09-22

## Question

Does adding host-owned exact-literal section append remove the observed
formatting failure while preserving the passing v6 table, list, section,
frontmatter, table-read, and fallback behavior?

## Frozen conditions

- Treatment code is frozen at `f023515`; targeted evidence is frozen in the
  section-append v1 pool before this full run begins.
- Paired control is full profile v6. Its complete 480-row pool contains 474
  correct results, one harmful formatting result, and five loud operation
  errors. The earlier 473/479 claim excluded a transport in its v5 control;
  this v7 comparison uses all 480 v6 rows directly.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint,
  Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks and seeds 0 through 9, original prompts and
  graders, isolated file reset, and four-turn cap.
- Routed population: the prior 180 trials plus ten exact section-append trials,
  190 total.
- Remaining usable trials must retain the exact standard eight-tool surface.
- Outputs use `gemma_safe_routed_full_v7_20260922` and are append-only.

Transport rows may be retried once. At most two persistent transport pairs may
be excluded and must be reported by identity.

## Adoption gate

The profile passes only if:

1. At least 478 usable pairs remain, treatment correctness is no lower than the
   matching v6 control, and treatment has at least 472 correct results.
2. Harmful outcomes do not exceed the matching v6 control.
3. All 190 routed trials are usable and correct with exact single-tool provider
   surfaces. Existing route arguments plus append model/resolved arguments must
   be canonical; no routed task may mutate twice.
4. All ten `append-after-fence` trials expose `section_append_target`, call it
   once with `{}`, resolve the preregistered section and exact text, and grade
   correct.
5. Every usable fallback trial advertises exactly the standard eight tools.
6. Family floors hold: tables 57/60, lists 95/100, sections 140/150,
   frontmatter 105/110, and table reads 57/60.

The paired McNemar value is reported but is not a full-run gate. The targeted
arm had only one possible recovery and therefore could not support a
significance claim; this run tests composition-wide safety and retention under
normal stochastic variation.

A pass licenses retaining exact section append in Gemma `auto` and updating the
documented full-profile result. A failure removes only the new append route;
full v6 remains current.
