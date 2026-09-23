//! The list op family — §6.4, the second one built (Tier 2b).
//!
//! Structurally the same bet as the table family: the model supplies *content*
//! and incise does the bookkeeping. What counts as bookkeeping is different, and
//! the corpus fixtures name it — marker character, marker delimiter, indent
//! width, loose/tight blank lines, and ordered-list numbering. Every one of
//! those is a per-list convention read off the list as found, never normalized
//! to a house style.
//!
//! This module holds the half that finds things: the summary a model is given
//! instead of the document, and the two resolvers that turn an address and an
//! item selector into a list and an index. The edits are built on top of it.

use std::collections::HashMap;

use crate::args::{check_heading, check_ordinal, check_position_in, PosFamily, Position};
use crate::error::{OpError, Repair, Result};
use crate::json;
use crate::list::{find_lists, ListItem, MdList};
use crate::ops::table::heading_path_at;
use crate::scan::{match_item, py_strip, split_lines};
use crate::similar::get_close_matches;

/// One entry of the compact structural summary a model sees instead of the
/// document.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListEntry {
    /// Per heading path, matching how a model would count them.
    pub ordinal: usize,
    pub heading: String,
    /// `"ordered"` or `"bullet"`.
    pub kind: &'static str,
    /// The FIRST item's marker verbatim, not a synthesized `1.`. A list numbered
    /// 5, 6, 7 is legal and the summary is the model's only view of the file, so
    /// a tidied-up marker here is a false statement about the document even
    /// where no current task turns on it.
    pub marker: String,
    pub items: usize,
    pub levels: usize,
    pub loose: bool,
    pub tasks: usize,
}

/// One item returned by [`list_get`].  This is intentionally smaller than the
/// parser's [`ListItem`]: marker spelling and line spans are executor
/// bookkeeping, while text, nesting and checkbox state are the facts a caller
/// needs to address a subsequent edit without guessing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListReadItem {
    pub text: String,
    pub depth: usize,
    /// Index in `items`, so the relationship survives repeated parent text.
    pub parent: Option<usize>,
    pub checked: Option<bool>,
}

/// The structured result of [`list_get`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListItems {
    pub heading: String,
    pub ordinal: usize,
    pub items: Vec<ListReadItem>,
}

