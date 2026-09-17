#!/usr/bin/env python3
"""Arm C -- Arm B's tasks and seeds, executed by the real binary on real files.

Every rate in FINDINGS.md was measured with `incise_ops.apply_op` called
in-process, on a string. Arm B reads a fixture from disk and never writes one.
The shipping artifact is a Rust core behind a binary that does, and nothing has
measured whether the numbers survive the port and the process boundary.
REQUIREMENTS.md:1229-1250 is explicit about the direction of that test: Arm B's
rates are the bar the Rust must match, not beat -- a regression against them is
a bug in the port.

So this is Arm B with one line replaced. `armb.run_trial:1041`:

    after, err = apply_op(doc, op, op_args)          # in-memory string

becomes `execute()` below: argv, a subprocess, a real file, an exit code.
Everything else is held fixed by *importing* it rather than copying it --
the schemes, the system prompts, the user turn, the tool-name -> op mapping,
the model client and the grading predicates all come from `armb`, `runner` and
`grade`. A transcribed copy of any of them would make this a comparison between
two harnesses.

**The sandbox.** `armb.build_payload` renders the user turn with
`task["fixture"]` as the path label, and the model copies that string into
`path`. Handing the model a temp path would change the prompt bytes and confound
the arm. So the fixture is mirrored into a temp root at its *repo-relative* path
-- $TMP/corpus/tables/aligned.md -- and the binary is invoked with `cwd` set to
that root. The model emits `corpus/tables/aligned.md` exactly as in Arm B, the
prompt is byte-identical, and the write lands in the sandbox. The corpus is
frozen (FINDINGS quotes per-file results against those files); this protects it
by construction rather than by care.

**Two outcome classes Arm B could not produce**, both because Arm B had no file:

  usage_error  exit 2. A wrong or missing `path` was *inert* in Arm B -- the
               document was already in memory, so the argument was never read.
               Here it is a real failure, and folding it into `op_error` would
               report a whole failure class as if it were a refusal the model
               can re-call its way out of.
  escaped      the call named a path outside the sandbox. The binary is not
               invoked. This is harness safety, not pre-validation: it cannot
               fire on an in-bounds call, so no refusal sentence moves. It has
               its own class so that "it never happened" is a measurement rather
               than an assumption.

**What a successful call sends back.** On an edit the CLI returns
`describe_change` -- or `describe_frontmatter_change`, dispatched on the op name
the way `armb.tool_result` dispatches on the family. `armb.tool_result` returns
the renderer summary for tables and lists, because `describe_change` reads
headings and would describe the wrong structure. That divergence is inert at
`--turns 1`, which is the adopted configuration for those two families -- the
result is computed and never sent. Rather than leave that as a silent
assumption, `--turns > 1` is refused for them. It is an edit-only divergence: a
read's tool result is the renderer's string in both arms, so read tasks are
excluded from that guard rather than caught by it.

**A read runs here too, and the path is not `execute`.** §6.1 keeps the reads
out of `OPS`, so `table-get` has no subcommand of its own: it is `incise rows`,
and `execute_read` is what knows that. `rows --json` returns the rendered text
*and* the structured rows from one invocation, which is what lets this arm grade
a read the way Arm B does -- against `TableRows`, never against the renderer's
string. `frontmatter-get` is `incise keys` on the same terms, its structure in
the `frontmatter` field; it used to be refused here for want of a Rust port, and
the port is what removed the refusal rather than an argument about it.

    PATH=$HOME/.cargo/bin:$PATH cargo build --release
    python3 bench/ceiling.py --arm c --tasks bench/tasks/tables.json --schemes scheme_f
    python3 bench/armc.py --tasks bench/tasks/tables.json --scheme scheme_f \\
        --out bench/results/armc_tables.jsonl
    python3 bench/armc.py --tasks bench/tasks/tables.json --scheme scheme_f \\
        --out bench/results/armc_tables.jsonl --grade

`--replay` re-runs only what follows a first call that failed, varying the
message the model was given to recover from. See `replay`.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))

import armb  # noqa: E402
import incise_ops  # noqa: E402
from grade import check_result  # noqa: E402
from runner import call, record  # noqa: E402
from schematest import find_binary  # noqa: E402

# The CLI's codes (`crates/incise-cli/src/out.rs:28-31`), plus one of ours.
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_STALE = 3
EXIT_ESCAPED = -1        # never the binary's; see `execute`

# Filled by `grade_one` when a regrade does not reproduce the hash the run
# recorded. Read by `grade`, which reports it -- a mismatch means the process
# boundary is nondeterministic, which is precisely what this arm exists to
# detect, and it must not be discoverable only by reading the JSONL.
HASH_MISMATCHES = []


# --------------------------------------------------------------------------
# the sandbox
# --------------------------------------------------------------------------

class Sandbox:
    """A temp root holding one fixture at its repo-relative path.

    Repo-relative and not flattened, because the path the model emits is the
    path the prompt showed it, and the prompt is Arm B's byte for byte.
    """

    def __init__(self, task):
        self.rel = task["fixture"]
        self.root = None

    def __enter__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="armc-"))
        dest = os.path.join(self.root, self.rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, self.rel), dest)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def read(self):
        """The fixture as it now stands. The document every grade is made on."""
        with open(os.path.join(self.root, self.rel)) as fh:
            return fh.read()

    def sha256(self):
        """The same hash `incise hash` prints -- sha256 over the file's bytes."""
        with open(os.path.join(self.root, self.rel), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()


def execute(binary, sb, op, op_args):
    """Run one op through the real binary. Returns (description, error, exit).

    The whole argument object goes to `--args` unchanged, `path` and `action`
    included. The core ignores both, and they are what the 5674 graded calls
    behind FINDINGS contained, so they stay -- exactly as
    `plugins/hermes/__init__.py` keeps them.

    Nothing is checked before the binary sees it. The order arguments are
    checked in is part of incise's contract (§5.3): a front end that rejected
    one early would answer the same call with a different sentence, and this arm
    exists to find out whether the sentences still match. The single exception
    is the path escape guard, which decides which *file* to open -- one of the
    two things the core cannot see.
    """
    argv, refused = _argv(binary, sb, op, op_args)
    if refused is not None:
        return None, refused, EXIT_ESCAPED
    out, err, code = _run(argv, sb)
    return (out.get("description") if out else None), err, code


# Which subcommand answers a read op, and which envelope field carries its
# structure. A read is not `incise <op>`: `table-get` is `incise rows`, with its
# own arguments, because §6.1 keeps the reads out of `OPS` -- they return text
# *about* a document rather than a document, and adding them would move the
# `unknown operation` sentence §1.2 measured.
#
# The field is named here rather than assumed to be `rows` because the two reads
# return different structures: `TableRows` and `FrontState`. A single hardcoded
# key would have silently handed the grader `None` for every frontmatter read,
# which is the shape of a bug that looks like a model failure.
READ_SUBCOMMANDS = {"table-get": ("rows", "rows"),
                    "frontmatter-get": ("keys", "frontmatter")}


def execute_read(binary, sb, name, args):
    """One read tool call through the binary -> (report, rendered, error, exit).

    `armb.read_call`'s shape with the exit code the process boundary makes
    available, and the same two forms for the same reason: the rendered string
    is what the model is handed back, the structure is what
    `grade.check_table_read_result` grades. Parsing the structure back out of the
    rendered table would make every read grade a golden for the renderer, which
    is precisely what that function exists to avoid.

    Both come from one invocation. `rows --json` and `keys --json` each return
    `text` and the structure together (`crates/incise-cli/src/out.rs`), so the
    two cannot describe different reads of the file -- which a second subprocess
    could, since this is the arm whose whole subject is what happens on disk
    between calls.

    The vocabulary mapping is `armb.read_args`, imported rather than
    transcribed, for the reason the module docstring gives about every other
    piece of Arm B this file reuses.
    """
    op, op_args = armb.read_args(name, args)
    entry = READ_SUBCOMMANDS.get(op)
    if entry is None:
        raise SystemExit(f"{op}: no subcommand in this binary; see "
                         f"`armc.READ_SUBCOMMANDS`.")
    sub, field = entry
    argv, refused = _argv(binary, sb, sub, op_args)
    if refused is not None:
        return None, None, refused, EXIT_ESCAPED
    out, err, code = _run(argv, sb)
    if out is None:
        return None, None, err, code
    return out.get(field), out.get("text"), None, code


def _argv(binary, sb, subcommand, op_args):
    """`(argv, None)`, or `(None, refusal)` if `path` leaves the sandbox.

    The escape guard is harness safety, not pre-validation: it cannot fire on an
    in-bounds call, so no refusal sentence moves. A call with no usable `path` is
    invoked without the positional -- the CLI answers that itself, naming `path`,
    honouring `--json`, still exit 2, rather than letting clap answer it.
    `crates/incise-cli/src/main.rs`'s `path_of` says why, and `replay` is what
    measured it.
    """
    path = op_args.get("path")
    argv = [binary, subcommand]
    if isinstance(path, str) and path:
        target = os.path.realpath(os.path.join(sb.root, path))
        if target != sb.root and not target.startswith(sb.root + os.sep):
            return None, f"refused: {path!r} resolves outside the sandbox"
        argv.append(path)
    return argv + ["--args", json.dumps(op_args), "--json"], None


def _run(argv, sb):
    """`(payload, error, exit)` -- the parsed `--json` object, or the refusal."""
    p = subprocess.run(argv, cwd=sb.root, capture_output=True, text=True)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        # Anything that still leaves on stderr as prose -- clap's own errors for
        # a malformed flag, a panic. Reported with the code the process actually
        # returned, never a guess.
        msg = (p.stderr or p.stdout).strip() or "no output"
        return None, msg, p.returncode
    if out.get("ok"):
        return out, None, p.returncode
    return None, out.get("error") or "refused with no message", p.returncode


# --------------------------------------------------------------------------
# how a failure reaches the model
# --------------------------------------------------------------------------

# What the harness does to a refusal on its way into the tool message. Arm A,
# Arm B and Arm C all send `"Error: " + message`; the Hermes plugin does not,
# and `plugins/hermes/README.md:134-152` records both divergences as unmeasured.
# They are reproduced *here* rather than by changing the plugin, because the
# JSON wrapper and the cap are the host's, not incise's: a plugin that routed
# around either would be measuring a program nobody runs.
#
# These three are a *chain*, not three alternatives, which is how the host
# composes them: `tool_error` caps the body and then JSON-encodes the result, so
# there is no configuration anywhere that truncates a bare string. `cap` is
# therefore `json` plus the bound, and on every refusal the project has recorded
# but one, the two are byte-identical -- see `CAP` below.
FRAMINGS = ("plain", "json", "cap")

# `tools.registry._MAX_TOOL_ERROR_CHARS`, enforced outside this repo, and
# transcribed here with its marker so `cap` is the host's cut rather than a bare
# slice. `_bound_error_text` returns the text unchanged at or below the cap, and
# otherwise `text[:2048] + "… [truncated]"` -- applied to the *message*, before
# the JSON encoding and with no `"Error: "` prefix in front of it.
#
# The refusal this exists for is real and reproducible: `table-add-row` with a
# `table` that matches nothing, on `corpus/documents/api-reference.md`, is 2200
# characters and loses its last 152 -- four entries off the end of `Headings
# with tables:`. Note what does *not* go. §5.3's repair line is `Near matches:`,
# which is line 1 and survives whole; what the cap removes is the tail of a list
# whose opening still reads as exhaustive.
#
# What it is not is a thing that happens. Re-executing the first call of every
# trial in `bench/results/` gives 726 refusals, and **one** crosses the cap, by
# 16 characters. The divergence is real, the population is 1/726, and no
# condition can be sized on it. See FINDINGS F-framing.
CAP = 2048
TRUNCATION_MARKER = "… [truncated]"


def bound(err):
    """`tools.registry._bound_error_text`, transcribed.

    Transcription rather than an import: `bench/` runs on the stdlib and may not
    have hermes-agent installed, and `plugins/hermes/test_plugin.py:230-242`
    already asserts the real one against the real threshold. This copy is
    checked against that behaviour in `test_framings`.
    """
    return err if len(err) <= CAP else err[:CAP] + TRUNCATION_MARKER


def frame(framing, err):
    """The bytes the model reads in place of a refusal.

    `plain` must be byte-identical to what `run_trial` has always sent, or the
    replay's baseline is not the arm's baseline.

    `ensure_ascii=False` because that is what `tool_error` passes. It changes
    nothing on this corpus -- none of the 726 recorded refusals contains a
    non-ASCII character -- but a framing condition that is a transcription of a
    host is only worth running while it is an accurate one.
    """
    if framing == "plain":
        return "Error: " + err
    if framing == "json":
        return json.dumps({"error": err}, ensure_ascii=False)
    if framing == "cap":
        return json.dumps({"error": bound(err)}, ensure_ascii=False)
    raise SystemExit(f"unknown framing {framing!r}; valid: {', '.join(FRAMINGS)}")


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

def _check_supported(tasks, turns):
    """What this arm will and will not run, and why. See the module docstring.

    One guard now, where there were two. The turns guard is about a divergence
    between the two arms' *edit* results and says so; it has nothing to say
    about a read, whose tool result is the renderer's string in both arms --
    `armb.read_call` renders it in-process and `incise rows --json` /
    `incise keys --json` return the same bytes in their `text` field. Leaving
    reads refused for the edit reason would record a false statement about the
    port as if it were a measured constraint. So read tasks are excluded from it
    rather than caught by it, which also matters because "does the model reach
    for the read tool at all" is a multi-turn question by definition.

    The second guard is gone with the thing it described. It refused
    `frontmatter-get` because the family had no Rust port at all, so there was
    no subcommand to name; the port landed, `READ_SUBCOMMANDS` names `keys`, and
    an op this arm still could not run would be caught by `execute_read` saying
    so. Keeping the guard would now be refusing a family for a reason that has
    stopped being true -- the defect it was written to avoid, pointed the other
    way.

    `frontmatter` joins `section` in the turns guard for the reason that admits
    `section`: at `--result-shape delta`, which is the default, `armb.tool_result`
    sends `describe_frontmatter_change` and the CLI now prints the same function's
    output (`crates/incise-cli/src/main.rs`). Tables and lists still send a
    renderer summary at Arm B and a description at Arm C, so they stay out.
    """
    if turns <= 1:
        return
    reads = tuple(READ_SUBCOMMANDS)
    edits = [t for t in tasks if not t["family"].startswith(reads)]
    fams = {armb.family_of(t) for t in edits}
    if fams - {"section", "frontmatter"}:
        raise SystemExit(
            f"--turns {turns} with families {sorted(fams)}: on an edit the CLI "
            "returns `describe_change`, but `armb.tool_result` returns the "
            "renderer summary for tables and lists -- so multi-turn would "
            "compare two different tool results. Both families are adopted at "
            "--turns 1, where the result is never sent."
        )


def _converse(endpoint, binary, sb, payload, max_turns, framing,
              calls, codes, turns):
    """Sample up to `max_turns` assistant turns, executing every call made.

    Shared by `run_trial` and `replay_one` rather than written twice. The two
    differ only in how the *first* turn arrives -- sampled, or taken off disk --
    and a turn loop that had drifted between them would put the difference in
    the harness rather than in the treatment. `calls`, `codes` and `turns` are
    appended to, so a replay can seed them with the turn it pinned.
    """
    tokens, elapsed, finish, model = 0, 0.0, None, None
    for _ in range(max_turns):
        resp, took = call(endpoint, payload)
        row = record(resp, took)
        model = resp.get("model")
        turns.append({k: row.get(k) for k in
                      ("content", "tool_calls", "finish_reason",
                       "completion_tokens", "elapsed_s")})
        tokens += row.get("completion_tokens") or 0
        elapsed += row.get("elapsed_s") or 0
        finish = row.get("finish_reason")
        made = row.get("tool_calls") or []
        if not made:
            break
        calls += made
        payload["messages"].append(
            {"role": "assistant", "content": row.get("content"),
             "tool_calls": made})
        for c in made:
            fn = c.get("function", {})
            try:
                a = json.loads(fn.get("arguments") or "{}")
                if fn.get("name") in armb.READS:
                    # A read's result is the renderer's string, which is what
                    # `armb._converse` sends too. The structure is dropped here
                    # on purpose: it is the grader's, and grading happens in its
                    # own pass so an executor change can be measured without
                    # re-spending GPU time.
                    _got, desc, err, code = execute_read(
                        binary, sb, fn.get("name"), a)
                else:
                    op, op_args = armb.normalize(fn.get("name"), a)
                    desc, err, code = execute(binary, sb, op, op_args)
            except Exception as e:  # noqa: BLE001
                desc, err, code = None, armb.err_text(e), None
            codes.append(code)
            payload["messages"].append(
                {"role": "tool", "tool_call_id": c.get("id", "0"),
                 "content": frame(framing, err) if err else desc})
    return model, finish, tokens, elapsed


def run_trial(endpoint, binary, task, scheme, seed, max_turns):
    """One trial, up to `max_turns` assistant turns, as one recorded row.

    `armb.run_trial` with the executor swapped. The document is not carried in a
    variable here -- it is on disk, and each call re-reads it, which is the
    difference being measured.

    The error framing is Arm B's on purpose: `"Error: " + message`, which is
    also what the CLI itself prints on stderr. §5.3's 75% one-turn section
    recovery was measured against those exact bytes, so this arm must not move
    them. (The Hermes plugin's `{"error": ...}` framing is a separate
    divergence, and `replay` is where it is measured rather than assumed.)
    """
    payload = armb.build_payload(task, scheme, seed)
    calls, codes, turns = [], [], []
    with Sandbox(task) as sb:
        model, finish, tokens, elapsed = _converse(
            endpoint, binary, sb, payload, max_turns, "plain",
            calls, codes, turns)
        final_hash = sb.sha256()
    return {
        "model": model,
        "finish_reason": finish,
        "elapsed_s": round(elapsed, 2),
        "completion_tokens": tokens,
        "tool_calls": calls,
        "turns": turns,
        "n_turns": len(turns),
        "exit_codes": codes,
        # What the run left on disk. `grade_one` re-executes the same calls in a
        # fresh sandbox and asserts it lands here again; the two disagreeing
        # would be a nondeterminism the in-process arm could not have.
        "final_hash": final_hash,
    }


def run(args):
    """`armb.run`, with `run_trial` swapped and the same resume contract.

    At `--turns 1` this executes nothing -- exactly as Arm B does not. The
    single-turn arm records a response, and the op is run once, at grade time.
    Keeping grading a separate pass is what lets the executor change be measured
    without re-spending GPU time (FINDINGS Setup, S8), and it is why Arm C can
    be compared to Arm B's *stored* trials rather than a re-run of them.
    """
    tasks = json.load(open(args.tasks))["tasks"]
    _check_supported(tasks, args.turns)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            try:
                t = json.loads(line)
                # A row that errored is not a measurement, so re-running the
                # command retries it; readers take the last row per key. See
                # `armb.run` for why this matters in a paired design.
                if t.get("error") is None:
                    done.add((t["task_id"], t["scheme"], t["trial"]))
            except (json.JSONDecodeError, KeyError):
                continue
    if done:
        print(f"resuming: {len(done)} trials already recorded")

    work = [
        (task, trial)
        for task in tasks
        for trial in range(args.trials)
        if (task["id"], args.scheme, trial) not in done
    ]
    if not work:
        print("nothing to do")
        return 0

    print(f"{len(work)} trials to run, scheme={args.scheme}, binary={args.binary}")
    import time

    started = time.time()
    with open(args.out, "a") as fh:
        for n, (task, trial) in enumerate(work, 1):
            try:
                if args.turns > 1:
                    row = run_trial(args.endpoint, args.binary, task,
                                    args.scheme, trial, args.turns)
                else:
                    resp, elapsed = call(
                        args.endpoint, armb.build_payload(task, args.scheme, trial))
                    row = record(resp, elapsed)
                row.update(task_id=task["id"], scheme=args.scheme, trial=trial,
                           error=None)
            except Exception as e:  # noqa: BLE001
                row = {
                    "task_id": task["id"], "scheme": args.scheme, "trial": trial,
                    "error": f"{type(e).__name__}: {e}", "elapsed_s": None,
                }
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            el = time.time() - started
            eta = (el / n) * (len(work) - n) / 60
            print(
                f"[{n:3d}/{len(work)}] {task['id']:26s} t{trial:<2d} "
                f"{(row.get('elapsed_s') or 0):6.1f}s  "
                f"tok={row.get('completion_tokens') or 0:5d}  "
                f"{'ERR ' + row['error'][:40] if row.get('error') else ''}  eta {eta:.0f}m",
                flush=True,
            )
    return 0


# --------------------------------------------------------------------------
# replay
# --------------------------------------------------------------------------

def replay(args):
    """Re-run only what follows a first call that *failed*, one string different.

    `armb.replay` is the same move, pointed the other way. There the question
    was what a model does after a call that worked, so a prefix whose first call
    errored was excluded; here the errored prefixes are the whole sample, and
    the string under test is the message the model was given to recover from.

    Arm C made this worth measuring. Its largest single failure class was not in
    the core at all: 59 first calls across the two multi-turn families arrived
    with no usable `path`, were answered by clap rather than by incise, and
    recovered at a rate far below the 75% §5.3 measured for a refusal in
    incise's own voice. That is one string, in one front end, and this is how
    much it is worth.

    Two axes, deliberately separate, because they belong to different programs:

      the binary   which *sentence* the model reads. Selected with `--binary`
                   and named with `--tag`, so a run against a build from before
                   the change and a run against one from after land in the same
                   file under different keys and pair on (task_id, trial).
                   Transcribing either sentence into this harness would make it
                   a comparison between two copies rather than two programs.
      --framings   what the *host* does to that sentence on the way in: the
                   plugin's JSON wrapper, and its 2048-character cap. See
                   `FRAMINGS`.

    `plain` under the binary the arm was run with is the replication check. It
    must reproduce the rate Arm C recorded, or the replay is not sampling the
    state it claims to be, and nothing else in the table means anything.

    `_check_supported` is deliberately *not* applied here. It guards `run`, whose
    numbers are read against Arm B's, and the divergence it names -- the CLI
    describing a successful edit where `armb.tool_result` renders a summary --
    is a property of the executor, which both conditions share. Held constant,
    it cannot move a paired difference. It does mean a replay's absolute rate is
    not comparable to a list or table rate in FINDINGS, only to its own pair.
    """
    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    src = [json.loads(l) for l in open(args.replay) if l.strip()]
    framings = [s.strip() for s in args.framings.split(",")]
    for s in framings:
        if s not in FRAMINGS:
            print(f"unknown framing {s!r}; valid: {', '.join(FRAMINGS)}")
            return 1
    want = {"usage": EXIT_USAGE, "refusal": EXIT_REFUSED}[args.select]

    # The first call is re-executed rather than read off the recorded
    # `exit_codes`, for two reasons. The single-turn arms recorded no codes at
    # all -- they execute at grade time -- so reading them would silently
    # restrict the sample to the multi-turn files. And the code a *current*
    # binary returns is the one the replay will actually send, which is the
    # thing being selected on.
    prefixes = []
    skipped = Counter()
    for tr in src:
        task = tasks.get(tr["task_id"])
        calls = tr.get("tool_calls") or []
        if not task or not calls:
            skipped["no first call"] += 1
            continue
        fn = calls[0].get("function", {})
        try:
            a = json.loads(fn.get("arguments") or "{}")
            op, op_args = armb.normalize(fn.get("name"), a)
            with Sandbox(task) as sb:
                _desc, err, code = execute(args.binary, sb, op, op_args)
        except Exception as e:  # noqa: BLE001
            skipped[f"{type(e).__name__}"] += 1
            continue
        if code != want or not err:
            skipped[f"first call exit {code}"] += 1
            continue
        prefixes.append((task, tr, calls[0]))

    print(f"{len(prefixes)} usable prefixes from {len(src)} trials"
          + (f" (skipped: {dict(skipped)})" if skipped else ""))
    if not prefixes:
        return 1
    if executor_mismatch(prefixes, args):
        return 1

    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            try:
                t = json.loads(line)
                if t.get("error") is None:
                    done.add((t["task_id"], t["scheme"], t["trial"]))
            except (json.JSONDecodeError, KeyError):
                continue
    work = [(task, tr, c, framing)
            for framing in framings
            for (task, tr, c) in prefixes
            if (task["id"], f'{tr["scheme"]}:{args.tag}:{framing}', tr["trial"])
            not in done]
    if not work:
        print("nothing to do")
        return 0
    print(f"{len(work)} replays to run ({len(framings)} framings, tag={args.tag})")

    import time
    started = time.time()
    with open(args.out, "a") as fh:
        for n, (task, tr, first, framing) in enumerate(work, 1):
            scheme = f'{tr["scheme"]}:{args.tag}:{framing}'
            try:
                row = replay_one(args.endpoint, args.binary, task, tr, first,
                                 framing, args.turns)
                row.update(task_id=task["id"], scheme=scheme, trial=tr["trial"],
                           framing=framing, tag=args.tag, error=None)
            except Exception as e:  # noqa: BLE001
                row = {"task_id": task["id"], "scheme": scheme,
                       "trial": tr["trial"], "framing": framing, "tag": args.tag,
                       "error": f"{type(e).__name__}: {e}", "elapsed_s": None}
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            el = time.time() - started
            print(f"[{n:4d}/{len(work)}] {framing:6s} {task['id']:26s} "
                  f"t{tr['trial']:<2d} "
                  f"turns={row.get('n_turns') or 0} "
                  f"codes={row.get('exit_codes')} "
                  f"eta {(el / n) * (len(work) - n) / 60:5.1f}m", flush=True)
    return 0


def executor_mismatch(prefixes, args):
    """Refuse a prefix pool the `--binary` should never have refused.

    `replay` selects by re-executing the first call against `--binary`, which is
    right for its own mechanics and wrong about what the pool then *means*. A
    prefix's trial was produced under some scheme; if that scheme is retired,
    the binary implements a different tool, and re-executing asks a model to
    recover from a refusal it could not have seen. The population stops being
    "calls that were refused" and becomes "calls this binary refuses."

    It is not hypothetical and it is not small. F-framing published a tables
    one-turn recovery of 13/38 for one refusal; all 38 were `scheme_d` prefixes
    sending `row`, which `scheme_d` declares, no shipping schema does, and the
    crate refuses on purpose. Arm B's own executor **accepts all 38**. Over the
    23 genuinely-refused tables prefixes the rate is 23/23. One absolute rate in
    FINDINGS was wrong for a year of this file's life because nothing here
    looked.

    The test is direct evidence rather than a scheme-name lookup: replay the
    first call through the oracle and ask whether it actually failed. A name
    lookup would reject every non-adopted scheme, which is most of the corpus of
    prefixes and nearly all of them legitimately; this rejects exactly the ones
    where the two executors disagree about whether there was a fault at all.

    Only for `--select refusal`. A usage fault is argv-level -- a missing
    `path`, answered by the front end -- and `apply_op` is handed content
    directly, so it cannot see one and would call every such prefix "accepted."
    That is the whole Arm C population and filtering it would be the same class
    of error in the other direction.
    """
    if args.select != "refusal":
        return False
    bad = Counter()
    for task, tr, first in prefixes:
        fn = first.get("function", {})
        try:
            a = json.loads(fn.get("arguments") or "{}")
            if not isinstance(a, dict):
                continue
            op, op_args = armb.normalize(fn.get("name"), a)
            content = open(os.path.join(ROOT, task["fixture"]), newline="").read()
            after, err = incise_ops.apply_op(content, op, op_args)
        except Exception:  # noqa: BLE001
            continue
        if err is None and after != content:
            bad[str(tr.get("scheme", "?")).rsplit(":", 1)[0]] += 1
    if not bad:
        return False
    total = sum(bad.values())
    print(f"\n  !! {total} of {len(prefixes)} prefixes have a first call the "
          f"ORACLE ACCEPTS.\n"
          f"     {dict(bad)}\n"
          f"     These were not refused in the arm they came from. The binary "
          f"refuses them\n"
          f"     because it implements a different schema, so replaying them "
          f"measures that\n"
          f"     mismatch, not the model. Any absolute rate over this pool is "
          f"an artifact;\n"
          f"     paired comparisons within it are not, since the executor is "
          f"held constant.\n"
          f"     Re-run against a results file from the adopted scheme, or pass "
          f"--allow-executor-mismatch\n"
          f"     if a paired contrast is all you intend to read.")
    if args.allow_executor_mismatch:
        print("     --allow-executor-mismatch given; continuing.")
        return False
    return True


def replay_one(endpoint, binary, task, tr, first, framing, max_turns):
    """Sample the turns that follow one already-failed call.

    The first turn is pinned, not sampled: the assistant message is the one on
    disk, and the tool message is that call executed now, framed by `framing`.
    Everything after it goes through the same `_converse` a live trial uses.
    """
    payload = armb.build_payload(task, tr["scheme"], tr["trial"])
    payload["messages"].append({"role": "assistant", "content": None,
                                "tool_calls": [first]})

    calls, codes, turns = [first], [], []
    with Sandbox(task) as sb:
        fn = first.get("function", {})
        a = json.loads(fn.get("arguments") or "{}")
        if fn.get("name") in armb.READS:
            _got, desc, err, code = execute_read(binary, sb, fn.get("name"), a)
        else:
            op, op_args = armb.normalize(fn.get("name"), a)
            desc, err, code = execute(binary, sb, op, op_args)
        codes.append(code)
        sent = frame(framing, err) if err else desc
        payload["messages"].append(
            {"role": "tool", "tool_call_id": first.get("id", "0"),
             "content": sent})

        # `max_turns` counts the whole trial, and one turn is already spent.
        model, finish, tokens, elapsed = _converse(
            endpoint, binary, sb, payload, max(1, max_turns - 1), framing,
            calls, codes, turns)
        final_hash = sb.sha256()
    return {
        "model": model,
        "finish_reason": finish,
        "elapsed_s": round(elapsed, 2),
        "completion_tokens": tokens,
        "tool_calls": calls,
        "turns": turns,
        # The pinned turn counts: a replay that stopped immediately spent one.
        "n_turns": len(turns) + 1,
        "exit_codes": codes,
        "final_hash": final_hash,
        # The exact bytes the treatment put in front of the model, kept so a
        # rate can be traced back to the string that produced it without
        # re-deriving it from a binary that may since have moved.
        "sent": sent,
    }


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

def grade_one(task, trial, binary):
    """Return (outcome, detail). `armb.grade_one`'s ladder, run through argv.

    The same outcome classes, in the same order, on the same
    `grade.check_result` -- both arms have to be judged by byte-identical
    criteria or the comparison between them is meaningless -- plus the two
    classes a file makes possible. See the module docstring.

    `transport` included, and for the same reason: a request that never
    produced a completion is not a trial of anything, and charging it to the
    model is what made F-compose's sections row read 14-1. Shared with
    `armb.grade_one` rather than reimplemented, because "byte-identical
    criteria" has to hold for this class too.
    """
    if trial.get("error"):
        kind = trial["error"].split(":", 1)[0]
        return ("transport" if kind in armb.TRANSPORT_ERRORS else "malformed",
                trial["error"])
    calls = trial.get("tool_calls") or []
    if not calls:
        return "malformed", "no tool call"

    before = open(os.path.join(ROOT, task["fixture"]), newline="").read()
    with Sandbox(task) as sb:
        errors, codes, report = [], [], None
        for i, c in enumerate(calls):
            fn = c.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as e:
                return "malformed", f"call {i + 1}: unparseable arguments: {e}"
            if not isinstance(args, dict):
                return "malformed", (f"call {i + 1}: arguments not an object: "
                                     f"{type(args).__name__}")
            where = f"call {i + 1}: " if len(calls) > 1 else ""
            if fn.get("name") in armb.READS:
                # `armb.grade_one`'s read branch, over argv. A read that refused
                # is collected exactly as a failed edit is, and a later read that
                # succeeds replaces it -- the model was handed the refusal and
                # tried again, which is recovery wherever else it happens. The
                # *last* successful read is the answer, because that is the one a
                # caller would act on.
                got, _text, err, code = execute_read(
                    binary, sb, fn.get("name"), args)
                if err:
                    errors.append(where + err.replace("\n", " | "))
                    codes.append(code)
                else:
                    report = got
                continue
            op, op_args = armb.normalize(fn.get("name"), args)
            _desc, err, code = execute(binary, sb, op, op_args)
            if err:
                # `unknown operation` used to return `malformed` here, which
                # contradicted the sentence three lines below it. Same fix and
                # same reasoning as `armb.grade_one`; see FINDINGS F-terminal.
                # Arm C is the one place the *sentence* is not also at fault:
                # the CLI is handed an op directly, so naming all fifteen is
                # correct here in a way it is not for a model with three tools.
                errors.append(where + err.replace("\n", " | "))
                codes.append(code)
            # A call that fails leaves the file untouched -- that is the op's
            # contract, and the CLI writes nothing on a refusal -- so the
            # sequence continues rather than aborting, as in Arm B.
        doc = sb.read()
        got_hash = sb.sha256()

    want = trial.get("final_hash")
    if want is not None and want != got_hash:
        HASH_MISMATCHES.append((task["id"], trial.get("trial"), want, got_hash))

    if task["family"].startswith("table-get"):
        # Past the `doc == before` ladder below, which reads an unchanged
        # document as "nothing happened". For a read an unchanged document is
        # the success condition. `armb.grade_one` says the rest; the one thing
        # this arm adds is that `doc == before` is now a claim about a file
        # rather than about a string it never wrote.
        return check_result(task, before, doc,
                            report if report is not None
                            else (errors[-1] if errors else None))

    if doc == before:
        if errors:
            if EXIT_ESCAPED in codes:
                return "escaped", errors[-1]
            if EXIT_USAGE in codes:
                return "usage_error", errors[-1]
            return "op_error", errors[-1]
        return "wrong", "op applied but changed nothing"

    outcome, detail = check_result(task, before, doc)
    if outcome == "wrong" and errors:
        # A partial edit the model was *told* about is a loud failure, not a
        # silent one. Only `wrong` is re-filed; see `armb.grade_one`.
        loud = ("usage_error" if EXIT_USAGE in codes else "op_error")
        return loud, f"{detail}; after: {errors[-1]}"
    return outcome, detail


def grade(args):
    """`armb.grade`'s report, over Arm C's grader."""
    del HASH_MISMATCHES[:]
    rc = armb.grade(args, grader=lambda task, tr: grade_one(task, tr, args.binary))
    if HASH_MISMATCHES:
        print(f"\n!! {len(HASH_MISMATCHES)} trials did not reproduce the hash the "
              f"run recorded -- the executor is not deterministic across the "
              f"process boundary, and no rate above is trustworthy:")
        for tid, trial, want, got in HASH_MISMATCHES[:10]:
            print(f"   {tid} t{trial}: ran to {want[:12]}, regraded to {got[:12]}")
    return rc


def cross(args):
    """Grade recorded trials by *both* arms and report where they disagree.

    The port question, asked of trials that already exist. `run` samples a model
    and costs GPU; this re-executes calls that are already on disk, once through
    `apply_op` in-process and once through argv, and reports the outcome pairs.
    REQUIREMENTS §7.4 puts Arm B's rates at the bar the port must match rather
    than beat, and this is that comparison at the level of the individual trial:
    a pooled rate can agree while trials swap outcomes underneath it.

    It is not a new arm and its output is not a new rate. Every trial here was
    sampled by Arm B and its rate is Arm B's; what this measures is whether the
    process boundary changes any of them.

    Pairs against the recorded row, not against a fresh run, so `--tasks` must be
    the task file those trials were run on. Unknown task ids are a hard error:
    silently skipping them would let a mismatched pairing report perfect
    agreement over nothing.

        python3 bench/armc.py --cross bench/results/armb_read_g.jsonl \\
            --tasks bench/tasks/tables_read.json
    """
    tasks = {t["id"]: t for t in json.load(open(args.tasks))["tasks"]}
    del HASH_MISMATCHES[:]

    pairs, rows = Counter(), 0
    for line in open(args.cross, newline=""):
        if not line.strip():
            continue
        tr = json.loads(line)
        # A grading record carries an outcome and no calls; an errored trial is
        # not a measurement. `population.is_grading_record` states the first.
        if "tool_calls" not in tr or tr.get("error") is not None:
            continue
        if tr["task_id"] not in tasks:
            raise SystemExit(
                f"{args.cross}: task {tr['task_id']!r} is not in {args.tasks}. "
                "These trials were run on a different task file, and pairing "
                "them against this one would compare two different questions.")
        task = tasks[tr["task_id"]]
        rows += 1
        pairs[(armb.grade_one(task, tr)[0], grade_one(task, tr, args.binary)[0])] += 1

    same = sum(n for (b, c), n in pairs.items() if b == c)
    print(f"{os.path.basename(args.cross)}: {rows} trials, {same} agree, "
          f"{rows - same} differ")
    for (b, c), n in sorted(pairs.items(), key=lambda kv: -kv[1]):
        mark = "  " if b == c else "!!"
        print(f"  {mark} {n:4d}  armb={b:20s} armc={c}")
    if HASH_MISMATCHES:
        print(f"  !! {len(HASH_MISMATCHES)} trials did not reproduce their "
              f"recorded hash")
    return 0 if same == rows and not HASH_MISMATCHES else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:8081/v1/chat/completions")
    ap.add_argument("--tasks", default=os.path.join(ROOT, "bench/tasks/tables.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "bench/results/armc.jsonl"))
    ap.add_argument("--graded", default=os.path.join(ROOT, "bench/results/armc_graded.jsonl"))
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--turns", type=int, default=1,
                    help="max assistant turns per trial; >1 is sections only")
    ap.add_argument("--scheme", default="scheme_f", choices=list(armb.SCHEMES))
    ap.add_argument("--binary", default=None,
                    help="the incise binary; $INCISE_BIN, then target/, then PATH")
    ap.add_argument("--grade", action="store_true")
    ap.add_argument("--cross", default=None,
                    help="a results file to grade through both arms' graders, "
                         "reporting where the process boundary moves an outcome")
    ap.add_argument("--replay", default=None,
                    help="a results file to take failed-first-call prefixes from")
    ap.add_argument("--select", default="usage", choices=("usage", "refusal"),
                    help="which first-call exit code makes a usable prefix: "
                         "usage is 2 (the missing-path class), refusal is 1")
    ap.add_argument("--allow-executor-mismatch", action="store_true",
                    help="proceed even if the oracle accepts first calls the "
                         "--binary refused; absolute rates over such a pool are "
                         "artifacts, paired contrasts within it are not")
    ap.add_argument("--framings", default=",".join(FRAMINGS),
                    help="comma-separated; see FRAMINGS")
    ap.add_argument("--tag", default="incise",
                    help="names the binary axis in the scheme key, so runs "
                         "against two builds pair in one file")
    args = ap.parse_args()

    args.binary = args.binary or find_binary()

    if args.grade:
        return grade(args)
    if args.cross:
        return cross(args)
    if args.replay:
        return replay(args)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
