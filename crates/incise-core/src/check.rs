//! Document-level structural checks over the same parsers the edit operations use.
//!
//! This is deliberately not a Markdown style linter. A finding names a condition
//! that makes an Incise address ambiguous, makes an edit refuse, or has a
//! deterministic Incise repair that still requires explicit intent. The checker
//! never reconstructs the document and [`fix_safe`] applies only repairs whose
//! class is [`RepairClass::Automatic`]. That allowlist starts empty.

use std::collections::BTreeMap;

use crate::front::{find_frontmatter, format_path, Fmt, Seg};
use crate::json::{self, Value};
use crate::ops::table::{list_tables, table_realign, TableAddress};
use crate::table::{find_tables, split_row};

pub const CHECK_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Severity {
    Info,
    Warning,
    Error,
}

impl Severity {
    pub fn as_str(self) -> &'static str {
        match self {
            Severity::Info => "info",
            Severity::Warning => "warning",
            Severity::Error => "error",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RepairClass {
    Automatic,
    Explicit,
    Manual,
}

impl RepairClass {
    pub fn as_str(self) -> &'static str {
        match self {
            RepairClass::Automatic => "automatic",
            RepairClass::Explicit => "explicit",
            RepairClass::Manual => "manual",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CheckSpan {
    pub start: usize,
    pub end: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CheckAddress {
    Table { heading: String, ordinal: usize },
    Frontmatter { key: String },
}

#[derive(Clone, Debug, PartialEq)]
pub struct CheckRepair {
    pub operation: &'static str,
    pub arguments: Value,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Finding {
    pub code: &'static str,
    pub severity: Severity,
    pub message: String,
    pub address: CheckAddress,
    pub span: CheckSpan,
    pub repair_class: RepairClass,
    pub repair: Option<CheckRepair>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CheckReport {
    pub findings: Vec<Finding>,
}

impl CheckReport {
    pub fn status(&self) -> &'static str {
        self.findings
            .iter()
            .map(|finding| finding.severity)
            .max()
            .map(Severity::as_str)
            .unwrap_or("clean")
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SafeFixResult {
    pub content: String,
    pub report: CheckReport,
    pub repaired: Vec<&'static str>,
}

/// Check one document without changing it.
pub fn check_document(content: &str) -> CheckReport {
    let tables = find_tables(content);
    let entries = list_tables(content);
    let mut findings = Vec::new();

    for (table, entry) in tables.iter().zip(entries.iter()) {
        let address = CheckAddress::Table {
            heading: entry.heading.clone(),
            ordinal: entry.ordinal,
        };
        let span = line_span(content, table.start, table.end);
        let counts: Vec<usize> = table
            .lines
            .iter()
            .map(|line| split_row(line).len())
            .collect();
        let want = counts.first().copied().unwrap_or(0);
        let rectangular = counts.iter().all(|count| *count == want);

        if let Some((index, got)) = counts.iter().enumerate().find(|(_, count)| **count != want) {
            let place = if index == 1 {
                "the delimiter row".to_string()
            } else {
                format!("row {}", index.saturating_sub(1))
            };
            findings.push(Finding {
                code: "table.non_rectangular",
                severity: Severity::Error,
                message: format!(
                    "table under \"{}\" ordinal {} is not rectangular: the header has {want} columns but {place} has {got}.",
                    entry.heading, entry.ordinal
                ),
                address: address.clone(),
                span: span.clone(),
                repair_class: RepairClass::Manual,
                repair: None,
            });
        }

        let has_crlf = table.lines.iter().any(|line| line.ends_with('\r'));
        let has_lf = table.lines.iter().any(|line| !line.ends_with('\r'));
        if has_crlf && has_lf {
            findings.push(Finding {
                code: "table.mixed_line_endings",
                severity: Severity::Error,
                message: format!(
                    "table under \"{}\" ordinal {} mixes CRLF and LF line endings.",
                    entry.heading, entry.ordinal
                ),
                address: address.clone(),
                span: span.clone(),
                repair_class: RepairClass::Manual,
                repair: None,
            });
        }

        let mut indents: Vec<&str> = table
            .lines
            .iter()
            .map(|line| &line[..line.len() - line.trim_start().len()])
            .collect();
        indents.sort_unstable();
        indents.dedup();
        let consistent_indent = indents.len() == 1;
        if !consistent_indent {
            findings.push(Finding {
                code: "table.mixed_indentation",
                severity: Severity::Error,
                message: format!(
                    "table under \"{}\" ordinal {} has inconsistent structural indentation.",
                    entry.heading, entry.ordinal
                ),
                address: address.clone(),
                span: span.clone(),
                repair_class: RepairClass::Manual,
                repair: None,
            });
        }

        let mut column_counts: BTreeMap<String, usize> = BTreeMap::new();
        for column in table.columns() {
            *column_counts.entry(column).or_default() += 1;
        }
        for (column, count) in column_counts.into_iter().filter(|(_, count)| *count > 1) {
            findings.push(Finding {
                code: "table.duplicate_column",
                severity: Severity::Warning,
                message: format!(
                    "table under \"{}\" ordinal {} has duplicate column \"{column}\" ({count} occurrences), so that name does not identify one cell.",
                    entry.heading, entry.ordinal
                ),
                address: address.clone(),
                span: span.clone(),
                repair_class: RepairClass::Manual,
                repair: None,
            });
        }

        if rectangular
            && !(has_crlf && has_lf)
            && consistent_indent
            && (!table.is_aligned() || table.has_tabs())
        {
            let table_address = TableAddress {
                heading: Some(Value::Str(entry.heading.clone())),
                ordinal: Some(Value::Int(entry.ordinal as i64)),
            };
            if table_realign(content, &table_address).is_ok() {
                let arguments = Value::Object(vec![(
                    "table".to_string(),
                    Value::Object(vec![
                        ("heading".to_string(), Value::Str(entry.heading.clone())),
                        ("ordinal".to_string(), Value::Int(entry.ordinal as i64)),
                    ]),
                )]);
                findings.push(Finding {
                    code: "table.ragged_alignment",
                    severity: Severity::Info,
                    message: format!(
                        "table under \"{}\" ordinal {} is rectangular but not uniformly aligned; use table-realign only if reformatting the whole table is intended.",
                        entry.heading, entry.ordinal
                    ),
                    address: address.clone(),
                    span: span.clone(),
                    repair_class: RepairClass::Explicit,
                    repair: Some(CheckRepair {
                        operation: "table-realign",
                        arguments,
                    }),
                });
            }
        }
    }

    let front = find_frontmatter(content);
    if front.present && front.fmt == Some(Fmt::Yaml) {
        let mut distinct: Vec<(Vec<Seg>, Vec<usize>)> = Vec::new();
        for (index, entry) in front.entries.iter().enumerate() {
            match distinct.iter_mut().find(|(path, _)| *path == entry.path) {
                Some((_, indices)) => indices.push(index),
                None => distinct.push((entry.path.clone(), vec![index])),
            }
        }
        for (path, indices) in distinct
            .into_iter()
            .filter(|(_, indices)| indices.len() > 1)
        {
            let first = &front.entries[indices[0]];
            let last = &front.entries[*indices.last().unwrap()];
            let key = format_path(&path);
            findings.push(Finding {
                code: "frontmatter.duplicate_path",
                severity: Severity::Warning,
                message: format!(
                    "frontmatter path \"{key}\" appears {} times; Incise edits the last occurrence, while other YAML readers may disagree.",
                    indices.len()
                ),
                address: CheckAddress::Frontmatter { key },
                span: line_span(content, first.line, last.end),
                repair_class: RepairClass::Manual,
                repair: None,
            });
        }
    }

    findings.sort_by(|left, right| {
        (left.span.start, left.code, address_sort_key(&left.address)).cmp(&(
            right.span.start,
            right.code,
            address_sort_key(&right.address),
        ))
    });
    CheckReport { findings }
}

/// Apply every allowlisted automatic repair as one in-memory transaction.
///
/// No v1 rule is automatic. Keeping the transaction boundary in the initial
/// API makes adding the first proven rule an allowlist change rather than a new
/// mutating interface, while this no-op behavior is pinned by tests.
pub fn fix_safe(content: &str) -> SafeFixResult {
    SafeFixResult {
        content: content.to_string(),
        report: check_document(content),
        repaired: Vec::new(),
    }
}

/// Canonical JSON for the core-owned part of a report.
///
/// The CLI adds path and content hash around this object. The differential
/// harness compares this exact rendering with the independent Python oracle.
pub fn render_check_report(report: &CheckReport) -> String {
    let findings = render_check_findings(report);
    format!(
        "{{\"schema_version\": {CHECK_SCHEMA_VERSION}, \"status\": {}, \"findings\": {findings}}}",
        json::dumps_str(report.status())
    )
}

/// Canonical JSON array for embedding the findings in a host-owned envelope.
pub fn render_check_findings(report: &CheckReport) -> String {
    let findings = report
        .findings
        .iter()
        .map(render_finding)
        .collect::<Vec<_>>()
        .join(", ");
    format!("[{findings}]")
}

fn render_finding(finding: &Finding) -> String {
    let repair = match &finding.repair {
        None => "null".to_string(),
        Some(repair) => format!(
            "{{\"operation\": {}, \"arguments\": {}}}",
            json::dumps_str(repair.operation),
            render_json_value(&repair.arguments)
        ),
    };
    format!(
        "{{\"code\": {}, \"severity\": {}, \"message\": {}, \"address\": {}, \
         \"span\": {{\"start\": {}, \"end\": {}}}, \"repair_class\": {}, \"repair\": {repair}}}",
        json::dumps_str(finding.code),
        json::dumps_str(finding.severity.as_str()),
        json::dumps_str(&finding.message),
        render_address(&finding.address),
        finding.span.start,
        finding.span.end,
        json::dumps_str(finding.repair_class.as_str()),
    )
}

fn render_address(address: &CheckAddress) -> String {
    match address {
        CheckAddress::Table { heading, ordinal } => format!(
            "{{\"table\": {{\"heading\": {}, \"ordinal\": {ordinal}}}}}",
            json::dumps_str(heading)
        ),
        CheckAddress::Frontmatter { key } => {
            format!("{{\"frontmatter\": {{\"key\": {}}}}}", json::dumps_str(key))
        }
    }
}

fn render_json_value(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(value) => value.to_string(),
        Value::Int(value) => value.to_string(),
        Value::BigInt(value) => value.clone(),
        Value::Float(value) if value.is_finite() => value.to_string(),
        Value::Float(_) => "null".to_string(),
        Value::Str(value) => json::dumps_str(value),
        Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(render_json_value)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(values) => format!(
            "{{{}}}",
            values
                .iter()
                .map(|(key, value)| format!(
                    "{}: {}",
                    json::dumps_str(key),
                    render_json_value(value)
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

fn line_span(content: &str, start: usize, end: usize) -> CheckSpan {
    let mut offset = 0usize;
    let mut span_start = 0usize;
    let mut span_end = content.len();
    for (index, line) in content.split_inclusive('\n').enumerate() {
        if index == start {
            span_start = offset;
        }
        offset += line.len();
        if index == end {
            span_end = offset;
            return CheckSpan {
                start: span_start,
                end: span_end,
            };
        }
    }
    CheckSpan {
        start: span_start,
        end: span_end,
    }
}

fn address_sort_key(address: &CheckAddress) -> String {
    match address {
        CheckAddress::Table { heading, ordinal } => format!("table:{heading}:{ordinal}"),
        CheckAddress::Frontmatter { key } => format!("frontmatter:{key}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clean_document_has_a_clean_report() {
        let report = check_document("# A\n\n| A | B |\n| - | - |\n| x | y |\n");
        assert_eq!(report.status(), "clean");
        assert_eq!(
            render_check_report(&report),
            "{\"schema_version\": 1, \"status\": \"clean\", \"findings\": []}"
        );
    }

    #[test]
    fn safe_fix_starts_as_a_byte_identical_no_op() {
        let content = "| A | B |\n| --- | --- |\n| x |\n";
        let fixed = fix_safe(content);
        assert_eq!(fixed.content, content);
        assert!(fixed.repaired.is_empty());
        assert_eq!(fixed.report.status(), "error");
    }
}
