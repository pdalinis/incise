import { resolve } from "node:path";

import { withFileMutationQueue, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";

import type { ResolvedBinary } from "./binary.ts";
import { extractMarkdownPath } from "./minicpm-list.ts";
import { processError, runIncise } from "./runner.ts";
import type { ToolSchema } from "./schemas.ts";

export type SafeRouteKind = "section-rename" | "section-replace-body" | "table-query";

export interface OutlineEntry {
	path: string;
	heading: string;
}

export interface TableEntry {
	heading: string;
	ordinal: number;
	columns: string[];
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

export function filterColumns(columns: string[], prompt: string): string[] {
	return columns.filter((column) => {
		const escaped = escapeRegex(column);
		return new RegExp(`\\b(?:is|are|at|with|where|and)\\s+(?:the\\s+)?${escaped}\\b`, "i").test(prompt) ||
			new RegExp(`\\b${escaped}\\s+(?:is|are|equals?|=)\\b`, "i").test(prompt);
	});
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

function tableSchema(table: TableEntry, columns: string[]): ToolSchema {
	return {
		name: "table_query",
		description: `Query the already resolved ${JSON.stringify(table.heading)} table. Supply every requested filter exactly once.`,
		parameters: {
			type: "object",
			properties: Object.fromEntries(columns.map((column) => [column, { type: "string" }])),
			required: columns,
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
	if (section) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["outline", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		const target = resolveOutlineTarget(parseOutline(String(result.payload.text ?? "")), section.target);
		if (!target || typeof result.payload.hash !== "string") return undefined;
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
	if (!looksLikeTableRead(prompt)) return undefined;
	const result = await runIncise(pi.exec.bind(pi), binary.path, ["tables", path]);
	if (result.code !== 0 || result.payload.ok === false) return undefined;
	const table = requestedTable(parseTableSummary(String(result.payload.text ?? "")), prompt);
	if (!table) return undefined;
	const columns = filterColumns(table.columns, prompt);
	if (columns.length === 0) return undefined;
	const schema = tableSchema(table, columns);
	return {
		kind: "table-query",
		path,
		schema,
		operation: "rows",
		write: false,
		arguments: (params) => ({ table: { heading: table.heading, ordinal: table.ordinal }, filter: params }),
		systemPrompt: `Incise resolved the requested table and filter columns. Use table_query once, then answer only from its returned rows.`,
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
	const routedNames = new Set(["section_rename_target", "section_replace_target", "table_query"]);
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
