//! The invariants REQUIREMENTS.md §11 states as structural, checked over the
//! whole corpus so `cargo test` alone carries them.
//!
//! `bench/difftest.py` proves the port agrees with the oracle. It cannot prove
//! the oracle is right — if both sides ate a row, they would agree. These are
//! the properties that have to hold regardless of what either implementation
//! does, and each one is here because a trial broke it:
//!
//! * **No op removes a row it was not asked to remove.** This is the 10%
//!   data-loss finding, and the reason the project exists.
//! * **Bytes outside the target range are unchanged** (§5.2).
//! * **The blank line after a table survives.** Three trials consumed it.
//! * **Widen, never shrink.** Re-padding may grow a column and may not narrow
//!   one, or every edit becomes a whole-table diff.
//!
//! The list family restates the same four in its own vocabulary, and gains one
//! the table family cannot have: a list carries no padding, so add-then-remove
//! is *byte-identical* rather than merely non-narrowing. That is the claim that
//! catches a renumbering scheme which does not undo itself.
//!
//! The section family restates them a third time and adds the one question the
//! other two cannot ask: a section has **two ends**, its own prose and its
//! subtree, and nearly every property below is really about which one an op
//! used. Both are correct answers to different questions, so the differential
//! suite would happily watch two implementations pick the same wrong one.
//!
//! Two of the section round-trips are conditional, and the conditions are
//! findings rather than concessions — `rename` normalizes whitespace inside the
//! heading span by design, and `set-level` is not invertible when a promotion
//! changes which siblings the subtree contains. Both are stated where they are
//! skipped.
//!
//! The frontmatter family restates them a fourth time, through the narrowest
//! window of the four: the other three splice a span, so "bytes outside the
//! range are unchanged" is the strongest available claim; here the range is one
//! line of a block whose every other line is load-bearing, and the claim is
//! that a set moves exactly that line. A parse-and-serialize implementation
//! passes every case in `difftest.py` and fails that one, which is why it is
//! here and not there.
//!
//! Tables the ops legitimately refuse (mixed line endings, mixed indent) are
//! skipped rather than asserted on: a refusal is a correct outcome, and §5.3
//! covers its wording. What is *not* allowed is a refusal that still wrote.
//!
//! The fixtures are `corpus/` **and** `bench/synthetic/`. Adding the second set
//! immediately falsified two of these as they were written — see
//! `add_then_delete_loses_nothing_and_only_ever_widens`, which claimed
//! byte-identity, and `no_op_removes_an_item_it_was_not_asked_to_remove`, which
//! re-resolved an address that a successful edit had made stale. Both passed on
//! the corpus alone for the same reason: no corpus document reaches the case.
//! `front-dupes.md` did it a third time, to a claim about which line a set
//! moves — see `a_frontmatter_set_moves_exactly_one_line`.

use incise_core::describe::describe_change;
use incise_core::front::{find_frontmatter, format_path, Fmt, FrontMatter, Kind, Seg};
use incise_core::heading::{find_sections, Section};
use incise_core::json;
use incise_core::list::{find_lists, MdList};
use incise_core::ops::frontmatter::{
    describe_frontmatter_change, frontmatter_delete, frontmatter_get, frontmatter_set,
    frontmatter_set_guarded, render_frontmatter, render_frontmatter_get, FrontKey,
};
use incise_core::ops::list::{
    list_add_item, list_get, list_lists, list_remove_item, list_set_checked, resolve_item,
    resolve_list, ListAddress,
};
use incise_core::ops::section::{
    resolve_section, section_append, section_delete, section_insert, section_outline,
    section_rename, section_replace_body, section_set_level, SectionAddress, POSITIONS,
};
use incise_core::ops::table::{
    render_table_get, table_add_row, table_delete_row, table_get, table_realign, TableAddress,
    Values,
};
use incise_core::table::{find_tables, outside_table, Table};

/// Short enough never to widen a column — this is a round-trip test, not a
/// re-pad test, and a widening value would legitimately fail to shrink back.
const SENTINEL: &str = "zq7";

#[test]
fn the_list_read_exposes_exact_text_and_nesting_without_parser_bookkeeping() {
    let by_rel: std::collections::BTreeMap<String, String> = corpus().into_iter().collect();
    let content = &by_rel["corpus/lists/nested-mixed.md"];
    let got = list_get(
        content,
        &ListAddress::heading("Asterisk markers, four-space indent"),
    )
    .unwrap();
    assert_eq!(
        got.items
            .iter()
            .map(|item| item.text.as_str())
            .collect::<Vec<_>>(),
        ["alpha", "beta", "beta-one", "beta-two", "gamma"]
    );
    assert_eq!(
        got.items.iter().map(|item| item.depth).collect::<Vec<_>>(),
        [0, 0, 1, 1, 0]
    );
    assert_eq!(got.items[2].parent, Some(1));
    assert_eq!(got.items[3].parent, Some(1));
    assert!(got.items.iter().all(|item| item.checked.is_none()));
}

fn corpus() -> Vec<(String, String)> {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..");
    let mut out = Vec::new();
    // `corpus/` is the measured artifact; `bench/synthetic/` holds the documents
    // it provably cannot reach, and both harnesses read the same copies of them
    // (`bench/synthetic/README.md.txt`). Reading only the corpus here would
    // leave these properties blind to exactly the inputs that were added because
    // everything else was blind to them.
    for sub in ["corpus", "bench/synthetic"] {
        let base = root.join(sub);
        let mut stack = vec![base.clone()];
        while let Some(dir) = stack.pop() {
            let mut entries: Vec<_> = std::fs::read_dir(&dir)
                .unwrap_or_else(|e| panic!("read {}: {e}", dir.display()))
                .filter_map(|e| e.ok())
                .map(|e| e.path())
                .collect();
            entries.sort();
            for p in entries {
                if p.is_dir() {
                    stack.push(p);
                } else if p.extension().map(|e| e == "md").unwrap_or(false) {
                    let rel = p.strip_prefix(&root).unwrap().display().to_string();
                    out.push((rel, std::fs::read_to_string(&p).expect("read fixture")));
                }
            }
        }
    }
    out.sort();
    assert!(!out.is_empty(), "corpus is empty; is the path right?");
    out
}

/// Every (fixture, table-ordinal) pair, addressed the way an op addresses it.
fn each_table(f: &mut dyn FnMut(&str, &str, &TableAddress, &Table)) {
    let mut seen = 0;
    for (rel, content) in corpus() {
        let entries = incise_core::ops::table::list_tables(&content);
        for (t, e) in find_tables(&content).into_iter().zip(entries) {
            if t.columns().is_empty() || t.rows().is_empty() {
                continue;
            }
            let addr = TableAddress {
                heading: Some(json::Value::Str(e.heading.clone())),
                ordinal: Some(json::Value::Int(e.ordinal as i64)),
            };
            seen += 1;
            f(&rel, &content, &addr, &t);
        }
    }
    assert!(
        seen > 20,
        "only {seen} tables exercised; corpus lookup is wrong"
    );
}

fn short_row(t: &Table) -> Values {
    Values::ordered(t.columns().iter().map(|_| SENTINEL.to_string()))
}

#[test]
fn bytes_outside_the_table_are_untouched() {
    each_table(&mut |rel, content, addr, t| {
        for pos in [
            json::Value::Str("start".into()),
            json::Value::Str("end".into()),
            json::Value::Int(0),
        ] {
            let Ok(after) = table_add_row(content, addr, &short_row(t), Some(&pos)) else {
                continue;
            };
            let new_t = incise_core::ops::table::resolve_table(&after, addr)
                .expect("table still resolvable after its own edit");
            assert_eq!(
                outside_table(content, t),
                outside_table(&after, &new_t),
                "{rel}: adding a row changed bytes outside the table",
            );
        }
    });
}

