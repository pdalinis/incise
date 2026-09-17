//! The op dispatch: an op name and a JSON argument object in, a document or a
//! refusal out.
//!
//! This is the port of `apply_op` and the `OPS` table in `bench/incise_ops.py`,
//! and it is its own module for one reason: **the order the arguments are
//! checked in is part of the contract**, and in Python that order is made by the
//! language rather than by any code. `OPS` maps each op to a lambda whose
//! arguments are `_address(a)`, `_values(a)`, and so on, so Python evaluates
//! every one of them, left to right, *before* the op function runs. A malformed
//! `values` therefore outranks a nonexistent table, and a malformed `position`
//! does not, because `position` is passed through raw and checked inside the op.
//!
//! Rust has no such rule. Written naturally, a dispatch here would validate
//! everything up front and get a different refusal out of the same call. §5.3
//! makes the refusal the product — Arm B measured recovery against those exact
//! sentences — so "a refusal, just a different one" is a regression. The order
//! below is transcribed from `args`'s ordering note, not derived.
//!
//! One deliberate divergence from the oracle, recorded in FINDINGS: the oracle
//! accepts `row` as a legacy alias for `values` so `scheme_d`'s recorded trials
//! stay regradable. §6.2 rejected that second argument for the shipping schema
//! after measuring it, so it is absent here — `{"row": [...]}` gets "a row is
//! required", where the oracle would add the row.
//!
//! The other divergence is closed. This dispatch names what the crate
//! implements, and with the frontmatter family ported that is all fifteen of
//! the oracle's `OPS` entries in the oracle's own order, so the "unknown
//! operation" refusal now lists the same fifteen ops in the same sequence.
//! `difftest.py` compares that refusal directly rather than excluding unknown
//! op names, which is what it had to do while the two tables differed.
//!
//! The list family's aliases are a different case and ARE kept. `_item(a, "item",
//! "match")` accepts both spellings because the schemes under test spell the
//! selector differently, and §6.4 named `match` the selector for the shipping
//! schema; dropping `item` would change which of two live names works, not
//! remove a rejected one.

use crate::args;
use crate::error::{OpError, Result};
use crate::json::{self, Value};
use crate::ops::frontmatter::{frontmatter_delete, frontmatter_set};
use crate::ops::list::{list_add_item, list_remove_item, list_set_checked, ListAddress};
use crate::ops::section::{
    section_address_fields, section_append, section_delete, section_insert, section_rename,
    section_replace_body, section_set_level, SectionAddress,
};
use crate::ops::table::{
    table_add_row, table_delete_row, table_realign, table_update_cell, TableAddress, Values,
};

/// The ops this crate implements, in the order the "unknown operation" refusal
/// names them.
pub const OPS: &[&str] = &[
    "table-add-row",
    "table-update-cell",
    "table-delete-row",
    "table-realign",
    "list-add-item",
    "list-remove-item",
    "list-set-checked",
    "section-append",
    "section-replace-body",
    "section-insert",
    "section-delete",
    "section-rename",
    "section-set-level",
    "frontmatter-set",
    "frontmatter-delete",
];

