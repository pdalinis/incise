# MiniCPM5 v0.3 safe-routed composition count erratum

Recorded 2026-09-25 after all 480 raw trials completed and the first composition
analysis stopped on its route-count assertion. No model output, grade, route,
schema, or provider request changes as a result of this erratum.

The preregistration correctly defined 17 **affected** tasks: the 12 routes added
in v2 plus the five routes added in v3. Those are the tasks used for the Gemma
and Ornith retention arms. It incorrectly treated those 17 as the complete
routed population in the full shared profile and therefore predicted 170
routed trials plus 310 standard fallbacks.

The shared profile already contained exact routes for 30 other tasks from the
released Gemma and Ornith work. `v3_specs()` enumerates 47 routed task IDs; only
`get-whole-table` intentionally falls back to the standard eight-tool surface.
Across ten seeds, the mechanically correct audit expectations are therefore:

- 470 routed trials, each with one exact provider surface and one successful
  canonical call;
- 10 standard-fallback trials, each with the unchanged eight-tool surface.

The first analysis observed `checked: 470` with zero route errors, but failed
only because its assertion expected 170. Correct the analyzer to report and
require both 470 routed and 10 standard-fallback audits, then reanalyse the
existing immutable raw and graded pools under a separately named analysis.
Retain the original failed analysis. No retry or replacement seed is allowed.
