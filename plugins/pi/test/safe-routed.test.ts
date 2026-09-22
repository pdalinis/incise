import assert from "node:assert/strict";
import test from "node:test";

import {
	filterColumns,
	parseOutline,
	parseTableSummary,
	requestedTable,
	resolveOutlineTarget,
	sectionIntent,
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
	assert.deepEqual(
		filterColumns(table?.columns ?? [], "Which packages in the Packages table are priority urgent?"),
		["Priority"],
	);
});
