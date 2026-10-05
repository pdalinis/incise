import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";

import type { ResolvedBinary } from "./binary.ts";
import { resolveToolPath, type ToolArguments } from "./normalize.ts";
import { processError, runIncise, type IncisePayload } from "./runner.ts";

export const CHECK_TOOL_NAME = "md_check";

export const CHECK_TOOL_SCHEMA = {
	name: CHECK_TOOL_NAME,
	description: "Check one Markdown file for Incise structural hazards. Read-only. Returns the exact versioned JSON report. Available only while the explicit incise-check skill is active.",
	parameters: {
		type: "object",
		properties: {
			path: { type: "string", description: "Markdown file to check." },
		},
		required: ["path"],
		additionalProperties: false,
	},
} as const;

const SKILL_WRAPPER = /^<skill name="incise-check" location="[^"]+">\n/;

export function isExplicitCheckSkillPrompt(prompt: string): boolean {
	return SKILL_WRAPPER.test(prompt);
}

export function repairTools(report: IncisePayload, available: ReadonlySet<string>): string[] {
	const mapped = new Set<string>();
	const findings = Array.isArray(report.findings) ? report.findings : [];
	for (const finding of findings) {
		if (!finding || typeof finding !== "object" || Array.isArray(finding)) continue;
		const repair = (finding as Record<string, unknown>).repair;
		if (!repair || typeof repair !== "object" || Array.isArray(repair)) continue;
		const operation = (repair as Record<string, unknown>).operation;
		if (typeof operation !== "string") continue;
		const name = operation.startsWith("table-") ? "table_edit"
			: operation.startsWith("list-") ? "list_edit"
			: operation.startsWith("section-") ? "section_edit"
			: operation.startsWith("frontmatter-") ? "frontmatter_edit"
			: undefined;
		if (name && available.has(name)) mapped.add(name);
	}
	return [...mapped];
}

export function installCheckSkillTool(
	pi: ExtensionAPI,
	binary: ResolvedBinary,
	standardTools: readonly string[],
): void {
	const available = new Set(standardTools);
	let active = false;
	let restore: string[] | undefined;

	pi.registerTool({
		name: CHECK_TOOL_SCHEMA.name,
		label: CHECK_TOOL_SCHEMA.name,
		description: CHECK_TOOL_SCHEMA.description,
		parameters: CHECK_TOOL_SCHEMA.parameters as TSchema,
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			if (!active) throw new Error("md_check is available only while the explicit incise-check skill is active.");
			const located = resolveToolPath(params as ToolArguments, ctx.cwd);
			const result = await runIncise(pi.exec.bind(pi), binary.path, ["check", located.path], signal);
			if (result.code !== 0 || result.payload.ok === false) throw processError(result);
			pi.setActiveTools([CHECK_TOOL_NAME, ...repairTools(result.payload, available)]);
			return {
				content: [{ type: "text", text: JSON.stringify(result.payload) }],
				details: result.payload,
			};
		},
	});

	// Registration activates tools in Pi. Keep md_check out of every ordinary
	// provider request; explicit skill expansion below is the only activation.
	pi.setActiveTools(pi.getActiveTools().filter((name) => name !== CHECK_TOOL_NAME));

	pi.on("before_agent_start", async (event) => {
		if (!isExplicitCheckSkillPrompt(event.prompt)) return;
		restore = pi.getActiveTools().filter((name) => name !== CHECK_TOOL_NAME);
		active = true;
		pi.setActiveTools([CHECK_TOOL_NAME]);
	});

	pi.on("agent_end", async () => {
		if (!active) return;
		active = false;
		pi.setActiveTools(restore ?? standardTools.slice());
		restore = undefined;
	});
}