#[test]
fn add_then_delete_loses_nothing_and_only_ever_widens() {
    each_table(&mut |rel, content, addr, t| {
        // A table that already contains the sentinel would make the delete
        // ambiguous, which is a refusal, not a failure — skip it.
        if t.rows().iter().flatten().any(|c| c == SENTINEL) {
            return;
        }
        // So would a header that names the first column twice: the add goes
        // through on the ordered path and the delete cannot name a cell at all
        // (F-dupcol). Skipped for the same reason and by the same rule — the
        // refusal is correct — and narrowly, so that an unambiguous header
        // still has to round-trip.
        let col = t.columns()[0].clone();
        if t.columns().iter().filter(|c| **c == col).count() > 1 {
            return;
        }
        for pos in [
            json::Value::Str("start".into()),
            json::Value::Str("end".into()),
            json::Value::Int(1),
        ] {
            let Ok(added) = table_add_row(content, addr, &short_row(t), Some(&pos)) else {
                continue;
            };
            let back = table_delete_row(
                &added,
                addr,
                &[(col.clone(), json::Value::Str(SENTINEL.to_string()))],
            )
            .expect("the row just added must be deletable");
            if back == content {
                continue;
            }
            // This test claimed byte-identity outright until `bench/synthetic`
            // joined the fixtures, and it passed for one reason: no *corpus*
            // table is narrow enough for the insert to widen it. Byte-identity
            // is not the property — §5.2's ratchet widens and never shrinks, so
            // a table padded on the way in cannot be un-padded on the way out.
            //
            // What holds unconditionally is the part that matters: nothing was
            // lost and nothing outside moved, and the only difference is more
            // padding than there was. Asserting *that* is stricter than
            // skipping the widened cases, which is the other way to make this
            // test green and says nothing.
            let after = incise_core::ops::table::resolve_table(&back, addr)
                .expect("table survives its own add-then-delete");
            assert_eq!(
                t.columns(),
                after.columns(),
                "{rel}: add-then-delete changed a column name"
            );
            assert_eq!(
                t.rows(),
                after.rows(),
                "{rel}: add-then-delete changed a cell"
            );
            assert_eq!(
                outside_table(content, t),
                outside_table(&back, &after),
                "{rel}: add-then-delete changed bytes outside the table",
            );
            for (was, is) in t.widths().iter().zip(after.widths()) {
                for (w, i) in was.iter().zip(&is) {
                    assert!(
                        i >= w,
                        "{rel}: add-then-delete at {pos:?} narrowed a column, {w} -> {i}"
                    );
                }
            }
        }
    });
}

#[test]
fn no_op_removes_a_row_it_was_not_asked_to_remove() {
    each_table(&mut |rel, content, addr, t| {
        let cols = t.columns();
        let rows = t.rows();
        // Delete needs an unambiguous selector; use the first column value
        // that appears exactly once.
        let Some(idx) = (0..rows.len()).find(|&i| {
            let v = rows[i].first();
            v.is_some() && rows.iter().filter(|r| r.first() == v).count() == 1
        }) else {
            return;
        };
        let sel = [(cols[0].clone(), json::Value::Str(rows[idx][0].clone()))];
        let Ok(after) = table_delete_row(content, addr, &sel) else {
            return;
        };
        let left = incise_core::ops::table::resolve_table(&after, addr)
            .expect("table survives its own row deletion")
            .rows();
        let mut expect = rows.clone();
        expect.remove(idx);
        assert_eq!(
            expect.len(),
            left.len(),
            "{rel}: deleting row {idx} removed {} rows",
            rows.len() - left.len()
        );
        assert_eq!(
            expect, left,
            "{rel}: deleting row {idx} disturbed the others"
        );
    });
}

#[test]
fn adding_a_row_preserves_every_existing_row() {
    each_table(&mut |rel, content, addr, t| {
        let before = t.rows();
        for pos in [
            json::Value::Str("start".into()),
            json::Value::Str("end".into()),
            json::Value::Int(1),
        ] {
            let Ok(after) = table_add_row(content, addr, &short_row(t), Some(&pos)) else {
                continue;
            };
            let rows = incise_core::ops::table::resolve_table(&after, addr)
                .expect("table survives its own insertion")
                .rows();
            assert_eq!(
                before.len() + 1,
                rows.len(),
                "{rel}: row count wrong at {pos:?}"
            );
            // Every original row still present, in its original relative order.
            let kept: Vec<_> = rows
                .iter()
                .filter(|r| r.iter().any(|c| c != SENTINEL))
                .cloned()
                .collect();
            assert_eq!(before, kept, "{rel}: insertion at {pos:?} disturbed a row");
        }
    });
}

#[test]
fn the_blank_line_after_a_table_survives() {
    each_table(&mut |rel, content, addr, t| {
        let lines: Vec<&str> = content.split('\n').collect();
        // Only meaningful where a blank line actually follows the table.
        let next = t.end + 1;
        if next >= lines.len() || !lines[next].trim().is_empty() {
            return;
        }
        for pos in [
            json::Value::Str("start".into()),
            json::Value::Str("end".into()),
        ] {
            let Ok(after) = table_add_row(content, addr, &short_row(t), Some(&pos)) else {
                continue;
            };
            let new_t = incise_core::ops::table::resolve_table(&after, addr).unwrap();
            let after_lines: Vec<&str> = after.split('\n').collect();
            let n = new_t.end + 1;
            assert!(
                n < after_lines.len() && after_lines[n].trim().is_empty(),
                "{rel}: the blank line after the table was consumed at {pos:?}",
            );
        }
    });
}

#[test]
fn re_padding_widens_and_never_shrinks() {
    // Long enough to outgrow any column in the corpus, which is what makes
    // this a re-pad rather than a no-op.
    const LONG: &str = "a-value-far-wider-than-this-column-ever-was";
    let mut checked = 0;
    each_table(&mut |rel, content, addr, t| {
        // "Aligned" for re-padding purposes means aligned *and* tab-free
        // (§5.2). `hazards/whitespace.md` has equal column widths measured in
        // characters and a tab inside every cell: a re-pad would have to guess
        // a tab stop, so it stays ragged. Testing `is_aligned()` alone puts it
        // in the wrong branch.
        if !t.is_aligned() || t.has_tabs() {
            // A ragged table must not be prettified; that is the paired rule,
            // asserted below.
            let Ok(after) = table_add_row(content, addr, &short_row(t), None) else {
                return;
            };
            let before_body: Vec<&str> = content.split('\n').collect();
            let after_body: Vec<&str> = after.split('\n').collect();
            for i in 0..=(t.end - t.start) {
                assert_eq!(
                    before_body[t.start + i],
                    after_body[t.start + i],
                    "{rel}: a ragged table was re-padded",
                );
            }
            return;
        }
        let mut row: Vec<String> = t.columns().iter().map(|_| SENTINEL.to_string()).collect();
        row[0] = LONG.to_string();
        let Ok(after) = table_add_row(content, addr, &Values::ordered(row), None) else {
            return;
        };
        let new_t = incise_core::ops::table::resolve_table(&after, addr).unwrap();
        let before_w = &t.widths()[0];
        let after_w = &new_t.widths()[0];
        assert_eq!(before_w.len(), after_w.len(), "{rel}: column count changed");
        for (i, (b, a)) in before_w.iter().zip(after_w).enumerate() {
            assert!(a >= b, "{rel}: column {i} shrank from {b} to {a}");
        }
        assert!(
            after_w[0] > before_w[0],
            "{rel}: the widened column did not grow"
        );
        checked += 1;
    });
    assert!(checked > 0, "no aligned table was exercised");
}

// --------------------------------------------------------------------------
// table-realign (§6.2)
//
// The one op allowed to rewrite lines nobody named, which makes its
// postconditions the ones worth stating outright. Differential testing cannot
// reach them: it proves the two implementations agree on the output bytes, and
// both could agree on bytes that are not aligned, have lost a cell, or move
// again on a second call.
// --------------------------------------------------------------------------

/// Every table realign actually rewrites comes out aligned.
///
/// This is the operation's whole purpose stated as an assertion. A renderer
/// that merely produced *different* padding would satisfy the differential
/// suite as long as both sides produced the same different padding.
#[test]
fn realign_leaves_the_table_aligned() {
    let mut checked = 0;
    each_table(&mut |rel, content, addr, _t| {
        let Ok(after) = table_realign(content, addr) else {
            return; // refused: non-rectangular, mixed EOL/indent, or wide text
        };
        if after == *content {
            return; // already aligned, the documented no-op
        }
        let new_t = incise_core::ops::table::resolve_table(&after, addr)
            .expect("table still resolvable after its own realign");
        assert!(
            new_t.is_aligned(),
            "{rel}: realign did not produce an aligned table"
        );
        assert!(!new_t.has_tabs(), "{rel}: realign left a tab behind");
        checked += 1;
    });
    assert!(checked > 0, "no table was actually realigned");
}

