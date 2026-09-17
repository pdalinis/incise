//! Line-level scanning shared by every op family.
//!
//! The Python reference splits this across `mdlist.py` (frontmatter, item
//! pattern), `mdsection.py` (fences, headings) and `mdtable.py` (its own
//! inline fence loop). The split there is historical — three parsers written in
//! three sessions — and `test_fence_scanners_agree` exists in the Python suite
//! only to stop the duplicates drifting. There is nothing to preserve about
//! that, so the port has one scanner and no drift to test for.
//!
//! Everything works on `content.split('\n')`, exactly as the oracle does, so a
//! CRLF line still carries its `\r` and the ending stays a property of the
//! line rather than of the document (`corpus/hazards/mixed-endings.md`).

/// `content.split("\n")` — including the trailing empty element a final
/// newline produces, which is what makes join-back byte-exact.
pub fn split_lines(content: &str) -> Vec<&str> {
    content.split('\n').collect()
}

/// `(line without its CR, "\r" or "")`.
pub fn split_eol(line: &str) -> (&str, &str) {
    match line.strip_suffix('\r') {
        Some(rest) => (rest, "\r"),
        None => (line, ""),
    }
}

/// Leading whitespace of a line, verbatim.
pub fn leading_ws(line: &str) -> &str {
    let end = line
        .find(|c: char| !c.is_whitespace())
        .unwrap_or(line.len());
    &line[..end]
}

/// Python's `str.strip()` for the ASCII-plus-Unicode whitespace set.
pub fn py_strip(s: &str) -> &str {
    s.trim_matches(|c: char| c.is_whitespace())
}

/// One bool per line: is this line inside (or part of) a fenced code block?
///
/// Run length is what makes nested fences work — a closing fence must be at
/// least as long as the one that opened the block, so the three-backtick fence
/// inside ````markdown does not close it. Naive matching terminates there and
/// reads the rest of `corpus/hazards/code-fences.md` as prose.
pub fn fence_mask(lines: &[&str]) -> Vec<bool> {
    let mut mask = vec![false; lines.len()];
    let mut fence: Option<(char, usize)> = None;
    for (i, ln) in lines.iter().enumerate() {
        let s = ln.trim_start();
        if let Some((ch, need)) = fence {
            mask[i] = true;
            if s.starts_with(ch) {
                let run = s.chars().take_while(|c| *c == ch).count();
                // A closing fence is only fence characters; an info string
                // (```markdown) can open a block but never closes one.
                if run >= need && s[run..].trim().is_empty() {
                    fence = None;
                }
            }
            continue;
        }
        if s.starts_with("```") || s.starts_with("~~~") {
            let ch = s.chars().next().unwrap();
            let need = s.chars().take_while(|c| *c == ch).count();
            fence = Some((ch, need));
            mask[i] = true;
        }
    }
    mask
}

/// `(start, end)` line indices of leading YAML/TOML frontmatter, or `None`.
///
/// A YAML sequence looks like a bullet list and a YAML comment looks like an
/// H1, so both parsers are wrong on `corpus/frontmatter/rich.md` without it.
/// An unterminated opening `---` is a thematic break, not frontmatter; treating
/// it as frontmatter would swallow the whole document.
pub fn frontmatter_span(lines: &[&str]) -> Option<(usize, usize)> {
    let first = py_strip(lines.first()?);
    if first != "---" && first != "+++" {
        return None;
    }
    for (i, ln) in lines.iter().enumerate().skip(1) {
        let s = py_strip(ln);
        if s == first || s == "..." {
            return Some((0, i));
        }
    }
    None
}

/// The parts of a list-item marker line, or `None` if the line is not one.
///
/// The oracle spells this as a regex — `^([ \t]*)([-*+]|\d{1,9}[.)])(?:([ \t]+)(.*)|()$)`
/// — and the alternation at the end is the part that carries meaning. A marker
/// followed by whitespace takes the first branch; a marker alone at end of line
/// takes the second, so an empty item is not read as a paragraph; a marker
/// followed by anything else matches neither, which is why `-x` is prose and
/// `- x` is a list.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ItemMatch<'a> {
    /// Group 1: leading spaces and tabs, verbatim.
    pub indent: &'a str,
    /// Group 2: `-` / `*` / `+`, or digits and a `.` or `)`.
    pub marker: &'a str,
    /// Group 3, and `None` on the bare-marker branch — where the oracle's group
    /// is `None` too, which several callers spell as `m.group(3) or " "`.
    pub gap: Option<&'a str>,
    /// Group 4, or `""` on the bare-marker branch.
    pub text: &'a str,
    /// `m.end(2)`. A byte offset here and a character offset there, equal
    /// because everything to its left is ASCII by construction.
    pub marker_end: usize,
}

