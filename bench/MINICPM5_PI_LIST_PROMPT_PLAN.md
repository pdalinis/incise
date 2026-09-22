# MiniCPM5 Pi list prompt-isolation experiment

Recorded 2026-09-22 after the forced-tool arm failed and before changing the Pi profile prompt or inspecting any prompt-treatment outcome.

## Question and evidence

The adapter-independent integrated list pipeline scored 21/21, while the real Pi composition scored 16/21. Sending the exact OpenAI-compatible `tool_choice` did not move a single pair: the outgoing-request audit proved that every active request carried the expected choice, but the local MiniCPM5/llama.cpp path still returned prose on the same five phases.

The failed prose repeatedly says that the model cannot access files or lacks a file-writing tool. Pi's general coding-agent system prompt says its visible tools are `(none)`, says custom tools may exist, describes file and Pi-documentation workflows, and is then followed by the list summary. The successful direct arm instead uses a short family prompt saying that the model does not need file contents, the list tool performs the edit, formatting belongs to the host, and only the requested edit should be made.

This experiment asks whether that conflicting general framing, rather than the dynamic schemas, explains the real-Pi invocation gap.

## Control and treatment

Use the immutable unforced real-Pi `_v2` pool as the paired control. Preserve the same seven tasks, three seeds, fixtures, user prompts, MiniCPM5 Q8_0, temperature 0.7, top-p 0.95, Pi 0.85.1, Incise binary, four-tool allowlist, maximum turns, grader, sandbox behavior, dynamic schemas, host routing, validations, and one-successful-mutation latch.

Under `INCISE_PROFILE=minicpm-list` only, replace Pi's general system prompt with a compact profile prompt. It must state that the current Incise list tool can perform the requested edit, direct file access is unnecessary, exactly one current tool should be called, prose must not replace that call, the host owns formatting and addressing, and only the requested edit should be made. Append the same generated list summary and exact-selection instruction already used by the control.

Do not set `tool_choice`; the forced-choice arm established that the runtime does not enforce it. Do not change tool names, schemas, descriptions, the user message, execution, validation, or turn limit. The default and `safe-small` profiles must retain their existing Pi system prompt behavior.

## Deterministic verification

Export the compact prompt as a constant and assert its exact use in the MiniCPM integration test. Assert that the default profile still returns its normal Pi system prompt. Extend the passive provider-request record with the system-prompt SHA-256 and byte length, and verify that every treatment request uses the preregistered compact prompt plus the task-specific summary.

Run Pi tests, TypeScript typecheck, `bench/schematest.py`, syntax checks, and the real-binary one-write/stale-write integration test before sampling.

## Live gate

Write new raw, graded, and analysis artifacts with the `_v4` suffix. Run every fixed pair once; resume only transport failures.

The treatment passes only if all are true:

1. at least 19/21 final documents are correct;
2. every task is correct in at least two seeds;
3. no `_v2` correct pair regresses;
4. no generic-control correct pair regresses;
5. no outcome is destructive or collateral;
6. every refusal leaves the fixture byte-identical;
7. all 21 host routes match the preregistered mapping;
8. every successful mutation uses validated current structure;
9. no turn executes more than one successful mutation;
10. every provider request made while a pipeline phase is active carries the treatment system-prompt hash and contains no forced `tool_choice`;
11. the measured Gemma/default schema snapshot remains byte-identical.

A pass licenses the compact prompt only inside the opt-in Pi MiniCPM list profile. A failure ends Pi list-profile tuning: the unforced 16/21 profile remains experimental, and further progress requires a different runtime/model or host-derived list selection rather than more schema or prompt variants. This experiment does not validate Hermes, non-add list actions, or any default-profile change.
