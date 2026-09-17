# Decision Log

Each row records a decision and the reason it was taken.

| ID | Decision | Rationale |
| --- | --- | --- |
| D-1 | Return the description alone | Returning the heading outline alongside the one-line description was statistically identical to returning the outline alone, so the omission is the deliverable and the sentence on its own is what the measurement actually adopted here. |
| D-2 | Withhold the outline | Returning the heading outline instead of the one-line description was measurably worse on continuation, so the outline is withheld and the sentence on its own is what the measurement actually adopted for this response shape. |
| D-3 | Turn autojunk off for the line diff | Keeping the autojunk heuristic on a document's line list made the tally overstate an eighteen line delete, because the popular elements it purges are the blank lines and table delimiters a diff needs as anchors. |
| D-4 | Mutate before believing a green run | A surviving mutation is evidence about the harness before it is evidence about the code, so a green differential run counts for nothing at all until every mutation in the list has been shown to turn it red. |
| D-5 | Freeze the corpus | The corpus stays frozen because FINDINGS quotes per-file trial results against those twenty six files, and every coverage gap that needs a new document gets one under the synthetic directory instead of a corpus edit. |
