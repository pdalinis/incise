# MiniCPM5 Pi forced list-tool experiment

Recorded 2026-09-22 after the valid real-Pi list-profile pool and before implementing forced choice or inspecting any forced-choice outcome.

## Question and control

The adapter-independent integrated arm forced each phase and scored 21/21. The real Pi profile used the same schemas and validation but only restricted the active tool set; it scored 16/21. All 16 executed mutations were correct. Four failures answered in prose instead of invoking the sole active `list_select`, and one made the correct selection before answering in prose instead of invoking `list_append_item`.

This experiment asks whether forcing Pi's one active phase tool closes exactly that invocation gap without changing arguments, routing, validation, or execution.

Use the immutable `_v2` Pi pool as the paired control. Preserve the same seven tasks, three seeds, fixtures, user prompts, system-summary injection, MiniCPM5 Q8_0, temperature 0.7, top-p 0.95, Pi 0.85.1, Incise binary, four-tool allowlist, maximum turns, grader, and sandbox behavior.

## Treatment

Only under `INCISE_PROFILE=minicpm-list`, register a `before_provider_request` hook. When a pipeline phase is active:

1. verify that the outgoing request contains the one expected active tool;
2. set OpenAI-compatible `tool_choice` to that exact function name;
3. change no other request field.

The required name is `list_select` before address selection and the already selected route-specific content tool afterward. A refused or malformed content call keeps the same forced content tool available for repair. After one successful mutation, the one-success latch clears the required name and the adapter exposes no tools.

If the expected tool is absent from the provider payload, fail closed before inference rather than silently reverting to automatic choice. The hook must be absent from the measured and `safe-small` profiles.

## Deterministic verification

Extend the Pi integration test to capture both provider phases and assert that only `tool_choice` is added, with the exact active function name. Assert that the name changes after selection, remains after a refused content attempt, and is absent after success. Existing measured-profile tool registration, schemas, and provider payload behavior must stay unchanged.

Run the Pi package tests, TypeScript typecheck, `bench/schematest.py`, and the existing real-binary one-write/stale-write integration tests before sampling.

## Live gate

Write the new raw, graded, and analysis artifacts with the `_v3` suffix. Run every fixed pair once; resume only transport failures.

The treatment passes only if all are true:

1. at least 19/21 final documents are correct;
2. every task is correct in at least two seeds;
3. no `_v2` correct pair regresses;
4. no generic-control correct pair regresses;
5. no outcome is destructive or collateral;
6. every refusal leaves the fixture byte-identical;
7. all 21 routes match the preregistered mapping;
8. every successful mutation uses validated current structure;
9. no turn executes more than one successful mutation;
10. every provider request made while a pipeline phase is active carries that phase's exact forced tool; the expected minimum is 42 phase requests, and refused repair attempts may add more;
11. the measured Gemma/default schema snapshot remains byte-identical.

A pass licenses forced choice as part of the opt-in Pi MiniCPM list profile. A failure ends Pi list-profile tuning unless it reveals a distinct, bounded adapter defect. It does not change the default profile, validate Hermes, support non-add list actions, or generalize beyond the measured request shapes.
