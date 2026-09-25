import { readFile, writeFile } from "node:fs/promises";
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
import { processError, runIncise, type InciseResult } from "./runner.ts";
import type { ToolSchema } from "./schemas.ts";

export type SafeRouteKind = "section-rename" | "section-replace-body" | "section-insert" |
	"section-append" | "section-set-level-target" |
	"frontmatter-typed" | "frontmatter-create" | "frontmatter-delete" |
	"frontmatter-release" | "list-remove-target" |
	"list-append-target" | "list-set-checked-target" |
	"table-add-row-target" | "table-query";

export interface OutlineEntry {
	path: string;
	heading: string;
}

export interface TableEntry {
	heading: string;
	ordinal: number;
	columns: string[];
}

export type FrontmatterValueType = "string" | "integer" | "boolean" | "null";

interface FrontmatterEntry {
	path: string;
	kind: string;
	type: string;
	value: string;
}

export interface SectionInsertIntent {
	target: string;
	position: "before" | "last-child";
	heading: string;
	body?: string;
	children?: Array<{ heading: string; body: string }>;
}

export interface SectionAppendIntent {
	target: string | { path: string; ordinal: number };
	text: string;
}

export interface SectionSetLevelIntent {
	target: string;
	level: number;
}

export interface ListRemoveIntent {
	heading: string;
	item: string;
}

export interface ListContainsAppendIntent {
	heading: string;
	text: string;
	existingItem: string;
}

export interface ListAppendIntent {
	heading: string;
	text: string;
	after?: string;
	before?: string;
	containedItem?: string;
	loose?: boolean;
}

export interface ListCheckedIntent {
	heading: string;
	item: string;
	checked: boolean;
}

export interface TableAddRowIntent {
	heading: string;
	values: string[] | Record<string, string>;
}

export interface FrontmatterTypedIntent {
	valueType: FrontmatterValueType;
	value: string | number | boolean | null;
	key?: string;
	currentValue?: string;
	author?: string;
}

export interface FrontmatterCreateIntent {
	parent?: string;
	key: string;
	value: string | boolean;
	allowedStates?: string[];
}

export interface FrontmatterDeleteIntent {
	key: string;
}

export interface FrontmatterReleaseIntent {
	version: string;
	released: string;
}

interface RouteSpec {
	kind: SafeRouteKind;
	path: string;
	hash?: string;
	schema: ToolSchema;
	operation: string;
	write: boolean;
	arguments(params: Record<string, unknown>): Record<string, unknown>;
	followups?(params: Record<string, unknown>): Array<{
		operation: string;
		arguments: Record<string, unknown>;
	}>;
	resolvedArguments?(params: Record<string, unknown>): Record<string, unknown>;
	systemPrompt: string;
}

interface RoutedState {
	spec: RouteSpec;
	completed: boolean;
}