/// The structural summary, one entry per top-level list.
///
/// Deliberately withholds item text, exactly as
/// [`list_tables`](crate::ops::table::list_tables) withholds cell values: Arm
/// B's premise is that the model addresses an edit it cannot see, and the
/// instruction is what supplies the text to match. What it must include is
/// everything needed to *choose* a list — heading, ordinal, and enough shape to
/// tell two lists under one heading apart.
pub fn list_lists(content: &str) -> Vec<ListEntry> {
    let mut out: Vec<ListEntry> = find_lists(content)
        .iter()
        .map(|l| {
            let path = heading_path_at(content, l.start);
            ListEntry {
                ordinal: 0,
                heading: if path.is_empty() {
                    "(document root)".to_string()
                } else {
                    path.join(" > ")
                },
                kind: if l.ordered { "ordered" } else { "bullet" },
                marker: l
                    .items
                    .first()
                    .map(|it| it.marker.clone())
                    .unwrap_or_else(|| l.bullet.clone()),
                items: l.items.len(),
                levels: l.items.iter().map(|it| it.depth).max().unwrap_or(0) + 1,
                loose: l.loose,
                tasks: l.items.iter().filter(|it| it.checkbox.is_some()).count(),
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

/// The model-readable form of [`list_lists`] — the Arm B prompt context.
///
/// As with the table summary this string *is* the prompt, so §1.2's numbers
/// measure the ops and this rendering together.
pub fn render_list_summary(content: &str, path: &str) -> String {
    let mut out = vec![format!("Lists in `{path}`:")];
    for e in list_lists(content) {
        let mut bits = vec![
            format!("{} list, marker \"{}\"", e.kind, e.marker),
            format!("{} items", e.items),
            if e.loose {
                "loose (blank line between items)".to_string()
            } else {
                "tight".to_string()
            },
        ];
        if e.levels > 1 {
            bits.insert(1, format!("{} levels of nesting", e.levels));
        }
        if e.tasks > 0 {
            bits.push(format!("{} task checkboxes", e.tasks));
        }
        out.push(format!(
            "  heading \"{}\"  ordinal {}\n    {}",
            e.heading,
            e.ordinal,
            bits.join(", ")
        ));
    }
    out.join("\n")
}

/// A list address. Same two fields as
/// [`TableAddress`](crate::ops::table::TableAddress), and unchecked for the same
/// reason: `check_heading` and `check_ordinal` are statements inside the
/// resolver, not part of extracting the address, so a malformed `heading` cannot
/// outrank a malformed `text`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ListAddress {
    pub heading: Option<json::Value>,
    pub ordinal: Option<json::Value>,
}

impl ListAddress {
    pub fn none() -> Self {
        Self::default()
    }

    pub fn heading(h: impl Into<String>) -> Self {
        ListAddress {
            heading: Some(json::Value::Str(h.into())),
            ordinal: None,
        }
    }

    pub fn with_ordinal(mut self, ordinal: i64) -> Self {
        self.ordinal = Some(json::Value::Int(ordinal));
        self
    }
}

impl From<&str> for ListAddress {
    fn from(h: &str) -> Self {
        ListAddress::heading(h)
    }
}

/// The `list` argument as it arrives — an object, a bare heading string, or
/// absent — split into the two fields the resolver reads.
///
/// The bare-string shorthand is the table family's, kept identical so the two do
/// not teach the model two different addressing habits.
pub fn list_address_fields(value: Option<&json::Value>) -> ListAddress {
    match value {
        Some(json::Value::Str(s)) => ListAddress::heading(s.clone()),
        Some(json::Value::Object(pairs)) => ListAddress {
            heading: pairs
                .iter()
                .find(|(k, _)| k == "heading")
                .map(|(_, v)| v.clone()),
            ordinal: pairs
                .iter()
                .find(|(k, _)| k == "ordinal")
                .map(|(_, v)| v.clone()),
        },
        _ => ListAddress::none(),
    }
}

/// Find the one list an address names, or fail with the candidates.
pub fn resolve_list(content: &str, address: &ListAddress) -> Result<MdList> {
    let lists = find_lists(content);
    let entries = list_lists(content);
    // Both up front, as `locate_table` does, so a malformed `ordinal` is refused
    // even when the heading it accompanies does not exist.
    let heading = check_heading(address.heading.as_ref(), "list")?;
    let ordinal = check_ordinal(address.ordinal.as_ref(), "list")?;

    let want_h = match &heading {
        Some(h) => h,
        None => {
            if lists.len() == 1 {
                return Ok(lists.into_iter().next().unwrap());
            }
            let cands: Vec<String> = entries
                .iter()
                .map(|e| format!("\"{}\" ordinal {}", e.heading, e.ordinal))
                .collect();
            return Err(OpError::new(format!(
                "list address required: this file has {} lists.\n  Candidates: {}",
                lists.len(),
                cands.join("; ")
            )));
        }
    };

    let norm = want_h.trim().to_lowercase();
    let matched: Vec<(&MdList, &ListEntry)> = lists
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
            "no list under heading \"{}\".\n  Near matches: {}\n  Headings with lists: {}",
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
                    format!(
                        "ordinal {} ({}, marker \"{}\", {} items)",
                        e.ordinal, e.kind, e.marker, e.items
                    )
                })
                .collect();
            return Err(OpError::new(format!(
                "ambiguous: {} lists under \"{}\". Pass an ordinal.\n  Candidates: {}",
                matched.len(),
                want_h,
                cands.join("; ")
            )));
        }
    };

    // As in `locate_table`: an ordinal too large for an `i64` cannot name a
    // list, so "does not fit" and "does not match" are the same answer.
    if let Some(want) = want_o.small() {
        for (l, e) in &matched {
            if e.ordinal as i64 == want {
                return Ok((*l).clone());
            }
        }
    }
    let valid: Vec<String> = matched.iter().map(|(_, e)| e.ordinal.to_string()).collect();
    Err(OpError::new(format!(
        "no list with ordinal {} under \"{}\".\n  Valid ordinals: {}",
        want_o.repr(),
        want_h,
        valid.join(", ")
    )))
}

