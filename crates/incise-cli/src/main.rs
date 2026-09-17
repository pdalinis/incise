//! `incise` -- the command-line front end over `incise-core`.
//!
//! REQUIREMENTS.md section 8: "a core crate holding parse/locate/splice and the
//! operation set, with thin CLI and MCP binaries over it. **Neither front end
//! contains logic.**" This is that CLI, and "thin" is meant literally -- it turns
//! argv into a JSON object, reads a file, calls `apply_op`, writes the file back,
//! and prints. Every decision about what an argument means belongs to the core.
//!
//! Two consequences are worth stating because they look like omissions:
//!
//! * **The op subcommands are generated from `incise_core::OPS`.** Listing them
//!   here would be a second copy of the op set, and the first thing to go stale.
//! * **Nothing is validated before `apply_op` sees it.** The order arguments are
//!   checked in is part of the contract (`ops/dispatch.rs`): a malformed `values`
//!   outranks a nonexistent table, and a front end that rejected either one early
//!   would answer the same call with a different sentence. Section 5.3 makes the
//!   sentence the product, so "a refusal, just a different one" is a regression.
//!   An unknown op name is handed to `apply_op` too, for the same reason -- the
//!   core names the fifteen that exist, where clap would say "unrecognized
//!   subcommand".
//! * **A missing file is answered here, not by clap.** It is the one fault the
//!   core can never see: with no path there is nothing to read and no call to
//!   make. clap's answer to it names `<FILE>` and prints a `Usage:` line, in
//!   prose, on stderr, whatever `--json` said -- see [`path_of`] for what Arm C
//!   measured that costing.

use std::path::PathBuf;
use std::process;

use clap::{Arg, ArgAction, ArgGroup, ArgMatches, Command};

use incise_core::json::Value;
use incise_core::ops::dispatch::to_address;
use incise_core::ops::list::render_list_summary;
use incise_core::{
    args, frontmatter_get, render_frontmatter, render_frontmatter_get, render_section_outline,
    render_table_list, render_table_rows, table_get,
};

mod io;
mod opargs;
mod out;
mod schema;

use opargs::{Kind, FLAGS};
use out::{Format, EXIT_USAGE};

fn main() {
    let matches = match cli().try_get_matches() {
        Ok(m) => m,
        // clap's own codes already match ours: 0 for --help and --version, 2 for
        // a malformed invocation.
        Err(e) => e.exit(),
    };
    process::exit(run(&matches));
}

// --------------------------------------------------------------------------
// the command tree
// --------------------------------------------------------------------------

fn cli() -> Command {
    let mut cmd = Command::new("incise")
        .version(env!("CARGO_PKG_VERSION"))
        .about("Content-addressed, byte-preserving markdown edits.")
        .long_about(
            "Content-addressed, byte-preserving markdown edits.\n\n\
             Everything outside the targeted range is byte-identical after an edit. \
             Addressing is semantic -- heading paths, column values, item text -- and \
             never a line number, which is stale the moment anything above it moves.\n\n\
             A successful edit prints one sentence saying what changed. A refusal \
             prints on stderr and exits 1; it is written to be acted on, not logged.",
        )
        .subcommand_required(true)
        .arg_required_else_help(true)
        .allow_external_subcommands(true);

    for op in incise_core::OPS {
        cmd = cmd.subcommand(op_subcommand(op));
    }

    cmd.subcommand(read_subcommand("outline", "List the document's sections."))
        .subcommand(read_subcommand("tables", "List the document's tables."))
        .subcommand(read_subcommand("lists", "Summarize the document's lists."))
        .subcommand(read_subcommand(
            "front",
            "Summarize the document's frontmatter.",
        ))
        .subcommand(rows_subcommand())
        .subcommand(keys_subcommand())
        .subcommand(
            Command::new("hash")
                .about("Print the file's content hash, for --if-match.")
                .arg(file_arg())
                .args(common_args()),
        )
        .subcommand(
            Command::new("schema")
                .about("Print the tool schemas a model is given.")
                .long_about(
                    "Print the tool schemas a model is given.\n\n\
                     These are not descriptive: each is the schema variant that won its \
                     measured comparison, copied from `bench/armb.py`. A harness wiring \
                     incise to a model should read them from here rather than keep a copy.",
                )
                .arg(
                    Arg::new("tool")
                        .long("tool")
                        .value_name("NAME")
                        .value_parser(schema::TOOLS.to_vec())
                        .help("Print one tool instead of all five"),
                ),
        )
}

