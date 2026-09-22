//! The tool schemas the front end publishes.
//!
//! Generated from `bench/armb.py`, not written: REQUIREMENTS.md section 6 makes a
//! tool description a requirement surface -- "Changes to the description are
//! behavioural changes and belong in the benchmark, not in a docs commit". Each
//! of these five is the scheme that *won* its comparison, copied byte for byte
//! from the file the comparison ran in, so the schema a model is shown in
//! production is the schema the number was measured on.
//!
//! | tool | scheme | what it settled |
//! |---|---|---|
//! | `table_edit` | `scheme_f` | B6/B7: the description, not the type constraint, is what carries the address. `values` is untyped -- `oneOf` measured inert across 60/60 byte-identical calls, and is unevenly supported by MCP clients. F-realign added the fourth action: the six existing tasks are 60/60 both ways, trial for trial, and never reach for it. |
//! | `list_edit` | `list_g` | L2/L3: the selector renamed `item` -> `match`, because `item` and `text` are synonyms and the model wrote the payload into the selector 39 times. 91%, against `list_f`'s 61%. |
//! | `section_edit` | `section_g_hpath` | S15: the section address is spelled `heading`, leaving `path` to mean the file. The collision was costing calls that were otherwise correct. |
//! | `frontmatter_edit` | `front_p` | F-front: `key` names the dotted path and says to copy it from the summary, against `front_naive`'s bare "Which frontmatter key to edit." 105/110. The headline p = 0.0156 is **not** quotable -- 4 of its 7 wins are one task no scheme can answer, and dropping it leaves +3 -0, p = 0.25. |
//! | `table_get` | `table_read_g` | F-read: the row selector is `filter`, *"narrows the rows"*, against `where` described as it is on the write ops. 58/60 = 96.7% against 45.0%, and the naive spelling returned the whole table 33 times. |
//!
//! `bench/schematest.py` asserts this file still equals those five entries. It
//! is the only thing standing between the shipped schema and the measured one,
//! and it fails loudly rather than drifting quietly.
//!
//! **The set was measured, not just its members** (FINDINGS, F-compose). Every
//! row above is a single-tool scheme, and until F-compose nothing had ever shown
//! a model more than three tools at once. Five against three is 6-3 of 310 paired
//! trials, p = 0.51 -- publishing the fourth and fifth tools costs nothing
//! detectable. What does cost is the step this file took long ago: three tools
//! against one is 11-1, p = 0.0063, about three and a fifth points, and it is
//! priced here for the first time rather than fixed. So the contract has two
//! halves now. Each tool is the scheme that won its comparison, *and* the set of
//! five is a composition that has been run end to end. `schematest.py` guards
//! both: `ADOPTED` for the first half, `check_composition` for the second,
//! against `bench/compose_5.measured.json`.
//!
//! **And the set has drifted once, by one line.** F-realign published a fourth
//! `table_edit` action, and `compose_5` holds `scheme_f`'s tool object by
//! reference -- so the shipped composition gained `action=realign` the day the
//! ship landed, while the arms that produced 6-3 of 310 ran three actions. Every
//! per-tool check still passed, because both sides moved together; the set check
//! exists because of this, and was written after it. The difference is one
//! description line and one enum entry, on the family F-realign measured hardest:
//! the six existing table tasks are 60/60 in both worlds, trial for trial, and
//! reached for the new action zero times in 62 treatment calls. So the 6-3 is
//! carried forward rather than re-run, and it is carried forward knowingly --
//! `COMPOSITION_DRIFT` lists the two paths and what is claimed about them, and a
//! *second* change to either is reported as unlisted rather than inheriting this
//! excuse.
//!
//! **And what the table's numbers are not.** Every rate in it -- 96.7%, 105/110,
//! 91% -- was measured with that tool alone in the request, and no tool is ever
//! used that way here. The shipped condition is five tools at once, so the rate
//! a shipped tool achieves is `compose_5`'s and not the column above. The 3.2
//! points between them are the price of being a multi-family product, and they
//! are priced and accepted rather than pending: F-compose named three mechanisms,
//! F-terminal removed one by re-grading, F-anchor showed the second is k = 5
//! against a floor of 6 -- real in the calls and unresolvable by any paired run
//! -- and F-reach ran the arm for the third. It did not pay. The treatment halved
//! the defect it targeted (address-less calls 16 -> 7 of 298) and moved the
//! outcome not at all (14-9, p = 0.4049), while making `action=delete` read as
//! one argument from callable and doubling silent corruption. So the contract
//! claims three things and disclaims a fourth: each tool's text is the text that
//! won its comparison, the set of five has been run end to end *modulo the one
//! listed line*, the cost of composing them is 3.2 points and is accepted -- and
//! the table's rates are the comparisons that *selected* each text, not the rate
//! that text achieves as shipped. Quoting one of them as a product number is the
//! misreading this file invites, and the disclaimer is here because nothing can
//! guard against it.
//!
//! Three warts are preserved on purpose, because the text is what was measured
//! and tidying it is a schema change that belongs in a benchmark run:
//!
//!   * `values`'s description says "in column order" twice, an artifact of how
//!     `scheme_f` concatenates its two halves. It is in the text 60/60 was
//!     measured with.
//!   * `table_get`'s `table` says "Which table to **edit**", copied from
//!     `table_edit` into a tool that cannot edit anything. The address itself
//!     resolved 60/60 in the pool that adopted it, and this one is **permanent**
//!     rather than pending (FINDINGS, F-wart): the arm that would fix it was
//!     priced and its gain is bounded at zero, while the misroute it is accused
//!     of is 0 of 120 composed trials. A wart no benchmark run can settle still
//!     ships as measured -- that is the contract's cost, paid on purpose.
//!   * `frontmatter_edit`'s description ends in a newline and the others do not.

