import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const expected = [
	["darwin-arm64", "@pdalinis/pi-incise-darwin-arm64", "darwin", "arm64", undefined],
	["darwin-x64", "@pdalinis/pi-incise-darwin-x64", "darwin", "x64", undefined],
	["linux-arm64-gnu", "@pdalinis/pi-incise-linux-arm64-gnu", "linux", "arm64", "glibc"],
	["linux-x64-gnu", "@pdalinis/pi-incise-linux-x64-gnu", "linux", "x64", "glibc"],
] as const;

test("native package metadata matches the retained npm release version", () => {
	const main = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));
	const scope = JSON.parse(
		readFileSync(resolve(root, "..", "..", ".github", "release-scope.json"), "utf8"),
	);
	assert.equal(main.version, scope.npmVersion);
	for (const [directory, name, os, cpu, libc] of expected) {
		const manifest = JSON.parse(readFileSync(resolve(root, "native", directory, "package.json"), "utf8"));
		assert.equal(manifest.name, name);
		assert.equal(manifest.version, main.version);
		assert.equal(main.optionalDependencies[name], main.version);
		assert.deepEqual(manifest.os, [os]);
		assert.deepEqual(manifest.cpu, [cpu]);
		assert.deepEqual(manifest.libc, libc ? [libc] : undefined);
		assert(manifest.files.includes("bin/incise"));
		assert.equal(manifest.scripts, undefined);
	}
});
