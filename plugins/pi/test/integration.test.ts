import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { copyFile, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import type { ExecOptions, ExecResult, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import inciseExtension from "../extension/index.ts";

function exec(command: string, args: string[], options: ExecOptions = {}): Promise<ExecResult> {
	return new Promise((resolve, reject) => {
		const child = spawn(command, args, {
			cwd: options.cwd,
			signal: options.signal,
			stdio: ["ignore", "pipe", "pipe"],
		});
		let stdout = "";
		let stderr = "";
		let killed = false;
		const timer = options.timeout ? setTimeout(() => {
			killed = child.kill();
		}, options.timeout) : undefined;
		child.stdout.setEncoding("utf8");
		child.stderr.setEncoding("utf8");
		child.stdout.on("data", (chunk) => { stdout += chunk; });
		child.stderr.on("data", (chunk) => { stderr += chunk; });
		child.on("error", reject);
		child.on("close", (code) => {
			if (timer) clearTimeout(timer);
			resolve({ stdout, stderr, code: code ?? 1, killed });
		});
	});
}

test("loads eight tools and preserves read, write, refusal, and queue behavior", async () => {
	const repository = resolve(process.cwd(), "..", "..");
	const binary = resolve(repository, "target", "debug", "incise");
	const tools = new Map<string, any>();
	const commands = new Map<string, any>();
	const pi = {
		exec,
		registerTool(tool: any) { tools.set(tool.name, tool); },
		registerCommand(name: string, command: any) { commands.set(name, command); },
	} as unknown as ExtensionAPI;

	const previousBinary = process.env.INCISE_BIN;
	process.env.INCISE_BIN = binary;
	try {
		await inciseExtension(pi);
	} finally {
		if (previousBinary === undefined) delete process.env.INCISE_BIN;
		else process.env.INCISE_BIN = previousBinary;
	}
	assert.deepEqual([...tools.keys()].sort(), [
		"frontmatter_edit",
		"list_edit",
		"md_lists",
		"md_outline",
		"md_tables",
		"section_edit",
		"table_edit",
		"table_get",
	]);
	assert(commands.has("incise-doctor"));

	const directory = await mkdtemp(join(tmpdir(), "pi-incise-"));
	const path = join(directory, "tables.md");
	await writeFile(path, "# Packages\n\n| Name |\n| --- |\n| base |\n", "utf8");
	const ctx = { cwd: directory } as any;

	const tableList = await tools.get("md_tables").execute("read", { path: "@tables.md" }, undefined, undefined, ctx);
	const directRead = await exec(binary, ["tables", path, "--json"]);
	const directPayload = JSON.parse(directRead.stdout);
	assert.equal(tableList.content[0].text, directPayload.text);

	const add = (name: string) => tools.get("table_edit").execute(
		`add-${name}`,
		{ action: "add-row", path: "tables.md", table: { heading: "Packages" }, values: { Name: name } },
		undefined,
		undefined,
		ctx,
	);
	const [first, second] = await Promise.all([add("one"), add("two")]);
	assert.match(first.content[0].text, /^Applied:/);
	assert.match(second.content[0].text, /^Applied:/);
	const changed = await readFile(path, "utf8");
	assert.match(changed, /\| one\s+\|/);
	assert.match(changed, /\| two\s+\|/);

	const invalid = {
		action: "delete-row",
		path: "tables.md",
		table: { heading: "Missing" },
		where: { Name: "base" },
	};
	await assert.rejects(
		() => tools.get("table_edit").execute("refusal", invalid, undefined, undefined, ctx),
		(error: unknown) => error instanceof Error && error.message.startsWith("no table under heading \"Missing\"."),
	);
});

test("minicpm-list profile validates two phases and permits one successful write", async () => {
	const repository = resolve(process.cwd(), "..", "..");
	const binary = resolve(repository, "target", "debug", "incise");
	const tools = new Map<string, any>();
	const commands = new Map<string, any>();
	const events = new Map<string, any>();
	const active: string[][] = [];
	const pi = {
		exec,
		registerTool(tool: any) { tools.set(tool.name, tool); },
		registerCommand(name: string, command: any) { commands.set(name, command); },
		on(name: string, handler: any) { events.set(name, handler); },
		setActiveTools(names: string[]) { active.push([...names]); },
	} as unknown as ExtensionAPI;

	const previousBinary = process.env.INCISE_BIN;
	const previousProfile = process.env.INCISE_PROFILE;
	process.env.INCISE_BIN = binary;
	process.env.INCISE_PROFILE = "minicpm-list";
	try {
		await inciseExtension(pi);
	} finally {
		if (previousBinary === undefined) delete process.env.INCISE_BIN;
		else process.env.INCISE_BIN = previousBinary;
		if (previousProfile === undefined) delete process.env.INCISE_PROFILE;
		else process.env.INCISE_PROFILE = previousProfile;
	}

	assert(commands.has("incise-doctor"));
	assert(events.has("before_agent_start"));
	const directory = await mkdtemp(join(tmpdir(), "pi-incise-minicpm-list-"));
	const path = join(directory, "lists.md");
	await writeFile(path, [
		"# Sequential", "", "1. first", "2. second", "3. third", "4. fourth", "",
	].join("\n"), "utf8");
	const context = { cwd: directory } as any;
	const prepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "In @lists.md, insert an item named two and a half between second and third.",
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(prepared.systemPrompt, /Lists in/);
	assert.deepEqual(active.at(-1), ["list_select"]);

	const selected = await tools.get("list_select").execute(
		"select", { heading: "Sequential", ordinal: 0 }, undefined, undefined, context,
	);
	assert.match(selected.content[0].text, /text="second"/);
	assert.deepEqual(active.at(-1), ["list_insert_between"]);

	const inserted = await tools.get("list_insert_between").execute(
		"insert",
		{ text: "two and a half", after: "second", before: "third" },
		undefined,
		undefined,
		context,
	);
	assert.match(inserted.content[0].text, /^Applied:/);
	assert.equal(inserted.details.validated, true);
	assert.deepEqual(active.at(-1), []);
	const once = await readFile(path, "utf8");
	assert.match(once, /3\. two and a half\n4\. third/);

	await assert.rejects(
		() => tools.get("list_insert_between").execute(
			"duplicate",
			{ text: "duplicate", after: "second", before: "two and a half" },
			undefined,
			undefined,
			context,
		),
		/one successful list mutation/,
	);
	assert.equal(await readFile(path, "utf8"), once);

	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "In @lists.md, add an item named fifth at the end of the Sequential list.",
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	await tools.get("list_select").execute(
		"select-stale", { heading: "Sequential", ordinal: 0 }, undefined, undefined, context,
	);
	const externallyChanged = `${once}<!-- external -->\n`;
	await writeFile(path, externallyChanged, "utf8");
	await assert.rejects(
		() => tools.get("list_append_item").execute(
			"stale", { text: "fifth" }, undefined, undefined, context,
		),
		/has changed since it was read/,
	);
	assert.equal(await readFile(path, "utf8"), externallyChanged);
});

test("safe-routed profile resolves section targets and preserves foreign tools", async () => {
	const repository = resolve(process.cwd(), "..", "..");
	const binary = resolve(repository, "target", "debug", "incise");
	const tools = new Map<string, any>();
	const commands = new Map<string, any>();
	const events = new Map<string, any>();
	const active = new Set<string>(["foreign_tool"]);
	const pi = {
		exec,
		registerTool(tool: any) {
			tools.set(tool.name, tool);
			active.add(tool.name);
		},
		registerCommand(name: string, command: any) { commands.set(name, command); },
		on(name: string, handler: any) { events.set(name, handler); },
		getActiveTools() { return [...active]; },
		setActiveTools(names: string[]) {
			active.clear();
			for (const name of names) active.add(name);
		},
	} as unknown as ExtensionAPI;

	const previousBinary = process.env.INCISE_BIN;
	const previousProfile = process.env.INCISE_PROFILE;
	process.env.INCISE_BIN = binary;
	process.env.INCISE_PROFILE = "safe-routed";
	try {
		await inciseExtension(pi);
	} finally {
		if (previousBinary === undefined) delete process.env.INCISE_BIN;
		else process.env.INCISE_BIN = previousBinary;
		if (previousProfile === undefined) delete process.env.INCISE_PROFILE;
		else process.env.INCISE_PROFILE = previousProfile;
	}

	const directory = await mkdtemp(join(tmpdir(), "pi-incise-safe-routed-"));
	const path = join(directory, "sections.md");
	await copyFile(resolve(repository, "corpus", "sections", "setext-and-atx.md"), path);
	const context = { cwd: directory, model: { id: "unrelated-model" } } as any;
	const prepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: 'In @sections.md, rename "Closed ATX level 3" to "Closed ATX heading".',
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(prepared.systemPrompt, /resolved the requested section/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "section_rename_target"]);

	const renamed = await tools.get("section_rename_target").execute(
		"rename", { new_heading: "Closed ATX heading" }, undefined, undefined, context,
	);
	assert.match(renamed.content[0].text, /^Applied:/);
	assert.equal(renamed.details.validated, true);
	assert.deepEqual([...active], ["foreign_tool"]);
	assert.match(await readFile(path, "utf8"), /### Closed ATX heading ###/);

	const insertPath = join(directory, "insert.md");
	await copyFile(resolve(repository, "corpus", "sections", "deep-nesting.md"), insertPath);
	const insertPrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: [
			'Sections in `insert.md` (address by heading path, e.g. "Deep heading nesting > Install"):',
			"  Deep heading nesting   (body)",
			"",
			'In @insert.md, under Install, add a FreeBSD subsection after the existing ones, saying "Use pkg."',
		].join("\n"),
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(insertPrepared.systemPrompt, /resolved the complete section insertion/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "section_insert_target"]);
	assert.equal(tools.get("section_insert_target").parameters.required, undefined);
	const inserted = await tools.get("section_insert_target").execute(
		"insert", {}, undefined, undefined, context,
	);
	assert.equal(inserted.details.route, "section-insert");
	assert.deepEqual(inserted.details.resolvedArguments, {
		section: "Deep heading nesting > Install",
		position: "last-child",
		heading: "FreeBSD",
		body: "Use pkg.",
	});
	assert.match(await readFile(insertPath, "utf8"), /### FreeBSD\n\nUse pkg\./);
	assert.deepEqual([...active], ["foreign_tool"]);

	const promotePath = join(directory, "promote.md");
	await copyFile(resolve(repository, "corpus", "sections", "deep-nesting.md"), promotePath);
	const promotePrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: [
			'Sections in `promote.md` (address by heading path, e.g. "Deep heading nesting > Install"):',
			"  Deep heading nesting   (body, 1 subsection)",
			"    Reference   (no body of its own, 1 subsection)",
			"      API   (no body of its own, 1 subsection)",
			"",
			"Promote the API heading under Reference to a second-level heading, moving its subsections with it.",
		].join("\n"),
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(promotePrepared.systemPrompt, /resolved the requested section level change/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "section_set_level_target"]);
	const promoted = await tools.get("section_set_level_target").execute(
		"promote", {}, undefined, undefined, context,
	);
	assert.equal(promoted.details.route, "section-set-level-target");
	assert.deepEqual(promoted.details.resolvedArguments, {
		section: "Deep heading nesting > Reference > API",
		level: 2,
		subtree: true,
	});
	assert.match(await readFile(promotePath, "utf8"), /\n## API\n\n### Endpoints\n\n#### Authentication\n/);
	assert.deepEqual([...active], ["foreign_tool"]);

	const appendPath = join(directory, "fences.md");
	await copyFile(resolve(repository, "corpus", "hazards", "code-fences.md"), appendPath);
	const appendBefore = await readFile(appendPath, "utf8");
	const appendPrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: [
			'Sections in `fences.md` (address by heading path, e.g. "Code fences > Fenced headings and lists"):',
			"  Code fences   (body, 6 subsections)",
			"    Fenced headings and lists   (body)",
			"",
			'Add a sentence to the "Fenced headings and lists" section saying "None of the above is parsed as markdown."',
		].join("\n"),
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(appendPrepared.systemPrompt, /activated section_append_target/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "section_append_target"]);
	assert.equal(tools.get("section_append_target").parameters.required, undefined);
	const appended = await tools.get("section_append_target").execute(
		"append", {}, undefined, undefined, context,
	);
	assert.equal(appended.details.route, "section-append");
	assert.deepEqual(appended.details.resolvedArguments, {
		section: "Code fences > Fenced headings and lists",
		text: "None of the above is parsed as markdown.",
	});
	const appendAfter = await readFile(appendPath, "utf8");
	assert.equal(
		appendAfter,
		appendBefore.replace(
			"---\n```\n\n## Tilde fences",
			"---\n```\n\nNone of the above is parsed as markdown.\n\n## Tilde fences",
		),
	);
	assert.deepEqual([...active], ["foreign_tool"]);

	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "Summarize @sections.md without changing it.",
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert(active.has("foreign_tool"));
	assert(active.has("section_edit"));
	assert(active.has("md_outline"));
	assert(!active.has("section_rename_target"));
	assert.equal(active.size, 9);

	const tablePath = join(directory, "tables.md");
	await copyFile(resolve(repository, "corpus", "tables", "sortable.md"), tablePath);
	const tablePrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "In @tables.md, in the Packages table, find the package that is priority low AND at version 2.0.0. What date was it released?",
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(tablePrepared.systemPrompt, /resolved the requested table/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "table_query"]);
	const queried = await tools.get("table_query").execute(
		"query", {}, undefined, undefined, context,
	);
	assert.match(queried.content[0].text, /echo/);
	assert.equal(queried.details.route, "table-query");
	assert.deepEqual([...active], ["foreign_tool"]);

	const componentsPath = join(directory, "components.md");
	await copyFile(resolve(repository, "corpus", "tables", "ragged.md"), componentsPath);
	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "In @components.md, list every component in the Components table with its status and owner.",
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert(active.has("table_get"));
	assert(!active.has("table_query"));

	const cellsPath = join(directory, "cells.md");
	await copyFile(resolve(repository, "corpus", "tables", "cell-edge-cases.md"), cellsPath);
	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: 'In @cells.md, in the Hazardous cells table, what is the Value cell of the row whose Case is "escaped pipe"?',
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.deepEqual([...active].sort(), ["foreign_tool", "table_query"]);
	assert.deepEqual(tools.get("table_query").parameters.required, undefined);
	const escaped = await tools.get("table_query").execute(
		"escaped", {}, undefined, undefined, context,
	);
	assert.match(escaped.content[0].text, /a \\\| b/);
	assert.deepEqual(escaped.details.resolvedArguments.filter, { Case: "escaped pipe" });
	assert.deepEqual([...active], ["foreign_tool"]);

	const frontmatterPath = join(directory, "frontmatter.md");
	await copyFile(resolve(repository, "corpus", "frontmatter", "rich.md"), frontmatterPath);
	const frontmatterPrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "In @frontmatter.md, the build should run with 8 parallel jobs instead of 4.",
		systemPrompt: "System.\n\nAvailable tools:\n(none)",
		systemPromptOptions: {},
	}, context);
	assert.match(frontmatterPrepared.systemPrompt, /activated frontmatter_set_integer/);
	assert.match(frontmatterPrepared.systemPrompt, /build\.jobs/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "frontmatter_set_integer"]);
	assert.deepEqual(tools.get("frontmatter_set_integer").parameters.required, ["key", "value"]);
	const frontmatterChanged = await tools.get("frontmatter_set_integer").execute(
		"frontmatter", { key: "build.jobs", value: 8 }, undefined, undefined, context,
	);
	assert.equal(frontmatterChanged.details.route, "frontmatter-typed");
	assert.deepEqual(frontmatterChanged.details.resolvedArguments, {
		key: "build.jobs", value: 8, must_exist: true,
	});
	assert.match(await readFile(frontmatterPath, "utf8"), /  jobs: 8/);
	assert.deepEqual([...active], ["foreign_tool"]);

	const createPrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "In @frontmatter.md, turn on caching for the build.",
		systemPrompt: "System.\n\nAvailable tools:\n(none)",
		systemPromptOptions: {},
	}, context);
	assert.match(createPrepared.systemPrompt, /activated frontmatter_create_target/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "frontmatter_create_target"]);
	assert.equal(tools.get("frontmatter_create_target").parameters.required, undefined);
	const frontmatterCreated = await tools.get("frontmatter_create_target").execute(
		"frontmatter-create", {}, undefined, undefined, context,
	);
	assert.equal(frontmatterCreated.details.route, "frontmatter-create");
	assert.deepEqual(frontmatterCreated.details.resolvedArguments, {
		key: "build.cache", value: true, must_absent: true,
	});
	assert.match(await readFile(frontmatterPath, "utf8"), /  jobs: 8\n  cache: true\nauthors:/);
	assert.deepEqual([...active], ["foreign_tool"]);

	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "In @frontmatter.md, turn on caching for the build.",
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert(active.has("frontmatter_edit"));
	assert(!active.has("frontmatter_create_target"));

	const listPath = join(directory, "numbering.md");
	await copyFile(resolve(repository, "corpus", "lists", "ordered-numbering.md"), listPath);
	const listPrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: 'In @numbering.md, remove the "third" item from the list under "Non-sequential".',
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(listPrepared.systemPrompt, /resolved the exact quoted list item/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "list_remove_target"]);
	assert.equal(tools.get("list_remove_target").parameters.required, undefined);
	const removed = await tools.get("list_remove_target").execute(
		"remove", {}, undefined, undefined, context,
	);
	assert.equal(removed.details.route, "list-remove-target");
	assert.deepEqual(removed.details.resolvedArguments, {
		list: { heading: "Ordered list numbering > Non-sequential", ordinal: 0 },
		match: "third",
	});
	const numbering = await readFile(listPath, "utf8");
	assert.match(numbering, /## Non-sequential[\s\S]*?1\. first\n7\. seventh\n\n## Nested under unordered/);
	assert.deepEqual([...active], ["foreign_tool"]);

	const tasksPath = join(directory, "tasks.md");
	await copyFile(resolve(repository, "corpus", "lists", "tasks.md"), tasksPath);
	const checkedPrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: [
			"Lists in `tasks.md`:",
			'  heading "Task lists > Nested"  ordinal 0',
			"    bullet list, marker \"-\", 3 levels of nesting, 5 items, tight, 5 task checkboxes",
			"",
			'Mark the "child pending" task as done, in the list under "Nested".',
		].join("\n"),
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(checkedPrepared.systemPrompt, /resolved the exact checkbox item/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "list_set_checked_target"]);
	const checkedResult = await tools.get("list_set_checked_target").execute(
		"check", {}, undefined, undefined, context,
	);
	assert.equal(checkedResult.details.route, "list-set-checked-target");
	assert.deepEqual(checkedResult.details.resolvedArguments, {
		list: { heading: "Task lists > Nested", ordinal: 0 },
		match: "child pending",
		checked: true,
	});
	assert.match(await readFile(tasksPath, "utf8"), /  - \[x\] child pending/);
	assert.deepEqual([...active], ["foreign_tool"]);

	const mixedPath = join(directory, "nested-mixed.md");
	await copyFile(resolve(repository, "corpus", "lists", "nested-mixed.md"), mixedPath);
	const mixedBefore = await readFile(mixedPath, "utf8");
	const mixedPrepared = await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: [
			"Lists in `nested-mixed.md`:",
			'  heading "Nested and mixed lists > Mixed markers at the same level"  ordinal 0',
			'    bullet list, marker "-", 1 items, tight',
			'  heading "Nested and mixed lists > Mixed markers at the same level"  ordinal 1',
			'    bullet list, marker "*", 1 items, tight',
			'  heading "Nested and mixed lists > Mixed markers at the same level"  ordinal 2',
			'    bullet list, marker "+", 1 items, tight',
			"",
			'Under "Mixed markers at the same level", add an item "second star item" to the list that contains the star item.',
		].join("\n"),
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert.match(mixedPrepared.systemPrompt, /activated list_append_target/);
	assert.deepEqual([...active].sort(), ["foreign_tool", "list_append_target"]);
	assert.equal(tools.get("list_append_target").parameters.required, undefined);
	const mixedAdded = await tools.get("list_append_target").execute(
		"list-append", {}, undefined, undefined, context,
	);
	assert.equal(mixedAdded.details.route, "list-append-target");
	assert.deepEqual(mixedAdded.details.resolvedArguments, {
		list: { heading: "Nested and mixed lists > Mixed markers at the same level", ordinal: 1 },
		text: "second star item",
		position: "end",
	});
	assert.equal(
		await readFile(mixedPath, "utf8"),
		mixedBefore.replace("* star item\n\n+ plus item", "* star item\n* second star item\n\n+ plus item"),
	);
	assert.deepEqual([...active], ["foreign_tool"]);

	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: 'In @nested-mixed.md, under "Mixed markers at the same level", add an item "second star item" to the list that contains the star item.',
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, context);
	assert(active.has("list_edit"));
	assert(!active.has("list_append_target"));
});

