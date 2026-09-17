//! Runtime validation of tool arguments, ported from `bench/incise_ops.py`.
//!
//! REQUIREMENTS.md §11: *"every argument is validated at runtime, because the
//! schema's `required` and type constraints do not bind the model's output."*
//! B6 measured the second half of that — deleting a `oneOf` union from a
//! property changed the model's output in 0 of 60 trials — so the schema is a
//! suggestion and this module is the enforcement.
//!
//! The rule is the one `unstring` establishes: **parse what parses, refuse the
//! rest.** A coercion that cannot be wrong is performed — `"0"` is an integer,
//! `"End"` is `end`, a string containing a JSON object is that object — and
//! anything needing a guess is refused, naming the field and the shape wanted.
//! A default is not a guess only when the argument is *absent*: `position`
//! missing means `end`, `position` present and unreadable means stop.
//!
//! Every message here is byte-identical to the oracle's, for the reason every
//! message in this crate is (§5.3), with one addition specific to this module:
//! the `Got:` lines quote the offending value back with Python's `repr`, so
//! `json::py_repr` is doing contract work here and not just diagnostics.
//!
//! How this module is covered. `bench/difftest.py` generates its arguments from
//! the document — the address from `list_tables`, the column from the header
//! row — so every generated call is well-typed by construction and none of this
//! code is on that path. That is how the oracle itself went three op families
//! with an argument layer nobody had looked at (FINDINGS F-args). The gap is
//! closed by two hand-written case families, `check_args` and `py_repr`, which
//! are a cross product rather than a list: 40 JSON values against 14 functions.
//! They earned their keep on the first run, finding three divergences this
//! module's own unit tests had asserted away — CPython's `Infinity`, Python's
//! unbounded integers, and `list.insert`'s clamping. `bench/mutate.py` carries
//! nine mutations aimed here to keep those cases honest.

use crate::error::{OpError, Result};
use crate::json::{self, Value};

/// Which shapes `unstring` will accept out of a JSON-in-a-string argument.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Expect {
    Object,
    ObjectOrArray,
}

impl Expect {
    /// The English the refusal uses. `" or "`-joined in declaration order,
    /// matching Python's iteration over the `expect` tuple.
    fn want(self) -> &'static str {
        match self {
            Expect::Object => "an object",
            Expect::ObjectOrArray => "an object or an array",
        }
    }

    fn accepts(self, v: &Value) -> bool {
        match self {
            Expect::Object => matches!(v, Value::Object(_)),
            Expect::ObjectOrArray => matches!(v, Value::Object(_) | Value::Array(_)),
        }
    }
}

/// Recover a structured argument the model serialized into a string.
///
/// Measured: the model sometimes sends `"{\"Component\": \"gadget\"}"` where an
/// object belongs, and `"i, j, k, l"` where an array belongs. The first parses
/// as JSON to exactly the intended value, so parsing it recovers the call with
/// nothing guessed. The second is not JSON, and splitting on commas would be
/// guessing at cell boundaries — the class of error §6.2 exists to refuse.
///
/// `plain_ok` is for `table`, where a bare string is a legitimate shape (the
/// heading shorthand) rather than a mistake.
///
/// Without this the failure surfaced as `no column "{"`, an error about the
/// consequence rather than the cause.
pub fn unstring(
    value: Option<&Value>,
    expect: Expect,
    field: &str,
    plain_ok: bool,
) -> Result<Option<Value>> {
    let v = match value {
        None => return Ok(None),
        Some(v) => v,
    };
    let s = match v {
        Value::Str(s) => s,
        other => return Ok(Some(other.clone())),
    };
    if let Some(parsed) = json::parse(s) {
        if expect.accepts(&parsed) {
            return Ok(Some(parsed));
        }
    }
    if plain_ok {
        return Ok(Some(v.clone()));
    }
    let want = expect.want();
    Err(OpError::new(format!(
        "`{field}` arrived as a string, but must be {want}.\n  Got: {}\n  Send {want} directly, not a string containing one.",
        json::py_repr_str(s)
    )))
}

