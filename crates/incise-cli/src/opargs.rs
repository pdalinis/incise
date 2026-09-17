//! Command-line flags to the JSON argument object `apply_op` expects.
//!
//! Everything here is reshaping. Nothing is validated: the order arguments are
//! checked in is part of the contract (`ops/dispatch.rs`), and a front end that
//! rejects `--level 9` early produces a different refusal for the same call than
//! the one Arm B measured recovery against. The only errors raised here are ones
//! the core can never see — argv that is not JSON at all, a `K=V` pair with no
//! `=` — which are usage faults, not refusals.

use incise_core::json::{self, Value};

/// How one flag's argv text becomes one JSON value.
#[derive(Clone, Copy, PartialEq)]
pub enum Kind {
    /// A JSON string. The default, and what every address and every payload is.
    Str,
    /// A JSON integer.
    Int,
    /// A JSON boolean, spelled `true` or `false` on the command line.
    Bool,
    /// A JSON `true` when the flag is present, and absent otherwise.
    Present,
    /// Repeatable `key=value`, collected into an object of strings.
    Pairs,
    /// A JSON literal, parsed as-is. The escape hatch for shapes the flat
    /// spellings cannot reach — an ordered row, a subsection tree.
    Json,
}

pub struct Flag {
    pub long: &'static str,
    /// The key this flag writes into the argument object. Several flags may
    /// share one key when they differ only in how the value is spelled.
    pub key: &'static str,
    pub kind: Kind,
    pub value_name: &'static str,
    pub help: &'static str,
}

/// The flag set, in the order the keys are emitted.
///
/// Every op subcommand carries all of it. Which keys an op actually reads is the
/// core's business, and a CLI that offered `--level` only on `section-set-level`
/// would be deciding that question a second time, in a place no test looks.
///
/// Emission order is fixed and declared here because `json::Value::Object` is a
/// `Vec` rather than a map — Python dictionaries preserve insertion order and
/// `repr` prints them in it, so the order a refusal quotes arguments back in is
/// observable behaviour.
pub const FLAGS: &[Flag] = &[
    Flag {
        long: "table",
        key: "table",
        kind: Kind::Str,
        value_name: "HEADING",
        help: "Which table, by the heading it sits under",
    },
    Flag {
        long: "list",
        key: "list",
        kind: Kind::Str,
        value_name: "HEADING",
        help: "Which list, by the heading it sits under",
    },
    Flag {
        long: "section",
        key: "section",
        kind: Kind::Str,
        value_name: "PATH",
        help: "Which section, by heading path (e.g. \"Install > macOS\")",
    },
    Flag {
        long: "values",
        key: "values",
        kind: Kind::Pairs,
        value_name: "COLUMN=VALUE",
        help: "A row, named by column. Repeatable",
    },
    Flag {
        long: "values-json",
        key: "values",
        kind: Kind::Json,
        value_name: "JSON",
        help: "A row as a JSON literal -- use for an ordered array",
    },
    Flag {
        long: "where",
        key: "where",
        kind: Kind::Pairs,
        value_name: "COLUMN=VALUE",
        help: "Selects one existing row by its cells. Repeatable",
    },
    Flag {
        long: "column",
        key: "column",
        kind: Kind::Str,
        value_name: "NAME",
        help: "The column whose cell changes",
    },
    Flag {
        long: "value",
        key: "value",
        kind: Kind::Str,
        value_name: "TEXT",
        help: "The new cell value",
    },
    Flag {
        long: "position",
        key: "position",
        kind: Kind::Str,
        value_name: "WHERE",
        help: "start/end for rows and items; before/after/first-child/last-child for sections",
    },
    Flag {
        long: "text",
        key: "text",
        kind: Kind::Str,
        value_name: "TEXT",
        help: "The new item's content, or a section's body",
    },
    Flag {
        long: "match",
        key: "match",
        kind: Kind::Str,
        value_name: "TEXT",
        help: "Selects one existing list item by its text",
    },
    Flag {
        long: "after",
        key: "after",
        kind: Kind::Str,
        value_name: "TEXT",
        help: "Put the new item immediately after this existing one",
    },
    Flag {
        long: "checked",
        key: "checked",
        kind: Kind::Bool,
        value_name: "BOOL",
        help: "true to tick the box, false to untick it",
    },
    Flag {
        long: "body",
        key: "body",
        kind: Kind::Str,
        value_name: "TEXT",
        help: "The new section's body",
    },
    Flag {
        long: "new-heading",
        key: "new_heading",
        kind: Kind::Str,
        value_name: "TEXT",
        help: "The new heading text, without `#` marks",
    },
    Flag {
        long: "level",
        key: "level",
        kind: Kind::Int,
        value_name: "N",
        help: "The heading level to move to, 1 to 6",
    },
    Flag {
        long: "subtree",
        key: "subtree",
        kind: Kind::Bool,
        value_name: "BOOL",
        help: "Move the subsections too. Default true",
    },
    Flag {
        long: "children",
        key: "children",
        kind: Kind::Json,
        value_name: "JSON",
        help: "Subsections of the new section, as a JSON array",
    },
    Flag {
        long: "overwrite",
        key: "overwrite",
        kind: Kind::Present,
        value_name: "",
        help: "Confirm that discarding a section's existing text is intended",
    },
    // Frontmatter last, the order the families were built in. `--value` above is
    // shared rather than duplicated: `frontmatter-set` takes a value in the same
    // sense `table-update-cell` does, and a `--front-value` would be a second
    // spelling of one key for the core to tell apart. A scalar is all this
    // spelling reaches -- a null, a number, a bool or a nested object needs
    // `--args`, which is the canonical spelling anyway.
    Flag {
        long: "key",
        key: "key",
        kind: Kind::Str,
        value_name: "PATH",
        help: "Which frontmatter key, by dotted path (e.g. \"build.jobs\")",
    },
];

