//! The section family: append, replace-body, insert, delete, rename, set-level.
//!
//! Ported from `bench/incise_ops.py`, which is the oracle for every sentence in
//! here. The parser is already in [`crate::heading`]; this module is what the
//! ops do with it, and the difficulty is not the parsing.
//!
//! Three things make this family unlike tables and lists, and all three are
//! measured rather than assumed:
//!
//! * **A section has two ends.** `own_end` is where its own prose stops; `end`
//!   is where its subtree stops. `append` uses the first and `delete` uses the
//!   second, and swapping them is the difference between adding a paragraph and
//!   adding it after six subsections, or between deleting a heading and
//!   deleting 32 lines.
//! * **The level is derived, never passed** (S6/L4). `insert` takes a *position*
//!   relative to an anchor and works the level out; a `level` argument is a
//!   number the model would have to invent, and across 30
//!   `insert-release-at-top` trials the model wrote a level-3 heading by hand at
//!   levels 1, 2 and 4 — never at 3.
//! * **Two ops refuse things they could do.** `replace-body` refuses to discard
//!   a non-empty body without `overwrite` (S2: asked to *add* a line, the model
//!   called `replace-body` in five trials of ten), and `append` refuses a
//!   `heading` argument outright (S3: five in ten passed one, and got prose
//!   where a section should have been). Both convert a `wrong` into an
//!   `op_error`, which B3 measured as recoverable in one turn.
//!
//! What is deliberately *not* here is `describe_change`, the oracle's account of
//! what an op did to a document. It is not an op — nothing in `OPS` calls it —
//! and it needs `difflib.SequenceMatcher.get_opcodes`, where [`crate::similar`]
//! ports only the ratio. FINDINGS records it as the front end's to carry.

use crate::args::{self, check_heading_named, check_ordinal, PyInt};
use crate::error::{OpError, Repair, Result};
use crate::heading::{find_sections, heading_gap, inert_headings, Section};
use crate::json::{self, Value};
use crate::scan::{py_strip, split_lines, HeadingStyle};
use crate::similar::get_close_matches;

/// One addressable section, as the model sees it in the outline.
///
/// Unlike `list_tables` and `list_lists` this does NOT withhold the content
/// being addressed — the heading text *is* the address, so hiding it would leave
/// nothing to address with. What it withholds is every section's body, which is
/// the part an edit supplies.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SectionEntry {
    pub level: usize,
    pub path: String,
    pub text: String,
    pub style: &'static str,
    pub ordinal: usize,
    /// Whether the path is enough on its own. Anything false here is a section
    /// the model must pass an ordinal for, and the outline is where it finds
    /// that out — not the error message.
    pub unique: bool,
    pub has_body: bool,
    pub subsections: usize,
}

pub fn section_outline(content: &str) -> Vec<SectionEntry> {
    let secs = find_sections(content);
    let slugs: Vec<String> = secs.iter().map(|s| s.slug()).collect();
    let mut out = Vec::with_capacity(secs.len());
    for (n, s) in secs.iter().enumerate() {
        let slug = &slugs[n];
        out.push(SectionEntry {
            level: s.level,
            path: slug.clone(),
            text: s.text.clone(),
            style: s.style.as_str(),
            ordinal: slugs[..n].iter().filter(|p| *p == slug).count(),
            unique: slugs.iter().filter(|p| *p == slug).count() == 1,
            has_body: s.has_body(),
            subsections: secs.iter().filter(|o| o.parent == Some(n)).count(),
        });
    }
    out
}

pub fn render_section_outline(content: &str, path: &str) -> String {
    let entries = section_outline(content);
    // The example is taken from this document rather than being a fixed string.
    // A model shown `e.g. "Install > macOS"` while editing a changelog has to
    // infer that the separator generalizes; a model shown a path it can see in
    // the outline below does not. Nothing is leaked — every path here is already
    // printed.
    let hint = match entries.iter().find(|e| e.path.contains(" > ")) {
        Some(e) => format!("e.g. \"{}\"", e.path),
        None => "one heading per line, indented by level".to_string(),
    };
    let mut out = vec![format!(
        "Sections in `{path}` (address by heading path, {hint}):"
    )];
    for e in &entries {
        let mut bits = vec![if e.has_body {
            "body".to_string()
        } else {
            "no body of its own".to_string()
        }];
        if e.subsections > 0 {
            bits.push(format!(
                "{} subsection{}",
                e.subsections,
                if e.subsections > 1 { "s" } else { "" }
            ));
        }
        if !e.unique {
            bits.push(format!("DUPLICATE PATH -- needs ordinal {}", e.ordinal));
        }
        out.push(format!(
            "{}{}   ({})",
            "  ".repeat(e.level),
            e.text,
            bits.join(", ")
        ));
    }
    out.join("\n")
}

// --------------------------------------------------------------------------
// addressing
// --------------------------------------------------------------------------

/// The `section` argument split into the fields the resolver reads.
///
/// `path` and `heading` are two spellings of the same thing — the schemes under
/// test used both — and `path` wins when it is truthy, which is Python's `or`
/// and not a preference.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct SectionAddress {
    pub path: Option<Value>,
    pub heading: Option<Value>,
    pub ordinal: Option<Value>,
}

impl SectionAddress {
    pub fn none() -> Self {
        Self::default()
    }

    pub fn path(p: impl Into<String>) -> Self {
        SectionAddress {
            path: Some(Value::Str(p.into())),
            ..Default::default()
        }
    }

    pub fn with_ordinal(mut self, ordinal: i64) -> Self {
        self.ordinal = Some(Value::Int(ordinal));
        self
    }
}

impl From<&str> for SectionAddress {
    fn from(p: &str) -> Self {
        SectionAddress::path(p)
    }
}

/// A bare string is `{"path": ...}`; an object gives up its three fields
/// unexamined, because the oracle looks at them inside the resolver.
pub fn section_address_fields(value: Option<&Value>) -> SectionAddress {
    match value {
        Some(Value::Str(s)) => SectionAddress::path(s.clone()),
        Some(Value::Object(pairs)) => SectionAddress {
            path: pairs
                .iter()
                .find(|(k, _)| k == "path")
                .map(|(_, v)| v.clone()),
            heading: pairs
                .iter()
                .find(|(k, _)| k == "heading")
                .map(|(_, v)| v.clone()),
            ordinal: pairs
                .iter()
                .find(|(k, _)| k == "ordinal")
                .map(|(_, v)| v.clone()),
        },
        _ => SectionAddress::none(),
    }
}

