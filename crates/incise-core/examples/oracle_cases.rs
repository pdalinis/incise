//! The Rust half of the differential test (`bench/difftest.py`).
//!
//! Reads a case file, applies each case through `incise-core`, and writes one
//! result record per case. `bench/incise_ops.py` runs the identical case list
//! and the two outputs are compared byte-for-byte — including refusal messages,
//! which are as much of the contract as the documents are (§5.3).
//!
//! Deliberately not JSON. The core crate has no dependencies and this is
//! test-only plumbing, so cases use ASCII separator characters that cannot
//! occur in a markdown corpus (US and RS), with backslash escaping for the
//! newlines that can. A JSON parser here would be a hundred lines of surface
//! whose bugs would look exactly like a port bug.

use std::collections::BTreeMap;
use std::fs;

use incise_core::describe::describe_change;
use incise_core::front::{find_frontmatter, format_path, parse_path, Fmt, Seg};
use incise_core::heading::{find_sections, inert_headings};
use incise_core::list::find_lists;
use incise_core::ops::dispatch::apply_op;
use incise_core::ops::frontmatter::{
    describe_frontmatter_change, frontmatter_get, render_frontmatter, render_frontmatter_get,
};
use incise_core::ops::list::{
    list_lists, render_list_summary, resolve_item, resolve_list, ListAddress,
};
use incise_core::ops::section::{
    render_section_outline, resolve_section, section_outline, SectionAddress,
};
use incise_core::ops::table::{
    list_tables, render_table_get, render_table_list, resolve_row, resolve_table, table_add_row,
    table_delete_row, table_update_cell, TableAddress, Values,
};
use incise_core::table::find_tables;
use incise_core::{args as va, json};

const FS: char = '\u{1f}'; // between fields
const RS: char = '\u{1e}'; // between args
const GS: char = '\u{1d}'; // between an arg's key and value

fn esc(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}

/// `"-"` for a field the oracle leaves as `None`, which is how the dumps spell
/// an absent number, delimiter or checkbox without inventing a second column.
fn opt(v: Option<String>) -> String {
    v.unwrap_or_else(|| "-".to_string())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: oracle_cases <cases> <corpus-root> <out>");
        std::process::exit(2);
    }
    let cases = fs::read_to_string(&args[1]).expect("read cases");
    let root = std::path::Path::new(&args[2]);
    let mut out = String::new();
    let mut docs: BTreeMap<String, String> = BTreeMap::new();

    for line in cases.lines() {
        if line.is_empty() {
            continue;
        }
        let parts: Vec<&str> = line.split(FS).collect();
        let (id, file, op, argblob) = (
            parts[0],
            parts[1],
            parts[2],
            parts.get(3).copied().unwrap_or(""),
        );
        let content = docs
            .entry(file.to_string())
            .or_insert_with(|| fs::read_to_string(root.join(file)).expect("read fixture"))
            .clone();
        let a = parse_args(argblob);
        let (status, payload) = run(&content, op, &a);
        out.push_str(&format!("{id}{FS}{status}{FS}{}\n", esc(&payload)));
    }
    fs::write(&args[3], out).expect("write results");
}

type Args = BTreeMap<String, String>;

fn parse_args(blob: &str) -> Args {
    let mut m = BTreeMap::new();
    for pair in blob.split(RS) {
        if pair.is_empty() {
            continue;
        }
        let mut it = pair.splitn(2, GS);
        let k = it.next().unwrap_or("").to_string();
        let v = it.next().unwrap_or("").to_string();
        m.insert(k, v);
    }
    m
}

/// Indexed args as a `where` selector. The values are `json::Value` because
/// that is what the op takes -- `resolve_row` runs `check_cell` over them at the
/// oracle's position, so handing it pre-stringified cells would skip the check.
fn where_pairs(a: &Args) -> Vec<(String, json::Value)> {
    indexed(a, "wk", "wv")
        .into_iter()
        .map(|(k, v)| (k, json::Value::Str(v)))
        .collect()
}

