//! The fourth op family, and the first whose specification is a corpus file
//! rather than a section of REQUIREMENTS: `corpus/frontmatter/rich.md:37-43`
//! names key order, a leading comment, an inline comment on a sibling, two
//! block scalar styles and one quoted key, and requires every one of them
//! byte-identical after `frontmatter-set build.jobs 8`. [`crate::front`] is what
//! makes that reachable — an edit rewrites one line's value and no other line
//! is touched at all.
//!
//! Two ops, not three: `frontmatter-set` creates a key as readily as it changes
//! one, so a separate `-add` would be a second name for one behaviour and a
//! second way for a model to pick wrong. [`frontmatter_get`] is a read and
//! stays out of `OPS` for the reason `table_get` does — it returns text *about*
//! a document rather than a document.

use crate::describe::{line_counts, plural};
use crate::error::{OpError, Result};
use crate::front::{find_frontmatter, format_path, parse_path, Entry, Fmt, FrontMatter, Kind, Seg};
use crate::json::{self, Value};
use crate::similar::get_close_matches;

/// The block, with TOML refused.
///
/// `verb` arrives already conjugated. A caller that passes a stem and lets this
/// add the `s` writes `incise delete froms YAML`, and a refusal is the product
/// (§5.3) — it is read by a model that has to decide what to do next, and a
/// sentence that has visibly been assembled by string arithmetic is one more
/// reason not to believe the rest of it.
///
/// [`crate::scan::frontmatter_span`] accepts `+++` on purpose: the list and
/// section parsers only need to know which lines to skip, and skipping a TOML
/// block is as correct as skipping a YAML one. An op cannot be that relaxed.
/// `corpus/hazards/toml-frontmatter.md` states the requirement and the failure
/// it guards against — "a YAML parser accepting some of this by accident and
/// writing back a mangled block" — so the format is checked here, once, before
/// any op can reach the entries.
fn front(content: &str, verb: &str) -> Result<FrontMatter> {
    let fm = find_frontmatter(content);
    if fm.present && fm.fmt != Some(Fmt::Yaml) {
        return Err(OpError::new(format!(
            "this file's frontmatter is TOML (`{}`), and incise {verb} YAML \
             (`---`) frontmatter only.\n  Tables, lists and sections in this \
             file are unaffected; only frontmatter ops stop here.",
            fm.delim
        )));
    }
    Ok(fm)
}

/// A frontmatter key is a dotted path, as a string.
fn check_key(value: Option<&Value>) -> Result<Vec<Seg>> {
    match value {
        Some(Value::Str(s)) => parse_path(s).ok_or_else(|| {
            OpError::new(format!(
                "`key` is not a readable frontmatter path.\n  Got: {}\n  Send a \
                 dotted path, e.g. \"build.jobs\", or an indexed one, e.g. \
                 \"authors[0].role\".",
                json::py_repr_str(s)
            ))
        }),
        None | Some(Value::Null) => Err(OpError::new(
            "`key` is required: it says which frontmatter key to change.\n  \
             Send a dotted path, e.g. \"build.jobs\".",
        )),
        Some(v) => Err(OpError::new(format!(
            "`key` must be a string, but arrived as {}.\n  Got: {}\n  Send a \
             dotted path, e.g. \"build.jobs\".",
            v.type_name(),
            json::py_repr(v)
        ))),
    }
}

/// A frontmatter value is one scalar. A structure is refused, not written.
///
/// [`crate::args::check_cell`]'s reasoning, one family over: a nested object
/// stringified into a cell was silent corruption, and a nested object written
/// into a YAML value would be the same thing with a Python repr in it. Writing
/// a real nested block is a different edit and needs a different op, which is
/// why this names the key rather than suggesting a spelling.
///
/// `None` here is the argument being **absent**, which is a refusal;
/// `Some(Value::Null)` is an explicit null, which is a value. The two are the
/// oracle's `_MISSING` and `None`, and collapsing them would make
/// `frontmatter-set key` mean `frontmatter-set key null`.
fn check_front_value(value: Option<&Value>) -> Result<Option<&Value>> {
    match value {
        None => Err(OpError::new(
            "`value` is required: it says what to set the key to.\n  Send null \
             to set the key to an empty (YAML null) value.",
        )),
        Some(v @ (Value::Object(_) | Value::Array(_))) => Err(OpError::new(format!(
            "`value` must be a single value, but arrived as {}.\n  Got: {}\n  A \
             frontmatter key holds one scalar; set its leaf keys individually.",
            v.type_name(),
            json::py_repr(v)
        ))),
        Some(v) => Ok(Some(v)),
    }
}