/// One op subcommand, carrying the whole flag set.
///
/// Which keys an op reads is the core's business. A CLI that offered `--level`
/// only on `section-set-level` would be deciding that a second time, in a place
/// no differential test looks.
fn op_subcommand(op: &'static str) -> Command {
    let mut cmd = Command::new(op)
        .about(op_about(op))
        .arg(file_arg())
        .arg(args_arg())
        .arg(args_file_arg())
        .arg(
            Arg::new("dry-run")
                .long("dry-run")
                .action(ArgAction::SetTrue)
                .help("Say what would change; write nothing"),
        )
        .arg(
            Arg::new("if-match")
                .long("if-match")
                .value_name("HASH")
                .help("Refuse unless the file still hashes to this (any prefix)"),
        )
        .arg(ordinal_arg())
        .args(common_args());

    for flag in FLAGS {
        cmd = cmd.arg(flag_arg(flag));
    }

    // `--args` is the canonical spelling and the per-key flags are sugar over
    // it. Mixing them would make the precedence a thing to remember.
    let keys: Vec<&'static str> = FLAGS
        .iter()
        .map(|f| f.long)
        .chain(std::iter::once("ordinal"))
        .collect();
    cmd.group(ArgGroup::new("per-key").args(keys).multiple(true))
        .mut_arg("args", |a| a.conflicts_with("per-key"))
        .mut_arg("args-file", |a| a.conflicts_with("per-key"))
}

fn read_subcommand(name: &'static str, about: &'static str) -> Command {
    Command::new(name)
        .about(about)
        .arg(file_arg())
        .args(common_args())
}

/// `rows` is the one read that takes an argument, so it is the one read that
/// also takes `--args`.
///
/// The per-key flags cannot express every address the ops accept: a table
/// qualified by ordinal is `{"table": {"heading": ..., "ordinal": ...}}`, and
/// `--table`/`--ordinal` reach that one nesting only because `collect_rows_args`
/// knows to build it. `filter` is flat `COLUMN=VALUE` pairs, so a filter value
/// that is not a string has no spelling here at all -- and `check_cell` has
/// refusals for exactly those, which nothing could reach through this door.
///
/// It is also what lets a harness send a read the way it sends an edit. Arm C's
/// rule is that nothing is checked before the binary sees it (§5.3 is about the
/// order arguments are checked in), so a harness translating a model's argument
/// object into flags would be pre-validating it -- and measuring its own
/// translation rather than incise's answer.
fn rows_subcommand() -> Command {
    read_subcommand("rows", "Show a table's rows.")
        .arg(args_arg())
        .arg(args_file_arg())
        .arg(flag_arg(&FLAGS[0])) // --table
        .arg(ordinal_arg())
        .arg(
            Arg::new("filter")
                .long("filter")
                .value_name("COLUMN=VALUE")
                .action(ArgAction::Append)
                .help("Show only rows whose cells match. Repeatable"),
        )
        // The same precedence rule `op_subcommand` states, for the same reason.
        .group(
            ArgGroup::new("per-key")
                .args(["table", "ordinal", "filter"])
                .multiple(true),
        )
        .mut_arg("args", |a| a.conflicts_with("per-key"))
        .mut_arg("args-file", |a| a.conflicts_with("per-key"))
}