/// Indexed args: `wk0`/`wv0`, `wk1`/`wv1`, … collected in order.
///
/// A repeated key overwrites in place, keeping its original position. Both sides
/// are standing in for one JSON *object*, and `difftest.py` builds a `dict`, so
/// `d[k] = v` on an existing key is the semantics to match — insertion order
/// preserved, value replaced. Keeping both pairs here instead would make a
/// duplicate-column fixture fail on a difference between the two harnesses
/// rather than between the two implementations.
fn indexed(a: &Args, kp: &str, vp: &str) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();
    for i in 0.. {
        match (a.get(&format!("{kp}{i}")), a.get(&format!("{vp}{i}"))) {
            (Some(k), Some(v)) => match out.iter_mut().find(|(ek, _)| ek == k) {
                Some(slot) => slot.1 = v.clone(),
                None => out.push((k.clone(), v.clone())),
            },
            _ => break,
        }
    }
    out
}

/// The `filter` argument of the read op, as the op takes it.
///
/// Three distinct inputs, and they are not interchangeable: absent (every row),
/// an empty object (also every row, but by a different route through
/// `check_filter`), and a populated object. `shape=filter` on the wire is how a
/// case says "an empty object was sent" rather than "nothing was sent".
fn filter_arg(a: &Args) -> Option<json::Value> {
    let pairs = indexed(a, "fk", "fv");
    if pairs.is_empty() && a.get("shape").map(String::as_str) != Some("filter") {
        return None;
    }
    Some(json::Value::Object(
        pairs
            .into_iter()
            .map(|(k, v)| (k, json::Value::Str(v)))
            .collect(),
    ))
}

fn address(a: &Args) -> TableAddress {
    TableAddress {
        heading: a.get("heading").map(|h| json::Value::Str(h.clone())),
        // `difftest.py` does `int(ordinal)` before it calls, so the address
        // carries an integer rather than a numeric string.
        ordinal: a
            .get("ordinal")
            .and_then(|s| s.parse::<i64>().ok())
            .map(json::Value::Int),
    }
}

/// The whole argument object, smuggled through as one JSON string.
///
/// The flat wire format carries `KEY␝VALUE` pairs and nothing else, so every
/// value it can express is a string. That left `check_cell`'s refusals on a
/// boolean, a null or a nested object *inside* a filter reachable by no case at
/// all — the F-args gap in miniature, and the stated reason `filter-value-typed`
/// was kept out of `mutate.py`: a mutation known in advance to be unreachable
/// measures the harness, not the code.
///
/// `apply_op` and `describe_change` already use this convention. Adding it here
/// is FINDINGS' "worth doing once rather than per-op", not a second mechanism.
fn typed_args(a: &Args) -> Option<json::Value> {
    a.get("args").and_then(|t| json::parse(t))
}

/// The `table` field of a [`typed_args`] object as an address.
///
/// A bare string is shorthand for the heading, matching `_locate_table`. Any
/// other type is passed through as the heading so the *check* is what answers
/// it, rather than this function deciding the answer.
fn typed_address(v: Option<&json::Value>) -> TableAddress {
    match v {
        Some(json::Value::Object(_)) => TableAddress {
            heading: v.unwrap().get("heading").cloned(),
            ordinal: v.unwrap().get("ordinal").cloned(),
        },
        Some(x) => TableAddress {
            heading: Some(x.clone()),
            ordinal: None,
        },
        None => TableAddress {
            heading: None,
            ordinal: None,
        },
    }
}

/// The `filter` field of a [`typed_args`] object.
///
/// `null` and absent collapse to `None`, because they collapse on the other
/// side: `table_get(content, address, filter=None)` cannot tell a caller who
/// passed `None` from one who passed nothing. Keeping them apart here would
/// make the two sides express two different calls that only look alike on the
/// wire. A *null filter* is `check_filter`'s business and the `check_args`
/// cross product already reaches it; what this hatch is for is a filter that
/// exists and holds a value no string can be.
fn typed_filter(v: &json::Value) -> Option<json::Value> {
    match v.get("filter") {
        None | Some(json::Value::Null) => None,
        Some(x) => Some(x.clone()),
    }
}

