//! Heading and section structure.
//!
//! A wrong section boundary is worse than a wrong table or list boundary,
//! because a section's span routinely covers most of a document — `## Install`
//! in `corpus/sections/deep-nesting.md` owns 32 lines and six subsections, so
//! getting `end` wrong by one heading silently eats or orphans a subtree.
//!
//! Three classes of heading-shaped line are deliberately not sections, and the
//! distinction is the whole difficulty of the file: inside a fenced code block,
//! indented four or more spaces, and inside a blockquote. None are silently
//! dropped — [`inert_headings`] returns every one with the reason, because
//! reporting "not found" for a heading the user can see on their screen is
//! worse than refusing.
//!
//! Unclosed fences run to end of document (CommonMark's choice), so the
//! trailing heading in `corpus/hazards/code-fences.md` is inert.

use crate::scan::{
    fence_mask, frontmatter_span, is_blockquote, is_link_ref, is_list_item, is_setext_rule,
    parse_atx, py_strip, split_eol, split_lines, HeadingStyle,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Section {
    /// Line index of the heading (setext: its text line).
    pub start: usize,
    /// Last line of the heading itself (setext: the underline).
    pub heading_end: usize,
    /// Last non-blank line of this section's own body.
    pub own_end: usize,
    /// Last non-blank line of the subtree.
    pub end: usize,
    pub level: usize,
    /// Addressing form: stripped, decoration removed.
    pub text: String,
    /// Between the marker and any closing hashes, verbatim.
    pub raw_text: String,
    pub style: HeadingStyle,
    pub indent: String,
    pub marker: String,
    pub space: String,
    pub closing: String,
    /// `"\r"` if the heading line is CRLF, else `""`.
    pub eol: String,
    /// Index into the section list, or `None`.
    pub parent: Option<usize>,
    /// Ancestor texts, ending with this section's own.
    pub path: Vec<String>,
    /// Blank lines between `end` and whatever follows.
    pub gap_after: usize,
}

impl Section {
    pub fn has_body(&self) -> bool {
        self.own_end > self.heading_end
    }

    pub fn slug(&self) -> String {
        self.path.join(" > ")
    }

    /// The heading line(s) as they should be written back.
    ///
    /// A rename goes through here rather than through string surgery at the
    /// call site, because three things have to survive that are easy to lose:
    /// the original syntax (setext stays setext), the closing hash run, and
    /// `eol` — `corpus/hazards/crlf.md` stores `\r` at the end of every line,
    /// and a heading rebuilt from `raw_text` alone converts exactly one line of
    /// a CRLF document to LF.
    pub fn rebuild(&self, text: Option<&str>) -> Vec<String> {
        let t = text.unwrap_or(&self.raw_text);
        if self.style == HeadingStyle::Setext {
            // The underline is re-run to the new text's width. Setext
            // underlines need only be one character long, but every corpus
            // fixture matches the title, and matching what was found is the
            // rule (§5.2).
            let ch = self.marker.chars().next().unwrap_or('=');
            let width = t.chars().count().max(1);
            return vec![
                format!("{}{}{}", self.indent, t, self.eol),
                format!(
                    "{}{}{}",
                    self.indent,
                    ch.to_string().repeat(width),
                    self.eol
                ),
            ];
        }
        if t.is_empty() {
            return vec![format!("{}{}{}", self.indent, self.marker, self.eol)];
        }
        let space = if self.space.is_empty() {
            " "
        } else {
            &self.space
        };
        let mut line = format!("{}{}{}{}", self.indent, self.marker, space, t);
        if self.style == HeadingStyle::AtxClosed {
            line.push(' ');
            line.push_str(&self.closing);
        }
        line.push_str(&self.eol);
        vec![line]
    }
}

/// Every addressable section in `content`, in document order.
pub fn find_sections(content: &str) -> Vec<Section> {
    let lines = split_lines(content);
    let mask = fence_mask(&lines);
    let skip = frontmatter_span(&lines);
    let in_fm = |i: usize| skip.is_some_and(|(lo, hi)| i >= lo && i <= hi);

    let mut sections: Vec<Section> = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        if mask[i] || in_fm(i) {
            i += 1;
            continue;
        }
        // Setext is checked first: its underline is line i and its text is line
        // i-1, which would otherwise already have been passed over.
        if is_setext(&lines, i, &mask, &in_fm) {
            let (body, eol) = split_eol(lines[i - 1]);
            let (rule, _) = split_eol(lines[i]);
            let rule = py_strip(rule);
            let indent_len = body.len() - body.trim_start().len();
            let text = py_strip(body).to_string();
            sections.push(Section {
                start: i - 1,
                heading_end: i,
                own_end: i - 1,
                end: i - 1,
                level: if rule.starts_with('=') { 1 } else { 2 },
                raw_text: text.clone(),
                text,
                style: HeadingStyle::Setext,
                indent: body[..indent_len].to_string(),
                marker: rule.to_string(),
                space: String::new(),
                closing: String::new(),
                eol: eol.to_string(),
                parent: None,
                path: Vec::new(),
                gap_after: 0,
            });
            i += 1;
            continue;
        }
        if is_blockquote(lines[i]) {
            i += 1;
            continue;
        }
        let (body, eol) = split_eol(lines[i]);
        if let Some(a) = parse_atx(body) {
            sections.push(Section {
                start: i,
                heading_end: i,
                own_end: i,
                end: i,
                level: a.level,
                text: a.text,
                raw_text: a.raw_text,
                style: a.style,
                indent: a.indent,
                marker: a.marker,
                space: a.space,
                closing: a.closing,
                eol: eol.to_string(),
                parent: None,
                path: Vec::new(),
                gap_after: 0,
            });
        }
        i += 1;
    }

    // Spans. `own_end` stops at the next heading of ANY level — the section's
    // own prose. `end` stops at the next heading of the same level or lower, so
    // it covers the subtree. "Append to this section" and "delete this section"
    // need different answers to "where does it stop".
    //
    // Both are capped at `footer`, so a trailing link-reference block belongs to
    // the document rather than to whichever section happens to be last.
    let footer = footer_start(&lines, &mask);
    for n in 0..sections.len() {
        let next = sections
            .get(n + 1)
            .map(|s| s.start)
            .unwrap_or(lines.len())
            .min(footer);
        let heading_end = sections[n].heading_end;
        let level = sections[n].level;
        sections[n].own_end =
            trim_blank(&lines, heading_end, heading_end.max(next.saturating_sub(1)));

        let mut sub = lines.len();
        for following in sections.iter().skip(n + 1) {
            if following.level <= level {
                sub = following.start;
                break;
            }
        }
        let sub = sub.min(footer);
        sections[n].end = trim_blank(&lines, heading_end, heading_end.max(sub.saturating_sub(1)));
        sections[n].gap_after = sub.saturating_sub(sections[n].end + 1);
    }

    // Parents and paths. Nearest preceding heading of *lower* level, which
    // handles both a forest of H1s and a document that skips from H2 to H4.
    let mut stack: Vec<(usize, usize)> = Vec::new(); // (level, index)
    for n in 0..sections.len() {
        let level = sections[n].level;
        while stack.last().is_some_and(|(l, _)| *l >= level) {
            stack.pop();
        }
        let parent = stack.last().map(|(_, idx)| *idx);
        sections[n].parent = parent;
        let mut path = match parent {
            Some(p) => sections[p].path.clone(),
            None => Vec::new(),
        };
        path.push(sections[n].text.clone());
        sections[n].path = path;
        stack.push((level, n));
    }
    sections
}

