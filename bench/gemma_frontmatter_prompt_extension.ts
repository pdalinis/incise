import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import gemmaBenchExtension from "./gemma_bench_extension.ts";

function expectedTool(): string {
	const raw = process.env.INCISE_GEMMA_BENCH_CONFIG;
	if (!raw) throw new Error("INCISE_GEMMA_BENCH_CONFIG is required");
	const config = JSON.parse(raw) as { kind?: string; valueType?: string };
	if (config.kind !== "frontmatter_typed") {
		throw new Error("frontmatter prompt extension requires frontmatter_typed");
	}
	if (config.valueType === "null") return "frontmatter_clear";
	if (!["string", "integer", "boolean"].includes(config.valueType ?? "")) {
		throw new Error("frontmatter prompt extension requires a supported valueType");
	}
	return `frontmatter_set_${config.valueType}`;
}

export function routeInstruction(tool: string): string {
	return `Incise inspected the frontmatter and activated ${tool}. This custom tool is available even if the base tool summary says none. Call ${tool} exactly once to perform the requested edit; do not describe or simulate the call.`;
}

export default async function gemmaFrontmatterPromptExtension(pi: ExtensionAPI): Promise<void> {
	await gemmaBenchExtension(pi);
	const instruction = routeInstruction(expectedTool());
	pi.on("before_agent_start", (event) => ({
		systemPrompt: `${event.systemPrompt}\n\n${instruction}`,
	}));
}
