# MiniCPM5 semantic-label section planner experiment

Recorded 2026-09-21 before implementing the treatment or inspecting any treatment outcome.

## Question

The dynamic three-field planner produced only 3/12 exact plans. Its anchor intent was semantically correct in all 12 calls, but `position` was wrong in 8/12 and numeric `child_count` in 7/12. The errors track executor vocabulary: MiniCPM treated `after` as compatible with "under" and treated ordinary body text as a child while flattening explicitly named subsections into body.

This experiment asks whether factorizing placement into request-language concepts and naming content shapes is enough for MiniCPM to classify structure. It is planner-only: no mutation and no second content call occur.

## Population and control

Use the same 12 `(task_id, trial)` pairs, prompts, fixtures, outlines, seeds, sampling settings, and forced single planning call as `minicpm5_section_pipeline_20260921`.

The recorded dynamic planner is the paired control at 3/12 exact plans. It is not resampled.

## Treatment

Expose and force one `section_insert_semantic_plan` tool with these required fields:

- `anchor`: the same dynamic shortest-unique address enum. After the call, resolve any supplied unique valid section address and canonicalize it to the enum address. This accepts a copied longer path such as `Reference > API` but still refuses absent or ambiguous sections.
- `relationship`: `sibling` or `subsection`. "Under", "inside", and "at the end of SECTION" mean `subsection`; "above", "below", "before", and "after SECTION" mean `sibling`.
- `order`: `before-existing` or `after-existing`. "Above", "before", or "at the start" mean `before-existing`; "below", "after", or "at the end" mean `after-existing`.
- `content_shape`: `body-only`, `one-subsection`, or `two-subsections`. Ordinary prose, code, or list text belongs to body and does not count. Only explicitly named nested headings count as subsections.

Map relationship plus order to executor placement only after sampling:

- sibling + before-existing -> before
- sibling + after-existing -> after
- subsection + before-existing -> first-child
- subsection + after-existing -> last-child

Map content shape to child count 0, 1, or 2. File and operation remain host-owned. Do not expose executor placement names or a numeric count.

The expected semantic plan is derived before sampling from the same ideal first operation and ideal-call cardinality as the control.

## Endpoints and gate

Primary endpoint: exact canonical structural-plan accuracy across all four fields after safe anchor canonicalization. Report each field separately and paired exact-plan transitions against the recorded dynamic planner.

The treatment clears the gate only if all are true:

1. at least 10/12 plans are exact;
2. relationship, order, and content shape are each correct in at least 11/12;
3. every task type is exact in at least two seeds;
4. all 12 anchors resolve uniquely and canonically;
5. no call reaches an edit executor.

A pass licenses a separately preregistered end-to-end pipeline run using the already-proven required content schemas. A failure ends section-classifier work for MiniCPM under this architecture; structure should remain host-derived or be assigned to a stronger model.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_section_semantic_plan_20260921{,_graded}.jsonl` and analysis to `bench/results/minicpm5_section_semantic_plan_analysis_20260921.json`. Preserve raw calls, raw and canonical anchors, expected and received plans, field matches, schema/input hashes, model identity, token counts, and latency.

Run each fixed pair once. Resume only transport errors. Do not alter labels, descriptions, mappings, gate thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
