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