/// Strip stray literal quotes from object keys.
///
/// Measured once: `{"\"heading\"": "..."}`. The key is unambiguous once the
/// quotes come off, and dropping the field instead would produce a confusing
/// "address required" error for a call that supplied the address.
pub fn clean_keys(value: Option<Value>) -> Option<Value> {
    match value {
        Some(Value::Object(pairs)) => Some(Value::Object(
            pairs
                .into_iter()
                .map(|(k, v)| {
                    let bytes = k.as_bytes();
                    if bytes.len() > 1 && bytes[0] == b'"' && bytes[bytes.len() - 1] == b'"' {
                        (k[1..k.len() - 1].to_string(), v)
                    } else {
                        (k, v)
                    }
                })
                .collect(),
        )),
        other => other,
    }
}

/// An address is an object, a bare heading string, or absent.
pub fn check_address(value: Option<Value>, field: &str) -> Result<Option<Value>> {
    match &value {
        None | Some(Value::Null) | Some(Value::Str(_)) | Some(Value::Object(_)) => Ok(value),
        Some(v) => Err(OpError::new(format!(
            "`{field}` must be an object or a heading string, but arrived as {}.\n  Got: {}\n  Send {{\"heading\": \"...\"}}, or the heading on its own.",
            v.type_name(),
            json::py_repr(v)
        ))),
    }
}

pub fn check_heading(value: Option<&Value>, field: &str) -> Result<Option<String>> {
    check_heading_named(value, &format!("{field}.heading"))
}

/// The same check, told the whole key to quote.
///
/// The section family reaches its address through either `section.path` or
/// `section.heading` and picks between them by truthiness, so it is the one
/// caller that cannot let the label be derived from the family name: a refusal
/// naming `section.heading` when the caller sent `section.path` describes a key
/// that is not in the call.
pub fn check_heading_named(value: Option<&Value>, label: &str) -> Result<Option<String>> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Str(s)) => Ok(Some(s.clone())),
        Some(v) => Err(OpError::new(format!(
            "`{label}` must be a string, but arrived as {}.\n  Got: {}\n  Send the heading text, or the heading path joined with \" > \".",
            v.type_name(),
            json::py_repr(v)
        ))),
    }
}

/// A Python integer, which has no width.
///
/// `i64` would be the obvious choice and is wrong for a reason `difftest` found
/// rather than a reason anyone predicted: the oracle accepts
/// `ordinal: 12345678901234567890123456789` and quotes the digits back in
/// `no table with ordinal 12345678901234567890123456789`, so the value has to
/// survive as far as the message. `Big` therefore keeps the digits verbatim —
/// no arithmetic is ever done on one, because an ordinal that large cannot
/// match a table and an index that large cannot be inside a list.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PyInt {
    Small(i64),
    Big(String),
}

impl PyInt {
    /// Whether this is the given ordinal.
    ///
    /// A `Big` never is: an ordinal counts things in one document, so a value
    /// outside `i64` cannot name one. It still has to compare rather than
    /// panic, because the digits survive this far precisely so the refusal can
    /// quote them back.
    pub fn eq_usize(&self, n: usize) -> bool {
        match self {
            PyInt::Small(i) => *i == n as i64,
            PyInt::Big(_) => false,
        }
    }

    /// Python's `repr` of the integer, which is its decimal digits.
    pub fn repr(&self) -> String {
        match self {
            PyInt::Small(n) => n.to_string(),
            PyInt::Big(s) => s.clone(),
        }
    }

    /// The index `list.insert` would use, given a list of `len` items.
    ///
    /// Python clamps at both ends and counts negatives from the right, and a
    /// value too large for `i64` clamps by definition — which is why `Big`
    /// needs only its sign here.
    pub fn insert_index(&self, len: usize) -> usize {
        match self {
            PyInt::Big(s) => {
                if s.starts_with('-') {
                    0
                } else {
                    len
                }
            }
            PyInt::Small(n) => {
                let n = *n;
                if n < 0 {
                    let from_end = len as i64 + n;
                    if from_end < 0 {
                        0
                    } else {
                        from_end as usize
                    }
                } else if (n as u64) > len as u64 {
                    len
                } else {
                    n as usize
                }
            }
        }
    }

