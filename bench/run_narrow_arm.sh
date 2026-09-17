#!/bin/bash
# F-narrow's arm, three cells (450 trials). See FINDINGS, "The pre-registration,
# written before the run". Conditions are pinned there and must not be varied
# between cells: --turns 4 --result-shape delta, 15 tasks x 10 trials.
#
# One process per cell but one world for all three: `section_create` publishes
# no `action`, so `_actions_from_schemes` skips it and the three schemes coexist
# in the same import. That is the difference from `run_realign_gate.sh`, and the
# reason F-realign needed an env var and this does not.
set -u
cd "$(dirname "$0")/.."
R=bench/results
COMMON="--trials 10 --turns 4 --result-shape delta"

for cell in section_g_hpath section_kids_hpath section_split_hpath; do
    echo "=== cell: $cell"
    python3 bench/armb.py --tasks bench/tasks/sections.json --scheme "$cell" \
        $COMMON --out "$R/narrow_$cell.jsonl"
done

echo "=== grading"
for cell in section_g_hpath section_kids_hpath section_split_hpath; do
    python3 bench/armb.py --grade --tasks bench/tasks/sections.json \
        --out "$R/narrow_$cell.jsonl" --graded "$R/narrow_${cell}_graded.jsonl"
done

echo "=== done"