/// A value as the bytes that go after the colon.
///
/// **Quoting is decided by the text, not by the JSON type it arrived as.**
/// `8` and `"8"` produce the same byte, and that is deliberate: a tool schema
/// cannot express YAML's scalar types, every arm's calls arrive as JSON, and
/// quoting a value because the transport happened to carry it as a string would
/// measure JSON rather than the model. §6.5's own example is
/// `frontmatter-set build.jobs 8` writing `8`.
///
/// Quotes go on only where the text would not survive being read back plain: an
/// empty value, leading or trailing space, a leading indicator character, an
/// embedded `: ` or ` #`. Those are the cases where writing it bare changes the
/// document's structure rather than its value.
fn yaml_scalar(value: Option<&Value>) -> String {
    let s = match value {
        None | Some(Value::Null) => return String::new(),
        Some(Value::Bool(true)) => return "true".to_string(),
        Some(Value::Bool(false)) => return "false".to_string(),
        // `repr(value)`, because CPython's float repr is not Rust's `{}` —
        // `1e16` prints as `1e+16` there and `10000000000000000` here.
        Some(Value::Float(f)) => json::py_float_repr(*f),
        // `str(value)`, not `repr`: a string keeps its own characters. For
        // every other scalar the two agree.
        Some(Value::Str(s)) => s.clone(),
        Some(Value::Int(n)) => n.to_string(),
        Some(Value::BigInt(d)) => d.clone(),
        Some(v) => json::py_repr(v),
    };
    if needs_quotes(&s) {
        return quote(&s);
    }
    s
}

fn needs_quotes(s: &str) -> bool {
    s.is_empty()
        || s != crate::scan::py_strip(s)
        || s.starts_with([
            '-', '?', ':', ',', '[', ']', '{', '}', '#', '&', '*', '!', '|', '>', '\'', '"', '%',
            '@', '`',
        ])
        || s.contains(": ")
        || s.contains(" #")
        || s.contains('\n')
        || s.contains('\t')
}

fn quote(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

/// A new key's own bytes. Existing keys are never re-spelled.
fn yaml_key(name: &Seg) -> String {
    let s = match name {
        Seg::Key(k) => k.clone(),
        Seg::Index(n) => n.clone(),
    };
    if s.is_empty()
        || s != crate::scan::py_strip(&s)
        || s.contains(':')
        || s.contains('#')
        || s.starts_with([
            '-', '?', ',', '[', ']', '{', '}', '&', '*', '!', '|', '>', '\'', '"', '%', '@', '`',
        ])
    {
        return quote(&s);
    }
    s
}

/// "No such key", with the paths that do exist.
///
/// `missing` is the deepest segment that could not be resolved and `wanted` is
/// what the caller asked for; when they differ the message says so, because
/// "no key `build.cache.size`" on a file that has `build` sends a model hunting
/// for a typo in the wrong segment.
fn no_front_key(fm: &FrontMatter, missing: &[Seg], wanted: &[Seg]) -> OpError {
    let have: Vec<String> = fm.entries.iter().map(|e| format_path(&e.path)).collect();
    let want = format_path(missing);
    let near = get_close_matches(&want, &have, 3, 0.6);
    let mut lines = vec![format!("no frontmatter key `{want}`.")];
    if missing != wanted {
        lines.push(format!(
            "  `{}` needs it to exist first.",
            format_path(wanted)
        ));
    }
    // A key whose own name contains a dot is unreachable: `a.b` is read as two
    // segments before anything looks at the document, so no spelling of `key`
    // addresses it. Saying so is the difference between a model trying another
    // spelling and a model trying the same one four times.
    let literal = wanted
        .iter()
        .map(|s| match s {
            Seg::Key(k) => k.as_str(),
            Seg::Index(n) => n.as_str(),
        })
        .collect::<Vec<_>>()
        .join(".");
    if fm
        .entries
        .iter()
        .any(|e| e.path.len() == 1 && e.path[0] == Seg::Key(literal.clone()))
    {
        lines.push(format!(
            "  This file has a single key *named* `{literal}`. A dot always \
             separates path segments, so that key cannot be addressed."
        ));
    }
    if !near.is_empty() {
        lines.push(format!("  Near matches: {}", near.join(", ")));
    }
    if !have.is_empty() {
        let shown = &have[..have.len().min(12)];
        let more = if have.len() == shown.len() {
            String::new()
        } else {
            format!(", ... ({} more)", have.len() - 12)
        };
        lines.push(format!("  Keys: {}{more}", shown.join(", ")));
    } else {
        lines.push("  The frontmatter block has no keys.".to_string());
    }
    OpError::new(lines.join("\n"))
}

/// Every entry written under `path`, at any depth.
fn front_children<'a>(fm: &'a FrontMatter, path: &[Seg]) -> Vec<&'a Entry> {
    fm.entries
        .iter()
        .filter(|e| e.path.len() > path.len() && e.path.starts_with(path))
        .collect()
}

