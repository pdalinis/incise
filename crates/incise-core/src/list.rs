//! Markdown list location and shape — the list family's [`crate::table`].
//!
//! Small and strict for the same reason: a wrong list boundary makes every
//! downstream edit land in the wrong place, so an ambiguous case ends a list
//! rather than absorbs the next thing. What a "list" is here follows CommonMark
//! on the three points that decide an edit:
//!
//! * A **marker change ends the list.** `- a` followed by `* b` is two lists,
//!   not one list of two items (`corpus/lists/nested-mixed.md`). An op that
//!   appended to "the list" without knowing this would insert into the wrong
//!   one.
//! * **Ordered delimiters are part of the marker.** `1.` and `1)` are different
//!   lists, and an inserted item must match the one it joins.
//! * **Loose vs tight is a property of the whole list**, decided by whether a
//!   blank line separates any two of its items. Inserting into a loose list
//!   without the blank changes how every item renders.
//!
//! Nesting is flattened: [`MdList::items`] holds every item in the run, each
//! carrying its `depth`. That is not a shortcut — it is what makes the op
//! vocabulary content-addressed. An item inserted after `beta-two` takes
//! `beta-two`'s indent and marker, so "add a nested item" needs no depth
//! argument and there is no way to spell an impossible one (§6.4).

use crate::scan::{
    expanded_width, fence_mask, frontmatter_span, leading_ws, match_checkbox, match_item, py_strip,
    split_lines, ItemMatch,
};

/// One item of a run, at any depth.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListItem {
    /// Line index of the marker line.
    pub start: usize,
    /// Last line of this item's own content, excluding its children.
    pub own_end: usize,
    /// Last line of the item's subtree, children included.
    pub end: usize,
    /// 0 for a top-level item of the run.
    pub depth: usize,
    /// Leading whitespace of the marker line, verbatim.
    pub indent: String,
    /// `-` / `*` / `+` / `3.` / `3)`.
    pub marker: String,
    pub ordered: bool,
    /// Ordered only.
    pub number: Option<i64>,
    /// `.` or `)`, ordered only.
    pub delim: Option<char>,
    /// `' '`, `'x'`, `'X'`, or `None` when the item is not a task.
    pub checkbox: Option<char>,
    /// Content after the marker and the checkbox.
    pub text: String,
    /// Index into [`MdList::items`].
    pub parent: Option<usize>,
}

impl ListItem {
    /// The marker's identity for sibling-matching: the character, or — for an
    /// ordered item — its delimiter, because the number varies and the
    /// delimiter does not.
    pub fn bullet(&self) -> String {
        match self.delim {
            Some(d) if self.ordered => d.to_string(),
            _ => self.marker.clone(),
        }
    }
}

/// One top-level list run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MdList {
    pub start: usize,
    /// Last non-blank line of the run; a trailing blank belongs to the document.
    pub end: usize,
    pub ordered: bool,
    /// `-` / `*` / `+` / `.` / `)`.
    pub bullet: String,
    pub indent: String,
    pub loose: bool,
    pub items: Vec<ListItem>,
    pub lines: Vec<String>,
}

impl MdList {
    pub fn texts(&self) -> Vec<String> {
        self.items.iter().map(|it| it.text.clone()).collect()
    }
}

fn bullet_of(marker: &str) -> &str {
    if marker.as_bytes()[0].is_ascii_digit() {
        &marker[marker.len() - 1..]
    } else {
        marker
    }
}

fn is_ordered(marker: &str) -> bool {
    marker.as_bytes()[0].is_ascii_digit()
}

/// Everything an item's marker line says about it.
fn parse_marker(m: &ItemMatch<'_>) -> ListItem {
    let ordered = is_ordered(m.marker);
    let (number, delim) = if ordered {
        (
            m.marker[..m.marker.len() - 1].parse::<i64>().ok(),
            m.marker.chars().last(),
        )
    } else {
        (None, None)
    };
    let (checkbox, rest) = match match_checkbox(m.text) {
        Some((c, end)) => (Some(c), &m.text[end..]),
        None => (None, m.text),
    };
    ListItem {
        start: 0,
        own_end: 0,
        end: 0,
        depth: 0,
        indent: m.indent.to_string(),
        marker: m.marker.to_string(),
        ordered,
        number,
        delim,
        checkbox,
        // `str.rstrip()`, which takes the `\r` of a CRLF line with it.
        text: rest
            .trim_end_matches(|c: char| c.is_whitespace())
            .to_string(),
        parent: None,
    }
}

