//! A JSON value, a parser for it, and Python's `repr` of one.
//!
//! Three things the argument layer needs and the crate cannot get from a
//! dependency (§9 criterion 7):
//!
//! * **Parsing.** `_unstring` in the oracle calls `json.loads` on a string that
//!   arrived where an object belonged, because a model sometimes serializes its
//!   arguments twice. Whether that string parses decides whether the call is
//!   recovered or refused, so the parser is part of the contract, not plumbing.
//! * **Serializing.** One refusal is built with `json.dumps`.
//! * **`repr`.** Several refusals quote the offending value with `{value!r}`,
//!   which is Python's `repr` — including its float formatting, which is not
//!   Rust's. Those messages are compared byte-for-byte by `bench/difftest.py`.

use std::fmt::Write as _;

/// A parsed JSON value, shaped to preserve the distinctions Python preserves.
///
/// `Int` and `Float` are separate because `json.loads` produces `int` for `1`
/// and `float` for `1.0`, and their `repr`s differ (`1` vs `1.0`) — which shows
/// up directly in a refusal message. `BigInt` keeps the digits of an integer
/// too large for `i64`, since Python's integers have no width and truncating
/// one would misquote the value back to the model.
///
/// `Object` is a `Vec`, not a map: Python dictionaries preserve insertion order
/// and `repr` prints them in it.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    BigInt(String),
    Float(f64),
    Str(String),
    Array(Vec<Value>),
    Object(Vec<(String, Value)>),
}

impl Value {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_object(&self) -> Option<&[(String, Value)]> {
        match self {
            Value::Object(o) => Some(o),
            _ => None,
        }
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        self.as_object()?
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v)
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    /// The JSON name of this value's type, as the refusals word it.
    ///
    /// "a number" covers both `Int` and `Float`: the model wrote JSON, and JSON
    /// has one number type. Saying "an integer" would describe Python's reading
    /// of the value rather than what was sent.
    pub fn type_name(&self) -> &'static str {
        match self {
            Value::Null => "null",
            Value::Bool(_) => "a boolean",
            Value::Int(_) | Value::BigInt(_) | Value::Float(_) => "a number",
            Value::Str(_) => "a string",
            Value::Array(_) => "an array",
            Value::Object(_) => "an object",
        }
    }
}

// --------------------------------------------------------------------------
// parsing
// --------------------------------------------------------------------------

/// `json.loads`, returning `None` where Python raises `ValueError`.
///
/// Strict in the same places CPython is strict — no trailing commas, no single
/// quotes, no unquoted keys — because the whole point of the call is to decide
/// whether a string *is* JSON. A lenient parser here would accept calls the
/// oracle refuses, which is a divergence in behaviour, not in tolerance.
pub fn parse(s: &str) -> Option<Value> {
    let b = s.as_bytes();
    let mut i = 0;
    let v = parse_value(b, &mut i)?;
    skip_ws(b, &mut i);
    if i == b.len() {
        Some(v)
    } else {
        None
    }
}

fn skip_ws(b: &[u8], i: &mut usize) {
    while *i < b.len() && matches!(b[*i], b' ' | b'\t' | b'\n' | b'\r') {
        *i += 1;
    }
}

fn parse_value(b: &[u8], i: &mut usize) -> Option<Value> {
    skip_ws(b, i);
    match *b.get(*i)? {
        b'n' => lit(b, i, "null", Value::Null),
        b't' => lit(b, i, "true", Value::Bool(true)),
        b'f' => lit(b, i, "false", Value::Bool(false)),
        b'"' => parse_string(b, i).map(Value::Str),
        b'[' => parse_array(b, i),
        b'{' => parse_object(b, i),
        // Not JSON, but CPython's `json` accepts these three by default via
        // `parse_constant`, and it is CPython's acceptance this has to match --
        // `bench/difftest.py` found the divergence by feeding `Infinity` to
        // both sides. Case-sensitive and exactly these spellings: `nan` and
        // `inf` are ValueErrors there and must be here.
        b'N' => lit(b, i, "NaN", Value::Float(f64::NAN)),
        b'I' => lit(b, i, "Infinity", Value::Float(f64::INFINITY)),
        b'-' if b[*i..].starts_with(b"-Infinity") => {
            lit(b, i, "-Infinity", Value::Float(f64::NEG_INFINITY))
        }
        c if c == b'-' || c.is_ascii_digit() => parse_number(b, i),
        _ => None,
    }
}

fn lit(b: &[u8], i: &mut usize, word: &str, v: Value) -> Option<Value> {
    if b[*i..].starts_with(word.as_bytes()) {
        *i += word.len();
        Some(v)
    } else {
        None
    }
}