/// Find the one section an address names, or fail with the candidates.
///
/// Matching runs narrowest-first, and a pass that finds several stops rather
/// than falling through to a looser one: an exact full path that hits three
/// sections is ambiguous, and trying a suffix match next would only widen it.
///
/// ```text
/// full path exact -> full path case-folded -> path suffix -> suffix folded
/// ```
///
/// The suffix pass is what makes `"macOS"` legal shorthand for
/// `"Install > macOS"` in a file that has only one, and what makes it refuse
/// with all three in `deep-nesting.md`, which has three.
pub fn resolve_section(content: &str, address: &SectionAddress) -> Result<Section> {
    let secs = find_sections(content);
    let entries = section_outline(content);

    // `address.get("path") or address.get("heading")`: a falsy `path` falls
    // through, so `{"path": "", "heading": "Install"}` addresses by heading.
    // The label travels with the value because the refusal has to quote the key
    // the caller actually sent, not the one this family happens to prefer.
    let (want, want_label): (Option<&Value>, &str) = match &address.path {
        Some(p) if json::py_truthy(p) => (Some(p), "section.path"),
        _ => (address.heading.as_ref(), "section.heading"),
    };
    // No null-filter here: `check_ordinal` maps an explicit `null` to "no
    // ordinal" itself, which is what `_check_ordinal` does in the oracle. The
    // filter this line used to carry became dead the moment the check went in,
    // and `section-ordinal-null` surviving its own mutation is how that showed.
    let want_o: Option<&Value> = address.ordinal.as_ref();

    // Both up front, as `locate_table` does, so a malformed `ordinal` is
    // refused even when the heading it accompanies does not exist -- and ahead
    // of the no-headings refusal, because a call that could never be well
    // formed is answered before the document is consulted.
    //
    // This is what made the section family the odd one out. `check_heading` was
    // never called here, so `{"path": 1}` was stringified to `"1"` and hunted
    // for; `check_ordinal` was never called, so `{"ordinal": "0"}` addressed a
    // table and a list and refused a section. Section 6.4 asks the three
    // families to teach one habit, and this was the line where they stopped.
    let want_str_checked = check_heading_named(want, want_label)?;
    let want_int = check_ordinal(want_o, "section")?;

    if secs.is_empty() {
        return Err(OpError::new(
            "this file has no headings, so no section can be addressed.",
        ));
    }
    let want_str = want_str_checked.unwrap_or_default();
    if want_str.trim().is_empty() {
        return Err(OpError::new(format!(
            "`section` is required: the heading path of the section to act on.\n  This file has {} sections. Candidates: {}{}",
            secs.len(),
            entries.iter().take(8).map(|e| format!("\"{}\"", e.path)).collect::<Vec<_>>().join("; "),
            if entries.len() > 8 { "; ..." } else { "" }
        )));
    }

    let segs: Vec<&str> = want_str
        .split('>')
        .map(py_strip)
        .filter(|p| !p.is_empty())
        .collect();
    let lower: Vec<String> = segs.iter().map(|p| p.to_lowercase()).collect();

    // `len(p) >= len(q) and p[len(p) - len(q):] == q`, with an empty `q` matching
    // everything — which `section: ">"` reaches, and which must go on matching
    // everything so the refusal names every candidate.
    let exact =
        |s: &Section| s.path.len() == segs.len() && s.path.iter().zip(&segs).all(|(a, b)| a == b);
    let folded = |s: &Section| {
        s.path.len() == lower.len()
            && s.path
                .iter()
                .zip(&lower)
                .all(|(a, b)| a.to_lowercase() == *b)
    };
    let suffix = |s: &Section| {
        s.path.len() >= segs.len()
            && s.path[s.path.len() - segs.len()..]
                .iter()
                .zip(&segs)
                .all(|(a, b)| a == b)
    };
    let suffix_folded = |s: &Section| {
        s.path.len() >= lower.len()
            && s.path[s.path.len() - lower.len()..]
                .iter()
                .zip(&lower)
                .all(|(a, b)| a.to_lowercase() == *b)
    };
    let preds: [&dyn Fn(&Section) -> bool; 4] = [&exact, &folded, &suffix, &suffix_folded];

    for pred in preds {
        let hits: Vec<usize> = secs
            .iter()
            .enumerate()
            .filter(|(_, s)| pred(s))
            .map(|(i, _)| i)
            .collect();
        if hits.is_empty() {
            continue;
        }
        // If their full paths differ, the fix is a longer path and the message
        // shows exactly which ones — an ordinal would work too but teaches the
        // wrong habit. Identical paths are the only case where an ordinal is
        // the answer, and `duplicate-siblings.md` requires it. This split is
        // computed before the ordinal branch because a *missed* ordinal has to
        // make it too: `{"heading": "Errors", "ordinal": 9}` against a file
        // with twenty-one distinct sections named "Errors" is an ambiguity,
        // not an out-of-range ordinal, and listing twenty-one zeroes as the
        // valid ordinals is advice that cannot be taken.
        let paths: Vec<String> = hits.iter().map(|i| secs[*i].slug()).collect();
        let mut uniq = paths.clone();
        uniq.sort();
        uniq.dedup();
        let distinct = uniq.len() == paths.len();
        if let Some(o) = &want_int {
            for &i in &hits {
                if o.eq_usize(entries[i].ordinal) {
                    return Ok(secs[i].clone());
                }
            }
            if distinct && hits.len() > 1 {
                return Err(OpError::new(format!(
                    "no section \"{}\" with ordinal {}.\n  These {} sections have different paths, so an ordinal does not tell them apart. Use a longer path.\n  Candidates: {}",
                    want_str,
                    o.repr(),
                    hits.len(),
                    paths.iter().map(|p| format!("\"{p}\"")).collect::<Vec<_>>().join("; ")
                )));
            }
            if hits.len() == 1 {
                // The whole recorded population, and the branch below was
                // written for none of it. `bench/ordinal_sizing.py`: 140 of 140
                // ordinal refusals in `bench/results/` come from here, the path
                // matched one section in every one of them, and the message
                // below — which explains how to tell tied sections apart — was
                // answering a caller who had no tie.
                //
                // Worse than useless. Taking its advice, on the 111 that were
                // first calls, gives `correct` 37 times and destroys the
                // document 52 times, all on `rename-closed-atx`, where the
                // model addresses the parent and means a child: dropping the
                // ordinal renames the parent and reports success. That is the
                // destructive retry S11 and S12 traced to `Valid ordinals: 0`,
                // surviving the rewrite that was supposed to answer them, and
                // 5.3's own rule against it — a wrong suggestion is worse than
                // none: it is authoritative and the model will follow it.
                //
                // So say the thing that is true and load-bearing, in the order
                // S11's own reasoning gives. S11 kept this refusal because *the
                // ordinal is the only evidence the path is wrong*; a caller who
                // sends one has asserted there are several of these, and there
                // is one, so the caller's own call is the evidence. "You
                // probably meant this one, drop the ordinal" throws that away,
                // which is why the path reading leads and the sections nested
                // under the match are quoted: that list contains the address
                // the task wanted in 52 of the 52 calls whose old advice
                // destroyed the document. Nothing here scores or ranks the two
                // readings — the resolver cannot tell them apart, and guessing
                // would be the invention 6.4 forbids.
                //
                // Which is why both lines are conditionals and neither is an
                // imperative. `Send ordinal 0, or drop it.` told the caller what
                // to do; these tell it what each reading would mean, and the
                // caller is the only party that knows which it meant. The
                // adversarial number says why that matters: take the first path
                // quoted here without reading it and the sizing run scores 62 of
                // 111 destructive, worse than the old 52, because any wrong
                // address renames the wrong heading. The claim this branch makes
                // is only that the right address is now *in* the sentence — 91
                // of 111, against 37 — not that a model picks it.
                let base = &secs[hits[0]].path;
                let inner: Vec<String> = secs
                    .iter()
                    .filter(|s| s.path.len() > base.len() && s.path[..base.len()] == base[..])
                    .map(|s| s.slug())
                    .collect();
                // `want_label`, not the word "path", and the replay is why. The
                // first draft said "send the longer path", and two of its 27
                // after-trials answered by putting the section address into the
                // tool's `path` argument — the FILE. That is S15's collision
                // measured again, and the schema S15 adopted addresses sections
                // by `section.heading`, so in the shipping scheme "the longer
                // path" names the file argument and nothing else.
                let tail = if inner.is_empty() {
                    format!("  Nothing is nested under it, so a longer address will not help -- check `{want_label}`, or send it again without an ordinal.")
                } else {
                    format!(
                        "  If you meant a section inside it, send one of these as `{}`: {}{}\n  If you did mean this one, send it again without an ordinal.",
                        want_label,
                        inner
                            .iter()
                            .take(8)
                            .map(|p| format!("\"{p}\""))
                            .collect::<Vec<_>>()
                            .join("; "),
                        if inner.len() > 8 { "; ..." } else { "" }
                    )
                };
                return Err(OpError::new(format!(
                    "no section \"{}\" with ordinal {}.\n  Only one section matches `{}`. Sending an ordinal says you expected several, so it may not be the section you meant.\n{}",
                    want_str,
                    o.repr(),
                    want_label,
                    tail
                )));
            }
            let mut valid: Vec<usize> = hits.iter().map(|i| entries[*i].ordinal).collect();
            valid.sort_unstable();
            valid.dedup();
            let valid: Vec<String> = valid.iter().map(|n| n.to_string()).collect();
            return Err(OpError::new(format!(
                "no section \"{}\" with ordinal {}.\n  Ordinals count sections that share a heading path, starting at 0.\n  This one has {}. Send ordinal {}, or drop it.",
                want_str,
                o.repr(),
                if valid.len() == 1 {
                    format!("just ordinal {}", valid[0])
                } else {
                    format!("ordinals {}", valid.join(", "))
                },
                valid.join(" or ")
            )));
        }
        if hits.len() == 1 {
            return Ok(secs[hits[0]].clone());
        }
        if distinct {
            return Err(OpError::new(format!(
                "ambiguous: \"{}\" matches {} sections. Use a longer path.\n  Candidates: {}",
                want_str,
                hits.len(),
                paths
                    .iter()
                    .map(|p| format!("\"{p}\""))
                    .collect::<Vec<_>>()
                    .join("; ")
            )));
        }
        return Err(OpError::new(format!(
            "ambiguous: {} sections share the path \"{}\" and nothing distinguishes them but position. Pass an ordinal.\n  Candidates: {}",
            hits.len(),
            paths[0],
            hits.iter()
                .map(|i| format!(
                    "ordinal {} (line {}, {})",
                    entries[*i].ordinal,
                    secs[*i].start + 1,
                    if secs[*i].has_body() { "body" } else { "no body" }
                ))
                .collect::<Vec<_>>()
                .join("; ")
        )));
    }

    Err(no_section(content, &want_str, &entries))
}

