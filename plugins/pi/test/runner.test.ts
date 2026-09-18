import assert from "node:assert/strict";
import test from "node:test";

import { processError, runIncise, type Exec } from "../extension/runner.ts";

test("appends json mode and parses a successful payload", async () => {
	let received: string[] = [];
	const exec: Exec = async (_command, args) => {
		received = args;
		return {
			stdout: JSON.stringify({ ok: true, description: "Applied.", hash: "abc", changed: true }),
			stderr: "",
			code: 0,
			killed: false,
		};
	};
	const result = await runIncise(exec, "/bin/incise", ["table-add-row", "/tmp/a.md"]);
	assert.deepEqual(received, ["table-add-row", "/tmp/a.md", "--json"]);
	assert.equal(result.payload.description, "Applied.");
});

test("preserves refusal text and classifies the exit", async () => {
	const exec: Exec = async () => ({
		stdout: JSON.stringify({ ok: false, error: "Pass an ordinal." }),
		stderr: "",
		code: 1,
		killed: false,
	});
	const result = await runIncise(exec, "/bin/incise", ["rows", "/tmp/a.md"]);
	const error = processError(result) as Error & { exitCode: number; kind: string };
	assert.equal(error.message, "Pass an ordinal.");
	assert.equal(error.exitCode, 1);
	assert.equal(error.kind, "refusal");
});

test("turns non-json process failures into a usable error", async () => {
	const exec: Exec = async () => ({ stdout: "", stderr: "permission denied\n", code: 126, killed: false });
	const result = await runIncise(exec, "/bin/incise", ["tables", "/tmp/a.md"]);
	assert.equal(result.payload.error, "permission denied");
});

test("forwards timeout and cancellation to Pi's process runner", async () => {
	const controller = new AbortController();
	let received: unknown;
	const exec: Exec = async (_command, _args, options) => {
		received = options;
		return { stdout: '{"ok":true}', stderr: "", code: 0, killed: false };
	};
	await runIncise(exec, "/bin/incise", ["tables", "/tmp/a.md"], controller.signal, 1234);
	assert.deepEqual(received, { signal: controller.signal, timeout: 1234 });

	const aborted = new Error("aborted");
	const rejecting: Exec = async () => { throw aborted; };
	await assert.rejects(() => runIncise(rejecting, "/bin/incise", [], controller.signal), aborted);
});