    /// `i64` if it fits, `None` if it does not — for comparisons against real
    /// ordinals, where "does not fit" and "does not match" are the same answer.
    pub fn small(&self) -> Option<i64> {
        match self {
            PyInt::Small(n) => Some(*n),
            PyInt::Big(_) => None,
        }
    }
}

/// `int(s)` for a string Python would accept, in canonical `repr` form.
///
/// Python's `int()` strips whitespace, allows one leading sign, and allows
/// underscores *between* digits (`int("1_0") == 10`). It also accepts non-ASCII
/// decimal digits — `int("١٢") == 12` — which this does not; matching that
/// would mean shipping a Unicode numeric table in a crate that has no
/// dependencies, to serve an ordinal no model will ever send. The gap is
/// recorded rather than hidden, and it is the only known divergence in this
/// module.
pub fn py_int_from_str(s: &str) -> Option<PyInt> {
    let t = s.trim();
    let (neg, rest) = match t.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, t.strip_prefix('+').unwrap_or(t)),
    };
    if rest.is_empty() || !rest.is_ascii() {
        return None;
    }
    let mut digits = String::new();
    let bytes = rest.as_bytes();
    for (i, c) in bytes.iter().enumerate() {
        if c.is_ascii_digit() {
            digits.push(*c as char);
        } else if *c == b'_' {
            // Underscores must sit between digits: not leading, not trailing,
            // not doubled. `int("_1")`, `int("1_")` and `int("1__0")` all raise.
            let prev_ok = i > 0 && bytes[i - 1].is_ascii_digit();
            let next_ok = bytes.get(i + 1).is_some_and(u8::is_ascii_digit);
            if !prev_ok || !next_ok {
                return None;
            }
        } else {
            return None;
        }
    }
    // `repr` has no leading zeros and no `-0`.
    let trimmed = digits.trim_start_matches('0');
    let canon = if trimmed.is_empty() { "0" } else { trimmed };
    let signed = if neg && canon != "0" {
        format!("-{canon}")
    } else {
        canon.to_string()
    };
    Some(match signed.parse::<i64>() {
        Ok(n) => PyInt::Small(n),
        Err(_) => PyInt::Big(signed),
    })
}

/// The integer a JSON value already *is*, if it is one.
fn py_int_from_value(v: &Value) -> Option<PyInt> {
    match v {
        Value::Int(n) => Some(PyInt::Small(*n)),
        Value::BigInt(s) => Some(PyInt::Big(s.clone())),
        _ => None,
    }
}

/// `0` and `"0"` are the same number; `0.5` and `true` are not ordinals.
///
/// A string that is exactly an integer is parsed rather than refused, for the
/// reason `unstring` parses a serialized object: nothing is guessed, and the
/// alternative message ("no table with ordinal 0" when ordinal 0 exists) is an
/// error about the consequence rather than the cause.
pub fn check_ordinal(value: Option<&Value>, field: &str) -> Result<Option<PyInt>> {
    match value {
        None | Some(Value::Null) => return Ok(None),
        Some(Value::Str(s)) => {
            if let Some(n) = py_int_from_str(s) {
                return Ok(Some(n));
            }
        }
        Some(v) => {
            if let Some(n) = py_int_from_value(v) {
                return Ok(Some(n));
            }
        }
    }
    let v = value.unwrap();
    Err(OpError::new(format!(
        "`{field}.ordinal` must be a whole number, but arrived as {}.\n  Got: {}\n  Ordinals count {field}s under the same heading, starting at 0.",
        v.type_name(),
        json::py_repr(v)
    )))
}

/// Where a new row goes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Position {
    Start,
    End,
    Index(PyInt),
}

/// Which family is asking.
///
/// The two place a new thing differently, so one check cannot use one sentence.
/// A table row has a position in a grid and an index means something there; a
/// list item is placed by the item it follows, and `after` is how that is said.
/// Sharing the *parsing* is the point of section 6.4's "one habit" — `"Start"`
/// must mean start in both families, which it did not. Sharing the *prose*
/// would mean telling a model about rows in a list.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PosFamily {
    Table,
    List,
}

