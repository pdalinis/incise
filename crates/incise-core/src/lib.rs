//! incise's core: content-addressed, byte-preserving markdown edits.
//!
//! The premise, measured rather than assumed (`bench/FINDINGS.md`): a local
//! small model editing markdown as text corrupts it. Tables were 19% correct
//! with 28% data loss when edited directly; the same model driving these ops
//! scores 60/60 with zero data loss. This crate is the half that has to be
//! dependable, so its rules are the ones the benchmark forced:
//!
//! * **Addressing is semantic** (§5.1) — heading paths, column values, item
//!   text. Never a line number, which is stale the moment anything above it
//!   moves.
//! * **Edits splice bytes** (§5.2). Everything outside the targeted range is
//!   byte-identical afterwards; the one exception is re-padding an aligned
//!   table, which is scoped to that table's own lines.
//! * **Refusals are the product** (§5.3). An [`error::OpError`] message is
//!   written for a model to recover from in one turn, and 75% of them do.
//!
//! `bench/incise_ops.py` is the differential-testing oracle (§9 criterion 7):
//! where a comment here cites a corpus fixture, that fixture is the test.

pub mod args;
pub mod describe;
pub mod error;
pub mod front;
pub mod heading;
pub mod json;
pub mod list;
pub mod ops;
pub mod scan;
pub mod similar;
pub mod table;

pub use describe::describe_change;
pub use error::{OpError, Result};
pub use front::{find_frontmatter, format_path, parse_path, Entry, Fmt, FrontMatter, Kind, Seg};
pub use heading::{find_sections, heading_gap, inert_headings, Section};
pub use ops::dispatch::{apply_op, OPS};
pub use ops::frontmatter::{
    describe_frontmatter_change, frontmatter_delete, frontmatter_get, frontmatter_set,
    render_frontmatter, render_frontmatter_get, FrontKey, FrontState,
};
pub use ops::section::{
    render_section_outline, resolve_section, section_append, section_delete, section_insert,
    section_outline, section_rename, section_replace_body, section_set_level, SectionAddress,
    SectionEntry, POSITIONS,
};
pub use ops::table::{
    caption, heading_path, list_tables, render_table_get, render_table_list, render_table_rows,
    resolve_row, resolve_table, table_add_row, table_delete_row, table_get, table_realign,
    table_update_cell, Position, TableAddress, TableEntry, TableRows, Values,
};
pub use table::{find_tables, Table};