/// `keys` is `rows` for the frontmatter family: the one frontmatter read that
/// takes an argument, so the one that also takes `--args`.
///
/// `--key` is optional here and required by `frontmatter-set`, which is the
/// oracle's asymmetry and not this layer's: a `keys` call with no key reports
/// the whole block, so the argument is a narrowing rather than an address. An
/// explicit `{"key": null}` through `--args` means the same as no key at all,
/// again because that is what the core does with it -- `--key` cannot spell it,
/// and pre-translating it here would be deciding a question the core owns.
fn keys_subcommand() -> Command {
    read_subcommand("keys", "Show the document's frontmatter keys.")
        .arg(args_arg())
        .arg(args_file_arg())
        .arg(flag_arg(flag_named("key")))
        // The same precedence rule `op_subcommand` states, for the same reason.
        .group(ArgGroup::new("per-key").args(["key"]).multiple(true))
        .mut_arg("args", |a| a.conflicts_with("per-key"))
        .mut_arg("args-file", |a| a.conflicts_with("per-key"))
}

/// One flag by its long name. By name rather than by index so that reordering
/// `FLAGS` -- which is emission order, and load-bearing -- cannot silently hand
/// a read command somebody else's argument.
fn flag_named(long: &str) -> &'static opargs::Flag {
    FLAGS
        .iter()
        .find(|f| f.long == long)
        .expect("flag is declared in opargs::FLAGS")
}

/// The whole argument object as JSON -- the canonical spelling on every
/// subcommand that takes arguments at all.
fn args_arg() -> Arg {
    Arg::new("args")
        .long("args")
        .value_name("JSON")
        .help("The whole argument object, as JSON")
}

fn args_file_arg() -> Arg {
    Arg::new("args-file")
        .long("args-file")
        .value_name("PATH")
        .conflicts_with("args")
        .help("The argument object from a file, or \"-\" for stdin")
}

/// The file to operate on -- deliberately *not* `required`, so that clap does
/// not answer a missing one. See [`path_of`].
fn file_arg() -> Arg {
    Arg::new("file")
        .value_name("FILE")
        .help("The markdown file")
}

/// `--ordinal` has no key of its own; it qualifies whichever address is present.
/// See `opargs::build`.
fn ordinal_arg() -> Arg {
    Arg::new("ordinal")
        .long("ordinal")
        .value_name("N")
        .value_parser(clap::value_parser!(i64))
        .help("Which of several things sharing that heading, 0-based")
}

fn common_args() -> Vec<Arg> {
    vec![
        Arg::new("json")
            .long("json")
            .action(ArgAction::SetTrue)
            .help("Machine-readable output on stdout, including refusals"),
        Arg::new("quiet")
            .long("quiet")
            .short('q')
            .action(ArgAction::SetTrue)
            .help("Suppress the success line and the hash; the exit code still speaks"),
    ]
}

fn flag_arg(flag: &'static opargs::Flag) -> Arg {
    let arg = Arg::new(flag.long).long(flag.long).help(flag.help);
    match flag.kind {
        Kind::Present => arg.action(ArgAction::SetTrue),
        Kind::Pairs => arg.value_name(flag.value_name).action(ArgAction::Append),
        Kind::Int => arg
            .value_name(flag.value_name)
            .value_parser(clap::value_parser!(i64)),
        Kind::Bool => arg
            .value_name(flag.value_name)
            .value_parser(["true", "false"]),
        Kind::Str | Kind::Json => arg.value_name(flag.value_name),
    }
}

