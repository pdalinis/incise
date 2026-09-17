#!/bin/bash
# F-realign's 120-trial gate, run as four cells (180 trials). See FINDINGS,
# "The pre-registration, written before the run". Conditions are pinned there
# and must not be varied between cells: --turns 4 --result-shape delta.
#
# The two worlds share no process: INCISE_BENCH_REALIGN is read at import, and
# `_actions_from_schemes` raises if one tool name publishes two enums, so the
# candidate cannot be a scheme alongside its own control.
set -u
cd "$(dirname "$0")/.."
R=bench/results
COMMON="--trials 10 --turns 4 --result-shape delta"

echo "=== cell 1/4: tables.json under scheme_f (control world)"
python3 bench/armb.py --tasks bench/tasks/tables.json --scheme scheme_f \
    $COMMON --out $R/realign_ctl_tables.jsonl

echo "=== cell 2/4: tables_realign.json under scheme_f (control world, forced)"
python3 bench/armb.py --tasks bench/tasks/tables_realign.json --scheme scheme_f \
    $COMMON --out $R/realign_ctl_realign.jsonl

echo "=== cell 3/4: tables.json under scheme_f_realign (treatment world)"
INCISE_BENCH_REALIGN=1 python3 bench/armb.py --tasks bench/tasks/tables.json \
    --scheme scheme_f_realign $COMMON --out $R/realign_trt_tables.jsonl

echo "=== cell 4/4: tables_realign.json under scheme_f_realign (treatment world)"
INCISE_BENCH_REALIGN=1 python3 bench/armb.py --tasks bench/tasks/tables_realign.json \
    --scheme scheme_f_realign $COMMON --out $R/realign_trt_realign.jsonl

echo "=== grading"
python3 bench/armb.py --grade --tasks bench/tasks/tables.json \
    --out $R/realign_ctl_tables.jsonl --graded $R/realign_ctl_tables_graded.jsonl
python3 bench/armb.py --grade --tasks bench/tasks/tables_realign.json \
    --out $R/realign_ctl_realign.jsonl --graded $R/realign_ctl_realign_graded.jsonl
INCISE_BENCH_REALIGN=1 python3 bench/armb.py --grade --tasks bench/tasks/tables.json \
    --out $R/realign_trt_tables.jsonl --graded $R/realign_trt_tables_graded.jsonl
INCISE_BENCH_REALIGN=1 python3 bench/armb.py --grade --tasks bench/tasks/tables_realign.json \
    --out $R/realign_trt_realign.jsonl --graded $R/realign_trt_realign_graded.jsonl

echo "=== done"