/// Apply one op. `Ok(document)`, or `Err` carrying the sentence the model reads.
///
/// The oracle returns `(content, None)` or `(None, message)`; a `Result` says
/// the same thing in Rust's vocabulary, and a caller that needs the tuple can
/// make it at the edge.
///
/// There is no equivalent of the oracle's `except (KeyError, TypeError, ...)`
/// backstop. That clause exists because Python cannot promise an argument was
/// validated, and every message it can produce is an exception repr rather than
/// a repair; here the types make the promise instead.
pub fn apply_op(content: &str, op: &str, args: Option<&Value>) -> Result<String> {
    if !OPS.contains(&op) {
        return Err(OpError::new(format!(
            "unknown operation \"{op}\". Valid: {}",
            OPS.join(", ")
        )));
    }
    // Reached when a model emits a bare string or array where the argument
    // object belongs. Without this the oracle surfaced "AttributeError: 'str'
    // object has no attribute 'get'" — a stack trace where a repair belongs.
    let empty = Value::Object(Vec::new());
    let a = match args {
        None | Some(Value::Null) => &empty,
        Some(v @ Value::Object(_)) => v,
        Some(v) => {
            return Err(OpError::new(format!(
                "arguments for `{op}` must be an object, but arrived as {}.\n  Got: {}",
                v.type_name(),
                json::py_repr(v)
            )))
        }
    };

    match op {
        // lambda c, a: table_add_row(c, _address(a), _values(a), a.get("position", "end"), ...)
        //
        // `address` and `values` are lambda arguments and run first, in that
        // order. `position` is passed through raw, which is why it is checked
        // last of all — inside `table_add_row`, after the row's cells.
        "table-add-row" => {
            let address = to_address(args::address(a)?);
            let values = to_values(args::values(a, "values")?);
            table_add_row(content, &address, &values, a.get("position"))
        }
        // lambda c, a: table_update_cell(c, _address(a), _where(a), a.get("column"), a.get("value"))
        //
        // `column` and `value` are both raw: `check_column` runs inside the op
        // once the table has resolved, and `check_value` runs after the row has.
        "table-update-cell" => {
            let address = to_address(args::address(a)?);
            let selector = to_where(args::where_arg(a)?);
            table_update_cell(
                content,
                &address,
                &selector,
                a.get("column"),
                a.get("value"),
            )
        }
        "table-delete-row" => {
            let address = to_address(args::address(a)?);
            let selector = to_where(args::where_arg(a)?);
            table_delete_row(content, &address, &selector)
        }
        // lambda c, a: table_realign(c, _address(a))
        //
        // One argument, so there is no ordering to get wrong here — the only
        // op in the family for which that is true.
        "table-realign" => {
            let address = to_address(args::address(a)?);
            table_realign(content, &address)
        }
        // lambda c, a: list_add_item(c, _list_address(a), _item(a, "text"),
        //                            a.get("position", "end"), _item(a, "after"),
        //                            a.get("checked"))
        //
        // Only the address can refuse from out here; `_item` reshapes and never
        // raises, and `position` and `checked` travel raw. So the whole ordering
        // question for this family is "the address first", and everything else
        // is decided inside the op after the list has resolved.
        "list-add-item" => {
            let address = to_list_address(args::list_address(a)?);
            let text = item(a, &["text"]);
            let after = item(a, &["after"]);
            list_add_item(
                content,
                &address,
                text.as_deref(),
                a.get("position"),
                after.as_deref(),
                a.get("checked"),
            )
        }
        "list-remove-item" => {
            let address = to_list_address(args::list_address(a)?);
            let selector = item(a, &["item", "match"]);
            list_remove_item(content, &address, selector.as_deref())
        }
        // `a.get("checked", True)` — absent means tick. An explicit `null` does
        // not: it reaches the op as a value that is not in the truthy tuple, so
        // it unticks. `None` here is the absent case only, which is why
        // `a.get` returning `Some(Value::Null)` must be passed through.
        "list-set-checked" => {
            let address = to_list_address(args::list_address(a)?);
            let selector = item(a, &["item", "match"]);
            list_set_checked(content, &address, selector.as_deref(), a.get("checked"))
        }
        // The section family, and the same shape of answer as the list family's:
        // only `_section_address(a)` can refuse from out here, so the ordering
        // question is again "the address first". `_item` reshapes without
        // raising, `bool()` cannot raise, and `position`, `level`, `subtree` and
        // `children` all travel raw to be decided after the section resolves.
        //
        // lambda c, a: section_append(c, _section_address(a),
        //                             _item(a, "text", "body"),
        //                             _item(a, "heading", "new_heading", "title"))
        "section-append" => {
            let address = to_section_address(args::section_address(a)?);
            let text = item(a, &["text", "body"]);
            let heading = item(a, &["heading", "new_heading", "title"]);
            section_append(content, &address, text.as_deref(), heading.as_deref())
        }
        // `bool(a.get("overwrite"))`, so absent, `null`, `false`, `0` and `""`
        // are all "not acknowledged" — the guard stays up for everything but a
        // truthy value. The asymmetry is deliberate: the failure this protects
        // against (S2) is a model that never meant to overwrite at all, and such
        // a model does not send `overwrite: 0`.
        "section-replace-body" => {
            let address = to_section_address(args::section_address(a)?);
            let text = item(a, &["text", "body"]);
            let overwrite = a.get("overwrite").is_some_and(json::py_truthy);
            let heading = item(a, &["heading", "new_heading", "title"]);
            section_replace_body(
                content,
                &address,
                text.as_deref(),
                overwrite,
                heading.as_deref(),
            )
        }
        // `a.get("children") or a.get("subsections") or a.get("sections")`: the
        // first TRUTHY one, and — when every one of them is falsy — Python's
        // `or` yields its last operand rather than `None`. `{"sections": []}`
        // therefore arrives as `[]` and not as absent, which `section_insert`
        // re-tests rather than assuming.
        //
        // `heading` reads `heading`/`title` here but `text` is NOT among them,
        // because `_item(a, "body", "text")` claims it for the body. A call that
        // sends only `text` is giving the new section prose, not a name, and is
        // refused for the missing heading.
        "section-insert" => {
            let address = to_section_address(args::section_address(a)?);
            let heading = item(a, &["heading", "title"]);
            let body = item(a, &["body", "text"]);
            let children = ["children", "subsections", "sections"]
                .iter()
                .find_map(|f| a.get(f).filter(|v| json::py_truthy(v)))
                .or_else(|| a.get("sections"));
            section_insert(
                content,
                &address,
                a.get("position"),
                heading.as_deref(),
                body.as_deref(),
                children,
            )
        }
        "section-delete" => {
            let address = to_section_address(args::section_address(a)?);
            section_delete(content, &address)
        }
        // `text` IS a spelling of the new name here, because a rename has no
        // body for it to mean instead.
        "section-rename" => {
            let address = to_section_address(args::section_address(a)?);
            let heading = item(a, &["heading", "title", "text"]);
            section_rename(content, &address, heading.as_deref())
        }
        // `a.get("subtree", True)` — absent means carry the subtree, which is
        // the safe default. An explicit `null` does not: it reaches the op as a
        // falsy value and reparents the children, the same way `checked: null`
        // unticks.
        "section-set-level" => {
            let address = to_section_address(args::section_address(a)?);
            let subtree = a.get("subtree").map_or(true, json::py_truthy);
            section_set_level(content, &address, a.get("level"), subtree)
        }
        // `key` and nothing else. `item`'s alias list is deliberately not used
        // here: every call already carries `path`, meaning the *file*, and
        // letting it double as the frontmatter key is the exact failure S15
        // measured for the section family. `a.get` rather than `item` because
        // `item` stringifies, which would swallow the type refusal `check_key`
        // exists to give.
        //
        // `a.get("value", _MISSING)` is the one argument in the whole dispatch
        // where absent and an explicit `null` must stay apart: null is a value
        // a key can hold, so collapsing them would make `frontmatter-set key`
        // silently mean `frontmatter-set key null`. `Option<&Value>` already
        // says that — `None` is absent, `Some(Value::Null)` is the null — so
        // the distinction needs no sentinel here.
        "frontmatter-set" => frontmatter_set(content, a.get("key"), a.get("value")),
        "frontmatter-delete" => frontmatter_delete(content, a.get("key")),
        _ => unreachable!("op was checked against OPS above"),
    }
}