/// Realign moves a table at most once.
///
/// A second call must be the documented no-op. If it is not, the renderer has
/// no fixed point and every realign is a fresh diff — and the ratchet this op
/// exists to repair would simply be replaced by a different one.
#[test]
fn realign_is_idempotent() {
    each_table(&mut |rel, content, addr, _t| {
        let Ok(once) = table_realign(content, addr) else {
            return;
        };
        let twice = table_realign(&once, addr)
            .unwrap_or_else(|e| panic!("{rel}: realigned table refuses realign: {}", e.message()));
        assert_eq!(once, twice, "{rel}: realign is not idempotent");
    });
}

/// Realign changes padding and nothing else.
///
/// Every cell, in every row, identical before and after — the property
/// `corpus/tables/cell-edge-cases.md` states in prose and the one F-pipes
/// showed both implementations were violating in agreement. Realign is where it
/// matters most, because it rewrites every row of the table at once.
#[test]
fn realign_preserves_every_cell() {
    each_table(&mut |rel, content, addr, t| {
        let Ok(after) = table_realign(content, addr) else {
            return;
        };
        let new_t = incise_core::ops::table::resolve_table(&after, addr).unwrap();
        assert_eq!(
            t.columns(),
            new_t.columns(),
            "{rel}: realign changed a column name"
        );
        assert_eq!(t.rows(), new_t.rows(), "{rel}: realign changed a cell");
        assert_eq!(
            outside_table(content, t),
            outside_table(&after, &new_t),
            "{rel}: realign changed bytes outside the table",
        );
    });
}

/// An unfiltered read reports every row of the table, in order, unchanged.
///
/// The read-side statement of the invariant this project exists for. The 10%
/// finding was an *edit* silently dropping a row; a read that drops one is the
/// same failure with a shorter blast radius, and it is harder to notice because
/// the output still looks like a table. `matched` and `total` are asserted too:
/// they are the only part of the answer a model is likely to believe without
/// checking, so a count that disagrees with the rows below it is worse than no
/// count at all.
#[test]
fn an_unfiltered_read_reports_every_row() {
    each_table(&mut |rel, content, addr, t| {
        let Ok(got) = table_get(content, addr, None) else {
            return;
        };
        assert_eq!(
            got.columns,
            t.columns(),
            "{rel}: read changed a column name"
        );
        assert_eq!(got.rows, t.rows(), "{rel}: read changed or dropped a row");
        assert_eq!(
            got.total,
            t.rows().len(),
            "{rel}: `total` is not the row count"
        );
        assert_eq!(
            got.matched,
            got.rows.len(),
            "{rel}: `matched` disagrees with the rows"
        );
    });
}

/// A filter selects; it never invents, reorders, or edits.
///
/// Whatever comes back must be a subsequence of the unfiltered read — same
/// cells, same relative order — and every returned row must actually carry the
/// value that was filtered on. Those are two different failures: the first is a
/// filter that rebuilds rows, the second is a filter that does not filter.
#[test]
fn a_filter_returns_a_subsequence_that_matches() {
    each_table(&mut |rel, content, addr, _t| {
        let Ok(all) = table_get(content, addr, None) else {
            return;
        };
        let Some(first) = all.rows.first() else {
            return;
        };
        let (col, want) = (all.columns[0].clone(), first[0].clone());
        let filter = json::Value::Object(vec![(col.clone(), json::Value::Str(want.clone()))]);
        // A repeated header name is refused rather than resolved (F-dupcol),
        // which is a correct outcome and not this invariant's business.
        let Ok(got) = table_get(content, addr, Some(&filter)) else {
            return;
        };
        let idx = all.columns.iter().position(|c| *c == col).unwrap();
        for row in &got.rows {
            assert!(
                all.rows.contains(row),
                "{rel}: filter returned a row the table does not have"
            );
            assert_eq!(
                row[idx], want,
                "{rel}: filter returned a row that does not match"
            );
        }
        let mut it = all.rows.iter();
        for row in &got.rows {
            assert!(it.any(|r| r == row), "{rel}: filter reordered the rows");
        }
        assert_eq!(
            got.matched,
            got.rows.len(),
            "{rel}: `matched` disagrees with the rows"
        );
        assert!(
            got.matched >= 1,
            "{rel}: a value taken from the table matched nothing"
        );
    });
}

/// The rendered read parses back as a table with the same cells.
///
/// The render is the product — it is what the model reads — and it is markdown,
/// so it can be fed straight back into `find_tables`. That closes the loop
/// F-pipes left open on the write side: a cell holding `a \| b` has to survive
/// being written into a table and read out of it again, and a renderer that
/// dropped the escape would produce a table with a column count it does not
/// claim. Zero-match reads render prose rather than a table, so they are
/// skipped; they have no cells to preserve.
#[test]
fn a_rendered_read_parses_back_to_the_same_cells() {
    each_table(&mut |rel, content, addr, _t| {
        let (Ok(got), Ok(text)) = (
            table_get(content, addr, None),
            render_table_get(content, addr, None),
        ) else {
            return;
        };
        if got.rows.is_empty() {
            return;
        }
        let parsed = find_tables(&text);
        assert_eq!(parsed.len(), 1, "{rel}: a rendered read is not one table");
        assert_eq!(
            parsed[0].columns(),
            got.columns,
            "{rel}: render changed a column name"
        );
        assert_eq!(parsed[0].rows(), got.rows, "{rel}: render changed a cell");
    });
}

// --------------------------------------------------------------------------
// lists (Tier 2b)
// --------------------------------------------------------------------------
// The same four claims as above, restated in the vocabulary of the family: no
// item is lost, bytes outside the list are untouched, an edit does not convert
// the list between loose and tight, and the ratchet has an exact analogue that
// tables do not — a list has no padding, so add-then-remove is *byte-identical*
// rather than merely non-narrowing. That is a much stronger claim, and it is the
// one that catches a renumbering scheme that does not undo itself.
//
// The conventions are their own invariant, because they are the reason the ops
// take no `depth`, `marker` or `indent` argument (§6.4). If an inserted item did
// not inherit them, those arguments would have to come back.

/// Item text that no fixture contains, and that no fixture's text contains as a
/// substring — `resolve_item`'s third pass is a substring match, so a sentinel
/// that overlapped would resolve to two items and refuse.
const ITEM_SENTINEL: &str = "zq7-sentinel";

/// Every (fixture, list-ordinal) pair, addressed the way an op addresses it.
fn each_list(f: &mut dyn FnMut(&str, &str, &ListAddress, &MdList)) {
    let mut seen = 0;
    for (rel, content) in corpus() {
        let entries = list_lists(&content);
        for (l, e) in find_lists(&content).into_iter().zip(entries) {
            if l.items.is_empty() {
                continue;
            }
            let addr = ListAddress {
                heading: Some(json::Value::Str(e.heading.clone())),
                ordinal: Some(json::Value::Int(e.ordinal as i64)),
            };
            seen += 1;
            f(&rel, &content, &addr, &l);
        }
    }
    assert!(
        seen > 40,
        "only {seen} lists exercised; corpus lookup is wrong"
    );
}

/// Items whose text can be used as an `after`/`item` selector: non-blank, and
/// unique under all three of `resolve_item`'s passes. An ambiguous selector is a
/// refusal, which is a correct outcome and not something to assert on.
fn selectable(l: &MdList) -> Vec<usize> {
    let texts = l.texts();
    (0..l.items.len())
        .filter(|i| {
            let t = &texts[*i];
            !t.trim().is_empty() && resolve_item(l, Some(t), "item") == Ok(*i)
        })
        .collect()
}

/// The document with the list's own lines cut out. The `\u{1}` keeps the two
/// halves from merging, so moving a line across the boundary is visible.
fn outside_list(content: &str, lo: usize, hi: usize) -> String {
    let lines: Vec<&str> = content.split('\n').collect();
    format!(
        "{}\u{1}{}",
        lines[..lo].join("\n"),
        lines[hi + 1..].join("\n")
    )
}

#[test]
fn add_then_remove_is_byte_identical() {
    each_list(&mut |rel, content, addr, l| {
        for i in selectable(l) {
            let anchor = l.items[i].text.clone();
            let Ok(added) = list_add_item(
                content,
                addr,
                Some(ITEM_SENTINEL),
                None,
                Some(&anchor),
                None,
            ) else {
                continue;
            };
            let back = list_remove_item(&added, addr, Some(ITEM_SENTINEL))
                .expect("the item just added must be removable");
            assert_eq!(
                content, back,
                "{rel}: add-after-{anchor:?} then remove did not round-trip",
            );
        }
    });
}

