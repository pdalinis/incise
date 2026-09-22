import { resolve } from "node:path";

import { withFileMutationQueue, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";

import type { ResolvedBinary } from "./binary.ts";
import { extractMarkdownPath } from "./minicpm-list.ts";
import { processError, runIncise } from "./runner.ts";
import type { ToolSchema } from "./schemas.ts";

export type SafeRouteKind = "section-rename" | "section-replace-body" | "section-insert" | "table-query";

export interface OutlineEntry {
	path: string;
	heading: string;
}

export interface TableEntry {
	heading: string;
	ordinal: number;
	columns: string[];
}

export interface SectionInsertIntent {
	target: string;
	position: "before" | "last-child";
	shape: "body" | "one-child" | "two-children";
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

export function sectionInsertIntent(
	prompt: string,
	entries: OutlineEntry[],
): SectionInsertIntent | undefined {
	if (!/\badd\b/i.test(prompt) || !/\b(?:section|subsection)\b/i.test(prompt)) return undefined;
	const anchor = insertionAnchor(prompt);
	if (!anchor) return undefined;
	const target = resolveInsertionAnchor(entries, anchor.requested);
	if (!target) return undefined;
	let shape: SectionInsertIntent["shape"];
	if (/\bwith\s+two\s+subsections\s*:/i.test(prompt)) {
		shape = "two-children";
	} else if (/\bgive\s+it\s+(?:an?|the)\s+[^\n.]+?\s+subsection\b/i.test(prompt)) {
		shape = "one-child";
	} else if (/\bsubsection\b[^\n]*\bsaying\s+["“`]/i.test(prompt)) {
		shape = "body";
	} else {
		return undefined;
	}
	return { target, position: anchor.position, shape };
}

export function sectionInsertArguments(
	intent: SectionInsertIntent,
	params: Record<string, unknown>,
): Record<string, unknown> {
	const common = {
		section: intent.target,
		position: intent.position,
		heading: params.new_heading,
	};
	if (intent.shape === "body") return { ...common, body: params.body };
	if (intent.shape === "one-child") {
		return {
			...common,
			children: [{ heading: params.subsection_heading, body: params.subsection_body }],
		};
	}
	return {
		...common,
		children: [
			{ heading: params.first_subsection_heading, body: params.first_subsection_body },
			{ heading: params.second_subsection_heading, body: params.second_subsection_body },
		],
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
	const common = { new_heading: { type: "string" } };
	let properties: Record<string, unknown>;
	let required: string[];
	if (intent.shape === "body") {
		properties = { ...common, body: { type: "string" } };
		required = ["new_heading", "body"];
	} else if (intent.shape === "one-child") {
		properties = {
			...common,
			subsection_heading: { type: "string" },
			subsection_body: { type: "string" },
		};
		required = ["new_heading", "subsection_heading", "subsection_body"];
	} else {
		properties = {
			...common,
			first_subsection_heading: { type: "string" },
			first_subsection_body: { type: "string" },
			second_subsection_heading: { type: "string" },
			second_subsection_body: { type: "string" },
		};
		required = [
			"new_heading", "first_subsection_heading", "first_subsection_body",
			"second_subsection_heading", "second_subsection_body",
		];
	}
	return {
		name: "section_insert_target",
		description: `Insert the requested section at the already resolved ${intent.position} position relative to ${JSON.stringify(intent.target)}. Copy every requested heading and body exactly.`,
		parameters: {
			type: "object",
			properties,
			required,
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
			arguments: (params) => sectionInsertArguments(insertion, params),
			systemPrompt: `Incise resolved the insertion anchor to ${JSON.stringify(insertion.target)} with position ${JSON.stringify(insertion.position)}. Use ${schema.name} once; supply only the requested new content fields.`,
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
		"section_rename_target", "section_replace_target", "section_insert_target", "table_query",
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