/// `ITEM_RE.match(line)`.
pub fn match_item(line: &str) -> Option<ItemMatch<'_>> {
    // Spaces and tabs only: `[ \t]*` is narrower than `str.lstrip()`, and the
    // difference decides whether a line indented with a form feed is an item.
    let ind = line.len() - line.trim_start_matches([' ', '\t']).len();
    let rest = &line[ind..];
    let marker_len = if rest.starts_with(['-', '*', '+']) {
        1
    } else {
        // `\d{1,9}` with backtracking still fails on a tenth digit: every
        // shorter prefix leaves a digit where the delimiter must be.
        let digits = rest.chars().take_while(|c| c.is_ascii_digit()).count();
        if digits == 0 || digits > 9 {
            return None;
        }
        match rest[digits..].chars().next() {
            Some('.') | Some(')') => digits + 1,
            _ => return None,
        }
    };
    let after = &rest[marker_len..];
    let gap = after.len() - after.trim_start_matches([' ', '\t']).len();
    if gap > 0 {
        Some(ItemMatch {
            indent: &line[..ind],
            marker: &rest[..marker_len],
            gap: Some(&after[..gap]),
            text: &after[gap..],
            marker_end: ind + marker_len,
        })
    } else if after.is_empty() {
        Some(ItemMatch {
            indent: &line[..ind],
            marker: &rest[..marker_len],
            gap: None,
            text: "",
            marker_end: ind + marker_len,
        })
    } else {
        None
    }
}

/// Whether [`match_item`] matches. `\d{1,9}` is CommonMark's limit.
pub fn is_list_item(line: &str) -> bool {
    match_item(line).is_some()
}

/// `CHECKBOX_RE`: `^\[([ xX])\](?: |$)` against an item's text.
///
/// Returns the state character and `m.end()`, which is what the oracle slices
/// the text at. Anchored and spelled out rather than made permissive, because
/// the near misses in `corpus/lists/tasks.md` (`[]`, `[ ]no space`, `[y]`) must
/// all fail to match: each one is a plain item that happens to start with a
/// bracket, and treating it as a task would let `list-set-checked` rewrite it.
///
/// `$` is end of string, not end of line — the oracle's lines come from
/// `split("\n")`, so a CRLF document leaves `\r` in the text and `- [x]\r` is
/// deliberately not a task item on either side.
pub fn match_checkbox(text: &str) -> Option<(char, usize)> {
    let b = text.as_bytes();
    if b.len() < 3 || b[0] != b'[' || b[2] != b']' || !matches!(b[1], b' ' | b'x' | b'X') {
        return None;
    }
    match b.len() {
        3 => Some((b[1] as char, 3)),
        _ if b[3] == b' ' => Some((b[1] as char, 4)),
        _ => None,
    }
}

/// `len(s.expandtabs(4))` for a string of spaces and tabs: the column a run of
/// indentation ends at, which is the only width in which "four or more means
/// code" can be checked.
pub fn expanded_width(indent: &str) -> usize {
    let mut col = 0;
    for c in indent.chars() {
        if c == '\t' {
            col += 4 - col % 4;
        } else {
            col += 1;
        }
    }
    col
}

/// `BLOCKQUOTE_RE`: `^ {0,3}>`.
pub fn is_blockquote(line: &str) -> bool {
    let spaces = line.chars().take_while(|c| *c == ' ').count();
    spaces <= 3 && line[spaces..].starts_with('>')
}

/// `SETEXT_RE`: up to three spaces, then all `=` or all `-`, then optional
/// trailing whitespace. Whether such a line *is* a heading underline depends
/// entirely on what precedes it — that check lives in the heading scanner.
pub fn is_setext_rule(line: &str) -> Option<char> {
    let spaces = line.chars().take_while(|c| *c == ' ').count();
    if spaces > 3 {
        return None;
    }
    let rest = &line[spaces..];
    let ch = rest.chars().next()?;
    if ch != '=' && ch != '-' {
        return None;
    }
    let run = rest.chars().take_while(|c| *c == ch).count();
    if rest[run..].chars().all(|c| c == ' ' || c == '\t') {
        Some(ch)
    } else {
        None
    }
}