fn parse_array(b: &[u8], i: &mut usize) -> Option<Value> {
    *i += 1; // '['
    let mut out = Vec::new();
    skip_ws(b, i);
    if b.get(*i) == Some(&b']') {
        *i += 1;
        return Some(Value::Array(out));
    }
    loop {
        out.push(parse_value(b, i)?);
        skip_ws(b, i);
        match b.get(*i)? {
            b',' => *i += 1,
            b']' => {
                *i += 1;
                return Some(Value::Array(out));
            }
            _ => return None,
        }
    }
}

fn parse_object(b: &[u8], i: &mut usize) -> Option<Value> {
    *i += 1; // '{'
    let mut out: Vec<(String, Value)> = Vec::new();
    skip_ws(b, i);
    if b.get(*i) == Some(&b'}') {
        *i += 1;
        return Some(Value::Object(out));
    }
    loop {
        skip_ws(b, i);
        if b.get(*i)? != &b'"' {
            return None;
        }
        let k = parse_string(b, i)?;
        skip_ws(b, i);
        if b.get(*i)? != &b':' {
            return None;
        }
        *i += 1;
        let v = parse_value(b, i)?;
        // A repeated key keeps the last value at the original key's position —
        // `{"a": 1, "b": 2, "a": 3}` is `{'a': 3, 'b': 2}` in Python, not
        // `{'b': 2, 'a': 3}`. The order shows up in `repr`.
        match out.iter_mut().find(|(ek, _)| *ek == k) {
            Some(slot) => slot.1 = v,
            None => out.push((k, v)),
        }
        skip_ws(b, i);
        match b.get(*i)? {
            b',' => *i += 1,
            b'}' => {
                *i += 1;
                return Some(Value::Object(out));
            }
            _ => return None,
        }
    }
}

fn parse_string(b: &[u8], i: &mut usize) -> Option<String> {
    *i += 1; // '"'
    let mut out = String::new();
    // Escaped surrogate halves are combined here rather than rejected, because
    // that is what CPython's decoder does.
    let mut pending_high: Option<u16> = None;
    loop {
        let c = *b.get(*i)?;
        if c == b'"' {
            *i += 1;
            if pending_high.is_some() {
                out.push('\u{fffd}');
            }
            return Some(out);
        }
        if c == b'\\' {
            *i += 1;
            let e = *b.get(*i)?;
            *i += 1;
            if e == b'u' {
                let unit = hex4(b, i)?;
                match pending_high.take() {
                    Some(hi) if (0xdc00..0xe000).contains(&unit) => {
                        let cp = 0x10000 + (((hi - 0xd800) as u32) << 10) + (unit - 0xdc00) as u32;
                        out.push(char::from_u32(cp)?);
                    }
                    Some(_) => {
                        out.push('\u{fffd}');
                        push_unit(&mut out, &mut pending_high, unit);
                    }
                    None => push_unit(&mut out, &mut pending_high, unit),
                }
                continue;
            }
            if pending_high.take().is_some() {
                out.push('\u{fffd}');
            }
            out.push(match e {
                b'"' => '"',
                b'\\' => '\\',
                b'/' => '/',
                b'b' => '\u{8}',
                b'f' => '\u{c}',
                b'n' => '\n',
                b'r' => '\r',
                b't' => '\t',
                _ => return None,
            });
            continue;
        }
        if c < 0x20 {
            return None; // a raw control character is invalid JSON
        }
        if pending_high.take().is_some() {
            out.push('\u{fffd}');
        }
        // Step over one whole UTF-8 character.
        let rest = std::str::from_utf8(&b[*i..]).ok()?;
        let ch = rest.chars().next()?;
        out.push(ch);
        *i += ch.len_utf8();
    }
}

fn push_unit(out: &mut String, pending: &mut Option<u16>, unit: u16) {
    if (0xd800..0xdc00).contains(&unit) {
        *pending = Some(unit);
    } else {
        out.push(char::from_u32(unit as u32).unwrap_or('\u{fffd}'));
    }
}

fn hex4(b: &[u8], i: &mut usize) -> Option<u16> {
    let s = b.get(*i..*i + 4)?;
    let mut v: u16 = 0;
    for &c in s {
        v = v.checked_mul(16)? + (c as char).to_digit(16)? as u16;
    }
    *i += 4;
    Some(v)
}

