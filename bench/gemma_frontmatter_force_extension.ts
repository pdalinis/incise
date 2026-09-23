import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import gemmaBenchExtension from "./gemma_bench_extension.ts";

function expectedTool(): string {
	const raw = process.env.INCISE_GEMMA_BENCH_CONFIG;
	if (!raw) throw new Error("INCISE_GEMMA_BENCH_CONFIG is required");
	const config = JSON.parse(raw) as { kind?: string; valueType?: string };
	if (config.kind !== "frontmatter_typed") {
		throw new Error("forced frontmatter extension requires frontmatter_typed");
	}
	if (config.valueType === "null") return "frontmatter_clear";
	if (!["string", "integer", "boolean"].includes(config.valueType ?? "")) {
		throw new Error("forced frontmatter extension requires a supported valueType");
	}
	return `frontmatter_set_${config.valueType}`;
}

export default async function gemmaFrontmatterForceExtension(pi: ExtensionAPI): Promise<void> {
	await gemmaBenchExtension(pi);
	const expected = expectedTool();
	pi.on("before_provider_request", (event) => {
		if (!event.payload || typeof event.payload !== "object" || Array.isArray(event.payload)) {
			return undefined;
		}
		const payload = event.payload as Record<string, unknown>;
		const tools = Array.isArray(payload.tools) ? payload.tools : [];
		const present = tools.some((raw) => {
			if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
			const fn = (raw as Record<string, unknown>).function;
			return Boolean(fn && typeof fn === "object" && !Array.isArray(fn) &&
				(fn as Record<string, unknown>).name === expected);
		});
		if (!present) return undefined;
		return {
			...payload,
			tool_choice: { type: "function", function: { name: expected } },
		};
	});
}
