import { resolve } from "node:path";

export type ToolArguments = Record<string, unknown>;

export const WRITE_TOOLS = new Set([
	"table_edit",
	"list_edit",
	"section_edit",
	"frontmatter_edit",
	"table_add_row",
	"table_update_cell",
	"list_add_item",
	"section_insert",
	"section_append",
	"frontmatter_set",
]);

export const READ_SUBCOMMAND: Readonly<Record<string, string>> = {
	md_outline: "outline",
	md_tables: "tables",
	md_lists: "lists",
	table_get: "rows",
	list_get: "items",
	frontmatter_get: "keys",
};

function actionName(value: unknown): string {
	return value === undefined || value === null ? "None" : String(value);
}

export function normalizeEdit(name: string, input: ToolArguments): { operation: string; args: ToolArguments } {
	const narrow: Readonly<Record<string, string>> = {
		table_add_row: "table-add-row",
		table_update_cell: "table-update-cell",
		list_add_item: "list-add-item",
		section_append: "section-append",
		frontmatter_set: "frontmatter-set",
	};
	const narrowOperation = narrow[name];
	if (narrowOperation) return { operation: narrowOperation, args: input };
	if (name === "section_insert") {
		const args: ToolArguments = { ...input };
		if ("parent" in args) {
			args.section = args.parent;
			delete args.parent;
		}
		if ("new_heading" in args) {
			args.heading = args.new_heading;
			delete args.new_heading;
		}
		if ("body" in args) {
			args.text = args.body;
			delete args.body;
		}
		if (args.section && typeof args.section === "object" && !Array.isArray(args.section)) {
			const section = { ...(args.section as ToolArguments) };
			if ("heading" in section && !("path" in section)) {
				section.path = section.heading;
				delete section.heading;
			}
			args.section = section;
		}
		return { operation: "section-insert", args };
	}
	if (name === "table_edit") return { operation: `table-${actionName(input.action)}`, args: input };
	if (name === "list_edit") return { operation: `list-${actionName(input.action)}`, args: input };
	if (name === "frontmatter_edit") {
		return { operation: `frontmatter-${actionName(input.action)}`, args: input };
	}
	if (name !== "section_edit") throw new Error(`not an edit tool: ${name}`);

	const args: ToolArguments = { ...input };
	if ("new_heading" in args) {
		args.heading = args.new_heading;
		delete args.new_heading;
	}
	if ("file" in args && !("path" in args)) {
		args.path = args.file;
		delete args.file;
	}
	if (args.section && typeof args.section === "object" && !Array.isArray(args.section)) {
		const section = { ...(args.section as ToolArguments) };
		if ("heading" in section && !("path" in section)) {
			section.path = section.heading;
			delete section.heading;
		}
		args.section = section;
	}
	return { operation: `section-${actionName(args.action)}`, args };
}

export function stripPiPathPrefix(path: string): string {
	return path.startsWith("@") ? path.slice(1) : path;
}

export function resolveToolPath(args: ToolArguments, cwd: string): { path: string; args: ToolArguments } {
	const raw = args.path ?? args.file;
	if (typeof raw !== "string" || !raw) {
		throw new Error("incise needs `path`: the markdown file to read or edit.");
	}
	const path = resolve(cwd, stripPiPathPrefix(raw));
	return { path, args: { ...args, path } };
}

export interface Invocation {
	operation: string;
	path: string;
	args: ToolArguments;
	write: boolean;
}

export function prepareInvocation(name: string, input: ToolArguments, cwd: string): Invocation {
	if (WRITE_TOOLS.has(name)) {
		const normalized = normalizeEdit(name, input);
		const located = resolveToolPath(normalized.args, cwd);
		return { operation: normalized.operation, path: located.path, args: located.args, write: true };
	}
	const operation = READ_SUBCOMMAND[name];
	if (!operation) throw new Error(`unknown incise tool: ${name}`);
	const located = resolveToolPath(input, cwd);
	return { operation, path: located.path, args: located.args, write: false };
}
