import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packed = spawnSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
	cwd: root,
	encoding: "utf8",
	env: { ...process.env, npm_config_cache: mkdtempSync(resolve(tmpdir(), "pi-incise-npm-cache-")) },
});
if (packed.status !== 0) throw new Error(packed.stderr || packed.stdout);
const report = JSON.parse(packed.stdout) as Array<{ files: Array<{ path: string }> }>;
const files = report[0]?.files.map((file) => file.path).sort() ?? [];
assert(files.includes("package.json"));
assert(files.includes("README.md"));
assert(files.includes("LICENSE"));
assert(files.includes("extension/index.ts"));
assert(!files.some((path) => path.startsWith("test/")));
assert(!files.some((path) => path.startsWith("native/")));
assert(!files.includes("tsconfig.json"));
console.log(`pack check passed (${files.length} files)`);