/// The same two fields as [`address`], for the list family — a separate type
/// on that side, so a separate builder here.
fn list_address(a: &Args) -> ListAddress {
    ListAddress {
        heading: a.get("heading").map(|h| json::Value::Str(h.clone())),
        ordinal: a
            .get("ordinal")
            .and_then(|s| s.parse::<i64>().ok())
            .map(json::Value::Int),
    }
}

/// The section family's address, off its own wire keys. Three fields rather
/// than two, and `path` is not a spelling of `heading` — `resolve_section`
/// reads `path` first and falls back, so a case that sends only `sheading` is
/// exercising a branch the other two families do not have.
fn section_address(a: &Args) -> SectionAddress {
    SectionAddress {
        path: a.get("spath").map(|p| json::Value::Str(p.clone())),
        heading: a.get("sheading").map(|h| json::Value::Str(h.clone())),
        ordinal: a
            .get("sordinal")
            .and_then(|s| s.parse::<i64>().ok())
            .map(json::Value::Int),
    }
}

fn values(a: &Args) -> Values {
    let named = indexed(a, "vk", "vv");
    if !named.is_empty() || a.get("shape").map(String::as_str) == Some("named") {
        return Values::named(named);
    }
    let mut ordered = Vec::new();
    for i in 0.. {
        match a.get(&format!("vo{i}")) {
            Some(v) => ordered.push(v.clone()),
            None => break,
        }
    }
    Values::ordered(ordered)
}

/// The raw `position`, as the op takes it -- `check_position` runs inside
/// `table_add_row`, after the row's cells, and handing it a pre-checked
/// `Position` here would move that refusal ahead of a bad cell.
///
/// `difftest.py` does `int(position)` before it calls, so a numeric case reaches
/// the op as an integer rather than a numeric string. Mirrored exactly: the two
/// happen to agree in `check_position`, but a case that only passes because two
/// paths agree is not testing the path it names.
fn position(a: &Args) -> Option<json::Value> {
    let raw = a.get("position").map(String::as_str).unwrap_or("end");
    Some(match raw {
        "start" | "end" => json::Value::Str(raw.to_string()),
        n => match n.parse::<i64>() {
            Ok(i) => json::Value::Int(i),
            Err(_) => json::Value::Str(n.to_string()),
        },
    })
}

/// One validation function against one JSON value (FINDINGS F-args).
///
/// The Python side answers with `repr()` of whatever the function returned, so
/// this side answers with `json::py_repr` of the same thing -- uniformly, even
/// where the return is already a string, so that `'0'` and `0` cannot compare
/// equal by accident.
fn arg_case(fname: &str, text: &str) -> Result<String, incise_core::error::OpError> {
    let absent = text == "ABSENT";
    let parsed = if absent { None } else { json::parse(text) };
    // Every ARG_VALUES entry is valid JSON by construction; a `None` here would
    // be a `parse` bug, and reporting it as such beats silently testing `None`.
    if !absent && parsed.is_none() {
        return Ok(format!("PARSE-FAILED {text}"));
    }
    let v = parsed.as_ref();
    let opt = |name: &str| -> json::Value {
        match v {
            None => json::Value::Object(vec![]),
            Some(x) => json::Value::Object(vec![(name.to_string(), x.clone())]),
        }
    };
    let repr_opt = |o: Option<json::Value>| match o {
        None => "None".to_string(),
        Some(x) => json::py_repr(&x),
    };

    Ok(match fname {
        "unstring_obj" => repr_opt(va::unstring(v, va::Expect::Object, "table", false)?),
        "unstring_obj_plain" => repr_opt(va::unstring(v, va::Expect::Object, "table", true)?),
        "unstring_objarr" => repr_opt(va::unstring(v, va::Expect::ObjectOrArray, "values", false)?),
        "clean_keys" => repr_opt(va::clean_keys(v.cloned())),
        "check_address" => repr_opt(va::check_address(v.cloned(), "table")?),
        "check_heading" => match va::check_heading(v, "table")? {
            None => "None".to_string(),
            Some(s) => json::py_repr_str(&s),
        },
        "check_ordinal" => match va::check_ordinal(v, "table")? {
            None => "None".to_string(),
            Some(n) => n.repr(),
        },
        "check_position" => match va::check_position(v)? {
            va::Position::Start => "'start'".to_string(),
            va::Position::End => "'end'".to_string(),
            va::Position::Index(n) => n.repr(),
        },
        "check_cell" => json::py_repr_str(&va::check_cell(
            v.unwrap_or(&json::Value::Null),
            "Component",
            "values",
        )?),
        "check_where" => repr_opt(va::check_where(v.cloned())?),
        "check_filter" => repr_opt(va::check_filter(v)?.map(|p| json::Value::Object(p.clone()))),
        "check_column" => json::py_repr_str(&va::check_column(v)?),
        "address" => repr_opt(va::address(&opt("table"))?),
        "values" => repr_opt(va::values(&opt("values"), "values")?),
        "where_arg" => repr_opt(va::where_arg(&opt("where"))?),
        other => panic!("unknown arg fn {other}"),
    })
}

