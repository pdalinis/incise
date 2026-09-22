//! The CLI's contract, driven through the built binary.
//!
//! Unit tests inside the crate can check that argv becomes the right JSON
//! object. They cannot check the things this front end actually risks getting
//! wrong, all of which are about the process boundary: which stream a message
//! leaves on, what the exit code says, and whether the file on disk afterwards
//! is the one the op returned. So these spawn `incise`.
//!
//! Every case runs on a copy in a temporary directory. The corpus is frozen --
//! `bench/FINDINGS.md` quotes per-file results against those files -- so a test
//! that edited one in place would invalidate a measurement to check a print
//! statement.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

const BIN: &str = env!("CARGO_BIN_EXE_incise");

fn corpus(rel: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("corpus")
        .join(rel)
}

/// A scratch copy of a corpus fixture, removed when the guard drops.
struct Scratch {
    dir: PathBuf,
    file: PathBuf,
    original: Vec<u8>,
}

impl Scratch {
    fn of(rel: &str) -> Scratch {
        // Several cases copy the same fixture and the harness runs them on
        // parallel threads, so the directory name needs something that is unique
        // per *call* and not merely per process. A counter is; a timestamp is
        // not, as two threads reading the clock in the same nanosecond found out.
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let n = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);

        let src = corpus(rel);
        let name = src.file_name().unwrap().to_string_lossy().into_owned();
        let dir = std::env::temp_dir().join(format!("incise-cli-{}-{n}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let original = fs::read(&src).unwrap();
        let file = dir.join(name);
        fs::write(&file, &original).unwrap();
        Scratch {
            dir,
            file,
            original,
        }
    }

    fn now(&self) -> Vec<u8> {
        fs::read(&self.file).unwrap()
    }

    fn text(&self) -> String {
        String::from_utf8(self.now()).unwrap()
    }

    fn is_untouched(&self) -> bool {
        self.now() == self.original
    }

    fn run(&self, args: &[&str]) -> Run {
        let mut argv: Vec<String> = Vec::new();
        for a in args {
            argv.push(if *a == "@" {
                self.file.display().to_string()
            } else {
                a.to_string()
            });
        }
        Run::of(Command::new(BIN).args(&argv).output().unwrap())
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}

struct Run {
    code: i32,
    out: String,
    err: String,
}

impl Run {
    fn of(o: Output) -> Run {
        Run {
            code: o.status.code().unwrap_or(-1),
            out: String::from_utf8_lossy(&o.stdout).into_owned(),
            err: String::from_utf8_lossy(&o.stderr).into_owned(),
        }
    }
}

fn plain(args: &[&str]) -> Run {
    Run::of(Command::new(BIN).args(args).output().unwrap())
}

const ADD: &[&str] = &[
    "table-add-row",
    "@",
    "--table",
    "Components",
    "--values",
    "Component=gizmo",
    "--values",
    "Status=new",
    "--values",
    "Owner=ada",
];

// --------------------------------------------------------------------------
// what a success prints
// --------------------------------------------------------------------------

/// Section 5.4 and section 9 criterion 11. S14 measured the alternatives: an
/// outline in place of the sentence cost 8/300 redundant continuations and three
/// destroyed documents, and printing both measured the same as the outline
/// alone. So the test is not "the output is useful" but "the output is *only*
/// the sentence".
#[test]
fn a_success_prints_the_description_and_nothing_else() {
    let s = Scratch::of("tables/aligned.md");
    let before = s.text();
    let run = s.run(ADD);

    assert_eq!(run.code, 0, "stderr: {}", run.err);
    assert_eq!(run.err, "");
    assert_eq!(
        run.out,
        format!("{}\n", incise_core::describe_change(&before, &s.text())),
    );
    assert_eq!(run.out.lines().count(), 1);
    assert!(
        !run.out.contains('|'),
        "the document leaked into the result: {}",
        run.out
    );
}

#[test]
fn the_edit_is_a_splice_and_the_rest_of_the_file_is_byte_identical() {
    let s = Scratch::of("tables/aligned.md");
    let before = String::from_utf8(s.original.clone()).unwrap();
    s.run(ADD);
    let after = s.text();

    // Section 5.2: everything outside the targeted range is byte-identical, and
    // the one sanctioned exception -- re-padding -- is scoped to the table's own
    // lines. So the prose either side of the table has to come through untouched,
    // byte for byte, including the blank lines around it.
    let head = before.split("| Component").next().unwrap();
    let tail = before.split("|\n\n").last().unwrap();
    assert!(!head.is_empty() && !tail.is_empty());
    assert!(after.starts_with(head), "the text above the table moved");
    assert!(after.ends_with(tail), "the text below the table moved");

    // And the change really is confined to the table: every line that is not a
    // table row is where it was.
    let non_row = |t: &str| -> Vec<String> {
        t.lines()
            .filter(|l| !l.trim_start().starts_with('|'))
            .map(String::from)
            .collect()
    };
    assert_eq!(non_row(&before), non_row(&after));
}

#[test]
fn a_no_op_says_so_and_leaves_the_file_alone() {
    let s = Scratch::of("tables/aligned.md");
    let run = s.run(&["table-realign", "@", "--table", "Components"]);
    assert_eq!(run.code, 0, "stderr: {}", run.err);
    assert_eq!(run.out, "Applied, but the document is unchanged.\n");
    assert!(s.is_untouched());
}

// --------------------------------------------------------------------------
// refusals
// --------------------------------------------------------------------------

/// Section 5.3: the message is the product, and Arm B measured 75% one-turn
/// recovery against these exact sentences. The library's string is the
/// reference, so this fails if the CLI ever wraps, trims or re-words one.
#[test]
fn a_refusal_is_the_library_s_sentence_verbatim_on_stderr() {
    let s = Scratch::of("tables/aligned.md");
    let run = s.run(&[
        "table-update-cell",
        "@",
        "--table",
        "Components",
        "--where",
        "Component=nope",
        "--column",
        "Status",
        "--value",
        "ok",
    ]);

    let args = incise_core::json::parse(
        r#"{"table": "Components", "where": {"Component": "nope"}, "column": "Status", "value": "ok"}"#,
    )
    .unwrap();
    let expected = incise_core::apply_op(&s.text(), "table-update-cell", Some(&args)).unwrap_err();

    assert_eq!(run.code, 1);
    assert_eq!(run.out, "");
    assert_eq!(run.err, format!("Error: {}\n", expected.message()));
    assert!(s.is_untouched());
}

/// An op name clap does not know is handed to the core rather than answered
/// here, so a typo gets the sentence that names the fifteen ops that exist.
#[test]
fn an_unknown_op_gets_the_core_s_list_not_clap_s_apology() {
    let run = plain(&["table-add-rows", "nothing.md"]);
    assert_eq!(run.code, 1);
    assert_eq!(
        run.err,
        format!(
            "Error: {}\n",
            incise_core::apply_op("", "table-add-rows", None)
                .unwrap_err()
                .message()
        )
    );
    assert!(run.err.contains("table-add-row, table-update-cell"));
}

/// The same argument, one level down: a missing file is answered by incise, in
/// incise's voice, naming `path` -- which is what the argument is called in the
/// tool schema a model is given, where `<FILE>` and a `Usage:` line describe an
/// argv it never wrote. Arm C measured 8 of 40 such first calls recovering
/// within four turns, against section 5.3's 75% for a refusal in this voice.
///
/// It stays exit 2 -- the invocation never became a call -- and it honours
/// `--json`, which clap could not, because clap exits before the flag is read.
#[test]
fn a_missing_file_is_incise_s_sentence_and_names_path() {
    for argv in [
        vec!["table-add-row", "--table", "Components"],
        vec!["tables"],
        vec!["hash"],
    ] {
        let run = plain(&argv);
        assert_eq!(run.code, 2, "{argv:?} -> {}", run.err);
        assert_eq!(run.out, "", "{argv:?}");
        assert!(
            run.err.starts_with("incise: no file to edit was given"),
            "{argv:?}: {}",
            run.err
        );
        // None of clap's furniture: not the `<FILE>` the caller never typed, not
        // a usage line, not an invitation to run `--help` it cannot act on.
        assert!(!run.err.contains("<FILE>"), "{argv:?}: {}", run.err);
        assert!(!run.err.contains("Usage:"), "{argv:?}: {}", run.err);
        // And it says what to do next, which is the half section 5.3 measures.
        assert!(run.err.contains("Send it"), "{argv:?}: {}", run.err);

        let mut json_argv = argv.clone();
        json_argv.push("--json");
        let json = plain(&json_argv);
        assert_eq!(json.code, 2);
        assert_eq!(
            json.err, "",
            "{json_argv:?}: the JSON caller got prose on stderr"
        );
        let parsed = incise_core::json::parse(json.out.trim()).expect(&json.out);
        let obj = match &parsed {
            incise_core::json::Value::Object(kv) => kv.clone(),
            other => panic!("{other:?}"),
        };
        let get = |k: &str| obj.iter().find(|(n, _)| n == k).map(|(_, v)| v.clone());
        assert_eq!(get("usage"), Some(incise_core::json::Value::Bool(true)));
        match get("error") {
            Some(incise_core::json::Value::Str(s)) => {
                assert!(s.starts_with("no file to edit was given"), "{s}");
                // The prefix belongs to the human stream only: a caller reading
                // the JSON gets the sentence, not the program's name in front
                // of it.
                assert!(!s.starts_with("incise:"), "{s}");
            }
            other => panic!("{other:?}"),
        }
    }
}

/// Arguments that are JSON but not an object reach the core, which quotes them
/// back. Rejecting them here would produce a different sentence for the same
/// call, which section 5.3 counts as a regression rather than as strictness.
#[test]
fn args_that_are_json_but_not_an_object_are_the_core_s_to_refuse() {
    let s = Scratch::of("tables/aligned.md");
    let run = s.run(&["table-add-row", "@", "--args", "[1, 2]"]);
    assert_eq!(run.code, 1);
    assert!(
        run.err
            .contains("must be an object, but arrived as an array"),
        "{}",
        run.err
    );
    assert!(run.err.contains("Got: [1, 2]"), "{}", run.err);
}

// --------------------------------------------------------------------------
// exit codes: the machine-readable half of the contract
// --------------------------------------------------------------------------

#[test]
fn the_four_outcomes_have_four_codes() {
    let s = Scratch::of("tables/aligned.md");

    // 0: applied.
    assert_eq!(s.run(ADD).code, 0);
    // 1: refused -- the call is wrong and the caller should change it.
    assert_eq!(
        s.run(&["table-delete-row", "@", "--table", "Nope", "--where", "a=b"])
            .code,
        1
    );
    // 2: the invocation never became a call at all.
    assert_eq!(s.run(&["table-add-row", "@", "--args", "{nope}"]).code, 2);
    assert_eq!(plain(&["tables", "/no/such/file.md"]).code, 2);
    // 3: the call was right and the world moved.
    assert_eq!(
        s.run(&["table-realign", "@", "--if-match", "deadbeef"])
            .code,
        3
    );
}

// --------------------------------------------------------------------------
// section 5.5: dry run, if-match, atomic write
// --------------------------------------------------------------------------

#[test]
fn a_dry_run_describes_the_edit_and_writes_nothing() {
    let s = Scratch::of("tables/aligned.md");
    let mut args = ADD.to_vec();
    args.push("--dry-run");
    let dry = s.run(&args);

    assert_eq!(dry.code, 0);
    assert!(s.is_untouched(), "--dry-run wrote to the file");
    // The sentence on stdout is the real one, so a dry run diffs against the
    // edit it predicts. The caveat goes on stderr, where it cannot be mistaken
    // for the measured text.
    assert!(dry.err.contains("dry run"), "{}", dry.err);

    let wet = s.run(ADD);
    assert_eq!(dry.out, wet.out);
    assert!(!s.is_untouched());
}

#[test]
fn if_match_takes_any_prefix_of_the_hash_and_names_both_on_a_miss() {
    let s = Scratch::of("tables/aligned.md");
    let hash = plain(&["hash", &s.file.display().to_string()])
        .out
        .trim()
        .to_string();
    assert_eq!(hash.len(), 64);

    for n in [8usize, 12, 40, 64] {
        let mut args = vec!["table-realign", "@", "--if-match", &hash[..n]];
        args.push("--quiet");
        assert_eq!(s.run(&args).code, 0, "prefix of {n} rejected");
    }

    let miss = s.run(&["table-realign", "@", "--if-match", "0000000000"]);
    assert_eq!(miss.code, 3);
    assert!(
        miss.err.contains("0000000000") && miss.err.contains(&hash),
        "{}",
        miss.err
    );

    // And the hash moves when the file does.
    let edit = s.run(ADD);
    assert_eq!(edit.code, 0, "stderr: {}", edit.err);
    let stale = s.run(&["table-realign", "@", "--if-match", &hash[..12]]);
    assert_eq!(stale.code, 3, "stdout: {} stderr: {}", stale.out, stale.err);
}

#[test]
fn the_hash_the_cli_reports_is_the_hash_of_the_file_on_disk() {
    let s = Scratch::of("tables/aligned.md");
    let run = s.run(ADD);
    assert_eq!(run.code, 0);
    let claimed = s.run(&["hash", "@"]).out.trim().to_string();

    // `--json` carries the new hash so a caller can chain an edit without
    // re-reading the file. If it ever describes the *old* contents, the chain
    // silently edits a version that no longer exists.
    let json = s.run(&["table-realign", "@", "--json"]);
    assert!(
        json.out.contains(&format!("\"hash\": \"{claimed}\"")),
        "{}",
        json.out
    );
}

// --------------------------------------------------------------------------
// bytes in, bytes out
// --------------------------------------------------------------------------

#[test]
fn crlf_survives_a_round_trip_through_the_front_end() {
    let s = Scratch::of("hazards/crlf.md");
    assert!(s.original.windows(2).any(|w| w == b"\r\n"));
    let run = s.run(&["outline", "@"]);
    assert_eq!(run.code, 0, "stderr: {}", run.err);
    assert!(s.is_untouched());

    // A read cannot change the file; an edit must not change the endings of the
    // lines it did not touch.
    let sections = incise_core::find_sections(&s.text());
    if let Some(first) = sections.first() {
        let edit = s.run(&[
            "section-append",
            "@",
            "--section",
            &first.text,
            "--text",
            "x",
        ]);
        if edit.code == 0 {
            let after = s.text();
            let crlf_before = s.original.windows(2).filter(|w| *w == b"\r\n").count();
            let crlf_after = after
                .as_bytes()
                .windows(2)
                .filter(|w| *w == b"\r\n")
                .count();
            assert!(crlf_after >= crlf_before, "an edit converted CRLF to LF");
        }
    }
}

/// Encoding is unspecified in REQUIREMENTS.md, so the front end decides -- and
/// this is the decision. A BOM would reach the core as an ordinary character in
/// front of the first `#`, and every address into the document would then miss
/// with a refusal about a section that is plainly there. Section 5.5: refuse and
/// explain rather than produce a plausible-but-wrong edit.
#[test]
fn a_byte_order_mark_is_refused_by_name_rather_than_silently_absorbed() {
    let s = Scratch::of("tables/aligned.md");
    let mut bytes = vec![0xEF, 0xBB, 0xBF];
    bytes.extend_from_slice(&s.original);
    fs::write(&s.file, &bytes).unwrap();

    let run = s.run(&["outline", "@"]);
    assert_eq!(run.code, 2);
    assert!(run.err.contains("byte-order mark"), "{}", run.err);
    assert_eq!(s.now(), bytes, "a refused read still modified the file");
}

// --------------------------------------------------------------------------
// reads
// --------------------------------------------------------------------------

/// `render_table_list` is not a convenience view -- it *is* the Arm B prompt
/// (section 11, Tier 2), and `python3 bench/incise_ops.py <file>` prints the
/// same string. So stdout carries it and nothing else, and the hash section 5.5
/// asks for goes to stderr rather than onto the end of it.
#[test]
fn a_read_prints_the_renderer_s_string_with_nothing_appended() {
    for (sub, rel) in [
        ("tables", "tables/multiple-per-section.md"),
        ("outline", "sections/deep-nesting.md"),
        ("lists", "lists/nested-mixed.md"),
        ("front", "frontmatter/rich.md"),
    ] {
        let s = Scratch::of(rel);
        let run = s.run(&[sub, "@"]);
        assert_eq!(run.code, 0, "{sub}: {}", run.err);

        let shown = s.file.display().to_string();
        let expected = match sub {
            "tables" => incise_core::render_table_list(&s.text(), &shown),
            "outline" => incise_core::render_section_outline(&s.text(), &shown),
            "front" => incise_core::render_frontmatter(&s.text(), &shown),
            _ => incise_core::ops::list::render_list_summary(&s.text(), &shown),
        };
        assert_eq!(
            run.out,
            format!("{expected}\n"),
            "{sub} is not the renderer's string"
        );
        assert_eq!(run.err, format!("hash: {}\n", sha_of(&s.original)));
    }
}

#[test]
fn rows_addresses_a_table_the_same_way_an_edit_does() {
    let s = Scratch::of("tables/multiple-per-section.md");
    let listed = s.run(&["tables", "@"]).out;

    // The two-table-per-heading case is the one an ordinal exists for, and the
    // one B6 found the model failing. If the read path resolved `--ordinal`
    // differently from the write path, a model would read one table and edit
    // another with the same words.
    if listed.contains("ordinal") || listed.matches("rows)").count() > 1 {
        let zero = s.run(&["rows", "@", "--table", "Two tables", "--ordinal", "0"]);
        let one = s.run(&["rows", "@", "--table", "Environments", "--ordinal", "1"]);
        if zero.code == 0 && one.code == 0 {
            assert_ne!(zero.out, one.out, "--ordinal selected the same table twice");
        }
    }

    // And an ordinal with nothing to qualify is a usage fault, not a refusal:
    // the core was never asked anything.
    assert_eq!(s.run(&["rows", "@", "--ordinal", "0"]).code, 2);
}

/// `--args` is the canonical spelling on `rows` as on every op.
///
/// The per-key flags cannot say everything an argument object can. A filter
/// value that is not a string is the clearest case: `--filter COLUMN=VALUE` is
/// flat text, so `check_cell`'s refusals for a boolean, a number or a null
/// inside a filter are unreachable through the flags and reachable through
/// `--args`. A harness that had to translate a model's object into flags would
/// be answering those itself, which is the one thing Arm C must not do.
#[test]
fn rows_takes_the_whole_argument_object_as_json() {
    let s = Scratch::of("tables/multiple-per-section.md");

    // The nesting the flags reach only because `collect_rows_args` builds it.
    let viaargs = s.run(&[
        "rows",
        "@",
        "--args",
        r#"{"table": {"heading": "Environments", "ordinal": 1}}"#,
    ]);
    let viaflags = s.run(&["rows", "@", "--table", "Environments", "--ordinal", "1"]);
    assert_eq!(viaargs.code, viaflags.code, "{}", viaargs.err);
    assert_eq!(viaargs.out, viaflags.out, "--args and the flags disagree");

    // A typed filter value: the core's sentence, not the CLI's.
    let typed = s.run(&[
        "rows",
        "@",
        "--args",
        r#"{"table": "Networks", "filter": {"Purpose": true}}"#,
    ]);
    assert_eq!(
        typed.code, 1,
        "a typed filter value is a refusal: {}",
        typed.out
    );
    assert!(
        typed.err.starts_with("Error: ") && typed.err.contains("filter"),
        "not the core's refusal: {:?}",
        typed.err
    );

    // Mixing the two spellings is refused, as it is on an op: `--args` is
    // canonical and the flags are sugar over it, so precedence never arises.
    assert_eq!(
        s.run(&["rows", "@", "--args", "{}", "--table", "Networks"])
            .code,
        2
    );
    // Not JSON at all is the CLI's own fault to report, and it is a usage fault.
    let bad = s.run(&["rows", "@", "--args", "{", "--json"]);
    assert_eq!(bad.code, 2);
    assert!(bad.out.contains("\"usage\": true"), "{}", bad.out);
}

/// `rows --json` carries the structure beside the string, and they agree.
///
/// Section 6.1 defers letting a *model* choose an output shape and says the
/// structured/renderer split gives both for free at the call site. This is that
/// call site: a caller grading a read needs `TableRows`, and parsing it back out
/// of the rendered table would make the grade a golden for the renderer --
/// exactly what `bench/grade.py`'s `check_table_read_result` refuses to be.
///
/// `difftest.py` drives the core directly through `examples/oracle_cases.rs`, so
/// nothing it runs can see this envelope. It is covered here or nowhere.
#[test]
fn rows_json_carries_the_structure_the_text_was_rendered_from() {
    let s = Scratch::of("tables/multiple-per-section.md");
    let spec = r#"{"table": {"heading": "Environments", "ordinal": 2}}"#;
    let run = s.run(&["rows", "@", "--args", spec, "--json"]);
    assert_eq!(run.code, 0, "{}{}", run.out, run.err);

    let payload = incise_core::json::parse(run.out.trim()).expect("not JSON");
    let rows = payload.get("rows").expect("no `rows` in the envelope");

    // The same read, taken from the core by the same two steps the CLI takes.
    let args = incise_core::json::parse(spec).unwrap();
    let address =
        incise_core::ops::dispatch::to_address(incise_core::args::address(&args).unwrap());
    let got = incise_core::table_get(&s.text(), &address, None).unwrap();

    assert_eq!(rows.get("heading").unwrap().as_str().unwrap(), got.heading);
    assert_eq!(strings(rows.get("columns").unwrap()), got.columns);
    assert_eq!(
        rows.get("matched").unwrap(),
        &incise_core::json::Value::Int(got.matched as i64)
    );
    assert_eq!(
        rows.get("total").unwrap(),
        &incise_core::json::Value::Int(got.total as i64)
    );
    let cells: Vec<Vec<String>> = match rows.get("rows").unwrap() {
        incise_core::json::Value::Array(rs) => rs.iter().map(strings).collect(),
        other => panic!("rows is not an array: {other:?}"),
    };
    assert_eq!(
        cells, got.rows,
        "the structure is not the rows the core read"
    );

    // The string is unmoved: still the renderer's, byte for byte, so nothing a
    // model reads changed when the structure was added beside it.
    assert_eq!(
        payload.get("text").unwrap().as_str().unwrap(),
        incise_core::render_table_rows(&got)
    );

    // Without `--json` this is the plain read it always was.
    let plain_run = s.run(&["rows", "@", "--args", spec]);
    assert_eq!(
        plain_run.out,
        format!("{}\n", incise_core::render_table_rows(&got))
    );
    assert!(s.is_untouched(), "a read wrote to the file");
}

#[test]
fn items_json_carries_copyable_text_nesting_and_checkbox_state() {
    let s = Scratch::of("lists/nested-mixed.md");
    let spec = r#"{"list": {"heading": "Asterisk markers, four-space indent"}}"#;
    let run = s.run(&["items", "@", "--args", spec, "--json"]);
    assert_eq!(run.code, 0, "{}{}", run.out, run.err);

    let payload = incise_core::json::parse(run.out.trim()).expect("not JSON");
    let list = payload.get("list").expect("no `list` in the envelope");
    let items = match list.get("items").unwrap() {
        incise_core::json::Value::Array(items) => items,
        other => panic!("items is not an array: {other:?}"),
    };
    assert_eq!(items.len(), 5);
    assert_eq!(items[3].get("text").unwrap().as_str().unwrap(), "beta-two");
    assert_eq!(
        items[3].get("depth").unwrap(),
        &incise_core::json::Value::Int(1)
    );
    assert_eq!(
        items[3].get("parent").unwrap(),
        &incise_core::json::Value::Int(1)
    );
    assert_eq!(
        items[3].get("checked").unwrap(),
        &incise_core::json::Value::Null
    );

    let args = incise_core::json::parse(spec).unwrap();
    let address = incise_core::ops::list::list_address_fields(
        incise_core::args::list_address(&args).unwrap().as_ref(),
    );
    let got = incise_core::list_get(&s.text(), &address).unwrap();
    assert_eq!(
        payload.get("text").unwrap().as_str().unwrap(),
        incise_core::render_list_items(&got)
    );
    assert_eq!(
        s.run(&[
            "items",
            "@",
            "--list",
            "Asterisk markers, four-space indent"
        ])
        .out,
        format!("{}\n", incise_core::render_list_items(&got))
    );
    assert!(s.is_untouched(), "a read wrote to the file");
}

#[test]
fn json_refusals_keep_the_message_and_add_copyable_repair_data() {
    let s = Scratch::of("sections/deep-nesting.md");
    let run = s.run(&[
        "section-delete",
        "@",
        "--args",
        r#"{"section":"Install > macOS"}"#,
        "--json",
    ]);
    assert_eq!(run.code, 1, "{}{}", run.out, run.err);
    let payload = incise_core::json::parse(run.out.trim()).expect("not JSON");
    let message = payload.get("error").unwrap().as_str().unwrap();
    assert!(message.contains("subtree=true"), "{message}");
    let repair = payload.get("repair").expect("no repair object");
    assert_eq!(
        repair.get("code").unwrap().as_str().unwrap(),
        "subtree_confirmation_required"
    );
    assert_eq!(repair.get("argument").unwrap().as_str().unwrap(), "subtree");
    assert!(strings(repair.get("candidates").unwrap())
        .contains(&"Deep heading nesting > Install > macOS > Apple Silicon".to_string()));
    assert!(s.is_untouched(), "a refused deletion wrote to the file");
}

fn strings(v: &incise_core::json::Value) -> Vec<String> {
    match v {
        incise_core::json::Value::Array(items) => items
            .iter()
            .map(|i| i.as_str().expect("not a string").to_string())
            .collect(),
        other => panic!("not an array of strings: {other:?}"),
    }
}

// --------------------------------------------------------------------------
// frontmatter
// --------------------------------------------------------------------------

/// `keys --json` carries the structure beside the string, and they agree.
///
/// `rows --json`'s test, for the family that needs it more. `state` and
/// `format` appear in neither rendering: `absent` and `empty` are distinct by
/// requirement (`corpus/frontmatter/absent.md:17`, `empty.md:6`) and a TOML
/// block is reported by this read while the edit ops refuse it. A caller that
/// had to infer either from the rendered sentence would be parsing prose.
///
/// `difftest.py` drives the core directly, so it cannot see this envelope
/// either. It is covered here or nowhere.
#[test]
fn keys_json_carries_the_structure_the_text_was_rendered_from() {
    let s = Scratch::of("frontmatter/rich.md");
    let spec = r#"{"key": "build"}"#;
    let run = s.run(&["keys", "@", "--args", spec, "--json"]);
    assert_eq!(run.code, 0, "{}{}", run.out, run.err);

    let payload = incise_core::json::parse(run.out.trim()).expect("not JSON");
    let front = payload
        .get("frontmatter")
        .expect("no `frontmatter` in the envelope");

    let key = incise_core::json::parse(spec).unwrap();
    let got = incise_core::frontmatter_get(&s.text(), key.get("key")).unwrap();

    assert_eq!(front.get("state").unwrap().as_str().unwrap(), got.state);
    assert_eq!(front.get("format").unwrap().as_str().unwrap(), "yaml");
    let keys = match front.get("keys").unwrap() {
        incise_core::json::Value::Array(ks) => ks,
        other => panic!("keys is not an array: {other:?}"),
    };
    assert_eq!(
        keys.len(),
        got.keys.len(),
        "the structure is not the keys the core read"
    );
    for (j, k) in keys.iter().zip(&got.keys) {
        assert_eq!(j.get("path").unwrap().as_str().unwrap(), k.path);
        assert_eq!(j.get("kind").unwrap().as_str().unwrap(), k.kind);
        assert_eq!(j.get("type").unwrap().as_str().unwrap(), k.value_type);
        assert_eq!(j.get("value").unwrap().as_str().unwrap(), k.value);
        assert_eq!(
            j.get("lines").unwrap(),
            &incise_core::json::Value::Int(k.lines as i64)
        );
    }

    // The string is unmoved: still the renderer's, byte for byte.
    let shown = s.file.display().to_string();
    let text = incise_core::render_frontmatter_get(&s.text(), &shown, key.get("key")).unwrap();
    assert_eq!(payload.get("text").unwrap().as_str().unwrap(), text);

    // Without `--json` this is the plain read it always was.
    assert_eq!(
        s.run(&["keys", "@", "--args", spec]).out,
        format!("{text}\n")
    );

    // `--key` is the same call, and mixing the spellings is refused as it is
    // everywhere else.
    assert_eq!(
        s.run(&["keys", "@", "--key", "build"]).out,
        format!("{text}\n")
    );
    assert_eq!(
        s.run(&["keys", "@", "--key", "build", "--args", "{}"]).code,
        2
    );

    // A key that is not there is the core's sentence, verbatim, on stderr.
    let miss = s.run(&["keys", "@", "--key", "nope"]);
    assert_eq!(miss.code, 1);
    assert!(
        miss.err.starts_with("Error: no frontmatter key `nope`."),
        "not the core's refusal: {:?}",
        miss.err
    );

    assert!(s.is_untouched(), "a read wrote to the file");
}

/// A frontmatter edit is described by `describe_frontmatter_change`, not by
/// `describe_change`.
///
/// The two are siblings by design (`ops/frontmatter.rs`), so the CLI dispatches
/// on the op name the way `armb.py:1467` does. They are not interchangeable:
/// `describe_change` is derived from the two documents, and a `frontmatter-set`
/// that rewrites one line inside the block is a change it can only describe as
/// text moving somewhere in the file.
#[test]
fn a_frontmatter_edit_gets_the_frontmatter_description() {
    let s = Scratch::of("frontmatter/rich.md");
    let before = s.text();
    let run = s.run(&[
        "frontmatter-set",
        "@",
        "--key",
        "build.jobs",
        "--value",
        "8",
    ]);
    assert_eq!(run.code, 0, "{}", run.err);

    let after = s.text();
    assert_eq!(
        run.out,
        format!(
            "{}\n",
            incise_core::describe_frontmatter_change(&before, &after)
        )
    );
    assert!(
        run.out.contains("build.jobs"),
        "the key is not named: {:?}",
        run.out
    );

    // The splice is one line. The comment on the sibling key, the key order and
    // the two block scalars are what `rich.md:37-43` exists to hold still.
    let moved: Vec<(&str, &str)> = before
        .lines()
        .zip(after.lines())
        .filter(|(a, b)| a != b)
        .collect();
    assert_eq!(moved.len(), 1, "more than one line moved: {moved:?}");
    assert_eq!(before.lines().count(), after.lines().count());
}

#[test]
fn a_frontmatter_existence_guard_refuses_with_structured_repair() {
    let s = Scratch::of("frontmatter/rich.md");
    let run = s.run(&[
        "frontmatter-set",
        "@",
        "--args",
        r#"{"key":"build.target","value":true,"must_absent":true}"#,
        "--json",
    ]);
    assert_eq!(run.code, 1, "{}{}", run.out, run.err);
    let payload = incise_core::json::parse(run.out.trim()).expect("not JSON");
    let repair = payload.get("repair").expect("no repair object");
    assert_eq!(
        repair.get("code").unwrap().as_str().unwrap(),
        "frontmatter_key_exists"
    );
    assert_eq!(repair.get("argument").unwrap().as_str().unwrap(), "key");
    assert_eq!(
        repair.get("received").unwrap().as_str().unwrap(),
        "build.target"
    );
    assert!(s.is_untouched(), "a refused guarded set wrote to the file");
}

// --------------------------------------------------------------------------
// the published schema
// --------------------------------------------------------------------------

#[test]
fn schema_publishes_the_five_measured_tools() {
    let all = plain(&["schema"]);
    assert_eq!(all.code, 0);
    for tool in [
        "table_edit",
        "list_edit",
        "section_edit",
        "frontmatter_edit",
        "table_get",
    ] {
        assert!(
            all.out.contains(&format!("\"name\": \"{tool}\"")),
            "{tool} missing"
        );
        let one = plain(&["schema", "--tool", tool]);
        assert_eq!(one.code, 0);
        assert!(one.out.trim().starts_with('{') && one.out.trim().ends_with('}'));
        assert!(one.out.contains(&format!("\"name\": \"{tool}\"")));
    }
    // S15, which the core cannot enforce because `resolve_section` accepts both
    // spellings: the section address is `heading`, and `path` is the file.
    let section = plain(&["schema", "--tool", "section_edit"]).out;
    assert!(section.contains("\"description\": \"File to edit.\""));
    let at = section.find("\"section\"").unwrap();
    assert!(section[at..].contains("\"heading\""));

    assert_eq!(plain(&["schema", "--tool", "nope"]).code, 2);
}

fn sha_of(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(bytes))
}
