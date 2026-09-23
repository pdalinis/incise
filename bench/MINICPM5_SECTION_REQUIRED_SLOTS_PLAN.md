# MiniCPM5 cardinality-routed required section-slots experiment

Recorded 2026-09-21 before implementing the treatment schemas or inspecting any treatment outcome.

## Question

The host-routed flat section-slots arm improved insertion from 0/12 to 6/12 with no safety failure, but MiniCPM frequently omitted optional child fields: release insertion was 3/3, a single ordinary subsection 2/3, a one-child nested insertion 1/3, and a two-child insertion 0/3.

This experiment asks whether the host can remove that optionality after classifying how many subsections the user requested. It is another routing ceiling, not an end-to-end cardinality classifier.

## Control

Use the 12 paired results in `bench/results/minicpm5_section_slots_20260921{,_graded}.jsonl`: 6/12 correct, six wrong, zero destructive or collateral outcomes.

## Treatment

Keep the same model, endpoint, prompts, fixtures, outlines, host-injected file/anchor/position, three seeds, temperature 0.7, top-p 0.95, one atomic mutation, executor, and grader.

The host selects and forces one content tool from the request's known shape:

- zero-child insertion: require `new_heading` and `body`;
- one-child insertion: require `new_heading`, `child_1_heading`, and `child_1_body`;
- two-child insertion: require `new_heading`, both child headings, and both child bodies.

Fields for unrequested children are absent from the schema. Tool names and descriptions state the required cardinality. The host composes the same atomic `section-insert` operation as the control. There is no retry, correction turn, structural field exposed to the model, or second mutation.

## Endpoints and decision rule

Primary endpoint: paired exact correctness over the same 12 pairs, with exact two-sided McNemar.

The treatment clears the gate only if all are true:

1. at least 10/12 pairs are exactly correct;
2. every task type is correct in at least two of three seeds;
3. no treatment pair is destructive or collateral;
4. no control-correct pair regresses;
5. every refusal leaves the fixture byte-identical.

A passing result supports a production router that classifies requested child count before exposing a content schema. It does not validate that classifier or alter the default profile.

## Artifacts and stopping

Write raw and graded rows to `bench/results/minicpm5_section_required_slots_20260921{,_graded}.jsonl` and analysis to `bench/results/minicpm5_section_required_slots_analysis_20260921.json`. Pin schemas per task shape and all source artifacts by hash.

Run each fixed pair once. Resume only transport errors. Do not revise field requirements, descriptions, thresholds, or seeds after seeing outcomes. Restore Gemma after collection.
