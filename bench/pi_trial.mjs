#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { accessSync, constants, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const RESULT_PREFIX = "PI_BENCH_RESULT=";

function textOf(content) {
	if (!Array.isArray(content)) return typeof content === "string" ? content : "";
	return content.filter((part) => part?.type === "text").map((part) => part.text).join("");
}

function thinkingOf(content) {
	if (!Array.isArray(content)) return "";
	return content
		.filter((part) => part?.type === "thinking")
		.map((part) => part.thinking ?? "")
		.join("");
}

function systemPromptOf(messages) {
	if (!Array.isArray(messages)) return "";
	return messages
		.filter((message) => message?.role === "system")
		.map((message) => textOf(message.content))
		.filter(Boolean)
		.join("\n\n");
}

function packageRootFor(extensionPath) {
	return resolve(dirname(extensionPath), "..");
}

function packageVersion(root) {
	return JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version;
}

function binaryVersion(path) {
	return execFileSync(path, ["--version"], { encoding: "utf8" }).trim();
}

function packageBinary(extensionPath) {
	const names = {
		"darwin-arm64": "@pdalinis/pi-incise-darwin-arm64",
		"darwin-x64": "@pdalinis/pi-incise-darwin-x64",
		"linux-arm64": "@pdalinis/pi-incise-linux-arm64-gnu",
		"linux-x64": "@pdalinis/pi-incise-linux-x64-gnu",
	};
	const packageName = names[`${process.platform}-${process.arch}`];
	if (!packageName) return null;
	try {
		const require = createRequire(extensionPath);
		const manifest = require.resolve(`${packageName}/package.json`);
		const path = join(dirname(manifest), "bin", "incise");
		accessSync(path, constants.X_OK);
		return { path, source: "package", packageName, version: binaryVersion(path) };
	} catch {
		return null;
	}
}

function modelFor(request) {
	const configured = request.model ?? {};
	const reasoning = configured.reasoning ?? false;
	const defaultSampling = reasoning
		? {}
		: { chat_template_kwargs: { enable_thinking: false } };
	return {
		id: configured.id ?? "gemma4-direct-q8",
		name: configured.name ?? "gemma-4-26B-A4B-it",
		api: "openai-completions",
		provider: "pi-composition-local",
		baseUrl: request.endpoint.replace(/\/$/, ""),
		reasoning,
		...(configured.thinkingLevelMap ? { thinkingLevelMap: configured.thinkingLevelMap } : {}),
		input: ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: configured.contextWindow ?? 65_536,
		maxTokens: configured.maxTokens ?? 8_192,
		samplingParams: {
			seed: request.seed ?? 0,
			...defaultSampling,
			...(configured.samplingParams ?? {}),
		},
		compat: {
			maxTokensField: "max_tokens",
			supportsUsageInStreaming: true,
			...(configured.compat ?? {}),
		},
	};
}

async function createSession(request) {
	const sdk = await import(pathToFileURL(resolve(request.piSdk)).href);
	const {
		createAgentSession,
		DefaultResourceLoader,
		ModelRuntime,
		SessionManager,
		SettingsManager,
	} = sdk;

	const resourceLoader = new DefaultResourceLoader({
		cwd: request.cwd,
		agentDir: request.agentDir,
		additionalExtensionPaths: [request.extension],
		noExtensions: true,
		noSkills: true,
		noPromptTemplates: true,
		noThemes: true,
		noContextFiles: true,
	});
	await resourceLoader.reload();

	const modelRuntime = await ModelRuntime.create({
		authPath: join(request.agentDir, "auth.json"),
		modelsPath: join(request.agentDir, "models.json"),
	});
	const requestedModel = modelFor(request);
	const { provider, baseUrl, api, ...modelDefinition } = requestedModel;
	modelRuntime.registerProvider(provider, {
		baseUrl,
		api,
		apiKey: "local-benchmark",
		models: [modelDefinition],
	});
	await modelRuntime.refresh({ allowNetwork: false });
	const model = modelRuntime.getModel(provider, requestedModel.id);
	if (!model) throw new Error(`custom model was not registered: ${provider}/${requestedModel.id}`);

	const settingsManager = SettingsManager.inMemory({
		compaction: { enabled: false },
		retry: { enabled: false },
	});
	const created = await createAgentSession({
		cwd: request.cwd,
		agentDir: request.agentDir,
		model,
		thinkingLevel: request.thinkingLevel ?? (requestedModel.reasoning ? "high" : "off"),
		modelRuntime,
		resourceLoader,
		tools: request.tools,
		sessionManager: SessionManager.inMemory(request.cwd),
		settingsManager,
	});
	return created.session;
}

function toolInfo(session, names) {
	const wanted = new Set(names);
	return session.getAllTools()
		.filter((tool) => wanted.has(tool.name))
		.map((tool) => ({
			name: tool.name,
			description: tool.description,
			parameters: tool.parameters,
			promptGuidelines: tool.promptGuidelines ?? [],
		}));
}

async function probe(request, session) {
	const binary = packageBinary(request.extension);
	const root = packageRootFor(request.extension);
	return {
		mode: "probe",
		packageRoot: root,
		packageVersion: packageVersion(root),
		binary,
		activeTools: session.getActiveToolNames(),
		tools: toolInfo(session, request.tools),
		systemPrompt: session.systemPrompt,
	};
}