fn parse_number(b: &[u8], i: &mut usize) -> Option<Value> {
    let start = *i;
    if b.get(*i) == Some(&b'-') {
        *i += 1;
    }
    // JSON forbids leading zeros, and so does CPython's decoder.
    match b.get(*i)? {
        b'0' => *i += 1,
        c if c.is_ascii_digit() => {
            while b.get(*i).is_some_and(u8::is_ascii_digit) {
                *i += 1;
            }
        }
        _ => return None,
    }
    let mut is_float = false;
    if b.get(*i) == Some(&b'.') {
        *i += 1;
        if !b.get(*i).is_some_and(u8::is_ascii_digit) {
            return None;
        }
        while b.get(*i).is_some_and(u8::is_ascii_digit) {
            *i += 1;
        }
        is_float = true;
    }
    if matches!(b.get(*i), Some(b'e') | Some(b'E')) {
        *i += 1;
        if matches!(b.get(*i), Some(b'+') | Some(b'-')) {
            *i += 1;
        }
        if !b.get(*i).is_some_and(u8::is_ascii_digit) {
            return None;
        }
        while b.get(*i).is_some_and(u8::is_ascii_digit) {
            *i += 1;
        }
        is_float = true;
    }
    let text = std::str::from_utf8(&b[start..*i]).ok()?;
    if is_float {
        return Some(Value::Float(text.parse().ok()?));
    }
    match text.parse::<i64>() {
        Ok(n) => Some(Value::Int(n)),
        // Python integers have no width. Keeping the digits is the only way to
        // quote the value back unchanged.
        Err(_) => Some(Value::BigInt(text.to_string())),
    }
}

// --------------------------------------------------------------------------
// serializing
// --------------------------------------------------------------------------

/// `json.dumps(obj)` for a string-keyed, string-valued mapping: `", "` between
/// pairs, `": "` after keys, and `ensure_ascii=True`.
pub fn dumps_object(pairs: &[(String, String)]) -> String {
    let body = pairs
        .iter()
        .map(|(k, v)| format!("{}: {}", dumps_str(k), dumps_str(v)))
        .collect::<Vec<_>>()
        .join(", ");
    format!("{{{body}}}")
}