/// The address flags, and the only ones `--ordinal` can attach to.
pub const ADDRESS_KEYS: &[&str] = &["table", "list", "section"];

/// A usage fault: argv the core will never be shown, because it never became a
/// JSON value at all.
pub struct Usage(pub String);

/// Build the argument object from the per-key flags.
///
/// `--ordinal` has no key of its own. An ordinal disambiguates *an address*, so
/// it nests inside whichever of `--table`/`--list`/`--section` was given, turning
/// the bare-string shorthand into the `{"heading": ..., "ordinal": n}` object the
/// published schema describes. Every family reads `heading`, including sections,
/// where `resolve_section` takes `path` first and falls back to it.
pub fn build(
    get_one: &dyn Fn(&str) -> Option<String>,
    get_many: &dyn Fn(&str) -> Option<Vec<String>>,
    is_present: &dyn Fn(&str) -> bool,
) -> Result<Value, Usage> {
    let mut pairs: Vec<(String, Value)> = Vec::new();

    for flag in FLAGS {
        let value = match flag.kind {
            Kind::Present => {
                if is_present(flag.long) {
                    Some(Value::Bool(true))
                } else {
                    None
                }
            }
            Kind::Pairs => match get_many(flag.long) {
                None => None,
                Some(items) => {
                    let mut inner = Vec::with_capacity(items.len());
                    for item in items {
                        let (k, v) = item.split_once('=').ok_or_else(|| {
                            Usage(format!(
                                "--{} takes KEY=VALUE, but got {:?}. Quote the whole pair: \
                                 --{} 'Column=some value'",
                                flag.long, item, flag.long
                            ))
                        })?;
                        inner.push((k.to_string(), Value::Str(v.to_string())));
                    }
                    Some(Value::Object(inner))
                }
            },
            Kind::Json => match get_one(flag.long) {
                None => None,
                Some(raw) => Some(json::parse(&raw).ok_or_else(|| {
                    Usage(format!("--{} is not valid JSON: {:?}", flag.long, raw))
                })?),
            },
            Kind::Int => match get_one(flag.long) {
                None => None,
                // clap has already refused anything that is not an integer.
                Some(raw) => Some(Value::Int(raw.parse::<i64>().map_err(|_| {
                    Usage(format!(
                        "--{} takes a whole number, but got {:?}",
                        flag.long, raw
                    ))
                })?)),
            },
            Kind::Bool => get_one(flag.long).map(|raw| Value::Bool(raw == "true")),
            Kind::Str => get_one(flag.long).map(Value::Str),
        };

        if let Some(v) = value {
            // Two flags may share a key (`--values` and `--values-json`); the
            // later one replaces the earlier rather than appending a duplicate
            // the core would never look at.
            match pairs.iter_mut().find(|(k, _)| k == flag.key) {
                Some(slot) => slot.1 = v,
                None => pairs.push((flag.key.to_string(), v)),
            }
        }
    }

    if let Some(raw) = get_one("ordinal") {
        let n = raw
            .parse::<i64>()
            .map_err(|_| Usage(format!("--ordinal takes a whole number, but got {raw:?}")))?;
        let slot = pairs
            .iter_mut()
            .find(|(k, _)| ADDRESS_KEYS.contains(&k.as_str()))
            .ok_or_else(|| {
                Usage(
                    "--ordinal says which of several things sharing a heading to act on, \
                     so it needs one of --table, --list or --section beside it."
                        .to_string(),
                )
            })?;
        let heading = std::mem::replace(&mut slot.1, Value::Null);
        slot.1 = Value::Object(vec![
            ("heading".to_string(), heading),
            ("ordinal".to_string(), Value::Int(n)),
        ]);
    }

    Ok(Value::Object(pairs))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn harness(
        ones: &[(&str, &str)],
        manys: &[(&str, &[&str])],
        present: &[&str],
    ) -> Result<Value, Usage> {
        let ones: HashMap<String, String> = ones
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        let manys: HashMap<String, Vec<String>> = manys
            .iter()
            .map(|(k, v)| (k.to_string(), v.iter().map(|s| s.to_string()).collect()))
            .collect();
        let present: Vec<String> = present.iter().map(|s| s.to_string()).collect();
        build(
            &|k| ones.get(k).cloned(),
            &|k| manys.get(k).cloned(),
            &|k| present.iter().any(|p| p == k),
        )
    }

    #[test]
    fn keys_come_out_in_the_declared_order_not_the_argv_order() {
        let got = harness(
            &[("value", "ok"), ("column", "Status"), ("table", "Parts")],
            &[],
            &[],
        )
        .ok()
        .unwrap();
        let keys: Vec<&str> = got
            .as_object()
            .unwrap()
            .iter()
            .map(|(k, _)| k.as_str())
            .collect();
        assert_eq!(keys, ["table", "column", "value"]);
    }

    #[test]
    fn an_ordinal_nests_into_whichever_address_is_there() {
        let got = harness(
            &[("section", "Install > macOS"), ("ordinal", "1")],
            &[],
            &[],
        )
        .ok()
        .unwrap();
        assert_eq!(
            got.get("section"),
            Some(&Value::Object(vec![
                (
                    "heading".to_string(),
                    Value::Str("Install > macOS".to_string())
                ),
                ("ordinal".to_string(), Value::Int(1)),
            ]))
        );
    }

    #[test]
    fn an_ordinal_with_nothing_to_qualify_is_a_usage_fault_not_a_refusal() {
        assert!(harness(&[("ordinal", "0")], &[], &[]).is_err());
    }

    #[test]
    fn values_json_reaches_the_ordered_shape_that_pairs_cannot() {
        let got = harness(&[("values-json", r#"["i", "j"]"#)], &[], &[])
            .ok()
            .unwrap();
        assert_eq!(
            got.get("values"),
            Some(&Value::Array(vec![
                Value::Str("i".to_string()),
                Value::Str("j".to_string())
            ]))
        );
    }

    #[test]
    fn a_pair_without_an_equals_says_how_to_quote_it() {
        let err = harness(&[], &[("where", &["Host stage-1"])], &[])
            .err()
            .unwrap();
        assert!(err.0.contains("KEY=VALUE"), "{}", err.0);
    }

    #[test]
    fn a_present_flag_is_true_and_an_absent_one_is_not_a_key() {
        let on = harness(&[], &[], &["overwrite"]).ok().unwrap();
        assert_eq!(on.get("overwrite"), Some(&Value::Bool(true)));
        let off = harness(&[], &[], &[]).ok().unwrap();
        assert_eq!(off.get("overwrite"), None);
    }
}
