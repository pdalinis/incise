//! Tier 1 table operations — the three measured failures (REQUIREMENTS.md §11).
//!
//! `table-add-row` was 4/10 aligned and **0/10** when a re-pad was forced;
//! `table-update-cell` read 10/10 only because the test value was narrower than
//! its column; `table-delete-row` could not be expressed at all 6/10 of the
//! time. Everything here exists because of one of those three numbers.
//!
//! The rendering rules are §5.2's, and the one that looks cosmetic is not:
//! **widen when necessary, never shrink.** `corpus/tables/aligned.md` pads
//! `Owner` to 9 where its content needs 7 — an author's choice. Normalizing to
//! minimum width would rewrite all three existing rows just to append a short
//! one, and shrink a whole table to delete one row from it. With the rule, a
//! short add touches only the added line and a delete touches only the removed
//! line.

use std::collections::HashMap;

use crate::args::{
    check_cell, check_column, check_filter, check_heading, check_ordinal, check_position,
    check_value,
};
use crate::error::{OpError, Result};
use crate::heading::find_sections;
use crate::json;
use crate::scan::py_strip;
use crate::similar::get_close_matches;
use crate::table::{find_tables, split_row, Table};

const MARKER_NONE: u8 = 0;
const MARKER_LEFT: u8 = 1;
const MARKER_RIGHT: u8 = 2;
const MARKER_CENTER: u8 = 3;

// --------------------------------------------------------------------------
// structure
// --------------------------------------------------------------------------

/// Heading path enclosing a table, outermost-first.
pub fn heading_path(content: &str, table: &Table) -> Vec<String> {
    heading_path_at(content, table.start)
}

/// Heading path enclosing the line at `start`, outermost-first.
///
/// Split out because the list family needs the same answer for a span that is
/// not a table. The oracle's version takes anything with a `.start`, and
/// `incise_ops._Span` exists there for exactly this call; a line index says the
/// same thing without the stand-in.
pub fn heading_path_at(content: &str, start: usize) -> Vec<String> {
    let mut stack: Vec<(usize, String)> = Vec::new();
    for sec in find_sections(content) {
        if sec.start > start {
            break;
        }
        while stack.last().is_some_and(|(l, _)| *l >= sec.level) {
            stack.pop();
        }
        stack.push((sec.level, sec.text));
    }
    stack.into_iter().map(|(_, t)| t).collect()
}

/// The label introducing a table, or `""`.
///
/// Heading path plus columns does not disambiguate
/// `corpus/tables/multiple-per-section.md`, where three tables under one
/// heading share identical columns and differ only by the line above them.
///
/// A caption must be the nearest non-blank line above the table *and* end in a
/// colon. The colon is not decoration: without it the rule returns the last line
/// of whatever paragraph precedes the table, which on `corpus/tables/ragged.md`
/// yields the mid-sentence fragment "treated as ragged and left alone." A wrong
/// label is worse than none — it costs prompt tokens and misdescribes the
/// table. Captions are only a disambiguation hint anyway, since addressing is by
/// heading and ordinal, so the conservative rule loses nothing.
pub fn caption(lines: &[&str], table: &Table) -> String {
    for i in (0..table.start).rev() {
        let s = lines[i].trim();
        if s.is_empty() {
            continue;
        }
        if s.starts_with('#') || s.starts_with('|') || !s.ends_with(':') {
            return String::new();
        }
        return s[..s.len() - 1].trim().to_string();
    }
    String::new()
}

/// One entry of the compact structural summary a model sees instead of the
/// document.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TableEntry {
    /// Per heading path, matching how a model would count them.
    pub ordinal: usize,
    pub heading: String,
    pub caption: String,
    pub columns: Vec<String>,
    pub rows: usize,
}

pub fn list_tables(content: &str) -> Vec<TableEntry> {
    let lines: Vec<&str> = content.split('\n').collect();
    let mut out: Vec<TableEntry> = find_tables(content)
        .iter()
        .map(|t| {
            let path = heading_path(content, t);
            TableEntry {
                ordinal: 0,
                heading: if path.is_empty() {
                    "(document root)".to_string()
                } else {
                    path.join(" > ")
                },
                caption: caption(&lines, t),
                columns: t.columns(),
                rows: t.body().len(),
            }
        })
        .collect();
    let mut seen: HashMap<String, usize> = HashMap::new();
    for e in out.iter_mut() {
        let n = seen.entry(e.heading.clone()).or_insert(0);
        e.ordinal = *n;
        *n += 1;
    }
    out
}

/// The model-readable form of [`list_tables`] — the Arm B prompt context.
///
/// Not optional infrastructure (§11 Tier 2): this string *is* the prompt, so
/// §1.2's numbers measure the ops and this summary together.
pub fn render_table_list(content: &str, path: &str) -> String {
    let mut lines = vec![format!("Tables in `{path}`:")];
    for e in list_tables(content) {
        let cap = if e.caption.is_empty() {
            String::new()
        } else {
            format!("  labelled \"{}\"", e.caption)
        };
        lines.push(format!(
            "  heading \"{}\"  ordinal {}{}\n    columns: {}   ({} rows)",
            e.heading,
            e.ordinal,
            cap,
            e.columns.join(" | "),
            e.rows
        ));
    }
    lines.join("\n")
}

/// One table's rows, filtered. The result of [`table_get`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TableRows {
    pub heading: String,
    pub columns: Vec<String>,
    /// Positional, not keyed by column name — see [`table_get`].
    pub rows: Vec<Vec<String>>,
    pub matched: usize,
    pub total: usize,
}