export function sectionIntent(prompt: string): { kind: "section-rename"; target: string; heading: string } |
	{ kind: "section-replace-body"; target: string; body?: string; directChild?: string } | undefined {
	if (/\b(?:do\s+not|don't|must\s+not)\s+replace\b/i.test(prompt)) return undefined;
	const rename = prompt.match(
		/\brename(?:\s+the)?\s*(?:"([^"]+)"|“([^”]+)”|`([^`]+)`)\s*(?:heading\s+)?to\s*(?:"([^"]+)"|“([^”]+)”|`([^`]+)`)/i,
	);
	if (rename) {
		const target = rename.slice(1, 4).find((value) => value !== undefined)?.trim();
		const heading = rename.slice(4, 7).find((value) => value !== undefined)?.trim();
		if (target && heading) return { kind: "section-rename", target, heading };
	}
	const qualifiedPreamble = prompt.match(
		/\breplace\s+the\s+introductory\s+paragraph\s+under\s+(.+?)\s+(?:--|—)\s+the\s+one\s+before\s+the\s+(.+?)\s+subsection\s+(?:--|—)\s+with\s+(?:"([^"]+)"|“([^”]+)”|`([^`]+)`)/i,
	);
	if (qualifiedPreamble) {
		const target = qualifiedPreamble[1].trim();
		const directChild = qualifiedPreamble[2].trim();
		const body = qualifiedPreamble.slice(3, 6).find((value) => value !== undefined)?.trim();
		if (target && directChild && body && target.length <= 240 && directChild.length <= 240) {
			return { kind: "section-replace-body", target, body, directChild };
		}
	}

	const replacement = prompt.match(
		/\breplace\s+(?:the\s+)?(?:text|body|content)\s+under\s+([^\n]+?)\s+with\s+(?:"([^"]+)"|“([^”]+)”|`([^`]+)`)/i,
	);
	if (replacement) {
		const target = replacement[1].trim();
		const body = replacement.slice(2, 5)
			.find((value) => value !== undefined)?.trim();
		if (target && body && target.length <= 240 && body.length <= 4_000) {
			return { kind: "section-replace-body", target, body };
		}
	}
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
	const request = framed ? prompt.slice(framed[0].length) : prompt;
	return request.replace(/^in\s+@?[^,\n]+,\s*/i, "");
}

export function sectionAppendIntent(
	prompt: string,
	entries: OutlineEntry[],
): SectionAppendIntent | undefined {
	const request = sectionInsertionRequest(prompt).trim();
	const saying = request.match(
		/^add\s+a\s+sentence\s+to\s+the\s+(?:"([^"]+)"|“([^”]+)”)\s+section\s+saying\s+(?:"([^"]+)"|“([^”]+)”)\s*\.?$/i,
	);
	const sentence = request.match(
		/^add\s+the\s+sentence\s+(?:"([^"]+)"|“([^”]+)”)\s+to\s+the\s+(?:"([^"]+)"|“([^”]+)”)\s+section\s*\.?$/i,
	);
	const under = request.match(
		/^add\s+(?:"([^"]+)"|“([^”]+)”)\s+to\s+the\s+([^\n]+?)\s+section\s+under\s+([^\n.]+)\s*\.?$/i,
	);
	const ordinal = request.match(
		/^add\s+the\s+line\s+(?:"([^"]+)"|“([^”]+)”)\s+to\s+the\s+(first|second|third)\s+of\s+the\s+(two|three)\s+([^\n]+?)\s+sections\s*\.?$/i,
	);
	if (ordinal) {
		const indexes: Record<string, number> = { first: 0, second: 1, third: 2 };
		const counts: Record<string, number> = { two: 2, three: 3 };
		const text = ordinal[1] ?? ordinal[2];
		const requested = ordinal[5].trim();
		const matches = entries.filter((entry) => entry.heading === requested);
		const index = indexes[ordinal[3].toLowerCase()];
		if (!text || matches.length !== counts[ordinal[4].toLowerCase()] || index >= matches.length) {
			return undefined;
		}
		return { target: { path: requested, ordinal: index }, text };
	}
	const requested = saying ? (saying[1] ?? saying[2])
		: sentence ? (sentence[3] ?? sentence[4])
			: under ? `${under[4].trim()} > ${under[3].trim()}` : undefined;
	const text = saying ? (saying[3] ?? saying[4])
		: sentence ? (sentence[1] ?? sentence[2])
			: under ? (under[1] ?? under[2]) : undefined;
	if (!requested || !text || requested !== requested.trim() || text !== text.trim()) {
		return undefined;
	}
	const target = resolveOutlineTarget(entries, requested);
	return target ? { target, text } : undefined;
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

