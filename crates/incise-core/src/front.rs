//! Frontmatter parsing — the fourth sibling of [`crate::table`], [`crate::list`]
//! and [`crate::heading`], and the port of `bench/mdfront.py`.
//!
//! It sits beside [`crate::list`] rather than above it because
//! [`crate::scan::frontmatter_span`] already lives one level down —
//! `find_lists` and `find_sections` both need it, since a YAML sequence looks
//! like a bullet list and a YAML comment looks like an H1 — and asking two
//! modules where the frontmatter is, is how they come to disagree.
//!
//! **This is not a YAML parser and must never become one.**
//! `corpus/frontmatter/rich.md:37-43` is the whole specification:
//!
//! > `frontmatter-set build.jobs 8` must change exactly that value. Key order,
//! > the leading comment, the inline comment on `build.target`, the block
//! > scalar styles, and the quoting of `quoted_key` must all be byte-identical
//! > afterward. Most YAML libraries destroy at least three of those on a
//! > load/dump round trip.
//!
//! A parse-and-serialize design fails that by construction, so nothing here
//! loads a value into a value type and writes it back. Every [`Entry`] records
//! the pieces of its own line — the text before the key, the key exactly as
//! written, the gap after the colon, the value, the padding, the trailing
//! comment — and an edit rewrites one of those pieces and leaves the rest of the
//! line alone. Lines no edit names are never touched at all, which is why
//! comments, blank lines and block scalar styles survive without any code that
//! knows they exist.
//!
//! What is deliberately *not* modelled: anchors, aliases, tags, flow mappings
//! (`{a: 1}`), flow sequences (`[1, 2]`), multi-document streams, and merge
//! keys. None appears in the corpus. They parse as opaque scalar text, which is
//! the safe failure: an op that cannot address inside them refuses, and one that
//! rewrites a sibling leaves them byte-identical.
//!
//! The oracle spells its four scanners as regexes. Each one is hand-written
//! here, in [`crate::scan::match_item`]'s style, with the pattern quoted above
//! the function and the part that carries meaning called out — the crate takes
//! no dependencies, and a regex crate would be one.

use crate::scan::{frontmatter_span, py_strip};

/// One segment of a frontmatter address: a key, or an index into a sequence.
///
/// The index is held as canonical decimal digits rather than an integer. The
/// oracle's is a Python `int`, which is unbounded, so `authors[99999999999999999999]`
/// is an address it can hold, fail to resolve, and quote back in the refusal.
/// A `usize` here would overflow on exactly that input; canonical digits —
/// leading zeros stripped, so `[007]` and `[7]` are one address, as `int()`
/// makes them — compare and print identically to the oracle's integers at every
/// width.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Seg {
    Key(String),
    Index(String),
}

/// What an [`Entry`] holds. The oracle's `kind` string.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Scalar,
    Null,
    Map,
    Seq,
    Block,
    Item,
}

impl Kind {
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Scalar => "scalar",
            Kind::Null => "null",
            Kind::Map => "map",
            Kind::Seq => "seq",
            Kind::Block => "block",
            Kind::Item => "item",
        }
    }
}

/// One addressable thing in the block, and every byte of the line it owns.
///
/// `line` is where the key is written and `end` is the last line of what it
/// owns — the same line for a scalar, the last child for a map, the last
/// content line for a block scalar. Deleting an entry is `lines[line..=end]`,
/// and that is the only definition of "this key's lines" anywhere in the family.
#[derive(Clone, Debug)]
pub struct Entry {
    /// `("build", "jobs")` or `("authors", 0, "role")`.
    pub path: Vec<Seg>,
    /// Line index of the key, or of the `-` for an item.
    pub line: usize,
    /// Inclusive last line owned by this entry.
    pub end: usize,
    /// Everything before the key, verbatim: indent, or `"  - "`.
    pub prefix: String,
    /// The key as written, quotes included; empty for an item.
    pub key_text: String,
    /// Between the colon and the value.
    pub gap: String,
    /// The value text on the key line, verbatim.
    pub value: String,
    /// Between the value and the comment.
    pub pad: String,
    /// `"# ..."`, verbatim, or empty.
    pub comment: String,
    pub kind: Kind,
    /// `"\r"` if this line is CRLF, else empty.
    pub eol: String,
}