/// A one-line summary per op, taken from what the op family's schema tells a
/// model. Human help, not a contract -- `incise schema` is the contract.
fn op_about(op: &'static str) -> &'static str {
    match op {
        "table-add-row" => "Add a row to a table.",
        "table-update-cell" => "Change one cell of one row.",
        "table-delete-row" => "Delete one row.",
        "table-realign" => "Re-pad a table's columns.",
        "list-add-item" => "Add an item to a list.",
        "list-remove-item" => "Remove one item from a list.",
        "list-set-checked" => "Tick or untick a checkbox item.",
        "section-append" => "Add to a section's body, keeping what is there.",
        "section-replace-body" => "Replace a section's body; needs --overwrite if it has one.",
        "section-insert" => "Create a section, relative to an existing one.",
        "section-delete" => "Delete a section and its subtree.",
        "section-rename" => "Change a section's heading text.",
        "section-set-level" => "Move a section to a different heading level.",
        "frontmatter-set" => "Set a frontmatter key, creating it if it is absent.",
        "frontmatter-delete" => "Delete a frontmatter key and anything under it.",
        _ => "",
    }
}

// --------------------------------------------------------------------------
// dispatch
// --------------------------------------------------------------------------

fn run(m: &ArgMatches) -> i32 {
    match m.subcommand() {
        Some(("outline", s)) => read(s, View::Outline),
        Some(("tables", s)) => read(s, View::Tables),
        Some(("lists", s)) => read(s, View::Lists),
        Some(("front", s)) => read(s, View::Front),
        Some(("rows", s)) => read(s, View::Rows),
        Some(("keys", s)) => read(s, View::Keys),
        Some(("hash", s)) => hash(s),
        Some(("schema", s)) => print_schema(s),
        Some((op, s)) if incise_core::OPS.contains(&op) => edit(op, s),
        // An external subcommand: a name clap did not recognise. The core owns
        // the answer, because the core owns the list.
        Some((other, _)) => {
            // clap parsed no flags for this branch, so `--json` is read from
            // argv directly. A caller that asked for machine output must not get
            // prose back merely because its op name was a typo -- that is the
            // one case where it most needs to read the reply.
            let json = std::env::args().any(|a| a == "--json");
            let f = Format { json, quiet: false };
            match incise_core::apply_op("", other, None) {
                Err(e) => out::refusal(&f, e.message()),
                // Unreachable: the guard above claims every name in OPS.
                Ok(_) => EXIT_USAGE,
            }
        }
        None => EXIT_USAGE,
    }
}

fn format_of(m: &ArgMatches) -> Format {
    Format {
        json: m.get_flag("json"),
        quiet: m.get_flag("quiet"),
    }
}

/// The file to operate on, or the CLI's own sentence if none was named.
///
/// `file` is not `required` in the command tree, and this is the reason. clap
/// answers a missing positional with `<FILE>` and a `Usage:` line describing an
/// argv the caller never wrote -- which is exactly wrong for the caller that
/// matters, a model driving incise through a tool call where the argument is
/// spelled `path`. It also arrives on stderr as prose whatever `--json` said,
/// because clap exits before the flag has been read.
///
/// Arm C measured what that costs. Forty first calls arrived with no file; 8
/// recovered within four turns -- 23%, against the 75% one-turn recovery
/// section 5.3 measured for a refusal written in incise's own voice. It was the
/// arm's largest single failure class, and the only one that did not belong to
/// the core.
///
/// **The sentence below did not close that gap, and the replay says so.** Three
/// messages were replayed over the same 59 failed prefixes (`armc.py --replay
/// --select usage`): clap's text, and two incise candidates. On "did the next
/// call carry a file?" the lists recovered 92%/83%/96% and the sections 24%/9%/12%
/// -- the family moves the number by seventy points and the wording by five,
/// and no incise wording beat clap on the sections (McNemar p=0.13 and 0.06,
/// both against). The wording here is the better-measured of the two candidates
/// and ties clap pooled (30/59 either way, discordant 4-4, p=1.0).
///
/// So the reason this function exists is the half the replay could not see. The
/// harness frames stdout and stderr alike, so it scored clap's prose as if a
/// caller could read it. A `--json` caller cannot: clap exits before the flag is
/// parsed and emits **nothing on stdout at all**, so the plugin's `error` field
/// is absent rather than wrong. Routing through `out::usage` makes a missing
/// file the same shape as every other refusal. Whether the words are worth more
/// than clap's is, on the evidence, still open -- see `bench/FINDINGS.md`.
///
/// Two things stay as they were. The exit code is still 2: the invocation never
/// became a call, which is a different thing from a call the core refused, and
/// a caller that cannot tell those apart retries the wrong one. And the
/// `incise:` prefix stays, for the same reason -- these are the CLI's words.
fn path_of(m: &ArgMatches) -> Result<PathBuf, &'static str> {
    match m.get_one::<String>("file") {
        Some(p) => Ok(PathBuf::from(p)),
        None => Err("no file to edit was given.\n  \
             `path` is the markdown file itself, not a heading path inside it.\n  \
             Send it, e.g. \"docs/api.md\"."),
    }
}

