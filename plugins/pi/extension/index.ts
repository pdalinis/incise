import { withFileMutationQueue, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { TSchema } from "typebox";

import { packageVersion, resolveBinary, type ResolvedBinary } from "./binary.ts";
import { installMiniCpmListProfile, MINICPM_LIST_TOOL_NAMES } from "./minicpm-list.ts";
import { prepareInvocation, READ_SUBCOMMAND, type ToolArguments } from "./normalize.ts";
import {
	requestedProfile,
	selectProfile,
	type ProfileDecision,
	type RequestedProfile,
} from "./profiles.ts";
import { binaryVersion, processError, runIncise } from "./runner.ts";
import { installSafeRoutedProfile, type SafeRouteKind } from "./safe-routed.ts";
import { loadMeasuredSchemas, PROMPT_METADATA, STRUCTURAL_READ_SCHEMAS, type ToolSchema } from "./schemas.ts";

interface Diagnostics {
	packageVersion: string;
	binary?: ResolvedBinary;
	binaryVersion?: string;
	schemas: ToolSchema[];
	error?: string;
	fatalMismatch: boolean;
	registeredTools?: string[];
	schemasAvailable?: boolean;
	requestedProfile?: RequestedProfile;
	profileDecision?: ProfileDecision;
	activeRoute?: SafeRouteKind | "standard";
}

function diagnosticText(diagnostics: Diagnostics): string {
	const schemasAvailable = diagnostics.schemasAvailable ?? diagnostics.schemas.length > 0;
	const registered = diagnostics.registeredTools && !diagnostics.fatalMismatch
		? diagnostics.registeredTools.join(", ")
		: diagnostics.schemas.length > 0 && !diagnostics.fatalMismatch
		? [...diagnostics.schemas, ...STRUCTURAL_READ_SCHEMAS].map((schema) => schema.name).join(", ")
		: "none";
	const lines = [
		`pi-incise ${diagnostics.packageVersion}`,
		`binary: ${diagnostics.binary?.path ?? "not found"}`,
		`binary source: ${diagnostics.binary?.source ?? "none"}`,
		`binary version: ${diagnostics.binaryVersion ?? "unknown"}`,
		`schemas: ${schemasAvailable ? "available" : "unavailable"}`,
		`registered tools: ${registered}`,
	];
	if (diagnostics.requestedProfile) {
		lines.push(`profile requested: ${diagnostics.requestedProfile}`);
		lines.push(`profile effective: ${diagnostics.profileDecision?.effective ?? "pending first model-bearing turn"}`);
	}
	if (diagnostics.profileDecision) {
		lines.push(`model: ${diagnostics.profileDecision.model}`);
		lines.push(`model family: ${diagnostics.profileDecision.family}`);
		lines.push(`profile reason: ${diagnostics.profileDecision.reason}`);
	}
	if (diagnostics.activeRoute) lines.push(`last route: ${diagnostics.activeRoute}`);
	if (diagnostics.binaryVersion && diagnostics.binaryVersion !== diagnostics.packageVersion) {
		lines.push(`warning: package ${diagnostics.packageVersion} is using incise ${diagnostics.binaryVersion}`);
	}
	if (diagnostics.error) lines.push(`error: ${diagnostics.error}`);
	return lines.join("\n");
}

function registerDoctor(pi: ExtensionAPI, diagnostics: Diagnostics): void {
	pi.registerCommand("incise-doctor", {
		description: "Report the pi-incise package, binary, schema, and tool status",
		handler: async (_args, ctx) => {
			const text = diagnosticText(diagnostics);
			const severity = diagnostics.error || diagnostics.fatalMismatch ? "error" :
				diagnostics.binaryVersion && diagnostics.binaryVersion !== diagnostics.packageVersion ? "warning" : "info";
			ctx.ui.notify(text, severity);
		},
	});
}

function argvFor(name: string, operation: string, path: string, args: ToolArguments): string[] {
	const argv = [operation, path];
	if (!(name in READ_SUBCOMMAND) || ["table_get", "list_get", "frontmatter_get"].includes(name)) {
		argv.push("--args", JSON.stringify(args));
	}
	return argv;
}

function registerTool(pi: ExtensionAPI, binary: ResolvedBinary, schema: ToolSchema): void {
	const prompt = PROMPT_METADATA[schema.name];
	pi.registerTool({
		name: schema.name,
		label: schema.name,
		description: schema.description,
		promptSnippet: prompt?.snippet,
		promptGuidelines: prompt?.guidelines,
		parameters: schema.parameters as TSchema,
		async execute(_toolCallId, params, signal, _onUpdate, ctx) {
			const invocation = prepareInvocation(schema.name, params as ToolArguments, ctx.cwd);
			const call = async () => runIncise(
				pi.exec.bind(pi),
				binary.path,
				argvFor(schema.name, invocation.operation, invocation.path, invocation.args),
				signal,
			);
			const result = invocation.write
				? await withFileMutationQueue(invocation.path, call)
				: await call();
			if (result.code !== 0 || result.payload.ok === false) throw processError(result);

			if (invocation.write) {
				return {
					content: [{ type: "text", text: String(result.payload.description ?? "") }],
					details: {
						exitCode: result.code,
						hash: result.payload.hash,
						path: result.payload.path ?? invocation.path,
						changed: Boolean(result.payload.changed),
					},
				};
			}
			return {
				content: [{ type: "text", text: String(result.payload.text ?? "") }],
				details: {
					exitCode: result.code,
					hash: result.payload.hash,
					path: result.payload.path ?? invocation.path,
					rows: result.payload.rows,
					list: result.payload.list,
					frontmatter: result.payload.frontmatter,
				},
			};
		},
	});
}

export default async function inciseExtension(pi: ExtensionAPI): Promise<void> {
	const expectedVersion = packageVersion();
	const binary = resolveBinary();
	const diagnostics: Diagnostics = {
		packageVersion: expectedVersion,
		binary,
		schemas: [],
		fatalMismatch: false,
	};
	let profile: RequestedProfile;
	try {
		profile = requestedProfile(process.env.INCISE_PROFILE);
		diagnostics.requestedProfile = profile;
	} catch (error) {
		diagnostics.error = error instanceof Error ? error.message : String(error);
		registerDoctor(pi, diagnostics);
		return;
	}

	if (!binary) {
		diagnostics.error = "No Incise binary is available for this platform. Set INCISE_BIN or install incise on PATH.";
		registerDoctor(pi, diagnostics);
		return;
	}

	diagnostics.binaryVersion = await binaryVersion(pi.exec.bind(pi), binary.path);
	if (binary.source === "package" && diagnostics.binaryVersion !== expectedVersion) {
		diagnostics.fatalMismatch = true;
		diagnostics.error = "The packaged native binary version does not match pi-incise; reinstall the package.";
		registerDoctor(pi, diagnostics);
		return;
	}
	if (profile === "minicpm-list") {
		diagnostics.profileDecision = selectProfile(profile, undefined);
		diagnostics.schemasAvailable = true;
		diagnostics.registeredTools = [...MINICPM_LIST_TOOL_NAMES];
		registerDoctor(pi, diagnostics);
		installMiniCpmListProfile(pi, binary);
		return;
	}

	try {
		diagnostics.schemas = await loadMeasuredSchemas(
			pi.exec.bind(pi),
			binary.path,
			profile === "safe-small" ? "safe-small" : "measured",
		);
	} catch (error) {
		diagnostics.error = error instanceof Error ? error.message : String(error);
		registerDoctor(pi, diagnostics);
		return;
	}

	const structural = profile === "safe-small" ? [] : STRUCTURAL_READ_SCHEMAS;
	const schemas = [...diagnostics.schemas, ...structural];
	diagnostics.registeredTools = schemas.map((schema) => schema.name);
	for (const schema of schemas) {
		registerTool(pi, binary, schema);
	}

	if (profile !== "auto") diagnostics.profileDecision = selectProfile(profile, undefined);
	if (profile === "auto" || profile === "safe-routed") {
		let decision = diagnostics.profileDecision;
		const familyOverride = profile === "auto" ? process.env.INCISE_MODEL_FAMILY : undefined;
		if (profile === "auto" && familyOverride) {
			try {
				decision = selectProfile(profile, undefined, familyOverride);
				diagnostics.profileDecision = decision;
			} catch (error) {
				diagnostics.error = error instanceof Error ? error.message : String(error);
			}
		}
		if (diagnostics.error) {
			registerDoctor(pi, diagnostics);
			return;
		}
		installSafeRoutedProfile(pi, binary, {
			standardTools: schemas.map((schema) => schema.name),
			isEnabled(ctx) {
				if (!decision && ctx.model) {
					decision = selectProfile(profile, ctx.model, familyOverride);
					diagnostics.profileDecision = decision;
				}
				return decision?.effective === "safe-routed";
			},
			onRoute(route) { diagnostics.activeRoute = route; },
		});
	}
	registerDoctor(pi, diagnostics);
}