/// The five tools, as a JSON array of OpenAI function definitions.
pub const SCHEMAS: &str = r#"[
  {
    "name": "table_edit",
    "description": "Edit a markdown table. Column widths and alignment are maintained automatically; you do not need to pad anything.\n`table` says WHICH table in the file and is required for every action. Copy it from the table list in the request; the last heading segment on its own is enough (e.g. \"All four forms\").\n  action=add-row      requires `table`, `values`\n  action=update-cell  requires `table`, `where`, `column`, `value`\n  action=delete-row   requires `table`, `where`\n  action=realign      requires `table`. Re-pads a table whose columns were left ragged by some other editor. Changes no cell text.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "File to edit."
        },
        "action": {
          "type": "string",
          "description": "The operation to perform.",
          "enum": [
            "add-row",
            "update-cell",
            "delete-row",
            "realign"
          ]
        },
        "table": {
          "type": "object",
          "description": "Which table to edit, addressed by content. Never by line number.",
          "properties": {
            "heading": {
              "type": "string",
              "description": "The heading the table sits under. Either the last heading (e.g. \"Environments\") or the full path (e.g. \"Deployment > Environments\")."
            },
            "ordinal": {
              "type": "integer",
              "description": "0-based index among tables under that same heading, in document order. Required only when more than one table shares the heading. The table list shows the ordinal of each."
            }
          },
          "required": [
            "heading"
          ]
        },
        "values": {
          "description": "The new row. Either an object keyed by column name, or an array of values in column order. The row's values in column order, one per column, all columns required. For the table Default | Left | Center | Right, the values i, j, k, l are [\"i\", \"j\", \"k\", \"l\"]. Use this when the request lists values in order rather than naming a column for each."
        },
        "where": {
          "type": "object",
          "description": "Selects one existing row by its cell values, as {\"ColumnName\": \"cell value\"}. Must match exactly one row. Example: {\"Host\": \"stage-1\"}.",
          "additionalProperties": {
            "type": "string"
          }
        },
        "column": {
          "type": "string",
          "description": "For update-cell: the column whose cell changes."
        },
        "value": {
          "type": "string",
          "description": "For update-cell: the new cell value."
        },
        "position": {
          "type": "string",
          "description": "Where to insert: \"end\" (default) or \"start\".",
          "enum": [
            "end",
            "start"
          ]
        }
      },
      "required": [
        "path",
        "action",
        "table"
      ]
    }
  },
  {
    "name": "list_edit",
    "description": "Edit a markdown list. Marker character, marker delimiter, indentation, blank-line spacing and ordered-list numbering are all maintained automatically; you do not need to format anything.\n`list` says WHICH list in the file and is required for every action. Copy it from the list summary in the request; the last heading segment on its own is enough (e.g. \"All ones\").\n  action=add-item     requires `list`, `text`\n  action=remove-item  requires `list`, `match`\n  action=set-checked  requires `list`, `match`, `checked`",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "File to edit."
        },
        "action": {
          "type": "string",
          "description": "The operation to perform.",
          "enum": [
            "add-item",
            "remove-item",
            "set-checked"
          ]
        },
        "list": {
          "type": "object",
          "description": "Which list to edit, addressed by content. Never by line number.",
          "properties": {
            "heading": {
              "type": "string",
              "description": "The heading the list sits under. Either the last heading (e.g. \"All ones\") or the full path (e.g. \"Ordered list numbering > All ones\")."
            },
            "ordinal": {
              "type": "integer",
              "description": "0-based index among lists under that same heading, in document order. Required only when more than one list shares the heading. The list summary shows the ordinal of each."
            }
          },
          "required": [
            "heading"
          ]
        },
        "text": {
          "type": "string",
          "description": "For add-item: the content of the new item. Text only -- no marker, no number, no checkbox, no indentation."
        },
        "after": {
          "type": "string",
          "description": "For add-item: put the new item immediately after this existing item. The new item copies that item's indentation and marker, so this is also how an item is added inside a nested list."
        },
        "position": {
          "type": "string",
          "description": "For add-item, when `after` is not given: \"end\" (default) or \"start\".",
          "enum": [
            "end",
            "start"
          ]
        },
        "checked": {
          "type": "boolean",
          "description": "For set-checked: true to tick the box, false to untick it."
        },
        "match": {
          "type": "string",
          "description": "For remove-item and set-checked: selects an existing item by its text. Must match exactly one item."
        }
      },
      "required": [
        "path",
        "action",
        "list"
      ]
    }
  },
  {
    "name": "section_edit",
    "description": "Edit a markdown document's sections. Heading syntax, heading level, blank-line spacing and the boundaries of each section are all maintained automatically; you do not need to format anything or count levels.\n  action=append        requires `text`. Adds to the section's existing text, keeping it. Cannot create a section.\n  action=replace-body  requires `text`. DISCARDS the section's existing text; also requires `overwrite`=true if it has any.\n  action=insert        requires `position`, `new_heading`. The only action that creates a section; use position=last-child for a new subsection.\n  action=delete        requires nothing else -- takes the subtree with it\n  action=rename        requires `new_heading`\n  action=set-level     requires `level`",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "File to edit."
        },
        "action": {
          "type": "string",
          "description": "The operation to perform.",
          "enum": [
            "append",
            "replace-body",
            "insert",
            "delete",
            "rename",
            "set-level"
          ]
        },
        "section": {
          "type": "object",
          "description": "Which section to act on, addressed by heading path. Never by line number.",
          "properties": {
            "heading": {
              "type": "string",
              "description": "The heading path, from the outline. Either the last segment (e.g. \"macOS\") or the full path (e.g. \"Install > macOS\"). Use the full path when the last segment appears more than once."
            },
            "ordinal": {
              "type": "integer",
              "description": "0-based index among sections that share an identical path, in document order. Required only for those; the outline marks them DUPLICATE PATH."
            }
          },
          "required": [
            "heading"
          ]
        },
        "text": {
          "type": "string",
          "description": "For append and replace-body: the markdown to put in the section's own body -- the part above its first subsection. Not its heading."
        },
        "body": {
          "type": "string",
          "description": "For insert: the new section's body. Optional."
        },
        "position": {
          "type": "string",
          "description": "For insert: where the new section goes relative to `section`. before/after make it a sibling; first-child/last-child make it a subsection. after and last-child go past the whole subtree.",
          "enum": [
            "before",
            "after",
            "first-child",
            "last-child"
          ]
        },
        "level": {
          "type": "integer",
          "description": "For set-level: the heading level to move to, 1 to 6."
        },
        "subtree": {
          "type": "boolean",
          "description": "For set-level: move the subsections too. Default true. False reparents them, which is rarely what is wanted."
        },
        "new_heading": {
          "type": "string",
          "description": "For rename: the new heading text. For insert: the heading text of the new section. Text only -- no `#` marks; the level is worked out from `section` and `position`."
        },
        "overwrite": {
          "type": "boolean",
          "description": "For replace-body: confirms that discarding the section's existing text is intended. Required when it has any."
        }
      },
      "required": [
        "path",
        "action",
        "section"
      ]
    }
  },
  {
    "name": "frontmatter_edit",
    "description": "Edit the YAML frontmatter of a markdown file -- the block between `---` lines at the very top. This does not touch the document below it.\n  action=set     requires `key`, `value`. Creates the key if it is not there, and creates the whole block if the file has none.\n  action=delete  requires `key`. Removes the key and everything under it.\n",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "File to edit."
        },
        "action": {
          "type": "string",
          "enum": [
            "set",
            "delete"
          ],
          "description": "Which edit to make."
        },
        "key": {
          "type": "string",
          "description": "Which frontmatter key to edit, as a full path from the top of the block. Copy it from the frontmatter summary in the request. A nested key is written with dots -- \"build.jobs\", not \"jobs\" -- and an item in a sequence is indexed from 0 -- \"authors[0].role\"."
        },
        "value": {
          "description": "For set: the new value, as one scalar. Send null to empty the key without removing it. The tool decides YAML quoting; send the value, not a quoted spelling of it."
        }
      },
      "required": [
        "path",
        "action",
        "key"
      ]
    }
  },
  {
    "name": "table_get",
    "description": "Read rows out of a markdown table. This does not change the file.\n`table` says WHICH table and is required. Copy it from the table list in the request; the last heading segment on its own is enough (e.g. \"Packages\").\n`filter` narrows the rows. Leave it out to get the whole table.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "File to read."
        },
        "table": {
          "type": "object",
          "description": "Which table to edit, addressed by content. Never by line number.",
          "properties": {
            "heading": {
              "type": "string",
              "description": "The heading the table sits under. Either the last heading (e.g. \"Environments\") or the full path (e.g. \"Deployment > Environments\")."
            },
            "ordinal": {
              "type": "integer",
              "description": "0-based index among tables under that same heading, in document order. Required only when more than one table shares the heading. The table list shows the ordinal of each."
            }
          },
          "required": [
            "heading"
          ]
        },
        "filter": {
          "type": "object",
          "description": "Keeps only the rows whose cells match, as {\"ColumnName\": \"cell value\"}. Several columns are ANDed. Any number of rows may match, including none -- matching nothing is an answer, not an error. Example: {\"Priority\": \"high\"}.",
          "additionalProperties": {
            "type": "string"
          }
        }
      },
      "required": [
        "path",
        "table"
      ]
    }
  }
]"#;