/// `_item(a, *fields)`: the first of `fields` the caller supplied, as a string.
///
/// Several names are accepted for the *selector* because the schemes under test
/// spell it differently (`item` vs `match`), and the executor must be identical
/// across schemes or the A/B measures the harness. It deliberately does NOT let
/// `list-add-item` read `item`: that collision is the thing being measured (L3),
/// and quietly absorbing it here would erase the result instead of recording it.
///
/// `str(v)` and not `repr(v)`, so `text: 7` becomes `"7"` — a number the model
/// meant as content becomes that content, spelled the way CPython spells it.
/// A JSON `null` is skipped, because in the oracle it is indistinguishable from
/// an absent key — and skipped, not fatal: `{"item": null, "match": "beta"}`
/// falls through to `match`, as the Python `for`/`continue` does.
fn item(a: &Value, fields: &[&str]) -> Option<String> {
    fields
        .iter()
        .find_map(|f| a.get(f).filter(|v| !matches!(v, Value::Null)))
        .map(json::py_str)
}

// --------------------------------------------------------------------------
// JSON to the typed arguments
// --------------------------------------------------------------------------
// These validate nothing. Everything refusable has already been refused by
// `args`; what is left is reshaping, and any shape these cannot reshape is one
// `args` should have caught — so the fallthrough arms are unreachable in
// practice and chosen to be harmless rather than clever.

