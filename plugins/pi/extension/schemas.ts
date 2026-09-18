import type { Exec } from "./runner.ts";

export interface ToolSchema {
	name: string;
	description: string;
	parameters: Record<string, unknown>;
}

const PATH = {
	type: "string",
	description: "Path to the markdown file.",
};

export const STRUCTURAL_READ_SCHEMAS: ToolSchema[] = [
	{
		name: "md_tables",
		description: "List every markdown table in a document: the heading each one sits under, its column names, and how many rows it has. Returns the structure, not the document text. Call this before a `table_edit` to get the exact `table` heading and `column` spellings it needs, and again if an edit is refused for a table or column that is not there.",
		parameters: { type: "object", properties: { path: PATH }, required: ["path"] },
	},
	{
		name: "md_lists",
		description: "List every bullet or task list in a markdown document: the heading each one sits under, how many items it has, and whether they are checkboxes. Returns the structure, not the document text. Call this before a `list_edit` to get the exact `list` heading and the item text its `match` needs.",
		parameters: { type: "object", properties: { path: PATH }, required: ["path"] },
	},
	{
		name: "md_outline",
		description: "List the headings of a markdown document as a tree, with the level and ordinal of each. Returns the structure, not the document text. Call this to find the heading to address a `section_edit` to, or to see what a file contains before editing it.",
		parameters: { type: "object", properties: { path: PATH }, required: ["path"] },
	},
];

const MEASURED_NAMES = new Set([
	"table_edit",
	"list_edit",
	"section_edit",
	"frontmatter_edit",
	"table_get",
]);

export async function loadMeasuredSchemas(exec: Exec, binary: string): Promise<ToolSchema[]> {
	const result = await exec(binary, ["schema"], { timeout: 10_000 });
	if (result.code !== 0) throw new Error((result.stderr || result.stdout).trim() || "incise schema failed");
	let value: unknown;
	try {
		value = JSON.parse(result.stdout);
	} catch {
		throw new Error("incise schema did not return valid JSON");
	}
	if (!Array.isArray(value) || value.length !== MEASURED_NAMES.size) {
		throw new Error("incise schema did not return the five measured tool schemas");
	}
	const schemas = value as ToolSchema[];
	if (!schemas.every((schema) => schema && typeof schema.name === "string" &&
		MEASURED_NAMES.has(schema.name) && typeof schema.description === "string" &&
		schema.parameters && typeof schema.parameters === "object")) {
		throw new Error("incise schema returned an unexpected tool schema");
	}
	if (new Set(schemas.map((schema) => schema.name)).size !== MEASURED_NAMES.size) {
		throw new Error("incise schema returned duplicate tool names");
	}
	return schemas;
}

export const PROMPT_METADATA: Readonly<Record<string, { snippet: string; guidelines: string[] }>> = {
	md_tables: {
		snippet: "Inspect Markdown tables before structured table edits",
		guidelines: ["Use md_tables before table_edit to copy exact table addresses and column names."],
	},
	md_lists: {
		snippet: "Inspect Markdown lists before structured list edits",
		guidelines: ["Use md_lists before list_edit to copy exact list addresses and item text."],
	},
	md_outline: {
		snippet: "Inspect Markdown section structure before section edits",
		guidelines: ["Use md_outline before section_edit to copy exact heading paths."],
	},
	table_get: {
		snippet: "Read selected rows from a Markdown table",
		guidelines: ["Use table_get instead of reconstructing a Markdown table when only selected rows are needed."],
	},
	table_edit: {
		snippet: "Edit Markdown tables without reconstructing them",
		guidelines: ["Use table_edit for structured Markdown table changes and follow any Incise refusal remedy."],
	},
	list_edit: {
		snippet: "Edit Markdown lists without reconstructing them",
		guidelines: ["Use list_edit for structured Markdown list changes and follow any Incise refusal remedy."],
	},
	section_edit: {
		snippet: "Edit Markdown sections without reconstructing them",
		guidelines: ["Use section_edit for Markdown section changes and follow any Incise refusal remedy."],
	},
	frontmatter_edit: {
		snippet: "Edit Markdown frontmatter without rewriting it",
		guidelines: ["Use frontmatter_edit for Markdown frontmatter changes and follow any Incise refusal remedy."],
	},
};