impl PosFamily {
    /// What the field may hold, as the refusal's first line says it.
    fn accepts(self) -> &'static str {
        match self {
            PosFamily::Table => "\"start\", \"end\", or a row index",
            PosFamily::List => "\"start\" or \"end\"",
        }
    }

    /// The repair line. Empty for the boolean branch, which has none in either
    /// family -- the value is not near-miss enough for advice to be useful.
    fn repair(self) -> &'static str {
        match self {
            PosFamily::Table => "\n  Use \"start\" for the first row, \"end\" for the last, or a 0-based index to insert before an existing row.",
            PosFamily::List => "\n  Send \"start\" for the first item, \"end\" for the last, or `after` with the text of the item to put the new one below.",
        }
    }
}

/// `start`, `end`, or an index. Absent means `end`; unreadable means stop.
///
/// The measured failure this prevents: every unrecognized value — `"middle"`,
/// `1.5`, `[1]`, and `"0"` — was silently appended at the end and reported as
/// success. `"0"` is the worst of them, because a model that sends the index as
/// a string gets the opposite of what it asked for and is told it worked.
pub fn check_position(value: Option<&Value>) -> Result<Position> {
    check_position_in(value, PosFamily::Table)
}

/// The same check, for the family that has no indices.
///
/// `list_add_item` compared `position` against the literal `"start"` and
/// appended on everything else, so `"Start"` and `0` both meant *start* on a
/// table and *end* on a list — silently, reported as success. That is the same
/// shape of defect B6 measured for `values` and F-pipes for cells: the wrong
/// thing done, and called done. Sharing the parser closes it.
///
/// An index parses and is then refused rather than coerced, because a list has
/// no row numbers to count and guessing which of "top-level items" or "every
/// item" was meant is exactly the invention section 6.4 forbids.
pub fn check_position_in(value: Option<&Value>, fam: PosFamily) -> Result<Position> {
    let refuse_index = |v: &Value| -> Result<Position> {
        Err(OpError::new(format!(
            "`position` must be {}, but arrived as an index.\n  Got: {}\n  A list item is placed by the item it follows, not by number.{}",
            fam.accepts(),
            json::py_repr(v),
            fam.repair()
        )))
    };
    match value {
        None | Some(Value::Null) => return Ok(Position::End),
        // Python reaches the boolean branch first on purpose: `isinstance(True,
        // int)` is True there, so a bare `true` would otherwise be read as
        // index 1. Rust's types make that impossible, but the arm stays in the
        // same place so the two files read the same way.
        Some(Value::Bool(_)) => {
            let v = value.unwrap();
            return Err(OpError::new(format!(
                "`position` must be {}, but arrived as a boolean.\n  Got: {}",
                fam.accepts(),
                json::py_repr(v)
            )));
        }
        Some(Value::Str(s)) => {
            let low = s.trim().to_lowercase();
            if low == "start" {
                return Ok(Position::Start);
            }
            if low == "end" {
                return Ok(Position::End);
            }
            if let Some(n) = py_int_from_str(&low) {
                if fam == PosFamily::List {
                    return refuse_index(value.unwrap());
                }
                return Ok(Position::Index(n));
            }
        }
        Some(v) => {
            if let Some(n) = py_int_from_value(v) {
                if fam == PosFamily::List {
                    return refuse_index(v);
                }
                return Ok(Position::Index(n));
            }
        }
    }
    let v = value.unwrap();
    Err(OpError::new(format!(
        "`position` must be {}, but arrived as {}.\n  Got: {}{}",
        fam.accepts(),
        v.type_name(),
        json::py_repr(v),
        fam.repair()
    )))
}