fn edit(op: &str, m: &ArgMatches) -> i32 {
    let f = format_of(m);
    let path = match path_of(m) {
        Ok(p) => p,
        Err(msg) => return out::usage(&f, msg),
    };

    let args = match collect_args(m) {
        Ok(v) => v,
        Err(msg) => return out::usage(&f, &msg),
    };

    let bytes = match io::read_bytes(&path) {
        Ok(b) => b,
        Err(e) => return out::usage(&f, &e.0),
    };
    let before = match io::to_text(&bytes, &path) {
        Ok(s) => s,
        Err(e) => return out::usage(&f, &e.0),
    };
    let hash = io::sha256_hex(&bytes);

    if let Some(want) = m.get_one::<String>("if-match") {
        let want = want.trim().to_ascii_lowercase();
        if want.is_empty() || !want.chars().all(|c| c.is_ascii_hexdigit()) {
            return out::usage(&f, "--if-match takes a hex hash, or a prefix of one");
        }
        if !hash.starts_with(&want) {
            return out::stale(&f, &want, &hash, &path);
        }
    }

    match incise_core::apply_op(&before, op, Some(&args)) {
        Err(e) => out::refusal(&f, e.message()),
        Ok(after) => {
            let changed = after != before;
            let dry = m.get_flag("dry-run");
            // A no-op edit does not touch the file. The bytes would be
            // identical, so the only thing a write could change is the mtime,
            // and something is probably watching it.
            let written = changed && !dry;
            if written {
                if let Err(e) = io::write_atomic(&path, &after, &bytes) {
                    return out::usage(&f, &e.0);
                }
            }
            let hash = if changed {
                io::sha256_hex(after.as_bytes())
            } else {
                hash
            };
            // Dispatched on the op name, matching `armb.py:1467`. The two are
            // siblings rather than one function because `describe_change` is
            // derived from the two documents and not from the op: prepending
            // text to a file that opens with `---` moves the delimiter off line
            // 0, `frontmatter_span` stops finding a block, and the change reads
            // as the block having been *removed*. Folding them is a behaviour
            // change with its own evidence to gather, not a dispatch detail.
            let description = if op.starts_with("frontmatter-") {
                incise_core::describe_frontmatter_change(&before, &after)
            } else {
                incise_core::describe_change(&before, &after)
            };
            out::success(&f, &description, &hash, changed, written, &path)
        }
    }
}

/// The argument object: `--args`/`--args-file` if given, the per-key flags
/// otherwise.
///
/// A value that parses as JSON but is not an object is passed through rather
/// than rejected. `apply_op` has a refusal for exactly that case -- "arguments
/// for `op` must be an object, but arrived as an array" -- and it is a better
/// answer than anything this layer could write, because it quotes the value back.
fn collect_args(m: &ArgMatches) -> Result<Value, String> {
    if let Some(v) = raw_args(m)? {
        return Ok(v);
    }

    opargs::build(
        &|k| m.get_one::<String>(k).cloned(),
        &|k| {
            m.get_many::<String>(k)
                .map(|vs| vs.cloned().collect::<Vec<_>>())
        },
        &|k| m.get_flag(k),
    )
    .map_err(|e| e.0)
}

