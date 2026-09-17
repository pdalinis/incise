//! What the CLI prints, and what it deliberately does not.
//!
//! This module is short and the reasoning behind it is not, because the front
//! end is where a measured result can be quietly undone.
//!
//! **A successful edit prints one sentence.** Not the document, not an outline.
//! S14 measured the alternatives on the same tasks: returning the outline in
//! place of a description produced 8/300 redundant continuations -- the model
//! reading structure it had not asked for, deciding more work was implied -- and
//! three documents destroyed by the follow-up edit. Returning *both* the
//! description and the outline measured identically to the outline alone. The
//! subtraction is the requirement, so it lives in code rather than in taste.
//!
//! **A refusal is reproduced verbatim.** Section 5.3 makes the message the
//! product; Arm B measured 75% one-turn recovery against these exact sentences.
//! Wrapping, truncating or re-wording one is a behaviour change.
//!
//! **A read's output is byte-identical to the renderer's.** `render_table_list`
//! is not a convenience view -- it *is* the Arm B prompt (section 11, Tier 2),
//! and `python3 bench/incise_ops.py <file>` prints the same string. The content
//! hash section 5.5 asks for therefore goes beside it, on stderr, never appended
//! to it.
//!
//! **`rows --json` carries the structure as well as the string, and that is not
//! the deferred `format` argument.** Section 6.1 defers letting a *model* choose
//! its output shape -- "two renderers, not two arguments, until there is evidence
//! a model needs to choose" -- and says the structured/renderer split gives both
//! for free at the call site. This is that call site. A caller grading a read
//! needs the rows; parsing them back out of the rendered table would make every
//! grade a golden for the renderer, which is exactly what
//! `bench/grade.py`'s `check_table_read_result` is written to avoid. The text
//! field is unmoved, so nothing a model reads changes.

use std::path::Path;

use incise_core::json::dumps_str;
use incise_core::{Fmt, FrontState, TableRows};

pub const EXIT_OK: i32 = 0;
pub const EXIT_REFUSED: i32 = 1;
pub const EXIT_USAGE: i32 = 2;
pub const EXIT_STALE: i32 = 3;

pub struct Format {
    pub json: bool,
    pub quiet: bool,
}

/// A successful edit: the one sentence, and nothing else on stdout.
pub fn success(
    f: &Format,
    description: &str,
    hash: &str,
    changed: bool,
    written: bool,
    path: &Path,
) -> i32 {
    if f.json {
        println!(
            "{{\"ok\": true, \"description\": {}, \"hash\": {}, \"changed\": {}, \
             \"written\": {}, \"path\": {}}}",
            dumps_str(description),
            dumps_str(hash),
            changed,
            written,
            dumps_str(&path.display().to_string()),
        );
    } else if !f.quiet {
        println!("{description}");
        // The description is reproduced as-is even under `--dry-run`, so a dry
        // run and the real edit are diffable against each other. It says
        // "Applied", though, and under `--dry-run` nothing was -- so the part
        // that is not the measured sentence goes where it cannot be mistaken
        // for it.
        if changed && !written {
            eprintln!("dry run: {} not written", path.display());
        }
    }
    EXIT_OK
}

/// A read: the renderer's string, untouched.
pub fn view(f: &Format, text: &str, hash: &str, path: &Path) -> i32 {
    if f.json {
        println!(
            "{{\"ok\": true, \"text\": {}, \"hash\": {}, \"path\": {}}}",
            dumps_str(text),
            dumps_str(hash),
            dumps_str(&path.display().to_string()),
        );
    } else {
        println!("{text}");
        if !f.quiet {
            eprintln!("hash: {hash}");
        }
    }
    EXIT_OK
}

/// `rows`: [`view`] plus the structure the string was rendered from.
///
/// Only the `--json` form differs. Without `--json` this *is* [`view`] -- the
/// plain-text output of a read is the renderer's string and nothing else, which
/// is the guarantee at the top of this module.
///
/// `rows` is positional, mirroring [`TableRows::rows`], because a table may
/// legally repeat a header and keying by column name would report one cell's
/// value under every position that shares its name -- a false statement about
/// the document, from the op whose whole job is to report the document.
pub fn rows_view(f: &Format, text: &str, got: &TableRows, hash: &str, path: &Path) -> i32 {
    if !f.json {
        return view(f, text, hash, path);
    }
    println!(
        "{{\"ok\": true, \"text\": {}, \"rows\": {{\"heading\": {}, \"columns\": {}, \
         \"rows\": {}, \"matched\": {}, \"total\": {}}}, \"hash\": {}, \"path\": {}}}",
        dumps_str(text),
        dumps_str(&got.heading),
        dumps_strs(&got.columns),
        dumps_rows(&got.rows),
        got.matched,
        got.total,
        dumps_str(hash),
        dumps_str(&path.display().to_string()),
    );
    EXIT_OK
}

