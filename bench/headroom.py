#!/usr/bin/env python3
"""What a pending re-measurement could possibly show, before any GPU is spent.

`bench/ceiling.py` asks whether a scheme *can* express the right answer. This
asks the question one step earlier and about the population rather than the
schema: **of the trials this re-measurement would run, how many can the change
under test touch at all?**

It exists because that question has now been answered late three times, each
time after the run rather than before it:

  - F-framing priced a table refusal at 13/38 one-turn recovery. All 38 prefixes
    were `scheme_d` sending `row`; the shipping schema does not declare `row`,
    Arm B's own executor accepts all 38, and **0 of 480** recorded table calls
    had ever drawn the refusal being priced.
  - Lists' `` `text` is required `` sat at 16/37, every one of the 37 from
    `list_f` or `list_naive`. The adopted `list_g` draws it **0 times in 400**,
    because L3 renamed the selector and the collision stopped existing.
  - F-address reconciled four addressing divergences and re-measured Arm B. The
    re-measure reproduced the baseline exactly -- because no task in the set
    pushes a model into the argument shapes where the addressing diverged.

The shape is the same every time and it is not bad luck, it is the **order the
work happens in**. A refusal message gets rewritten because some measured scheme
provoked it; the same measurement usually also produces the schema change that
stops it being provoked. So by the time the message fix is ready to re-measure,
the population that motivated it has been retired by its own fix. A re-measure
proposed against yesterday's failure is, by default, aimed at a branch nothing
takes any more.

**The arithmetic that makes this decidable.** These comparisons are paired and
scored with McNemar, where only discordant pairs carry information. If a change
can only affect the trials that reach its branch, then the discordant count `b`
is at most the reachable count `k`. `stats.mcnemar_exact(b, 0)` -- every
discordant pair falling the same way, the most favourable outcome that exists --
is `2 ** (1 - b)`, so:

    k = 5  ->  best achievable p = 0.0625     cannot reach 0.05
    k = 6  ->  best achievable p = 0.0312

**Six reachable trials is a hard floor.** Below it the run cannot produce a
significant result even if the change is perfect, and that is knowable for the
price of re-executing calls already on disk.

**The bound is one-sided for a description change, and the asymmetry is the
point.** An executor-side change (a guard, a refusal message) cannot alter a
trial that never reaches it: paired at (task, seed), non-reaching trials replay
identically, so `k` bounds the result in both directions. A *schema description*
change is in the prompt for every trial, so it can move trials that never go
near the branch -- which is what S14 measured when an unneeded extra call
destroyed the document 36% of the time. For those, `k` bounds the **gain** and
nothing bounds the **loss**. A description tune with k=1 is not merely
underpowered; it is an uncapped downside bought for a capped upside.

What this does not do, stated so it is a choice and not an oversight. It does
not say a re-measure is worthless -- a bounded, non-significant result is still
a result, and "the guards cost nothing" was worth having. It says what the run
can and cannot return, so that is decided before the GPU rather than in the
write-up. And it is retrospective by construction: it can only see branches that
recorded calls reach, so a candidate needing a *new instrument* -- new tasks, a
new tool, a new contrast -- is reported as out of scope rather than as dead.

**The counting is checked against a published column rather than asserted.**
The S8 candidate finds 20 guard-tripping trials in `section_naive` and 20 in
`section_p`; re-grading those same outputs against the guarded executor moved
`op_error` by +21 and +20 (`armb_sections_*_s6guard_graded.jsonl`). S8's table
prints +20 and +17 because its v2 column also carries S10's whitespace fix,
which moves three `section_p` trials back out of `op_error`. A candidate whose
count cannot be tied to something already published should be treated as
unvalidated.

    python3 bench/headroom.py
"""

import collections
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import incise_ops  # noqa: E402
import population  # noqa: E402
from schematest import ADOPTED  # noqa: E402
from stats import mcnemar_exact  # noqa: E402

ADOPTED_SCHEMES = {scheme for _tool, scheme in ADOPTED}

# The floor derived in the module docstring, computed rather than asserted so it
# tracks `stats.mcnemar_exact` if that ever changes.
FLOOR = next(k for k in range(1, 64) if mcnemar_exact(k, 0) < 0.05)