impl Entry {
    /// The column the key starts in — what a sibling must align to.
    ///
    /// A byte length where the oracle takes a character length, equal because
    /// `prefix` is spaces, or spaces and `- `, by construction.
    pub fn indent(&self) -> usize {
        self.prefix.len()
    }

    /// This entry's key line, with `value` swapped in if one is given.
    ///
    /// The gap is decided by the value, not kept blindly: `empty_value:`
    /// becomes `empty_value: 4`, and setting a key to null gives back `title:`
    /// rather than `title: ` with a trailing space that was never in the file.
    /// `target: release        # comment` keeps both its gap and its padding,
    /// which is what holds the inline comment in the column it was written in.
    ///
    /// The `\r` goes back on last. Lines arrive from a split on `\n`, so a CRLF
    /// line still carries one; a line rebuilt without it is a silent conversion
    /// of that line to LF, which is `_table_eol`'s defect one family over.
    pub fn rebuilt(&self, value: Option<&str>) -> String {
        let v = value.unwrap_or(&self.value);
        if self.kind == Kind::Item {
            // An item has no key and no colon; the dash is already in `prefix`.
            // A bare `-` carries no gap, so one is supplied rather than writing
            // `-value`, which is a scalar beginning with a dash and not an item.
            let mut pre = self.prefix.clone();
            if !v.is_empty() && !pre.ends_with(' ') && !pre.ends_with('\t') {
                pre.push(' ');
            } else if v.is_empty() && self.pad.is_empty() && self.comment.is_empty() {
                // `- ` with nothing after it is a null item written with a
                // trailing space the file never had; `-` alone is the same item.
                pre = pre.trim_end_matches([' ', '\t']).to_string();
            }
            return format!("{pre}{v}{}{}{}", self.pad, self.comment, self.eol);
        }
        let gap = if v.is_empty() {
            ""
        } else if self.gap.is_empty() {
            " "
        } else {
            &self.gap
        };
        format!(
            "{}{}:{gap}{v}{}{}{}",
            self.prefix, self.key_text, self.pad, self.comment, self.eol
        )
    }
}

/// The block's format. `+++` is a span but never an editable block.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fmt {
    Yaml,
    Toml,
}

/// The block, its format, and every addressable entry in it.
#[derive(Clone, Debug)]
pub struct FrontMatter {
    pub present: bool,
    pub fmt: Option<Fmt>,
    /// Opening delimiter line. Meaningful only when `present`.
    pub start: usize,
    /// Closing delimiter line. Meaningful only when `present`.
    pub end: usize,
    /// `"---"` / `"+++"`, verbatim, or empty when absent.
    pub delim: String,
    /// The closing delimiter as written — may be `...`.
    pub close: String,
    pub entries: Vec<Entry>,
    /// The block's own line ending, for lines inserted into it.
    pub eol: String,
}

impl FrontMatter {
    /// The entry at `path`, if one is written.
    ///
    /// **The last one, when a key is written twice.** The oracle spells this as
    /// `{e.path: e for e in self.entries}`, and a Python dict comprehension
    /// keeps the last value for a repeated key — so on `a: 1` followed by
    /// `a: 2`, a set rewrites the second line and a delete removes it. Nothing
    /// forbids a duplicate key in a hand-edited block, and taking the first
    /// would edit a line the document's own readers ignore.
    ///
    /// A reverse scan where the oracle builds a dict. The blocks this runs on
    /// have tens of entries, and a scan keeps document order the single source
    /// of truth — [`Self::by_path_map`] depends on that order and would
    /// otherwise need its own ordering put back.
    pub fn by_path(&self, path: &[Seg]) -> Option<&Entry> {
        self.entries.iter().rev().find(|e| e.path == path)
    }