/// The not-found refusal, raised only after checking it is really not there.
///
/// A heading the user can see on their screen being reported as absent is worse
/// than a refusal, so every inert heading is consulted by name first.
fn no_section(content: &str, want: &str, entries: &[SectionEntry]) -> OpError {
    let leaf = py_strip(want.rsplit('>').next().unwrap_or(want)).to_string();
    let leaf_lower = leaf.to_lowercase();
    for h in inert_headings(content) {
        if h.text.to_lowercase() == leaf_lower {
            let whereis = match h.reason {
                "code-fence" => "inside a fenced code block",
                "blockquote" => "inside a blockquote",
                "indented-code" => "in an indented code block",
                _ => "in the frontmatter",
            };
            return OpError::new(format!(
                "\"{}\" is on line {}, but it is {}, so it is not an addressable section.\n  Nothing there can be edited by heading path; edit the enclosing section's body instead.",
                leaf,
                h.line + 1,
                whereis
            ));
        }
    }
    let texts: Vec<String> = entries.iter().map(|e| e.text.clone()).collect();
    let near = get_close_matches(&leaf, &texts, 3, 0.4);
    OpError::new(format!(
        "no section at path \"{}\".\n  Near matches: {}\n  Paths: {}{}",
        want,
        if near.is_empty() {
            "none".to_string()
        } else {
            near.join(", ")
        },
        entries
            .iter()
            .take(10)
            .map(|e| format!("\"{}\"", e.path))
            .collect::<Vec<_>>()
            .join("; "),
        if entries.len() > 10 { "; ..." } else { "" }
    ))
}

// --------------------------------------------------------------------------
// conventions
// --------------------------------------------------------------------------

/// The line ending the section's own lines use, or a refusal if it has two.
fn section_eol(content: &str, sec: &Section) -> Result<&'static str> {
    let lines = split_lines(content);
    let mut cr = false;
    let mut lf = false;
    for ln in &lines[sec.start..=sec.end] {
        if ln.ends_with('\r') {
            cr = true;
        } else {
            lf = true;
        }
    }
    match (cr, lf) {
        (true, false) => Ok("\r"),
        (false, true) => Ok(""),
        _ => Err(OpError::new(
            "this section mixes CRLF and LF line endings, so there is no convention to match.\n  Normalize the section's line endings first, then retry.",
        )),
    }
}