def load_tasks():
    """Every task by id. Ids are unique across the five task files."""
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "bench/tasks/*.json"))):
        doc = json.load(open(path, newline=""))
        for task in (doc["tasks"] if isinstance(doc, dict) else doc):
            out[task["id"]] = task
    return out


# Every tool name any scheme has ever published. A recorded call naming anything
# else belongs to an arm with its own executor -- see `replay`.
PUBLISHED_TOOLS = {t["name"] for tools in armb.SCHEMES.values() for t in tools}


def disposition(name, raw_args):
    """What `replay` would do with one recorded call, as a decision on its own.

    `{"route": "read"|"edit", "op":…, "args":…, "op_args":…}`, or
    `{"route": "skip", "reason": …}`. Split out of `replay`'s loop, unchanged,
    so `replaycheck.py` can ask **this module** what it executes rather than
    transcribing the rules into a third copy -- which would re-create exactly
    the drift that check exists to catch. The reasons below are the four
    paragraphs of `replay`'s docstring, one each.

    `normalize` is deliberately not wrapped. If it raises, `replay` crashes
    today, and a checker that quietly absorbed that would hide a real gap
    between this module and `regrade_snapshot.py`, which records the exception
    and carries on.
    """
    if name not in PUBLISHED_TOOLS:
        return {"route": "skip", "reason": "tool no scheme publishes"}
    try:
        args = json.loads(raw_args or "{}")
    except ValueError:
        return {"route": "skip", "reason": "arguments did not parse"}
    if not isinstance(args, dict):
        return {"route": "skip", "reason": "arguments are not an object"}
    op, op_args = armb.normalize(name, args)
    # Keyed on the *op*, where `regrade_snapshot.disposition` keys on the tool
    # name. The two agree only because `normalize` returns the tool name
    # unchanged for a read; `replaycheck.py` asserts that rather than trusting
    # it, since the day it stops being true these two modules diverge silently.
    return {"route": "read" if op in armb.READS else "edit",
            "op": op, "args": args, "op_args": op_args}


def replay(row, task):
    """Yield `(op, args, error)` for each call, executed in sequence.

    In sequence because the arm is: call 2 sees the document call 1 left, so a
    refusal that only appears on a partly-edited document is reachable only if
    the earlier calls are applied. Executing each call against the pristine
    fixture would undercount exactly the multi-turn branches.

    Read ops are executed through `armb.read_call`, not through `apply_op`.
    `table-get` and `frontmatter-get` are off `apply_op` on purpose
    (`armb.READS`), and feeding them to it yields `unknown operation`, which is
    this module's own artifact. They used to be skipped instead, yielding
    `error=None` so that predicates had to judge on the arguments -- an
    undercount that was safe only while no candidate's branch lived behind a
    read. F-remedy's does, and it is the sharpest instance of it: the rename
    refusal is drawn by `table_get` 10 times in 10 on `get-repeated-name`, and
    the survey reported **UNTESTED at k=0** with that pool already on disk.
    `read_call` returns the refusal a model actually read, so it is counted now.
    A read leaves `content` alone, which is what makes executing it in sequence
    safe.

    A tool no scheme publishes is skipped outright, for the same reason one step
    further on. Arm A's `patch` is executed by `arma.py` and never goes near
    `apply_op`; replaying it here manufactures `unknown operation "patch"` 380
    times, which is a sentence no model in that arm was ever shown. It went
    unnoticed while every predicate happened to match a *specific* refusal --
    F-action's matches the one the artifact wears, and counted 260 Arm A trials
    as reaching a branch none of them can reach.

    The test is membership in `PUBLISHED_TOOLS`, not "has an `action` enum".
    Writing it the second way silently dropped `scheme_a`, whose three tools are
    one op each and publish no `action` at all, and turned B2's CLOSED verdict
    into UNTESTED by deleting the thirteen trials that earned it.

    Arguments that are not a JSON object are skipped for the third instance of
    the same reason. `armb.run_trial` decodes inside the `try` that wraps the
    call, so the model was handed the decode error and no op ran; substituting
    `{}` here invents a `section-None` and with it a refusal nobody read. Two of
    F-action's hits were truncated `replace-body` payloads, which is a token
    limit and not an `action` fault.
    """
    content = open(os.path.join(ROOT, task["fixture"]), newline="").read()
    for call in row.get("tool_calls") or []:
        fn = call.get("function", {})
        d = disposition(fn.get("name"), fn.get("arguments"))
        if d["route"] == "skip":
            continue
        op, args = d["op"], d["args"]
        if d["route"] == "read":
            # A read cannot change the document, so `content` is not rebound.
            _report, _rendered, err = armb.read_call(content, fn["name"], args)
            yield op, args, err
            continue
        after, err = incise_ops.apply_op(content, op, d["op_args"])
        yield op, args, err
        if err is None and after is not None:
            content = after