/// Return the addressable contents of one list.
///
/// Unlike [`list_lists`], this is an explicit inspection read: item text is the
/// point.  It shares the exact resolver used by edits, so copying a returned
/// `text` into `after` or `item` names the same list item the executor saw.
pub fn list_get(content: &str, address: &ListAddress) -> Result<ListItems> {
    let list = resolve_list(content, address)?;
    let index = find_lists(content)
        .iter()
        .position(|candidate| candidate.start == list.start)
        .ok_or_else(|| OpError::new("internal: resolved list has no summary entry."))?;
    let entry = list_lists(content)
        .into_iter()
        .nth(index)
        .ok_or_else(|| OpError::new("internal: resolved list has no summary entry."))?;
    let items = list
        .items
        .iter()
        .map(|item| ListReadItem {
            text: item.text.clone(),
            depth: item.depth,
            parent: item.parent,
            checked: item.checkbox.map(|mark| mark == 'x' || mark == 'X'),
        })
        .collect();
    Ok(ListItems {
        heading: entry.heading,
        ordinal: entry.ordinal,
        items,
    })
}

/// Model-readable rendering of [`list_get`].
pub fn render_list_items(got: &ListItems) -> String {
    let mut out = vec![format!(
        "List {} ordinal {} -- {} items",
        json::dumps_str(&got.heading),
        got.ordinal,
        got.items.len()
    )];
    for (index, item) in got.items.iter().enumerate() {
        let parent = item
            .parent
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string());
        let checked = item
            .checked
            .map(|value| value.to_string())
            .unwrap_or_else(|| "null".to_string());
        out.push(format!(
            "  [{}] text={} depth={} parent={} checked={}",
            index,
            json::dumps_str(&item.text),
            item.depth,
            parent,
            checked
        ));
    }
    out.join("\n")
}

pub fn render_list_get(content: &str, address: &ListAddress) -> Result<String> {
    list_get(content, address).map(|got| render_list_items(&got))
}

/// Index of the one item `text` names, or a refusal.
///
/// Three passes, narrowest first: exact, case-insensitive exact, then unique
/// substring. This is looser than the table family's `where`, and the looseness
/// is deliberate rather than inherited — a list item is prose, not a cell value,
/// so a request that says "the child pending task" is naming a real thing that a
/// strict comparison would reject over a word of surrounding phrasing.
///
/// What does NOT change is the rule underneath: the selector must identify
/// exactly one item. A substring matching two items refuses, and names both.
pub fn resolve_item(lst: &MdList, text: Option<&str>, field: &str) -> Result<usize> {
    let raw = text.unwrap_or("");
    if raw.trim().is_empty() {
        return Err(OpError::new(format!(
            "`{}` is required: the text of the list item to act on.\n  The list has {} items.",
            field,
            lst.items.len()
        )));
    }
    let want = raw.trim();
    let texts = lst.texts();

    let lower_want = want.to_lowercase();
    let passes: [&dyn Fn(&str) -> bool; 3] = [
        &|t: &str| t == want,
        &|t: &str| t.to_lowercase() == lower_want,
        &|t: &str| t.to_lowercase().contains(&lower_want),
    ];
    for pred in passes {
        let hits: Vec<usize> = texts
            .iter()
            .enumerate()
            .filter(|(_, t)| pred(t))
            .map(|(i, _)| i)
            .collect();
        if hits.len() == 1 {
            return Ok(hits[0]);
        }
        if hits.len() > 1 {
            let matches: Vec<String> = hits.iter().map(|i| texts[*i].clone()).collect();
            let shown: Vec<String> = matches.iter().map(|text| format!("\"{}\"", text)).collect();
            let mut repair = Repair::new(
                "ambiguous_item",
                "Repeat the call with one exact item text from candidates.",
            );
            repair.argument = Some(field.to_string());
            repair.received = Some(want.to_string());
            repair.candidates = matches;
            return Err(OpError::with_repair(
                format!(
                    "\"{}\" matches {} items; it must identify exactly one.\n  Matches: {}",
                    want,
                    hits.len(),
                    shown.join("; ")
                ),
                repair,
            ));
        }
    }
    let near = get_close_matches(want, &texts, 3, 0.4);
    Err(OpError::new(format!(
        "no list item matching \"{}\".\n  Near matches: {}\n  Items: {}",
        want,
        if near.is_empty() {
            "none".to_string()
        } else {
            near.join(", ")
        },
        texts.join("; ")
    )))
}