    /// Every distinct path with its entry, in dict order.
    ///
    /// Python's dict, exactly: a repeated key keeps the position of its **first**
    /// appearance and the value of its **last**. Both halves are load-bearing —
    /// the position is the order a change summary lists its notes in, and the
    /// value is the line an edit lands on.
    pub fn by_path_map(&self) -> Vec<(&[Seg], &Entry)> {
        let mut out: Vec<(&[Seg], &Entry)> = Vec::new();
        for e in &self.entries {
            match out.iter_mut().find(|(p, _)| *p == e.path.as_slice()) {
                Some(slot) => slot.1 = e,
                None => out.push((e.path.as_slice(), e)),
            }
        }
        out
    }

    pub fn has(&self, path: &[Seg]) -> bool {
        self.by_path(path).is_some()
    }

    /// Entries written exactly one level under `path`.
    pub fn children_of(&self, path: &[Seg]) -> Vec<&Entry> {
        self.entries
            .iter()
            .filter(|e| e.path.len() == path.len() + 1 && e.path.starts_with(path))
            .collect()
    }

    /// Top-level entries.
    pub fn top(&self) -> Vec<&Entry> {
        self.entries.iter().filter(|e| e.path.len() == 1).collect()
    }
}

// --------------------------------------------------------------------------
// the four scanners
// --------------------------------------------------------------------------

/// `SEQ_RE`: `^([ ]*)(-)(?:([ \t]+)(.*)|()$)`, a sequence entry.
///
/// The empty branch is spelled out so `-` alone is an item rather than a scalar
/// that happens to start with a dash. The indent is spaces only, which is
/// narrower than `lstrip()` and is what the sibling comparisons in
/// [`seq_at`] and [`parse`] measure against.
struct SeqMatch<'a> {
    indent: &'a str,
    /// Group 3, or `""` on the bare-marker branch — the oracle reads it as
    /// `m.group(3) or ""`.
    sp: &'a str,
    /// Group 4, or `""` on the bare-marker branch.
    content: &'a str,
}

fn match_seq(line: &str) -> Option<SeqMatch<'_>> {
    let ind = line.len() - line.trim_start_matches(' ').len();
    let rest = &line[ind..];
    if !rest.starts_with('-') {
        return None;
    }
    let after = &rest[1..];
    let sp = after.len() - after.trim_start_matches([' ', '\t']).len();
    if sp > 0 {
        Some(SeqMatch {
            indent: &line[..ind],
            sp: &after[..sp],
            content: &after[sp..],
        })
    } else if after.is_empty() {
        Some(SeqMatch {
            indent: &line[..ind],
            sp: "",
            content: "",
        })
    } else {
        None
    }
}

/// `QUOTED_KEY_RE`: `^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*')[ \t]*:`, returning the
/// length of group 1 — the quoted key including its own quotes.
///
/// Kept as one pattern in the oracle so the key's quotes are part of `key_text`
/// and survive an edit to its value; `quoted_key` in `rich.md` is quoted for a
/// reason and un-quoting it is one of the three things that file exists to
/// catch.
///
/// **No backtracking is needed, and that is a property of the pattern rather
/// than an assumption.** A greedy star over `[^']|''` consumes `''` pairs and
/// stops at the first unpaired `'`, which is the only position the closing quote
/// can take: reaching a later one would mean crossing an unpaired quote, which
/// neither alternative matches. The loop below walks to that same position
/// directly. The double-quoted branch is the same argument with `\\.` in place
/// of `''`.
fn quoted_key(text: &str) -> Option<usize> {
    let b = text.as_bytes();
    let q = *b.first()?;
    if q != b'"' && q != b'\'' {
        return None;
    }
    let mut i = 1usize;
    let end = loop {
        if i >= b.len() {
            return None;
        }
        let c = b[i];
        if q == b'"' && c == b'\\' {
            // `\\.` — one character, and `.` cannot match a newline, but a line
            // holds none. A trailing backslash matches neither alternative and
            // leaves the key unterminated.
            if i + 1 >= b.len() {
                return None;
            }
            i += 2;
            continue;
        }
        if c == q {
            if q == b'\'' && b.get(i + 1) == Some(&b'\'') {
                i += 2;
                continue;
            }
            break i + 1;
        }
        i += 1;
    };
    let mut j = end;
    while j < b.len() && (b[j] == b' ' || b[j] == b'\t') {
        j += 1;
    }
    if b.get(j) == Some(&b':') {
        Some(end)
    } else {
        None
    }
}