# --- the candidates -------------------------------------------------------
#
# One entry per open re-measurement in FINDINGS. `where` decides which recorded
# trials the re-measure would run over; `reaches` decides which of those the
# change could touch. Adding an entry is how a proposed run gets priced.

GLOBBY = set("*?[]")


def _b2_selector(op, args, err):
    return bool(err) and err.startswith("no row matches all of")


def _s8_guards(op, args, err):
    return bool(err) and (
        "already has a body, and `replace-body`" in err
        or "cannot create a section, and you passed a heading" in err
    )


def _filter_glob(op, args, err):
    filt = args.get("filter")
    return isinstance(filt, dict) and any(
        isinstance(v, str) and (set(v) & GLOBBY) for v in filt.values()
    )


# Every refusal `resolve_table` can return, i.e. every way the `table` argument
# can miscarry. Listed in full rather than trimmed to the two the pools actually
# contain, because the predicate is a claim about the argument and not about
# this directory -- a pool that draws `ambiguous:` tomorrow should raise `k`
# without anyone remembering to come back here.
TABLE_ADDRESS_REFUSALS = (
    "table address required",
    "no table under heading ",
    "no table with ordinal ",
    "ambiguous: ",
    "`table.ordinal` must be",
)


# The wart's two hypothesized harms, which are different failures and are both
# counted here.
#
# `op != "table_get"` is the misroute. A read is normalized to the *tool* name
# (`armb.READS` is keyed that way), so a `table-` op arriving on a `table-get`
# task means the model reached for `table_edit` to answer a question -- which is
# what a read tool whose address says "Which table to **edit**" is accused of
# inviting. The reverse misroute, `table_get` on an edit task, is not visible to
# a candidate whose `where` is the read family; it was counted separately and is
# 0 of 60 (FINDINGS, F-wart).
#
# The other harm is the argument itself: the phrase is on `table`, so if it
# misleads within the tool it does so by producing a `table` that does not
# resolve.
def _table_address_lost(op, args, err):
    if op != "table_get":
        return op.startswith("table-")
    return bool(err) and err.startswith(TABLE_ADDRESS_REFUSALS)


# The two refusals F-remedy found whose only named remedy is a document change
# no shipping tool can make. Matched on the remedy line rather than on the
# diagnosis, because it is the remedy that is the defect: both diagnoses are
# correct and would survive a rewrite.
#
# `replay` executes reads now, so what this counts is the **residual**: the
# `filter` call site was rewritten and measured (F-remedy, 0/10 -> 10/10), and
# its refusal no longer contains either of these strings, so the ten
# `get-repeated-name` calls that made this POWERED at k=10 are correctly gone
# from the count. What is left is `where`, keyed `values`, `column` and the
# three section body ops -- and `column`'s is not a defect at all, since nothing
# addresses a repeated column and renaming really is the only way out. A k that
# fell to 0 here means the measured half shipped, not that the survey lost sight
# of it.
UNPERFORMABLE = (
    "Rename one of them in the document, then retry.",
    "Normalize the section's line endings first, then retry.",
)