/// Optional composition for models that benefit from one operation per tool
/// and from inspecting exact structure before editing.  Unlike [`SCHEMAS`],
/// this is explicitly an evaluation candidate rather than a measured default.
/// Keeping it behind `--profile safe-small` prevents a promising compatibility
/// profile from silently rewriting the product condition whose results are
/// recorded in `bench/FINDINGS.md`.
const SAFE_SMALL_OBJECTS: &[(&str, &str)] = &[
    (
        "md_tables",
        r#"{"name":"md_tables","description":"List markdown tables and their exact headings, ordinals, columns, and row counts. Inspect before a table edit.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Markdown file to inspect."}},"required":["path"]}}"#,
    ),
    (
        "table_add_row",
        r#"{"name":"table_add_row","description":"Add one row to a markdown table. Inspect with md_tables first and copy the table address and column names exactly.","parameters":{"type":"object","properties":{"path":{"type":"string"},"table":{"type":"object","properties":{"heading":{"type":"string"},"ordinal":{"type":"integer"}},"required":["heading"]},"values":{"description":"Named row object, or scalar values in column order."},"position":{"type":"string","enum":["end","start"]}},"required":["path","table","values"]}}"#,
    ),
    (
        "table_update_cell",
        r#"{"name":"table_update_cell","description":"Update one cell in exactly one markdown table row. Copy table and column spellings from structural reads.","parameters":{"type":"object","properties":{"path":{"type":"string"},"table":{"type":"object","properties":{"heading":{"type":"string"},"ordinal":{"type":"integer"}},"required":["heading"]},"where":{"type":"object","additionalProperties":{"type":"string"}},"column":{"type":"string"},"value":{"type":"string"}},"required":["path","table","where","column","value"]}}"#,
    ),
    (
        "md_lists",
        r#"{"name":"md_lists","description":"List markdown lists and their exact headings, ordinals, kinds, nesting levels, and item counts. Use list_get to inspect actual item text.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}"#,
    ),
    (
        "list_get",
        r#"{"name":"list_get","description":"Read one markdown list's exact item text, depth, parent index, and checkbox state. Use this before list_add_item when placement depends on an existing item.","parameters":{"type":"object","properties":{"path":{"type":"string"},"list":{"type":"object","properties":{"heading":{"type":"string"},"ordinal":{"type":"integer"}},"required":["heading"]}},"required":["path","list"]}}"#,
    ),
    (
        "list_add_item",
        r#"{"name":"list_add_item","description":"Add one markdown list item. Copy an exact existing item from list_get into after when nesting or placement matters.","parameters":{"type":"object","properties":{"path":{"type":"string"},"list":{"type":"object","properties":{"heading":{"type":"string"},"ordinal":{"type":"integer"}},"required":["heading"]},"text":{"type":"string"},"after":{"type":"string"},"position":{"type":"string","enum":["end","start"]},"checked":{"type":"boolean"}},"required":["path","list","text"]}}"#,
    ),
    (
        "md_outline",
        r#"{"name":"md_outline","description":"Read markdown heading paths, levels, ordinals, body presence, and descendant counts before a section edit.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}"#,
    ),
    (
        "section_insert",
        r#"{"name":"section_insert","description":"Insert one new markdown section. parent is the existing section used as the placement anchor; use position last-child for a subsection.","parameters":{"type":"object","properties":{"path":{"type":"string"},"parent":{"type":"object","properties":{"heading":{"type":"string"},"ordinal":{"type":"integer"}},"required":["heading"]},"position":{"type":"string","enum":["before","after","first-child","last-child"]},"new_heading":{"type":"string"},"body":{"type":"string"}},"required":["path","parent","position","new_heading"]}}"#,
    ),
    (
        "section_append",
        r#"{"name":"section_append","description":"Append text to one existing markdown section while preserving its current body and subsections.","parameters":{"type":"object","properties":{"path":{"type":"string"},"section":{"type":"object","properties":{"heading":{"type":"string"},"ordinal":{"type":"integer"}},"required":["heading"]},"text":{"type":"string"}},"required":["path","section","text"]}}"#,
    ),
    (
        "frontmatter_get",
        r#"{"name":"frontmatter_get","description":"Read flattened, copyable frontmatter paths with types and values. Inspect before setting a nested key or sequence item.","parameters":{"type":"object","properties":{"path":{"type":"string"},"key":{"type":"string","description":"Optional dotted path or indexed subtree to narrow the read."}},"required":["path"]}}"#,
    ),
    (
        "frontmatter_set",
        r#"{"name":"frontmatter_set","description":"Set one exact frontmatter path. Copy nested and indexed paths from frontmatter_get; do not guess a parent path.","parameters":{"type":"object","properties":{"path":{"type":"string"},"key":{"type":"string"},"value":{}},"required":["path","key","value"]}}"#,
    ),
];