/// `BLOCK_RE`: `^[|>][+-]?\d*$|^[|>]\d*[+-]?$`, a block scalar header.
fn is_block_header(v: &str) -> bool {
    let b = v.as_bytes();
    if b.is_empty() || (b[0] != b'|' && b[0] != b'>') {
        return false;
    }
    let rest = &b[1..];
    // `[+-]? \d* $`
    let chomp_first = {
        let r = match rest.first() {
            Some(&c) if c == b'+' || c == b'-' => &rest[1..],
            _ => rest,
        };
        r.iter().all(u8::is_ascii_digit)
    };
    // `\d* [+-]? $`
    let digits_first = {
        let k = rest.iter().take_while(|c| c.is_ascii_digit()).count();
        let r = &rest[k..];
        r.is_empty() || (r.len() == 1 && (r[0] == b'+' || r[0] == b'-'))
    };
    chomp_first || digits_first
}

/// `INDEX_RE`: `^(.*?)\[(\d+)\]$`, peeling one bracket index off the right.
///
/// The non-greedy prefix and the `$` anchor together mean the `[` is the last
/// one whose contents run to the final `]` as digits — no earlier `[` can work,
/// since the span from it would have to contain that `[`, which is not a digit.
/// So the rightmost `[` is the only candidate.
fn peel_index(seg: &str) -> Option<(&str, &str)> {
    let inner = seg.strip_suffix(']')?;
    let open = inner.rfind('[')?;
    let digits = &inner[open + 1..];
    if digits.is_empty() || !digits.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some((&seg[..open], digits))
}

// --------------------------------------------------------------------------
// line splitting
// --------------------------------------------------------------------------

/// `rest` after the colon -> `(gap, value, pad, comment)`.
///
/// A `#` is a comment only at the start or after whitespace, and only outside
/// quotes. `quoted_key: "value: with a colon"` has neither, but a naive
/// `split('#')` would cut `folded: > # ...` styles and any value containing a
/// URL fragment, and the damage would be silent — the comment would be
/// re-emitted as part of the value.
///
/// Scanned over bytes where the oracle scans characters. Equivalent: every byte
/// it tests for is ASCII, and UTF-8 continuation bytes are all ≥ 0x80, so a
/// multi-byte character can neither match one nor be mistaken for the space or
/// tab that licenses a `#`. Every index used to slice lands on a `#`, or on a
/// whitespace boundary, so all of them are character boundaries.
fn split_comment(rest: &str) -> (&str, &str, &str, &str) {
    let b = rest.as_bytes();
    let mut i = 0usize;
    let mut q = 0u8;
    let mut cut = None;
    while i < b.len() {
        let ch = b[i];
        if q != 0 {
            if ch == b'\\' && q == b'"' {
                i += 2;
                continue;
            }
            if ch == q {
                q = 0;
            }
        } else if ch == b'"' || ch == b'\'' {
            q = ch;
        } else if ch == b'#' && (i == 0 || b[i - 1] == b' ' || b[i - 1] == b'\t') {
            cut = Some(i);
            break;
        }
        i += 1;
    }
    let (head, comment) = match cut {
        None => (rest, ""),
        Some(c) => (&rest[..c], &rest[c..]),
    };
    let stripped = head.trim_start_matches([' ', '\t']);
    let gap = &head[..head.len() - stripped.len()];
    let value = stripped.trim_end_matches([' ', '\t']);
    let pad = &stripped[value.len()..];
    (gap, value, pad, comment)
}

