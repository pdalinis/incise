# Pull request

Thank you for contributing to incise. Keep the description focused on the behavior being changed and the evidence used to validate it.

## Summary

<!-- What changed? Keep this concise and describe the resulting behavior. -->

## Why

<!-- What problem does this solve? Link an issue or benchmark finding when one exists. -->

## Validation

<!-- List the exact commands or checks you ran and their results. If a standard check was not run, explain why. -->

## Benchmark impact

Replace the value below with exactly one classification.

Benchmark impact: `select one: no model-facing effect | replay or regrade only | targeted live remeasurement required | family-wide live remeasurement required | composition-wide live remeasurement required`

<!-- Explain the classification. A change has a model-facing effect if it can alter the tool or prompt bytes a model sees, the call it emits, the executor response it receives, or whether it continues to another turn. Passing deterministic tests does not refresh a model measurement. -->

## Benchmark evidence

<!-- For no model-facing effect, explain why the measured interface is byte-identical. Otherwise link the reach analysis, replay or regrade, pre-registered plan, and new results as applicable. If live measurement is intentionally deferred, identify the affected claim as unverified. -->

## Compatibility and documentation

<!-- Describe public CLI, schema, plugin, refusal-message, fixture, or documentation effects. State whether release notes or migration guidance are needed. -->

## Reviewer notes

<!-- Call out subtle invariants, deliberately unchanged behavior, follow-up work, or areas where you want particular scrutiny. -->
