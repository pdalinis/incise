import { resolve } from "node:path";

import { withFileMutationQueue, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";

import type { ResolvedBinary } from "./binary.ts";
import { stripPiPathPrefix, type ToolArguments } from "./normalize.ts";
import { processError, runIncise, type IncisePayload } from "./runner.ts";
import type { ToolSchema } from "./schemas.ts";

export type ListRoute = "append" | "after" | "between";

export interface ListEntry {
	heading: string;
	ordinal: number;
}

export interface ListItem {
	text: string;
	depth: number;
	parent: number | null;
	checked: boolean | null;
}

interface PipelineState {
	path: string;
	route: ListRoute;
	entries: ListEntry[];
	selected?: ListEntry;
	items?: ListItem[];
	hash?: string;
	successfulMutation: boolean;
	requiredTool: string;
	forcedRequests: Array<{ tool: string; present: boolean }>;
}

export const MINICPM_LIST_TOOL_NAMES = [
	"list_select",
	"list_append_item",
	"list_insert_after",
	"list_insert_between",
] as const;

export function forceToolChoice(
	payload: unknown,
	expected: string,
): { payload: unknown; present: boolean } {
	const choice = { type: "function", function: { name: expected } };
	if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
		return { payload: { tools: [], tool_choice: choice }, present: false };
	}
	const source = payload as Record<string, unknown>;
	const tools = Array.isArray(source.tools) ? source.tools : [];
	const present = tools.some((raw) => {
		if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
		const fn = (raw as Record<string, unknown>).function;
		return Boolean(fn && typeof fn === "object" && !Array.isArray(fn) &&
			(fn as Record<string, unknown>).name === expected);
	});
	return {
		payload: present
			? { ...source, tool_choice: choice }
			: { ...source, tools: [], tool_choice: choice },
		present,
	};
}