#[test]
fn adding_an_item_preserves_every_existing_item() {
    each_list(&mut |rel, content, addr, l| {
        let before = l.texts();
        for i in selectable(l) {
            let anchor = l.items[i].text.clone();
            let Ok(added) = list_add_item(
                content,
                addr,
                Some(ITEM_SENTINEL),
                None,
                Some(&anchor),
                None,
            ) else {
                continue;
            };
            let after = resolve_list(&added, addr).expect("list survives its own insertion");
            assert_eq!(
                before.len() + 1,
                after.items.len(),
                "{rel}: item count wrong"
            );
            let kept: Vec<String> = after
                .texts()
                .into_iter()
                .filter(|t| t != ITEM_SENTINEL)
                .collect();
            assert_eq!(
                before, kept,
                "{rel}: inserting after {anchor:?} disturbed an item"
            );
            assert_eq!(l.loose, after.loose, "{rel}: inserting changed loose/tight");
        }
    });
}

#[test]
fn no_op_removes_an_item_it_was_not_asked_to_remove() {
    each_list(&mut |rel, content, addr, l| {
        for i in selectable(l) {
            let target = l.items[i].text.clone();
            let Ok(after) = list_remove_item(content, addr, Some(&target)) else {
                continue;
            };
            // The item's whole subtree goes with it — that is the contract, not
            // a loss — so what must survive is every item that is neither the
            // target nor beneath it.
            let doomed: Vec<usize> = (0..l.items.len())
                .filter(|k| {
                    l.items[*k].start >= l.items[i].start && l.items[*k].end <= l.items[i].end
                })
                .collect();
            // Every item in the *document*, not just in this list, and compared
            // as a flat sequence. Re-resolving the address would be the obvious
            // thing and is wrong: removing the only item of a list removes the
            // list, and `ordinal 0` under that heading then names the *next*
            // one — which reports a neighbour's items as survivors of an edit
            // that never touched it. The document-wide form has no address to
            // go stale, and it also catches an edit that disturbs a list it was
            // not addressed to.
            let expect: Vec<String> = find_lists(content)
                .iter()
                .flat_map(|other| {
                    if other.start == l.start {
                        (0..l.items.len())
                            .filter(|k| !doomed.contains(k))
                            .map(|k| l.items[k].text.clone())
                            .collect::<Vec<_>>()
                    } else {
                        other.texts()
                    }
                })
                .collect();
            let left: Vec<String> = find_lists(&after)
                .iter()
                .flat_map(|other| other.texts())
                .collect();
            assert_eq!(
                expect, left,
                "{rel}: removing {target:?} disturbed another item"
            );
        }
    });
}

#[test]
fn bytes_outside_the_list_are_untouched() {
    each_list(&mut |rel, content, addr, l| {
        let before = outside_list(content, l.start, l.end);
        for i in selectable(l) {
            let anchor = l.items[i].text.clone();
            let Ok(added) = list_add_item(
                content,
                addr,
                Some(ITEM_SENTINEL),
                None,
                Some(&anchor),
                None,
            ) else {
                continue;
            };
            let after = resolve_list(&added, addr).expect("list survives its own insertion");
            assert_eq!(
                before,
                outside_list(&added, after.start, after.end),
                "{rel}: inserting after {anchor:?} changed bytes outside the list",
            );
        }
    });
}

/// §6.4's argument for having no `depth`, `marker` or `indent` argument: the
/// inserted item takes all three from the sibling it lands beside, so there is
/// nothing for a model to get wrong and no impossible depth to express.
#[test]
fn an_inserted_item_inherits_its_neighbour_s_conventions() {
    each_list(&mut |rel, content, addr, l| {
        for i in selectable(l) {
            let a = l.items[i].clone();
            let Ok(added) = list_add_item(
                content,
                addr,
                Some(ITEM_SENTINEL),
                None,
                Some(&a.text),
                None,
            ) else {
                continue;
            };
            let after = resolve_list(&added, addr).expect("list survives its own insertion");
            let new = after
                .items
                .iter()
                .find(|it| it.text == ITEM_SENTINEL)
                .expect("the inserted item is in the list it was inserted into");
            assert_eq!(
                a.indent, new.indent,
                "{rel}: inserted item took a different indent"
            );
            assert_eq!(
                a.depth, new.depth,
                "{rel}: inserted item landed at a different depth"
            );
            assert_eq!(
                a.ordered, new.ordered,
                "{rel}: inserted item changed list kind"
            );
            if a.ordered {
                assert_eq!(
                    a.delim, new.delim,
                    "{rel}: inserted item took a different delimiter"
                );
            } else {
                assert_eq!(
                    a.marker, new.marker,
                    "{rel}: inserted item took a different marker"
                );
            }
        }
    });
}

/// Ticking a box and unticking it again is the identity, and each step changes
/// exactly one line. The corpus spells `[x]` and `[X]` both ways, so this also
/// pins what the round-trip is *not*: unticking a capital box and re-ticking it
/// yields lowercase, and that difference must show up as a failure here rather
/// than be discovered in a document.
#[test]
fn set_checked_changes_exactly_one_line_and_toggles_back() {
    let mut seen = 0;
    each_list(&mut |rel, content, addr, l| {
        for i in selectable(l) {
            let Some(state) = l.items[i].checkbox else {
                continue;
            };
            let text = l.items[i].text.clone();
            let was = state == 'x' || state == 'X';
            let flip = json::Value::Bool(!was);
            let unflip = json::Value::Bool(was);
            let toggled = list_set_checked(content, addr, Some(&text), Some(&flip))
                .expect("a task item toggles to the state it is not in");
            let before: Vec<&str> = content.split('\n').collect();
            let mid: Vec<&str> = toggled.split('\n').collect();
            assert_eq!(
                before.len(),
                mid.len(),
                "{rel}: set-checked changed the line count"
            );
            let differ: Vec<usize> = (0..before.len())
                .filter(|k| before[*k] != mid[*k])
                .collect();
            assert_eq!(
                differ.len(),
                1,
                "{rel}: set-checked changed {} lines",
                differ.len()
            );
            assert_eq!(
                differ[0], l.items[i].start,
                "{rel}: set-checked changed the wrong line"
            );

            let back = list_set_checked(&toggled, addr, Some(&text), Some(&unflip))
                .expect("toggling back is always possible");
            if state == 'X' {
                // The one permitted difference, and it is deliberate: the op
                // rewrites the box it was asked about and does not go looking
                // for the author's capitalization to restore.
                assert_eq!(
                    back,
                    content.replacen("[X]", "[x]", 1),
                    "{rel}: capital round-trip"
                );
            } else {
                assert_eq!(back, content, "{rel}: tick-then-untick did not round-trip");
            }
            seen += 1;
        }
    });
    assert!(
        seen > 10,
        "only {seen} task items exercised; the fixtures have too few"
    );
}

/// A CRLF document must not acquire a lone LF. The line ending is read off the
/// list being edited, and an op that built its new line with a bare `\n` would
/// leave a file that renders correctly and diffs as though every later line had
/// changed.
#[test]
fn no_op_adds_a_lone_lf_to_a_crlf_list() {
    each_list(&mut |rel, content, addr, l| {
        if !l.lines.iter().all(|ln| ln.ends_with('\r')) {
            return;
        }
        for i in selectable(l) {
            let anchor = l.items[i].text.clone();
            let mut outs = Vec::new();
            if let Ok(o) = list_add_item(
                content,
                addr,
                Some(ITEM_SENTINEL),
                None,
                Some(&anchor),
                None,
            ) {
                outs.push(o);
            }
            if let Ok(o) = list_remove_item(content, addr, Some(&anchor)) {
                outs.push(o);
            }
            if let Ok(o) =
                list_set_checked(content, addr, Some(&anchor), Some(&json::Value::Bool(true)))
            {
                outs.push(o);
            }
            for out in outs {
                let lines: Vec<&str> = out.split('\n').collect();
                for (k, ln) in lines[..lines.len() - 1].iter().enumerate() {
                    assert!(ln.ends_with('\r'), "{rel}: line {k} lost its CR: {ln:?}");
                }
            }
        }
    });
}

// --------------------------------------------------------------------------
// sections (Tier 2c)
// --------------------------------------------------------------------------
// The same claims a third time, and one the other two families cannot make: a
// section has two ends, so nearly every property here is really a question
// about which one an op used. `own_end` and `end` are both correct answers to
// different questions, and no amount of agreement with the oracle would notice
// the two implementations picking the same wrong one.
//
// The round-trip is the load-bearing test. `section-insert` puts its gap on the
// far side of the block and `section-delete` takes a section's trailing gap,
// and those two decisions have to be the *same* decision — if they are not,
// insert-then-delete leaves a blank line behind and a document edited all day
// loosens one line at a time. Nothing in the differential suite can see that:
// both implementations would leave the same blank line, and agree.

