#!/usr/bin/env python3
"""One rule for reading `bench/results/`, because it has been got wrong twice.

**`bench/results/` is not one population.** Every arm this project has ever run
writes into it, and a replay writes into it too -- and a replay's rows are not
new observations. `armb.replay` and `armc.replay` take prefixes *out* of this
directory, pin the first call, and vary one string after it. So every replayed
row's first call is a copy of a first call already in the directory. Counting
both is double counting, and it has produced two wrong published figures:

  - F-framing published **726 refusals**; the exit-1 count was 1727 and most of
    it was the harness pointed at the wrong executor. `refusal_pool.py` was
    written to fix that, and it also excluded replay output -- by **file name
    prefix**, `armc_framing_`, under a comment promising the rule was general:
    *"not as a blocklist of arms: the same applies to any future replay
    output."* It was a blocklist. The next two replays were called
    `armc_replay_path*` and `armc_ordinal*`, and both slipped straight through.
  - F-unique published **206 ordinal refusals / 155 first calls**, over a
    population that included F-framing's replay rows. The true figures are 140
    and 111.

The test is the `tag` field. `armb.replay` and `armc.replay` stamp every row
they write with the condition tag they varied; nothing else in `results/` has
one. It is a property of the row rather than of its file name, so a replay
written tomorrow under any name is excluded the day it is written.

What this rule deliberately does **not** do is key on the scheme string. That
was tried first and is wrong in the expensive direction: replay rows do carry
compound schemes like `section_g:before:plain`, but so do S14's `section_g:delta`
and `section_kids:both`, which are genuine trials -- a model answering a fresh
prompt at a different result shape. Dropping those to catch the replays would
have thrown away eleven real samples to remove sixty-six duplicates.

A caller that wants the replays back -- grading one, say -- should read the
files directly and say so. This module is for counting *what models did*.

**Not every count over `results/` is a census, and this rule would damage the
ones that are not.** `regrade_snapshot.py` globs the directory whole and must
keep doing it: it asks whether any *recorded call's* behaviour moves under a
change, which makes it a regression corpus, not a sample. A replay's
re-execution of a call is a recorded call whose behaviour moves too, so
excluding it would shrink coverage for nothing -- duplicates cost that script
runtime, not validity. `s15_analyse.py` and `framing_report.py` are the same
case named from the other side: both open specific files, and `framing_report`
exists to report *on* a replay. The question to ask of a count is what its
denominator means, not which directory it read.

Where a census and a corpus count the same event they will disagree, and the
disagreement is the check rather than a defect to be flattened. F-action's
fused-key figure is `21` through `regrade_snapshot` and `11` through here; the
difference is exactly ten `armc_framing_lists` rows, which are five of those
same calls re-executed under two framings (`FINDINGS:4701`).

One thing this rule is blunt about, stated so it is a choice rather than an
oversight. A replay row's **first** call is the pinned copy; its later turns are
fresh model output. Dropping the whole row therefore drops those later turns
too. That is deliberate: a replay's turn 3 is a response to a tool result the
replay *altered*, so it is an observation of the replay's condition and not of
the arm, and pooling it into "what the arms recorded" mixes treatments. The
measured cost of the bluntness is small and was checked rather than assumed --
on the directory as it stands, every fused-key call in a replay row is at call
index 0, and exactly one non-first call of any kind is lost.
"""

import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_replay(row):
    """Was this row written by a replay rather than by an arm?

    See the module docstring: `tag` is stamped by `armb.replay` and
    `armc.replay` and by nothing else.
    """
    return "tag" in row


def is_grading_record(row):
    """Is this a grade written beside the trials rather than a trial?

    `bench/results/` also holds `*_graded.jsonl`, whose rows carry the same
    `(scheme, task_id, trial)` key as the trial they grade, report an
    `outcome`, and contain no calls. They are not observations of a model.

    Every current caller happens to survive them by skipping rows with no
    `tool_calls`, which is luck rather than a rule, and the luck has already
    run out once elsewhere: `s15_analyse.py` keyed on `(scheme, task, trial)`
    instead, so the graded file -- which sorts *after* the raw one -- replaced
    every `section_g_hpath` trial with a call-less stub and the arm reported
    0/150 correct.

    Tested on the row, not the file name, for the reason the module docstring
    gives. An errored trial is not a grading record: it has no `outcome`, so it
    is still yielded and still counted as the attempt it was.
    """
    return "outcome" in row and "tool_calls" not in row