/// What a container entry holds, for a refusal that names the cost.
fn holds(entry: &Entry) -> &'static str {
    match entry.kind {
        Kind::Map => "a map",
        Kind::Seq => "a sequence",
        Kind::Block => "a block scalar",
        _ => "a map on its `-` line",
    }
}

/// One key of [`frontmatter_get`]'s answer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrontKey {
    pub path: String,
    pub kind: &'static str,
    pub value: String,
    pub lines: usize,
}

/// The block as structure: present, format, and every path with its value.
///
/// Off `OPS` by requirement (§6.1): it returns text about a document rather
/// than a document. `absent` and `empty` are distinct states here and not two
/// spellings of falsy, because `corpus/frontmatter/absent.md:17` and
/// `empty.md:6` both require a caller to be able to tell them apart.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrontState {
    pub state: &'static str,
    /// `None` where the oracle's dict holds `None`: no block, so no format.
    pub format: Option<Fmt>,
    pub keys: Vec<FrontKey>,
}

pub fn frontmatter_get(content: &str, key: Option<&Value>) -> Result<FrontState> {
    let fm = front(content, "reads")?;
    // An explicit null `key` is no key, not a bad one. The oracle's parameter
    // defaults to `None` and it tests `if key is not None`, so a call carrying
    // `"key": null` and a call carrying no `key` at all arrive identically —
    // which is the opposite of `frontmatter-set`, where absent is a refusal.
    // The two ops differ because here the argument is optional.
    let key = key.filter(|v| !v.is_null());
    let mut entries: Vec<&Entry> = fm.entries.iter().collect();
    if key.is_some() {
        let path = check_key(key)?;
        if !fm.has(&path) {
            return Err(no_front_key(&fm, &path, &path));
        }
        entries.retain(|e| e.path.starts_with(&path));
    }
    Ok(FrontState {
        state: if !fm.present {
            "absent"
        } else if fm.entries.is_empty() {
            "empty"
        } else {
            "present"
        },
        format: fm.fmt,
        keys: entries
            .iter()
            .map(|e| FrontKey {
                path: format_path(&e.path),
                kind: e.kind.as_str(),
                value: e.value.clone(),
                lines: e.end - e.line + 1,
            })
            .collect(),
    })
}

/// The block's own lines, or `None` if there is no block.
fn front_text(content: &str, fm: &FrontMatter) -> Option<String> {
    if !fm.present {
        return None;
    }
    let lines: Vec<&str> = content.split('\n').collect();
    Some(lines[fm.start..=fm.end].join("\n"))
}

/// Everything but the frontmatter block, for "did anything else move?".
///
/// Leading blank lines come off both sides, because the blank line between a
/// block and the document belongs to the block: creating one on
/// `corpus/frontmatter/absent.md` inserts that separator, and reporting it as a
/// second, vaguer change to the body would describe one edit twice.
fn strip_front(content: &str) -> String {
    let fm = find_frontmatter(content);
    let rest = if !fm.present {
        content.to_string()
    } else {
        content
            .split('\n')
            .skip(fm.end + 1)
            .collect::<Vec<_>>()
            .join("\n")
    };
    rest.trim_start_matches('\n').to_string()
}