/// Rows of one named table, optionally filtered. A read, not an edit.
///
/// Not an [`apply_op`](crate::apply_op) entry, deliberately (§6.1). Every op in
/// `OPS` takes a document and returns a document or a refusal; this returns text
/// *about* a document, which does not fit that contract, and adding it anyway
/// would change the "unknown operation" refusal — a sentence §1.2 measured.
///
/// `filter` is not `where`. On the write ops `where` must identify exactly one
/// row or refuse, because B2 measured the model inventing selector values and
/// silently editing the wrong row. On a read, zero or many matches is the normal
/// answer, so the leniency gets its own word rather than overloading a strict one
/// — the mistake S15 found in `path`.
///
/// Rows come back **positional**, not keyed by column name. A table may legally
/// repeat a header, and the oracle's `dict(zip(cols, row))` would then report the
/// last such cell's value under every one of its positions — a false statement
/// about the document, in the op whose whole job is to report the document.
pub fn table_get(
    content: &str,
    address: &TableAddress,
    filter: Option<&json::Value>,
) -> Result<TableRows> {
    let table = locate_table(content, address)?;
    check_rectangular(&table, true)?;
    let cols = table.columns();
    let supplied: Vec<(String, String)> = match check_filter(filter)? {
        None => Vec::new(),
        Some(pairs) => pairs
            .iter()
            .map(|(k, v)| check_cell(v, k, "filter").map(|c| (k.clone(), c)))
            .collect::<Result<_>>()?,
    };
    for (c, _) in &supplied {
        if !cols.contains(c) {
            let near = get_close_matches(c, &cols, 2, 0.4);
            return Err(OpError::new(format!(
                "no column \"{}\".\n  Near matches: {}\n  Columns: {}",
                c,
                if near.is_empty() {
                    "none".to_string()
                } else {
                    near.join(", ")
                },
                cols.join(" | ")
            )));
        }
        check_unambiguous(
            &cols,
            c,
            // The one call site with a performable remedy. FINDINGS, F-remedy.
            Some("Omit `filter` to read every row, and pick the one you want from the result."),
        )?;
    }
    let rows = table.rows();
    let total = rows.len();
    let kept: Vec<Vec<String>> = rows
        .into_iter()
        .filter(|r| {
            supplied
                .iter()
                .all(|(k, v)| cell_of(&cols, r, k) == v.as_str())
        })
        .collect();
    let path = heading_path(content, &table);
    Ok(TableRows {
        heading: if path.is_empty() {
            "(document root)".to_string()
        } else {
            path.join(" > ")
        },
        columns: cols,
        matched: kept.len(),
        total,
        rows: kept,
    })
}

/// The model-readable form of [`table_get`].
///
/// Single-space padding rather than aligned. Alignment is a display-width
/// question this tool cannot answer (§5.2, and the reason `table-realign`
/// refuses some tables), and a *result* has no author's formatting to preserve —
/// so the honest option is the one that never claims an alignment it cannot
/// verify.
///
/// Cells are emitted exactly as stored, escapes intact, because `split_row`
/// leaves them intact: a cell holding `a \| b` round-trips as `a \| b` and the
/// rendered table has the column count it claims.
pub fn render_table_get(
    content: &str,
    address: &TableAddress,
    filter: Option<&json::Value>,
) -> Result<String> {
    Ok(render_table_rows(&table_get(content, address, filter)?))
}

/// [`render_table_get`]'s second half, over rows already read.
///
/// Split out for one caller: the CLI's `rows --json` returns the structure *and*
/// the rendered string, and computing the read twice to get both would be the
/// only place in the project where one call runs the op two times.
///
/// The split is Rust-side only — the oracle's `render_table_get` is still one
/// function — and that is safe because it adds no behaviour to compare. Every
/// byte this returns reaches `render_table_get`, which `difftest.py` runs 2724
/// times against the oracle; a divergence introduced here fails there.
pub fn render_table_rows(got: &TableRows) -> String {
    let head = format!(
        "Table \"{}\" -- {} of {} row{}",
        got.heading,
        got.matched,
        got.total,
        if got.total == 1 { "" } else { "s" }
    );
    if got.rows.is_empty() {
        // A read that matched nothing still has to be actionable (§5.3): the
        // columns are the thing the caller got wrong, so name them.
        return format!(
            "{head}\n  No row matches.\n  Columns: {}",
            got.columns.join(" | ")
        );
    }
    let mut out = vec![
        head,
        format!("| {} |", got.columns.join(" | ")),
        format!(
            "| {} |",
            got.columns
                .iter()
                .map(|_| "---")
                .collect::<Vec<_>>()
                .join(" | ")
        ),
    ];
    for r in &got.rows {
        out.push(format!("| {} |", r.join(" | ")));
    }
    out.join("\n")
}

/// Refuse a column name this table's header uses more than once.
///
/// GFM permits two columns with the same name, and nothing can then say which
/// one `where`, `column`, `values` or `filter` meant. Three places in this
/// project answered that unanswerable question three different ways: the
/// oracle's `dict(zip(cols, row))` keeps the *last*, its `cols.index(name)`
/// finds the *first*, and this crate's `cell_of` also finds the first — so the
/// oracle matched a row against the last column and then wrote into the first,
/// while the port matched against the first. Both reported success, and the
/// differential suite could not see it because no corpus table repeats a header
/// (FINDINGS F-dupcol).
///
/// Refused, for the reason `check_rectangular` gives: this tool does not guess
/// which cell the caller meant. Scoped to *name* resolution, so the ops that
/// never map a name to a cell — `table-realign`, and an ordered `values` — still
/// work on such a table.
///
/// `remedy` replaces the last line, and `None` is the shipped sentence. F-remedy
/// measured that sentence at 0/10 recovery: it names a document edit no tool in
/// the set can make, and every one of the ten trials read it, believed it and
/// reported the question unanswerable. But there is no single performable remedy
/// here, because what the caller can do depends on which argument it sent —
/// omitting `filter` answers the question, and nothing addresses a repeated
/// column for `column`, where renaming really is the only way out. So the caller
/// passes the remedy it can honour, and `None` stays byte-identical to what was
/// measured. Only the `filter` site overrides it today; the other three are
/// reached 0 times in 2071 recorded trials, and rewriting a refusal nothing
/// draws is an unmeasured §5.3 change.
fn check_unambiguous(cols: &[String], name: &str, remedy: Option<&str>) -> Result<()> {
    let n = cols.iter().filter(|c| c.as_str() == name).count();
    if n > 1 {
        return Err(OpError::new(format!(
            "the column \"{name}\" appears {n} times in this table's header, so it does not identify one cell.\n  Columns: {}\n  {}",
            cols.join(" | "),
            remedy.unwrap_or("Rename one of them in the document, then retry.")
        )));
    }
    Ok(())
}

// --------------------------------------------------------------------------
// addressing
// --------------------------------------------------------------------------

