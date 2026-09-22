# Gemma safe-routed full Pi composition v6 plan

Date: 2026-09-22

## Question

Does adding guarded host-owned creation of `build.cache` eliminate the final
frontmatter failure cluster while preserving the passing v5 list, section,
table, existing-key frontmatter, and fallback behavior?

## Frozen conditions

- Treatment code is frozen at `854b522`; targeted evidence is frozen in the
  guarded-create v1 pool before this full run begins.
- Paired control is full profile v5: 469/479 usable pairs correct and five
  harmful outcomes. Its persistent `rename-setext` seed-1 transport remains
  excluded.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint,
  Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks and seeds 0 through 9, original prompts and
  graders, isolated file reset, and four-turn cap.
- Routed population: the prior 170 trials plus ten guarded frontmatter-create
  trials, 180 total.
- Remaining usable trials must retain the exact standard eight-tool surface.
- Outputs use `gemma_safe_routed_full_v6_20260922` and are append-only.

Transport rows may be retried once. At most two persistent transport pairs may
be excluded and must be reported by identity.

## Adoption gate

The profile passes only if:

1. At least 478 usable pairs remain, treatment correctness is no lower than the
   matching v5 control, and treatment has at least 467 correct results.
2. Harmful outcomes do not exceed the matching v5 control.
3. All 180 routed trials are usable and correct with exact single-tool provider
   surfaces. Existing route arguments and the guarded create model plus resolved
   arguments must be canonical; no routed task may mutate twice.
4. Every usable fallback trial advertises exactly the standard eight tools.
5. Family floors hold: tables 57/60, lists 95/100, sections 135/150,
   frontmatter 105/110, and table reads 57/60.

The paired McNemar value is reported but is not a full-run gate. The targeted
10-pair confirmation already supplies the significant efficacy result; this
run tests composition-wide safety under normal stochastic variation.

A pass licenses retaining guarded `build.cache` creation in Gemma `auto` and
updating the documented full-profile result. A failure removes only the new
create route; full v5 remains current.