/// A cell holds one value. Nested structures are refused, not stringified.
///
/// Measured: `{"Component": {"a": 1}}` wrote `{'a': 1}` into the table — a
/// Python repr, in the document, reported as success. The same coercion in a
/// `where` selector was merely useless rather than destructive, producing
/// `no row where Component="{'a': 1}"`, but it explains the consequence instead
/// of the cause, which is the thing §5.3 is about.
///
/// The success path is `str(value)`, so a number reaches the cell as Python
/// would print it — which is why `json::py_repr` distinguishes `Int` from
/// `Float`, and why `1.0` writes `1.0` rather than `1`.
pub fn check_cell(value: &Value, column: &str, field: &str) -> Result<String> {
    match value {
        Value::Object(_) | Value::Array(_) => Err(OpError::new(format!(
            "the value for \"{column}\" in `{field}` must be text, but arrived as {}.\n  Got: {}\n  A table cell holds a single value; flatten it first.",
            value.type_name(),
            json::py_repr(value)
        ))),
        Value::Null => Err(OpError::new(format!(
            "the value for \"{column}\" in `{field}` is null.\n  Send \"\" for an empty cell, or omit the column entirely."
        ))),
        Value::Bool(_) => Err(OpError::new(format!(
            "the value for \"{column}\" in `{field}` arrived as a boolean.\n  Got: {}\n  Send the text you want in the cell, e.g. \"true\" or \"yes\".",
            json::py_repr(value)
        ))),
        // `str()`, not `repr()`: a string keeps its own characters and a number
        // prints unquoted. For every non-string scalar the two agree anyway.
        Value::Str(s) => check_cell_text(s.clone(), column, field),
        other => check_cell_text(json::py_repr(other), column, field),
    }
}

/// A cell is one line between two pipes. Text that breaks either of those two
/// facts does not make a bad cell, it makes a different table, and both were
/// measured writing silent corruption and reporting success:
///
/// ```text
/// {"A": "x | y"}         ->  | x | y | z |   a three-column row in a
///                                            two-column table
/// {"A": "has\nnewline"}  ->  | has           the table ends at the break;
///                            newline | z |   the rest is a new table with
///                                            no header
/// ```
///
/// Neither can be repaired by quoting, because a cell holds *source markdown*
/// here — `**bold**` in a cell is bold, and `\|` is the escape the corpus
/// fixture already uses. So the refusal names the escape to write rather than
/// applying it: escaping on the model's behalf would make the stored text differ
/// from the text it sent, and `where` matches the stored text.
fn check_cell_text(text: String, column: &str, field: &str) -> Result<String> {
    if text.contains('\n') || text.contains('\r') {
        return Err(OpError::new(format!(
            "the value for \"{column}\" in `{field}` contains a line break, and a table cell is a single line.\n  Got: {}\n  Use `<br>` where the break should go, or send one line.",
            json::py_repr(&Value::Str(text))
        )));
    }
    if has_bare_pipe(&text) {
        return Err(OpError::new(format!(
            "the value for \"{column}\" in `{field}` contains a `|`, which would start a new column.\n  Got: {}\n  Write `\\|` for a literal pipe.",
            json::py_repr(&Value::Str(text))
        )));
    }
    Ok(text)
}

/// True if `text` holds a `|` that is not escaped.
///
/// The same scan as `table::raw_cells`, and for the same reason: `\|` is content
/// and `\\|` is a literal backslash followed by a separator, and only consuming
/// the escape pair tells them apart.
fn has_bare_pipe(text: &str) -> bool {
    let mut it = text.chars();
    while let Some(c) = it.next() {
        if c == '\\' {
            it.next();
        } else if c == '|' {
            return true;
        }
    }
    false
}

/// `where` is an object mapping column name to the value to match.
///
/// A list of column names reached `.items()` and raised `AttributeError`; a
/// number reached `for c in where` and raised `TypeError`. Both are the model
/// sending the right idea in the wrong shape, which is a refusal.
pub fn check_where(value: Option<Value>) -> Result<Option<Value>> {
    match &value {
        None | Some(Value::Null) | Some(Value::Object(_)) => Ok(value),
        Some(v) => Err(OpError::new(format!(
            "`where` must be an object mapping column names to values, but arrived as {}.\n  Got: {}\n  Send {{\"Column\": \"value\"}} naming enough columns to identify one row.",
            v.type_name(),
            json::py_repr(v)
        ))),
    }
}