# The width refusal, matched on its diagnosis. `table-realign` measures column
# width in characters, so it refuses any table holding a cell it cannot measure
# -- CJK, fullwidth forms, combining marks, emoji -- rather than re-padding it
# to a count that is ragged on screen.
#
# Matched on the diagnosis and not on the remedy, which is the opposite of
# `UNPERFORMABLE` above and for the opposite reason: this refusal's last line
# is performable ("Add, update and delete still work on this table"), and the
# defect, if there is one, is upstream of it -- incise cannot measure the width,
# so there is no narrowing available and the whole op is declined.
REALIGN_WIDTH = "does not occupy one display column"


def _realign_width_refused(op, args, err):
    if op != "table-realign":
        return False
    return bool(err) and REALIGN_WIDTH in err


def _unperformable_remedy(op, args, err):
    return bool(err) and any(r in err for r in UNPERFORMABLE)


# F-action's branch: the core's `unknown operation` sentence, which a tool-armed
# model reaches by sending an `action` the tool did not publish -- in practice
# always a fused JSON key, so the op name arrives as `list-None`. Matched on the
# sentence rather than on the shape of the arguments, because the sentence is
# what the condition would replace and a model that draws it is the population
# `CHECK_ACTION` would serve, however it got there.
#
# `replay` skips reads, which is what makes this predicate safe: `armb.READS`
# are off `apply_op` and feeding them to it produces this same sentence as a
# module artifact. Every hit below is a refusal some model actually read.
def _unknown_operation(op, args, err):
    return bool(err) and err.startswith("unknown operation")


# F-anchor's branch: `section_edit` called with no address at all -- `section`
# omitted, or sent as an object carrying neither `heading` nor `path`. Matched on
# the refusal rather than on the arguments so that the shapes which *do* resolve
# (a bare string, `{"path": ...}`) cannot be miscounted as defects; both were
# checked against `apply_op` and both work.
#
# This is the first candidate where "adopted" and "shipping" come apart, and the
# verdict below should be read with that in mind. `ADOPTED_SCHEMES` is derived
# from `schematest.ADOPTED`, which pairs each tool with the *single-tool* scheme
# whose text it ships -- and every one of those schemes publishes one tool, while
# `schema.rs` publishes five. The defect does not occur under one tool (0 of 150
# `compose_solo` trials) and occurs under five (8 of 150 `compose_5`), so `k`
# over the adopted schemes is 0 and the honest reading of that zero is "the
# single-tool condition cannot reach it", not "nothing reaches it". The composed
# rows in the per-scheme table below are where the 25 trials are, and
# `compose_5` is the condition the product actually ships.
def _no_section_address(op, args, err):
    return bool(err) and err.startswith("`section` is required")