/// A model-supplied markdown block as lines, with `eol` applied.
///
/// Blank lines are dropped from *both* ends rather than preserved. The spacing
/// between a block and what surrounds it is the *document's* convention (§6.3),
/// not the payload's, and a model that wraps its text in newlines is not making
/// a statement about that.
///
/// The leading half of that was added after the section fix arm: four trials in
/// 130 sent `"\nSuperseded."` — correct prose, correct section, with the
/// separator the op already inserts supplied a second time by hand. Keeping the
/// payload's blank line put two where the document uses one, which graded
/// `collateral:formatting`: a document damaged in a way no user asked for,
/// because the executor took a guess about whitespace as an instruction.
fn block(text: Option<&str>, eol: &str, field: &str) -> Result<Vec<String>> {
    let t = match text {
        Some(t) if !t.trim().is_empty() => t,
        _ => {
            return Err(OpError::new(format!(
                "`{field}` is required and must not be empty."
            )))
        }
    };
    let normalized = t.replace("\r\n", "\n");
    let mut body: Vec<&str> = normalized
        .split('\n')
        .map(|ln| ln.trim_end_matches('\r'))
        .collect();
    while body.last().is_some_and(|ln| ln.trim().is_empty()) {
        body.pop();
    }
    while body.first().is_some_and(|ln| ln.trim().is_empty()) {
        body.remove(0);
    }
    Ok(body.into_iter().map(|ln| format!("{ln}{eol}")).collect())
}

/// `ATX_RE.match(s)` and `m.group(4)`: the text of a heading line the model
/// quoted instead of naming.
///
/// Tolerance, not normalization — the level is not the caller's to set here, and
/// `section-set-level` is the op that does. A bare `###` with no whitespace
/// after it is left alone, because `group(4)` is `None` there rather than empty,
/// and it is the caller's own emptiness check that refuses it.
fn strip_atx_marker(s: &str) -> String {
    let spaces = s.chars().take_while(|c| *c == ' ').count();
    if spaces > 3 {
        return s.to_string();
    }
    let rest = &s[spaces..];
    let hashes = rest.chars().take_while(|c| *c == '#').count();
    if hashes == 0 || hashes > 6 {
        return s.to_string();
    }
    let after = &rest[hashes..];
    if after.is_empty() {
        return s.to_string(); // the optional group did not participate
    }
    let ws = after
        .chars()
        .take_while(|c| *c == ' ' || *c == '\t')
        .count();
    if ws == 0 {
        return s.to_string();
    }
    let text = &after[ws..];
    // `.` does not match a newline and the pattern is anchored at both ends, so
    // a multi-line payload is not a heading line at all.
    if text.contains('\n') {
        return s.to_string();
    }
    py_strip(py_strip(text).trim_end_matches('#')).to_string()
}

/// The new heading text a rename or an insert should write, or a refusal.
fn heading_text(heading: Option<&str>, missing: &str) -> Result<String> {
    let h = match heading {
        Some(h) if !h.trim().is_empty() => h,
        _ => return Err(OpError::new(missing.to_string())),
    };
    let new = strip_atx_marker(h.trim());
    if new.is_empty() {
        return Err(OpError::new("`heading` cannot be only a heading marker."));
    }
    Ok(new)
}

/// Refuse a `heading` argument on an op that has no heading to give it to.
///
/// With one exception, and the exception is the whole reason this is shared
/// rather than two inline checks. Re-grading the section arm under the first
/// version of these guards turned six previously-correct trials into `op_error`,
/// all of the same shape: the model echoed the section it was already addressing
/// back into the heading field. That asks for nothing — rename X to X — and the
/// old executor, which ignored the argument entirely, produced exactly the right
/// document. Refusing it is a guard that costs correct calls to catch nothing,
/// so an echo of the addressed section's own name (leaf or full path) passes
/// through.
///
/// Anything else is a real second intent riding on an op that cannot serve it,
/// and that is what S2 and S3 were made of.
fn reject_heading(sec: &Section, heading: Option<&str>, what: &str, remedy: &str) -> Result<()> {
    let h = match heading {
        Some(h) => h,
        None => return Ok(()),
    };
    let asked = h.trim();
    if asked.is_empty() || asked == sec.text || asked == sec.slug() {
        return Ok(());
    }
    Err(OpError::new(format!(
        "{what}, and you passed a heading ({}).\n{remedy}",
        json::py_repr_str(asked)
    )))
}

fn has_own_body(content: &str, sec: &Section) -> bool {
    let lines = split_lines(content);
    lines[sec.heading_end + 1..=sec.own_end]
        .iter()
        .any(|ln| !ln.trim().is_empty())
}

// --------------------------------------------------------------------------
// the ops
// --------------------------------------------------------------------------

/// Append a block to the end of a section's OWN body.
///
/// "Own" is the whole decision. `## [1.4.2]` in `changelog.md` has no prose of
/// its own and two subsections; appending to it means putting a paragraph
/// between the heading and `### Fixed`, not after `### Changed`. That is what
/// the address names, and `own_end` is the field that says where it stops.
///
/// The outline reports `has_body` and a subsection count for exactly this
/// reason: a model that meant `### Fixed` can see that it should have said so.
pub fn section_append(
    content: &str,
    address: &SectionAddress,
    text: Option<&str>,
    heading: Option<&str>,
) -> Result<String> {
    let sec = resolve_section(content, address)?;
    reject_heading(
        &sec,
        heading,
        "`append` cannot create a section",
        "  To add a subsection use action=insert with position=last-child (or first-child) and the parent as `section`.\n  To add prose to this section, drop the heading and pass `text`.",
    )?;
    let eol = section_eol(content, &sec)?;
    let lines = split_lines(content);
    let blk = block(text, eol, "text")?;
    let at = sec.own_end + 1;
    // One blank line separates block-level constructs. This is markdown's rule,
    // not a document convention, so unlike the gap between sections it is not
    // read off the file.
    let mut out: Vec<String> = lines[..at].iter().map(|s| s.to_string()).collect();
    out.push(eol.to_string());
    out.extend(blk);
    out.extend(lines[at..].iter().map(|s| s.to_string()));
    Ok(out.join("\n"))
}