/// Is line `i` a setext underline for line `i-1`?
///
/// Everything here is about what the *previous* line is. `---` under text is an
/// H2; the identical `---` after a blank line is a thematic break, and
/// `corpus/sections/setext-and-atx.md` puts both in one document three lines
/// apart.
fn is_setext(lines: &[&str], i: usize, mask: &[bool], in_fm: &dyn Fn(usize) -> bool) -> bool {
    if i == 0 || mask[i] || in_fm(i) {
        return false;
    }
    let (rule, _) = split_eol(lines[i]);
    if is_setext_rule(rule).is_none() {
        return false;
    }
    let (prev, _) = split_eol(lines[i - 1]);
    if py_strip(prev).is_empty() || mask[i - 1] || in_fm(i - 1) {
        return false;
    }
    if prev.len() - prev.trim_start_matches(' ').len() >= 4 {
        return false;
    }
    // The line above must be an ordinary paragraph. A heading, a list item, a
    // blockquote or another underline is not lazily continued into one.
    if parse_atx(prev).is_some() || is_list_item(prev) || is_blockquote(prev) {
        return false;
    }
    is_setext_rule(prev).is_none()
}

/// Heading-shaped lines deliberately excluded, with the reason for each.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InertHeading {
    pub line: usize,
    pub text: String,
    pub reason: &'static str,
}

