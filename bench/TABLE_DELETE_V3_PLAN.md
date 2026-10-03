# Whole-table deletion combined-repair v3 plan

## Evidence entering v3

The frozen v2 treatment at candidate commit cae15f9 completed 60 usable MiniCPM5 trials. Fifty-nine were correct and one was a loud op_error outcome, with zero destructive, collateral, data-loss, or silent-corruption results. The remaining failure was delete-first-adjacent-table seed 9: turn one omitted the ordinal; turns two and three supplied ordinal 0 but still omitted confirm. Each retry resolved the same first table and no mutation occurred. Raw SHA-256 is 3014021895172938a69b65c7b63b77f77078329cc0608621cdfe3ddb6849f567 and graded SHA-256 is 04e90e0b33352fac3fa5dfc760c2cd0f6c687d96a4ac86bfd5a81167a446c521. The failed v1 and v2 gates remain immutable.

## Question

Can the ambiguity refusal for delete-table collapse the two required repairs into one by telling the caller to pass both an ordinal and confirm=true, while preserving the confirmation guard and all existing table-address behavior for every other operation?

## Frozen change and procedure

Only the delete-table ambiguity refusal changes. When delete-table is called without confirm and its heading resolves to multiple tables, the existing ambiguity message gains one final line: `To delete one whole table, retry with both its ordinal and confirm=true.` The Rust core and independent Python oracle change byte-for-byte; all other operations retain the existing generic ambiguity refusal. Add exact refusal tests and a differential case. Then rerun deterministic, oracle, differential, and mutation checks. Rerun all six deletion tasks at seeds 0 through 9 with scheme_f, result-shape delta, and max-turns 2 in a new append-only pool with prefix table_delete_20261003_treatment_v3. Executor behavior after resolution, schema, fixtures, task instructions, model, server, decoding settings, and seeds remain frozen to TABLE_DELETE_PLAN.md.

## Gate

V3 passes only at 60/60 usable and correct, zero harmful or collateral outcomes, and no deletion of a non-target table. Every adjacent-table trial must either include the resolved ordinal and confirm=true on its recovery call and finish with exactly the golden bytes, or terminate without mutation and fail the gate. A pass restores eligibility for the original retention and composition-reach gates; it does not erase either earlier failed gate or itself license publication.

## Outcome

The frozen v3 pool completed 60 usable trials: 59 correct and one loud op_error, with zero data loss, silent corruption, collateral deletion, or wrong-table deletion. Adjacent-table seeds 0 through 8 recovered in one call with ordinal 0 and confirm=true. Seed 9 supplied ordinal 0 but omitted confirm, so the executor refused before mutation. Raw SHA-256 is 526e68cc172a6c34257970434991c47f5763bd241f72b9e9c6107f21854fe925 and graded SHA-256 is bebdafc14fe8f8a7778be79f73b1ca231c05220a306011d73935be090f69ad52. V3 fails its 60/60 gate. Per TABLE_DELETE_PLAN.md, the action is not eligible for the published model schema or host adapters; the core and CLI implementation may remain available while a separately preregistered interface is investigated.