/// Which table an op is about.
///
/// A bare heading string is accepted as shorthand for the same reason the
/// ordered row form is (§6.2): a nested object the model has to assemble is
/// friction, and the measured failure was the model omitting the address
/// altogether.
/// Both fields hold the **raw** JSON the caller sent, unchecked.
///
/// `check_heading` and `check_ordinal` are statements inside the oracle's
/// `resolve_table`, not part of extracting the address — `_address(a)` only
/// unstrings the value, strips quotes from its keys, and checks the outer
/// shape. Checking the fields here instead would put a bad `heading` ahead of a
/// malformed `values`, which is the wrong refusal. Found by the `apply_op`
/// differential cases, on the run that added arguments failing two checks at
/// once.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct TableAddress {
    pub heading: Option<json::Value>,
    pub ordinal: Option<json::Value>,
}

impl TableAddress {
    pub fn none() -> Self {
        Self::default()
    }

    pub fn heading(h: impl Into<String>) -> Self {
        TableAddress {
            heading: Some(json::Value::Str(h.into())),
            ordinal: None,
        }
    }

    pub fn with_ordinal(mut self, ordinal: i64) -> Self {
        self.ordinal = Some(json::Value::Int(ordinal));
        self
    }
}

impl From<&str> for TableAddress {
    fn from(h: &str) -> Self {
        TableAddress::heading(h)
    }
}

/// The table an address names, once it is safe to rewrite.
///
/// Split from `locate_table` so the rectangularity guard applies to every op
/// without being repeated at each of the four places a table is found.
pub fn resolve_table(content: &str, address: &TableAddress) -> Result<Table> {
    let table = locate_table(content, address)?;
    check_rectangular(&table, false)?;
    Ok(table)
}

/// Refuse a table whose rows disagree with its header on cell count.
///
/// `corpus/tables/cell-edge-cases.md` states the requirement in the document
/// itself: "GFM pads short rows and truncates long ones. incise must decide
/// explicitly: normalize to the header's column count, or fail loudly. It must
/// not silently drop the extra cell." This is the loud failure.
///
/// Without it, `table-update-cell` on a short row indexed past the end of the
/// row, and on a long row it wrote into a cell the header does not name and
/// re-emitted the row at its own width, changing the table's column count. Both
/// reported success.
///
/// Normalizing instead was rejected for the reason the fixture gives: padding a
/// short row invents a cell, truncating a long one destroys bytes GFM would have
/// hidden but not deleted. Neither is a formatting change, and this tool's only
/// reformatting operation is one the caller asks for by name.
///
/// `read = true` is [`table_get`], which refuses the same tables for a different
/// reason: it names cells by column, and a row that disagrees with the header has
/// no unambiguous mapping. Only the third line changes, because "will not
/// rewrite" is not true of a read and a message that misdescribes what the tool
/// was doing is what §5.3 exists to prevent.
fn check_rectangular(table: &Table, read: bool) -> Result<()> {
    let counts: Vec<usize> = table.lines.iter().map(|ln| split_row(ln).len()).collect();
    let want = counts[0];
    for (i, n) in counts.iter().enumerate() {
        if *n == want {
            continue;
        }
        let place = if i == 1 {
            "the delimiter row".to_string()
        } else {
            format!("row {}", i - 1)
        };
        let mut capped = place.clone();
        capped.replace_range(..1, &place[..1].to_uppercase());
        let cannot = if read {
            "incise will not report cells it cannot map to columns"
        } else {
            "incise will not rewrite a table it cannot read"
        };
        return Err(OpError::new(format!(
            "this table is not rectangular: the header has {want} columns but {place} has {n}.\n  {capped}: {}\n  {cannot} unambiguously.\n  A literal pipe inside a cell must be written `\\|`; otherwise add or remove a cell by hand, then retry.",
            py_strip(&table.lines[i])
        )));
    }
    Ok(())
}

/// Find the one table an address names, or fail with the candidates.
fn locate_table(content: &str, address: &TableAddress) -> Result<Table> {
    let tables = find_tables(content);
    let entries = list_tables(content);
    // Both up front, as the oracle does, so a malformed `ordinal` is refused
    // even when the heading it accompanies does not exist.
    let heading = check_heading(address.heading.as_ref(), "table")?;
    let ordinal = check_ordinal(address.ordinal.as_ref(), "table")?;

    let want_h = match &heading {
        Some(h) => h,
        None => {
            if tables.len() == 1 {
                return Ok(tables.into_iter().next().unwrap());
            }
            let cands: Vec<String> = entries
                .iter()
                .map(|e| format!("\"{}\" ordinal {}", e.heading, e.ordinal))
                .collect();
            return Err(OpError::new(format!(
                "table address required: this file has {} tables.\n  Candidates: {}",
                tables.len(),
                cands.join("; ")
            )));
        }
    };

    let norm = want_h.trim().to_lowercase();
    let matched: Vec<(&Table, &TableEntry)> = tables
        .iter()
        .zip(entries.iter())
        .filter(|(_, e)| {
            let lower = e.heading.to_lowercase();
            lower == norm || lower.rsplit(" > ").next().unwrap_or(&lower) == norm
        })
        .collect();

    if matched.is_empty() {
        let headings: Vec<String> = entries.iter().map(|e| e.heading.clone()).collect();
        let near = get_close_matches(want_h, &headings, 3, 0.4);
        let mut uniq: Vec<String> = headings.clone();
        uniq.sort();
        uniq.dedup();
        return Err(OpError::new(format!(
            "no table under heading \"{}\".\n  Near matches: {}\n  Headings with tables: {}",
            want_h,
            if near.is_empty() {
                "none".to_string()
            } else {
                near.join(", ")
            },
            uniq.join(", ")
        )));
    }

    let want_o = match &ordinal {
        Some(o) => o,
        None => {
            if matched.len() == 1 {
                return Ok(matched[0].0.clone());
            }
            let cands: Vec<String> = matched
                .iter()
                .map(|(_, e)| {
                    let cap = if e.caption.is_empty() {
                        String::new()
                    } else {
                        format!(" (\"{}\")", e.caption)
                    };
                    format!(
                        "ordinal {}{} columns {}",
                        e.ordinal,
                        cap,
                        e.columns.join(" | ")
                    )
                })
                .collect();
            return Err(OpError::new(format!(
                "ambiguous: {} tables under \"{}\". Pass an ordinal.\n  Candidates: {}",
                matched.len(),
                want_h,
                cands.join("; ")
            )));
        }
    };

    // `small()` is `None` for an ordinal too large for an `i64`, and an ordinal
    // that large cannot name a table -- so "does not fit" and "does not match"
    // are the same answer, and the digits still reach the message below.
    if let Some(want) = want_o.small() {
        for (t, e) in &matched {
            if e.ordinal as i64 == want {
                return Ok((*t).clone());
            }
        }
    }
    let valid: Vec<String> = matched.iter().map(|(_, e)| e.ordinal.to_string()).collect();
    Err(OpError::new(format!(
        "no table with ordinal {} under \"{}\".\n  Valid ordinals: {}",
        want_o.repr(),
        want_h,
        valid.join(", ")
    )))
}