/// A heading no fixture contains, so it resolves by its leaf alone.
const SECTION_SENTINEL: &str = "Zq7 Sentinel";

/// Every (fixture, section) pair, addressed the way an op addresses it.
fn each_section(f: &mut dyn FnMut(&str, &str, &SectionAddress, &Section)) {
    let mut seen = 0;
    for (rel, content) in corpus() {
        for (s, e) in find_sections(&content)
            .into_iter()
            .zip(section_outline(&content))
        {
            let addr = SectionAddress {
                path: Some(json::Value::Str(e.path.clone())),
                heading: None,
                ordinal: Some(json::Value::Int(e.ordinal as i64)),
            };
            seen += 1;
            f(&rel, &content, &addr, &s);
        }
    }
    assert!(
        seen > 100,
        "only {seen} sections exercised; corpus lookup is wrong"
    );
}

/// The document with the section's whole subtree cut out. The `\u{1}` keeps the
/// two halves from merging, so a line moved across the boundary is visible.
fn outside(content: &str, sec: &Section) -> String {
    let lines: Vec<&str> = content.split('\n').collect();
    format!(
        "{}\u{1}{}",
        lines[..sec.start].join("\n"),
        lines[sec.end + 1..].join("\n")
    )
}

#[test]
fn insert_then_delete_is_byte_identical() {
    let addr: SectionAddress = SECTION_SENTINEL.into();
    each_section(&mut |rel, content, anchor, _sec| {
        for pos in POSITIONS {
            let p = json::Value::Str((*pos).to_string());
            let Ok(added) = section_insert(
                content,
                anchor,
                Some(&p),
                Some(SECTION_SENTINEL),
                None,
                None,
            ) else {
                continue;
            };
            let back = section_delete(&added, &addr)
                .expect("the section just inserted must be addressable and removable");
            assert_eq!(
                content, back,
                "{rel}: insert {pos} then delete did not round-trip"
            );
        }
    });
}

#[test]
fn an_inserted_heading_is_a_section_at_the_level_the_position_implies() {
    each_section(&mut |rel, content, anchor, sec| {
        let before: Vec<String> = find_sections(content)
            .iter()
            .map(|s| s.text.clone())
            .collect();
        for pos in POSITIONS {
            let p = json::Value::Str((*pos).to_string());
            let Ok(added) = section_insert(
                content,
                anchor,
                Some(&p),
                Some(SECTION_SENTINEL),
                None,
                None,
            ) else {
                continue;
            };
            // The op's own promise, and `verify_heading`'s reason to exist: a
            // call that reports success has produced something the next call
            // can address. A heading written into a code fence would not be.
            let found = find_sections(&added);
            let new = found
                .iter()
                .find(|s| s.text == SECTION_SENTINEL)
                .unwrap_or_else(|| {
                    panic!("{rel}: insert {pos} reported success but wrote no section")
                });
            let want = if *pos == "before" || *pos == "after" {
                sec.level
            } else {
                sec.level + 1
            };
            assert_eq!(
                want, new.level,
                "{rel}: insert {pos} derived the wrong level"
            );
            // And every section that was there is still there, still saying
            // what it said.
            let after: Vec<String> = found
                .iter()
                .filter(|s| s.text != SECTION_SENTINEL)
                .map(|s| s.text.clone())
                .collect();
            assert_eq!(
                before, after,
                "{rel}: insert {pos} disturbed another section"
            );
        }
    });
}

#[test]
fn no_op_removes_a_section_it_was_not_asked_to_remove() {
    each_section(&mut |rel, content, addr, sec| {
        let Ok(after) = section_delete(content, addr) else {
            return;
        };
        // The subtree goes with it — that is the contract, not a loss — so what
        // must survive is every section that is neither the target nor beneath
        // it, in order, with its text intact.
        let kept: Vec<String> = find_sections(content)
            .iter()
            .filter(|s| s.start < sec.start || s.start > sec.end)
            .map(|s| s.text.clone())
            .collect();
        let left: Vec<String> = find_sections(&after)
            .iter()
            .map(|s| s.text.clone())
            .collect();
        assert_eq!(
            kept,
            left,
            "{rel}: deleting {:?} took a section with it",
            sec.slug()
        );
    });
}

#[test]
fn append_adds_to_the_body_and_replaces_none_of_it() {
    each_section(&mut |rel, content, addr, sec| {
        let Ok(after) = section_append(content, addr, Some("Zq7 appended."), None) else {
            return;
        };
        // S2 in its structural form: every line the section's own body had is
        // still there. `replace-body` is the op that discards, and this is the
        // claim that keeps `append` from quietly becoming it.
        let lines: Vec<&str> = content.split('\n').collect();
        let body: Vec<&str> = lines[sec.heading_end + 1..=sec.own_end].to_vec();
        let resolved = resolve_section(&after, addr).expect("the section survives its own append");
        let out: Vec<&str> = after.split('\n').collect();
        let new_body: Vec<&str> = out[resolved.heading_end + 1..=resolved.own_end].to_vec();
        for ln in &body {
            assert!(
                new_body.contains(ln),
                "{rel}: appending to {:?} lost the line {ln:?}",
                sec.slug()
            );
        }
        assert!(
            new_body
                .iter()
                .any(|ln| ln.trim_end_matches('\r') == "Zq7 appended."),
            "{rel}: appending to {:?} did not add the line",
            sec.slug()
        );
        // An append writes inside the section's own body and nowhere else.
        assert_eq!(
            outside(content, sec),
            outside(&after, &resolved),
            "{rel}: appending to {:?} changed bytes outside it",
            sec.slug()
        );
    });
}

#[test]
fn rename_round_trips_and_touches_only_the_heading() {
    each_section(&mut |rel, content, addr, sec| {
        let original = sec.text.clone();
        // `rename` trims what it is given, on purpose: a model handed a rename
        // quotes the line as often as it names the text, and `heading_text`
        // strips the marker and the space around it. The cost is that a heading
        // whose verbatim span is not already its addressing form — `### Setup `
        // in `corpus/sections/duplicate-siblings.md` — cannot be restored
        // through the op's own vocabulary, because the trailing space is not
        // expressible in the argument. Normalization, not loss, but not a round
        // trip either, so it is excluded rather than asserted.
        if sec.raw_text != original {
            return;
        }
        let Ok(renamed) = section_rename(content, addr, Some(SECTION_SENTINEL)) else {
            return;
        };
        let lines: Vec<&str> = content.split('\n').collect();
        let out: Vec<&str> = renamed.split('\n').collect();
        assert_eq!(
            lines.len(),
            out.len(),
            "{rel}: rename changed the line count"
        );
        for (k, (a, b)) in lines.iter().zip(&out).enumerate() {
            if k >= sec.start && k <= sec.heading_end {
                continue;
            }
            assert_eq!(a, b, "{rel}: rename changed line {k}, outside the heading");
        }
        // Renaming back restores the bytes, which is what catches a rebuild
        // that drops a closing hash run, a setext underline's width, or the
        // `\r` of a CRLF document.
        let back = section_rename(&renamed, &SECTION_SENTINEL.into(), Some(&original))
            .expect("the renamed section must be addressable");
        assert_eq!(
            content, back,
            "{rel}: rename to {SECTION_SENTINEL:?} and back lost bytes"
        );
    });
}

