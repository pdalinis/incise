//! GFM table location and geometry.
//!
//! Deliberately small and strict: it only needs to handle the corpus fixtures,
//! and it must never silently mis-locate a table — a wrong table index makes
//! every downstream edit land in the wrong place.

use crate::scan::{fence_mask, py_strip, split_lines};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Table {
    /// First line index (0-based, inclusive).
    pub start: usize,
    /// Last line index (inclusive).
    pub end: usize,
    pub lines: Vec<String>,
}

impl Table {
    pub fn header(&self) -> &str {
        &self.lines[0]
    }

    pub fn delimiter(&self) -> &str {
        &self.lines[1]
    }

    pub fn body(&self) -> &[String] {
        &self.lines[2..]
    }

    /// Character count between pipes, per row. Equal vectors mean aligned.
    ///
    /// Character count, not byte count. A byte count would read a multi-byte
    /// cell as wider than it prints, and since padding is emitted in
    /// characters the row would come out over-padded and the column ragged.
    ///
    /// The corpus alone does not prove this: its aligned tables do hold
    /// non-ASCII cells, but only short ones (`—`, `–`) that are never the
    /// widest in their column, so the two counts agree everywhere it matters.
    /// `bench/difftest.py` adds a deliberately wide non-ASCII value for that
    /// reason -- without it the byte-count mutation survives, which is how the
    /// gap was found (`bench/mutate.py`).
    pub fn widths(&self) -> Vec<Vec<usize>> {
        self.lines
            .iter()
            .map(|ln| split_row(ln).iter().map(|c| c.chars().count()).collect())
            .collect()
    }

    pub fn is_aligned(&self) -> bool {
        let w = self.widths();
        w.windows(2).all(|p| p[0] == p[1])
    }

    pub fn cells(&self, line: &str) -> Vec<String> {
        split_row(line)
            .into_iter()
            .map(|c| py_strip(c).to_string())
            .collect()
    }

    pub fn columns(&self) -> Vec<String> {
        self.cells(self.header())
    }

    pub fn rows(&self) -> Vec<Vec<String>> {
        self.body().iter().map(|ln| self.cells(ln)).collect()
    }

    /// True if any of the table's lines contains a tab.
    ///
    /// `corpus/hazards/whitespace.md` pads its cells with tabs. Those cells have
    /// equal *character* counts, so the alignment check reports aligned and the
    /// re-pad path rewrites every tab to spaces — a silent whitespace rewrite of
    /// lines nobody asked to touch. Character-count alignment is the only kind
    /// that can be maintained arithmetically; tab alignment depends on a tab
    /// stop this tool does not know. So a tab-containing table is treated as
    /// ragged, following §5.2's rule that a table whose alignment cannot be
    /// verified counts as ragged.
    pub fn has_tabs(&self) -> bool {
        self.lines.iter().any(|ln| ln.contains('\t'))
    }
}

/// The raw text between pipes, escapes left intact.
///
/// The obvious `line.split('|')` is wrong, and was wrong here and in the oracle
/// for the whole of Tier 1. GFM lets a cell hold a literal pipe by escaping it,
/// so this row from `corpus/tables/cell-edge-cases.md`
///
/// ```text
/// | escaped pipe    | a \| b                   | literal pipe, backslashed  |
/// ```
///
/// has three cells, not four. Reading four made the table look non-rectangular,
/// and made `table-update-cell` on `Note` overwrite the fragment `b` and emit a
/// four-column row — reported as success, on the fixture whose stated purpose is
/// "Any operation on this table must round-trip every cell exactly."
///
/// A backslash escapes the character after it, so `\|` is content and `\\|` is a
/// literal backslash followed by a real separator. Consuming the pair is the only
/// way to tell those apart. Identical to the naive split on any line without a
/// backslash, which is every line in the corpus but two.
pub fn split_row(line: &str) -> Vec<&str> {
    let s = line.trim_end();
    let mut parts: Vec<&str> = Vec::new();
    let mut start = 0usize;
    let mut it = s.char_indices();
    while let Some((i, c)) = it.next() {
        if c == '\\' {
            // The escaped character, whatever its width. A trailing backslash
            // escapes nothing and stays content, as it does in the oracle.
            it.next();
        } else if c == '|' {
            parts.push(&s[start..i]);
            start = i + 1; // `|` is one byte
        }
    }
    parts.push(&s[start..]);
    if parts.len() < 2 {
        return Vec::new();
    }
    parts[1..parts.len() - 1].to_vec()
}

fn is_delimiter(line: &str) -> bool {
    let s = py_strip(line);
    if !s.starts_with('|') {
        return false;
    }
    let cells = split_row(s);
    if cells.is_empty() {
        // `split("|")[1:-1]` on a lone `|` is empty, and `all([])` is true in
        // Python — but a bare `|` has no columns, so the loop below never runs
        // and the line qualifies. Kept faithful deliberately: the header line
        // above it still has to start with `|` for a table to be recognised.
        return true;
    }
    cells.iter().all(|cell| {
        let c = py_strip(cell);
        !c.is_empty() && c.chars().all(|ch| ch == '-' || ch == ':') && c.contains('-')
    })
}

/// Every GFM table in `content`, skipping fenced and indented code.
///
/// A table is a header line, a delimiter line, and zero or more body lines, all
/// starting with `|` at an indent of less than four spaces — four or more would
/// make it an indented code block.
pub fn find_tables(content: &str) -> Vec<Table> {
    let lines = split_lines(content);
    let mask = fence_mask(&lines);
    let mut tables = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        if mask[i] {
            i += 1;
            continue;
        }
        let stripped = lines[i].trim_start();
        let indent = lines[i].len() - stripped.len();
        let next_ok = i + 1 < lines.len()
            && !mask[i + 1]
            && is_delimiter(lines[i + 1])
            && (lines[i + 1].len() - lines[i + 1].trim_start().len()) < 4;
        if indent < 4 && stripped.starts_with('|') && next_ok {
            let start = i;
            i += 2;
            while i < lines.len() {
                let nxt = lines[i].trim_start();
                if !nxt.starts_with('|') || (lines[i].len() - nxt.len()) >= 4 {
                    break;
                }
                i += 1;
            }
            tables.push(Table {
                start,
                end: i - 1,
                lines: lines[start..i].iter().map(|s| s.to_string()).collect(),
            });
            continue;
        }
        i += 1;
    }
    tables
}

/// Everything except the table's own lines, for byte-identity checks.
pub fn outside_table(content: &str, table: &Table) -> String {
    let lines = split_lines(content);
    let mut kept: Vec<&str> = lines[..table.start].to_vec();
    kept.extend_from_slice(&lines[table.end + 1..]);
    kept.join("\n")
}