/// The tool names, in the order `SCHEMAS` lists them.
#[allow(dead_code)]
pub const TOOLS: &[&str] = &[
    "table_edit",
    "list_edit",
    "section_edit",
    "frontmatter_edit",
    "table_get",
];

pub const SAFE_SMALL_TOOLS: &[&str] = &[
    "md_tables",
    "table_get",
    "table_add_row",
    "table_update_cell",
    "md_lists",
    "list_get",
    "list_add_item",
    "md_outline",
    "section_insert",
    "section_append",
    "frontmatter_get",
    "frontmatter_set",
];

pub const ALL_TOOLS: &[&str] = &[
    "table_edit",
    "list_edit",
    "section_edit",
    "frontmatter_edit",
    "table_get",
    "md_tables",
    "table_add_row",
    "table_update_cell",
    "md_lists",
    "list_get",
    "list_add_item",
    "md_outline",
    "section_insert",
    "section_append",
    "frontmatter_get",
    "frontmatter_set",
];

pub fn profile(name: &str) -> String {
    if name == "measured" {
        return SCHEMAS.to_string();
    }
    let objects: Vec<String> = SAFE_SMALL_TOOLS
        .iter()
        .filter_map(|tool| one_in("safe-small", tool))
        .collect();
    format!("[\n{}\n]", objects.join(",\n"))
}