/// Every top-level list in `content`, skipping fenced code and frontmatter.
///
/// Only runs that *start* at an indent of less than four are returned: a list
/// nested inside another is part of its parent's run, and a block indented four
/// or more is code. Both are deliberate — the addressable unit is the top-level
/// list, and nested items are reached through it.
///
/// Frontmatter is skipped because a YAML block sequence is spelled exactly like
/// a bullet list. Without the skip, `corpus/frontmatter/rich.md` reports two
/// lists that are not lists, and the summary offers the model an edit that would
/// corrupt the document's metadata.
pub fn find_lists(content: &str) -> Vec<MdList> {
    let lines = split_lines(content);
    // The fence scanner starts after the frontmatter, as the oracle's does, so
    // a stray ``` inside a YAML value cannot open a block over the document.
    let from = frontmatter_span(&lines).map_or(0, |(_, e)| e + 1);
    let mask = fence_mask(&lines[from..]);
    let mut out = Vec::new();
    let mut i = from;
    while i < lines.len() {
        if mask[i - from] {
            i += 1;
            continue;
        }
        match match_item(lines[i]) {
            Some(m) if expanded_width(m.indent) < 4 => {
                let (lst, next) = consume_run(&lines, i);
                out.push(lst);
                i = next;
            }
            _ => i += 1,
        }
    }
    out
}

/// Consume one list run beginning at `start`. Returns the list and the next
/// line to scan from.
fn consume_run(lines: &[&str], start: usize) -> (MdList, usize) {
    let m0 = match_item(lines[start]).expect("consume_run called on a marker line");
    let base_indent = m0.indent.to_string();
    let base_bullet = bullet_of(m0.marker).to_string();
    let base_ordered = is_ordered(m0.marker);

    // Line index of every item marker in the run, at any depth.
    let mut marker_lines: Vec<usize> = Vec::new();
    let mut end = start;
    let (mut j, mut blanks) = (start, 0);
    while j < lines.len() {
        let ln = lines[j];
        if py_strip(ln).is_empty() {
            blanks += 1;
            // Two blank lines end any list; one may separate loose items.
            if blanks >= 2 {
                break;
            }
            j += 1;
            continue;
        }
        let indent = leading_ws(ln);
        let m = match_item(ln);
        if indent.chars().count() <= base_indent.chars().count() {
            // Back at (or outside) the run's own level: only a matching marker
            // continues it. A different bullet starts a NEW list, and a
            // non-marker line ends it.
            match &m {
                None => break,
                Some(_) if indent != base_indent => break,
                Some(mm) if bullet_of(mm.marker) != base_bullet => break,
                Some(mm) if is_ordered(mm.marker) != base_ordered => break,
                Some(_) => {}
            }
        }
        if m.is_some() {
            marker_lines.push(j);
        }
        blanks = 0;
        end = j;
        j += 1;
    }

    let mut items: Vec<ListItem> = Vec::new();
    // (indent width, item index) of the open ancestors.
    let mut stack: Vec<(usize, usize)> = Vec::new();
    for &li in &marker_lines {
        let m = match_item(lines[li]).expect("recorded as a marker line");
        let mut item = parse_marker(&m);
        let ind = expanded_width(m.indent);
        while stack.last().is_some_and(|(w, _)| *w >= ind) {
            stack.pop();
        }
        item.start = li;
        item.own_end = li;
        item.end = li;
        item.depth = stack.len();
        item.parent = stack.last().map(|(_, idx)| *idx);
        stack.push((ind, items.len()));
        items.push(item);
    }

    // Spans: `own_end` stops at the next marker of any depth; `end` stops at
    // the next marker at this depth or shallower, so it covers the subtree.
    for n in 0..items.len() {
        let nxt = marker_lines.get(n + 1).copied().unwrap_or(end + 1);
        items[n].own_end = trim_blank(lines, items[n].start, nxt - 1);
        let mut sub = end + 1;
        for k in n + 1..items.len() {
            if items[k].depth <= items[n].depth {
                sub = items[k].start;
                break;
            }
        }
        items[n].end = trim_blank(lines, items[n].start, sub - 1);
    }

    // Loose iff a blank line separates two items of the run.
    let loose = (0..items.len().saturating_sub(1))
        .any(|n| (items[n].end + 1..items[n + 1].start).any(|k| py_strip(lines[k]).is_empty()));

    (
        MdList {
            start,
            end,
            ordered: base_ordered,
            bullet: base_bullet,
            indent: base_indent,
            loose,
            items,
            lines: lines[start..=end].iter().map(|s| s.to_string()).collect(),
        },
        end + 1,
    )
}

fn trim_blank(lines: &[&str], lo: usize, mut hi: usize) -> usize {
    while hi > lo && py_strip(lines[hi]).is_empty() {
        hi -= 1;
    }
    hi
}

/// Everything except the list's own lines, for byte-identity checks.
pub fn outside_list(content: &str, lst: &MdList) -> String {
    let lines = split_lines(content);
    let mut kept: Vec<&str> = lines[..lst.start].to_vec();
    kept.extend_from_slice(&lines[lst.end + 1..]);
    kept.join("\n")
}