export function extractMarkdownPath(prompt: string): string | undefined {
	const found = new Set<string>();
	const patterns = [
		/`([^`\n]+\.md)`/gi,
		/(?:^|\s)@([^\s`"'<>]+\.md)(?=$|[\s,.;:!?])/gi,
		/(?:^|[\s("'])((?:\.{0,2}\/)?[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*\.md)(?=$|[\s)"',.;:!?])/gi,
	];
	for (const pattern of patterns) {
		for (const match of prompt.matchAll(pattern)) {
			const value = match[1]?.trim();
			if (value) found.add(stripPiPathPrefix(value));
		}
	}
	return found.size === 1 ? [...found][0] : undefined;
}

export function routeListRequest(prompt: string): ListRoute {
	const normalized = ` ${prompt.toLowerCase().replace(/\s+/g, " ")} `;
	if (normalized.includes(" insert ") && normalized.includes(" between ")) return "between";
	if (normalized.includes(" immediately after ")) return "after";
	return "append";
}

export function parseListSummary(text: string): ListEntry[] {
	const entries: ListEntry[] = [];
	const pattern = /^  heading "(.*)"  ordinal ([0-9]+)$/gm;
	for (const match of text.matchAll(pattern)) {
		entries.push({ heading: match[1], ordinal: Number(match[2]) });
	}
	return entries;
}

export function selectEntry(
	entries: ListEntry[],
	args: ToolArguments,
): ListEntry {
	const heading = args.heading;
	const ordinal = args.ordinal;
	if (typeof heading !== "string" || typeof ordinal !== "number" ||
		!Number.isSafeInteger(ordinal) || ordinal < 0) {
		throw new Error("list_select requires an exact heading and non-negative integer ordinal.");
	}
	const matches = entries.filter((entry) => entry.heading === heading && entry.ordinal === ordinal);
	if (matches.length !== 1) {
		throw new Error("The selected heading and ordinal do not identify one current list.");
	}
	return matches[0];
}

export function selectionSchema(entries: ListEntry[]): ToolSchema {
	const headings = [...new Set(entries.map((entry) => entry.heading))];
	const ordinals = [...new Set(entries.map((entry) => entry.ordinal))].sort((a, b) => a - b);
	return {
		name: "list_select",
		description: "Choose the one existing list matching every constraint in the request. Copy its exact full heading and ordinal from the summary.",
		parameters: {
			type: "object",
			properties: {
				heading: {
					type: "string",
					enum: headings,
					description: "Exact full heading path of the target list.",
				},
				ordinal: {
					type: "integer",
					enum: ordinals,
					description: "Exact ordinal of the target list under that heading.",
				},
			},
			required: ["heading", "ordinal"],
		},
	};
}

function exactItemTexts(items: ListItem[]): string[] {
	return [...new Set(items.map((item) => item.text))];
}

export function contentSchema(route: ListRoute, items: ListItem[]): ToolSchema {
	if (route === "append") {
		return {
			name: "list_append_item",
			description: "Supply the text of the one new item to append. The host already knows the exact file and list.",
			parameters: {
				type: "object",
				properties: { text: { type: "string", description: "New item text." } },
				required: ["text"],
			},
		};
	}
	const itemTexts = exactItemTexts(items);
	if (route === "after") {
		return {
			name: "list_insert_after",
			description: "Supply the new item text and choose the exact existing item after which it belongs. The host already knows the file and list.",
			parameters: {
				type: "object",
				properties: {
					text: { type: "string", description: "Text of the new list item." },
					after: {
						type: "string",
						enum: itemTexts,
						description: "Existing item after which the new item belongs. Copy one exact item text from this enum, not its index.",
					},
				},
				required: ["text", "after"],
			},
		};
	}
	const boundary = { type: "string", enum: itemTexts };
	return {
		name: "list_insert_between",
		description: "Supply the new item and both existing boundary items named by the request. Copy the boundaries in request order. The host already knows the file and list.",
		parameters: {
			type: "object",
			properties: {
				text: { type: "string", description: "Text of the new list item." },
				after: {
					...boundary,
					description: "First named boundary: the existing item the new item follows.",
				},
				before: {
					...boundary,
					description: "Second named boundary: the existing item the new item precedes.",
				},
			},
			required: ["text", "after", "before"],
		},
	};
}

function oneItemIndex(items: ListItem[], text: unknown, field: string): number {
	if (typeof text !== "string") throw new Error(`${field} must be exact returned item text.`);
	const hits = items.flatMap((item, index) => item.text === text ? [index] : []);
	if (hits.length !== 1) throw new Error(`${field} must identify one exact current item.`);
	return hits[0];
}

export function composeListAdd(
	path: string,
	entry: ListEntry,
	route: ListRoute,
	items: ListItem[],
	args: ToolArguments,
): ToolArguments {
	if (typeof args.text !== "string") throw new Error("text must be a string.");
	const composed: ToolArguments = {
		path,
		list: { heading: entry.heading, ordinal: entry.ordinal },
		text: args.text,
	};
	if (route === "append") {
		composed.position = "end";
		return composed;
	}
	const afterIndex = oneItemIndex(items, args.after, "after");
	composed.after = args.after;
	if (route === "after") return composed;

	const beforeIndex = oneItemIndex(items, args.before, "before");
	if (beforeIndex !== afterIndex + 1) {
		throw new Error("The selected boundaries are not adjacent and ordered.");
	}
	if (items[afterIndex].depth !== items[beforeIndex].depth ||
		items[afterIndex].parent !== items[beforeIndex].parent) {
		throw new Error("The selected boundaries are not structural siblings.");
	}
	return composed;
}

function listItems(payload: IncisePayload, selected: ListEntry): ListItem[] {
	const list = payload.list;
	if (!list || typeof list !== "object" || Array.isArray(list)) {
		throw new Error("incise items did not return a structured list.");
	}
	const value = list as Record<string, unknown>;
	if (value.heading !== selected.heading || value.ordinal !== selected.ordinal ||
		!Array.isArray(value.items)) {
		throw new Error("incise items returned a different list than the validated selection.");
	}
	const items: ListItem[] = [];
	for (const raw of value.items) {
		if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
			throw new Error("incise items returned a malformed item.");
		}
		const item = raw as Record<string, unknown>;
		if (typeof item.text !== "string" || typeof item.depth !== "number" ||
			!Number.isSafeInteger(item.depth) ||
			!(item.parent === null || (typeof item.parent === "number" && Number.isSafeInteger(item.parent))) ||
			!(item.checked === null || typeof item.checked === "boolean")) {
			throw new Error("incise items returned a malformed item.");
		}
		items.push(item as unknown as ListItem);
	}
	return items;
}

function toolResult(text: string, details: Record<string, unknown>) {
	return { content: [{ type: "text" as const, text }], details };
}