/// `--args` / `--args-file`, parsed, or `None` if neither was given.
///
/// Shared by `collect_args` and `collect_rows_args` rather than written twice:
/// the two commands build their per-key sugar differently, but the canonical
/// spelling has to mean the same thing on both, down to the refusal a caller
/// gets for JSON that does not parse.
fn raw_args(m: &ArgMatches) -> Result<Option<Value>, String> {
    let raw = match (
        m.get_one::<String>("args"),
        m.get_one::<String>("args-file"),
    ) {
        (Some(s), _) => s.clone(),
        (None, Some(p)) => {
            if p == "-" {
                std::io::read_to_string(std::io::stdin())
                    .map_err(|e| format!("cannot read arguments from stdin: {e}"))?
            } else {
                std::fs::read_to_string(p).map_err(|e| format!("cannot read {p}: {e}"))?
            }
        }
        (None, None) => return Ok(None),
    };

    incise_core::json::parse(raw.trim())
        .map(Some)
        .ok_or_else(|| format!("arguments are not valid JSON: {:?}", raw.trim()))
}

// --------------------------------------------------------------------------
// reads
// --------------------------------------------------------------------------

enum View {
    Outline,
    Tables,
    Lists,
    Front,
    Rows,
    Keys,
}

/// The read path, which is separate from `apply_op` by requirement (section 6.1):
/// these return text *about* a document rather than a document, so they are not
/// ops and do not appear in `OPS`.
fn read(m: &ArgMatches, view: View) -> i32 {
    let f = format_of(m);
    let path = match path_of(m) {
        Ok(p) => p,
        Err(msg) => return out::usage(&f, msg),
    };

    let bytes = match io::read_bytes(&path) {
        Ok(b) => b,
        Err(e) => return out::usage(&f, &e.0),
    };
    let content = match io::to_text(&bytes, &path) {
        Ok(s) => s,
        Err(e) => return out::usage(&f, &e.0),
    };
    let hash = io::sha256_hex(&bytes);
    // The renderers name the file in their own first line, so they are given the
    // path as written rather than one canonicalized behind the caller's back.
    let shown = path.display().to_string();

    let text = match view {
        View::Outline => render_section_outline(&content, &shown),
        View::Tables => render_table_list(&content, &shown),
        View::Lists => render_list_summary(&content, &shown),
        View::Front => render_frontmatter(&content, &shown),
        View::Rows => {
            let args = match collect_rows_args(m) {
                Ok(v) => v,
                Err(msg) => return out::usage(&f, &msg),
            };
            // `args::address` and `to_address` are the same two steps the ops
            // take, in the same order, so the read path and the write path
            // cannot come to disagree about what an address means.
            let address = match args::address(&args) {
                Ok(v) => to_address(v),
                Err(e) => return out::refusal(&f, e.message()),
            };
            // The structure first, then the renderer over it. `render_table_get`
            // would read the table a second time to produce the same rows.
            let got = match table_get(&content, &address, args.get("filter")) {
                Ok(r) => r,
                Err(e) => return out::refusal(&f, e.message()),
            };
            return out::rows_view(&f, &render_table_rows(&got), &got, &hash, &path);
        }
        View::Keys => {
            let args = match collect_keys_args(m) {
                Ok(v) => v,
                Err(msg) => return out::usage(&f, &msg),
            };
            // The structure first, then the renderer over it -- `rows`' reason,
            // and the same one: `render_frontmatter_get` would parse the block a
            // second time to answer the same question.
            let key = args.get("key");
            let got = match frontmatter_get(&content, key) {
                Ok(g) => g,
                Err(e) => return out::refusal(&f, e.message()),
            };
            let text = match render_frontmatter_get(&content, &shown, key) {
                Ok(t) => t,
                // Unreachable while the two agree: the renderer's only refusals
                // come from the call above. Answered rather than asserted
                // because the core owns which of them refuses first.
                Err(e) => return out::refusal(&f, e.message()),
            };
            return out::keys_view(&f, &text, &got, &hash, &path);
        }
    };

    out::view(&f, &text, &hash, &path)
}

