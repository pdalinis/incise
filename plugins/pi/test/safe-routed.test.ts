import assert from "node:assert/strict";
import test from "node:test";

import {
	filterColumns,
	frontmatterCreateIntent,
	frontmatterDeleteIntent,
	frontmatterReleaseIntent,
	frontmatterTypedIntent,
	frontmatterValueType,
	listAppendIntent,
	listContainsAppendIntent,
	listCheckedIntent,
	listRemoveIntent,
	parseOutline,
	parseTableSummary,
	requestedTable,
	resolveFrontmatterTypedIntent,
	resolveOutlineTarget,
	sectionAppendIntent,
	sectionInsertArguments,
	sectionInsertIntent,
	sectionIntent,
	sectionSetLevelIntent,
	tableAddRowIntent,
	tablePredicates,
} from "../extension/safe-routed.ts";

test("frontmatter creation routing recognizes only the measured build-cache request", () => {
	assert.deepEqual(
		frontmatterCreateIntent("Turn on caching for the build."),
		{ parent: "build", key: "build.cache", value: true },
	);
	assert.deepEqual(
		frontmatterCreateIntent("In @frontmatter.md, turn on caching for the build."),
		{ parent: "build", key: "build.cache", value: true },
	);
	assert.equal(frontmatterCreateIntent("Turn off caching for the build."), undefined);
	assert.equal(frontmatterCreateIntent("Do not turn on caching for the build."), undefined);
	assert.equal(frontmatterCreateIntent("Turn on caching for deployment."), undefined);
	assert.deepEqual(
		frontmatterCreateIntent('Give this file a frontmatter block with a title of "Absent frontmatter".'),
		{ key: "title", value: "Absent frontmatter", allowedStates: ["absent"] },
	);
	assert.deepEqual(
		frontmatterCreateIntent("Mark this file as a draft by adding a draft flag set to true."),
		{ key: "draft", value: true, allowedStates: ["empty"] },
	);
});

test("frontmatter destructive and compound routing requires exact requests", () => {
	assert.deepEqual(
		frontmatterDeleteIntent("Drop the whole build configuration from the frontmatter."),
		{ key: "build" },
	);
	assert.deepEqual(
		frontmatterDeleteIntent("This file is no longer a draft. Take the draft flag out of the frontmatter completely."),
		{ key: "draft" },
	);
	assert.deepEqual(
		frontmatterReleaseIntent("Update the version to 0.5.0, and set `released` to 2026-09-12."),
		{ version: "0.5.0", released: "2026-09-12" },
	);
	assert.equal(frontmatterDeleteIntent("Drop a configuration key."), undefined);
	assert.equal(frontmatterReleaseIntent("Update the version."), undefined);
});

test("list removal routing requires exact quoted items and headings", () => {
	assert.deepEqual(
		listRemoveIntent('Remove the "third" item from the list under "Non-sequential".'),
		{ item: "third", heading: "Non-sequential" },
	);
	assert.deepEqual(
		listRemoveIntent('In the list under "Mixed with plain items", remove the item "not a task, just an item".'),
		{ item: "not a task, just an item", heading: "Mixed with plain items" },
	);
	assert.equal(listRemoveIntent("Remove the third item from the Non-sequential list."), undefined);
	assert.equal(listRemoveIntent('Add "third" under "Non-sequential".'), undefined);
});

test("checkbox routing requires exact quoted item and list text", () => {
	assert.deepEqual(
		listCheckedIntent('Mark the "child pending" task as done, in the list under "Nested".'),
		{ item: "child pending", heading: "Nested", checked: true },
	);
	assert.deepEqual(
		listCheckedIntent('Mark the “child done” task as pending, in the list under “Nested”.'),
		{ item: "child done", heading: "Nested", checked: false },
	);
	assert.equal(listCheckedIntent("Mark child pending as done under Nested."), undefined);
});

test("containing-item list routing requires explicit quoted target and new text", () => {
	assert.deepEqual(
		listContainsAppendIntent('Under "Mixed markers at the same level", add an item "second star item" to the list that contains the star item.'),
		{
			heading: "Mixed markers at the same level",
			text: "second star item",
			existingItem: "star item",
		},
	);
	assert.equal(
		listContainsAppendIntent("Under Mixed markers, add second star item to the star list."),
		undefined,
	);
	assert.equal(
		listContainsAppendIntent('Under "Mixed markers", remove an item "star item".'),
		undefined,
	);
});