/// Replace a section's own body, leaving its heading and subsections alone.
///
/// Refuses to discard a non-empty body unless `overwrite` says so. This is the
/// one op in the family that destroys content as its normal function, and
/// FINDINGS S2 measured what that costs: asked to *add* a line to a section, the
/// model called `replace-body` in five trials of ten and deleted the line that
/// was already there. Addressing was correct in every one — right file, right
/// section, right ordinal — so nothing about *where* was in doubt. The model was
/// wrong about the verb, and the executor cannot tell a deliberate overwrite
/// from a mistaken one by looking at the arguments.
///
/// So it asks. A section whose body is empty is not protected, because there is
/// nothing to lose.
pub fn section_replace_body(
    content: &str,
    address: &SectionAddress,
    text: Option<&str>,
    overwrite: bool,
    heading: Option<&str>,
) -> Result<String> {
    let sec = resolve_section(content, address)?;
    reject_heading(
        &sec,
        heading,
        "`replace-body` cannot create or rename a section",
        "  Use action=rename to change a heading, or action=insert to add a section.",
    )?;
    if !overwrite && has_own_body(content, &sec) {
        return Err(OpError::new(format!(
            "\"{}\" already has a body, and `replace-body` discards it.\n  If you meant to add to it, use action=append.\n  If you really meant to replace it, pass overwrite=true.",
            sec.slug()
        )));
    }
    let eol = section_eol(content, &sec)?;
    let lines = split_lines(content);
    let blk = block(text, eol, "text")?;
    let mut out: Vec<String> = lines[..sec.heading_end + 1]
        .iter()
        .map(|s| s.to_string())
        .collect();
    out.push(eol.to_string());
    out.extend(blk);
    out.extend(lines[sec.own_end + 1..].iter().map(|s| s.to_string()));
    Ok(out.join("\n"))
}

/// Delete a section and its entire subtree.
///
/// Deleting `## Install` from `deep-nesting.md` removes 32 lines and six
/// subsections. That is correct and it is also the most destructive op in the
/// vocabulary, so the outline's subsection count is the model's warning and this
/// docstring is the reader's: `end`, not `own_end`.
pub fn section_delete(content: &str, address: &SectionAddress) -> Result<String> {
    let sec = resolve_section(content, address)?;
    let lines = split_lines(content);
    // Take the trailing gap with it, so the document's section spacing is
    // unchanged rather than doubled where the section used to be.
    let stop = sec.end + 1 + sec.gap_after;
    if stop >= lines.len() {
        // Last section in the file: there is no following gap to absorb, so take
        // the *leading* blank lines instead. Otherwise the document keeps the
        // separator for a section that no longer exists.
        let mut start = sec.start;
        while start > 0 && lines[start - 1].trim().is_empty() {
            start -= 1;
        }
        let mut out: Vec<&str> = lines[..start].to_vec();
        out.extend_from_slice(&lines[sec.end + 1..]);
        return Ok(out.join("\n"));
    }
    let mut out: Vec<&str> = lines[..sec.start].to_vec();
    out.extend_from_slice(&lines[stop..]);
    Ok(out.join("\n"))
}

/// Delete a section through the agent-facing safety boundary.
///
/// A leaf needs no extra acknowledgement. A section with descendants requires
/// `subtree=true`, after a refusal that names the exact descendant paths at
/// risk. This keeps the underlying splice reusable for trusted round-trip
/// invariants while making the dispatched operation fail closed.
pub fn section_delete_confirmed(
    content: &str,
    address: &SectionAddress,
    confirm_subtree: bool,
) -> Result<String> {
    let target = resolve_section(content, address)?;
    let descendants: Vec<String> = find_sections(content)
        .into_iter()
        .filter(|section| section.start > target.start && section.start <= target.end)
        .map(|section| format!("\"{}\"", section.slug()))
        .collect();
    if !descendants.is_empty() && !confirm_subtree {
        let mut repair = Repair::new(
            "subtree_confirmation_required",
            "Repeat the call with subtree=true only if deleting every named descendant is intended.",
        );
        repair.argument = Some("subtree".to_string());
        repair.received = Some("false".to_string());
        repair.candidates = descendants
            .iter()
            .map(|path| path.trim_matches('"').to_string())
            .collect();
        return Err(OpError::with_repair(format!(
            "deleting \"{}\" would also delete {} descendant section{}: {}.\n  If you intend to delete the whole subtree, pass subtree=true.",
            target.slug(),
            descendants.len(),
            if descendants.len() == 1 { "" } else { "s" },
            descendants.join("; ")
        ), repair));
    }
    section_delete(content, address)
}

/// Change a heading's text, preserving the syntax it was written in.
///
/// Setext stays setext, a closed ATX heading keeps its trailing hashes, an
/// unusual run of spaces after the marker survives, and a CRLF file stays CRLF.
/// [`Section::rebuild`] owns all four; see its docstring for why the last one is
/// not hypothetical.
pub fn section_rename(
    content: &str,
    address: &SectionAddress,
    heading: Option<&str>,
) -> Result<String> {
    let sec = resolve_section(content, address)?;
    // A model handed "## Fixed" for a rename is quoting the line, not naming the
    // text. Stripping the marker is tolerance, not normalization.
    let new = heading_text(
        heading,
        "`heading` is required: the new text for the heading.",
    )?;
    let lines = split_lines(content);
    let mut out: Vec<String> = lines[..sec.start].iter().map(|s| s.to_string()).collect();
    out.extend(sec.rebuild(Some(&new)));
    out.extend(lines[sec.heading_end + 1..].iter().map(|s| s.to_string()));
    Ok(out.join("\n"))
}

pub const POSITIONS: &[&str] = &["before", "after", "first-child", "last-child"];

/// Refuse a `body` payload that contains a heading.
///
/// S6: `insert`'s preamble promises the model never has to count levels, and for
/// `heading` that is true and measured (18-20/20 on rename and set-level).
/// `body` takes markdown *source*, so the promise stops at its boundary in the
/// one place the model most needs it: a new changelog release needs an `Added`
/// subsection, and the only way to say so in one call was to write `### Added`
/// by hand and get the 3 right. Across 30 `insert-release-at-top` trials the
/// model wrote that heading at level 1, 2 and 4 — never at 3.
///
/// Refusing converts the class from `wrong` to `op_error`: the difference
/// between a changelog with a malformed release and a calling agent that knows
/// it needs a second call. The level is never named in the message, for the same
/// reason it is never named in the schema.
///
/// Parsed, not pattern-matched on the first line: `find_sections` is the same
/// parser the document itself goes through, so a `# comment` inside a fenced
/// bash block is not a heading here either — and a heading that arrives on the
/// *third* line, after a stray table row, is. One trial sent exactly that; a
/// first-line check would have written it.
fn reject_heading_in_body(body: Option<&str>, field: &str) -> Result<()> {
    let b = match body {
        Some(b) if !b.trim().is_empty() => b,
        _ => return Ok(()),
    };
    let text = b.replace("\r\n", "\n");
    let found = find_sections(&text);
    let first = match found.first() {
        Some(f) => f,
        None => return Ok(()),
    };
    let name = json::py_repr_str(&first.text);
    Err(OpError::new(format!(
        "`{field}` contains a heading ({name}), and it is inserted as literal text -- the level would not be worked out for you.\n  Make the section first, then add the subsection with a second call: action=insert, position=last-child, `section` = the section you just created.\n  If {name} is meant to be prose, drop the `#` marks."
    )))
}