CANDIDATES = [
    {
        "name": "B2: a description warning against invented selectors",
        "bullet": "Re-measure B2 with the improved error text in the first turn",
        "side": "description",
        "where": lambda t: t["family"].startswith("table")
                 and not t["family"].startswith("table-get"),
        "reaches": _b2_selector,
    },
    {
        "name": "S8: the two guards, live instead of re-graded",
        "bullet": "Sections: re-run `section_naive` and `section_p` against the "
                  "guarded executor",
        "side": "executor",
        "where": lambda t: t["family"].startswith("section"),
        "reaches": _s8_guards,
    },
    {
        "name": "F-read: say in the description that `filter` is literal",
        "bullet": "A `filter` value is matched literally, and one trial in 60 "
                  "assumed globs",
        "side": "description",
        "where": lambda t: t["family"].startswith("table-get"),
        "reaches": _filter_glob,
    },
    {
        "name": "F-wart: `table_get`'s address says \"Which table to edit\"",
        "bullet": "Reword the copy-paste from `table_edit` that survives in a "
                  "read tool",
        # Description-side, so `k` bounds the gain alone -- and here the bound
        # tightens further than the survey can print. All three reachable trials
        # are graded `correct`: the model drew the refusal and recovered inside
        # its turn budget. A trial that already wins cannot be won, so the gain
        # is 0 against an unbounded loss. See FINDINGS, F-wart.
        "side": "description",
        "where": lambda t: t["family"].startswith("table-get"),
        "reaches": _table_address_lost,
    },
    {
        "name": "F-remedy: a refusal whose remedy no shipping tool can perform",
        "bullet": "Reword the two refusals that tell the model to change the "
                  "document rather than the call",
        # Executor-side: the sentence is in the refusal, not in the schema, so
        # a trial that never draws it replays identically and `k` bounds the
        # result in both directions rather than the gain alone.
        "side": "executor",
        "where": lambda t: True,
        "reaches": _unperformable_remedy,
        # F-provoke. The table half had an instrument already
        # (`tables_read_remedy.json`, F-remedy); the section half was called
        # unbuildable there, on the grounds that a mixed-ending append has a
        # ceiling of zero. It does not: `section-delete` is the one body op
        # that does not call `_section_eol`, so delete-then-re-insert performs
        # the remedy in two calls and `ceiling.py` is 3/3.
        "instrument": ("bench/tasks/tables_read_remedy.json (3 tasks, ceiling "
                       "3/3) and bench/tasks/sections_mixed_endings.json "
                       "(3 tasks, ceiling 3/3)"),
    },
    {
        "name": "F-action: the `unknown operation` sentence, for a tool caller",
        "bullet": "CLOSED for the product -- F-valid. The five shipped tools "
                  "publish fifteen actions reaching all fifteen ops, so every "
                  "name is reachable as served, and `schematest.py` now "
                  "asserts it. The count below is a property of the schemes "
                  "these pools ran under, which published two to four of them",
        # Executor-side, and the classification is the point rather than a
        # formality. `CHECK_ACTION` changes `normalize`, which runs after the
        # model has spoken: a trial whose calls all carry a good `action`
        # replays byte-for-byte either way, so `k` bounds the loss as well as
        # the gain. Were this instead fixed by adding a sentence to the tool
        # description, it would be one-sided and this survey could not bound it
        # at all.
        "side": "executor",
        "where": lambda t: True,
        "reaches": _unknown_operation,
    },
    {
        "name": "F-anchor: `section_edit` called with no address at all",
        "bullet": "The composition residue is `section_edit` losing its address, "
                  "and it is the one tool whose description never names it",
        # Description-side, so one-sided: the sentence would be in the prompt of
        # every trial, `k` bounds the gain and nothing bounds the loss on the
        # other 142. See the comment on `_no_section_address` for why the adopted
        # count is 0 and why that is not the whole answer here.
        "side": "description",
        "where": lambda t: t["family"].startswith("section"),
        "reaches": _no_section_address,
    },
    {
        "name": "F-width: the realign refusal, now that a model can draw it",
        "bullet": "`table-realign` refuses rather than narrowing on any width "
                  "it cannot measure",
        # Executor-side: the sentence is a refusal, so a trial that never draws
        # it replays identically and `k` bounds the result in both directions.
        #
        # This entry exists because the item changed class without changing
        # text. Until F-realign the refusal was operator-facing -- `table_edit`
        # published three actions and `realign` was not one of them, so its only
        # caller was the CLI. Publishing the fourth action made the same bytes
        # product text under REQUIREMENTS §5.3, on a path no arm has measured.
        "side": "executor",
        "where": lambda t: True,
        "reaches": _realign_width_refused,
        # F-provoke. Unlike every other instrument in this file, this one
        # cannot pass the pre-flight gate and is not meant to: `grade_one`
        # grades an unchanged document `op_error`, so a task whose correct
        # outcome is a refusal can never grade `correct` and `ceiling.py`
        # returns 1/3 by construction. The endpoint is the failure class, as
        # it was for F-realign's control cell.
        "instrument": ("bench/tasks/tables_realign_width.json (3 tasks; "
                       "ceiling 1/3 by construction -- the endpoint is the "
                       "failure class, not the correct-rate)"),
    },
]