pub fn inert_headings(content: &str) -> Vec<InertHeading> {
    let lines = split_lines(content);
    let mask = fence_mask(&lines);
    let skip = frontmatter_span(&lines);
    let in_fm = |i: usize| skip.is_some_and(|(lo, hi)| i >= lo && i <= hi);

    let mut out = Vec::new();
    for (i, ln) in lines.iter().enumerate() {
        let stripped = py_strip(ln);
        if !stripped.starts_with('#') && !is_blockquote(ln) {
            continue;
        }
        let (text, reason) = if in_fm(i) {
            let t = parse_atx(stripped)
                .map(|a| a.text)
                .unwrap_or_else(|| stripped.to_string());
            (t, "frontmatter")
        } else if mask[i] {
            match parse_atx(stripped) {
                Some(a) => (a.text, "code-fence"),
                None => continue,
            }
        } else if is_blockquote(ln) {
            match parse_atx(strip_quote(ln)) {
                Some(a) => (a.text, "blockquote"),
                None => continue,
            }
        } else if ln.len() - ln.trim_start_matches(' ').len() >= 4 {
            match parse_atx(stripped) {
                Some(a) => (a.text, "indented-code"),
                None => continue,
            }
        } else {
            continue;
        };
        out.push(InertHeading {
            line: i,
            text,
            reason,
        });
    }
    out
}

/// `re.sub(r"^ {0,3}> ?", "", line)`.
fn strip_quote(line: &str) -> &str {
    let spaces = line.chars().take_while(|c| *c == ' ').count();
    if spaces > 3 || !line[spaces..].starts_with('>') {
        return line;
    }
    let rest = &line[spaces + 1..];
    rest.strip_prefix(' ').unwrap_or(rest)
}

/// Index where a document's trailing link-reference block begins, or
/// `lines.len()` when there is none, so callers can use it as a cap
/// unconditionally.
///
/// A deliberate departure from the structure of the document, because the
/// alternative is silent data loss: by CommonMark the six `[1.4.2]: https://…`
/// lines at the bottom of `corpus/documents/changelog.md` are inside the *last*
/// section, so "delete the 1.2.0 release" — an ordinary, safe-sounding request
/// — deleted every link definition in the file, including ones for releases
/// that were still there.
///
/// The rule is as narrow as it can be, because inventing markdown semantics is
/// how a tool starts being wrong in ways nobody predicted: the run must be at
/// the very end of the document, every line in it a link reference definition,
/// and a blank line must separate it from what precedes it.
fn footer_start(lines: &[&str], mask: &[bool]) -> usize {
    let mut i = lines.len() as isize - 1;
    while i >= 0 && py_strip(lines[i as usize]).is_empty() {
        i -= 1;
    }
    if i < 0 || mask[i as usize] || !is_link_ref(lines[i as usize]) {
        return lines.len();
    }
    while i >= 0 && !mask[i as usize] && is_link_ref(lines[i as usize]) {
        i -= 1;
    }
    // Must be a block of its own, not the tail of a paragraph.
    if i >= 0 && !py_strip(lines[i as usize]).is_empty() {
        return lines.len();
    }
    (i + 1) as usize
}

fn trim_blank(lines: &[&str], lo: usize, hi: usize) -> usize {
    let mut hi = hi.min(lines.len().saturating_sub(1));
    while hi > lo && py_strip(lines[hi]).is_empty() {
        hi -= 1;
    }
    hi
}

/// The document's dominant blank-line gap between sections.
///
/// A document that separates its headings with one blank line and a document
/// that uses two are both correct, and an inserted section has to match the one
/// it joins rather than a house style. Read off the document, never assumed.
pub fn heading_gap(sections: &[Section]) -> usize {
    let gaps: Vec<usize> = sections
        .iter()
        .filter(|s| s.has_body() && s.gap_after > 0)
        .map(|s| s.gap_after)
        .collect();
    if gaps.is_empty() {
        return 1;
    }
    // `max(set(gaps), key=gaps.count)`: most frequent gap, ties broken by the
    // *smallest*. The oracle iterates a `set` of small integers, whose CPython
    // order is ascending for the values a blank-line gap can take, and `max`
    // keeps the first maximum it sees — so the smallest tied gap wins there.
    // Relying on set iteration order would be a bug in either language; the
    // tiebreak is written down instead so the two agree by construction.
    let mut best: Option<(usize, usize)> = None; // (count, gap)
    for g in gaps
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>()
    {
        let count = gaps.iter().filter(|x| **x == g).count();
        if best.is_none_or(|(c, _)| count > c) {
            best = Some((count, g));
        }
    }
    best.map_or(1, |(_, g)| g)
}

/// Everything except the section's subtree, for byte-identity checks.
pub fn outside_section(content: &str, sec: &Section) -> String {
    let lines = split_lines(content);
    let mut kept: Vec<&str> = lines[..sec.start].to_vec();
    kept.extend_from_slice(&lines[sec.end + 1..]);
    kept.join("\n")
}