/// `LINKREF_RE`: `[label]: destination`.
pub fn is_link_ref(line: &str) -> bool {
    let spaces = line.chars().take_while(|c| *c == ' ').count();
    if spaces > 3 {
        return false;
    }
    let rest = &line[spaces..];
    if !rest.starts_with('[') {
        return false;
    }
    let close = match rest[1..].find(']') {
        Some(k) if k > 0 => 1 + k,
        _ => return false,
    };
    if !rest[close + 1..].starts_with(':') {
        return false;
    }
    let after = &rest[close + 2..];
    let trimmed = after.trim_start_matches([' ', '\t']);
    !trimmed.is_empty() && !trimmed.starts_with(|c: char| c.is_whitespace())
}

/// `ATX_RE` plus the closing-hash rule: up to three spaces of indent, one to
/// six hashes, then whitespace or end of line.
///
/// `#####Authentication` is not a heading, and four spaces of indent is an
/// indented code block rather than a heading — both fall out of the pattern
/// rather than needing a block model.
pub struct Atx {
    pub level: usize,
    /// Between the marker and any closing hashes, verbatim.
    pub raw_text: String,
    /// Addressing form: stripped, decoration removed.
    pub text: String,
    pub style: HeadingStyle,
    pub indent: String,
    pub marker: String,
    pub space: String,
    pub closing: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HeadingStyle {
    Atx,
    AtxClosed,
    Setext,
}

impl HeadingStyle {
    pub fn as_str(self) -> &'static str {
        match self {
            HeadingStyle::Atx => "atx",
            HeadingStyle::AtxClosed => "atx_closed",
            HeadingStyle::Setext => "setext",
        }
    }
}

pub fn parse_atx(line: &str) -> Option<Atx> {
    let spaces = line.chars().take_while(|c| *c == ' ').count();
    if spaces > 3 {
        return None;
    }
    let rest = &line[spaces..];
    let hashes = rest.chars().take_while(|c| *c == '#').count();
    if hashes == 0 || hashes > 6 {
        return None;
    }
    let after = &rest[hashes..];
    let (space, mut raw) = if after.is_empty() {
        (String::new(), String::new())
    } else {
        let ws = after
            .chars()
            .take_while(|c| *c == ' ' || *c == '\t')
            .count();
        if ws == 0 {
            // `#####Authentication`: no whitespace after the run, so the line
            // is not a heading at any shorter hash count either.
            return None;
        }
        (after[..ws].to_string(), after[ws..].to_string())
    };

    let mut style = HeadingStyle::Atx;
    let mut closing = String::new();
    if let Some((before, hashes_run)) = trailing_closing_hashes(&raw) {
        style = HeadingStyle::AtxClosed;
        closing = hashes_run;
        raw = before;
    } else {
        let t = py_strip(&raw);
        if !t.is_empty() && t.chars().all(|c| c == '#') {
            // `## ###` — all decoration, no text. Rare, but it addresses as "".
            style = HeadingStyle::AtxClosed;
            closing = t.to_string();
            raw = String::new();
        }
    }

    Some(Atx {
        level: hashes,
        text: py_strip(&raw).to_string(),
        raw_text: raw,
        style,
        indent: " ".repeat(spaces),
        marker: "#".repeat(hashes),
        space,
        closing,
    })
}

/// `CLOSING_RE`: `^(.*?)[ \t]+(#+)[ \t]*$`.
///
/// A closing hash sequence is decoration. It must be preceded by whitespace and
/// be nothing but hashes to the end, so `### foo #bar` keeps its `#bar`.
fn trailing_closing_hashes(rest: &str) -> Option<(String, String)> {
    let t = rest.trim_end_matches([' ', '\t']);
    let run = t.chars().rev().take_while(|c| *c == '#').count();
    if run == 0 {
        return None;
    }
    let split = t.len() - run;
    let before = &t[..split];
    let trimmed = before.trim_end_matches([' ', '\t']);
    if trimmed.len() == before.len() {
        // No whitespace between the text and the hashes: `foo###` is text.
        return None;
    }
    Some((trimmed.to_string(), t[split..].to_string()))
}