/// A row selector: column name to required value, in the order supplied.
///
/// Ordered, not a map, because the order is visible in two error messages and
/// in the `json.dumps` suggestion inside one of them.
pub type Where = [(String, String)];

/// A selector as it arrives: values still `json::Value`, because the oracle
/// checks them as cells *inside* `resolve_row` -- after the empty check and
/// before the unknown-column check. Converting earlier reorders two refusals.
pub type WhereArg = [(String, json::Value)];

/// Index into `table.body()` for the single row matching `selector`.
pub fn resolve_row(table: &Table, raw: &WhereArg) -> Result<usize> {
    if raw.is_empty() {
        return Err(OpError::new(
            "a `where` selector is required to identify the row.",
        ));
    }
    let cols = table.columns();
    // Insertion order, matching the oracle's dict comprehension: the leftmost
    // unusable selector value is the one reported.
    let selector: Vec<(String, String)> = raw
        .iter()
        .map(|(k, v)| check_cell(v, k, "where").map(|c| (k.clone(), c)))
        .collect::<Result<_>>()?;
    let selector: &Where = &selector;
    for (c, _) in selector {
        if !cols.contains(c) {
            let near = get_close_matches(c, &cols, 2, 0.4);
            return Err(OpError::new(format!(
                "no column \"{}\".\n  Near matches: {}\n  Columns: {}",
                c,
                if near.is_empty() {
                    "none".to_string()
                } else {
                    near.join(", ")
                },
                cols.join(" | ")
            )));
        }
        check_unambiguous(&cols, c, None)?;
    }
    let rows = table.rows();
    let hits: Vec<usize> = rows
        .iter()
        .enumerate()
        .filter(|(_, row)| {
            selector
                .iter()
                .all(|(k, v)| cell_of(&cols, row, k) == v.as_str())
        })
        .map(|(i, _)| i)
        .collect();

    match hits.len() {
        0 => Err(OpError::new(no_row_message(table, &cols, selector))),
        1 => Ok(hits[0]),
        n => Err(OpError::new(format!(
            "{} rows match {}; the selector must identify exactly one.",
            n,
            json::py_dict_repr(selector)
        ))),
    }
}

/// `dict(zip(cols, row)).get(key, "")` — `zip` truncates, so a short row simply
/// has no value for the trailing columns.
fn cell_of<'a>(cols: &[String], row: &'a [String], key: &str) -> &'a str {
    cols.iter()
        .zip(row.iter())
        .find(|(c, _)| c.as_str() == key)
        .map(|(_, v)| v.as_str())
        .unwrap_or("")
}

/// Explain a failed row selector well enough for a model to fix it in one turn.
///
/// Arm B (FINDINGS.md B2) measured the failure this exists for: the model cannot
/// see the document, so it *invents* extra selector columns —
/// `{Component: "gadget", Owner: "unknown", Status: "active"}` against a row
/// that is actually retired/rowan. Refusing is right; the document is untouched
/// and the model gets a turn to retry.
///
/// The naive message reported only the first key, which picked the one key that
/// *did* match and said 'no row where Component="gadget" / near matches:
/// gadget'. That is worse than useless — it points at the correct part of the
/// selector. So when some keys match and others do not, name the conflict
/// precisely and say what to send instead.
fn no_row_message(table: &Table, cols: &[String], selector: &Where) -> String {
    let rows = table.rows();
    let sel = selector
        .iter()
        .map(|(k, v)| format!("{k}=\"{v}\""))
        .collect::<Vec<_>>()
        .join(", ");

    let matched_keys = |row: &[String]| -> Vec<String> {
        selector
            .iter()
            .filter(|(k, v)| cell_of(cols, row, k) == v.as_str())
            .map(|(k, _)| k.clone())
            .collect()
    };

    // Which row did the model most likely mean? Not "the first row matching any
    // key" — that picks whichever row happens to share a low-information value.
    // On the measured delete-row failure, `Status="active"` matched `widget`
    // before `Component="gadget"` matched the intended row, and the message then
    // advised sending `{"Status": "active"}`, which matches two rows.
    //
    // Score a match by how identifying it is: 1/(rows sharing that value). A
    // value unique to one row scores 1.0; one shared by two scores 0.5. So
    // "gadget" beats "active" and the message names the row the model meant.
    // The oracle's `selectivity(rec, k)` ignores `rec` — the score depends
    // only on how many rows share the value the selector asked for.
    let selectivity = |k: &str| -> f64 {
        let v = selector
            .iter()
            .find(|(key, _)| key == k)
            .map(|(_, v)| v.as_str())
            .unwrap_or("");
        let n = rows.iter().filter(|r| cell_of(cols, r, k) == v).count();
        if n == 0 {
            0.0
        } else {
            1.0 / n as f64
        }
    };

    let mut best: Option<(f64, usize)> = None;
    for (i, row) in rows.iter().enumerate() {
        let keys = matched_keys(row);
        if keys.is_empty() {
            continue;
        }
        let score: f64 = keys.iter().map(|k| selectivity(k)).sum();
        // `max()` keeps the first maximum; strict `>` reproduces that.
        if best.is_none_or(|(b, _)| score > b) {
            best = Some((score, i));
        }
    }

    if let (Some((_, i)), true) = (best, selector.len() > 1) {
        let row = &rows[i];
        let good = matched_keys(row);
        let conflicts = selector
            .iter()
            .filter(|(k, _)| !good.contains(k))
            .map(|(k, v)| {
                format!(
                    "you said {k}=\"{v}\" but it is \"{}\"",
                    cell_of(cols, row, k)
                )
            })
            .collect::<Vec<_>>()
            .join(", ");
        let subset: Vec<(String, String)> = selector
            .iter()
            .filter(|(k, _)| good.contains(k))
            .cloned()
            .collect();
        let unique = rows
            .iter()
            .filter(|r| {
                subset
                    .iter()
                    .all(|(k, v)| cell_of(cols, r, k) == v.as_str())
            })
            .count()
            == 1;
        let fix = if unique {
            format!(
                "  `where` only needs enough columns to identify one row. Send {}.",
                json::dumps_object(&subset)
            )
        } else {
            "  `where` must match one row exactly. Drop the columns you are not \
sure of, and keep enough to be unique."
                .to_string()
        };
        return format!(
            "no row matches all of {{{sel}}}.\n  Row {} matches on {}, but {}.\n{}",
            i + 1,
            good.join(", "),
            conflicts,
            fix
        );
    }

    let (col, val) = &selector[0];
    let vals: Vec<String> = rows
        .iter()
        .map(|r| cell_of(cols, r, col).to_string())
        .collect();
    let near = get_close_matches(val, &vals, 3, 0.4);
    format!(
        "no row where {}=\"{}\".\n  Near matches: {}\n  Values in {}: {}",
        col,
        val,
        if near.is_empty() {
            "none".to_string()
        } else {
            near.join(", ")
        },
        col,
        if vals.is_empty() {
            "(table is empty)".to_string()
        } else {
            vals.join(", ")
        }
    )
}