/// Paths in `src` and not in `other`, each with the count written under it.
///
/// Only the outermost such path speaks: an ancestor that is itself new accounts
/// for everything beneath it, so a subtree reports as one note and a count
/// rather than as one sentence per leaf.
fn absent_roots<'a>(
    src: &[(&'a [Seg], &Entry)],
    other: &[(&[Seg], &Entry)],
) -> Vec<(&'a [Seg], usize)> {
    fn has(set: &[(&[Seg], &Entry)], p: &[Seg]) -> bool {
        set.iter().any(|(q, _)| *q == p)
    }
    let mut out = Vec::new();
    for (p, _) in src {
        if has(other, p) {
            continue;
        }
        if (1..p.len()).any(|n| has(src, &p[..n]) && !has(other, &p[..n])) {
            continue;
        }
        let under = src
            .iter()
            .filter(|(q, _)| q.len() > p.len() && q.starts_with(p))
            .count();
        out.push((*p, under));
    }
    out
}

/// (notes, whether a line tally is wanted) for a change to the block.
fn front_notes(before: &str, after: &str) -> (Vec<String>, bool) {
    let fb = find_frontmatter(before);
    let fa = find_frontmatter(after);
    if front_text(before, &fb) == front_text(after, &fa) {
        return (Vec::new(), false);
    }
    if !fb.present {
        return (
            vec![format!(
                "added a frontmatter block with {}",
                plural(fa.top().len(), "key")
            )],
            true,
        );
    }
    if !fa.present {
        return (vec!["removed the frontmatter block".to_string()], true);
    }

    let (b, a) = (fb.by_path_map(), fa.by_path_map());
    let (mut notes, mut tally) = (Vec::new(), false);
    for (path, e) in &a {
        if let Some((_, be)) = b.iter().find(|(q, _)| q == path) {
            if be.value != e.value && e.kind != Kind::Item {
                notes.push(format!(
                    "set `{}` to {}",
                    format_path(path),
                    if e.value.is_empty() {
                        "an empty value"
                    } else {
                        e.value.as_str()
                    }
                ));
            }
        }
    }
    // A subtree collapses to its root, for `run_notes`' reason: deleting `tags`
    // removes four entries and four sentences bury the one fact.
    for (verb, src, other) in [("added", &a, &b), ("removed", &b, &a)] {
        for (p, under) in absent_roots(src, other) {
            tally = true;
            let extra = if under > 0 {
                format!(" and {} under it", plural(under, "key"))
            } else {
                String::new()
            };
            notes.push(format!(
                "{verb} the frontmatter key `{}`{extra}",
                format_path(p)
            ));
        }
    }
    if notes.is_empty() {
        notes.push("changed the frontmatter block".to_string());
        tally = true;
    }
    (notes, tally)
}

/// [`crate::describe_change`], for the one family it does not describe.
///
/// Deliberately *not* folded into it. That function is derived from the two
/// documents rather than from the op name, so a fold would re-describe edits it
/// already has an answer for — prepending text to a file that opens with `---`
/// moves the delimiter off line 0, the span is gone, and the block reads as
/// *removed*. Mirroring the oracle's split keeps `difftest.py` comparing the
/// same function on both sides; folding is a behaviour change with its own
/// enumeration to run, not part of a port.
///
/// What it buys is S14's finding: `describe_change` alone reports every
/// frontmatter edit as "changed text outside any heading", which is true — the
/// block is outside every heading — and useless. A model that asked to change
/// `build.jobs` and typed `build.jobz` is told here that it *added* a key,
/// which is the one sentence that catches the typo. [`render_frontmatter`]
/// cannot do it: it omits scalar values on purpose, so it cannot testify that a
/// value changed.
pub fn describe_frontmatter_change(before: &str, after: &str) -> String {
    if before == after {
        return "Applied, but the document is unchanged.".to_string();
    }
    let (mut notes, mut tally_wanted) = front_notes(before, after);
    // The block's notes come first, and the body fallback fires only for a
    // change they cannot account for — otherwise one `frontmatter-set` is
    // described twice, once correctly and once vaguely.
    if notes.is_empty() || strip_front(before) != strip_front(after) {
        notes.push("changed text outside the frontmatter block".to_string());
        tally_wanted = true;
    }
    let mut tally = Vec::new();
    if tally_wanted {
        let (added, removed) = line_counts(before, after);
        if added > 0 {
            tally.push(format!("+{}", plural(added, "line")));
        }
        if removed > 0 {
            tally.push(format!("-{}", plural(removed, "line")));
        }
    }
    let head = format!("Applied: {}.", notes.join("; "));
    if tally.is_empty() {
        head
    } else {
        format!("{head} ({}.)", tally.join(", "))
    }
}

/// The compact structural summary a model sees instead of the block.
///
/// `list_tables`' contract, one family over: every path needed to *choose* a
/// key, and no scalar values. Arm B's premise is that the model addresses an
/// edit it cannot see, and the instruction is what supplies the new value. The
/// *kinds* stay, because they are what says `build` cannot be set to a scalar
/// and `build.jobs` can.
pub fn render_frontmatter(content: &str, path: &str) -> String {
    let fm = find_frontmatter(content);
    if !fm.present {
        return format!("Frontmatter in `{path}`: none. The file starts with content.");
    }
    if fm.fmt != Some(Fmt::Yaml) {
        return format!(
            "Frontmatter in `{path}`: TOML (`{}`). incise edits YAML (`---`) \
             frontmatter only.",
            fm.delim
        );
    }
    if fm.entries.is_empty() {
        return format!(
            "Frontmatter in `{path}`: YAML, present but empty. The delimiters \
             are there and the block has no keys."
        );
    }
    let mut out = vec![format!(
        "Frontmatter in `{path}`: YAML, {} top-level keys",
        fm.top().len()
    )];
    for e in &fm.entries {
        let what = match e.kind {
            Kind::Item => continue,
            Kind::Map => format!("{} below it", plural(fm.children_of(&e.path).len(), "key")),
            Kind::Seq => plural(fm.children_of(&e.path).len(), "item"),
            Kind::Block => format!("{} block scalar, {} lines", block_style(e), e.end - e.line),
            Kind::Null => "empty (null)".to_string(),
            Kind::Scalar => "scalar".to_string(),
        };
        out.push(format!("  {:<24} {what}", format_path(&e.path)));
    }
    out.join("\n")
}

fn block_style(e: &Entry) -> &'static str {
    if e.value.starts_with('|') {
        "literal"
    } else {
        "folded"
    }
}