# Open items this module deliberately cannot price, named so their absence is
# not read as a clean bill. Each needs an instrument that does not exist, so
# there is no recorded call to count: the question is not "does anything reach
# this branch" but "what would a new contrast show".
#
# The third entry is the useful one to read first. "Nothing to count" is not
# the same as "undecidable", and treating them as the same is how this module
# would waste an hour of GPU on a question a corpus file already answers.
OUT_OF_SCOPE = [
    ("Sections: `children` on a narrower tool",
     "a new tool and a new scheme. S13's tax is measured; whether narrowing "
     "removes it is a fresh arm, not a branch anything reaches today. RUN -- "
     "F-narrow, 450 trials. Narrowing removed none of it, and the tax itself "
     "turned out to be 4-5 points rather than S13's twelve, below this "
     "module's own floor. Kept here because the verdict was right: no recorded "
     "call could have told anyone that."),
    ("What the JSON framing damages is not what was predicted",
     "needs n, not reach. The strata are already discordant (7-2, 15-8, 6-7); "
     "separating the wrapper from the escaping needs a designed contrast."),
    ("Whether the plugin's `md_rows` or the measured `table_get` should ship",
     "answered, and by the other module. There were no recorded `md_rows` calls "
     "to count -- it ships in the plugin and has never been in an arm -- so "
     "this survey had nothing to survey, which is the `OUT_OF_SCOPE` verdict "
     "and was also useless. What settled it is `ceiling.py`'s question asked of "
     "a schema rather than a scheme: `md_rows` took `table` as a plain string, "
     "`tables_read.json`'s `get-ordinal-table` needs an ordinal, and "
     "`table_read_g` answers it 10/10. Ten discordant pairs are forced, so "
     "p <= 0.0386 before a model is asked anything. The pairing is worth "
     "keeping in view: this module bounds what a re-measurement can *return*, "
     "and `ceiling.py` bounds what a schema can *express* -- a candidate that "
     "needs a new instrument here may still be decidable there, for free."),
    ("Whether the five-tool shipping set costs anything",
     "answered, and never by this survey. A composition is in the prompt of "
     "every trial, so k = n -- but no recorded call reached a multi-tool prompt, "
     "so there was nothing here to count. `armb.py --scheme compose_5` was the "
     "instrument and it ran: five tools against the three that shipped is 6-3 "
     "of 310, p = 0.51, and one tool against three is 11-1, p = 0.0063. The "
     "entry stays because the shape recurs -- a sixth tool would put this "
     "survey back at nothing to count, and the answer would again be an arm."),
]


def survey():
    tasks = load_tasks()
    print(f"floor: {FLOOR} discordant pairs, below which no paired result can "
          f"reach p<0.05\n(mcnemar_exact({FLOOR - 1}, 0) = "
          f"{mcnemar_exact(FLOOR - 1, 0):.4f}, "
          f"mcnemar_exact({FLOOR}, 0) = {mcnemar_exact(FLOOR, 0):.4f})")

    for cand in CANDIDATES:
        trials = collections.Counter()
        reach_calls = collections.Counter()
        reach_trials = collections.defaultdict(set)
        ran_task = collections.defaultdict(collections.Counter)
        for _path, row in population.recorded_rows():
            task = tasks.get(row.get("task_id"))
            if not task or not cand["where"](task):
                continue
            scheme = str(row.get("scheme") or "-").split(":")[0]
            trials[scheme] += 1
            ran_task[scheme][row["task_id"]] += 1
            for op, args, err in replay(row, task):
                if cand["reaches"](op, args, err):
                    reach_calls[scheme] += 1
                    reach_trials[scheme].add((row["task_id"], row.get("trial")))

        print(f"\n{'=' * 74}\n{cand['name']}\n  open item: {cand['bullet']}"
              f"\n  {cand['side']}-side change")
        print(f"  {'scheme':22s} {'adopted':>8s} {'trials':>7s} "
              f"{'calls':>6s} {'trials':>7s}")
        for scheme in sorted(trials, key=lambda s: (-reach_calls[s], s)):
            mark = "yes" if scheme in ADOPTED_SCHEMES else "--"
            # Arm A is shown no tool at all, so it records no scheme. Absent
            # here means absent by design, as `population.provenance` says.
            label = "(Arm A)" if scheme == "-" else scheme
            print(f"  {label:22s} {mark:>8s} {trials[scheme]:7d} "
                  f"{reach_calls[scheme]:6d} {len(reach_trials[scheme]):7d}")

        live = {s: n for s, n in trials.items() if s in ADOPTED_SCHEMES}
        k = sum(len(reach_trials[s]) for s in live)
        n = sum(live.values())
        retired = sum(len(v) for s, v in reach_trials.items() if s not in live)
        # `ADOPTED_SCHEMES` comes from `schematest.ADOPTED`, which pairs each
        # tool with the single-tool scheme whose text it ships. `schema.rs`
        # publishes five tools at once, and the only schemes that reproduce that
        # condition are the `compose_*` arms -- which are therefore not adopted
        # and not retired either. Counting them with the dead schemes would print
        # a sentence that is false of the product (F-anchor), so they are split
        # out and named.
        composed = sum(len(v) for s, v in reach_trials.items()
                       if s not in live and s.startswith("compose_"))

        # Which tasks ever provoked the branch, under any scheme, and how often
        # the adopted scheme was run on those same tasks. This separates the two
        # ways `k` can be 0, which call for opposite responses: a task set that
        # never goes near the branch is an instrument to build, and a task set
        # that goes there and no longer fails is a question already answered.
        provoking = {t for s, v in reach_trials.items() for t, _tr in v}
        covered = sum(ran_task[s][t] for s in live for t in provoking)

        print(f"\n  over the adopted scheme(s) {sorted(live) or '-- none --'}: "
              f"k={k} reachable of n={n}")
        if retired - composed:
            print(f"  {retired - composed} further reachable trials exist, all "
                  f"under schemes that do not ship -- a rate over them describes "
                  f"the schema they were run under, not the product.")
        if composed:
            print(f"  {composed} more are under the `compose_*` arms, which are "
                  f"not adopted schemes but ARE the five-tool condition "
                  f"`schema.rs` ships. `k` above does not include them.")
        if provoking:
            print(f"  provoking tasks {sorted(provoking)}: run "
                  f"{covered} times by the adopted scheme(s)")
        print("  " + verdict(cand, k, n, covered, provoking))

    print(f"\n{'=' * 74}\nnot priced here, and why")
    for name, why in OUT_OF_SCOPE:
        print(f"  {name}\n    {why}")


