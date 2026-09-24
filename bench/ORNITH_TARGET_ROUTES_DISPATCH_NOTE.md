# Ornith target-route dispatch correction

The first treatment dispatch on 2026-09-23 was stopped after five rows. The Pi
extension selected `list_set_checked_target`, but `bench/ornith_full.py` had not
added the two new route names to its explicit session tool allow-list. Provider
manifests therefore recorded an empty active tool set, and every row ended with
no tool call.

The five raw and graded rows are retained under the
`ornith_target_routes_treatment_dispatch_failure_20260923` prefix. They are
pre-inference harness failures and do not enter the treatment. The correction
only adds `list_set_checked_target` and `section_set_level_target` to the list
of tools the benchmark worker may expose. The treatment restarts from all 30
task/seed pairs under separately named files.