/// `json.dumps(s)` with `ensure_ascii=True`.
pub fn dumps_str(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c if (c as u32) < 0x7f => out.push(c),
            c => {
                // Non-ASCII is escaped, and astral characters become a
                // surrogate pair, exactly as CPython's encoder emits them.
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

// --------------------------------------------------------------------------
// repr
// --------------------------------------------------------------------------

/// Python's `repr` of a `dict[str, str]`, which is what an f-string produces
/// when a selector is interpolated directly.
pub fn py_dict_repr(pairs: &[(String, String)]) -> String {
    let body = pairs
        .iter()
        .map(|(k, v)| format!("{}: {}", py_repr_str(k), py_repr_str(v)))
        .collect::<Vec<_>>()
        .join(", ");
    format!("{{{body}}}")
}

/// Python's `repr` of an arbitrary decoded JSON value.
/// Python's truthiness, which is a *control-flow* rule the oracle relies on.
///
/// `table_add_row` asks `if not supplied` before it asks what shape the row is,
/// so `values: 0` is a missing row and `values: 7` is a misshapen one — two
/// different repairs from two values that are equally not-a-row. Rust has no
/// such notion, and writing `is_empty()` the obvious way would merge them.
///
/// `NaN` is true in Python: the rule is `__bool__`, not "is this a number worth
/// having". `-0.0` is false.
pub fn py_truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Int(i) => *i != 0,
        // A `BigInt` only exists because the literal did not fit an `i64`, so
        // it cannot be zero -- but the digits are checked rather than assumed,
        // since the variant is reachable from `PyInt` too.
        Value::BigInt(d) => !d
            .trim_start_matches(['-', '+'])
            .trim_start_matches('0')
            .is_empty(),
        Value::Float(f) => *f != 0.0,
        Value::Str(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Python's `str(v)`, which differs from [`py_repr`] on exactly one type: a
/// string is itself rather than a quoted literal.
///
/// The dispatch's `_item` helper is `str(v)` on whatever the model sent, so
/// `text: 7` becomes `"7"` and `text: null` never reaches it. Anything that goes
/// into a document through that path must be spelled the way CPython spells it.
pub fn py_str(v: &Value) -> String {
    match v {
        Value::Str(s) => s.clone(),
        other => py_repr(other),
    }
}

pub fn py_repr(v: &Value) -> String {
    match v {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Int(n) => n.to_string(),
        Value::BigInt(s) => s.clone(),
        Value::Float(f) => py_float_repr(*f),
        Value::Str(s) => py_repr_str(s),
        Value::Array(xs) => {
            let body = xs.iter().map(py_repr).collect::<Vec<_>>().join(", ");
            format!("[{body}]")
        }
        Value::Object(kv) => {
            let body = kv
                .iter()
                .map(|(k, val)| format!("{}: {}", py_repr_str(k), py_repr(val)))
                .collect::<Vec<_>>()
                .join(", ");
            format!("{{{body}}}")
        }
    }
}

/// Python's `repr` of a `str`: single quotes, unless the value contains a
/// single quote and no double quote.
pub fn py_repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || (c as u32) == 0x7f => {
                out.push_str(&format!("\\x{:02x}", c as u32))
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Python's `repr` of a `float`, which Rust's `{}` is not.
///
/// Both produce the shortest digit string that round-trips, so the digits agree
/// and only the layout differs. CPython (`format_float_short`, mode `'r'`)
/// switches to exponential form when the decimal point sits at or before -4 or
/// after 16, always writes at least one digit after the point in fixed form,
/// and pads the exponent to two digits. Rust's `{}` never uses exponential form
/// and never adds a trailing `.0`, so `1e20` and `1.0` both come out wrong
/// without this.
pub fn py_float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".to_string();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    let neg = f.is_sign_negative();
    let a = f.abs();
    if a == 0.0 {
        return if neg {
            "-0.0".to_string()
        } else {
            "0.0".to_string()
        };
    }

    // `{:e}` gives the shortest round-tripping digits with an explicit
    // exponent: "7e-1", "1.5e0", "1e20". Split it into digits and `decpt`,
    // where the value is 0.<digits> x 10^decpt — the same normalization
    // CPython's `_Py_dg_dtoa` produces.
    let sci = format!("{a:e}");
    let (mantissa, exp) = sci.split_once('e').expect("{:e} always emits an exponent");
    let exp: i32 = exp.parse().expect("{:e} exponent is an integer");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let digits = digits.trim_end_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };
    let decpt = exp + 1;

    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if decpt <= -4 || decpt > 16 {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        let e = decpt - 1;
        let _ = write!(out, "e{}{:02}", if e < 0 { '-' } else { '+' }, e.abs());
    } else if decpt <= 0 {
        out.push_str("0.");
        for _ in 0..-decpt {
            out.push('0');
        }
        out.push_str(digits);
    } else if (decpt as usize) >= digits.len() {
        out.push_str(digits);
        for _ in 0..(decpt as usize - digits.len()) {
            out.push('0');
        }
        out.push_str(".0");
    } else {
        out.push_str(&digits[..decpt as usize]);
        out.push('.');
        out.push_str(&digits[decpt as usize..]);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pairs(xs: &[(&str, &str)]) -> Vec<(String, String)> {
        xs.iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn dumps_matches_python_separators() {
        assert_eq!(
            dumps_object(&pairs(&[("Component", "gadget"), ("Status", "active")])),
            r#"{"Component": "gadget", "Status": "active"}"#
        );
    }

    #[test]
    fn repr_matches_python_quoting() {
        assert_eq!(
            py_dict_repr(&pairs(&[("Status", "active")])),
            "{'Status': 'active'}"
        );
        assert_eq!(py_repr_str("it's"), "\"it's\"");
        assert_eq!(py_repr_str("both ' and \""), "'both \\' and \"'");
    }

    #[test]
    fn non_ascii_is_escaped_in_json_and_kept_in_repr() {
        // `ensure_ascii=True` is the default, so JSON escapes and `repr` does
        // not — the two call sites are three lines apart in the oracle.
        assert_eq!(dumps_str("caf\u{e9}"), "\"caf\\u00e9\"");
        assert_eq!(py_repr_str("caf\u{e9}"), "'caf\u{e9}'");
    }

    #[test]
    fn floats_repr_the_way_python_does() {
        // The boundaries of the fixed/exponential switch, which is where Rust's
        // `{}` and Python's `repr` part company.
        assert_eq!(py_float_repr(1.5), "1.5");
        assert_eq!(py_float_repr(1.0), "1.0");
        assert_eq!(py_float_repr(0.7), "0.7");
        assert_eq!(py_float_repr(-0.0), "-0.0");
        assert_eq!(py_float_repr(1e15), "1000000000000000.0");
        assert_eq!(py_float_repr(1e16), "1e+16");
        assert_eq!(py_float_repr(1e20), "1e+20");
        assert_eq!(py_float_repr(1e-4), "0.0001");
        assert_eq!(py_float_repr(1e-5), "1e-05");
        assert_eq!(py_float_repr(1.5e-7), "1.5e-07");
    }

    #[test]
    fn parses_what_python_parses_and_rejects_what_it_rejects() {
        assert_eq!(parse("1"), Some(Value::Int(1)));
        assert_eq!(parse("1.0"), Some(Value::Float(1.0)));
        assert_eq!(parse(" null "), Some(Value::Null));
        assert_eq!(
            parse(r#"{"a": 1}"#),
            Some(Value::Object(vec![("a".into(), Value::Int(1))]))
        );
        // Strictness matters: these decide refuse-vs-recover in `_unstring`.
        assert_eq!(parse("{'a': 1}"), None);
        assert_eq!(parse("[1, 2,]"), None);
        assert_eq!(parse("01"), None);
        assert_eq!(parse("i, j, k"), None);
        // Too large for i64, and quoted back to the model unchanged.
        assert_eq!(
            py_repr(&parse("99999999999999999999").unwrap()),
            "99999999999999999999"
        );
    }
}
