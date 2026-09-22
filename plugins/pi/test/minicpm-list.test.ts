import assert from "node:assert/strict";
import test from "node:test";

import {
	composeListAdd,
	contentSchema,
	extractMarkdownPath,
	forceToolChoice,
	parseListSummary,
	routeListRequest,
	selectEntry,
	selectionSchema,
	type ListItem,
} from "../extension/minicpm-list.ts";

const ITEMS: ListItem[] = [
	{ text: "first", depth: 0, parent: null, checked: null },
	{ text: "second", depth: 0, parent: null, checked: null },
	{ text: "third", depth: 0, parent: null, checked: null },
	{ text: "fourth", depth: 0, parent: null, checked: null },
];

test("forces the expected function without mutating or changing other provider fields", () => {
	const source = {
		model: "minicpm5-2b-q8",
		messages: [{ role: "user", content: "Edit the list." }],
		tools: [
			{ type: "function", function: { name: "list_select", parameters: { type: "object" } } },
			{ type: "function", function: { name: "unrelated_tool" } },
		],
		temperature: 0.7,
	};
	const before = structuredClone(source);
	const forced = forceToolChoice(source, "list_select");
	assert.equal(forced.present, true);
	assert.deepEqual(forced.payload, {
		...source,
		tool_choice: { type: "function", function: { name: "list_select" } },
	});
	assert.deepEqual(source, before);
});

test("fails closed when the expected function is absent", () => {
	const forced = forceToolChoice({
		model: "minicpm5-2b-q8",
		tools: [{ type: "function", function: { name: "another_tool" } }],
	}, "list_select");
	assert.equal(forced.present, false);
	assert.deepEqual(forced.payload, {
		model: "minicpm5-2b-q8",
		tools: [],
		tool_choice: { type: "function", function: { name: "list_select" } },
	});
});

test("extracts exactly one explicit markdown path and refuses ambiguity", () => {
	assert.equal(extractMarkdownPath("Edit `docs/guide.md` now."), "docs/guide.md");
	assert.equal(extractMarkdownPath("Add this to @notes/tasks.md"), "notes/tasks.md");
	assert.equal(extractMarkdownPath("Update document.md"), "document.md");
	assert.equal(extractMarkdownPath("Compare a.md and b.md"), undefined);
	assert.equal(extractMarkdownPath("No file here"), undefined);
});

test("routes the seven measured request shapes without descriptive false positives", () => {
	const cases = [
		["At the end of the list under Dash markers, add an item that says fourth.", "append"],
		["Under Asterisk markers, add beta-three immediately after beta-two.", "after"],
		["Add loose four at the end of the list whose items have blank lines between them.", "append"],
		["In the Sequential list, insert two and a half between second and third.", "between"],
		["Add fourth at the end of the All ones list.", "append"],
		["Add fourth at the end of the Paren delimiter list.", "append"],
		["Add second star item to the list that contains the star item.", "append"],
	] as const;
	for (const [request, route] of cases) assert.equal(routeListRequest(request), route, request);
});

test("parses and validates exact heading and ordinal pairs", () => {
	const summary = [
		"Lists in `doc.md`:",
		"  heading \"Tasks\"  ordinal 0",
		"    bullet list, marker \"-\", 2 items, tight",
		"  heading \"Tasks\"  ordinal 1",
		"    bullet list, marker \"*\", 2 items, loose (blank line between items)",
	].join("\n");
	const entries = parseListSummary(summary);
	assert.deepEqual(entries, [
		{ heading: "Tasks", ordinal: 0 },
		{ heading: "Tasks", ordinal: 1 },
	]);
	assert.deepEqual(selectEntry(entries, { heading: "Tasks", ordinal: 1 }), entries[1]);
	assert.throws(() => selectEntry(entries, { heading: "Tasks", ordinal: 2 }));
	const schema = selectionSchema(entries);
	assert.deepEqual(schema.parameters.required, ["heading", "ordinal"]);
});

test("publishes only route-specific required content", () => {
	assert.deepEqual(contentSchema("append", ITEMS).parameters.required, ["text"]);
	assert.deepEqual(contentSchema("after", ITEMS).parameters.required, ["text", "after"]);
	assert.deepEqual(contentSchema("between", ITEMS).parameters.required, ["text", "after", "before"]);
});

test("composes validated canonical list-add-item arguments", () => {
	const entry = { heading: "Tasks", ordinal: 1 };
	assert.deepEqual(composeListAdd("/work/doc.md", entry, "append", ITEMS, { text: "fourth" }), {
		path: "/work/doc.md",
		list: entry,
		text: "fourth",
		position: "end",
	});
	assert.deepEqual(composeListAdd("/work/doc.md", entry, "after", ITEMS, {
		text: "second-b", after: "second",
	}), {
		path: "/work/doc.md",
		list: entry,
		text: "second-b",
		after: "second",
	});
	assert.deepEqual(composeListAdd("/work/doc.md", entry, "between", ITEMS, {
		text: "two and a half", after: "second", before: "third",
	}), {
		path: "/work/doc.md",
		list: entry,
		text: "two and a half",
		after: "second",
	});
	assert.throws(() => composeListAdd("/work/doc.md", entry, "between", ITEMS, {
		text: "bad", after: "first", before: "third",
	}), /not adjacent/);
	const nonSiblings: ListItem[] = [
		{ text: "parent", depth: 0, parent: null, checked: null },
		{ text: "child", depth: 1, parent: 0, checked: null },
	];
	assert.throws(() => composeListAdd("/work/doc.md", entry, "between", nonSiblings, {
		text: "bad", after: "parent", before: "child",
	}), /not structural siblings/);
});
