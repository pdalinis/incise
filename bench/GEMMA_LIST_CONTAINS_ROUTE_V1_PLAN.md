# Gemma containing-item list route v1 plan

Date: 2026-09-22

## Question

Can a host-resolved list append eliminate Gemma's remaining collateral edit when
the request identifies one of several same-heading lists by an existing item?

## Frozen conditions

- Paired control is the matching full-v7 `add-item-mixed-markers` pool: 9/10
  correct and one `collateral:content` result caused by falling back from
  `list_edit` to `section_edit`.
- Population is `add-item-mixed-markers` at seeds 0 through 9, ten pairs total.
- Model/runtime is local `gemma4-direct-q8`, llama.cpp, Pi 0.85.1, 65,536-token
  context, thinking disabled, and the production `safe-routed` profile.
- Original prompt, fixture, grader, isolated reset, and four-turn cap are
  unchanged.
- Outputs use `gemma_list_contains_route_v1_20260922` and are append-only.

## Treatment

Recognize only an explicit request of the form `Under "HEADING", add an item
"NEW" to the list that contains the EXISTING item.` after removing the
benchmark's list-summary preamble. Before inference, the adapter must:

1. extract exactly one Markdown path;
2. inspect current lists and collect every list matching the quoted heading as
   an exact suffix;
3. inspect the actual items of every candidate list;
4. require exactly one candidate to contain exactly one item whose text equals
   the request's `EXISTING item` phrase;
5. require the exact new item text to be absent from the selected list; and
6. retain the selected item-read content hash.

It then exposes only zero-argument `list_append_target`. The adapter supplies
the full heading plus ordinal, exact new item text, and `position=end`, writes
with the inspection hash, and permits one successful mutation. Any failed
precondition or unsupported request falls back to the standard profile. No
marker-name mapping, fuzzy item matching, or executor change is permitted.

Transport failures may be retried once. No other pair may be resampled.

## Gate

All ten treatment trials must be usable and correct, with zero destructive or
collateral outcomes and zero regressions among the nine baseline-correct pairs.
Every first provider request must expose exactly `list_append_target` under
automatic tool choice and include its route-specific instruction; every model
call must supply `{}`; every resolved argument must equal
`{"list":{"heading":"Nested and mixed lists > Mixed markers at the same level","ordinal":1},"text":"second star item","position":"end"}`;
and no trial may mutate twice.

With only one addressable control failure, the best possible paired result has
one treatment-only recovery and exact two-sided McNemar `p = 1.0`; significance
is therefore descriptive rather than a gate. A pass licenses a separately
preregistered full-v8 composition run. A failure removes only this route; full
v7 remains current.

## Non-goals

This experiment does not route unquoted headings or new text, perform fuzzy
matching, map natural-language marker names to punctuation, insert relative to
an item, or change the standard `list_edit` or Incise core contracts.