/// Render `[{heading, body, children?}]` as lines at `level`, recursively.
///
/// The structured alternative to S6's raw-markdown `body`: the caller names the
/// shape, the executor names the levels. `level` is the child's own level,
/// already derived from the parent, so nothing here can produce a heading the
/// document could not contain.
fn child_blocks(children: &Value, level: usize, eol: &str, field: &str) -> Result<Vec<String>> {
    let items: Vec<Value> = match children {
        Value::Null => return Ok(Vec::new()),
        Value::Object(_) => vec![children.clone()],
        Value::Array(xs) => xs.clone(),
        other => {
            return Err(OpError::new(format!(
                "`{field}` must be a list of subsections, each with a `heading` and an optional `body`. Got {}.",
                py_type_name(other)
            )))
        }
    };
    if level > 6 {
        return Err(OpError::new(format!(
            "a subsection here would be level 7 and markdown stops at 6.\n  Drop `{field}` and insert those sections as siblings instead."
        )));
    }
    let mut out: Vec<String> = Vec::new();
    for (i, raw) in items.iter().enumerate() {
        let ch = match raw {
            Value::Str(s) => Value::Object(vec![("heading".to_string(), Value::Str(s.clone()))]),
            Value::Object(_) => raw.clone(),
            other => {
                return Err(OpError::new(format!(
                    "`{field}`[{i}] must be an object with a `heading`. Got {}.",
                    py_type_name(other)
                )))
            }
        };
        let head_raw = item(&ch, &["heading", "title", "new_heading"]);
        let head = match &head_raw {
            Some(h) if !h.trim().is_empty() => strip_atx_marker(h.trim()),
            _ => {
                return Err(OpError::new(format!(
                    "`{field}`[{i}] is missing `heading`."
                )))
            }
        };
        if head.is_empty() {
            return Err(OpError::new(format!(
                "`{field}`[{i}] `heading` cannot be only `#` marks."
            )));
        }
        if !out.is_empty() {
            out.push(eol.to_string());
        }
        out.push(format!("{} {}{}", "#".repeat(level), head, eol));
        let body = item(&ch, &["body", "text"]);
        if body.as_deref().is_some_and(|b| !b.trim().is_empty()) {
            let f = format!("{field}[{i}].body");
            reject_heading_in_body(body.as_deref(), &f)?;
            out.push(eol.to_string());
            out.extend(block(body.as_deref(), eol, &f)?);
        }
        if let Some(kids) = truthy_of(&ch, &["children", "sections"]) {
            out.push(eol.to_string());
            out.extend(child_blocks(
                &kids,
                level + 1,
                eol,
                &format!("{field}[{i}].children"),
            )?);
        }
    }
    Ok(out)
}