// --------------------------------------------------------------------------
// rendering — REQUIREMENTS.md §5.2
// --------------------------------------------------------------------------

fn marker_of(delim_cell: &str) -> u8 {
    let c = delim_cell.trim();
    match (c.starts_with(':'), c.ends_with(':')) {
        (true, true) => MARKER_CENTER,
        (true, false) => MARKER_LEFT,
        (false, true) => MARKER_RIGHT,
        _ => MARKER_NONE,
    }
}

/// One delimiter cell at `width` chars between pipes, markers intact.
fn delim_cell(marker: u8, width: usize) -> String {
    let inner = width.saturating_sub(2).max(3);
    let body = match marker {
        MARKER_CENTER => format!(":{}:", "-".repeat(inner.saturating_sub(2).max(1))),
        MARKER_LEFT => format!(":{}", "-".repeat(inner.saturating_sub(1).max(1))),
        MARKER_RIGHT => format!("{}:", "-".repeat(inner.saturating_sub(1).max(1))),
        _ => "-".repeat(inner),
    };
    format!(" {body} ")
}

/// Re-pad every line to uniform column width — the exception in §5.2, and the
/// whole point of the tool.
fn render_aligned(
    header: &[String],
    markers: &[u8],
    body: &[Vec<String>],
    existing: &[usize],
) -> Vec<String> {
    let ncols = header.len();
    // A cell that a short row does not have reads as empty rather than
    // panicking. Only reachable through a hand-built body, since an aligned
    // table's rows all have the same cell count by definition.
    fn at(row: &[String], i: usize) -> &str {
        row.get(i).map(|s| s.as_str()).unwrap_or("")
    }

    let widths: Vec<usize> = (0..ncols)
        .map(|i| {
            let need = body
                .iter()
                .map(|r| at(r, i).chars().count())
                .chain(std::iter::once(header[i].chars().count()))
                .max()
                .unwrap_or(0)
                + 2;
            need.max(existing.get(i).copied().unwrap_or(0)).max(5)
        })
        .collect();

    let row = |cells: &[String]| -> String {
        let mut s = String::from("|");
        for (i, width) in widths.iter().enumerate().take(ncols) {
            let c = at(cells, i);
            let pad = width - 2;
            let fill = pad.saturating_sub(c.chars().count());
            s.push(' ');
            s.push_str(c);
            s.push_str(&" ".repeat(fill));
            s.push_str(" |");
        }
        s
    };

    let mut out = vec![row(header)];
    let mut delim = String::from("|");
    for (i, width) in widths.iter().enumerate().take(ncols) {
        delim.push_str(&delim_cell(
            markers.get(i).copied().unwrap_or(MARKER_NONE),
            *width,
        ));
        delim.push('|');
    }
    out.push(delim);
    out.extend(body.iter().map(|r| row(r)));
    out
}

/// Single-space padding, for inserting into a ragged table (§5.2).
fn render_row_loose(cells: &[String]) -> String {
    format!("| {} |", cells.join(" | "))
}

/// The line ending the table's own lines use, or a refusal if they disagree.
///
/// Lines arrive from a split on `\n`, so a CRLF line still carries its `\r`.
/// Rebuilt lines are constructed fresh and would silently drop it, converting a
/// CRLF table to LF — caught by `corpus/hazards/crlf.md`.
///
/// Whole-file convention is deliberately not consulted: §5.2 says an edit
/// touches the target range only, and `corpus/hazards/mixed-endings.md` is a
/// file with no single convention to consult. Scoped to one table the question
/// is answerable where per-file is not.
fn table_eol(table: &Table) -> Result<&'static str> {
    let crlf = table.lines.iter().any(|ln| ln.ends_with('\r'));
    let lf = table.lines.iter().any(|ln| !ln.ends_with('\r'));
    if crlf && lf {
        return Err(OpError::new(
            "this table mixes CRLF and LF line endings, so there is no convention \
to match.\n  Normalize the table's line endings first, then retry.",
        ));
    }
    Ok(if crlf { "\r" } else { "" })
}

/// The leading whitespace shared by the table's lines, or a refusal.
///
/// A table inside a list item is indented (`corpus/hazards/nested-blocks.md`).
/// Rebuilt lines are constructed from cell values and carry no indentation, so
/// without this a table nested in a list is silently de-indented and falls out
/// of its list item — structural corruption of the worst kind. Caught by the
/// add-then-delete round trip, not by inspection.
fn table_indent(table: &Table) -> Result<String> {
    let mut indents: Vec<&str> = table
        .lines
        .iter()
        .map(|ln| &ln[..ln.len() - ln.trim_start().len()])
        .collect();
    indents.sort_unstable();
    indents.dedup();
    if indents.len() == 1 {
        return Ok(indents[0].to_string());
    }
    Err(OpError::new(
        "this table's lines are indented inconsistently, so there is no \
indentation to match.\n  Normalize the table's indentation first, then retry.",
    ))
}