#[test]
fn set_level_round_trips_and_moves_only_headings() {
    each_section(&mut |rel, content, addr, sec| {
        // Every heading line in the document, both ends of a setext one. Only
        // these may differ after a level change; anything else is prose the op
        // had no business touching.
        let heads: Vec<usize> = find_sections(content)
            .iter()
            .flat_map(|s| [s.start, s.heading_end])
            .collect();
        for want in 1..=6usize {
            if want == sec.level {
                continue;
            }
            let level = json::Value::Int(want as i64);
            let Ok(moved) = section_set_level(content, addr, Some(&level), true) else {
                continue;
            };
            let lines: Vec<&str> = content.split('\n').collect();
            let out: Vec<&str> = moved.split('\n').collect();
            assert_eq!(
                lines.len(),
                out.len(),
                "{rel}: set-level changed the line count"
            );
            for (k, (a, b)) in lines.iter().zip(&out).enumerate() {
                if heads.contains(&k) {
                    continue;
                }
                assert_eq!(
                    a, b,
                    "{rel}: set-level {want} rewrote line {k}, not a heading"
                );
            }
            // And back. The address is rebuilt from the moved document rather
            // than reused, because promoting a section changes its path — which
            // is the whole reason the level is derived and never remembered.
            let there = find_sections(&moved)
                .into_iter()
                .find(|s| s.start == sec.start)
                .expect("the section is still at its own line");
            // set-level is not invertible in general, and that is the
            // operation's meaning rather than a defect: subtree membership is
            // derived from the document, so promoting a section adopts the
            // siblings that follow it, and demoting it back takes them down
            // with it. `bench/synthetic/duplicate-columns.md` does exactly
            // this. Assert the round trip only where the subtree the second
            // call will move is the one the first call moved.
            if there.end != sec.end {
                continue;
            }
            // Promotion can also make two sections share a path, and an
            // ambiguous address is a refusal rather than a property.
            let slug = there.slug();
            if section_outline(&moved)
                .iter()
                .filter(|e| e.path == slug)
                .count()
                != 1
            {
                continue;
            }
            let back_addr = SectionAddress {
                path: Some(json::Value::Str(slug)),
                heading: None,
                ordinal: None,
            };
            let home = json::Value::Int(sec.level as i64);
            let Ok(back) = section_set_level(&moved, &back_addr, Some(&home), true) else {
                continue;
            };
            assert_eq!(content, back, "{rel}: set-level {want} and back lost bytes");
        }
    });
}

#[test]
fn replace_body_keeps_the_heading_and_every_subsection() {
    each_section(&mut |rel, content, addr, sec| {
        let Ok(after) = section_replace_body(content, addr, Some("Zq7 replaced."), true, None)
        else {
            return;
        };
        // The op is destructive by design, and precisely bounded: the heading
        // stays, the subtree stays, and the section's OWN prose is what goes.
        // `own_end` against `end` a third time.
        let before: Vec<String> = find_sections(content)
            .iter()
            .map(|s| s.text.clone())
            .collect();
        let left: Vec<String> = find_sections(&after)
            .iter()
            .map(|s| s.text.clone())
            .collect();
        assert_eq!(
            before, left,
            "{rel}: replace-body changed the section structure"
        );
        let resolved = resolve_section(&after, addr).expect("the section survives");
        assert_eq!(
            outside(content, sec),
            outside(&after, &resolved),
            "{rel}: replace-body on {:?} changed bytes outside it",
            sec.slug()
        );
    });
}

// --------------------------------------------------------------------------
// describe_change (§9 criterion 11)
// --------------------------------------------------------------------------
// The response shape, not the document. These are the claims that hold however
// the description is worded, and the reason they are here rather than only in
// the differential suite is that the oracle could be wrong in the one direction
// that matters: a description asserting a change the bytes do not support is a
// worse failure than one that says nothing, because it is the exact input that
// makes a model stop checking. Both implementations agreeing on such a sentence
// would prove only that both are lying.

/// Every heading `text` the after-document actually contains.
fn heading_texts(content: &str) -> Vec<String> {
    find_sections(content)
        .iter()
        .map(|s| s.text.clone())
        .collect()
}

/// Every `added the section "X"` claim in a description.
fn claimed_additions(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut rest = text;
    while let Some(i) = rest.find("added the section \"") {
        rest = &rest[i + "added the section \"".len()..];
        match rest.find('"') {
            Some(j) => {
                out.push(rest[..j].to_string());
                rest = &rest[j + 1..];
            }
            None => break,
        }
    }
    out
}

#[test]
fn a_description_never_claims_a_heading_the_document_does_not_have() {
    // The property the whole response shape rests on. If this can fail, every
    // other guarantee about the result is worthless.
    let mut checked = 0;
    let after_pos = json::Value::Str("after".to_string());
    let child_pos = json::Value::Str("last-child".to_string());
    each_section(&mut |rel, content, addr, _sec| {
        for after in [
            section_insert(
                content,
                addr,
                Some(&after_pos),
                Some("Zq7 Added"),
                None,
                None,
            )
            .ok(),
            section_insert(
                content,
                addr,
                Some(&child_pos),
                Some("Zq7 Added"),
                None,
                None,
            )
            .ok(),
            section_rename(content, addr, Some("Zq7 Renamed")).ok(),
            section_delete(content, addr).ok(),
        ]
        .into_iter()
        .flatten()
        {
            let text = describe_change(content, &after);
            let present = heading_texts(&after);
            for name in claimed_additions(&text) {
                assert!(
                    present.contains(&name),
                    "{rel}: description claims it added {name:?}, which is not in the result\n{text}"
                );
            }
            checked += 1;
        }
    });
    assert!(checked > 100, "only {checked} descriptions exercised");
}

#[test]
fn the_no_op_sentence_appears_exactly_when_nothing_changed() {
    const NO_OP: &str = "Applied, but the document is unchanged.";
    let mut changed = 0;
    for (rel, content) in corpus() {
        assert_eq!(
            describe_change(&content, &content),
            NO_OP,
            "{rel}: an identity edit must say so rather than report the call back"
        );
        // And the converse: any real difference must not be reported as a
        // no-op. The first two are edits no op can make -- there is nothing
        // before the first heading in any fixture -- and the third is an op.
        let first = section_outline(&content).first().map(|e| e.path.clone());
        let seeded = first.and_then(|p| {
            let addr: SectionAddress = p.as_str().into();
            let pos = json::Value::Str("after".to_string());
            section_insert(
                &content,
                &addr,
                Some(&pos),
                Some(SECTION_SENTINEL),
                None,
                None,
            )
            .ok()
        });
        for after in [
            format!("zq7 preamble.\n\n{content}"),
            format!("{content}\nzq7 trailer.\n"),
        ]
        .into_iter()
        .chain(seeded)
        {
            if after == content {
                continue;
            }
            let text = describe_change(&content, &after);
            assert_ne!(text, NO_OP, "{rel}: a real change reported as a no-op");
            assert!(
                text.starts_with("Applied:"),
                "{rel}: a description of a real change must lead with it\n{text}"
            );
            changed += 1;
        }
    }
    assert!(changed > 40, "only {changed} real changes exercised");
}

#[test]
fn a_description_is_one_line_and_never_echoes_the_document() {
    // §5.4 / §9 criterion 11: returning the description *alongside* the outline
    // measured identically to returning the outline alone, so the omission is
    // the requirement. A port that "helpfully" appends context re-opens the
    // finding, and this is what says so.
    let mut checked = 0;
    each_section(&mut |rel, content, addr, sec| {
        let Ok(after) = section_append(content, addr, Some("Zq7 appended."), None) else {
            return;
        };
        let text = describe_change(content, &after);
        assert!(
            !text.contains('\n'),
            "{rel}: a description must stay one line\n{text}"
        );
        // It may name a heading — that is the address the model needs. It may
        // not carry the body of one.
        assert!(
            !text.contains("Zq7 appended."),
            "{rel}: the description echoes the text it just wrote\n{text}"
        );
        for other in heading_texts(&after) {
            if other != sec.text && text.contains(&format!("\"{other}\"")) {
                panic!("{rel}: description names an unrelated section {other:?}\n{text}");
            }
        }
        checked += 1;
    });
    assert!(checked > 100, "only {checked} descriptions exercised");
}

// --------------------------------------------------------------------------
// frontmatter
// --------------------------------------------------------------------------
//
// The fourth restatement, and the one with the narrowest window: a frontmatter
// op may rewrite **one line**. The other three families splice a span, so
// "bytes outside the range are unchanged" is the strongest thing there is to
// say; here the range is a single line of a block whose every other line is
// load-bearing. `corpus/frontmatter/rich.md:37-43` names five things that must
// survive a `frontmatter-set` — key order, a leading comment, an inline comment
// on a sibling, two block-scalar styles and one quoted key — and they are not
// five assertions below. They are lines, and an edit that moves exactly one
// line cannot have touched any of them.
//
// A parse-and-serialize implementation passes every differential case and fails
// every test here, which is precisely why these are not in `difftest.py`.