// --------------------------------------------------------------------------
// conventions
// --------------------------------------------------------------------------
// Everything below reads a convention off the list as found. None of it is a
// house style, and none of it is inferred from a default: the marker character,
// the ordered delimiter, the gap after the marker, the indent, the loose blank
// line and the numbering scheme are all copied from the item the new one sits
// beside. That is why `list-add-item` has no `depth`, `indent` or `marker`
// argument -- there is nothing for the model to get wrong.

/// The list's line ending, or a refusal if it has two.
fn list_eol(lst: &MdList) -> Result<&'static str> {
    let mut cr = false;
    let mut lf = false;
    for ln in &lst.lines {
        if ln.ends_with('\r') {
            cr = true;
        } else {
            lf = true;
        }
    }
    match (cr, lf) {
        (true, false) => Ok("\r"),
        (false, true) => Ok(""),
        _ => Err(OpError::new(
            "this list mixes CRLF and LF line endings, so there is no convention to match.\n  Normalize the list's line endings first, then retry.",
        )),
    }
}

/// The whitespace between marker and content, copied rather than assumed.
fn marker_gap(lines: &[&str], item: &ListItem) -> String {
    match match_item(lines[item.start]) {
        Some(m) => m.gap.unwrap_or(" ").to_string(),
        None => " ".to_string(),
    }
}

/// How an ordered sibling group is numbered.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Style {
    /// 1,2,3,4 — inserting requires renumbering everything after.
    Sequential,
    /// 1,1,1 — legal CommonMark; renumbering would be the bug.
    Constant,
    /// 1,3,7 — already inconsistent; renumbering is a behaviour change the
    /// caller did not ask for.
    Irregular,
}

/// The three cases are not stylistic preferences, they are three different
/// correct answers, and `corpus/lists/ordered-numbering.md` was built to make
/// that concrete.
///
/// A sibling group can MIX ordered and unordered items: a marker change ends a
/// top-level list, but nothing stops `- y` and `1. x` sitting at the same depth
/// under one parent, and the bullet's `number` is `None`. Such a group is
/// irregular by the same argument as 1,3,7 — it is already something no
/// renumbering scheme describes, so leaving it alone is the only answer that
/// does not invent a change. The oracle raised `None + 0` here instead, and
/// reported the TypeError to the model (FINDINGS F-mixnum).
fn numbering_style(nums: &[Option<i64>]) -> Style {
    if nums.iter().any(|n| n.is_none()) {
        return Style::Irregular;
    }
    let v: Vec<i64> = nums.iter().map(|n| n.unwrap()).collect();
    if v.len() >= 2 && v.iter().all(|n| *n == v[0]) {
        return Style::Constant;
    }
    // An empty group takes this branch vacuously, as `all([])` does.
    if v.iter().enumerate().all(|(k, n)| *n == v[0] + k as i64) {
        return Style::Sequential;
    }
    Style::Irregular
}

/// The number a renumbering run counts from: the group's first real one,
/// falling back to the anchor's own when the group opens with a bullet.
fn group_start(nums: &[Option<i64>], fallback: Option<i64>) -> Option<i64> {
    nums.iter().find_map(|n| *n).or(fallback)
}