/// `args::address` has already unstrung the value, stripped quotes from its
/// keys, and refused every shape but a string or an object. The two *fields*
/// are deliberately not checked here — `resolve_table` does that, because that
/// is where the oracle does it and the order is observable.
///
/// Public because `table-get` is not an op and so has no entry in the match
/// above: a front end reaching `render_table_get` has to reshape the address
/// itself, and reshaping it a second way is how the read path and the write
/// path come to disagree about what `{"ordinal": "0"}` addresses.
pub fn to_address(v: Option<Value>) -> TableAddress {
    match v {
        None | Some(Value::Null) => TableAddress::none(),
        // A bare string is shorthand for `{"heading": ...}` (§6.2).
        Some(Value::Str(h)) => TableAddress {
            heading: Some(Value::Str(h)),
            ordinal: None,
        },
        Some(obj) => TableAddress {
            heading: obj.get("heading").cloned(),
            ordinal: obj.get("ordinal").cloned(),
        },
    }
}

/// The list family's counterpart to [`to_address`], and identical in shape: a
/// bare string is `{"heading": ...}`, and the two fields go through unexamined
/// because `resolve_list` is where the oracle looks at them.
fn to_list_address(v: Option<Value>) -> ListAddress {
    match v {
        None | Some(Value::Null) => ListAddress::none(),
        Some(Value::Str(h)) => ListAddress {
            heading: Some(Value::Str(h)),
            ordinal: None,
        },
        Some(obj) => ListAddress {
            heading: obj.get("heading").cloned(),
            ordinal: obj.get("ordinal").cloned(),
        },
    }
}

/// The section family's counterpart, and the one place the three families
/// differ: a bare string is `{"path": ...}`, not `{"heading": ...}`. Sections
/// are addressed by a path through the outline, and `resolve_section` reads
/// `path` first and falls back to `heading`, so the shorthand has to land on the
/// field that carries the separator.
fn to_section_address(v: Option<Value>) -> SectionAddress {
    section_address_fields(v.as_ref())
}

/// `args::values` refuses only a *string* that is not an encoded object or
/// array. Everything else it lets past, so anything that is not one of the two
/// row shapes has to survive as itself: `Values::Other` carries it to the op,
/// which is where the oracle decides between "a row is required" and "`values`
/// must be an object … or an ordered array of N values". Absent becomes
/// `Other(Null)` — falsy, so it takes the first of those two.
fn to_values(v: Option<Value>) -> Values {
    match v {
        Some(Value::Array(items)) => Values::Ordered(items),
        Some(Value::Object(pairs)) => Values::Named(pairs),
        Some(other) => Values::Other(other),
        None => Values::Other(Value::Null),
    }
}