def verdict(cand, k, n, covered, provoking):
    """One sentence on what the run could return. Deliberately blunt."""
    if n == 0:
        return ("DEAD: no adopted scheme has ever been run on this family, so "
                "there is no shipping population to re-measure. Whether the "
                "tool should ship is the prior question.")
    if k == 0 and not covered:
        # Two different states print the same `k = 0`, and conflating them is
        # how this module told F-width and F-remedy to "build a task set" that
        # by then existed (F-provoke). `provoking` is derived from recorded
        # trials, so it stays empty until a pool runs, and it cannot see an
        # instrument that has been built and not yet spent GPU on. The
        # candidate has to say so itself.
        if cand.get("instrument"):
            return (f"UNRUN: no adopted trial reaches the branch, but the "
                    f"instrument exists -- {cand['instrument']}. This is GPU "
                    f"to spend, not a task set to build. `k` stays 0 until it "
                    f"is spent, and no re-survey will move it.")
        return (f"UNTESTED: no adopted trial reaches the branch, and the "
                f"adopted scheme was never run on the {len(provoking)} task(s) "
                f"that provoke it. This is a task set to build, not a result. "
                f"It is F-address's failure, not F-framing's.")
    if k == 0:
        return (f"CLOSED: the adopted scheme ran the provoking task(s) "
                f"{covered} times and reached the branch zero times. The "
                f"schema change already removed the failure; there is nothing "
                f"left for a message fix to move.")
    best = mcnemar_exact(k, 0)
    label = "UNDERPOWERED" if k < FLOOR else "POWERED"
    out = (f"{label}: k={k}, best achievable p={best:.4f} "
           f"(every discordant pair falling the same way)")
    if k < FLOOR:
        out += (f" -- below the floor of {FLOOR}, so a significant result is "
                f"unavailable at any effect size.")
    else:
        out += " -- reaches significance only if the effect is near-total."
    if cand["side"] == "description":
        out += (" One-sided: this bounds the gain only, since a description "
                "reaches every trial and can move ones that never had the "
                "failure.")
    return out


if __name__ == "__main__":
    survey()
