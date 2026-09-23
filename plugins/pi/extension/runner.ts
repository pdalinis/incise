import type { ExecOptions, ExecResult } from "@earendil-works/pi-coding-agent";

export type Exec = (command: string, args: string[], options?: ExecOptions) => Promise<ExecResult>;

export interface IncisePayload {
	ok?: boolean;
	error?: string;
	description?: string;
	text?: string;
	hash?: string;
	path?: string;
	changed?: boolean;
	written?: boolean;
	stale?: boolean;
	usage?: boolean;
	[key: string]: unknown;
}

export interface InciseResult {
	code: number;
	killed: boolean;
	stderr: string;
	payload: IncisePayload;
}

function fallbackMessage(result: ExecResult): string {
	return (result.stderr || result.stdout).trim() || `incise exited ${result.code}`;
}

export async function runIncise(
	exec: Exec,
	binary: string,
	args: string[],
	signal?: AbortSignal,
	timeout = 30_000,
): Promise<InciseResult> {
	const result = await exec(binary, [...args, "--json"], { signal, timeout });
	let payload: IncisePayload = {};
	try {
		payload = result.stdout.trim() ? JSON.parse(result.stdout) as IncisePayload : {};
	} catch {
		// The synthesized error below retains the process output for non-JSON failures.
	}
	if (!payload || typeof payload !== "object" || Array.isArray(payload)) payload = {};
	if (Object.keys(payload).length === 0) payload = { ok: false, error: fallbackMessage(result) };
	return { code: result.code, killed: result.killed, stderr: result.stderr, payload };
}

export async function binaryVersion(exec: Exec, binary: string): Promise<string | undefined> {
	const result = await exec(binary, ["--version"], { timeout: 10_000 });
	if (result.code !== 0) return undefined;
	return result.stdout.trim().match(/^incise\s+(\S+)$/)?.[1];
}

export function processError(result: InciseResult): Error {
	const message = typeof result.payload.error === "string"
		? result.payload.error
		: `incise exited ${result.code} with nothing to say.`;
	const error = new Error(message) as Error & {
		exitCode?: number;
		kind?: "refusal" | "usage" | "stale" | "process";
		stderr?: string;
		repair?: unknown;
	};
	error.exitCode = result.code;
	error.kind = result.code === 1 ? "refusal" : result.code === 2 ? "usage" : result.code === 3 ? "stale" : "process";
	error.stderr = result.stderr;
	error.repair = result.payload.repair;
	return error;
}