async function ideal(request, session) {
	const results = [];
	for (const [index, call] of request.calls.entries()) {
		const definition = session.getToolDefinition(call.name);
		if (!definition) throw new Error(`active tool has no definition: ${call.name}`);
		try {
			const result = await definition.execute(
				`ideal-${index}`,
				call.arguments,
				new AbortController().signal,
				undefined,
				{ cwd: request.cwd },
			);
			results.push({
				tool_call_id: `ideal-${index}`,
				name: call.name,
				is_error: false,
				content: textOf(result.content),
				details: result.details ?? null,
			});
		} catch (error) {
			results.push({
				tool_call_id: `ideal-${index}`,
				name: call.name,
				is_error: true,
				content: error instanceof Error ? error.message : String(error),
				details: null,
			});
		}
	}
	return { mode: "ideal", toolResults: results };
}

async function run(request, session) {
	let turnsSeen = 0;
	let capped = false;
	let abortPromise;
	const activeTools = [];
	const providerRequests = [];
	const unsubscribe = session.subscribe((event) => {
		if (request.recordActiveTools && (event.type === "turn_start" || event.type === "tool_execution_start")) {
			activeTools.push({ event: event.type, tools: session.getActiveToolNames() });
		}
		if (event.type !== "turn_end") return;
		turnsSeen += 1;
		if (turnsSeen >= request.maxTurns && session.isStreaming && !abortPromise) {
			capped = true;
			abortPromise = session.abort();
		}
	});

	const started = performance.now();
	let promptError;
	const originalFetch = globalThis.fetch;
	if (request.recordProviderRequests) {
		globalThis.fetch = async (input, init) => {
			try {
				if (typeof init?.body === "string") {
					const payload = JSON.parse(init.body);
					if (payload && typeof payload === "object" && Array.isArray(payload.messages)) {
						const systemPrompt = systemPromptOf(payload.messages);
						providerRequests.push({
							model: payload.model ?? null,
							active_tools: session.getActiveToolNames(),
							tool_choice: payload.tool_choice ?? null,
							seed: payload.seed ?? null,
							max_tokens: payload.max_tokens ?? payload.max_completion_tokens ?? null,
							temperature: payload.temperature ?? null,
							top_p: payload.top_p ?? null,
							top_k: payload.top_k ?? null,
							min_p: payload.min_p ?? null,
							presence_penalty: payload.presence_penalty ?? null,
							repeat_penalty: payload.repeat_penalty ?? null,
							parallel_tool_calls: payload.parallel_tool_calls ?? null,
							chat_template_kwargs: payload.chat_template_kwargs ?? null,
							tools: Array.isArray(payload.tools)
								? payload.tools.map((tool) => tool?.function?.name ?? null)
								: [],
							system_prompt: systemPrompt,
							system_prompt_sha256: createHash("sha256").update(systemPrompt).digest("hex"),
							system_prompt_bytes: Buffer.byteLength(systemPrompt),
						});
					}
				}
			} catch {
				// Observation must never alter the provider request or its outcome.
			}
			return originalFetch(input, init);
		};
	}
	try {
		await session.prompt(request.prompt);
	} catch (error) {
		if (!capped) promptError = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
	} finally {
		globalThis.fetch = originalFetch;
	}
	if (abortPromise) await abortPromise;
	const elapsedSeconds = (performance.now() - started) / 1000;
	unsubscribe();

	const turns = [];
	const toolCalls = [];
	const toolResults = [];
	let completionTokens = 0;
	let reasoningTokens = 0;
	let reasoningCharacters = 0;
	for (const message of session.state.messages) {
		if (message.role === "assistant") {
			const thinking = thinkingOf(message.content);
			const calls = (message.content ?? [])
				.filter((part) => part.type === "toolCall")
				.map((part) => ({
					id: part.id,
					type: "function",
					function: {
						name: part.name,
						arguments: JSON.stringify(part.arguments ?? {}),
					},
				}));
			toolCalls.push(...calls);
			completionTokens += message.usage?.output ?? 0;
			reasoningTokens += message.usage?.reasoning ?? 0;
			reasoningCharacters += thinking.length;
			turns.push({
				content: textOf(message.content),
				reasoning_content: thinking,
				reasoning_characters: thinking.length,
				tool_calls: calls,
				finish_reason: message.stopReason,
				completion_tokens: message.usage?.output ?? 0,
				reasoning_tokens: message.usage?.reasoning ?? 0,
			});
		} else if (message.role === "toolResult") {
			toolResults.push({
				tool_call_id: message.toolCallId,
				name: message.toolName,
				is_error: Boolean(message.isError),
				content: textOf(message.content),
				details: message.details ?? null,
			});
		}
	}

	return {
		mode: "run",
		error: promptError,
		capped,
		elapsed_s: Math.round(elapsedSeconds * 100) / 100,
		completion_tokens: completionTokens,
		reasoning_tokens: reasoningTokens,
		reasoning_characters: reasoningCharacters,
		n_turns: turns.length,
		turns,
		tool_calls: toolCalls,
		tool_results: toolResults,
		final_content: [...session.state.messages].reverse().find((message) => message.role === "assistant")
			? textOf([...session.state.messages].reverse().find((message) => message.role === "assistant").content)
			: "",
		...(request.recordActiveTools ? { active_tools: activeTools } : {}),
		...(request.recordProviderRequests ? { provider_requests: providerRequests } : {}),
	};
}

async function main() {
	const input = readFileSync(0, "utf8");
	const request = JSON.parse(input);
	const session = await createSession(request);
	try {
		let result;
		if (request.mode === "probe") result = await probe(request, session);
		else if (request.mode === "ideal") result = await ideal(request, session);
		else if (request.mode === "run") result = await run(request, session);
		else throw new Error(`unknown mode: ${request.mode}`);
		process.stdout.write(`${RESULT_PREFIX}${JSON.stringify(result)}\n`);
	} finally {
		session.dispose();
	}
}

main().catch((error) => {
	const text = error instanceof Error ? `${error.name}: ${error.message}\n${error.stack ?? ""}` : String(error);
	process.stderr.write(`${text}\n`);
	process.exitCode = 1;
});