test("auto profile selects once from the active model and reports the decision", async () => {
	const repository = resolve(process.cwd(), "..", "..");
	const binary = resolve(repository, "target", "debug", "incise");
	const tools = new Map<string, any>();
	const commands = new Map<string, any>();
	const events = new Map<string, any>();
	const active = new Set<string>();
	const pi = {
		exec,
		registerTool(tool: any) { tools.set(tool.name, tool); active.add(tool.name); },
		registerCommand(name: string, command: any) { commands.set(name, command); },
		on(name: string, handler: any) { events.set(name, handler); },
		getActiveTools() { return [...active]; },
		setActiveTools(names: string[]) {
			active.clear();
			for (const name of names) active.add(name);
		},
	} as unknown as ExtensionAPI;

	const previousBinary = process.env.INCISE_BIN;
	const previousProfile = process.env.INCISE_PROFILE;
	process.env.INCISE_BIN = binary;
	process.env.INCISE_PROFILE = "auto";
	try {
		await inciseExtension(pi);
	} finally {
		if (previousBinary === undefined) delete process.env.INCISE_BIN;
		else process.env.INCISE_BIN = previousBinary;
		if (previousProfile === undefined) delete process.env.INCISE_PROFILE;
		else process.env.INCISE_PROFILE = previousProfile;
	}

	const directory = await mkdtemp(join(tmpdir(), "pi-incise-auto-"));
	await copyFile(
		resolve(repository, "corpus", "sections", "setext-and-atx.md"),
		join(directory, "sections.md"),
	);
	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: 'In @sections.md, rename "Closed ATX level 3" to "Closed ATX heading".',
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, { cwd: directory, model: { id: "gemma4-direct-q8" } } as any);
	assert.deepEqual([...active], ["section_rename_target"]);

	let notice = "";
	await commands.get("incise-doctor").handler("", {
		ui: { notify(text: string) { notice = text; } },
	} as any);
	assert.match(notice, /profile requested: auto/);
	assert.match(notice, /profile effective: safe-routed/);
	assert.match(notice, /model family: gemma/);
	assert.match(notice, /last route: section-rename/);

	await events.get("before_agent_start")({
		type: "before_agent_start",
		prompt: "Summarize @sections.md.",
		systemPrompt: "System.",
		systemPromptOptions: {},
	}, { cwd: directory, model: { id: "openbmb/MiniCPM5-2B" } } as any);
	assert(active.has("section_edit"));
	await commands.get("incise-doctor").handler("", {
		ui: { notify(text: string) { notice = text; } },
	} as any);
	assert.match(notice, /model: gemma4-direct-q8/);
});