/// Every fixture that has a YAML block, with it parsed.
///
/// TOML is excluded because the ops refuse it, which is asserted on its own
/// below rather than mixed in here as a skip.
fn each_front(f: &mut dyn FnMut(&str, &str, &FrontMatter)) {
    let mut seen = 0;
    for (rel, content) in corpus() {
        let fm = find_frontmatter(&content);
        if !fm.present || fm.fmt != Some(Fmt::Yaml) {
            continue;
        }
        seen += 1;
        f(&rel, &content, &fm);
    }
    assert!(
        seen > 5,
        "only {seen} blocks exercised; corpus lookup is wrong"
    );
}

const FRONT_PROBE: &str = "zzq_roundtrip_probe";

fn front_key(p: &[Seg]) -> json::Value {
    json::Value::Str(format_path(p))
}

/// Set then delete restores the file byte for byte, for every block.
///
/// `add_then_remove_is_byte_identical`'s bet one family over, and what
/// PLAN.md:1276-1278 asks for: the two ops are tested as inverses rather than
/// each against a golden, because a golden can only say what one edit looks
/// like and the failure this family is built around is a byte somewhere *else*
/// in the block. A dropped `\r`, a comment re-emitted as a value, a block
/// scalar re-indented — none of them are near the key that was named, and all
/// of them show up here.
///
/// `absent.md` is skipped for a stated reason rather than by accident: a set
/// there *creates* the delimiters and delete does not un-create them, so the
/// pair is not an inverse on that file and asserting it would be asserting
/// something untrue.
#[test]
fn a_frontmatter_set_then_delete_is_byte_identical() {
    let mut checked = 0;
    let key = json::Value::Str(FRONT_PROBE.to_string());
    let value = json::Value::Str("x".to_string());
    each_front(&mut |rel, content, _fm| {
        let added = match frontmatter_set(content, Some(&key), Some(&value)) {
            Ok(s) => s,
            Err(e) => panic!("{rel}: set refused: {}", e.0),
        };
        assert_ne!(added, content, "{rel}: set wrote nothing");
        let back = match frontmatter_delete(&added, Some(&key)) {
            Ok(s) => s,
            Err(e) => panic!("{rel}: delete refused: {}", e.0),
        };
        assert_eq!(back, content, "{rel}: set+delete did not round-trip");
        checked += 1;
    });
    assert!(checked > 5, "only {checked} round-trips exercised");
}

/// Create/update intent is a precondition, not permission to retarget.
#[test]
fn frontmatter_existence_guards_refuse_without_writing() {
    let content = "---\nbuild:\n  target: release\n---\n\n# Project\n";
    let existing = json::Value::Str("build.target".to_string());
    let absent = json::Value::Str("build.cache".to_string());
    let value = json::Value::Bool(true);
    let yes = json::Value::Bool(true);

    let create_wrong =
        frontmatter_set_guarded(content, Some(&existing), Some(&value), Some(&yes), None)
            .unwrap_err();
    assert!(create_wrong
        .message()
        .contains("requires an absent frontmatter key"));
    assert_eq!(
        create_wrong.repair().map(|r| r.code.as_str()),
        Some("frontmatter_key_exists")
    );

    let update_wrong =
        frontmatter_set_guarded(content, Some(&absent), Some(&value), None, Some(&yes))
            .unwrap_err();
    assert!(update_wrong
        .message()
        .contains("requires an existing frontmatter key"));
    assert_eq!(
        update_wrong.repair().map(|r| r.code.as_str()),
        Some("frontmatter_key_missing")
    );

    let created =
        frontmatter_set_guarded(content, Some(&absent), Some(&value), Some(&yes), None).unwrap();
    assert_eq!(
        created,
        frontmatter_set(content, Some(&absent), Some(&value)).unwrap()
    );

    let updated =
        frontmatter_set_guarded(content, Some(&existing), Some(&value), None, Some(&yes)).unwrap();
    assert_eq!(
        updated,
        frontmatter_set(content, Some(&existing), Some(&value)).unwrap()
    );
}

/// A set rewrites the key's own line and no other, for every settable key.
///
/// The containers are the other half of the claim, and they are counted rather
/// than skipped: `build` and `tags` hold things, and a set that flattened one
/// to a scalar would delete what is under it and *still* pass a one-line window
/// check, because the window would be the lines it deleted.
#[test]
fn a_frontmatter_set_moves_exactly_one_line() {
    let mut settable = 0;
    let mut refused = 0;
    let value = json::Value::Str("zzqprobe".to_string());
    each_front(&mut |rel, content, fm| {
        let before: Vec<&str> = content.split('\n').collect();
        let order: Vec<Vec<Seg>> = fm.entries.iter().map(|e| e.path.clone()).collect();
        for e in &fm.entries {
            let key = front_key(&e.path);
            let name = format_path(&e.path);
            let after = match frontmatter_set(content, Some(&key), Some(&value)) {
                Ok(s) => s,
                Err(err) => {
                    refused += 1;
                    // A container is the only thing allowed to refuse here.
                    // Anything else is a key the family can address and cannot
                    // edit, which is the shape of refusal §5.3 exists to rule
                    // out. (A dotted name is the second allowed case: the path
                    // round-trips to something that addresses a different key.)
                    assert!(
                        !matches!(e.kind, Kind::Scalar | Kind::Null) || name.contains('.'),
                        "{rel}: {name} is addressable and unsettable: {}",
                        err.0
                    );
                    continue;
                }
            };
            settable += 1;
            let lines: Vec<&str> = after.split('\n').collect();
            let moved: Vec<usize> = (0..before.len().max(lines.len()))
                .filter(|&i| before.get(i) != lines.get(i))
                .collect();
            // Against the line the *address* resolves to, not `e.line`. A key
            // written twice in one block has two entries and one address:
            // `by_path` takes the last, the way a Python dict comprehension
            // does, so a set on the first one's path rewrites the second one's
            // line. That is the behaviour, and `bench/synthetic/front-dupes.md`
            // is the fixture that falsified the simpler claim.
            let target = fm.by_path(&e.path).expect("its own path resolves").line;
            assert_eq!(moved, vec![target], "{rel}: {name} moved {moved:?}");
            let now: Vec<Vec<Seg>> = find_frontmatter(&after)
                .entries
                .iter()
                .map(|x| x.path.clone())
                .collect();
            assert_eq!(now, order, "{rel}: {name} reordered the block");
        }
    });
    assert!(
        settable > 20 && refused > 5,
        "{settable} settable / {refused} containers is not a sweep"
    );
}

/// Absent, empty and null are three states, not two spellings of falsy.
///
/// `corpus/frontmatter/absent.md:17` and `empty.md:6` both require a caller to
/// tell absent from empty, and `rich.md:52` requires null to be distinct from
/// the empty string. Both are cheap to lose — one `if entries.is_empty()`
/// anywhere in the read path collapses the first pair, and any round trip
/// through a YAML loader collapses the second — so they are asserted at the
/// boundary a caller actually sees.
#[test]
fn absent_empty_and_null_stay_three_distinct_states() {
    let by_rel: std::collections::BTreeMap<String, String> = corpus().into_iter().collect();
    let read = |rel: &str| -> &String { &by_rel[rel] };

    let states: Vec<&str> = [
        "corpus/frontmatter/absent.md",
        "corpus/frontmatter/empty.md",
        "corpus/frontmatter/rich.md",
    ]
    .iter()
    .map(|rel| {
        frontmatter_get(read(rel), None)
            .expect("read refused")
            .state
    })
    .collect();
    assert_eq!(states, vec!["absent", "empty", "present"]);

    let shapes = frontmatter_get(read("bench/synthetic/front-shapes.md"), None).unwrap();
    let by: std::collections::BTreeMap<&str, &FrontKey> =
        shapes.keys.iter().map(|k| (k.path.as_str(), k)).collect();
    assert_eq!(by["empty_null"].kind, "null");
    assert_eq!(by["empty_null"].value, "");
    // The quotes are part of the value. A renderer that stripped them would be
    // telling the model the document holds something it does not.
    assert_eq!(by["empty_string"].kind, "scalar");
    assert_eq!(by["empty_string"].value, "\"\"");

    // And setting a key to null writes the key rather than removing it, and
    // writes no quotes -- which would make it the empty string instead.
    let rich = read("corpus/frontmatter/rich.md");
    let key = json::Value::Str("title".to_string());
    let cleared = frontmatter_set(rich, Some(&key), Some(&json::Value::Null)).unwrap();
    let got = frontmatter_get(&cleared, None).unwrap();
    let title = got
        .keys
        .iter()
        .find(|k| k.path == "title")
        .expect("title vanished");
    assert_eq!((title.kind, title.value.as_str()), ("null", ""));
    assert!(
        cleared.replace('\r', "").contains("title:\n"),
        "a key set to null gained a trailing space"
    );
}