/// `rows` builds its object from `--args` when it is given one, and otherwise
/// from the per-key flags, which are a subset of the full set -- so this does it
/// directly rather than through `opargs::build`, which would offer keys this
/// command has no argument for.
fn collect_rows_args(m: &ArgMatches) -> Result<Value, String> {
    if let Some(v) = raw_args(m)? {
        return Ok(v);
    }
    let mut pairs: Vec<(String, Value)> = Vec::new();

    if let Some(t) = m.get_one::<String>("table") {
        let table = match m.get_one::<i64>("ordinal") {
            None => Value::Str(t.clone()),
            Some(n) => Value::Object(vec![
                ("heading".to_string(), Value::Str(t.clone())),
                ("ordinal".to_string(), Value::Int(*n)),
            ]),
        };
        pairs.push(("table".to_string(), table));
    } else if m.get_one::<i64>("ordinal").is_some() {
        return Err(
            "--ordinal says which table sharing that heading, so it needs \
                    --table beside it."
                .to_string(),
        );
    }

    if let Some(items) = m.get_many::<String>("filter") {
        let mut inner = Vec::new();
        for item in items {
            let (k, v) = item
                .split_once('=')
                .ok_or_else(|| format!("--filter takes COLUMN=VALUE, but got {item:?}"))?;
            inner.push((k.to_string(), Value::Str(v.to_string())));
        }
        pairs.push(("filter".to_string(), Value::Object(inner)));
    }

    Ok(Value::Object(pairs))
}

/// `keys` builds its object the way `collect_rows_args` does, and for the same
/// reason: `opargs::build` would offer this command eighteen keys it has no
/// argument for.
///
/// No key is an empty object rather than `{"key": null}`, because the two are
/// the same call only by the core's choice and writing the second here would
/// make that choice twice.
fn collect_keys_args(m: &ArgMatches) -> Result<Value, String> {
    if let Some(v) = raw_args(m)? {
        return Ok(v);
    }
    let mut pairs: Vec<(String, Value)> = Vec::new();
    if let Some(k) = m.get_one::<String>("key") {
        pairs.push(("key".to_string(), Value::Str(k.clone())));
    }
    Ok(Value::Object(pairs))
}

fn hash(m: &ArgMatches) -> i32 {
    let f = format_of(m);
    let path = match path_of(m) {
        Ok(p) => p,
        Err(msg) => return out::usage(&f, msg),
    };
    match io::read_bytes(&path) {
        Err(e) => out::usage(&f, &e.0),
        Ok(bytes) => {
            let h = io::sha256_hex(&bytes);
            if f.json {
                println!(
                    "{{\"ok\": true, \"hash\": {}, \"path\": {}}}",
                    incise_core::json::dumps_str(&h),
                    incise_core::json::dumps_str(&path.display().to_string()),
                );
            } else {
                println!("{h}");
            }
            out::EXIT_OK
        }
    }
}

fn print_schema(m: &ArgMatches) -> i32 {
    match m.get_one::<String>("tool") {
        None => println!("{}", schema::SCHEMAS),
        Some(name) => match schema::one(name) {
            Some(one) => println!("{one}"),
            // Unreachable: clap's value_parser holds it to `schema::TOOLS`.
            None => return out::EXIT_USAGE,
        },
    }
    out::EXIT_OK
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_command_tree_is_well_formed() {
        cli().debug_assert();
    }

    #[test]
    fn every_op_the_core_has_is_a_subcommand() {
        let cmd = cli();
        let names: Vec<&str> = cmd.get_subcommands().map(|s| s.get_name()).collect();
        for op in incise_core::OPS {
            assert!(names.contains(op), "no subcommand for {op}");
        }
        // And nothing hyphenated that the core does not have -- an op the CLI
        // invented would refuse at `apply_op` with a message that reads as the
        // core's, which is the worst place to find out.
        for name in &names {
            if name.contains('-') {
                assert!(incise_core::OPS.contains(name), "{name} is not an op");
            }
        }
    }

    #[test]
    fn an_unknown_op_reaches_the_core_rather_than_clap() {
        // The refusal a typo produces is the core's sentence, which names all
        // fifteen. Section 1.2 measured recovery from it.
        let e = incise_core::apply_op("", "table-add-rows", None).unwrap_err();
        assert!(e
            .message()
            .starts_with("unknown operation \"table-add-rows\". Valid: "));
        assert!(cli()
            .try_get_matches_from(["incise", "table-add-rows", "x.md"])
            .is_ok());
    }
}
