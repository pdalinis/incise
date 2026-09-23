# Ornith routed-read grading correction

Recorded 2026-09-23 after the routed, reasoning-off pilot and before any later
Ornith outcome run.

The pilot's generic graded artifact labeled all six `table_query` trials
`malformed` because `pi_composition.grade_actual` reconstructs reports only
from `table_get` calls. Inspection showed that every trial made one successful
`table_query` call, the host resolved the preregistered exact filter, the tool
returned the correct rows, and the model's answer was correct.

This is a harness-grading omission, not a product change. Gemma's routed
campaign already uses route-aware grading based on `details.rows`. The Ornith
harness now applies the same rule when a successful `table_query` result is
present. The original graded JSONL remains immutable; a separately named
route-aware regrade and analysis preserve both interpretations. Mutation tasks,
prompts, model requests, tools, fixtures, and executor behavior are unchanged.
