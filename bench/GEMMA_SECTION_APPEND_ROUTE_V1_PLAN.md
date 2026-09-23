# Gemma exact section-append route v1 plan

Date: 2026-09-22

## Question

Can a host-resolved, exact-literal section append eliminate Gemma's remaining
leading-space formatting error without changing generic section behavior?

## Frozen conditions

- Paired control is the matching full-v6 `append-after-fence` pool: 9/10
  correct and one `collateral:formatting` result caused by a leading space.
- Population is `append-after-fence` at seeds 0 through 9, ten pairs total.
- Model/runtime is local `gemma4-direct-q8`, llama.cpp, Pi 0.85.1, 65,536-token
  context, thinking disabled, and the production `safe-routed` profile.
- Original prompt, fixture, grader, isolated reset, and four-turn cap are
  unchanged.
- Outputs use `gemma_section_append_route_v1_20260922` and are append-only.

## Treatment

Recognize only an explicit request of the form `Add a sentence to the
"SECTION" section saying "TEXT".` after removing the benchmark's section
outline preamble. Before inference, the adapter must:

1. extract exactly one Markdown path;
2. inspect the outline;
3. resolve the quoted section name to exactly one heading path;
4. retain the outline content hash; and
5. require non-empty quoted sentence text with no leading or trailing
   whitespace after parsing.

It then exposes only zero-argument `section_append_target`. The adapter supplies
the resolved section path and exact quoted text, writes with the inspection
hash, and permits one successful mutation. Any failed precondition or
unsupported request falls back to the standard profile. The executor and its
generic `section-append` contract are unchanged.

Transport failures may be retried once. No other pair may be resampled.

## Gate

All ten treatment trials must be usable and correct, with zero destructive or
collateral outcomes and zero regressions among the nine baseline-correct pairs.
Every first provider request must expose exactly `section_append_target` under
automatic tool choice and include its route-specific instruction; every model
call must supply `{}`; every resolved argument must equal
`{"section":"Code fences > Fenced headings and lists","text":"None of the above is parsed as markdown."}`;
and no trial may mutate twice.

With only one addressable control failure, the best possible paired result is
one treatment-only recovery and exact two-sided McNemar `p = 1.0`. Statistical
significance is therefore not a gate. A pass demonstrates removal of this
observed failure mode and licenses a separately preregistered full-composition
run; it does not establish a general effectiveness gain. A failure removes only
the append route; full v6 remains current.

## Non-goals

This experiment does not normalize arbitrary whitespace, infer unquoted
content, append multiple paragraphs, change the standard `section_edit` schema,
or alter Incise core behavior.