/// Post-prefix text -> `(key_text, rest)`, or `None` if this is not a key line.
///
/// A bare key ends at the first colon that is followed by a space or the end of
/// the line. That is YAML's own rule, and it is what keeps
/// `quoted_key: "value: with a colon"` a single key rather than two.
fn split_key(text: &str) -> Option<(&str, &str)> {
    if let Some(klen) = quoted_key(text) {
        // The oracle takes `text.index(":", len(group1))`, which is the colon
        // the pattern already proved is there past the optional blanks.
        let colon = klen + text[klen..].find(':')?;
        return Some((&text[..klen], &text[colon + 1..]));
    }
    if text.is_empty() || text.starts_with('#') {
        return None;
    }
    let b = text.as_bytes();
    let mut i = text.find(':');
    while let Some(p) = i {
        if p + 1 == b.len() || b[p + 1] == b' ' || b[p + 1] == b'\t' {
            let key = &text[..p];
            // A key cannot span a `#`; if one is in the way this is a comment
            // line with a colon in it, not a mapping.
            return if key.contains('#') {
                None
            } else {
                Some((key, &text[p + 1..]))
            };
        }
        i = text[p + 1..].find(':').map(|k| k + p + 1);
    }
    None
}

/// The key's identity for addressing, with YAML's two quotings removed.
fn unquote(key_text: &str) -> String {
    let b = key_text.as_bytes();
    if b.len() >= 2 && b[0] == b'"' && b[b.len() - 1] == b'"' {
        return key_text[1..key_text.len() - 1]
            .replace("\\\"", "\"")
            .replace("\\\\", "\\");
    }
    if b.len() >= 2 && b[0] == b'\'' && b[b.len() - 1] == b'\'' {
        return key_text[1..key_text.len() - 1].replace("''", "'");
    }
    key_text.to_string()
}

// --------------------------------------------------------------------------
// extent
// --------------------------------------------------------------------------

/// Spaces-only indent width, the measure every comparison here uses.
fn indent_of(line: &str) -> usize {
    line.len() - line.trim_start_matches(' ').len()
}

fn is_blank(line: &str) -> bool {
    py_strip(line).is_empty()
}

/// Last line of the block owned by a key at `indent`, starting after `i`.
///
/// Blank lines inside are absorbed; blank lines trailing the block are not, so
/// a delete never eats the separator before the next key.
fn block_end(lines: &[&str], hi: usize, i: usize, indent: usize) -> usize {
    let (mut j, mut last) = (i + 1, i);
    while j <= hi {
        let raw = lines[j];
        if is_blank(raw) {
            j += 1;
            continue;
        }
        if indent_of(raw) <= indent {
            break;
        }
        last = j;
        j += 1;
    }
    last
}

/// Last line of a sequence written at its *own key's* indent, or `i`.
///
/// `tags:\n- a\n- b` is valid YAML and is what most static site generators emit,
/// but the items are not indented past the key, so [`block_end`] stops at the
/// first one and the key reads as null. Left that way the items parse as a
/// second, top-level sequence — and `frontmatter-delete tags` then removes the
/// `tags:` line and leaves them behind, which is the family's worst available
/// failure: a success that produces a document nothing can read.
///
/// A key at this indent followed by a dash at the same indent can only be that
/// key's sequence; a mapping cannot have a bare `-` sibling. Deeper lines belong
/// to whichever item is open.
fn seq_at(lines: &[&str], hi: usize, i: usize, indent: usize) -> usize {
    let (mut j, mut last) = (i + 1, i);
    while j <= hi {
        let raw = lines[j];
        if is_blank(raw) {
            j += 1;
            continue;
        }
        let ind = indent_of(raw);
        if ind < indent || (ind == indent && match_seq(raw).is_none()) {
            break;
        }
        last = j;
        j += 1;
    }
    last
}

// --------------------------------------------------------------------------
// the recursive descent
// --------------------------------------------------------------------------

/// Entries at `indent`, between `lo` and `hi` inclusive, into `out`.
fn parse(
    lines: &[&str],
    lo: usize,
    hi: usize,
    indent: usize,
    prefix_path: &[Seg],
    out: &mut Vec<Entry>,
) {
    let (mut i, mut seq_n) = (lo, 0usize);
    while i <= hi {
        let raw = lines[i];
        if is_blank(raw) || raw.trim_start_matches(' ').starts_with('#') {
            i += 1;
            continue;
        }
        let ind = indent_of(raw);
        if ind < indent {
            break;
        }
        if ind > indent {
            // Deeper than anything at this level: owned by a key already taken,
            // or malformed. Either way not ours to describe.
            i += 1;
            continue;
        }

        if let Some(m) = match_seq(raw) {
            let (mi, msp, mc) = (
                m.indent.to_string(),
                m.sp.to_string(),
                m.content.to_string(),
            );
            i = parse_item(lines, hi, i, &mi, &msp, &mc, prefix_path, seq_n, out);
            seq_n += 1;
            continue;
        }

        let Some((key_text, rest)) = split_key(&raw[ind..]) else {
            i += 1;
            continue;
        };
        let (key_text, rest) = (key_text.to_string(), rest.to_string());
        let mut path = prefix_path.to_vec();
        path.push(Seg::Key(unquote(&key_text)));
        i = parse_key(lines, hi, i, &raw[..ind], &key_text, &rest, path, out);
    }
}