/// `(depth, parent text, sibling indices)` for the group an item belongs to.
fn list_context(lst: &MdList, idx: usize) -> (usize, String, Vec<usize>) {
    let it = &lst.items[idx];
    let parent_text = it
        .parent
        .map(|p| lst.items[p].text.clone())
        .unwrap_or_default();
    let group: Vec<usize> = lst
        .items
        .iter()
        .enumerate()
        .filter(|(_, o)| o.depth == it.depth && o.parent == it.parent)
        .map(|(i, _)| i)
        .collect();
    (it.depth, parent_text, group)
}

/// Rewrite the marker numbers of one sibling group, touching nothing else.
///
/// Re-parses the edited document rather than adjusting the pre-edit items,
/// because the insert has already moved every line index after it. The list is
/// found again by ordinal — `list_index` — which is why that ordinal is taken
/// before the edit.
fn renumber(
    lines: Vec<String>,
    lst_idx: usize,
    depth: usize,
    parent_text: &str,
    style: Style,
    start: i64,
) -> Vec<String> {
    if style == Style::Irregular {
        return lines;
    }
    let joined = lines.join("\n");
    let all = find_lists(&joined);
    let rebuilt = &all[lst_idx];
    let group: Vec<&ListItem> = rebuilt
        .items
        .iter()
        .filter(|it| {
            it.depth == depth
                && it
                    .parent
                    .map(|p| rebuilt.items[p].text.as_str())
                    .unwrap_or("")
                    == parent_text
        })
        .collect();
    let mut lines = lines;
    for (k, it) in group.iter().enumerate() {
        let want = if style == Style::Constant {
            start
        } else {
            start + k as i64
        };
        if it.number == Some(want) {
            continue;
        }
        let ln = lines[it.start].clone();
        let m = match match_item(&ln) {
            Some(m) => m,
            None => continue,
        };
        let delim = it.delim.map(|c| c.to_string()).unwrap_or_default();
        lines[it.start] = format!("{}{}{}{}", m.indent, want, delim, &ln[m.marker_end..]);
    }
    lines
}

/// Position of `lst` among the document's lists — stable across edits.
fn list_index(content: &str, lst: &MdList) -> Result<usize> {
    find_lists(content)
        .iter()
        .position(|o| o.start == lst.start)
        .ok_or_else(|| OpError::new("internal: list could not be relocated after the edit."))
}

/// The oracle's `checked in (True, "true", "True", "yes", 1)`.
///
/// A membership test with Python's `==`, so `1` and `1.0` are in and `False` and
/// `0` are not — the numeric cases are not decoration, a model that sends
/// `checked: 1` means checked.
fn is_checked(v: Option<&json::Value>) -> bool {
    match v {
        Some(json::Value::Bool(b)) => *b,
        Some(json::Value::Int(n)) => *n == 1,
        Some(json::Value::Float(f)) => *f == 1.0,
        Some(json::Value::Str(s)) => s == "true" || s == "True" || s == "yes",
        _ => false,
    }
}

// --------------------------------------------------------------------------
// the edits
// --------------------------------------------------------------------------

