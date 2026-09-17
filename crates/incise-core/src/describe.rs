//! What an op did to a document, derived from the document.
//!
//! This is the shape of a *success* (§5.4, §6.3.2, §9 criterion 11), and it is
//! the only part of the response contract that measurement forced rather than
//! taste. The harness originally returned the heading outline on every
//! successful section call — helpful-looking, 702 characters. Replacing it with
//! this one line took redundant continuation from 8/300 to 0/300 (McNemar
//! p = 0.0078) and destructive outcomes from 3 to 0; returning *both* was
//! statistically identical to returning the outline alone (6/300, p = 0.73,
//! S14). So the requirement is not "say what changed" but **"say what changed,
//! and stop showing the document"**, and the omission is the deliverable as
//! much as the sentence is.
//!
//! Everything here is a difference between the before and after *bytes*. That
//! is deliberate and it is the whole point: a description derived from the
//! call's arguments would be worthless for exactly the case that matters — a
//! model second-guessing whether its call landed learns nothing from being told
//! what it asked for, and an argument echo can report a change that did not
//! happen. Being derived from the documents also means it is correct for an op
//! this module has never heard of.
//!
//! Ported from `bench/incise_ops.py`, which is the oracle. Two notes on the
//! port:
//!
//! * **It is not an op.** Nothing in [`crate::ops::dispatch::OPS`] reaches it;
//!   it is what a front end wraps a successful op with. It lives in the core
//!   anyway because the core is where `bench/difftest.py`, `bench/mutate.py`
//!   and the invariant suite can hold it to the oracle.
//! * **The oracle's third parameter is dead.** `describe_change(before, after,
//!   path="")` never reads `path` in its body. It is not ported, rather than
//!   carried across as an argument no code reads.

use crate::heading::{find_sections, Section};
use crate::scan::{py_strip, split_lines};
use crate::similar::{Matcher, Tag};

/// `(text, level, own-body)` per heading, in document order.
///
/// The body is the section's *own* prose — `own_end`, not `end`. A section's
/// subtree belongs to its children, and folding it in here would report every
/// ancestor as changed whenever a leaf was touched.
fn describe_entries(content: &str) -> Vec<(String, usize, String)> {
    let lines = split_lines(content);
    find_sections(content)
        .iter()
        .map(|s| {
            (
                s.text.clone(),
                s.level,
                py_strip(&own_body(&lines, s)).to_string(),
            )
        })
        .collect()
}

fn own_body(lines: &[&str], sec: &Section) -> String {
    let (lo, hi) = (sec.heading_end + 1, sec.own_end + 1);
    // Python's slice yields `[]` when the start runs past the stop, which is
    // the empty-body case: `own_end == heading_end` on a section with no prose.
    if lo >= hi || lo >= lines.len() {
        return String::new();
    }
    lines[lo..hi.min(lines.len())].join("\n")
}

pub(crate) fn plural(n: usize, noun: &str) -> String {
    format!("{n} {noun}{}", if n == 1 { "" } else { "s" })
}

/// Describe a block of added or removed headings.
///
/// A subtree collapses. `delete` on a section with three subsections removes
/// four headings, and four sentences about it buries the one fact worth
/// reading — that three sections went with the one that was named. The
/// collapsed form states the count instead, which is the same information in
/// the shape a model can act on. Two headings stay itemized: that is the
/// `children` payload landing, and there the model wants to see both.
fn run_notes(verb: &str, run: &[(String, usize, String)]) -> Vec<String> {
    if run.len() > 2 && run[1..].iter().all(|e| e.1 > run[0].1) {
        return vec![format!(
            "{verb} the section \"{}\" (level {}) and {} nested under it",
            run[0].0,
            run[0].1,
            plural(run.len() - 1, "section")
        )];
    }
    run.iter()
        .map(|e| format!("{verb} the section \"{}\" (level {})", e.0, e.1))
        .collect()
}