export function installMiniCpmListProfile(
	pi: ExtensionAPI,
	binary: ResolvedBinary,
): void {
	let state: PipelineState | undefined;

	const registerContentTool = (schema: ToolSchema): void => {
		pi.registerTool({
			name: schema.name,
			label: schema.name,
			description: schema.description,
			parameters: schema.parameters as TSchema,
			async execute(_toolCallId, params, signal) {
				if (!state?.selected || !state.items || !state.hash) {
					throw new Error("No validated list selection is active.");
				}
				if (state.successfulMutation) {
					throw new Error("This turn already completed one successful list mutation.");
				}
				const args = composeListAdd(
					state.path, state.selected, state.route, state.items,
					params as ToolArguments,
				);
				const call = async () => runIncise(
					pi.exec.bind(pi),
					binary.path,
					["list-add-item", state!.path, "--args", JSON.stringify(args), "--if-match", state!.hash!],
					signal,
				);
				const result = await withFileMutationQueue(state.path, call);
				if (result.code !== 0 || result.payload.ok === false) throw processError(result);
				state.successfulMutation = true;
				state.requiredTool = "";
				pi.setActiveTools([]);
				return toolResult(String(result.payload.description ?? ""), {
					exitCode: result.code,
					hash: result.payload.hash,
					path: result.payload.path ?? state.path,
					changed: Boolean(result.payload.changed),
					route: state.route,
					validated: true,
					forcedProviderRequests: [...state.forcedRequests],
				});
			},
		});
	};

	const registerSelectionTool = (schema: ToolSchema): void => {
		pi.registerTool({
			name: schema.name,
			label: schema.name,
			description: schema.description,
			parameters: schema.parameters as TSchema,
			async execute(_toolCallId, params, signal) {
				if (!state) throw new Error("No MiniCPM list request is active.");
				const selected = selectEntry(state.entries, params as ToolArguments);
				const readArgs = {
					path: state.path,
					list: { heading: selected.heading, ordinal: selected.ordinal },
				};
				const result = await runIncise(
					pi.exec.bind(pi),
					binary.path,
					["items", state.path, "--args", JSON.stringify(readArgs)],
					signal,
				);
				if (result.code !== 0 || result.payload.ok === false) throw processError(result);
				const items = listItems(result.payload, selected);
				if (typeof result.payload.hash !== "string" || !result.payload.hash) {
					throw new Error("incise items did not return a content hash.");
				}
				state.selected = selected;
				state.items = items;
				state.hash = result.payload.hash;
				const next = contentSchema(state.route, items);
				state.requiredTool = next.name;
				registerContentTool(next);
				pi.setActiveTools([next.name]);
				return toolResult(String(result.payload.text ?? ""), {
					hash: result.payload.hash,
					path: state.path,
					list: result.payload.list,
					route: state.route,
					validated: true,
					forcedProviderRequests: [...state.forcedRequests],
				});
			},
		});
	};

	pi.on("before_agent_start", async (event, ctx) => {
		state = undefined;
		const found = extractMarkdownPath(event.prompt);
		if (!found) {
			pi.setActiveTools([]);
			return {
				systemPrompt: `${event.systemPrompt}\n\nThe MiniCPM list profile requires exactly one explicit Markdown file path in the user request. Do not edit a file.`,
			};
		}
		const path = resolve(ctx.cwd, found);
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["lists", path]);
		if (result.code !== 0 || result.payload.ok === false) {
			pi.setActiveTools([]);
			throw processError(result);
		}
		const text = String(result.payload.text ?? "");
		const entries = parseListSummary(text);
		if (entries.length === 0) {
			pi.setActiveTools([]);
			throw new Error("incise found no existing Markdown list to select.");
		}
		state = {
			path,
			route: routeListRequest(event.prompt),
			entries,
			successfulMutation: false,
			requiredTool: "list_select",
			forcedRequests: [],
		};
		const schema = selectionSchema(entries);
		registerSelectionTool(schema);
		pi.setActiveTools([schema.name]);
		return {
			systemPrompt: `${event.systemPrompt}\n\n${text}\n\nUse list_select once. Copy the exact full heading and ordinal for the requested list.`,
		};
	});

	pi.on("before_provider_request", (event) => {
		if (!state?.requiredTool) return undefined;
		const forced = forceToolChoice(event.payload, state.requiredTool);
		state.forcedRequests.push({ tool: state.requiredTool, present: forced.present });
		return forced.payload;
	});
}