/// `type(v).__name__`, which is what these two messages use — Python's own type
/// names, not the JSON ones `_type_name` produces elsewhere in the oracle. The
/// two are different sentences and the difference is observable.
fn py_type_name(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Int(_) | Value::BigInt(_) => "int",
        Value::Float(_) => "float",
        Value::Str(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

/// `_item(obj, *fields)` over a nested object: the first field supplied, as a
/// string.
fn item(obj: &Value, fields: &[&str]) -> Option<String> {
    fields
        .iter()
        .find_map(|f| obj.get(f).filter(|v| !matches!(v, Value::Null)))
        .map(json::py_str)
}

/// `obj.get(x) or obj.get(y)`: the first *truthy* value, or nothing.
fn truthy_of(obj: &Value, fields: &[&str]) -> Option<Value> {
    fields
        .iter()
        .find_map(|f| obj.get(f).filter(|v| json::py_truthy(v)))
        .cloned()
}

/// Insert a new section relative to an existing one.
///
/// The level is DERIVED, never passed. `before`/`after` make a sibling of the
/// anchor; `first-child`/`last-child` make a child one level deeper. This is the
/// list family's L4 result carried across: the model cannot see the document, so
/// a level argument is a number it would have to invent, and deriving it makes
/// an impossible level unexpressible rather than merely invalid.
///
/// `after` means after the anchor's whole subtree. Inserting `## [1.5.0]` after
/// `## [1.4.2]` must land past that release's `### Fixed` and `### Changed`, not
/// between the heading and its first subsection — which is the single most
/// common changelog edit there is.
pub fn section_insert(
    content: &str,
    anchor: &SectionAddress,
    position: Option<&Value>,
    heading: Option<&str>,
    body: Option<&str>,
    children: Option<&Value>,
) -> Result<String> {
    let sec = resolve_section(content, anchor)?;
    // `a.get("position", "after")`: absent is "after", but an explicit `null` is
    // `None`, and `None not in POSITIONS` is the refusal below.
    let pos_str = position.map_or_else(|| "after".to_string(), json::py_str);
    let known = match position {
        None => true,
        Some(Value::Str(s)) => POSITIONS.contains(&s.as_str()),
        // Only a string can be `in` a tuple of strings; `1` and `True` are not
        // `"before"` however they print.
        Some(_) => false,
    };
    if !known {
        return Err(OpError::new(format!(
            "unknown position \"{}\". Valid: {}.\n  before/after make a sibling of the anchor; first-child and last-child make a subsection of it.",
            pos_str,
            POSITIONS.join(", ")
        )));
    }
    let new_text = heading_text(
        heading,
        "`heading` is required: the new section's heading text.",
    )?;

    let eol = section_eol(content, &sec)?;
    let lines = split_lines(content);
    let secs = find_sections(content);
    let level = if pos_str == "before" || pos_str == "after" {
        sec.level
    } else {
        sec.level + 1
    };
    if level > 6 {
        return Err(OpError::new(format!(
            "\"{}\" is already at level {}; a subsection of it would be level 7 and markdown stops at 6.\n  Insert it as a sibling with position=after instead.",
            sec.slug(),
            sec.level
        )));
    }

    let at = match pos_str.as_str() {
        "before" => sec.start,
        "first-child" => sec.own_end + 1,
        // `after` and `last-child` are the same point and a different level.
        _ => sec.end + 1,
    };

    let gap: Vec<String> = vec![eol.to_string(); heading_gap(&secs).max(1)];
    let mut blk: Vec<String> = vec![format!("{} {}{}", "#".repeat(level), new_text, eol)];
    if body.is_some_and(|b| !b.trim().is_empty()) {
        reject_heading_in_body(body, "body")?;
        blk.push(eol.to_string());
        blk.extend(block(body, eol, "body")?);
    }
    // `if children:` — a falsy value is no children at all, not an empty list
    // to render. The dispatch's `or` chain can hand one through: `{"sections":
    // []}` reaches here as `[]`, because Python's `or` returns its last operand
    // when every one of them is falsy.
    if let Some(c) = children.filter(|c| json::py_truthy(c)) {
        blk.push(eol.to_string());
        blk.extend(child_blocks(c, level + 1, eol, "children")?);
    }

    let mut out: Vec<String> = Vec::with_capacity(lines.len() + blk.len() + gap.len());
    let head_at;
    if pos_str == "before" {
        out.extend(lines[..at].iter().map(|s| s.to_string()));
        out.extend(blk);
        out.extend(gap);
        out.extend(lines[at..].iter().map(|s| s.to_string()));
        head_at = at;
    } else {
        // `at` is one past the anchor's last non-blank line, so whatever blank
        // lines already separated it from the next section are still ahead of
        // it.
        let mut tail = at;
        while tail < lines.len() && lines[tail].trim().is_empty() {
            tail += 1;
        }
        if tail < lines.len() {
            // Step over that existing separator instead of replacing it, and put
            // the new gap on the far side of the block. Two reasons, and they
            // agree. Those blank lines are the document's own bytes —
            // `whitespace.md` separates two of its sections with two of them,
            // `mixed-endings.md` with a CRLF one — and §5.2 says match what was
            // found. And `section-delete` takes a section's *trailing* gap, so a
            // leading gap here would not compose: insert-then-delete would leave
            // a blank line behind and slowly loosen the document.
            out.extend(lines[..tail].iter().map(|s| s.to_string()));
            out.extend(blk);
            out.extend(gap);
            out.extend(lines[tail..].iter().map(|s| s.to_string()));
            head_at = tail;
        } else {
            // End of document: nothing follows to separate from, so the gap goes
            // before the block, and the blank lines `tail` just skipped stay
            // exactly as they were. Splitting on "\n" represents a file's final
            // newline as a last empty element; dropping it deletes a byte that is
            // invisible in a terminal and `collateral:formatting` by §5.1.
            // `whitespace.md` ends without one and has to keep not having one.
            let n = gap.len();
            out.extend(lines[..at].iter().map(|s| s.to_string()));
            out.extend(gap);
            out.extend(blk);
            out.extend(lines[at..].iter().map(|s| s.to_string()));
            head_at = at + n;
        }
    }

    let result = out.join("\n");
    verify_heading(&result, head_at, &new_text, &sec)?;
    Ok(result)
}

/// Refuse if the heading just written is not a heading in the output.
///
/// The only place in this family where an op can succeed and still be wrong in a
/// way the model cannot see. `corpus/hazards/code-fences.md` ends inside an
/// unclosed fence, so by CommonMark everything after it — including the anchor's
/// own last line, and therefore the insertion point — is code. Writing `## Foo`
/// there changes the file, reports success, and creates no section. That is the
/// difference §12 draws between `wrong` and `op_error`, and `op_error` is the
/// loud one: better to refuse than to be believed.
///
/// Checked by re-parsing rather than by testing the insertion point against
/// `fence_mask`, because the property that matters is the one the next op will
/// see, and only a parse establishes it.
fn verify_heading(result: &str, line: usize, text: &str, anchor: &Section) -> Result<()> {
    if find_sections(result).iter().any(|s| s.start == line) {
        return Ok(());
    }
    let mut whereis = "is not parsed as a heading there";
    for h in inert_headings(result) {
        if h.line == line {
            whereis = match h.reason {
                "code-fence" => "would land inside a fenced code block that is never closed, so it would be code, not a heading",
                "blockquote" => "would land inside a blockquote",
                "indented-code" => "would land inside an indented code block",
                _ => "would land inside the frontmatter",
            };
            break;
        }
    }
    Err(OpError::new(format!(
        "refusing to insert \"{}\": at line {} it {}.\n  \"{}\" runs to the end of an unterminated block, so there is no point after it where a new section would be addressable.\n  Close the block first, or edit the section's body instead.",
        text,
        line + 1,
        whereis,
        anchor.slug()
    )))
}

/// Promote or demote a heading, optionally carrying its subsections.
///
/// Two refusals with no analogue in the earlier families:
///
/// * A setext heading can only express levels 1 and 2. Demoting one to level 3
///   means rewriting it as ATX, which is a syntax change nobody asked for, so it
///   refuses and says so.
/// * `subtree=false` reparents children rather than moving them. That is a
///   legitimate thing to want and a terrible thing to do by accident, so it is
///   not the default.
pub fn section_set_level(
    content: &str,
    address: &SectionAddress,
    level: Option<&Value>,
    subtree: bool,
) -> Result<String> {
    let sec = resolve_section(content, address)?;
    let cast = level.and_then(py_int_cast);
    let want = match &cast {
        Some(n) => n,
        None => {
            return Err(OpError::new(format!(
                "`level` must be a number from 1 to 6, not {}.",
                level.map_or_else(|| "None".to_string(), json::py_repr)
            )))
        }
    };
    let want = match want.small() {
        Some(n) if (1..=6).contains(&n) => n,
        _ => {
            return Err(OpError::new(format!(
                "`level` must be between 1 and 6; got {}.",
                cast.as_ref().unwrap().repr()
            )))
        }
    };
    if want as usize == sec.level {
        return Err(OpError::new(format!(
            "\"{}\" is already at level {}; nothing to do.",
            sec.slug(),
            sec.level
        )));
    }

    let secs = find_sections(content);
    let idx = secs
        .iter()
        .position(|s| s.start == sec.start)
        .expect("resolved from this parse");
    let delta = want - sec.level as i64;
    let mut moving = vec![idx];
    if subtree {
        for (k, following) in secs.iter().enumerate().skip(idx + 1) {
            if following.level <= sec.level {
                break;
            }
            moving.push(k);
        }
    }

    for &k in &moving {
        let new_level = secs[k].level as i64 + delta;
        if !(1..=6).contains(&new_level) {
            return Err(OpError::new(format!(
                "moving \"{}\" to level {} would put its subsection \"{}\" at level {}, which markdown cannot express.\n  Choose a level that keeps the whole subtree within 1-6, or pass subtree=false to move only the heading.",
                sec.slug(),
                want,
                secs[k].slug(),
                new_level
            )));
        }
        if secs[k].style == HeadingStyle::Setext && new_level > 2 {
            return Err(OpError::new(format!(
                "\"{}\" is written in setext form (underlined), which can only express levels 1 and 2. Moving it to level {} would require rewriting it as `{}`, a change to the document's style that was not asked for.\n  Convert that heading to ATX first if that is what you want.",
                secs[k].slug(),
                new_level,
                "#".repeat(new_level as usize)
            )));
        }
    }

    let mut lines: Vec<String> = split_lines(content).iter().map(|s| s.to_string()).collect();
    for &k in &moving {
        let s = &secs[k];
        let new_level = (s.level as i64 + delta) as usize;
        if s.style == HeadingStyle::Setext {
            // Still setext: only the underline character changes.
            let ch = if new_level == 1 { '=' } else { '-' };
            lines[s.heading_end] = format!(
                "{}{}{}",
                s.indent,
                ch.to_string().repeat(s.marker.len()),
                s.eol
            );
        } else {
            let space = if s.space.is_empty() {
                " "
            } else {
                s.space.as_str()
            };
            let mut line = format!(
                "{}{}{}{}",
                s.indent,
                "#".repeat(new_level),
                space,
                s.raw_text
            );
            if s.style == HeadingStyle::AtxClosed {
                line.push(' ');
                line.push_str(&s.closing);
            }
            line.push_str(&s.eol);
            lines[s.start] = line;
        }
    }
    Ok(lines.join("\n"))
}

/// `int(v)` for the values a JSON argument can hold.
///
/// Wider than [`args::check_ordinal`] on purpose, because `int()` is: a boolean
/// is an integer in Python (`int(True) == 1`), and a float truncates toward zero
/// rather than being refused. `None`, a list and an object raise `TypeError`,
/// which the oracle catches and turns into the "must be a number from 1 to 6"
/// refusal.
fn py_int_cast(v: &Value) -> Option<PyInt> {
    match v {
        Value::Int(n) => Some(PyInt::Small(*n)),
        Value::BigInt(s) => Some(PyInt::Big(s.clone())),
        Value::Bool(b) => Some(PyInt::Small(i64::from(*b))),
        Value::Float(f) => {
            // JSON cannot carry an infinity, which is the one float `int()`
            // raises on rather than truncating.
            f.is_finite().then(|| PyInt::Small(f.trunc() as i64))
        }
        Value::Str(s) => args::py_int_from_str(s),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DOC: &str =
        "# Guide\n\n## Install\n\nRun it.\n\n### macOS\n\nBrew.\n\n## Usage\n\nType it.\n";

    #[test]
    fn append_lands_in_the_sections_own_body_not_after_its_subtree() {
        let out = section_append(DOC, &"Install".into(), Some("Then restart."), None).unwrap();
        // Before `### macOS`, not after `Brew.`
        assert!(
            out.contains("Run it.\n\nThen restart.\n\n### macOS"),
            "{out}"
        );
    }

    #[test]
    fn delete_takes_the_subtree_and_the_trailing_gap() {
        let out = section_delete(DOC, &"Install".into()).unwrap();
        assert_eq!(out, "# Guide\n\n## Usage\n\nType it.\n");
    }

    #[test]
    fn replace_body_refuses_a_non_empty_body_without_overwrite() {
        let e = section_replace_body(DOC, &"Usage".into(), Some("New."), false, None).unwrap_err();
        assert!(
            e.message()
                .starts_with("\"Guide > Usage\" already has a body"),
            "{}",
            e.message()
        );
        let out = section_replace_body(DOC, &"Usage".into(), Some("New."), true, None).unwrap();
        assert!(out.ends_with("## Usage\n\nNew.\n"), "{out}");
    }

    /// The suffix pass, and the refusal when it is not unique.
    #[test]
    fn a_leaf_addresses_when_it_is_the_only_one() {
        assert_eq!(resolve_section(DOC, &"macOS".into()).unwrap().level, 3);
        let two = "# A\n\n## Notes\n\nx\n\n# B\n\n## Notes\n\ny\n";
        let e = resolve_section(two, &"Notes".into()).unwrap_err();
        assert!(
            e.message()
                .starts_with("ambiguous: \"Notes\" matches 2 sections. Use a longer path."),
            "{}",
            e.message()
        );
        assert_eq!(resolve_section(two, &"B > Notes".into()).unwrap().start, 8);
    }

    #[test]
    fn insert_derives_the_level_from_the_position() {
        let last = Value::Str("last-child".into());
        let out = section_insert(
            DOC,
            &"Install".into(),
            Some(&last),
            Some("Linux"),
            None,
            None,
        )
        .unwrap();
        assert!(out.contains("### macOS\n\nBrew.\n\n### Linux\n"), "{out}");
        let after = Value::Str("after".into());
        let out = section_insert(
            DOC,
            &"Install".into(),
            Some(&after),
            Some("Config"),
            None,
            None,
        )
        .unwrap();
        assert!(out.contains("Brew.\n\n## Config\n\n## Usage"), "{out}");
    }

    #[test]
    fn a_body_containing_a_heading_is_refused_rather_than_written() {
        let after = Value::Str("after".into());
        let e = section_insert(
            DOC,
            &"Usage".into(),
            Some(&after),
            Some("Next"),
            Some("### Added\n\n- a"),
            None,
        )
        .unwrap_err();
        assert!(
            e.message()
                .starts_with("`body` contains a heading ('Added')"),
            "{}",
            e.message()
        );
    }

    #[test]
    fn set_level_carries_the_subtree_and_refuses_an_impossible_one() {
        let out = section_set_level(DOC, &"Install".into(), Some(&Value::Int(3)), true).unwrap();
        assert!(
            out.contains("### Install") && out.contains("#### macOS"),
            "{out}"
        );
        let e = section_set_level(DOC, &"Install".into(), Some(&Value::Int(6)), true).unwrap_err();
        assert!(
            e.message()
                .contains("at level 7, which markdown cannot express"),
            "{}",
            e.message()
        );
        // `int(True) == 1`, which is Python and therefore the contract.
        let out =
            section_set_level(DOC, &"Install".into(), Some(&Value::Bool(true)), true).unwrap();
        assert!(out.starts_with("# Guide\n\n# Install"), "{out}");
    }

    #[test]
    fn rename_keeps_the_syntax_it_found() {
        let setext = "Title\n=====\n\nx\n";
        let out = section_rename(setext, &"Title".into(), Some("## Renamed")).unwrap();
        assert_eq!(out, "Renamed\n=======\n\nx\n");
    }

    /// S3's guard, and the echo that must survive it.
    #[test]
    fn append_refuses_a_heading_but_not_an_echo_of_its_own() {
        let e = section_append(DOC, &"Usage".into(), Some("x"), Some("Examples")).unwrap_err();
        assert!(
            e.message().starts_with(
                "`append` cannot create a section, and you passed a heading ('Examples')."
            ),
            "{}",
            e.message()
        );
        assert!(section_append(DOC, &"Usage".into(), Some("x"), Some("Usage")).is_ok());
        assert!(section_append(DOC, &"Usage".into(), Some("x"), Some("Guide > Usage")).is_ok());
    }
}