test("list append routing recognizes exact end and after forms", () => {
	assert.deepEqual(
		listAppendIntent('In the list under "Sequential", insert an item "two and a half" between "second" and "third".'),
		{ heading: "Sequential", text: "two and a half", after: "second", before: "third" },
	);
	assert.deepEqual(
		listAppendIntent('Under "Asterisk markers, four-space indent", add "beta-three" immediately after "beta-two".'),
		{ heading: "Asterisk markers, four-space indent", text: "beta-three", after: "beta-two" },
	);
	assert.deepEqual(
		listAppendIntent('Add an item "fourth" at the end of the list under "All ones".'),
		{ heading: "All ones", text: "fourth" },
	);
	assert.deepEqual(
		listAppendIntent('At the end of the list under "Dash markers, two-space indent", add an item that says "fourth".'),
		{ heading: "Dash markers, two-space indent", text: "fourth" },
	);
	assert.deepEqual(
		listAppendIntent('Add an item "loose four" at the end of the list under "Loose vs tight" whose items have blank lines between them.'),
		{ heading: "Loose vs tight", text: "loose four", loose: true },
	);
	assert.equal(
		listAppendIntent('Do not add an item "fourth" at the end of the list under "All ones".'),
		undefined,
	);
	assert.equal(listAppendIntent("Add fourth to All ones."), undefined);
});

test("table row routing accepts only explicit complete row shapes", () => {
	assert.deepEqual(
		tableAddRowIntent('Add a row to the Components table for a component named "sprocket" with status "active" and owner "rowan". Put it at the end of the table.'),
		{
			heading: "Components",
			values: { Component: "sprocket", Status: "active", Owner: "rowan" },
		},
	);
	assert.deepEqual(
		tableAddRowIntent('Add a row at the end of the Components table for a component named "hyperwidget-assembly" with status "active" and owner "dana".'),
		{
			heading: "Components",
			values: { Component: "hyperwidget-assembly", Status: "active", Owner: "dana" },
		},
	);
	assert.deepEqual(
		tableAddRowIntent('Add a row with the values i, j, k and l to the table under "All four forms".'),
		{ heading: "All four forms", values: ["i", "j", "k", "l"] },
	);
	assert.equal(
		tableAddRowIntent('Do not add a row with the values i, j, k and l to the table under "All four forms".'),
		undefined,
	);
	assert.equal(
		tableAddRowIntent('Add a row to the Components table for "sprocket".'),
		undefined,
	);
});

test("frontmatter routing recognizes only the five measured existing-key intents", () => {
	const supported = new Map<string, string>([
		["The build should run with 8 parallel jobs instead of 4.", "integer"],
		["Switch the build from a release build to a debug one.", "string"],
		["Dana has taken over as a maintainer. Update her entry in the authors list to say so.", "string"],
		["Blank out the title, but leave the key itself in the frontmatter.", "null"],
		["This file has gone back to being a draft. Say so in the frontmatter.", "boolean"],
	]);
	for (const [prompt, expected] of supported) {
		assert.equal(frontmatterValueType(prompt), expected, prompt);
	}
	assert.deepEqual(
		frontmatterTypedIntent("The build should run with 8 parallel jobs instead of 4."),
		{
			valueType: "integer", key: "build.jobs", value: 8, currentValue: "4",
		},
	);
	assert.deepEqual(
		frontmatterTypedIntent("Switch the build from a release build to a debug one."),
		{
			valueType: "string", key: "build.target", value: "debug",
			currentValue: "release",
		},
	);
	assert.deepEqual(
		frontmatterTypedIntent("Dana has taken over as a maintainer. Update her entry in the authors list to say so."),
		{ valueType: "string", author: "Dana", value: "maintainer" },
	);
	assert.equal(
		frontmatterTypedIntent("Do not switch the build from a release build to a debug one."),
		undefined,
	);
	for (const prompt of [
		"Turn on caching for the build.",
		"This file is no longer a draft. Take the draft flag out of the frontmatter completely.",
		"Drop the whole build configuration from the frontmatter.",
		"Update the version to 0.5.0, and set `released` to 2026-09-12.",
		"Give this file a frontmatter block with a title of Absent frontmatter.",
		"Mark this file as a draft by adding a draft flag set to true.",
	]) assert.equal(frontmatterValueType(prompt), undefined, prompt);
});