/// Model-readable form of [`frontmatter_get`]: the same paths, with values.
///
/// The counterpart to [`render_frontmatter`], and the reason the project needs
/// both. That one is the summary the *first* turn is handed, and it omits every
/// scalar value on purpose: Arm B's premise is that the model addresses an edit
/// it cannot see. This one is what comes back when the model asks, and its whole
/// content is the values — a read that showed what the summary already showed
/// would be a tool that answers nothing, which is precisely the state
/// `set-dana-role` measured (F-frontmatter: the summary lists `authors[0].name`
/// and `authors[1].name` and no scheme offered any way to learn which one is
/// Dana, so both arms guessed).
///
/// Emitted as aligned `path` / `value` and deliberately **not** as YAML.
/// `render_table_get`'s reason applies unchanged — a result has no author's
/// formatting to preserve, so the honest form is the one that claims nothing —
/// and there is a second reason here: re-emitting a YAML block invites the model
/// to send a YAML document back as a `value`, which is the failure §6.5 exists
/// to avoid. The paths printed are the paths `key` accepts, so what the model
/// reads is already spelled the way it must spell it back.
///
/// Calls [`frontmatter_get`] rather than re-deriving the entry set, so the two
/// cannot disagree about whether a key exists or in what order the refusals
/// fire; the raw lines are consulted only for block scalars, whose value is not
/// on the key's own line.
pub fn render_frontmatter_get(content: &str, path: &str, key: Option<&Value>) -> Result<String> {
    let got = frontmatter_get(content, key)?;
    if got.state == "absent" {
        return Ok(format!(
            "Frontmatter in `{path}`: none. The file starts with content."
        ));
    }
    if got.state == "empty" {
        return Ok(format!(
            "Frontmatter in `{path}`: YAML, present but empty. The delimiters \
             are there and the block has no keys."
        ));
    }

    let fm = find_frontmatter(content);
    let lines: Vec<&str> = content.split('\n').collect();
    let wanted: Vec<&str> = got.keys.iter().map(|k| k.path.as_str()).collect();
    let mut head = format!("Frontmatter in `{path}`: YAML");
    match key.filter(|v| !v.is_null()) {
        // The key as the caller spelled it, not as `format_path` would: the
        // heading echoes the request. Only a string can get this far, since
        // `check_key` has already run inside `frontmatter_get`.
        Some(k) => head.push_str(&format!(", under `{}`", k.as_str().unwrap_or(""))),
        None => head.push_str(&format!(", {} top-level keys", fm.top().len())),
    }
    let mut out = vec![head];
    for e in &fm.entries {
        let p = format_path(&e.path);
        if !wanted.contains(&p.as_str()) {
            continue;
        }
        let kids = fm.children_of(&e.path);
        let what = match e.kind {
            Kind::Map => format!("{} below it", plural(kids.len(), "key")),
            Kind::Seq => plural(kids.len(), "item"),
            // A sequence item that is itself a map (`authors[0]`) has no value
            // of its own — `e.value` holds the first line of the mapping, which
            // would print `name: Peter` beside a path whose children print the
            // same two facts again. The children are the answer; this is a
            // signpost to them.
            Kind::Item if !kids.is_empty() => format!("{} below it", plural(kids.len(), "key")),
            Kind::Item => e.value.clone(),
            Kind::Null => "(empty)".to_string(),
            Kind::Block => {
                let body = &lines[e.line + 1..=e.end];
                out.push(format!(
                    "  {p:<24} {} block scalar, {}:",
                    block_style(e),
                    plural(body.len(), "line")
                ));
                // The body is the value, so it is shown. Indented past the
                // column the values sit in, and never re-wrapped: a folded
                // scalar's line breaks are the thing the author chose and the
                // thing an edit has to leave alone.
                out.extend(
                    body.iter()
                        .map(|ln| format!("      {}", crate::scan::py_strip(ln))),
                );
                continue;
            }
            Kind::Scalar => e.value.clone(),
        };
        out.push(format!("  {p:<24} {what}"));
    }
    Ok(out.join("\n"))
}

