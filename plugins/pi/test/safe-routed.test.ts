import assert from "node:assert/strict";
import test from "node:test";

import {
	filterColumns,
	parseOutline,
	parseTableSummary,
	requestedTable,
	resolveOutlineTarget,
	sectionInsertArguments,
	sectionInsertIntent,
	sectionIntent,
	tablePredicates,
} from "../extension/safe-routed.ts";

test("section routing recognizes only explicit rename and body-replacement requests", () => {
	assert.deepEqual(
		sectionIntent('Rename "Closed ATX level 3" to "Closed ATX heading".'),
		{ kind: "section-rename", target: "Closed ATX level 3" },
	);
	assert.deepEqual(
		sectionIntent('Replace the text under Upgrade > Linux with "See the platform notes."'),
		{ kind: "section-replace-body", target: "Upgrade > Linux" },
	);
	assert.equal(sectionIntent("Add a new section under Upgrade."), undefined);
});

test("section insertion routing freezes structure and exact literal content", () => {
	const entries = parseOutline([
		"Sections in `x.md`:",
		"  Changelog   (body, 1 subsection)",
		"    [1.4.2] - 2026-08-14   (body)",
		"  Deep heading nesting   (body, 2 subsections)",
		"    Install   (body)",
		"    Reference   (body, 1 subsection)",
		"      API   (body)",
	].join("\n"));
	const release = sectionInsertIntent(
		'Add a new release section for version 1.5.0, dated 2026-09-06, immediately above the [1.4.2] release. Give it an Added subsection containing the line "- flag."',
		entries,
	);
	assert.deepEqual(release, {
		target: "Changelog > [1.4.2] - 2026-08-14",
		position: "before",
		heading: "[1.5.0] - 2026-09-06",
		children: [{ heading: "Added", body: "- flag." }],
	});
	assert.deepEqual(sectionInsertIntent(
		'Under Install, add a FreeBSD subsection after the existing ones, saying "Use pkg."',
		entries,
	), {
		target: "Deep heading nesting > Install",
		position: "last-child",
		heading: "FreeBSD",
		body: "Use pkg.",
	});
	const nested = sectionInsertIntent(
		'Under the API section, add a Rate limits section, and give it a Headers subsection saying "Exact."',
		entries,
	);
	assert.deepEqual(nested, {
		target: "Deep heading nesting > Reference > API",
		position: "last-child",
		heading: "Rate limits",
		children: [{ heading: "Headers", body: "Exact." }],
	});
	assert.deepEqual(sectionInsertIntent(
		'At the end of Deep heading nesting, add a Troubleshooting section with two subsections: Logs, saying "Log.", and Common errors, saying "FAQ."',
		entries,
	), {
		target: "Deep heading nesting",
		position: "last-child",
		heading: "Troubleshooting",
		children: [
			{ heading: "Logs", body: "Log." },
			{ heading: "Common errors", body: "FAQ." },
		],
	});
	assert.deepEqual(sectionInsertArguments(nested!), {
		section: "Deep heading nesting > Reference > API",
		position: "last-child",
		heading: "Rate limits",
		children: [{ heading: "Headers", body: "Exact." }],
	});
	assert.equal(sectionInsertIntent("Add a section somewhere under API.", entries), undefined);
});

test("outline parsing resolves a unique suffix but refuses an ambiguous leaf", () => {
	const entries = parseOutline([
		"Sections in `x.md`:",
		"  Root   (body, 2 subsections)",
		"    Install   (body, 1 subsection)",
		"      Linux   (body)",
		"    Upgrade   (body, 1 subsection)",
		"      Linux   (body)",
	].join("\n"));
	assert.equal(resolveOutlineTarget(entries, "Upgrade > Linux"), "Root > Upgrade > Linux");
	assert.equal(resolveOutlineTarget(entries, "Linux"), undefined);
});

test("table routing resolves one named table and separates filters from requested output", () => {
	const entries = parseTableSummary([
		"Tables in `x.md`:",
		'  heading "Sortable table > Packages"  ordinal 0',
		"    columns: Name | Version | Released | Downloads | Priority   (5 rows)",
		'  heading "Sortable table > Stability"  ordinal 0',
		"    columns: Group | Item   (5 rows)",
	].join("\n"));
	const prompt = "In x.md, in the Packages table, find the package that is priority low AND at version 2.0.0. What date was it released?";
	const table = requestedTable(entries, prompt);
	assert.equal(table?.heading, "Sortable table > Packages");
	assert.deepEqual(filterColumns(table?.columns ?? [], prompt), ["Version", "Priority"]);
	assert.deepEqual(tablePredicates(table?.columns ?? [], prompt), {
		Version: "2.0.0",
		Priority: "low",
	});
	assert.deepEqual(
		filterColumns(table?.columns ?? [], "Which packages in the Packages table are priority urgent?"),
		["Priority"],
	);
});

test("table predicates exclude projected columns and retain exact requested values", () => {
	assert.deepEqual(
		tablePredicates(
			["Component", "Status", "Owner"],
			"List every component in the Components table with its status and owner.",
		),
		{},
	);
	assert.deepEqual(
		tablePredicates(
			["Case", "Value", "Note"],
			'In the Hazardous cells table, what is the Value cell of the row whose Case is "escaped pipe"?',
		),
		{ Case: "escaped pipe" },
	);
	assert.deepEqual(
		tablePredicates(
			["Name", "Priority"],
			"Which packages in the Packages table are priority high?",
		),
		{ Priority: "high" },
	);
});