/// Splice the table's lines back into the document, touching nothing else.
///
/// The invariant (FINDINGS.md F4): only lines `table.start..=table.end` are
/// replaced, so the blank line after the table is structurally untouchable —
/// three trials consumed it before the rule existed.
///
/// `realign` is the one caller allowed to reformat lines nobody named:
/// [`table_realign`], the sanctioned repair for the ratchet in REQUIREMENTS §5.2.
/// It differs from the ordinary aligned path in exactly two ways, both
/// deliberate. It renders aligned even when the table was found ragged — that is
/// the whole operation — and it passes no `existing` widths, so columns come
/// from content alone rather than inheriting a floor from whatever padding the
/// damaged table happened to carry.
fn rebuild(
    content: &str,
    table: &Table,
    header: &[String],
    body: &[Vec<String>],
    was_aligned: bool,
    realign: bool,
) -> Result<String> {
    let lines: Vec<&str> = content.split('\n').collect();
    let eol = table_eol(table)?;
    let indent = table_indent(table)?;
    let markers: Vec<u8> = split_row(table.delimiter())
        .iter()
        .map(|c| marker_of(c))
        .collect();

    let bare = |ln: &str| -> String {
        let no_cr = ln.strip_suffix('\r').unwrap_or(ln);
        no_cr[indent.len().min(no_cr.len())..].to_string()
    };

    let new_lines: Vec<String> = if realign {
        render_aligned(header, &markers, body, &[])
    } else if was_aligned && !table.has_tabs() {
        let existing = table.widths().into_iter().next().unwrap_or_default();
        render_aligned(header, &markers, body, &existing)
    } else {
        // Ragged: every line that survives keeps its exact bytes, and only
        // genuinely new rows are rendered. Keyed by cell content because that
        // is the only identity a row has once it has been through `rows()`.
        let mut existing: HashMap<Vec<String>, String> = HashMap::new();
        for ln in &table.lines {
            existing.insert(table.cells(ln), bare(ln));
        }
        let mut out = vec![existing
            .get(header)
            .cloned()
            .unwrap_or_else(|| render_row_loose(header))];
        out.push(bare(table.delimiter()));
        for r in body {
            out.push(
                existing
                    .get(r)
                    .cloned()
                    .unwrap_or_else(|| render_row_loose(r)),
            );
        }
        out
    };

    let mut kept: Vec<String> = lines[..table.start].iter().map(|s| s.to_string()).collect();
    kept.extend(new_lines.into_iter().map(|ln| format!("{indent}{ln}{eol}")));
    kept.extend(lines[table.end + 1..].iter().map(|s| s.to_string()));
    Ok(kept.join("\n"))
}

// --------------------------------------------------------------------------
// operations
// --------------------------------------------------------------------------

/// The two accepted row shapes (§6.2).
///
/// The named-only shape measured 3/10 on an instruction that supplied values
/// positionally — "add a row with the values i, j, k and l" — against 9/10 for
/// editing the document directly. The object shape imposed a
/// positional-to-named translation the model gets wrong.
/// Cells are `json::Value`, not `String`, because the *order* of the checks is
/// observable: the oracle refuses a wrong-length ordered row before it looks at
/// any cell, and an unknown column name before any cell. Converting to strings
/// at the boundary would put the cell refusal first and change which message a
/// model gets back — a §5.3 regression that no amount of correct output would
/// show.
#[derive(Debug, Clone, PartialEq)]
pub enum Values {
    /// Every column, in order. Strict about length.
    Ordered(Vec<json::Value>),
    /// Some columns, by name. Missing columns are empty.
    Named(Vec<(String, json::Value)>),
    /// Neither shape, and not something the extraction layer refuses.
    ///
    /// `args::values` only rejects a *string* that is not an encoded object or
    /// array; a bare `7` or `true` passes straight through and reaches the op,
    /// where it gets a refusal that names both shapes and the column count.
    /// Collapsing it to an empty row here would answer "a row is required" to a
    /// model that plainly supplied one, sending it to fix the wrong thing.
    ///
    /// Whether it is *empty* is Python truthiness, because that is the test the
    /// oracle applies (`if not supplied`) before it applies this one: `0`,
    /// `false` and `null` are a missing row, `7` is a misshapen one.
    Other(json::Value),
}

impl Values {
    /// Plain strings, for callers that already have text — tests and the
    /// differential-test harness, where the cells never came from a model.
    pub fn ordered<I: IntoIterator<Item = S>, S: Into<String>>(cells: I) -> Self {
        Values::Ordered(
            cells
                .into_iter()
                .map(|c| json::Value::Str(c.into()))
                .collect(),
        )
    }

    pub fn named<I: IntoIterator<Item = (K, V)>, K: Into<String>, V: Into<String>>(
        cells: I,
    ) -> Self {
        Values::Named(
            cells
                .into_iter()
                .map(|(k, v)| (k.into(), json::Value::Str(v.into())))
                .collect(),
        )
    }

    pub fn is_empty(&self) -> bool {
        match self {
            Values::Ordered(v) => v.is_empty(),
            Values::Named(kv) => kv.is_empty(),
            Values::Other(v) => !json::py_truthy(v),
        }
    }
}