/// One `key:` line and whatever it owns. Returns the next line to read.
#[allow(clippy::too_many_arguments)]
fn parse_key(
    lines: &[&str],
    hi: usize,
    i: usize,
    prefix: &str,
    key_text: &str,
    rest: &str,
    path: Vec<Seg>,
    out: &mut Vec<Entry>,
) -> usize {
    let (gap, value, pad, comment) = split_comment(rest);
    let mut end = block_end(lines, hi, i, prefix.len());
    if end == i && value.is_empty() {
        end = seq_at(lines, hi, i, prefix.len());
    }
    let kind = if is_block_header(value) {
        Kind::Block
    } else if end > i {
        let first = lines[i + 1..=end]
            .iter()
            .find(|l| !is_blank(l))
            .copied()
            .unwrap_or("");
        if match_seq(first).is_some() {
            Kind::Seq
        } else {
            Kind::Map
        }
    } else if value.is_empty() {
        Kind::Null
    } else {
        Kind::Scalar
    };

    out.push(Entry {
        path: path.clone(),
        line: i,
        end,
        prefix: prefix.to_string(),
        key_text: key_text.to_string(),
        gap: gap.to_string(),
        value: value.to_string(),
        pad: pad.to_string(),
        comment: comment.to_string(),
        kind,
        eol: String::new(),
    });
    if kind == Kind::Map || kind == Kind::Seq {
        let child_indent = lines[i + 1..=end]
            .iter()
            .filter(|l| !is_blank(l))
            .map(|l| indent_of(l))
            .min()
            .unwrap_or(0);
        parse(lines, i + 1, end, child_indent, &path, out);
    }
    end + 1
}

/// One `- ...` sequence item. Returns the next line to read.
///
/// A map item's first key is physically on the dash line, so the key's prefix is
/// `indent + "- "` and its siblings align to that column. Recording the prefix
/// verbatim is what lets `frontmatter-set authors[0].name` rewrite that line
/// without having to know it is the first key of anything.
#[allow(clippy::too_many_arguments)]
fn parse_item(
    lines: &[&str],
    hi: usize,
    i: usize,
    ind: &str,
    sp: &str,
    content: &str,
    prefix_path: &[Seg],
    n: usize,
    out: &mut Vec<Entry>,
) -> usize {
    let mut path = prefix_path.to_vec();
    path.push(Seg::Index(n.to_string()));
    let end = block_end(lines, hi, i, ind.len());
    let split = if content.is_empty() {
        None
    } else {
        split_key(content)
    };
    let prefix = format!("{ind}-{sp}");

    // A scalar item's trailing comment is split off, so setting its value keeps
    // it; a *map* item's is left in `content` on purpose, because the key on
    // that same line owns it and splitting here would give it two owners and
    // write it twice.
    let (value, pad, comment) = match split {
        None => {
            let (_, v, p, c) = split_comment(content);
            (v.to_string(), p.to_string(), c.to_string())
        }
        Some(_) => (content.to_string(), String::new(), String::new()),
    };
    out.push(Entry {
        path: path.clone(),
        line: i,
        end,
        prefix: prefix.clone(),
        key_text: String::new(),
        gap: String::new(),
        value,
        pad,
        comment,
        kind: Kind::Item,
        eol: String::new(),
    });

    if let Some((key_text, rest)) = split {
        let (key_text, rest) = (key_text.to_string(), rest.to_string());
        let mut kpath = path.clone();
        kpath.push(Seg::Key(unquote(&key_text)));
        parse_key(lines, end, i, &prefix, &key_text, &rest, kpath, out);
        // Siblings of that first key sit one line down, at its own column.
        parse(lines, i + 1, end, prefix.len(), &path, out);
    }
    end + 1
}

