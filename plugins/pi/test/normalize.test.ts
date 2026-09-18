import assert from "node:assert/strict";
import test from "node:test";

import { normalizeEdit, prepareInvocation, stripPiPathPrefix } from "../extension/normalize.ts";

test("normalizes edit operation names", () => {
	assert.equal(normalizeEdit("table_edit", { action: "add-row" }).operation, "table-add-row");
	assert.equal(normalizeEdit("list_edit", { action: "set-checked" }).operation, "list-set-checked");
	assert.equal(normalizeEdit("frontmatter_edit", { action: "set" }).operation, "frontmatter-set");
	assert.equal(normalizeEdit("table_edit", {}).operation, "table-None");
});

test("normalizes the measured section argument spellings", () => {
	const source = {
		action: "rename",
		file: "doc.md",
		section: { heading: "Install", ordinal: 1 },
		new_heading: "Setup",
	};
	const { operation, args } = normalizeEdit("section_edit", source);
	assert.equal(operation, "section-rename");
	assert.deepEqual(args, {
		action: "rename",
		path: "doc.md",
		section: { path: "Install", ordinal: 1 },
		heading: "Setup",
	});
	assert.deepEqual(source.section, { heading: "Install", ordinal: 1 });
});

test("resolves Pi paths against cwd and removes one leading at sign", () => {
	assert.equal(stripPiPathPrefix("@docs/api.md"), "docs/api.md");
	assert.equal(stripPiPathPrefix("@@literal.md"), "@literal.md");
	const invocation = prepareInvocation("md_tables", { path: "@docs/api.md" }, "/work");
	assert.equal(invocation.path, "/work/docs/api.md");
	assert.equal(invocation.args.path, "/work/docs/api.md");
	assert.equal(invocation.operation, "tables");
	assert.equal(invocation.write, false);
});

test("routes table_get as a read", () => {
	const invocation = prepareInvocation(
		"table_get",
		{ path: "tables.md", table: { heading: "Packages" } },
		"/work",
	);
	assert.equal(invocation.operation, "rows");
	assert.equal(invocation.write, false);
});
