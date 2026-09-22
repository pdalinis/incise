import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
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
	const providerBase = {
		model: "minicpm5-2b-q8",
		messages: [{ role: "user", content: "Insert the item." }],
		tools: [{ type: "function", function: { name: "list_select" } }],
		temperature: 0.7,
	};
	assert.deepEqual(
		events.get("before_provider_request")({
			type: "before_provider_request",
			payload: providerBase,
		}),
		{
			...providerBase,
			tool_choice: { type: "function", function: { name: "list_select" } },
		},
	);

	const selected = await tools.get("list_select").execute(
		"select", { heading: "Sequential", ordinal: 0 }, undefined, undefined, context,
	);
	assert.match(selected.content[0].text, /text="second"/);
	assert.deepEqual(active.at(-1), ["list_insert_between"]);
	const contentProviderBase = {
		...providerBase,
		tools: [{ type: "function", function: { name: "list_insert_between" } }],
	};
	assert.deepEqual(
		events.get("before_provider_request")({
			type: "before_provider_request",
			payload: contentProviderBase,
		}),
		{
			...contentProviderBase,
			tool_choice: { type: "function", function: { name: "list_insert_between" } },
		},
	);

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
	assert.equal(events.get("before_provider_request")({
		type: "before_provider_request",
		payload: contentProviderBase,
	}), undefined);
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
	const retryProviderBase = {
		...providerBase,
		tools: [{ type: "function", function: { name: "list_append_item" } }],
	};
	assert.deepEqual(
		events.get("before_provider_request")({
			type: "before_provider_request",
			payload: retryProviderBase,
		}),
		{
			...retryProviderBase,
			tool_choice: { type: "function", function: { name: "list_append_item" } },
		},
	);
	assert.equal(await readFile(path, "utf8"), externallyChanged);
});