/// `filter` is an object mapping column name to the value to match.
///
/// Same shapes and the same refusal as [`check_where`], because the model's
/// mistakes do not know which op it is calling. The difference between the two
/// is what happens when the object is *valid* and matches nothing: `where` is
/// selecting a row to rewrite, so zero matches and many matches are both
/// refusals; `filter` is reading, so both are ordinary answers. That difference
/// is why the argument is not called `where` — S15 found that reusing one word
/// for a strict and a lenient meaning is how a model learns the wrong rule.
///
/// Borrows rather than owns, unlike `check_where`: the caller iterates the pairs
/// immediately, and cloning the argument object would buy nothing.
pub fn check_filter(value: Option<&Value>) -> Result<Option<&Vec<(String, Value)>>> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Object(pairs)) => Ok(Some(pairs)),
        Some(v) => Err(OpError::new(format!(
            "`filter` must be an object mapping column names to values, but arrived as {}.\n  Got: {}\n  Send {{\"Column\": \"value\"}}, or omit it to get every row.",
            v.type_name(),
            json::py_repr(v)
        ))),
    }
}

/// The text a cell becomes.
///
/// Measured (FINDINGS F-args), and the worst of that family because it is the
/// op's entire purpose: `table-update-cell` with no `value` wrote the literal
/// string `None` into the cell and reported success. A nested object wrote
/// `{'a': 1}`, a boolean wrote `True`. `str(value)` accepts anything, which is
/// how a required field came to have a silent default.
///
/// Python needs a sentinel to tell an absent field from an explicit null, since
/// `a.get("value")` collapses both to `None`. `Option<&Value>` keeps them apart
/// for free, and they get different messages: one says the field is required,
/// the other says how to write an empty cell.
pub fn check_value(value: Option<&Value>, column: &str) -> Result<String> {
    match value {
        None => Err(OpError::new(
            "`value` is required: it is the text the cell becomes.\n  Send \"\" to empty the cell.",
        )),
        Some(v) => check_cell(v, column, "value"),
    }
}

pub fn check_column(value: Option<&Value>) -> Result<String> {
    if let Some(Value::Str(s)) = value {
        // `str.strip()` is Python's whitespace set; `trim` is Unicode's. They
        // differ only on characters no header contains, and this branch only
        // asks whether anything is left.
        if !s.trim().is_empty() {
            return Ok(s.clone());
        }
    }
    match value {
        None | Some(Value::Null) => Err(OpError::new(
            "`column` is required: it names the column whose cell changes.\n  Send the column's header text.",
        )),
        Some(v) => Err(OpError::new(format!(
            "`column` must be a string, but arrived as {}.\n  Got: {}\n  Send the column's header text.",
            v.type_name(),
            json::py_repr(v)
        ))),
    }
}

// --------------------------------------------------------------------------
// argument extraction
// --------------------------------------------------------------------------
// Python builds these inside the `OPS` dispatch table as lambda arguments,
// which means *all of them run before the op does*: `_unstring` refusals
// therefore precede `resolve_table`, and the order among them is the order they
// appear in the lambda. Rust has no such rule, so the ordering has to be written
// down rather than emerging from the language, and here it is.
//
// When the op is `table-add-row`, the oracle refuses in this order, and the
// first refusal wins:
//
//   1. `address(args)`      — table unstrung, de-quoted, shape-checked
//   2. `values(args, "values")`
//   3. `values(args, "row")` — the legacy alias; `position` is NOT checked here
//   4. resolve_table        — `table.heading`, `table.ordinal`, then lookup
//   5. the table's columns
//   6. `values` and `row` both supplied — this compares the two rows, so it
//      runs `check_cell` over both and a bad cell can surface at 6 not 8
//   7. `values` empty
//   8. each cell, left to right
//   9. `check_position`
//
// Steps 1–3 are the lambda's arguments and 4–9 are the body, which is why a
// malformed `values` outranks a nonexistent table while a malformed `position`
// does not. Nothing here derives that order; it was read off the Python.
//
// Reading it was not enough. `bench/difftest.py`'s `check_args` family asserts
// steps 1–3 and 9 in isolation and the generated cases reach 4–8 with well-typed
// arguments, but neither can see the *sequence* — so the `apply_op` family runs
// whole dispatch calls with real argument objects, and caught three places where
// `ops/dispatch.rs` had this list in front of it and still did something else.
// Note especially that `table.heading` and `table.ordinal` are checked at step 4
// and not at step 1: the address extraction only unstrings, de-quotes the keys,
// and checks the outer shape.
//
// `table-update-cell` is `address`, `where_arg`, then resolve_table, columns,
// `check_column`, the column-exists check, `resolve_row` — which re-checks
// `where`'s shape, requires it non-empty, and checks each selector value as a
// cell — and last `check_value`, so a bad value on a row that does not exist
// reports the row. `table-delete-row` is the same without the column steps or
// the value.