/// Insert an item, matching every convention of the list it joins.
///
/// The new item takes its indent, marker character, marker delimiter and marker
/// spacing from the sibling it is placed next to. That is why there is no
/// `depth` or `indent` argument: "add a nested item under beta" is expressed as
/// `after: "beta-two"`, and an impossible depth is unsayable (§6.4).
pub fn list_add_item(
    content: &str,
    address: &ListAddress,
    text: Option<&str>,
    position: Option<&json::Value>,
    after: Option<&str>,
    checked: Option<&json::Value>,
) -> Result<String> {
    let lst = resolve_list(content, address)?;
    let text = match text.map(py_strip) {
        Some(t) if !t.is_empty() => t.to_string(),
        _ => {
            return Err(OpError::new(
                "`text` is required: the content of the new list item.",
            ))
        }
    };
    if lst.items.is_empty() {
        return Err(OpError::new(
            "this list has no items to match conventions against.",
        ));
    }
    let lines = split_lines(content);
    let eol = list_eol(&lst)?;

    // The oracle reads `a.get("checked")`, which cannot tell an absent key from
    // an explicit `null` — both arrive as Python `None`, meaning "infer". The
    // dispatch passes the raw value, so the collapse happens here.
    // `list_set_checked` must NOT do this: its default is `True`, so there an
    // explicit `null` is falsy and an absent key is not.
    let checked = checked.filter(|v| !matches!(v, json::Value::Null));

    // Shared with the table family so that one word means one thing: `"Start"`
    // and `0` used to be *start* on a table and *end* on a list, silently, and
    // reported as success. `check_position_in` parses both the same way and
    // refuses an index here, where there are no row numbers to count.
    // Evaluated before the `after` branch, as the old `starts` was, so an
    // ill-typed `position` is refused rather than ignored when `after` decides
    // the placement -- F-args' rule, not a new one.
    let starts = match check_position_in(position, PosFamily::List)? {
        Position::Start => true,
        Position::End => false,
        // `check_position_in` refuses an index for `PosFamily::List`, so this
        // arm is unreachable; it is written out rather than `_ =>` so that
        // adding indices later is a compile error here instead of a silent
        // append.
        Position::Index(_) => {
            return Err(OpError::new("`position` index is not supported for lists."))
        }
    };
    let (anchor, insert_at) = if after.is_some_and(|a| !a.trim().is_empty()) {
        let anchor = resolve_item(&lst, after, "after")?;
        (anchor, lst.items[anchor].end + 1)
    } else if starts {
        (0, lst.items[0].start)
    } else {
        let anchor = lst
            .items
            .iter()
            .enumerate()
            .filter(|(_, it)| it.depth == 0)
            .map(|(i, _)| i)
            .next_back()
            .expect("a run always has a top-level item");
        (anchor, lst.items[anchor].end + 1)
    };

    let (depth, parent_text, group) = list_context(&lst, anchor);
    let a = &lst.items[anchor];
    let gap = marker_gap(&lines, a);

    // Checkbox: supplied explicitly, or inferred when every sibling is a task
    // item. Inference here is the same class of rule as copying the marker --
    // adding a plain item to an all-task list produces a list that renders
    // inconsistently -- but it IS an inference, and REQUIREMENTS.md flags it as
    // an open question rather than treating it as settled.
    let box_ = if checked.is_some() {
        if is_checked(checked) {
            "[x] "
        } else {
            "[ ] "
        }
    } else if !group.is_empty() && group.iter().all(|i| lst.items[*i].checkbox.is_some()) {
        "[ ] "
    } else {
        ""
    };

    let mut style = Style::Irregular;
    let mut start = 0i64;
    let marker = if a.ordered {
        let nums: Vec<Option<i64>> = group.iter().map(|i| lst.items[*i].number).collect();
        style = numbering_style(&nums);
        start = group_start(&nums, a.number).unwrap_or(0);
        let number = match style {
            // A placeholder on the sequential path: the group is renumbered
            // below, and this line is renumbered with it.
            Style::Constant | Style::Sequential => start,
            Style::Irregular => {
                // Leave the neighbours alone and follow the predecessor. Only
                // *numbered* predecessors count -- a bullet sibling has no
                // number to follow (FINDINGS F-mixnum).
                group
                    .iter()
                    .filter(|i| lst.items[**i].start < insert_at)
                    .filter_map(|i| lst.items[*i].number)
                    .next_back()
                    .map_or(start, |n| n + 1)
            }
        };
        format!(
            "{}{}",
            number,
            a.delim.map(|c| c.to_string()).unwrap_or_default()
        )
    } else {
        a.marker.clone()
    };

    let new_line = format!("{}{}{}{}{}{}", a.indent, marker, gap, box_, text, eol);
    let mut block = vec![new_line];
    if lst.loose {
        if insert_at > lst.items[anchor].start {
            block.insert(0, eol.to_string());
        } else {
            block.push(eol.to_string());
        }
    }
    let mut out: Vec<String> = lines[..insert_at].iter().map(|s| s.to_string()).collect();
    out.extend(block);
    out.extend(lines[insert_at..].iter().map(|s| s.to_string()));

    if a.ordered && style != Style::Irregular {
        let idx = list_index(content, &lst)?;
        out = renumber(out, idx, depth, &parent_text, style, start);
    }
    Ok(out.join("\n"))
}