/// (parent entry, insert-after line, indent) for a new key.
///
/// The three shapes a new key can arrive in: top level, under an existing map,
/// and under something that is not a map. The third is a refusal and not a
/// silent append at the root, which is what "parse what parses, refuse the rest"
/// means here.
fn front_parent<'a>(
    fm: &'a FrontMatter,
    path: &[Seg],
) -> Result<(Option<&'a Entry>, usize, usize)> {
    let parent = &path[..path.len() - 1];
    if parent.is_empty() {
        // `default=fm.start` is reached only on a block with no entries at all,
        // where the opening delimiter is the line to insert after.
        let last = fm.entries.iter().map(|e| e.end).max().unwrap_or(fm.start);
        return Ok((None, last, 0));
    }
    let Some(pe) = fm.by_path(parent) else {
        // Walk out to the deepest ancestor that does exist, so the message
        // names the segment that actually broke rather than the whole path.
        let mut missing = parent;
        for n in (1..parent.len()).rev() {
            if fm.has(&parent[..n]) {
                missing = &parent[..n + 1];
                break;
            }
        }
        return Err(no_front_key(fm, missing, path));
    };
    if pe.kind != Kind::Map {
        return Err(OpError::new(format!(
            "`{}` holds {}, so `{}` cannot be added under it.\n  Set `{}` \
             itself, or add the key somewhere that holds a map.",
            format_path(parent),
            holds(pe),
            format_path(path),
            format_path(parent)
        )));
    }
    let kids = fm.children_of(parent);
    let indent = kids.first().map_or(pe.indent() + 2, |k| k.indent());
    Ok((Some(pe), pe.end, indent))
}

/// The line ending a line inserted into this block should carry.
///
/// The block's own, when there is a block; otherwise the document's first line,
/// which is the only convention a file with no frontmatter has to offer.
/// `table_eol`'s rule — read the ending off the thing being edited — with the
/// narrower scope that a created block has nothing of its own yet.
fn front_eol(content: &str, fm: &FrontMatter) -> String {
    if fm.present {
        return fm.eol.clone();
    }
    let first = content.split('\n').next().unwrap_or("");
    if first.ends_with('\r') {
        "\r".to_string()
    } else {
        String::new()
    }
}