/// `table`, unstrung, de-quoted, and type-checked.
pub fn address(args: &Value) -> Result<Option<Value>> {
    check_address(
        clean_keys(unstring(args.get("table"), Expect::Object, "table", true)?),
        "table",
    )
}

/// `list`, for the list family. Symmetrical with [`address`] in every respect,
/// including that the two *fields* are left for `resolve_list` to check — which
/// it now does, so the two families refuse a malformed `heading` or `ordinal` at
/// the same point in the sequence.
pub fn list_address(args: &Value) -> Result<Option<Value>> {
    check_address(
        clean_keys(unstring(args.get("list"), Expect::Object, "list", true)?),
        "list",
    )
}

/// `section`, for the section family. Same caveat as [`list_address`].
pub fn section_address(args: &Value) -> Result<Option<Value>> {
    check_address(
        clean_keys(unstring(
            args.get("section"),
            Expect::Object,
            "section",
            true,
        )?),
        "section",
    )
}

pub fn where_arg(args: &Value) -> Result<Option<Value>> {
    check_where(clean_keys(unstring(
        args.get("where"),
        Expect::Object,
        "where",
        false,
    )?))
}

/// `values` (or `row`) — an ordered array or a named object, one untyped
/// argument (§6.2). The named-only shape measured 3/10 on positionally-phrased
/// instructions; accepting both took silent corruption to 0/60 (B6).
pub fn values(args: &Value, field: &str) -> Result<Option<Value>> {
    Ok(clean_keys(unstring(
        args.get(field),
        Expect::ObjectOrArray,
        field,
        false,
    )?))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &str) -> Value {
        Value::Str(v.to_string())
    }

    #[test]
    fn a_serialized_object_is_recovered_and_a_prose_list_is_not() {
        let got = unstring(
            Some(&s(r#"{"Component": "gadget"}"#)),
            Expect::Object,
            "where",
            false,
        );
        assert_eq!(
            got.unwrap(),
            Some(Value::Object(vec![("Component".into(), s("gadget"))]))
        );

        let err = unstring(
            Some(&s("i, j, k, l")),
            Expect::ObjectOrArray,
            "values",
            false,
        )
        .unwrap_err();
        assert_eq!(
            err.message(),
            "`values` arrived as a string, but must be an object or an array.\n  \
             Got: 'i, j, k, l'\n  \
             Send an object or an array directly, not a string containing one."
        );
    }

    #[test]
    fn a_bare_heading_survives_plain_ok_and_is_refused_without_it() {
        let got = unstring(Some(&s("Components")), Expect::Object, "table", true);
        assert_eq!(got.unwrap(), Some(s("Components")));

        let err = unstring(Some(&s("Components")), Expect::Object, "where", false).unwrap_err();
        assert!(err
            .message()
            .starts_with("`where` arrived as a string, but must be an object."));
    }

    #[test]
    fn quoted_keys_are_unquoted() {
        let v = Value::Object(vec![("\"heading\"".into(), s("H"))]);
        assert_eq!(
            clean_keys(Some(v)),
            Some(Value::Object(vec![("heading".into(), s("H"))]))
        );
    }

    #[test]
    fn a_string_index_is_an_index_and_middle_is_a_refusal() {
        // The whole point of F-args: `"0"` used to append at the end and report
        // success. It now means what it says.
        assert_eq!(
            check_position(Some(&s("0"))).unwrap(),
            Position::Index(PyInt::Small(0))
        );
        assert_eq!(check_position(Some(&s(" End "))).unwrap(), Position::End);
        assert_eq!(check_position(None).unwrap(), Position::End);
        assert_eq!(check_position(Some(&Value::Null)).unwrap(), Position::End);

        let err = check_position(Some(&s("middle"))).unwrap_err();
        assert_eq!(
            err.message(),
            "`position` must be \"start\", \"end\", or a row index, but arrived as a string.\n  \
             Got: 'middle'\n  \
             Use \"start\" for the first row, \"end\" for the last, or a 0-based index to insert before an existing row."
        );

        // `true` is not index 1, which is what Python would have done without
        // the boolean arm placed ahead of the integer one.
        let err = check_position(Some(&Value::Bool(true))).unwrap_err();
        assert_eq!(
            err.message(),
            "`position` must be \"start\", \"end\", or a row index, but arrived as a boolean.\n  Got: True"
        );

        let err = check_position(Some(&Value::Float(1.5))).unwrap_err();
        assert!(err.message().contains("arrived as a number.\n  Got: 1.5"));
    }

    #[test]
    fn an_ordinal_string_parses_and_a_fraction_does_not() {
        assert_eq!(
            check_ordinal(Some(&s(" 2 ")), "table").unwrap(),
            Some(PyInt::Small(2))
        );
        assert_eq!(
            check_ordinal(Some(&Value::Int(0)), "table").unwrap(),
            Some(PyInt::Small(0))
        );
        assert_eq!(check_ordinal(None, "table").unwrap(), None);

        let err = check_ordinal(Some(&Value::Float(1.5)), "table").unwrap_err();
        assert_eq!(
            err.message(),
            "`table.ordinal` must be a whole number, but arrived as a number.\n  \
             Got: 1.5\n  \
             Ordinals count tables under the same heading, starting at 0."
        );
        // A boolean is not an ordinal, though Python's `isinstance(True, int)`
        // would have said otherwise had the check not named `bool` first.
        assert!(check_ordinal(Some(&Value::Bool(true)), "table").is_err());
        assert!(check_ordinal(Some(&s("1.0")), "table").is_err());
    }

    #[test]
    fn a_nested_cell_is_refused_rather_than_reprd_into_the_document() {
        let nested = Value::Object(vec![("a".into(), Value::Int(1))]);
        let err = check_cell(&nested, "Component", "values").unwrap_err();
        assert_eq!(
            err.message(),
            "the value for \"Component\" in `values` must be text, but arrived as an object.\n  \
             Got: {'a': 1}\n  \
             A table cell holds a single value; flatten it first."
        );

        let err = check_cell(&Value::Null, "Component", "where").unwrap_err();
        assert_eq!(
            err.message(),
            "the value for \"Component\" in `where` is null.\n  \
             Send \"\" for an empty cell, or omit the column entirely."
        );

        // Numbers pass, and print as Python prints them — `1` and `1.0` are
        // different cells.
        assert_eq!(check_cell(&Value::Int(1), "C", "values").unwrap(), "1");
        assert_eq!(
            check_cell(&Value::Float(1.0), "C", "values").unwrap(),
            "1.0"
        );
        assert_eq!(check_cell(&s("plain"), "C", "values").unwrap(), "plain");
    }

    #[test]
    fn a_list_of_column_names_is_the_right_idea_in_the_wrong_shape() {
        let v = Value::Array(vec![s("Component")]);
        let err = check_where(Some(v)).unwrap_err();
        assert_eq!(
            err.message(),
            "`where` must be an object mapping column names to values, but arrived as an array.\n  \
             Got: ['Component']\n  \
             Send {\"Column\": \"value\"} naming enough columns to identify one row."
        );
        assert!(check_where(Some(Value::Int(5))).is_err());
        assert!(check_where(None).is_ok());
    }

    #[test]
    fn a_missing_column_says_what_to_send_rather_than_what_broke() {
        // The pre-F-args behaviour was "TypeError: 'NoneType' object is not
        // iterable", which describes the executor's stack.
        let err = check_column(None).unwrap_err();
        assert_eq!(
            err.message(),
            "`column` is required: it names the column whose cell changes.\n  \
             Send the column's header text."
        );
        assert!(check_column(Some(&s("   "))).is_err());
        assert_eq!(check_column(Some(&s("Status"))).unwrap(), "Status");
    }

    #[test]
    fn a_number_where_an_address_belongs_is_refused_not_crashed() {
        let args = Value::Object(vec![("table".into(), Value::Int(5))]);
        let err = address(&args).unwrap_err();
        assert_eq!(
            err.message(),
            "`table` must be an object or a heading string, but arrived as a number.\n  \
             Got: 5\n  \
             Send {\"heading\": \"...\"}, or the heading on its own."
        );
    }
}