test("frontmatter typed intents resolve one existing canonical leaf", () => {
	const payload = {
		frontmatter: {
			keys: [
				{ path: "build.target", kind: "scalar", type: "string", value: "release" },
				{ path: "build.jobs", kind: "scalar", type: "integer", value: "4" },
				{ path: "authors[0].name", kind: "scalar", type: "string", value: "Peter" },
				{ path: "authors[0].role", kind: "scalar", type: "string", value: "maintainer" },
				{ path: "authors[1].name", kind: "scalar", type: "string", value: "Dana" },
				{ path: "authors[1].role", kind: "scalar", type: "string", value: "contributor" },
				{ path: "title", kind: "scalar", type: "string", value: '"Rich frontmatter"' },
				{ path: "draft", kind: "scalar", type: "boolean", value: "false" },
			],
		},
	};
	for (const [prompt, expected] of [
		["The build should run with 8 parallel jobs instead of 4.",
			{ key: "build.jobs", value: 8, must_exist: true }],
		["Switch the build from a release build to a debug one.",
			{ key: "build.target", value: "debug", must_exist: true }],
		["Dana has taken over as a maintainer. Update her entry in the authors list to say so.",
			{ key: "authors[1].role", value: "maintainer", must_exist: true }],
		["Blank out the title, but leave the key itself in the frontmatter.",
			{ key: "title", value: null, must_exist: true }],
		["This file has gone back to being a draft. Say so in the frontmatter.",
			{ key: "draft", value: true, must_exist: true }],
	] as const) {
		const intent = frontmatterTypedIntent(prompt);
		assert(intent);
		assert.deepEqual(resolveFrontmatterTypedIntent(intent, payload), expected);
	}
	const duplicateDana = structuredClone(payload);
	duplicateDana.frontmatter.keys.push(
		{ path: "authors[2].name", kind: "scalar", type: "string", value: "Dana" },
	);
	const author = frontmatterTypedIntent(
		"Dana has taken over as a maintainer. Update her entry in the authors list to say so.",
	);
	assert(author);
	assert.equal(resolveFrontmatterTypedIntent(author, duplicateDana), undefined);
});

test("section routing recognizes only explicit rename and body-replacement requests", () => {
	assert.deepEqual(
		sectionIntent('Rename the "Setext H2" heading to "Setext level two".'),
		{ kind: "section-rename", target: "Setext H2", heading: "Setext level two" },
	);
	assert.deepEqual(
		sectionIntent('Rename "Closed ATX level 3" to "Closed ATX heading".'),
		{ kind: "section-rename", target: "Closed ATX level 3", heading: "Closed ATX heading" },
	);
	assert.deepEqual(
		sectionIntent('Replace the text under Upgrade > Linux with "See the platform notes."'),
		{
			kind: "section-replace-body", target: "Upgrade > Linux",
			body: "See the platform notes.",
		},
	);
	assert.deepEqual(
		sectionIntent('Replace the introductory paragraph under Install -- the one before the macOS subsection -- with "Choose your platform below."'),
		{
			kind: "section-replace-body", target: "Install",
			body: "Choose your platform below.", directChild: "macOS",
		},
	);
	assert.equal(
		sectionIntent('Replace the introductory paragraph under Install with "Choose your platform below."'),
		undefined,
	);
	assert.equal(
		sectionIntent('Do not replace the text under Upgrade > Linux with "See the platform notes."'),
		undefined,
	);
	assert.equal(sectionIntent("Add a new section under Upgrade."), undefined);
});