/// Set one key, changing nothing else in the file.
///
/// Three cases, in the order they are checked: the key exists and its value line
/// is rewritten in place; the key is new and a line is inserted under its
/// parent; the file has no block at all and one is created above the document.
pub fn frontmatter_set(
    content: &str,
    key: Option<&Value>,
    value: Option<&Value>,
) -> Result<String> {
    let fm = front(content, "edits")?;
    let path = check_key(key)?;
    let text = yaml_scalar(check_front_value(value)?);
    let eol = front_eol(content, &fm);
    // The key as the caller spelled it, for the two refusals that quote it back.
    let raw_key = key.and_then(Value::as_str).unwrap_or("");

    if !fm.present {
        if path.len() > 1 {
            return Err(OpError::new(format!(
                "this file has no frontmatter block, and `{raw_key}` is nested, \
                 so there is nothing for it to attach to.\n  Creating a block \
                 can set a top-level key -- `{}` -- but not a path inside one.",
                format_path(&path[..1])
            )));
        }
        if matches!(path[0], Seg::Index(_)) {
            return Err(OpError::new(format!(
                "this file has no frontmatter block, and `{raw_key}` addresses \
                 a sequence item.\n  Creating a block can set a top-level key; \
                 a sequence has to exist before it can be indexed."
            )));
        }
        let line = format!(
            "{}{}",
            yaml_key(&path[0]),
            if text.is_empty() {
                ":".to_string()
            } else {
                format!(": {text}")
            }
        );
        // A blank line goes between the new block and the document, unless the
        // document already opens with one. `corpus/frontmatter/absent.md:5`
        // names that blank line as part of what must be right.
        let gap = if content.starts_with('\n') || content.starts_with("\r\n") {
            String::new()
        } else {
            format!("{eol}\n")
        };
        let delim = if fm.delim.is_empty() {
            "---"
        } else {
            &fm.delim
        };
        return Ok(format!(
            "{delim}{eol}\n{line}{eol}\n---{eol}\n{gap}{content}"
        ));
    }

    let mut lines: Vec<String> = content.split('\n').map(str::to_string).collect();
    if let Some(e) = fm.by_path(&path) {
        // A sequence item holding one scalar is set like any other scalar --
        // `tags[1]` is `- two`, and rewriting it is the same line surgery with
        // the dash in the prefix instead of a key. An item holding a *map* is
        // not, and falls through to the refusal below with everything else that
        // has something written under it.
        let settable = matches!(e.kind, Kind::Scalar | Kind::Null)
            || (e.kind == Kind::Item && front_children(&fm, &path).is_empty());
        if !settable {
            return Err(OpError::new(format!(
                "`{}` holds {}, so setting it to a single value would delete \
                 what is under it.\n  Set one of its own keys instead, or \
                 delete `{}` first if replacing it is the intent.",
                format_path(&path),
                holds(e),
                format_path(&path)
            )));
        }
        lines[e.line] = e.rebuilt(Some(&text));
        return Ok(lines.join("\n"));
    }

    if matches!(path[path.len() - 1], Seg::Index(_)) {
        return Err(OpError::new(format!(
            "`{}` addresses a sequence item that does not exist.\n  \
             `frontmatter-set` changes a key's value; it does not extend a \
             sequence.",
            format_path(&path)
        )));
    }
    let (_, after, indent) = front_parent(&fm, &path)?;
    let new = format!(
        "{}{}{}",
        " ".repeat(indent),
        yaml_key(&path[path.len() - 1]),
        if text.is_empty() {
            ":".to_string()
        } else {
            format!(": {text}")
        }
    );
    lines.insert(after + 1, new + &eol);
    Ok(lines.join("\n"))
}

/// Remove one key and everything written under it.
///
/// The delimiters are never removed. Deleting the last key leaves `---\n---`,
/// which `corpus/frontmatter/empty.md:9-12` requires: taking the delimiters away
/// is a structural change the caller did not ask for, and a file with an empty
/// block is a state the family can already describe.
pub fn frontmatter_delete(content: &str, key: Option<&Value>) -> Result<String> {
    let fm = front(content, "deletes from")?;
    let path = check_key(key)?;
    if !fm.present {
        return Err(OpError::new(format!(
            "this file has no frontmatter block, so there is no `{}` to \
             delete.\n  The document starts with content; nothing needs \
             removing.",
            key.and_then(Value::as_str).unwrap_or("")
        )));
    }
    let Some(e) = fm.by_path(&path) else {
        return Err(no_front_key(&fm, &path, &path));
    };
    if !e.key_text.is_empty() && e.prefix.trim_end_matches(' ').ends_with('-') {
        let item = format_path(&path[..path.len() - 1]);
        return Err(OpError::new(format!(
            "`{}` is written on the `-` line of `{item}`, so deleting it alone \
             would take the item marker with it.\n  Delete `{item}` to remove \
             the whole item, or set the key to null to empty it.",
            format_path(&path)
        )));
    }
    let lines: Vec<&str> = content.split('\n').collect();
    let mut out = lines[..e.line].to_vec();
    out.extend_from_slice(&lines[e.end + 1..]);
    Ok(out.join("\n"))
}