// --------------------------------------------------------------------------
// entry points
// --------------------------------------------------------------------------

/// The block, its format, and every addressable entry in it.
///
/// The span comes from [`crate::scan::frontmatter_span`] rather than from a
/// second scanner here, because that one is what the list and section parsers
/// skip over: two answers to "where is the frontmatter" is how an op comes to
/// edit lines the other family thinks are body. It accepts `+++` as a span,
/// which is correct for skipping and wrong for editing, so the *format* is read
/// back off the delimiter here and the ops refuse on it.
///
/// Parsing runs over a copy with `\r` stripped, so every scanner here is written
/// once, against the line ending the file does not have. Each entry is then told
/// what its own line ended with, which is what [`Entry::rebuilt`] puts back.
pub fn find_frontmatter(content: &str) -> FrontMatter {
    let raw: Vec<&str> = content.split('\n').collect();
    let lines: Vec<&str> = raw
        .iter()
        .map(|ln| ln.strip_suffix('\r').unwrap_or(ln))
        .collect();
    let Some((start, end)) = frontmatter_span(&lines) else {
        return FrontMatter {
            present: false,
            fmt: None,
            start: 0,
            end: 0,
            delim: String::new(),
            close: String::new(),
            entries: Vec::new(),
            eol: String::new(),
        };
    };
    let delim = py_strip(lines[start]).to_string();
    let fmt = if delim == "---" { Fmt::Yaml } else { Fmt::Toml };
    let mut entries = Vec::new();
    if fmt == Fmt::Yaml && end > start + 1 {
        parse(&lines, start + 1, end - 1, 0, &[], &mut entries);
    }
    for e in &mut entries {
        e.eol = if raw[e.line].ends_with('\r') {
            "\r"
        } else {
            ""
        }
        .to_string();
    }
    FrontMatter {
        present: true,
        fmt: Some(fmt),
        start,
        end,
        delim,
        close: py_strip(lines[end]).to_string(),
        entries,
        eol: if raw[start].ends_with('\r') { "\r" } else { "" }.to_string(),
    }
}

/// `"authors[0].role"` -> `["authors", 0, "role"]`, or `None` if unreadable.
///
/// Returns `None` rather than raising: the refusal belongs in the ops layer,
/// where it can name the paths that do exist. An empty segment — `a..b`, `.a`,
/// `a.` — is unreadable rather than a key whose name is the empty string,
/// because no such key can be written in YAML without quotes.
pub fn parse_path(text: &str) -> Option<Vec<Seg>> {
    if text.is_empty() {
        return None;
    }
    let mut out = Vec::new();
    for seg in text.split('.') {
        // `a[0][1]` peels right to left, so the indices come off reversed and go
        // back on in document order once the name is known.
        let mut seg = seg;
        let mut idx = Vec::new();
        while let Some((head, digits)) = peel_index(seg) {
            seg = head;
            idx.push(digits);
        }
        if seg.is_empty() && idx.is_empty() {
            return None;
        }
        if !seg.is_empty() {
            out.push(Seg::Key(seg.to_string()));
        }
        for d in idx.into_iter().rev() {
            // `int("007")` is `7` and prints as `7`; canonical digits are what
            // make that true here. `\d+` admits no sign, so stripping zeros
            // down to a last one is the whole of it.
            let canon = d.trim_start_matches('0');
            out.push(Seg::Index(if canon.is_empty() {
                "0".to_string()
            } else {
                canon.to_string()
            }));
        }
    }
    Some(out)
}

/// The inverse of [`parse_path`], for refusal messages and summaries.
pub fn format_path(path: &[Seg]) -> String {
    let mut out = String::new();
    for seg in path {
        match seg {
            Seg::Index(n) => {
                out.push('[');
                out.push_str(n);
                out.push(']');
            }
            Seg::Key(k) => {
                if !out.is_empty() {
                    out.push('.');
                }
                out.push_str(k);
            }
        }
    }
    out
}