/// `keys`: [`view`] plus the structure, exactly as [`rows_view`] does it.
///
/// `state` and `format` are carried because neither appears in the rendered
/// string and they are the two fields a caller most needs: `absent` and `empty`
/// are distinct states by requirement (`corpus/frontmatter/absent.md:17` and
/// `empty.md:6`), and a TOML block is refused by the edit ops but reported by
/// this read. `format` is `null` when there is no block, which is the parser's
/// own answer rather than an invented third spelling.
pub fn keys_view(f: &Format, text: &str, got: &FrontState, hash: &str, path: &Path) -> i32 {
    if !f.json {
        return view(f, text, hash, path);
    }
    let keys: Vec<String> = got
        .keys
        .iter()
        .map(|k| {
            format!(
                "{{\"path\": {}, \"kind\": {}, \"value\": {}, \"lines\": {}}}",
                dumps_str(&k.path),
                dumps_str(k.kind),
                dumps_str(&k.value),
                k.lines,
            )
        })
        .collect();
    println!(
        "{{\"ok\": true, \"text\": {}, \"frontmatter\": {{\"state\": {}, \"format\": {}, \
         \"keys\": [{}]}}, \"hash\": {}, \"path\": {}}}",
        dumps_str(text),
        dumps_str(got.state),
        match got.format {
            Some(Fmt::Yaml) => "\"yaml\"".to_string(),
            Some(Fmt::Toml) => "\"toml\"".to_string(),
            None => "null".to_string(),
        },
        keys.join(", "),
        dumps_str(hash),
        dumps_str(&path.display().to_string()),
    );
    EXIT_OK
}

/// A JSON array of strings. Hand-written for the reason the crate has no serde:
/// `dumps_str` is the core's own escaper, and the one already proved against the
/// oracle by every refusal this CLI prints.
fn dumps_strs(items: &[String]) -> String {
    let inner: Vec<String> = items.iter().map(|s| dumps_str(s)).collect();
    format!("[{}]", inner.join(", "))
}

fn dumps_rows(rows: &[Vec<String>]) -> String {
    let inner: Vec<String> = rows.iter().map(|r| dumps_strs(r)).collect();
    format!("[{}]", inner.join(", "))
}

/// A refusal from the core, word for word.
pub fn refusal(f: &Format, message: &str) -> i32 {
    if f.json {
        println!("{{\"ok\": false, \"error\": {}}}", dumps_str(message));
    } else {
        eprintln!("Error: {message}");
    }
    EXIT_REFUSED
}

/// The file moved under a caller holding `--if-match`.
///
/// Its own exit code, because it is neither a refusal the model should re-word
/// its call to fix nor a usage fault: the call was right and the world changed.
/// A caller that cannot tell those apart retries the wrong one.
pub fn stale(f: &Format, want: &str, got: &str, path: &Path) -> i32 {
    let message = format!(
        "{} has changed since it was read. Expected a hash starting {want}, found {got}. \
         Read it again before editing.",
        path.display()
    );
    if f.json {
        println!(
            "{{\"ok\": false, \"stale\": true, \"error\": {}, \"hash\": {}}}",
            dumps_str(&message),
            dumps_str(got),
        );
    } else {
        eprintln!("Error: {message}");
    }
    EXIT_STALE
}

/// A fault in the invocation. Kept clearly apart from a refusal: these are the
/// CLI's own words, so they are prefixed with the CLI's own name.
pub fn usage(f: &Format, message: &str) -> i32 {
    if f.json {
        println!(
            "{{\"ok\": false, \"usage\": true, \"error\": {}}}",
            dumps_str(message)
        );
    } else {
        eprintln!("incise: {message}");
    }
    EXIT_USAGE
}