/// Normalize either row shape into a cell list in column order.
fn values_to_row(cols: &[String], values: &Values) -> Result<Vec<String>> {
    match values {
        Values::Ordered(vs) => {
            // A short array is the one case where guessing would be
            // catastrophic: silently left- or right-padding puts every value in
            // the wrong column, and the result is a well-formed table that is
            // entirely wrong. Refuse and say the count.
            if vs.len() != cols.len() {
                return Err(OpError::new(format!(
                    "`values` is an array of {}, but the table has {} columns: {}.\n  \
Ordered rows must supply every column, in order. Use the named form to fill only some.",
                    vs.len(),
                    cols.len(),
                    cols.join(" | ")
                )));
            }
            // Left to right, so the leftmost bad cell is the one reported.
            vs.iter()
                .enumerate()
                .map(|(i, v)| check_cell(v, &cols[i], "values"))
                .collect()
        }
        Values::Other(_) => Err(OpError::new(format!(
            "`values` must be an object keyed by column name, or an ordered array of {} values.\n  Columns: {}",
            cols.len(),
            cols.join(" | ")
        ))),
        Values::Named(kv) => {
            if let Some((k, _)) = kv.iter().find(|(k, _)| !cols.contains(k)) {
                let near = get_close_matches(k, cols, 2, 0.4);
                return Err(OpError::new(format!(
                    "no column \"{}\".\n  Near matches: {}\n  Columns: {}",
                    k,
                    if near.is_empty() { "none".to_string() } else { near.join(", ") },
                    cols.join(" | ")
                )));
            }
            for (k, _) in kv.iter() {
                check_unambiguous(cols, k, None)?;
            }
            // An absent column is an empty cell -- that is the named form's
            // whole point. A column present with an unusable value is a
            // different thing, and `check_cell` refuses it rather than writing
            // a Python repr into the row. Column order, not insertion order,
            // because that decides which bad cell is reported first.
            cols.iter()
                .map(|c| match kv.iter().find(|(k, _)| k == c) {
                    Some((_, v)) => check_cell(v, c, "values"),
                    None => Ok(String::new()),
                })
                .collect()
        }
    }
}

/// Where a new row goes.
///
/// Re-exported from `args` rather than defined twice: the index it carries is a
/// `PyInt` with Python's clamping and negative-from-the-right semantics, and a
/// second `Position` here would drift from that the first time either changed.
pub use crate::args::Position;

/// Add a row.
///
/// The shipping schema exposes **one** row argument (§6.2); the two-parameter
/// variant was measured and rejected. The oracle still accepts a legacy `row`
/// alias so recorded trials stay regradable without re-spending GPU time — that
/// is a benchmark concern and deliberately absent here.
/// `position` arrives unvalidated on purpose. The oracle checks it *after* the
/// row's cells (see the ordering in `args`), so taking an already-checked
/// `Position` here would move `position: "middle"` ahead of a bad cell and
/// change which refusal a model gets. The check happens below, where it happens
/// there.
pub fn table_add_row(
    content: &str,
    address: &TableAddress,
    values: &Values,
    position: Option<&json::Value>,
) -> Result<String> {
    let table = resolve_table(content, address)?;
    let cols = table.columns();
    // An empty row is refused before the shape is checked, because "you sent
    // nothing" and "you sent the wrong number of things" are different repairs.
    //
    // The sentence names `values` and nothing else, in the schema's own words.
    // It used to offer `row` as an ordered array — an argument this crate
    // refuses on purpose (see the divergence note in `dispatch`) and the
    // shipping schema never declares, so the refusal recommended a repair that
    // could not work. No measured cost: of 480 recorded table calls, none ever
    // drew this refusal, and every `row`-as-array call came from `scheme_d`,
    // the only scheme that declares it. Fixed because a refusal must describe
    // the schema in force (§5.3), not on a number.
    if values.is_empty() {
        return Err(OpError::new(format!(
            "a row is required: `values`, either an object keyed by column name or an array of values in column order.\n  Columns: {}",
            cols.join(" | ")
        )));
    }
    let new = values_to_row(&cols, values)?;
    let mut body = table.rows();
    match check_position(position)? {
        Position::Start => body.insert(0, new),
        Position::End => body.push(new),
        // The oracle splices -- `body[:n] + [new] + body[n:]` -- which for a
        // list is `insert` with both ends clamped and negatives counted from
        // the right. `insert_index` is that rule; see `args::PyInt`.
        Position::Index(n) => {
            let i = n.insert_index(body.len());
            body.insert(i, new)
        }
    }
    let aligned = table.is_aligned();
    rebuild(content, &table, &cols, &body, aligned, false)
}

/// Overwrite one cell.
///
/// `column` and `value` both arrive raw, as `position` does in `table_add_row`
/// and for the same reason: the oracle checks it *after* the row resolves, so a bad value on a
/// row that does not exist reports the missing row. Taking a `&str` here would
/// silently accept whatever the caller had already stringified — which is
/// exactly the defect (`str(None)` → `"None"`) that `check_value` exists to
/// close.
pub fn table_update_cell(
    content: &str,
    address: &TableAddress,
    selector: &WhereArg,
    column: Option<&json::Value>,
    value: Option<&json::Value>,
) -> Result<String> {
    let table = resolve_table(content, address)?;
    let cols = table.columns();
    // Raw, and checked here rather than in the dispatch: the oracle's
    // `_check_column` is the op's first statement after the columns are read,
    // so a missing table outranks a missing `column`. Checking it at the
    // dispatch put it first instead, and the `apply_op` differential cases
    // caught that on the run that introduced them.
    let column = &check_column(column)?;
    let col_idx = match cols.iter().position(|c| c == column) {
        Some(i) => i,
        None => {
            let near = get_close_matches(column, &cols, 2, 0.4);
            return Err(OpError::new(format!(
                "no column \"{}\".\n  Near matches: {}\n  Columns: {}",
                column,
                if near.is_empty() {
                    "none".to_string()
                } else {
                    near.join(", ")
                },
                cols.join(" | ")
            )));
        }
    };
    check_unambiguous(&cols, column, None)?;
    let idx = resolve_row(&table, selector)?;
    // After the row resolves, not before: every recorded trial sent a usable
    // value, so this placement is the one that cannot move a graded call.
    let value = check_value(value, column)?;
    let mut body = table.rows();
    if body[idx].len() <= col_idx {
        body[idx].resize(col_idx + 1, String::new());
    }
    body[idx][col_idx] = value;
    let aligned = table.is_aligned();
    rebuild(content, &table, &cols, &body, aligned, false)
}

pub fn table_delete_row(
    content: &str,
    address: &TableAddress,
    selector: &WhereArg,
) -> Result<String> {
    let table = resolve_table(content, address)?;
    let cols = table.columns();
    let idx = resolve_row(&table, selector)?;
    let mut body = table.rows();
    body.remove(idx);
    let aligned = table.is_aligned();
    rebuild(content, &table, &cols, &body, aligned, false)
}

