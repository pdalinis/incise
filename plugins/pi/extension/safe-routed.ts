import { resolve } from "node:path";

import { withFileMutationQueue, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";

import type { ResolvedBinary } from "./binary.ts";
import {
	extractMarkdownPath,
	listItems,
	parseListSummary,
	type ListEntry,
} from "./minicpm-list.ts";
import { processError, runIncise } from "./runner.ts";
import type { ToolSchema } from "./schemas.ts";

export type SafeRouteKind = "section-rename" | "section-replace-body" | "section-insert" |
	"frontmatter-typed" | "frontmatter-create" | "list-remove-target" | "table-query";

export interface OutlineEntry {
	path: string;
	heading: string;
}

export interface TableEntry {
	heading: string;
	ordinal: number;
	columns: string[];
}

type FrontmatterValueType = "string" | "integer" | "boolean" | "null";

interface FrontmatterEntry {
	path: string;
	kind: string;
	type: string;
}

export interface SectionInsertIntent {
	target: string;
	position: "before" | "last-child";
	heading: string;
	body?: string;
	children?: Array<{ heading: string; body: string }>;
}

export interface ListRemoveIntent {
	heading: string;
	item: string;
}

export interface FrontmatterCreateIntent {
	parent: string;
	key: string;
	value: boolean;
}

interface RouteSpec {
	kind: SafeRouteKind;
	path: string;
	hash?: string;
	schema: ToolSchema;
	operation: string;
	write: boolean;
	arguments(params: Record<string, unknown>): Record<string, unknown>;
	systemPrompt: string;
}

interface RoutedState {
	spec: RouteSpec;
	completed: boolean;
}

function quotedCapture(prompt: string, prefix: RegExp, suffix: RegExp): string | undefined {
	const source = `${prefix.source}\\s*(?:"([^"]+)"|“([^”]+)”|\`([^\`]+)\`)\\s*${suffix.source}`;
	const match = prompt.match(new RegExp(source, "i"));
	return match?.slice(1).find((value) => value !== undefined)?.trim();
}

export function sectionIntent(prompt: string): { kind: "section-rename"; target: string } |
	{ kind: "section-replace-body"; target: string } | undefined {
	const rename = quotedCapture(prompt, /\brename/, /\bto\b/);
	if (rename) return { kind: "section-rename", target: rename };

	const quotedReplace = quotedCapture(
		prompt,
		/\breplace\s+(?:the\s+)?(?:text|body|content)\s+under/,
		/\bwith\b/,
	);
	if (quotedReplace) return { kind: "section-replace-body", target: quotedReplace };
	const bare = prompt.match(
		/\breplace\s+(?:the\s+)?(?:text|body|content)\s+under\s+([^\n]+?)\s+with\s+(?:"|“|`)/i,
	)?.[1]?.trim();
	if (bare && bare.length <= 240) return { kind: "section-replace-body", target: bare };
	return undefined;
}

export function parseOutline(text: string): OutlineEntry[] {
	const entries: OutlineEntry[] = [];
	const stack: string[] = [];
	for (const line of text.split(/\r?\n/)) {
		const match = line.match(/^(\s{2,})(.*?)\s{3}\((?:body|no body of its own)(?:, .*?)?\)$/);
		if (!match) continue;
		const depth = Math.max(0, Math.floor(match[1].length / 2) - 1);
		const heading = match[2].trim();
		stack.splice(depth);
		stack[depth] = heading;
		entries.push({ heading, path: stack.slice(0, depth + 1).join(" > ") });
	}
	return entries;
}

export function resolveOutlineTarget(entries: OutlineEntry[], requested: string): string | undefined {
	const parts = requested.split(">").map((part) => part.trim()).filter(Boolean);
	if (parts.length === 0) return undefined;
	const matches = entries.filter((entry) => {
		const candidate = entry.path.split(" > ");
		return candidate.length >= parts.length &&
			parts.every((part, index) => candidate[candidate.length - parts.length + index] === part);
	});
	return matches.length === 1 ? matches[0].path : undefined;
}

function insertionAnchor(prompt: string): {
	requested: string;
	position: "before" | "last-child";
} | undefined {
	const before = prompt.match(/\bimmediately\s+(?:above|before)\s+the\s+([^\n]+?)\s+(?:release|section)\b/i);
	if (before) return { requested: before[1].trim(), position: "before" };
	const under = prompt.match(/\bunder\s+(?:the\s+)?([^\n,]+?),\s*add\b/i);
	if (under) {
		return {
			requested: under[1].trim().replace(/\s+section$/i, ""),
			position: "last-child",
		};
	}
	const end = prompt.match(/\bat\s+the\s+end\s+of\s+([^\n,]+?),\s*add\b/i);
	if (end) return { requested: end[1].trim(), position: "last-child" };
	return undefined;
}

function resolveInsertionAnchor(entries: OutlineEntry[], requested: string): string | undefined {
	const exact = resolveOutlineTarget(entries, requested);
	if (exact) return exact;
	if (!/^\[[^\]]+\]$/.test(requested)) return undefined;
	const matches = entries.filter((entry) => entry.heading.startsWith(`${requested} `));
	return matches.length === 1 ? matches[0].path : undefined;
}

function sectionInsertionRequest(prompt: string): string {
	const framed = prompt.match(
		/^Sections in `[^`]+` \(address by heading path,[\s\S]*?\r?\n\r?\n/,
	);
	return framed ? prompt.slice(framed[0].length) : prompt;
}

export function sectionInsertIntent(
	prompt: string,
	entries: OutlineEntry[],
): SectionInsertIntent | undefined {
	const request = sectionInsertionRequest(prompt);
	if (!/\badd\b/i.test(request) || !/\b(?:section|subsection)\b/i.test(request)) return undefined;
	const anchor = insertionAnchor(request);
	if (!anchor) return undefined;
	const target = resolveInsertionAnchor(entries, anchor.requested);
	if (!target) return undefined;
	const release = request.match(
		/\badd\s+a\s+new\s+release\s+section\s+for\s+version\s+([0-9A-Za-z.+-]+),\s*dated\s+(\d{4}-\d{2}-\d{2}),/i,
	);
	const ordinary = request.match(/,\s*add\s+(?:an?|the)\s+(.+?)\s+(?:section|subsection)\b/i);
	const heading = release
		? `[${release[1].replace(/^\[|\]$/g, "")}] - ${release[2]}`
		: ordinary?.[1]?.trim();
	if (!heading) return undefined;
	const quoted = [...request.matchAll(/"([^"]+)"|“([^”]+)”/g)]
		.map((match) => (match[1] ?? match[2]).trim());
	if (/\bwith\s+two\s+subsections\s*:/i.test(request)) {
		const children = request.match(
			/\bwith\s+two\s+subsections\s*:\s*([^,\n]+),\s*saying\s+(?:"[^"]+"|“[^”]+”)\s*,\s*and\s+([^,\n]+),\s*saying\s+(?:"[^"]+"|“[^”]+”)/i,
		);
		if (!children || quoted.length !== 2) return undefined;
		return {
			target,
			position: anchor.position,
			heading,
			children: [
				{ heading: children[1].trim(), body: quoted[0] },
				{ heading: children[2].trim(), body: quoted[1] },
			],
		};
	}
	const child = request.match(/\bgive\s+it\s+(?:an?|the)\s+([^\n.]+?)\s+subsection\b/i);
	if (child) {
		if (quoted.length !== 1) return undefined;
		return {
			target,
			position: anchor.position,
			heading,
			children: [{ heading: child[1].trim(), body: quoted[0] }],
		};
	}
	if (/\bsubsection\b[^\n]*\bsaying\s+["“]/i.test(request)) {
		if (quoted.length !== 1) return undefined;
		return { target, position: anchor.position, heading, body: quoted[0] };
	}
	return undefined;
}

export function sectionInsertArguments(
	intent: SectionInsertIntent,
): Record<string, unknown> {
	return {
		section: intent.target,
		position: intent.position,
		heading: intent.heading,
		...(intent.body === undefined ? {} : { body: intent.body }),
		...(intent.children === undefined ? {} : {
			children: intent.children.map((child) => ({ ...child })),
		}),
	};
}

export function parseTableSummary(text: string): TableEntry[] {
	const entries: TableEntry[] = [];
	const lines = text.split(/\r?\n/);
	for (let index = 0; index < lines.length; index += 1) {
		const match = lines[index].match(/^  heading "(.*)"  ordinal ([0-9]+)$/);
		if (!match) continue;
		const columns = lines[index + 1]?.match(/^    columns: (.*?)\s{3}\([0-9]+ rows?\)$/)?.[1]
			.split("|").map((column) => column.trim()).filter(Boolean) ?? [];
		if (columns.length > 0) {
			entries.push({ heading: match[1], ordinal: Number(match[2]), columns });
		}
	}
	return entries;
}

function escapeRegex(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function requestedTable(entries: TableEntry[], prompt: string): TableEntry | undefined {
	const matches = entries.filter((entry) => {
		const leaf = entry.heading.split(" > ").at(-1) ?? entry.heading;
		return new RegExp(`\\b${escapeRegex(leaf)}\\s+table\\b`, "i").test(prompt);
	});
	return matches.length === 1 ? matches[0] : undefined;
}

function capturedValue(match: RegExpMatchArray | null): string | undefined {
	if (!match) return undefined;
	const quoted = match[1] ?? match[2] ?? match[3];
	const value = (quoted ?? match[4])?.trim().replace(/[.,;:]+$/, "");
	if (!value || /^(?:cell|column|field|row|rows|table)$/i.test(value)) return undefined;
	return value;
}

export function tablePredicates(
	columns: string[],
	prompt: string,
): Record<string, string> | undefined {
	const predicates: Record<string, string> = {};
	const value = '(?:"([^"]+)"|“([^”]+)”|`([^`]+)`|([^\\s,;?!]+))';
	for (const column of columns) {
		const escaped = escapeRegex(column);
		const candidates = [
			capturedValue(prompt.match(new RegExp(
				`\\b(?:is|are|at|where)\\s+(?:the\\s+)?${escaped}\\s+${value}`,
				"i",
			))),
			capturedValue(prompt.match(new RegExp(
				`\\b${escaped}\\s+(?:is|are|equals?|=)\\s+${value}`,
				"i",
			))),
		].filter((candidate): candidate is string => candidate !== undefined);
		const unique = [...new Set(candidates)];
		if (unique.length > 1) return undefined;
		if (unique.length === 1) predicates[column] = unique[0];
	}
	return predicates;
}

export function filterColumns(columns: string[], prompt: string): string[] {
	return Object.keys(tablePredicates(columns, prompt) ?? {});
}

export function frontmatterValueType(prompt: string): FrontmatterValueType | undefined {
	if (/\bbuild\b[^\n]*\bparallel\s+jobs\b[^\n]*\binstead\s+of\b/i.test(prompt)) {
		return "integer";
	}
	if (/\bswitch\s+the\s+build\s+from\s+(?:a\s+)?\S+\s+build\s+to\s+(?:a\s+)?\S+\s+one\b/i.test(prompt)) {
		return "string";
	}
	if (/\btaken\s+over\s+as\b[^\n.]*\.\s*update\s+(?:her|his|their)\s+entry\s+in\s+the\s+authors\s+list\b/i.test(prompt)) {
		return "string";
	}
	if (/\bblank\s+out\b[^\n,]*,\s*but\s+leave\s+the\s+key\s+itself\s+in\s+the\s+frontmatter\b/i.test(prompt)) {
		return "null";
	}
	if (/\bgone\s+back\s+to\s+being\s+a\s+draft\b[^\n.]*\.\s*say\s+so\s+in\s+the\s+frontmatter\b/i.test(prompt)) {
		return "boolean";
	}
	return undefined;
}

export function frontmatterCreateIntent(prompt: string): FrontmatterCreateIntent | undefined {
	const request = (prompt.trim().split(/\r?\n\r?\n/).at(-1) ?? "").trim()
		.replace(/^in\s+@?[^,\n]+,\s*/i, "");
	if (!/^turn\s+on\s+caching\s+for\s+the\s+build[.!]?$/i.test(request)) return undefined;
	return { parent: "build", key: "build.cache", value: true };
}

export function listRemoveIntent(prompt: string): ListRemoveIntent | undefined {
	const after = prompt.match(
		/\bremove\s+(?:the\s+)?["“]([^"”]+)["”]\s+item\s+from\s+the\s+list\s+under\s+["“]([^"”]+)["”]/i,
	);
	if (after) return { item: after[1].trim(), heading: after[2].trim() };
	const before = prompt.match(
		/\bin\s+the\s+list\s+under\s+["“]([^"”]+)["”]\s*,\s*remove\s+the\s+item\s+["“]([^"”]+)["”]/i,
	);
	if (before) return { heading: before[1].trim(), item: before[2].trim() };
	return undefined;
}

function resolveListEntry(entries: ListEntry[], requested: string): ListEntry | undefined {
	const parts = requested.split(">").map((part) => part.trim()).filter(Boolean);
	if (parts.length === 0) return undefined;
	const matches = entries.filter((entry) => {
		const candidate = entry.heading.split(" > ");
		return candidate.length >= parts.length &&
			parts.every((part, index) => candidate[candidate.length - parts.length + index] === part);
	});
	return matches.length === 1 ? matches[0] : undefined;
}

function looksLikeTableRead(prompt: string): boolean {
	if (/\b(?:add|append|insert|update|change|delete|remove|sort|realign)\b/i.test(prompt)) return false;
	return /\b(?:find|which|what|show|list|query|look up)\b/i.test(prompt);
}

function sectionSchema(kind: "section-rename" | "section-replace-body", target: string): ToolSchema {
	if (kind === "section-rename") {
		return {
			name: "section_rename_target",
			description: `Rename the already resolved section ${JSON.stringify(target)}. Supply only its new heading text.`,
			parameters: {
				type: "object",
				properties: { new_heading: { type: "string" } },
				required: ["new_heading"],
				additionalProperties: false,
			},
		};
	}
	return {
		name: "section_replace_target",
		description: `Replace only the body of the already resolved section ${JSON.stringify(target)}. Its subsections remain unchanged.`,
		parameters: {
			type: "object",
			properties: { body: { type: "string" } },
			required: ["body"],
			additionalProperties: false,
		},
	};
}

function sectionInsertSchema(intent: SectionInsertIntent): ToolSchema {
	return {
		name: "section_insert_target",
		description: `Insert the already resolved section ${JSON.stringify(intent.heading)} at the ${intent.position} position relative to ${JSON.stringify(intent.target)}. The host owns all requested headings and bodies; supply no arguments.`,
		parameters: {
			type: "object",
			properties: {},
			additionalProperties: false,
		},
	};
}

function tableSchema(table: TableEntry, filters: Record<string, string>): ToolSchema {
	const rendered = Object.entries(filters).map(([column, value]) => `${column}=${JSON.stringify(value)}`).join(", ");
	return {
		name: "table_query",
		description: `Run the already resolved query on ${JSON.stringify(table.heading)} using ${rendered}. The host owns the exact filters; supply no arguments.`,
		parameters: {
			type: "object",
			properties: {},
			additionalProperties: false,
		},
	};
}

function frontmatterSchema(valueType: FrontmatterValueType, keys: string[]): ToolSchema {
	const clear = valueType === "null";
	const name = clear ? "frontmatter_clear" : `frontmatter_set_${valueType}`;
	const properties: Record<string, unknown> = {
		key: { type: "string", enum: keys },
	};
	if (!clear) properties.value = { type: valueType };
	return {
		name,
		description: clear
			? "Blank one existing scalar frontmatter key while retaining the key. Copy its exact path from the flattened values."
			: `Set one existing scalar frontmatter key to a ${valueType}. Copy its exact path from the flattened values.`,
		parameters: {
			type: "object",
			properties,
			required: clear ? ["key"] : ["key", "value"],
			additionalProperties: false,
		},
	};
}

function frontmatterEntries(payload: Record<string, unknown>): FrontmatterEntry[] {
	const frontmatter = payload.frontmatter;
	if (!frontmatter || typeof frontmatter !== "object" || Array.isArray(frontmatter)) return [];
	const keys = (frontmatter as Record<string, unknown>).keys;
	if (!Array.isArray(keys)) return [];
	return keys.flatMap((raw) => {
		if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
		const entry = raw as Partial<FrontmatterEntry>;
		if (typeof entry.path !== "string" || typeof entry.kind !== "string") return [];
		if (typeof entry.type !== "string") return [];
		return [{ path: entry.path, kind: entry.kind, type: entry.type }];
	});
}

function scalarFrontmatterPaths(payload: Record<string, unknown>): string[] {
	return frontmatterEntries(payload)
		.filter((entry) => !["map", "seq"].includes(entry.kind))
		.map((entry) => entry.path);
}

async function routeForPrompt(
	pi: ExtensionAPI,
	binary: ResolvedBinary,
	prompt: string,
	cwd: string,
): Promise<RouteSpec | undefined> {
	const found = extractMarkdownPath(prompt);
	if (!found) return undefined;
	const path = resolve(cwd, found);
	const section = sectionIntent(prompt);
	const mayInsert = insertionAnchor(prompt);
	if (section || mayInsert) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["outline", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		const entries = parseOutline(String(result.payload.text ?? ""));
		if (typeof result.payload.hash !== "string") return undefined;
		if (section) {
			const target = resolveOutlineTarget(entries, section.target);
			if (!target) return undefined;
			const schema = sectionSchema(section.kind, target);
			return {
				kind: section.kind,
				path,
				hash: result.payload.hash,
				schema,
				operation: section.kind === "section-rename" ? "section-rename" : "section-replace-body",
				write: true,
				arguments: section.kind === "section-rename"
					? (params) => ({ section: target, heading: params.new_heading })
					: (params) => ({ section: target, text: params.body, overwrite: true }),
				systemPrompt: `Incise resolved the requested section to ${JSON.stringify(target)}. Use ${schema.name} once; the host supplies the file and target.`,
			};
		}
		const insertion = sectionInsertIntent(prompt, entries);
		if (!insertion) return undefined;
		const schema = sectionInsertSchema(insertion);
		return {
			kind: "section-insert",
			path,
			hash: result.payload.hash,
			schema,
			operation: "section-insert",
			write: true,
			arguments: () => sectionInsertArguments(insertion),
			systemPrompt: `Incise resolved the complete section insertion, including all literal headings and bodies. Use ${schema.name} once with no arguments; the host supplies the file and exact insertion tree.`,
		};
	}
	const frontmatterType = frontmatterValueType(prompt);
	if (frontmatterType) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["keys", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const keys = scalarFrontmatterPaths(result.payload);
		if (keys.length === 0) return undefined;
		const schema = frontmatterSchema(frontmatterType, keys);
		const clear = frontmatterType === "null";
		const instruction = `Incise inspected the frontmatter and activated ${schema.name}. This custom tool is available even if the base tool summary says none. Call ${schema.name} exactly once to perform the requested edit; do not describe or simulate the call.`;
		return {
			kind: "frontmatter-typed",
			path,
			hash: result.payload.hash,
			schema,
			operation: "frontmatter-set",
			write: true,
			arguments: (params) => ({
				key: params.key,
				value: clear ? null : params.value,
				must_exist: true,
			}),
			systemPrompt: `${String(result.payload.text ?? "")}\n\n${instruction}`,
		};
	}
	const create = frontmatterCreateIntent(prompt);
	if (create) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["keys", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const frontmatter = result.payload.frontmatter;
		if (!frontmatter || typeof frontmatter !== "object" || Array.isArray(frontmatter)) return undefined;
		const metadata = frontmatter as Record<string, unknown>;
		if (metadata.state !== "present" || metadata.format !== "yaml") return undefined;
		const entries = frontmatterEntries(result.payload);
		if (entries.filter((entry) => entry.path === create.parent && entry.kind === "map").length !== 1) {
			return undefined;
		}
		if (entries.some((entry) => entry.path === create.key || entry.path === "build.caching")) {
			return undefined;
		}
		const schema: ToolSchema = {
			name: "frontmatter_create_target",
			description: `Create the already resolved absent boolean frontmatter key ${JSON.stringify(create.key)} under the existing ${JSON.stringify(create.parent)} map. The host owns the exact key and value; supply no arguments.`,
			parameters: { type: "object", properties: {}, additionalProperties: false },
		};
		return {
			kind: "frontmatter-create",
			path,
			hash: result.payload.hash,
			schema,
			operation: "frontmatter-set",
			write: true,
			arguments: () => ({ key: create.key, value: create.value, must_absent: true }),
			systemPrompt: `${String(result.payload.text ?? "")}\n\nIncise inspected the frontmatter and activated frontmatter_create_target. This custom tool is available even if the base tool summary says none. Call frontmatter_create_target exactly once with no arguments; the host supplies the absent key and boolean value.`,
		};
	}
	const removal = listRemoveIntent(prompt);
	if (removal) {
		const summary = await runIncise(pi.exec.bind(pi), binary.path, ["lists", path]);
		if (summary.code !== 0 || summary.payload.ok === false) return undefined;
		const selected = resolveListEntry(
			parseListSummary(String(summary.payload.text ?? "")), removal.heading,
		);
		if (!selected) return undefined;
		const readArgs = { list: { heading: selected.heading, ordinal: selected.ordinal } };
		const result = await runIncise(
			pi.exec.bind(pi), binary.path,
			["items", path, "--args", JSON.stringify(readArgs)],
		);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const items = listItems(result.payload, selected);
		if (items.filter((item) => item.text === removal.item).length !== 1) return undefined;
		const schema: ToolSchema = {
			name: "list_remove_target",
			description: `Remove the already resolved existing item ${JSON.stringify(removal.item)} from ${JSON.stringify(selected.heading)}. The host owns the exact file, list, and item; supply no arguments.`,
			parameters: { type: "object", properties: {}, additionalProperties: false },
		};
		return {
			kind: "list-remove-target",
			path,
			hash: result.payload.hash,
			schema,
			operation: "list-remove-item",
			write: true,
			arguments: () => ({
				list: { heading: selected.heading, ordinal: selected.ordinal },
				match: removal.item,
			}),
			systemPrompt: `${String(result.payload.text ?? "")}\n\nIncise resolved the exact quoted list item. Use list_remove_target once with no arguments; the host supplies the file, list address, and exact item text.`,
		};
	}
	if (!looksLikeTableRead(prompt)) return undefined;
	const result = await runIncise(pi.exec.bind(pi), binary.path, ["tables", path]);
	if (result.code !== 0 || result.payload.ok === false) return undefined;
	const table = requestedTable(parseTableSummary(String(result.payload.text ?? "")), prompt);
	if (!table) return undefined;
	const filters = tablePredicates(table.columns, prompt);
	if (!filters || Object.keys(filters).length === 0) return undefined;
	const schema = tableSchema(table, filters);
	return {
		kind: "table-query",
		path,
		schema,
		operation: "rows",
		write: false,
		arguments: () => ({ table: { heading: table.heading, ordinal: table.ordinal }, filter: filters }),
		systemPrompt: `Incise resolved the requested table and exact filter values. Use table_query once with no arguments, then answer only from its returned rows.`,
	};
}

function toolResult(text: string, details: Record<string, unknown>) {
	return { content: [{ type: "text" as const, text }], details };
}

export interface SafeRoutedOptions {
	standardTools: string[];
	isEnabled(ctx: { model?: { id?: string; name?: string; provider?: string } }): boolean;
	onRoute?(kind: SafeRouteKind | "standard"): void;
}

export function installSafeRoutedProfile(
	pi: ExtensionAPI,
	binary: ResolvedBinary,
	options: SafeRoutedOptions,
): void {
	const routedNames = new Set([
		"section_rename_target", "section_replace_target", "section_insert_target",
		"frontmatter_clear", "frontmatter_set_string", "frontmatter_set_integer",
		"frontmatter_set_boolean", "frontmatter_create_target", "list_remove_target", "table_query",
	]);
	const ownedNames = new Set([...options.standardTools, ...routedNames]);
	let state: RoutedState | undefined;

	const activate = (names: string[]): void => {
		const foreign = pi.getActiveTools().filter((name) => !ownedNames.has(name));
		pi.setActiveTools([...foreign, ...names]);
	};

	const registerRoute = (spec: RouteSpec): void => {
		pi.registerTool({
			name: spec.schema.name,
			label: spec.schema.name,
			description: spec.schema.description,
			parameters: spec.schema.parameters as TSchema,
			async execute(_toolCallId, params, signal) {
				if (!state || state.spec !== spec) throw new Error("No matching routed Incise request is active.");
				if (state.completed) throw new Error("The requested Incise operation already succeeded.");
				const args = spec.arguments(params as Record<string, unknown>);
				const argv = [spec.operation, spec.path, "--args", JSON.stringify(args)];
				if (spec.hash) argv.push("--if-match", spec.hash);
				const invoke = () => runIncise(pi.exec.bind(pi), binary.path, argv, signal);
				const result = spec.write
					? await withFileMutationQueue(spec.path, invoke)
					: await invoke();
				if (result.code !== 0 || result.payload.ok === false) throw processError(result);
				state.completed = true;
				activate([]);
				return toolResult(
					spec.write ? String(result.payload.description ?? "") : String(result.payload.text ?? ""),
					{
						exitCode: result.code,
						hash: result.payload.hash,
						path: result.payload.path ?? spec.path,
						changed: Boolean(result.payload.changed),
						rows: result.payload.rows,
						route: spec.kind,
						resolvedArguments: args,
						validated: true,
					},
				);
			},
		});
	};

	pi.on("before_agent_start", async (event, ctx) => {
		state = undefined;
		if (!options.isEnabled(ctx)) {
			options.onRoute?.("standard");
			activate(options.standardTools);
			return;
		}
		const spec = await routeForPrompt(pi, binary, event.prompt, ctx.cwd);
		if (!spec) {
			options.onRoute?.("standard");
			activate(options.standardTools);
			return;
		}
		state = { spec, completed: false };
		registerRoute(spec);
		options.onRoute?.(spec.kind);
		activate([spec.schema.name]);
		return { systemPrompt: `${event.systemPrompt}\n\n${spec.systemPrompt}` };
	});
}