pub fn one_in(profile: &str, name: &str) -> Option<String> {
    if profile == "measured" {
        return one(name);
    }
    if name == "table_get" {
        return one(name);
    }
    SAFE_SMALL_OBJECTS
        .iter()
        .find(|(tool, _)| *tool == name)
        .map(|(_, schema)| (*schema).to_string())
}

/// One tool's definition, as the substring of [`SCHEMAS`] that is its object.
///
/// A hand-rolled slice rather than a parse: this crate has a JSON *reader* in
/// `incise_core::json` but no writer for arbitrary values, and re-serializing
/// would risk handing out a schema that differs from the measured one by a
/// space. The text is generated and constant, so its shape is known.
pub fn one(name: &str) -> Option<String> {
    let needle = format!("\"name\": \"{name}\"");
    let at = SCHEMAS.find(&needle)?;
    let start = SCHEMAS[..at].rfind("\n  {")? + 3;
    let end = match SCHEMAS[start..].find("\n  },") {
        Some(i) => start + i + 4,
        None => SCHEMAS.rfind("\n  }")? + 4,
    };
    // Re-indent from inside the array to the top level.
    Some(
        SCHEMAS[start..end]
            .lines()
            .map(|l| l.strip_prefix("  ").unwrap_or(l))
            .collect::<Vec<_>>()
            .join("\n"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_published_tool_can_be_sliced_out_on_its_own() {
        for name in TOOLS {
            let got = one(name).unwrap_or_else(|| panic!("{name} not sliceable"));
            assert!(got.starts_with('{') && got.ends_with('}'), "{name}: {got}");
            assert!(got.contains(&format!("\"name\": \"{name}\"")), "{name}");
        }
        assert!(one("table_delete").is_none());
    }

    #[test]
    fn the_section_address_is_spelled_heading_and_path_is_the_file() {
        // S15. The one decision the core cannot enforce, because `resolve_section`
        // accepts either spelling -- so if it is lost, it is lost silently.
        let section = one("section_edit").unwrap();
        let at = section.find("\"section\"").unwrap();
        assert!(
            section[at..].contains("\"heading\""),
            "section address lost `heading`"
        );
        assert!(
            section.contains("\"description\": \"File to edit.\""),
            "`path` stopped meaning the file"
        );
    }

    #[test]
    fn safe_small_is_opt_in_and_contains_only_narrow_writes() {
        let parsed = incise_core::json::parse(&profile("safe-small")).unwrap();
        let names: Vec<&str> = match parsed {
            incise_core::json::Value::Array(ref tools) => tools
                .iter()
                .map(|tool| tool.get("name").unwrap().as_str().unwrap())
                .collect(),
            _ => panic!("safe-small profile is not an array"),
        };
        assert_eq!(names, SAFE_SMALL_TOOLS);
        for excluded in [
            "section_edit",
            "section_delete",
            "section_replace_body",
            "frontmatter_edit",
            "frontmatter_delete",
        ] {
            assert!(
                !names.contains(&excluded),
                "unsafe generic tool {excluded} leaked"
            );
        }
        assert_eq!(profile("measured"), SCHEMAS);
    }
}