/// Re-pad one named table to uniform column width.
///
/// The only reformatting operation in the tool (REQUIREMENTS §6.2) and the
/// repair path for the ratchet in §5.2: alignment is detected from the table as
/// found, so one misalignment introduced by anything else flips that table to
/// ragged permanently, and every later incise edit then preserves the raggedness
/// faithfully because that is the rule. Nothing else can undo it.
///
/// It is safe only because it is *requested*. incise cannot tell a ragged table
/// the author wrote from one that was damaged, so it never infers this, never
/// applies it to a whole document, and takes an address like any other op.
///
/// Already aligned is a no-op, and `describe_change` reports it as one. That is
/// not just an optimization: re-rendering an aligned table would **shrink** it to
/// minimum width, and `corpus/tables/aligned.md` pads `Owner` to 9 where its
/// content needs 7. That padding is an author's choice, protected by §5.2
/// everywhere else; realign is a repair, not a normalizer, so it must not take
/// it away either.
///
/// A tab-padded table is not "already aligned" for this purpose. Its cells have
/// equal character counts, so [`Table::is_aligned`] says yes, but §5.2 counts a
/// table whose alignment cannot be verified as ragged — which is exactly the
/// state this op exists to repair, so it goes down the realign path.
///
/// A table holding characters that are not one display column wide is refused
/// outright; see `check_realignable`.
pub fn table_realign(content: &str, address: &TableAddress) -> Result<String> {
    let table = resolve_table(content, address)?;
    if table.is_aligned() && !table.has_tabs() {
        return Ok(content.to_string());
    }
    check_realignable(&table)?;
    let cols = table.columns();
    let body = table.rows();
    rebuild(content, &table, &cols, &body, true, true)
}

/// Refuse to re-pad a table whose width incise cannot measure.
///
/// Column width here is counted in **characters**, which is the only measure
/// that can be maintained arithmetically without a full Unicode width table (see
/// [`Table::widths`]). A terminal lays text out in **display columns**, and for
/// CJK, Hangul, kana, fullwidth forms and emoji the two disagree by a factor of
/// two.
///
/// `corpus/tables/cell-edge-cases.md` is the case. Its cells are padded to
/// display width, so by character count it reads ragged — and realigning it
/// re-pads to character count, producing a table that is aligned by incise's
/// measure and visibly *worse* on screen than what it replaced. Realign exists
/// to make a table look aligned; an output that looks less aligned than the
/// input is a failure of the operation on its own terms, not a trade-off.
///
/// So it is refused, and only here. Add, update and delete never reach the
/// aligned renderer on such a table — it reads ragged, so they take the loose
/// path and preserve every existing line byte-for-byte (§5.2). Only the reformat
/// is withheld, which is the reversible choice: a refusal can be relaxed later,
/// a mangled table has already been written.
fn check_realignable(table: &Table) -> Result<()> {
    let bad = table
        .lines
        .iter()
        .flat_map(|ln| ln.chars())
        .find(|c| not_one_column(*c));
    let Some(bad) = bad else { return Ok(()) };
    let cell = table
        .lines
        .iter()
        .flat_map(|ln| table.cells(ln))
        .find(|c| c.chars().any(not_one_column))
        .unwrap_or_default();
    Err(OpError::new(format!(
        "this table contains \"{bad}\", which does not occupy one display \
column, and incise counts column width in characters.\n  Re-padding it would \
produce a table that is aligned by that count and ragged on screen, which is \
the opposite of what realign is for.\n  First such cell: \"{cell}\"\n  Realign \
is refused. Add, update and delete still work on this table and leave its \
existing lines byte-for-byte intact."
    )))
}

/// East Asian Wide and Fullwidth, plus emoji: the characters a terminal prints
/// two columns wide. Zero-width combining marks and variation selectors are in
/// here for the same reason, from the other direction.
///
/// Deliberately a coarse over-approximation of `wcwidth`, and correct to be one.
/// The consequence of over-including is a refused realign on a table that would
/// have come out fine, with a message saying so; the consequence of missing a
/// character is a silently mis-padded table, which is the outcome the whole
/// guard exists to prevent. So the ranges are drawn wide and the list stays short
/// enough to carry without a data dependency.
///
/// It must stay narrow enough to be useful, though: an em dash is one column,
/// and `corpus/documents/project-readme.md` — whose "Feature status" table is
/// the most realistic ratchet-repair case in the corpus — has one in every row.
/// An earlier version of this test was "any non-ASCII", which refused it.
const WIDE_RANGES: [(u32, u32); 20] = [
    (0x0300, 0x036F),   // combining diacritical marks (zero width)
    (0x1100, 0x115F),   // Hangul Jamo, initial consonants
    (0x200B, 0x200F),   // zero-width space ..= RTL mark
    (0x2028, 0x202E),   // line/paragraph separators, bidi overrides
    (0x2060, 0x206F),   // word joiner, invisible operators
    (0x2E80, 0x303E),   // CJK radicals, Kangxi, CJK symbols and punctuation
    (0x3041, 0x33FF),   // kana, Bopomofo, Hangul compat, CJK compat
    (0x3400, 0x4DBF),   // CJK ext A
    (0x4E00, 0x9FFF),   // CJK unified ideographs
    (0xA000, 0xA4CF),   // Yi
    (0xAC00, 0xD7A3),   // Hangul syllables
    (0xF900, 0xFAFF),   // CJK compatibility ideographs
    (0xFE00, 0xFE0F),   // variation selectors (zero width)
    (0xFE10, 0xFE19),   // vertical forms
    (0xFE20, 0xFE2F),   // combining half marks (zero width)
    (0xFE30, 0xFE6F),   // CJK compatibility forms, small form variants
    (0xFF00, 0xFF60),   // fullwidth forms
    (0xFFE0, 0xFFE6),   // fullwidth signs
    (0x1F300, 0x1F9FF), // emoji, pictographs, supplemental symbols
    (0x20000, 0x3FFFD), // CJK ext B and beyond
];

/// True if `c` is not reliably one display column wide.
fn not_one_column(c: char) -> bool {
    let n = c as u32;
    WIDE_RANGES.iter().any(|(lo, hi)| *lo <= n && n <= *hi)
}