def recorded_rows(pattern="bench/results/*.jsonl", replays=False):
    """Yield `(path, row)` for every trial a model actually produced.

    Skips replay output unless `replays=True`, and always skips grading
    records. Malformed and blank lines are skipped silently, which is what
    every caller did by hand before this existed -- `results/` is
    append-and-flush and a killed run can leave a partial last line.
    """
    for path in sorted(glob.glob(os.path.join(ROOT, pattern))):
        for line in open(path, newline=""):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if is_grading_record(row):
                continue
            if not replays and is_replay(row):
                continue
            yield path, row


def provenance():
    """Which schema each results file's trials were run under.

    A second way to misread this directory, found after the first was fixed.
    The rule above stops a *replay* being counted as a fresh observation; this
    one is about what a fresh observation is evidence *for*.

    **A prefix pool inherits the schema its trials were run under.** A rate
    computed over a file describes the schema the trials in it were shown, not
    the schema that ships, and nothing in a transcript says which. It has cost
    two published numbers:

      - F-framing's tables one-turn recovery, 13/38. All 38 prefixes were
        `scheme_d` sending `row`, which `scheme_d` declares and no shipping
        schema does. Arm B's own executor accepts all 38 -- they were never
        refused in the arm at all. `armc.executor_mismatch` now catches this
        shape, because the two executors *contradict* each other.
      - Lists' `` `text` is required `` at 16/37. All 37 are `list_f` and
        `list_naive`; `list_g` draws that refusal 0 times in 400 calls, because
        L3 renamed the selector and the collision stopped existing. These are
        genuine refusals -- the models really did fail -- so no guard can catch
        it. Only the scheme label says the rate describes a retired schema.

    So this prints the label, and prints it per file, because that is the
    cheapest form the check can take. It is a reading aid, not a gate: a
    pre-adoption file is not wrong, and most of this directory is one. Paired
    contrasts within such a file are fine -- the schema is held constant across
    conditions. It is *absolute* rates, read as describing the product, that
    need the label.

        python3 bench/population.py
    """
    import collections
    from schematest import ADOPTED as _ADOPTED

    adopted = {scheme for _tool, scheme in _ADOPTED}
    per = collections.defaultdict(collections.Counter)
    for path, row in recorded_rows():
        scheme = str(row.get("scheme") or "").split(":")[0]
        per[os.path.basename(path)][scheme or "-"] += 1

    def bucket(names):
        real = names - {"-"}
        if not real:
            # Arm A edits the document directly and is shown no tool at all, so
            # it has no scheme to record. Absent here means absent by design.
            return "no schema (Arm A)"
        if real <= adopted:
            return "ADOPTED"
        return "mixed" if real & adopted else "pre-adoption"

    groups = collections.defaultdict(list)
    for name, counts in per.items():
        groups[bucket(set(counts))].append((name, counts))

    print(f"{sum(sum(c.values()) for c in per.values())} trials in "
          f"{len(per)} files, by the schema they were run under")
    print(f"adopted today: {', '.join(sorted(adopted))}\n")
    for label in ("ADOPTED", "mixed", "pre-adoption", "no schema (Arm A)"):
        rows = sorted(groups.get(label, []))
        if not rows:
            continue
        n = sum(sum(c.values()) for _f, c in rows)
        print(f"{label}  --  {len(rows)} files, {n} trials")
        for name, counts in rows:
            mix = ", ".join(f"{s}:{k}" for s, k in counts.most_common())
            print(f"    {name:44s} {mix}")
        print()
    print("An absolute rate from a pre-adoption file describes that schema, not\n"
          "the product. Paired contrasts within one are unaffected.")


if __name__ == "__main__":
    provenance()