/// Insertion order is preserved, because it decides which selector's refusal a
/// model sees first. The per-value cell checks belong to `resolve_row`, which is
/// where the oracle does them.
fn to_where(v: Option<Value>) -> Vec<(String, Value)> {
    match v {
        Some(Value::Object(pairs)) => pairs,
        // `args::check_where` has already refused every non-object; an empty
        // selector is refused by `resolve_row`, not here.
        _ => Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DOC: &str =
        "# Parts\n\n| Component | Status | Owner |\n| --- | --- | --- |\n| widget | ok | peter |\n";

    fn obj(pairs: &[(&str, Value)]) -> Value {
        Value::Object(
            pairs
                .iter()
                .map(|(k, v)| (k.to_string(), v.clone()))
                .collect(),
        )
    }
    fn s(v: &str) -> Value {
        Value::Str(v.to_string())
    }

    #[test]
    fn unknown_op_names_what_exists() {
        let e = apply_op(DOC, "table-sort", None).unwrap_err();
        assert_eq!(
            e.message(),
            "unknown operation \"table-sort\". Valid: table-add-row, table-update-cell, \
             table-delete-row, table-realign, list-add-item, list-remove-item, list-set-checked, \
             section-append, section-replace-body, section-insert, section-delete, \
             section-rename, section-set-level, frontmatter-set, frontmatter-delete"
        );
    }

    #[test]
    fn non_object_args_refuse_before_anything_else() {
        let e = apply_op(DOC, "table-add-row", Some(&s("widget"))).unwrap_err();
        assert!(e
            .message()
            .starts_with("arguments for `table-add-row` must be an object"));
    }

    #[test]
    fn add_row_appends() {
        let out = apply_op(
            DOC,
            "table-add-row",
            Some(&obj(&[("values", obj(&[("Component", s("gadget"))]))])),
        )
        .unwrap();
        assert!(out.ends_with("| gadget |  |  |\n"), "{out:?}");
    }

    /// The ordering the module exists to hold: a malformed `values` outranks a
    /// table that does not exist, because in the oracle it is a lambda argument
    /// and the table lookup is in the body.
    ///
    /// It has to be a *string* that is not an encoded object or array, which is
    /// the only thing the extraction layer refuses. A bare `7` gets past it and
    /// is refused inside the op, i.e. after the table — asserted below, because
    /// the first draft of this test assumed otherwise and the oracle disagreed.
    #[test]
    fn values_outranks_a_missing_table() {
        let e = apply_op(
            DOC,
            "table-add-row",
            Some(&obj(&[
                ("table", s("Nonexistent")),
                ("values", s("not json")),
            ])),
        )
        .unwrap_err();
        assert!(
            e.message().starts_with("`values` arrived as a string"),
            "{}",
            e.message()
        );
    }

    /// The three ways `values` can fail to be a row, which are three different
    /// repairs and must stay three different sentences.
    #[test]
    fn a_values_that_is_neither_shape() {
        let msg = |v: Value| {
            apply_op(DOC, "table-add-row", Some(&obj(&[("values", v)])))
                .unwrap_err()
                .message()
                .to_string()
        };
        // Truthy but shapeless: the model sent something, just not a row.
        assert!(
            msg(Value::Int(7)).starts_with(
                "`values` must be an object keyed by column name, or an ordered array of 3 values."
            ),
            "{}",
            msg(Value::Int(7))
        );
        // Falsy: Python's `if not supplied` fires first, and the model is told
        // to send a row rather than to reshape the one it sent.
        assert!(
            msg(Value::Int(0)).starts_with("a row is required"),
            "{}",
            msg(Value::Int(0))
        );
        assert!(msg(Value::Null).starts_with("a row is required"));
        // Wrong length is its own refusal, and says the count. It names
        // `values` — the argument the shipping schema declares — and not `row`,
        // which it used to name and which this crate refuses.
        assert!(msg(Value::Array(vec![s("a")]))
            .starts_with("`values` is an array of 1, but the table has 3 columns"));
    }

    /// And the converse: `position` is raw, so a missing table outranks it.
    #[test]
    fn a_missing_table_outranks_position() {
        let e = apply_op(
            DOC,
            "table-add-row",
            Some(&obj(&[
                ("table", s("Nonexistent")),
                ("values", Value::Array(vec![s("a"), s("b"), s("c")])),
                ("position", s("middle")),
            ])),
        )
        .unwrap_err();
        assert!(e.message().starts_with("no table under"), "{}", e.message());
    }

    /// F-args, the defect this dispatch was written after: a missing `value` is
    /// a refusal, not the literal string "None" written into the cell.
    #[test]
    fn a_missing_value_is_a_refusal() {
        let e = apply_op(
            DOC,
            "table-update-cell",
            Some(&obj(&[
                ("where", obj(&[("Component", s("widget"))])),
                ("column", s("Status")),
            ])),
        )
        .unwrap_err();
        assert!(
            e.message().starts_with("`value` is required"),
            "{}",
            e.message()
        );
    }

    /// ...and the row is resolved first, so a bad value on a row that is not
    /// there reports the row.
    #[test]
    fn the_row_outranks_the_value() {
        let e = apply_op(
            DOC,
            "table-update-cell",
            Some(&obj(&[
                ("where", obj(&[("Component", s("nope"))])),
                ("column", s("Status")),
            ])),
        )
        .unwrap_err();
        assert!(e.message().starts_with("no row where"), "{}", e.message());
    }

    /// §6.2's rejected second argument, asserted as absent rather than left to
    /// be rediscovered: `row` is not part of the shipping schema.
    #[test]
    fn the_legacy_row_alias_is_not_accepted() {
        let e = apply_op(
            DOC,
            "table-add-row",
            Some(&obj(&[("row", Value::Array(vec![s("a"), s("b"), s("c")]))])),
        )
        .unwrap_err();
        assert!(
            e.message().starts_with("a row is required"),
            "{}",
            e.message()
        );
    }
}
