import { withFileMutationQueue, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { resolve } from "node:path";
import type { TSchema } from "typebox";

import { resolveBinary } from "../plugins/pi/extension/binary.ts";
import { processError, runIncise } from "../plugins/pi/extension/runner.ts";

interface BenchConfig {
	kind: "section_insert_tree" | "section_rename_target" | "section_replace_target" |
		"frontmatter_typed" | "table_query";
	path: string;
	target?: string;
	anchors?: string[];
	valueType?: "string" | "integer" | "boolean" | "null";
	keys?: string[];
	table?: { heading: string; ordinal?: number };
	filterColumns?: string[];
}

interface ToolSpec {
	name: string;
	description: string;
	parameters: Record<string, unknown>;
	operation: string;
	write: boolean;
	arguments(params: Record<string, unknown>): Record<string, unknown>;
}

const CHILD = {
	type: "object",
	properties: {
		heading: { type: "string" },
		body: { type: "string" },
	},
	required: ["heading", "body"],
	additionalProperties: false,
};

function requiredStrings(value: unknown, name: string): string[] {
	if (!Array.isArray(value) || value.length === 0 ||
		!value.every((item) => typeof item === "string" && item.length > 0)) {
		throw new Error(`${name} must be a non-empty string array`);
	}
	return value;
}

function toolFor(config: BenchConfig): ToolSpec {
	if (config.kind === "section_insert_tree") {
		const anchors = requiredStrings(config.anchors, "anchors");
		return {
			name: "section_insert_tree",
			description: "Insert one section and all explicitly requested subsections atomically. Use children for subsections; body is prose only.",
			parameters: {
				type: "object",
				properties: {
					parent: { type: "string", enum: anchors },
					position: { type: "string", enum: ["before", "after", "first-child", "last-child"] },
					heading: { type: "string" },
					body: { type: "string" },
					children: { type: "array", items: CHILD },
				},
				required: ["parent", "position", "heading"],
				additionalProperties: false,
			},
			operation: "section-insert",
			write: true,
			arguments: (params) => ({
				section: params.parent,
				position: params.position,
				heading: params.heading,
				...(params.body === undefined ? {} : { body: params.body }),
				...(params.children === undefined ? {} : { children: params.children }),
			}),
		};
	}
	if (config.kind === "section_rename_target") {
		if (!config.target) throw new Error("section rename needs a target");
		return {
			name: "section_rename_target",
			description: `Rename the already resolved section ${JSON.stringify(config.target)}. Supply only its new heading text.`,
			parameters: {
				type: "object",
				properties: { new_heading: { type: "string" } },
				required: ["new_heading"],
				additionalProperties: false,
			},
			operation: "section-rename",
			write: true,
			arguments: (params) => ({ section: config.target, heading: params.new_heading }),
		};
	}
	if (config.kind === "section_replace_target") {
		if (!config.target) throw new Error("section replacement needs a target");
		return {
			name: "section_replace_target",
			description: `Replace only the body of the already resolved section ${JSON.stringify(config.target)}. Subsections remain unchanged.`,
			parameters: {
				type: "object",
				properties: { body: { type: "string" } },
				required: ["body"],
				additionalProperties: false,
			},
			operation: "section-replace-body",
			write: true,
			arguments: (params) => ({ section: config.target, text: params.body, overwrite: true }),
		};
	}
	if (config.kind === "frontmatter_typed") {
		const keys = requiredStrings(config.keys, "keys");
		const valueType = config.valueType;
		if (!valueType || !["string", "integer", "boolean", "null"].includes(valueType)) {
			throw new Error("frontmatter tool needs a supported valueType");
		}
		const clear = valueType === "null";
		const properties: Record<string, unknown> = { key: { type: "string", enum: keys } };
		if (!clear) properties.value = { type: valueType };
		return {
			name: clear ? "frontmatter_clear" : `frontmatter_set_${valueType}`,
			description: clear
				? "Blank one existing scalar frontmatter key while retaining the key. Copy its exact path from the flattened values."
				: `Set one existing scalar frontmatter key to a ${valueType}. Copy its exact path from the flattened values.`,
			parameters: {
				type: "object",
				properties,
				required: clear ? ["key"] : ["key", "value"],
				additionalProperties: false,
			},
			operation: "frontmatter-set",
			write: true,
			arguments: (params) => ({
				key: params.key,
				value: clear ? null : params.value,
				must_exist: true,
			}),
		};
	}
	if (!config.table) throw new Error("table query needs a table address");
	const filterColumns = requiredStrings(config.filterColumns, "filterColumns");
	return {
		name: "table_query",
		description: `Query the already resolved ${JSON.stringify(config.table.heading)} table once. Supply every required filter exactly as stated in the request.`,
		parameters: {
			type: "object",
			properties: Object.fromEntries(filterColumns.map((column) => [column, { type: "string" }])),
			required: filterColumns,
			additionalProperties: false,
		},
		operation: "rows",
		write: false,
		arguments: (params) => ({ table: config.table, filter: params }),
	};
}

function configFromEnvironment(): BenchConfig {
	const raw = process.env.INCISE_GEMMA_BENCH_CONFIG;
	if (!raw) throw new Error("INCISE_GEMMA_BENCH_CONFIG is required");
	const parsed = JSON.parse(raw) as BenchConfig;
	if (!parsed || typeof parsed !== "object" || typeof parsed.kind !== "string" ||
		typeof parsed.path !== "string" || !parsed.path) {
		throw new Error("invalid INCISE_GEMMA_BENCH_CONFIG");
	}
	return parsed;
}

export default async function gemmaBenchExtension(pi: ExtensionAPI): Promise<void> {
	const binary = resolveBinary();
	if (!binary) throw new Error("Incise binary not found");
	const config = configFromEnvironment();
	const spec = toolFor(config);
	let completed = false;

	pi.registerTool({
		name: spec.name,
		label: spec.name,
		description: spec.description,
		parameters: spec.parameters as TSchema,
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			if (completed) throw new Error("The requested operation already succeeded; do not call another tool.");
			const path = resolve(ctx.cwd, config.path);
			const args = { ...spec.arguments(params as Record<string, unknown>), path };
			const invoke = () => runIncise(
				pi.exec.bind(pi), binary.path,
				[spec.operation, path, "--args", JSON.stringify(args)], signal,
			);
			const result = spec.write ? await withFileMutationQueue(path, invoke) : await invoke();
			if (result.code !== 0 || result.payload.ok === false) throw processError(result);
			completed = true;
			const text = spec.write ? String(result.payload.description ?? "") : String(result.payload.text ?? "");
			return {
				content: [{ type: "text" as const, text }],
				details: {
					exitCode: result.code,
					hash: result.payload.hash,
					path: result.payload.path ?? path,
					changed: Boolean(result.payload.changed),
					rows: result.payload.rows,
					benchArguments: args,
				},
			};
		},
	});
}