/// Remove an item and everything nested under it.
pub fn list_remove_item(
    content: &str,
    address: &ListAddress,
    item: Option<&str>,
) -> Result<String> {
    let lst = resolve_list(content, address)?;
    let idx = resolve_item(&lst, item, "item")?;
    let it = &lst.items[idx];
    let (depth, parent_text, group) = list_context(&lst, idx);
    let lines = split_lines(content);

    let (mut lo, mut hi) = (it.start, it.end);
    if lst.loose {
        // Take one separating blank line with the item, or the list grows a
        // trailing blank and the following block appears to move.
        if hi < lst.end && py_strip(lines[hi + 1]).is_empty() {
            hi += 1;
        } else if lo > lst.start && py_strip(lines[lo - 1]).is_empty() {
            lo -= 1;
        }
    }
    let mut out: Vec<String> = lines[..lo].iter().map(|s| s.to_string()).collect();
    out.extend(lines[hi + 1..].iter().map(|s| s.to_string()));

    if it.ordered {
        let nums: Vec<Option<i64>> = group.iter().map(|i| lst.items[*i].number).collect();
        let style = numbering_style(&nums);
        if style != Style::Irregular && group.len() > 1 {
            let start = group_start(&nums, it.number).unwrap_or(0);
            let li = list_index(content, &lst)?;
            out = renumber(out, li, depth, &parent_text, style, start);
        }
    }
    Ok(out.join("\n"))
}

/// Tick or untick one task item, leaving the rest of the line untouched.
pub fn list_set_checked(
    content: &str,
    address: &ListAddress,
    item: Option<&str>,
    checked: Option<&json::Value>,
) -> Result<String> {
    let lst = resolve_list(content, address)?;
    let idx = resolve_item(&lst, item, "item")?;
    let it = &lst.items[idx];
    let state = match it.checkbox {
        Some(c) => c,
        None => {
            let tasks: Vec<String> = lst
                .items
                .iter()
                .filter(|o| o.checkbox.is_some())
                .map(|o| o.text.clone())
                .collect();
            return Err(OpError::new(format!(
                "\"{}\" is not a task item -- it has no [ ] checkbox.\n  Task items in this list: {}",
                it.text,
                if tasks.is_empty() { "none".to_string() } else { tasks.join("; ") }
            )));
        }
    };
    // The dispatch defaults this to `True`, so `None` here means the caller
    // called the function directly and meant the default.
    let want = match checked {
        None => true,
        v => is_checked(v),
    };
    if want == (state == 'x' || state == 'X') {
        return Err(OpError::new(format!(
            "\"{}\" is already {}; nothing to do.",
            it.text,
            if want { "checked" } else { "unchecked" }
        )));
    }
    // Preserving the author's capitalization -- ticking with `[X]` because the
    // list uses `[X]` elsewhere -- is deliberately NOT attempted.
    // `corpus/lists/tasks.md` requires `[X]` to round-trip untouched, which it
    // does because this rewrites only the one line it was asked to.
    let mut out: Vec<String> = content.split('\n').map(|s| s.to_string()).collect();
    let ln = out[it.start].clone();
    let m = match_item(&ln).expect("an item line matches");
    // `m.group(3) or ""` and not `or " "`: on the bare-marker branch there is no
    // gap, and a checkbox cannot be on such a line anyway — but the two spellings
    // differ by one byte and only one of them is what the oracle computes.
    let head = m.marker_end + m.gap.unwrap_or("").len();
    out[it.start] = format!(
        "{}{}{}",
        &ln[..head],
        if want { "[x]" } else { "[ ]" },
        &ln[head + 3..]
    );
    Ok(out.join("\n"))
}