export function sectionSetLevelIntent(
	prompt: string,
	entries: OutlineEntry[],
): SectionSetLevelIntent | undefined {
	const request = sectionInsertionRequest(prompt).trim();
	const match = request.match(
		/^promote\s+the\s+([^\n]+?)\s+heading\s+under\s+([^\n]+?)\s+to\s+a\s+(first|second|third|fourth|fifth|sixth)-level\s+heading,\s*moving\s+its\s+subsections\s+with\s+it\.?$/i,
	);
	if (!match) return undefined;
	const child = match[1].trim();
	const parent = match[2].trim();
	const levels: Record<string, number> = {
		first: 1, second: 2, third: 3, fourth: 4, fifth: 5, sixth: 6,
	};
	const level = levels[match[3].toLowerCase()];
	const target = resolveOutlineTarget(entries, `${parent} > ${child}`);
	return target ? { target, level } : undefined;
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

export function tableAddRowIntent(prompt: string): TableAddRowIntent | undefined {
	if (/\b(?:do\s+not|don't|must\s+not)\s+(?:add|insert)\b/i.test(prompt)) {
		return undefined;
	}
	const named = prompt.match(
		/\badd\s+a\s+row\s+(?:to|at\s+the\s+end\s+of)\s+the\s+([^\n]+?)\s+table\s+for\s+a\s+component\s+named\s+["“]([^"”]+)["”]\s+with\s+status\s+["“]([^"”]+)["”]\s+and\s+owner\s+["“]([^"”]+)["”]\s*\.?(?:\s+put\s+it\s+at\s+the\s+end\s+of\s+the\s+table\s*\.?)?$/i,
	);
	if (named) {
		return {
			heading: named[1].trim(),
			values: {
				Component: named[2].trim(),
				Status: named[3].trim(),
				Owner: named[4].trim(),
			},
		};
	}
	const ordered = prompt.match(
		/\badd\s+a\s+row\s+with\s+the\s+values\s+([^\n]+?)\s+to\s+the\s+table\s+under\s+["“]([^"”]+)["”]\s*[.!]?$/i,
	);
	if (!ordered) return undefined;
	const values = ordered[1].split(/\s*,\s*|\s+and\s+/i)
		.map((value) => value.trim()).filter(Boolean);
	if (values.length < 2 || values.some((value) => !/^[^\s,"“”]+$/.test(value))) {
		return undefined;
	}
	return { heading: ordered[2].trim(), values };
}

function resolveTableEntry(entries: TableEntry[], requested: string): TableEntry | undefined {
	const parts = requested.split(">").map((part) => part.trim()).filter(Boolean);
	if (parts.length === 0) return undefined;
	const matches = entries.filter((entry) => {
		const candidate = entry.heading.split(" > ");
		return candidate.length >= parts.length && parts.every((part, index) =>
			candidate[candidate.length - parts.length + index].toLowerCase() === part.toLowerCase());
	});
	return matches.length === 1 ? matches[0] : undefined;
}

function tableAddRowValues(
	table: TableEntry,
	intent: TableAddRowIntent,
): string[] | Record<string, string> | undefined {
	if (Array.isArray(intent.values)) {
		return intent.values.length === table.columns.length ? [...intent.values] : undefined;
	}
	const entries = Object.entries(intent.values);
	if (entries.length !== table.columns.length) return undefined;
	const resolved: Record<string, string> = {};
	for (const [requested, value] of entries) {
		const columns = table.columns.filter(
			(column) => column.toLowerCase() === requested.toLowerCase(),
		);
		if (columns.length !== 1) return undefined;
		resolved[columns[0]] = value;
	}
	return Object.keys(resolved).length === table.columns.length ? resolved : undefined;
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

export function frontmatterTypedIntent(prompt: string): FrontmatterTypedIntent | undefined {
	const request = (prompt.trim().split(/\r?\n\r?\n/).at(-1) ?? "").trim()
		.replace(/^in\s+@?[^,\n]+,\s*/i, "");
	if (/\b(?:do\s+not|don't|must\s+not)\s+(?:set|switch|update|blank|mark)\b/i.test(request)) {
		return undefined;
	}
	const jobs = request.match(
		/^the\s+build\s+should\s+run\s+with\s+(\d+)\s+parallel\s+jobs\s+instead\s+of\s+(\d+)\s*[.!]?$/i,
	);
	if (jobs) {
		return {
			valueType: "integer", key: "build.jobs", value: Number(jobs[1]),
			currentValue: jobs[2],
		};
	}
	const target = request.match(
		/^switch\s+the\s+build\s+from\s+(?:a\s+)?([^\s]+)\s+build\s+to\s+(?:a\s+)?([^\s]+)\s+one\s*[.!]?$/i,
	);
	if (target) {
		return {
			valueType: "string", key: "build.target", value: target[2],
			currentValue: target[1],
		};
	}
	const author = request.match(
		/^([^\n.]+?)\s+has\s+taken\s+over\s+as\s+a\s+([^\n.]+?)\.\s*update\s+(?:her|his|their)\s+entry\s+in\s+the\s+authors\s+list\s+to\s+say\s+so\s*[.!]?$/i,
	);
	if (author) {
		return {
			valueType: "string", author: author[1].trim(), value: author[2].trim(),
		};
	}
	const clear = request.match(
		/^blank\s+out\s+the\s+([A-Za-z_][A-Za-z0-9_.-]*),\s*but\s+leave\s+the\s+key\s+itself\s+in\s+the\s+frontmatter\s*[.!]?$/i,
	);
	if (clear) return { valueType: "null", key: clear[1], value: null };
	if (/^this\s+file\s+has\s+gone\s+back\s+to\s+being\s+a\s+draft\.\s*say\s+so\s+in\s+the\s+frontmatter\s*[.!]?$/i.test(request)) {
		return {
			valueType: "boolean", key: "draft", value: true, currentValue: "false",
		};
	}
	return undefined;
}

export function frontmatterValueType(prompt: string): FrontmatterValueType | undefined {
	return frontmatterTypedIntent(prompt)?.valueType;
}

export function frontmatterCreateIntent(prompt: string): FrontmatterCreateIntent | undefined {
	const request = (prompt.trim().split(/\r?\n\r?\n/).at(-1) ?? "").trim()
		.replace(/^in\s+@?[^,\n]+,\s*/i, "");
	if (/^turn\s+on\s+caching\s+for\s+the\s+build[.!]?$/i.test(request)) {
		return { parent: "build", key: "build.cache", value: true };
	}
	const absent = request.match(
		/^give\s+this\s+file\s+a\s+frontmatter\s+block\s+with\s+a\s+title\s+of\s+["“]([^"”]+)["”]\s*[.!]?$/i,
	);
	if (absent) {
		return { key: "title", value: absent[1], allowedStates: ["absent"] };
	}
	if (/^mark\s+this\s+file\s+as\s+a\s+draft\s+by\s+adding\s+a\s+draft\s+flag\s+set\s+to\s+true[.!]?$/i.test(request)) {
		return { key: "draft", value: true, allowedStates: ["empty"] };
	}
	return undefined;
}

export function frontmatterDeleteIntent(prompt: string): FrontmatterDeleteIntent | undefined {
	const request = (prompt.trim().split(/\r?\n\r?\n/).at(-1) ?? "").trim()
		.replace(/^in\s+@?[^,\n]+,\s*/i, "");
	if (/^drop\s+the\s+whole\s+build\s+configuration\s+from\s+the\s+frontmatter[.!]?$/i.test(request)) {
		return { key: "build" };
	}
	if (/^this\s+file\s+is\s+no\s+longer\s+a\s+draft\.\s*take\s+the\s+draft\s+flag\s+out\s+of\s+the\s+frontmatter\s+completely[.!]?$/i.test(request)) {
		return { key: "draft" };
	}
	return undefined;
}

export function frontmatterReleaseIntent(prompt: string): FrontmatterReleaseIntent | undefined {
	const request = (prompt.trim().split(/\r?\n\r?\n/).at(-1) ?? "").trim()
		.replace(/^in\s+@?[^,\n]+,\s*/i, "");
	const match = request.match(
		/^update\s+the\s+version\s+to\s+([0-9]+\.[0-9]+\.[0-9]+),\s*and\s+set\s+`released`\s+to\s+(\d{4}-\d{2}-\d{2})[.!]?$/i,
	);
	return match ? { version: match[1], released: match[2] } : undefined;
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

export function listContainsAppendIntent(prompt: string): ListContainsAppendIntent | undefined {
	const match = prompt.match(
		/\bunder\s+["“]([^"”]+)["”]\s*,\s*add\s+an?\s+item\s+["“]([^"”]+)["”]\s+to\s+the\s+list\s+that\s+contains\s+the\s+([^\n]+?\bitem)\s*[.!]?\s*$/i,
	);
	if (!match) return undefined;
	const heading = match[1];
	const text = match[2];
	const existingItem = match[3];
	if ([heading, text, existingItem].some((value) => !value || value !== value.trim())) {
		return undefined;
	}
	return { heading, text, existingItem };
}

export function listAppendIntent(prompt: string): ListAppendIntent | undefined {
	if (/\b(?:do\s+not|don't|must\s+not)\s+(?:add|insert)\b/i.test(prompt)) {
		return undefined;
	}
	const contained = listContainsAppendIntent(prompt);
	if (contained) {
		return {
			heading: contained.heading,
			text: contained.text,
			containedItem: contained.existingItem,
		};
	}
	const after = prompt.match(
		/\bunder\s+["“]([^"”]+)["”]\s*,\s*add\s+["“]([^"”]+)["”]\s+immediately\s+after\s+["“]([^"”]+)["”]\s*[.!]?$/i,
	);
	if (after) {
		return { heading: after[1].trim(), text: after[2].trim(), after: after[3].trim() };
	}
	const between = prompt.match(
		/\bin\s+the\s+list\s+under\s+["“]([^"”]+)["”]\s*,\s*insert\s+an?\s+item\s+["“]([^"”]+)["”]\s+between\s+["“]([^"”]+)["”]\s+and\s+["“]([^"”]+)["”]\s*[.!]?$/i,
	);
	if (between) {
		return {
			heading: between[1].trim(), text: between[2].trim(),
			after: between[3].trim(), before: between[4].trim(),
		};
	}
	const end = prompt.match(
		/\badd\s+an?\s+item\s+["“]([^"”]+)["”]\s+at\s+the\s+end\s+of\s+the\s+list\s+under\s+["“]([^"”]+)["”](?:\s+whose\s+items\s+have\s+blank\s+lines\s+between\s+them)?\s*[.!]?$/i,
	);
	if (end) {
		return {
			heading: end[2].trim(), text: end[1].trim(),
			...(/\bwhose\s+items\s+have\s+blank\s+lines\s+between\s+them\b/i.test(end[0])
				? { loose: true } : {}),
		};
	}
	const leadingEnd = prompt.match(
		/\bat\s+the\s+end\s+of\s+the\s+list\s+under\s+["“]([^"”]+)["”]\s*,\s*add\s+an?\s+item\s+that\s+says\s+["“]([^"”]+)["”]\s*[.!]?$/i,
	);
	if (leadingEnd) {
		return { heading: leadingEnd[1].trim(), text: leadingEnd[2].trim() };
	}
	return undefined;
}

export function listCheckedIntent(prompt: string): ListCheckedIntent | undefined {
	const match = prompt.match(
		/\bmark\s+the\s+["“]([^"”]+)["”]\s+task\s+as\s+(done|pending),\s*in\s+the\s+list\s+under\s+["“]([^"”]+)["”]\s*[.!]?/i,
	);
	if (!match) return undefined;
	const item = match[1].trim();
	const heading = match[3].trim();
	if (!item || !heading) return undefined;
	return { heading, item, checked: match[2].toLowerCase() === "done" };
}

function matchingListEntries(entries: ListEntry[], requested: string): ListEntry[] {
	const parts = requested.split(">").map((part) => part.trim()).filter(Boolean);
	if (parts.length === 0) return [];
	return entries.filter((entry) => {
		const candidate = entry.heading.split(" > ");
		return candidate.length >= parts.length &&
			parts.every((part, index) => candidate[candidate.length - parts.length + index] === part);
	});
}

function resolveListEntry(entries: ListEntry[], requested: string): ListEntry | undefined {
	const matches = matchingListEntries(entries, requested);
	return matches.length === 1 ? matches[0] : undefined;
}

function looksLikeTableRead(prompt: string): boolean {
	if (/\b(?:add|append|insert|update|change|delete|remove|sort|realign)\b/i.test(prompt)) return false;
	return /\b(?:find|which|what|show|list|query|look up)\b/i.test(prompt);
}

function sectionSchema(
	kind: "section-rename" | "section-replace-body",
	target: string,
	hostOwnedBody = false,
): ToolSchema {
	if (kind === "section-rename") {
		return {
			name: "section_rename_target",
			description: `Rename the already resolved section ${JSON.stringify(target)} to the exact heading already parsed from the request. The host owns both values; supply no arguments.`,
			parameters: {
				type: "object",
				properties: {},
				additionalProperties: false,
			},
		};
	}
	if (hostOwnedBody) {
		return {
			name: "section_replace_target",
			description: `Replace only the body of the already resolved section ${JSON.stringify(target)} with the exact text parsed from the request. Its subsections remain unchanged; the host owns every argument.`,
			parameters: { type: "object", properties: {}, additionalProperties: false },
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

function sectionAppendSchema(intent: SectionAppendIntent): ToolSchema {
	return {
		name: "section_append_target",
		description: `Append the already resolved exact sentence to ${JSON.stringify(intent.target)}. The host owns the section and literal text; supply no arguments.`,
		parameters: {
			type: "object",
			properties: {},
			additionalProperties: false,
		},
	};
}

function sectionSetLevelSchema(intent: SectionSetLevelIntent): ToolSchema {
	return {
		name: "section_set_level_target",
		description: `Set the already resolved section ${JSON.stringify(intent.target)} to heading level ${intent.level}, moving its complete subtree with it. The host owns every argument; supply no arguments.`,
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

function tableAddRowSchema(table: TableEntry): ToolSchema {
	return {
		name: "table_add_row_target",
		description: `Add the exact requested row to the already resolved table ${JSON.stringify(table.heading)}. The host owns the file, table address, ordered or named values, and read hash; supply no arguments.`,
		parameters: {
			type: "object",
			properties: {},
			additionalProperties: false,
		},
	};
}

function frontmatterSchema(valueType: FrontmatterValueType, key: string): ToolSchema {
	const clear = valueType === "null";
	const name = clear ? "frontmatter_clear" : `frontmatter_set_${valueType}`;
	return {
		name,
		description: `Apply the already resolved ${clear ? "clear" : valueType} update to ${JSON.stringify(key)}. The host owns the exact key and typed value; supply no arguments.`,
		parameters: {
			type: "object",
			properties: {},
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
		if (typeof entry.value !== "string") return [];
		return [{ path: entry.path, kind: entry.kind, type: entry.type, value: entry.value }];
	});
}

export function resolveFrontmatterTypedIntent(
	intent: FrontmatterTypedIntent,
	payload: Record<string, unknown>,
): { key: string; value: string | number | boolean | null; must_exist: true } | undefined {
	const entries = frontmatterEntries(payload);
	let key = intent.key;
	if (intent.author) {
		const names = entries.filter((entry) =>
			entry.type === "string" && entry.path.endsWith(".name") && entry.value === intent.author);
		if (names.length !== 1) return undefined;
		key = `${names[0].path.slice(0, -".name".length)}.role`;
	}
	if (!key) return undefined;
	const expectedType = intent.valueType === "null" ? "string" : intent.valueType;
	const matches = entries.filter((entry) =>
		entry.path === key && !["map", "seq"].includes(entry.kind) && entry.type === expectedType);
	if (matches.length !== 1) return undefined;
	if (intent.currentValue !== undefined && matches[0].value !== intent.currentValue) {
		return undefined;
	}
	const rendered = intent.value === null ? "" : String(intent.value);
	if (matches[0].value === rendered) return undefined;
	return { key, value: intent.value, must_exist: true };
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
	const insertionRequest = sectionInsertionRequest(prompt);
	const mayInsert = /\b(?:section|subsection)\b/i.test(insertionRequest)
		? insertionAnchor(prompt)
		: undefined;
	const mayAppend = /\badd\b[^\n]*\b(?:section|sections)\b/i.test(insertionRequest);
	const maySetLevel = /\bpromote\s+the\s+[^\n]+?\s+heading\s+under\s+[^\n]+?\s+to\s+a\s+(?:first|second|third|fourth|fifth|sixth)-level\s+heading\b/i.test(
		insertionRequest,
	);
	if (section || mayInsert || mayAppend || maySetLevel) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["outline", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		const entries = parseOutline(String(result.payload.text ?? ""));
		if (typeof result.payload.hash !== "string") return undefined;
		if (section) {
			const target = resolveOutlineTarget(entries, section.target);
			if (!target) return undefined;
			if (section.kind === "section-replace-body" && section.directChild &&
				!entries.some((entry) => entry.path === `${target} > ${section.directChild}`)) {
				return undefined;
			}
			const hostOwnedBody = section.kind === "section-replace-body" && section.body !== undefined;
			const schema = sectionSchema(section.kind, target, hostOwnedBody);
			return {
				kind: section.kind,
				path,
				hash: result.payload.hash,
				schema,
				operation: section.kind === "section-rename" ? "section-rename" : "section-replace-body",
				write: true,
				arguments: section.kind === "section-rename"
					? () => ({ section: target, heading: section.heading })
					: hostOwnedBody
						? () => ({ section: target, text: section.body, overwrite: true })
						: (params) => ({ section: target, text: params.body, overwrite: true }),
				systemPrompt: section.kind === "section-rename"
					? `Incise resolved the requested section and exact replacement heading. Use ${schema.name} once with no arguments; the host supplies the file, target, and new heading.`
					: hostOwnedBody
						? `Incise resolved the requested section, verified its named direct child, and parsed the exact replacement body. Use ${schema.name} once with no arguments; the host supplies every argument.`
						: `Incise resolved the requested section to ${JSON.stringify(target)}. Use ${schema.name} once; the host supplies the file and target.`,
			};
		}
		const setLevel = sectionSetLevelIntent(prompt, entries);
		if (setLevel) {
			const schema = sectionSetLevelSchema(setLevel);
			return {
				kind: "section-set-level-target",
				path,
				hash: result.payload.hash,
				schema,
				operation: "section-set-level",
				write: true,
				arguments: () => ({
					section: setLevel.target,
					level: setLevel.level,
					subtree: true,
				}),
				systemPrompt: `Incise resolved the requested section level change and complete subtree. Use ${schema.name} once with no arguments; the host supplies the file, target, level, and subtree flag.`,
			};
		}
		const append = sectionAppendIntent(prompt, entries);
		if (append) {
			const schema = sectionAppendSchema(append);
			return {
				kind: "section-append",
				path,
				hash: result.payload.hash,
				schema,
				operation: "section-append",
				write: true,
				arguments: () => ({ section: append.target, text: append.text }),
				systemPrompt: `Incise resolved the requested section and exact quoted sentence, and activated section_append_target. Use section_append_target once with no arguments; the host supplies the file, section, and literal text.`,
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
	const frontmatter = frontmatterTypedIntent(prompt);
	if (frontmatter) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["keys", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const resolved = resolveFrontmatterTypedIntent(frontmatter, result.payload);
		if (!resolved) return undefined;
		const schema = frontmatterSchema(frontmatter.valueType, resolved.key);
		const instruction = `Incise inspected the frontmatter, resolved the exact key and typed value, and activated ${schema.name}. This custom tool is available even if the base tool summary says none. Call ${schema.name} exactly once with no arguments; the host supplies the complete guarded update.`;
		return {
			kind: "frontmatter-typed",
			path,
			hash: result.payload.hash,
			schema,
			operation: "frontmatter-set",
			write: true,
			arguments: () => resolved,
			systemPrompt: `${String(result.payload.text ?? "")}\n\n${instruction}`,
		};
	}
	const release = frontmatterReleaseIntent(prompt);
	if (release) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["keys", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const entries = frontmatterEntries(result.payload);
		if (entries.filter((entry) => entry.path === "version" && entry.type === "string").length !== 1 ||
			entries.some((entry) => entry.path === "released")) {
			return undefined;
		}
		const updates = [
			{ key: "version", value: release.version, must_exist: true },
			{ key: "released", value: release.released, must_absent: true },
		];
		const schema: ToolSchema = {
			name: "frontmatter_release_target",
			description: "Apply the already resolved version and release-date string updates as one guarded request. The host owns both keys and values; supply no arguments.",
			parameters: { type: "object", properties: {}, additionalProperties: false },
		};
		return {
			kind: "frontmatter-release",
			path,
			hash: result.payload.hash,
			schema,
			operation: "frontmatter-set",
			write: true,
			arguments: () => updates[0],
			followups: () => [{ operation: "frontmatter-set", arguments: updates[1] }],
			resolvedArguments: () => ({ updates }),
			systemPrompt: `Incise inspected both existing string keys and activated ${schema.name}. Use ${schema.name} exactly once with no arguments; the host applies both guarded string updates as one agent-facing request.`,
		};
	}
	const deletion = frontmatterDeleteIntent(prompt);
	if (deletion) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["keys", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const matches = frontmatterEntries(result.payload).filter((entry) => {
			if (entry.path !== deletion.key) return false;
			return deletion.key === "build"
				? entry.kind === "map"
				: deletion.key === "draft" && entry.kind !== "map" && entry.kind !== "seq" && entry.type === "boolean";
		});
		if (matches.length !== 1) return undefined;
		const schema: ToolSchema = {
			name: "frontmatter_delete_target",
			description: `Delete the already resolved frontmatter value ${JSON.stringify(deletion.key)} completely. The host owns the exact key; supply no arguments.`,
			parameters: { type: "object", properties: {}, additionalProperties: false },
		};
		return {
			kind: "frontmatter-delete",
			path,
			hash: result.payload.hash,
			schema,
			operation: "frontmatter-delete",
			write: true,
			arguments: () => ({ key: deletion.key }),
			systemPrompt: `Incise inspected the exact requested frontmatter value and activated ${schema.name}. Use ${schema.name} exactly once with no arguments; the host supplies the file, key, and read hash.`,
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
		if (!(create.allowedStates ?? ["present"]).includes(String(metadata.state))) return undefined;
		if (metadata.state !== "absent" && metadata.format !== "yaml") return undefined;
		const entries = frontmatterEntries(result.payload);
		if (create.parent &&
			entries.filter((entry) => entry.path === create.parent && entry.kind === "map").length !== 1) {
			return undefined;
		}
		if (entries.some((entry) => entry.path === create.key ||
			(create.key === "build.cache" && entry.path === "build.caching"))) {
			return undefined;
		}
		const schema: ToolSchema = {
			name: "frontmatter_create_target",
			description: `Create the already resolved absent frontmatter key ${JSON.stringify(create.key)}. The host owns the exact key and typed value; supply no arguments.`,
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
	const checked = listCheckedIntent(prompt);
	if (checked) {
		const summary = await runIncise(pi.exec.bind(pi), binary.path, ["lists", path]);
		if (summary.code !== 0 || summary.payload.ok === false) return undefined;
		const selected = resolveListEntry(
			parseListSummary(String(summary.payload.text ?? "")), checked.heading,
		);
		if (!selected) return undefined;
		const readArgs = { list: { heading: selected.heading, ordinal: selected.ordinal } };
		const result = await runIncise(
			pi.exec.bind(pi), binary.path,
			["items", path, "--args", JSON.stringify(readArgs)],
		);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const matches = listItems(result.payload, selected)
			.filter((item) => item.text === checked.item && item.checked !== null);
		if (matches.length !== 1 || matches[0].checked === checked.checked) return undefined;
		const schema: ToolSchema = {
			name: "list_set_checked_target",
			description: `Set the already resolved checkbox item ${JSON.stringify(checked.item)} in ${JSON.stringify(selected.heading)} to ${checked.checked ? "done" : "pending"}. The host owns every argument; supply no arguments.`,
			parameters: { type: "object", properties: {}, additionalProperties: false },
		};
		return {
			kind: "list-set-checked-target",
			path,
			hash: result.payload.hash,
			schema,
			operation: "list-set-checked",
			write: true,
			arguments: () => ({
				list: { heading: selected.heading, ordinal: selected.ordinal },
				match: checked.item,
				checked: checked.checked,
			}),
			systemPrompt: `Incise resolved the exact checkbox item and requested state. Use ${schema.name} once with no arguments; the host supplies the file, list, item, state, and read hash.`,
		};
	}
	const append = listAppendIntent(prompt);
	if (append) {
		const summary = await runIncise(pi.exec.bind(pi), binary.path, ["lists", path]);
		if (summary.code !== 0 || summary.payload.ok === false) return undefined;
		const entries = parseListSummary(String(summary.payload.text ?? ""));
		const candidates = append.containedItem || append.loose
			? matchingListEntries(entries, append.heading)
				.filter((entry) => !append.loose || entry.loose === true)
			: [resolveListEntry(entries, append.heading)].filter(
				(entry): entry is ListEntry => entry !== undefined,
			);
		if (candidates.length === 0) return undefined;
		const matches: Array<{ entry: ListEntry; hash: string }> = [];
		for (const entry of candidates) {
			const readArgs = { list: { heading: entry.heading, ordinal: entry.ordinal } };
			const result = await runIncise(
				pi.exec.bind(pi), binary.path,
				["items", path, "--args", JSON.stringify(readArgs)],
			);
			if (result.code !== 0 || result.payload.ok === false) return undefined;
			if (typeof result.payload.hash !== "string") return undefined;
			const items = listItems(result.payload, entry);
			const anchor = append.containedItem ?? append.after;
			const afterIndex = append.after === undefined
				? -1
				: items.findIndex((item) => item.text === append.after);
			const boundaryValid = append.before === undefined || (
				afterIndex >= 0 &&
				items.filter((item) => item.text === append.before).length === 1 &&
				items[afterIndex + 1]?.text === append.before &&
				items[afterIndex]?.depth === items[afterIndex + 1]?.depth
			);
			if ((!anchor || items.filter((item) => item.text === anchor).length === 1) && boundaryValid &&
				!items.some((item) => item.text === append.text)) {
				matches.push({ entry, hash: result.payload.hash });
			}
		}
		if (matches.length !== 1) return undefined;
		const selected = matches[0];
		const schema: ToolSchema = {
			name: "list_append_target",
			description: `Insert the exact requested item in the already resolved list ${JSON.stringify(selected.entry.heading)}. The host owns the file, list, position, and new text; supply no arguments.`,
			parameters: { type: "object", properties: {}, additionalProperties: false },
		};
		return {
			kind: "list-append-target",
			path,
			hash: selected.hash,
			schema,
			operation: "list-add-item",
			write: true,
			arguments: () => ({
				list: { heading: selected.entry.heading, ordinal: selected.entry.ordinal },
				text: append.text,
				...(append.after ? { after: append.after } : { position: "end" }),
			}),
			systemPrompt: `Incise inspected the lists and exact existing items, resolved the requested insertion, and activated list_append_target. Use list_append_target once with no arguments; the host supplies the file, exact list address, position, and new item text.`,
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
	const addRow = tableAddRowIntent(prompt);
	if (addRow) {
		const result = await runIncise(pi.exec.bind(pi), binary.path, ["tables", path]);
		if (result.code !== 0 || result.payload.ok === false) return undefined;
		if (typeof result.payload.hash !== "string") return undefined;
		const table = resolveTableEntry(
			parseTableSummary(String(result.payload.text ?? "")), addRow.heading,
		);
		if (!table) return undefined;
		const values = tableAddRowValues(table, addRow);
		if (!values) return undefined;
		const schema = tableAddRowSchema(table);
		return {
			kind: "table-add-row-target",
			path,
			hash: result.payload.hash,
			schema,
			operation: "table-add-row",
			write: true,
			arguments: () => ({
				table: { heading: table.heading, ordinal: table.ordinal },
				values,
			}),
			systemPrompt: `Incise inspected the tables, resolved the exact target and requested row, and activated ${schema.name}. Use ${schema.name} once with no arguments; the host supplies the file, table, values, and read hash.`,
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
		"section_append_target", "section_set_level_target",
		"frontmatter_clear", "frontmatter_set_string", "frontmatter_set_integer",
		"frontmatter_set_boolean", "frontmatter_create_target", "frontmatter_delete_target",
		"frontmatter_release_target", "list_remove_target",
		"list_append_target", "list_set_checked_target",
		"table_add_row_target", "table_query",
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
				const followups = spec.followups?.(params as Record<string, unknown>) ?? [];
				const operations = [{ operation: spec.operation, arguments: args }, ...followups];
				const invoke = async () => {
					const original = followups.length > 0 ? await readFile(spec.path) : undefined;
					let expectedHash = spec.hash;
					let result: InciseResult | undefined;
					for (let index = 0; index < operations.length; index += 1) {
						const operation = operations[index];
						const argv = [
							operation.operation, spec.path,
							"--args", JSON.stringify(operation.arguments),
						];
						if (expectedHash) argv.push("--if-match", expectedHash);
						result = await runIncise(pi.exec.bind(pi), binary.path, argv, signal);
						if (result.code !== 0 || result.payload.ok === false) {
							if (original && index > 0) await writeFile(spec.path, original);
							return result;
						}
						expectedHash = typeof result.payload.hash === "string"
							? result.payload.hash : undefined;
					}
					if (!result) throw new Error("Routed Incise request had no operations.");
					return result;
				};
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
						resolvedArguments: spec.resolvedArguments?.(
							params as Record<string, unknown>,
						) ?? args,
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
