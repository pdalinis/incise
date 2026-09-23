# Gemma safe-routed full Pi composition v5 plan

Date: 2026-09-22

## Question

Does adding the production exact quoted-item list-removal route to the passing
Gemma profile eliminate the remaining destructive list-removal behavior while
preserving every previous section, table, frontmatter, and fallback guarantee?

## Frozen conditions

- Treatment code is frozen at `ac1e8dd`; targeted evidence is frozen in the
  list-removal v1 pool before this full run begins.
- Paired control is full profile v4: 462/479 usable pairs correct and 10 harmful
  outcomes. Its one persistent `rename-setext` seed-1 transport remains excluded.
- Model/runtime: local `gemma4-direct-q8`, llama.cpp OpenAI-compatible endpoint,
  Pi 0.85.1, 65,536-token context, thinking disabled.
- Population: all 48 frozen tasks and seeds 0 through 9, original prompts and
  graders, isolated file reset, and four-turn cap.
- Routed population: the prior 150 section, table, and frontmatter trials plus
  the two exact list-removal tasks, 170 trials total.
- Remaining usable trials must retain the exact standard eight-tool surface.
- Outputs use `gemma_safe_routed_full_v5_20260922` and are append-only.

Transport rows may be retried once. At most two persistent transport pairs may
be excluded and must be reported by identity.

## Adoption gate

The profile passes only if:

1. At least 478 usable pairs remain, treatment correctness is no lower than the
   matching v4 control, and treatment has at least 460 correct results.
2. Harmful outcomes do not exceed the matching v4 control.
3. All 170 routed trials are usable and correct with exact single-tool provider
   surfaces. Existing table filters, section trees, frontmatter arguments, and
   list-removal model plus resolved arguments must be canonical; no routed task
   may mutate twice.
4. Every usable fallback trial advertises exactly the standard eight tools.
5. Family floors hold: tables 57/60, lists 95/100, sections 135/150,
   frontmatter 95/110, and table reads 57/60.

The paired McNemar value is reported but is not an adoption gate: the new route
addresses only five v4 failures, so even five wins and no losses have a
two-sided exact floor of 0.0625. The 20/20 targeted confirmation supplies the
route-specific efficacy gate; this run supplies composition-wide safety.

A pass licenses retaining exact quoted-item list removal in Gemma `auto` and
updating the documented full-profile result. A failure removes only the new
list-removal route; full v4 remains current.
