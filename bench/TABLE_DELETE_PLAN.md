# Whole-table deletion benchmark plan

## Classification

Benchmark impact: composition-wide live remeasurement requires consideration because the published table_edit enum and description change. The first live gate is table-family targeted; a pass licenses, but does not replace, the composition decision. Deterministic implementation work and ceiling checks precede GPU use.

## Hypothesis

Adding action=delete-table gives a model a bounded semantic operation for an explicit whole-table removal and prevents fallback to whole-file reconstruction, without causing the model to choose whole-table deletion on existing row-level table tasks.

## Frozen candidate

The public action is delete-table and normalizes explicitly to the core operation table-delete. It requires table. Generic dispatch refuses unless confirm=true, identifying the resolved heading and ordinal, data-row count, columns, and capped first and last row previews. The raw operation deletes only the table lines and their separating blank gap; it never deletes a caption, heading, or descendant section. It resolves identity without rectangularity validation. At an end-of-file or end-of-section boundary it consumes the leading gap; otherwise it consumes the trailing gap. Pi and Hermes use the same normalization. Any safe-routed whole-table route must inspect the table first, own the exact address and confirmation, and use the read hash.

## Population and procedure

Control is the current four-action table_edit surface and executor. Treatment is identical except for the new action, confirmation argument, normalization, and executor operation. First run deterministic Rust, Python-oracle, differential, schema, CLI, and adapter tests plus mutation testing. Then run ceiling.py against purpose-built whole-table deletion tasks and require complete executability.

The targeted live population contains all six existing table-edit tasks over the established ten seeds as a 60-pair retention set, plus a separately named synthetic deletion set covering a root table, a table between prose blocks, a section-final table, adjacent tables, duplicate-heading ordinals, and a malformed non-rectangular table. Control and treatment use separate processes because one published tool name cannot carry two action enums in one benchmark world. Model checkpoint, inference server, decoding settings, prompts, graders, and seed pairing remain those of the latest applicable table campaign. Results use a new table_delete_20261003 prefix and never overwrite an earlier pool.

## Gate and decision rule

The candidate advances only if the deterministic and ceiling suites pass at 100%, every treatment deletion removes exactly the intended table and spacing, and there are zero harmful or collateral outcomes. The existing 60 table tasks must remain 60/60 correct, with zero delete-table selections. The deletion population must be 100% correct in treatment, and every generic confirmation refusal must either recover with the identical resolved address and confirm=true or terminate without mutation. Report paired control-versus-treatment correctness and harmful outcomes; do not infer broad efficacy from the single motivating incident.

A targeted pass licenses the schema and host-route candidate for composition review. It does not automatically refresh the existing composition claim. Reach analysis must identify which standard fallbacks receive the changed table_edit surface; any affected published composition claim remains explicitly unverified until the required confirmation run passes. A failed retention or safety gate leaves delete-table unpublished.

## Reproducibility record

Record the model and checkpoint, server and version, decoding parameters, prompt and schema identifiers, executor commit, hashes of both task sets, seeds, timestamps, raw and graded artifact hashes, and the exact control and treatment commits. Keep the motivating private document out of fixtures and issue text; synthetic inputs carry the regression.