/// TOML is refused by every frontmatter op, and by nothing else.
///
/// `corpus/hazards/toml-frontmatter.md` names the failure: a YAML parser
/// accepting some of this by accident and writing back a mangled block.
/// `scan::frontmatter_span` accepts `+++` on purpose — skipping a TOML block is
/// as correct as skipping a YAML one — so the refusal has to be the ops' own,
/// and the file's tables and sections have to keep working around it.
#[test]
fn toml_frontmatter_is_refused_while_the_other_families_keep_working() {
    let by_rel: std::collections::BTreeMap<String, String> = corpus().into_iter().collect();
    let rel = "corpus/hazards/toml-frontmatter.md";
    let content = &by_rel[rel];
    let key = json::Value::Str("title".to_string());
    let value = json::Value::Str("x".to_string());

    for (op, err) in [
        (
            "frontmatter-set",
            frontmatter_set(content, Some(&key), Some(&value)).err(),
        ),
        (
            "frontmatter-delete",
            frontmatter_delete(content, Some(&key)).err(),
        ),
        ("frontmatter-get", frontmatter_get(content, None).err()),
    ] {
        // A refusal returns no document at all, which is the guarantee that
        // matters: there is no partially-edited TOML block to write back. The
        // `Result` is what makes that structural rather than asserted.
        let err = err.unwrap_or_else(|| panic!("{op} accepted a TOML block"));
        assert!(err.0.contains("TOML"), "{op}: {}", err.0);
        if op != "frontmatter-get" {
            assert!(
                err.0.contains("---") && err.0.contains("+++"),
                "{op} does not name both formats: {}",
                err.0
            );
        }
    }
    assert!(
        render_frontmatter(content, rel).contains("TOML"),
        "the renderer says nothing rather than TOML"
    );

    // The other half of what the fixture is for: a TOML block stops the
    // frontmatter ops and nothing else.
    assert!(!section_outline(content).is_empty());
    assert!(!find_tables(content).is_empty());
}

/// The read says what the summary withholds, on every block that has a value.
///
/// `render_frontmatter` omits scalar values by design — Arm B's premise is that
/// the model addresses an edit it cannot see — and F-frontmatter measured what
/// that costs when the family publishes no way to ask: `set-dana-role` needs to
/// know which of two authors is Dana, the summary lists `authors[0].name` and
/// `authors[1].name` with no values, and the two arms guessed 3/10 and 7/10 in
/// mirror image. So the property is a *difference* between two renderers, and
/// it is asserted as one rather than against a fixed string.
#[test]
fn the_frontmatter_read_supplies_what_the_summary_omits() {
    let mut checked = 0;
    each_front(&mut |rel, content, fm| {
        let summary = render_frontmatter(content, rel);
        let read = render_frontmatter_get(content, rel, None).expect("read refused");
        for e in &fm.entries {
            // A sequence item that is itself a map has no value of its own:
            // `value` holds the mapping's first line, and the renderer
            // signposts to the children that carry the facts instead.
            if !matches!(e.kind, Kind::Scalar | Kind::Item)
                || e.value.is_empty()
                || (e.kind == Kind::Item && !fm.children_of(&e.path).is_empty())
            {
                continue;
            }
            let name = format_path(&e.path);
            assert!(
                read.lines()
                    .any(|ln| ln.starts_with(&format!("  {name:<24} "))
                        && ln.trim_end().ends_with(&e.value)),
                "{rel}: the read does not say what {name} holds"
            );
            checked += 1;
        }
        // A read is a read. This is the claim `grade.py` relies on when it lets
        // a `frontmatter_get` call pass through without touching the document.
        assert!(!summary.is_empty());
    });
    assert!(checked > 20, "only {checked} values exercised");

    let by_rel: std::collections::BTreeMap<String, String> = corpus().into_iter().collect();
    let rel = "corpus/frontmatter/rich.md";
    let rich = &by_rel[rel];
    let typed = frontmatter_get(rich, None).unwrap();
    let version = typed.keys.iter().find(|key| key.path == "version").unwrap();
    let jobs = typed
        .keys
        .iter()
        .find(|key| key.path == "build.jobs")
        .unwrap();
    let draft = typed.keys.iter().find(|key| key.path == "draft").unwrap();
    assert_eq!(
        version.value_type, "string",
        "0.4.1 must not become a number"
    );
    assert_eq!(jobs.value_type, "integer");
    assert_eq!(draft.value_type, "boolean");
    let read = render_frontmatter_get(rich, rel, None).unwrap();
    assert!(!render_frontmatter(rich, rel).contains("Dana"));
    assert!(read.contains("Dana") && read.contains("Peter"));
    // The quoting is not stripped, and a block scalar's body is on the lines
    // below its key -- so a renderer printing `value` alone would answer `|` to
    // "what is in `multiline`".
    assert!(read.contains("\"value: with a colon\""));
    assert!(read.contains("Second line, newlines preserved."));

    // A subtree read, which is the call `set-dana-role` actually wants.
    let sub = json::Value::Str("authors".to_string());
    let narrowed = render_frontmatter_get(rich, rel, Some(&sub)).unwrap();
    assert!(narrowed.contains("Dana") && !narrowed.contains("quoted_key"));

    // Absent and empty stay distinguishable through the renderer, which is what
    // `absent.md:17` and `empty.md:6` require a caller to be able to do.
    let a = render_frontmatter_get(&by_rel["corpus/frontmatter/absent.md"], "a", None).unwrap();
    let e = render_frontmatter_get(&by_rel["corpus/frontmatter/empty.md"], "e", None).unwrap();
    assert_ne!(a, e, "absent and empty read the same");
}

/// The frontmatter describer names the key; `describe_change` cannot.
///
/// This is S14's finding as an assertion, and the reason the two functions are
/// siblings rather than one. `describe_change` is derived from the two
/// documents, and the block is outside every heading, so it reports every edit
/// here as "changed text outside any heading" — true, and useless: a model that
/// asked for `build.jobs` and typed `build.jobz` cannot tell from it that it
/// added a key. The contrast is measured on the same pair of documents rather
/// than asserted, so a `describe_change` that one day *could* say it would
/// retire this test by failing it.
///
/// The value is quoted back on purpose, which is why this is not
/// `a_description_is_one_line_and_never_echoes_the_document`: a section body is
/// prose and a frontmatter value is a scalar the model just sent. What still
/// holds is the line count — `Entry::value` is the text on the key's own line,
/// so a description that grew a second line would mean a block scalar's body
/// had leaked into it.
#[test]
fn a_frontmatter_description_names_the_key_where_describe_change_cannot() {
    let mut checked = 0;
    let mut contrasted = 0;
    let value = json::Value::Str("zq7probe".to_string());
    each_front(&mut |rel, content, fm| {
        for e in &fm.entries {
            let key = front_key(&e.path);
            let name = format_path(&e.path);
            let Ok(after) = frontmatter_set(content, Some(&key), Some(&value)) else {
                continue;
            };
            if after == *content {
                continue;
            }
            let text = describe_frontmatter_change(content, &after);
            assert!(!text.contains('\n'), "{rel}: not one line\n{text}");
            assert!(text.starts_with("Applied"), "{rel}: {text}");
            // A sequence item is the one kind with no key to name: `authors[0]`
            // is a position, and `_front_notes` skips `item` in the "set" note
            // for that reason. It still has to say the block changed rather than
            // inheriting `describe_change`'s sentence about headings.
            if e.kind == Kind::Item {
                assert!(
                    text.contains("frontmatter"),
                    "{rel}: an item edit is not described as one\n{text}"
                );
            } else {
                assert!(
                    text.contains(&name),
                    "{rel}: the description does not name the key\n{text}"
                );
            }
            // The whole of what the sibling buys, on the same two documents.
            let vague = describe_change(content, &after);
            assert!(
                !text.contains("outside any heading"),
                "{rel}: the frontmatter describer fell back to the vague sentence\n{text}"
            );
            if vague.contains("outside any heading") {
                assert!(
                    !vague.contains(&name) || e.kind == Kind::Item,
                    "{rel}: describe_change names the key after all; fold the two\n{vague}"
                );
                contrasted += 1;
            }
            checked += 1;
        }
    });
    assert!(checked > 20, "only {checked} descriptions exercised");
    assert!(
        contrasted > 20,
        "only {contrasted} of {checked} showed the contrast the sibling exists for"
    );
}