/// A one-paragraph account of what an op did to a document.
pub fn describe_change(before: &str, after: &str) -> String {
    if before == after {
        return "Applied, but the document is unchanged.".to_string();
    }

    let (b, a) = (describe_entries(before), describe_entries(after));
    let b_texts: Vec<String> = b.iter().map(|e| e.0.clone()).collect();
    let a_texts: Vec<String> = a.iter().map(|e| e.0.clone()).collect();
    let matcher = Matcher::new(&a_texts);

    let mut notes: Vec<String> = Vec::new();
    let mut levels: Vec<(String, usize, usize)> = Vec::new(); // a run of level shifts
    let mut tally_wanted = false; // do the notes account for the byte change?

    // `set-level` with `subtree` moves a heading and every descendant, and
    // naming all six of them is a wall of text that buries the one the model
    // asked about. The first is the one it named.
    fn flush_levels(levels: &mut Vec<(String, usize, usize)>, notes: &mut Vec<String>) {
        if levels.is_empty() {
            return;
        }
        let (text, old, new) = levels[0].clone();
        let verb = if new < old { "promoted" } else { "demoted" };
        let mut who = format!("\"{text}\"");
        if levels.len() > 1 {
            who.push_str(&format!(" and {}", plural(levels.len() - 1, "descendant")));
        }
        notes.push(format!("{verb} {who} from level {old} to level {new}"));
        levels.clear();
    }

    for (tag, i1, i2, j1, j2) in matcher.opcodes(&b_texts) {
        match tag {
            Tag::Equal => {
                for (i, j) in (i1..i2).zip(j1..j2) {
                    if b[i].1 != a[j].1 {
                        levels.push((a[j].0.clone(), b[i].1, a[j].1));
                        continue;
                    }
                    flush_levels(&mut levels, &mut notes);
                    if b[i].2 != a[j].2 {
                        notes.push(format!(
                            "changed the body of \"{}\" ({})",
                            a[j].0,
                            lines_delta(&b[i].2, &a[j].2)
                        ));
                    }
                }
            }
            // One heading swapped for one heading in the same place: a rename.
            // Saying "removed X, added Y" here would be true and would read as
            // data loss, which is the opposite of what happened.
            Tag::Replace if i2 - i1 == 1 && j2 - j1 == 1 => {
                flush_levels(&mut levels, &mut notes);
                notes.push(format!("renamed \"{}\" to \"{}\"", b[i1].0, a[j1].0));
            }
            _ => {
                flush_levels(&mut levels, &mut notes);
                tally_wanted = true;
                notes.extend(run_notes("removed", &b[i1..i2]));
                notes.extend(run_notes("added", &a[j1..j2]));
            }
        }
    }
    flush_levels(&mut levels, &mut notes);

    // Nothing above catches an edit to the text before the first heading, and a
    // response that goes quiet on a real change is worse than one that is
    // vague. The line count is the backstop, and it prints whenever the notes
    // do not already account for the bytes: a rename or a level shift rewrites
    // one heading line and reporting that as "+1 line, -1 line" reads as churn
    // nobody asked for, while "added the section X" says nothing about its size.
    if notes.is_empty() {
        notes.push("changed text outside any heading".to_string());
        tally_wanted = true;
    }
    let mut tally: Vec<String> = Vec::new();
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

fn lines_delta(old: &str, new: &str) -> String {
    let (added, removed) = line_counts(old, new);
    let mut bits: Vec<String> = Vec::new();
    if added > 0 {
        bits.push(format!("+{added}"));
    }
    if removed > 0 {
        bits.push(format!("-{removed}"));
    }
    if bits.is_empty() {
        "same line count".to_string()
    } else {
        format!("{} lines", bits.join(", "))
    }
}

pub(crate) fn line_counts(before: &str, after: &str) -> (usize, usize) {
    let a = split_lines(before);
    let b = split_lines(after);
    let matcher = Matcher::new(&b);
    let (mut added, mut removed) = (0usize, 0usize);
    for (tag, i1, i2, j1, j2) in matcher.opcodes(&a) {
        if matches!(tag, Tag::Replace | Tag::Delete) {
            removed += i2 - i1;
        }
        if matches!(tag, Tag::Replace | Tag::Insert) {
            added += j2 - j1;
        }
    }
    (added, removed)
}

#[cfg(test)]
mod tests {
    use super::*;

    const DOC: &str = "# Guide\n\nIntro.\n\n## Install\n\nSteps here.\n\n## Usage\n\nUse it.\n";

    #[test]
    fn an_unchanged_document_does_not_claim_a_change() {
        assert_eq!(
            describe_change(DOC, DOC),
            "Applied, but the document is unchanged."
        );
    }

    #[test]
    fn a_body_edit_names_the_section_and_counts_the_lines() {
        let after = DOC.replace("Steps here.", "Steps here.\nAnd one more.");
        assert_eq!(
            describe_change(DOC, &after),
            "Applied: changed the body of \"Install\" (+1 lines)."
        );
    }

    #[test]
    fn a_swap_in_place_reads_as_a_rename_not_as_data_loss() {
        let after = DOC.replace("## Install", "## Setup");
        let text = describe_change(DOC, &after);
        assert_eq!(text, "Applied: renamed \"Install\" to \"Setup\".");
        assert!(
            !text.contains("removed"),
            "a rename must not read as a loss"
        );
    }

    #[test]
    fn a_deleted_subtree_collapses_into_one_note() {
        // Three headings go with the one that was named, and the count is the
        // fact worth reading.
        let before = "# A\n\n## B\n\n### C\n\n### D\n\n# E\n\nTail.\n";
        let after = "# A\n\n# E\n\nTail.\n";
        let text = describe_change(before, after);
        assert!(
            text.contains("removed the section \"B\" (level 2)"),
            "{text}"
        );
        assert!(text.contains("2 sections nested under it"), "{text}");
    }

    #[test]
    fn the_backstop_speaks_when_no_heading_moved() {
        // An edit before the first heading changes no section's own body and no
        // heading, so every branch above stays silent. Going quiet on a real
        // change is worse than being vague.
        let before = "Preamble.\n\n# A\n\nBody.\n";
        let after = "Preamble, edited.\n\n# A\n\nBody.\n";
        assert_eq!(
            describe_change(before, after),
            "Applied: changed text outside any heading. (+1 line, -1 line.)"
        );
    }
}