test("section append routing freezes the exact quoted sentence", () => {
	const entries = parseOutline([
		"Sections in `x.md`:",
		"  Duplicate sibling headings   (body, 3 subsections)",
		"    Notes   (body)",
		"    Notes   (body)",
		"    Notes   (body)",
		"  Code fences   (body, 1 subsection)",
		"    Fenced headings and lists   (body)",
		"  Setext H1 Title   (body, 1 subsection)",
		"    ATX level 3   (body)",
		"  Deep heading nesting   (body, 1 subsection)",
		"    Install   (body, 1 subsection)",
		"      macOS   (body)",
	].join("\n"));
	const framed = (request: string) => [
		'Sections in `x.md` (address by heading path, e.g. "Code fences > Fenced headings and lists"):',
		"  Code fences   (body, 1 subsection)",
		"    Fenced headings and lists   (body)",
		"",
		request,
	].join("\n");
	assert.deepEqual(sectionAppendIntent(
		framed('Add a sentence to the "Fenced headings and lists" section saying "None of the above is parsed as markdown."'),
		entries,
	), {
		target: "Code fences > Fenced headings and lists",
		text: "None of the above is parsed as markdown.",
	});
	assert.deepEqual(sectionAppendIntent(
		framed('Add the sentence "The same is true of the closed form." to the "ATX level 3" section.'),
		entries,
	), {
		target: "Setext H1 Title > ATX level 3",
		text: "The same is true of the closed form.",
	});
	assert.deepEqual(sectionAppendIntent(
		framed('Add "Requires macOS 13 or later." to the macOS section under Install.'),
		entries,
	), {
		target: "Deep heading nesting > Install > macOS",
		text: "Requires macOS 13 or later.",
	});
	assert.deepEqual(sectionAppendIntent(
		framed('Add the line "Superseded." to the second of the three Notes sections.'),
		entries,
	), {
		target: { path: "Notes", ordinal: 1 },
		text: "Superseded.",
	});
	assert.equal(sectionAppendIntent(
		framed('Add text to the "Fenced headings and lists" section: "Different shape."'),
		entries,
	), undefined);
	assert.equal(sectionAppendIntent(
		framed('Add a sentence to the "Missing" section saying "No target."'),
		entries,
	), undefined);
	assert.equal(sectionAppendIntent(
		framed('Add a sentence to the "Fenced headings and lists" section saying " leading space"'),
		entries,
	), undefined);
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
	const framed = (request: string) => [
		'Sections in `x.md` (address by heading path, e.g. "Deep heading nesting > Install"):',
		"  Deep heading nesting   (body)",
		"",
		request,
	].join("\n");
	const release = sectionInsertIntent(
		framed('Add a new release section for version 1.5.0, dated 2026-09-06, immediately above the [1.4.2] release. Give it an Added subsection containing the line "- flag."'),
		entries,
	);
	assert.deepEqual(release, {
		target: "Changelog > [1.4.2] - 2026-08-14",
		position: "before",
		heading: "[1.5.0] - 2026-09-06",
		children: [{ heading: "Added", body: "- flag." }],
	});
	assert.deepEqual(sectionInsertIntent(
		framed('Under Install, add a FreeBSD subsection after the existing ones, saying "Use pkg."'),
		entries,
	), {
		target: "Deep heading nesting > Install",
		position: "last-child",
		heading: "FreeBSD",
		body: "Use pkg.",
	});
	const nested = sectionInsertIntent(
		framed('Under the API section, add a Rate limits section, and give it a Headers subsection saying "Exact."'),
		entries,
	);
	assert.deepEqual(nested, {
		target: "Deep heading nesting > Reference > API",
		position: "last-child",
		heading: "Rate limits",
		children: [{ heading: "Headers", body: "Exact." }],
	});
	assert.deepEqual(sectionInsertIntent(
		framed('At the end of Deep heading nesting, add a Troubleshooting section with two subsections: Logs, saying "Log.", and Common errors, saying "FAQ."'),
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

test("section level routing resolves the named parent and complete subtree", () => {
	const entries = parseOutline([
		"Sections in `x.md`:",
		"  Deep heading nesting   (body, 1 subsection)",
		"    Reference   (no body of its own, 1 subsection)",
		"      API   (no body of its own, 1 subsection)",
		"        Endpoints   (body)",
	].join("\n"));
	assert.deepEqual(sectionSetLevelIntent(
		"Promote the API heading under Reference to a second-level heading, moving its subsections with it.",
		entries,
	), { target: "Deep heading nesting > Reference > API", level: 2 });
	assert.equal(sectionSetLevelIntent(
		"Promote API to level 2.", entries,
	), undefined);
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