fn run(content: &str, op: &str, a: &Args) -> (&'static str, String) {
    match op {
        "py_repr" => {
            let text = a.get("text").map(String::as_str).unwrap_or("");
            match json::parse(text) {
                None => ("ok", "UNPARSED".to_string()),
                Some(v) => ("ok", json::py_repr(&v)),
            }
        }
        "check_args" => {
            let f = a.get("fn").map(String::as_str).unwrap_or("");
            let text = a.get("text").map(String::as_str).unwrap_or("");
            match arg_case(f, text) {
                Ok(s) => ("ok", s),
                Err(e) => ("err", e.message().to_string()),
            }
        }
        "render_table_list" => (
            "ok",
            render_table_list(content, a.get("path").map(String::as_str).unwrap_or("")),
        ),
        "list_tables" => {
            let dump = list_tables(content)
                .iter()
                .map(|e| {
                    format!(
                        "{}|{}|{}|{}|{}",
                        e.ordinal,
                        e.heading,
                        e.caption,
                        e.columns.join(" | "),
                        e.rows
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            ("ok", dump)
        }
        "find_tables" => {
            let dump = find_tables(content)
                .iter()
                .map(|t| format!("{}|{}|{}|{}", t.start, t.end, t.is_aligned(), t.has_tabs()))
                .collect::<Vec<_>>()
                .join("\n");
            ("ok", dump)
        }
        "find_sections" => {
            let dump = find_sections(content)
                .iter()
                .map(|s| {
                    format!(
                        "{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
                        s.start,
                        s.heading_end,
                        s.own_end,
                        s.end,
                        s.level,
                        s.style.as_str(),
                        s.gap_after,
                        s.parent.map(|p| p as isize).unwrap_or(-1),
                        esc(&s.indent),
                        s.marker,
                        esc(&s.space),
                        s.closing,
                        esc(&s.raw_text),
                        s.path.join(" > ")
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            ("ok", dump)
        }
        // The list parser, field by field, for the reason `find_sections` is
        // dumped: an op suite can agree everywhere and still be sitting on a
        // parser that disagrees about where a list ends. One line per list,
        // then one indented line per item -- `own_end` and `parent` are in
        // there because nothing else reads them, so nothing else would notice.
        "find_lists" => {
            let mut dump: Vec<String> = Vec::new();
            for l in find_lists(content) {
                dump.push(format!(
                    "{}|{}|{}|{}|{}|{}",
                    l.start,
                    l.end,
                    l.ordered,
                    l.bullet,
                    esc(&l.indent),
                    l.loose
                ));
                for it in &l.items {
                    dump.push(format!(
                        "  {}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
                        it.start,
                        it.own_end,
                        it.end,
                        it.depth,
                        esc(&it.indent),
                        it.marker,
                        it.ordered,
                        opt(it.number.map(|n| n.to_string())),
                        opt(it.delim.map(|c| c.to_string())),
                        opt(it.checkbox.map(|c| c.to_string())),
                        it.parent.map(|p| p as isize).unwrap_or(-1),
                        esc(&it.text)
                    ));
                }
            }
            ("ok", dump.join("\n"))
        }
        // The frontmatter parser, field by field, for the reason the other two
        // are dumped -- plus `rebuilt()`, which no other dump has an analogue
        // for. Every edit in the family goes out through it, so comparing it
        // here catches a gap or padding divergence on a line no op in the suite
        // happens to rewrite.
        // `parse_path`, typed and round-tripped. Its own case op because the
        // parser only ever hands out paths it built itself, so the refusal
        // branch and the index arithmetic are reachable from no fixture.
        "parse_path" => match parse_path(a.get("text").map(String::as_str).unwrap_or("")) {
            None => ("ok", "NONE".to_string()),
            Some(p) => {
                let kinds = p
                    .iter()
                    .map(|s| match s {
                        Seg::Index(n) => format!("i:{n}"),
                        Seg::Key(k) => format!("k:{k}"),
                    })
                    .collect::<Vec<_>>()
                    .join("|");
                ("ok", format!("{}\n{kinds}", format_path(&p)))
            }
        },
        "find_frontmatter" => {
            let fm = find_frontmatter(content);
            if !fm.present {
                return ("ok", "absent".to_string());
            }
            let mut dump = vec![format!(
                "{}|{}|{}|{}|{}|{}",
                match fm.fmt {
                    Some(Fmt::Yaml) => "yaml",
                    _ => "toml",
                },
                fm.start,
                fm.end,
                fm.delim,
                fm.close,
                esc(&fm.eol)
            )];
            for e in &fm.entries {
                dump.push(format!(
                    "  {}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
                    format_path(&e.path),
                    e.line,
                    e.end,
                    e.kind.as_str(),
                    esc(&e.prefix),
                    esc(&e.key_text),
                    esc(&e.gap),
                    esc(&e.value),
                    esc(&e.pad),
                    esc(&e.comment),
                    esc(&e.eol),
                    esc(&e.rebuilt(None))
                ));
            }
            ("ok", dump.join("\n"))
        }
        // `describe_change`'s case, for the family it does not describe. The
        // same shape deliberately: both sides apply the op and describe
        // before-vs-after, so a divergence in either half shows here.
        "describe_front" => {
            let name = a.get("opname").map(String::as_str).unwrap_or("");
            let arg = a.get("args").map(String::as_str).unwrap_or("ABSENT");
            let parsed = if arg == "ABSENT" {
                None
            } else {
                json::parse(arg)
            };
            if arg != "ABSENT" && parsed.is_none() {
                ("ok", format!("PARSE-FAILED {arg}"))
            } else {
                match apply_op(content, name, parsed.as_ref()) {
                    Ok(after) => ("ok", describe_frontmatter_change(content, &after)),
                    Err(e) => ("err", e.0),
                }
            }
        }
        "render_frontmatter" => (
            "ok",
            render_frontmatter(content, a.get("path").map(String::as_str).unwrap_or("")),
        ),
        // Through the rendered form for `render_table_get`'s reason — it is
        // what a model receives — and through the structure as well, because
        // that is what `keys --json` carries and `grade.py` scores. `state` and
        // `format` appear in neither rendering, so a port that got them wrong
        // would pass on the text alone.
        "frontmatter_get" => {
            let path = a.get("path").map(String::as_str).unwrap_or("");
            // Absent and an explicit `null` are the same call here, which is
            // the asymmetry with `frontmatter-set` the oracle spells with a
            // `key=None` default. Parsing gives `Value::Null` for the second
            // and the op filters it, so both arrive as no key.
            let key = match a.get("key") {
                None => None,
                Some(text) => match json::parse(text) {
                    Some(v) => Some(v),
                    None => return ("ok", format!("PARSE-FAILED {text}")),
                },
            };
            let got = match frontmatter_get(content, key.as_ref()) {
                Ok(g) => g,
                Err(e) => return ("err", e.0),
            };
            let text = match render_frontmatter_get(content, path, key.as_ref()) {
                Ok(t) => t,
                Err(e) => return ("err", e.0),
            };
            let mut dump = vec![format!(
                "{}|{}|{}",
                got.state,
                match got.format {
                    Some(Fmt::Yaml) => "yaml",
                    Some(Fmt::Toml) => "toml",
                    // Python's `None`, printed as an f-string prints it: the
                    // oracle's dict holds the parser's `fmt` unconverted, and
                    // an absent block has no format at all.
                    None => "None",
                },
                got.keys.len()
            )];
            for k in &got.keys {
                dump.push(format!(
                    "{}|{}|{}|{}",
                    k.path,
                    k.kind,
                    esc(&k.value),
                    k.lines
                ));
            }
            dump.push("--".to_string());
            dump.push(text);
            ("ok", dump.join("\n"))
        }
        // The list summary, field by field. The rendering is compared too, one
        // case below -- it is the Arm B prompt, so a divergence in it is a
        // divergence in what the model was measured on, not in a debug format.
        "list_lists" => {
            let dump = list_lists(content)
                .iter()
                .map(|e| {
                    format!(
                        "{}|{}|{}|{}|{}|{}|{}|{}",
                        e.ordinal, e.heading, e.kind, e.marker, e.items, e.levels, e.loose, e.tasks
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            ("ok", dump)
        }
        "render_list_summary" => (
            "ok",
            render_list_summary(content, a.get("path").map(String::as_str).unwrap_or("")),
        ),
        // The section outline, field by field, and its rendering one case
        // below. The render is the section family's prompt context, so a
        // divergence in it is a divergence in what a model was measured on.
        "section_outline" => {
            let dump = section_outline(content)
                .iter()
                .map(|e| {
                    format!(
                        "{}|{}|{}|{}|{}|{}|{}|{}",
                        e.level,
                        e.path,
                        e.text,
                        e.style,
                        e.ordinal,
                        e.unique,
                        e.has_body,
                        e.subsections
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            ("ok", dump)
        }
        "render_section_outline" => (
            "ok",
            render_section_outline(content, a.get("path").map(String::as_str).unwrap_or("")),
        ),
        // Three ends, not one: `own_end` and `end` are the field the ops
        // disagree about, so a resolver that found the right section with the
        // wrong subtree boundary would pass a `start`-only comparison.
        "resolve_section" => match resolve_section(content, &section_address(a)) {
            Ok(s) => (
                "ok",
                format!(
                    "{}|{}|{}|{}|{}",
                    s.start, s.heading_end, s.own_end, s.end, s.level
                ),
            ),
            Err(e) => ("err", e.0),
        },
        "resolve_list" => match resolve_list(content, &list_address(a)) {
            Ok(l) => ("ok", format!("{}|{}", l.start, l.end)),
            Err(e) => ("err", e.0),
        },
        "resolve_item" => match resolve_list(content, &list_address(a))
            .and_then(|l| resolve_item(&l, a.get("item").map(String::as_str), "item"))
        {
            Ok(i) => ("ok", i.to_string()),
            Err(e) => ("err", e.0),
        },
        "inert_headings" => {
            let dump = inert_headings(content)
                .iter()
                .map(|h| format!("{}|{}|{}", h.line, h.reason, h.text))
                .collect::<Vec<_>>()
                .join("\n");
            ("ok", dump)
        }
        "resolve_table" => match resolve_table(content, &address(a)) {
            Ok(t) => ("ok", format!("{}|{}", t.start, t.end)),
            Err(e) => ("err", e.0),
        },
        "resolve_row" => match resolve_table(content, &address(a))
            .and_then(|t| resolve_row(&t, &where_pairs(a)))
        {
            Ok(i) => ("ok", i.to_string()),
            Err(e) => ("err", e.0),
        },
        "add_row" => match table_add_row(content, &address(a), &values(a), position(a).as_ref()) {
            Ok(s) => ("ok", s),
            Err(e) => ("err", e.0),
        },
        "update_cell" => match table_update_cell(
            content,
            &address(a),
            &where_pairs(a),
            // Both raw, and both defaulted to "" -- the Python side passes
            // `args.get("column", "")` and `args.get("value", "")`, so an absent
            // argument is the empty string on this side too.
            Some(&json::Value::Str(
                a.get("column").cloned().unwrap_or_default(),
            )),
            Some(&json::Value::Str(
                a.get("value").cloned().unwrap_or_default(),
            )),
        ) {
            Ok(s) => ("ok", s),
            Err(e) => ("err", e.0),
        },
        // The read op, through its rendered form -- which is the whole result:
        // heading, matched/total counts, columns and every cell all appear in
        // the text, so comparing the render compares the struct behind it.
        // Comparing `TableRows` field by field would test a debug format that
        // no caller ever sees.
        "table_get" => {
            // Two wire formats, one op. The flat one is what every table case
            // uses; `args` is the typed hatch, and a case carrying it takes the
            // address from there too, or an untyped address would silently
            // override the typed one.
            let (addr, filt) = match typed_args(a) {
                Some(v) => (typed_address(v.get("table")), typed_filter(&v)),
                None => (address(a), filter_arg(a)),
            };
            match render_table_get(content, &addr, filt.as_ref()) {
                Ok(s) => ("ok", s),
                Err(e) => ("err", e.0),
            }
        }
        "delete_row" => match table_delete_row(content, &address(a), &where_pairs(a)) {
            Ok(s) => ("ok", s),
            Err(e) => ("err", e.0),
        },
        // The whole dispatch, arguments and all -- the op name and the raw
        // argument text, exactly as `difftest.py` hands them to `F.apply_op`.
        // What is compared is the message a model would actually receive, so
        // the argument-checking *order* (dispatch.rs's whole reason to exist)
        // is under test here and nowhere else.
        "apply_op" => {
            let name = a.get("opname").map(String::as_str).unwrap_or("");
            let text = a.get("args").map(String::as_str).unwrap_or("ABSENT");
            let parsed = if text == "ABSENT" {
                None
            } else {
                json::parse(text)
            };
            // Every DISPATCH_ARGS entry but `ABSENT` is valid JSON by
            // construction, so a `None` here is a `parse` bug. Saying so beats
            // passing `None` on and quietly testing the absent-argument path.
            if text != "ABSENT" && parsed.is_none() {
                ("ok", format!("PARSE-FAILED {text}"))
            } else {
                match apply_op(content, name, parsed.as_ref()) {
                    Ok(s) => ("ok", s),
                    Err(e) => ("err", e.0),
                }
            }
        }
        // `describe_change` needs two documents, and a case carries one
        // fixture. So it carries the *op* that produces the second: both sides
        // apply it and describe before-vs-after, which keeps the wire cheap and
        // reuses a document the corpus already vouches for. A refusal is
        // returned as itself — those messages are compared by the `apply_op`
        // family anyway, so nothing is lost and no case is wasted.
        //
        // `after` is the escape hatch for the branches no op reaches. It rides
        // as a JSON string because a raw newline would break the line-framed
        // case file, which is the same reason `apply_op` passes its arguments
        // that way.
        "describe_change" => {
            if let Some(text) = a.get("after") {
                return match json::parse(text) {
                    Some(json::Value::Str(s)) => ("ok", describe_change(content, &s)),
                    _ => ("ok", format!("PARSE-FAILED {text}")),
                };
            }
            let name = a.get("opname").map(String::as_str).unwrap_or("");
            let arg = a.get("args").map(String::as_str).unwrap_or("ABSENT");
            let parsed = if arg == "ABSENT" {
                None
            } else {
                json::parse(arg)
            };
            if arg != "ABSENT" && parsed.is_none() {
                ("ok", format!("PARSE-FAILED {arg}"))
            } else {
                match apply_op(content, name, parsed.as_ref()) {
                    Ok(after) => ("ok", describe_change(content, &after)),
                    Err(e) => ("err", e.0),
                }
            }
        }
        other => ("err", format!("unknown op {other}")),
    }
}
