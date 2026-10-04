#!/usr/bin/env node

// Thin host-owned launcher. Detection and repair remain in the Incise binary;
// this file only reuses pi-incise's version-matched binary resolution.
import { spawnSync } from "node:child_process";
import { resolveBinary } from "../../../extension/binary.ts";

const binary = resolveBinary();
if (!binary) {
	process.stderr.write("No Incise binary is available for this platform. Reinstall pi-incise or set INCISE_BIN.\n");
	process.exit(2);
}

const args = process.argv.slice(2);
if (args.length === 0) {
	process.stderr.write("usage: check.mjs PATH [--fix-safe --if-match HASH]\n");
	process.exit(2);
}
const result = spawnSync(binary.path, ["check", ...args, "--json"], {
	encoding: "utf8",
	stdio: ["ignore", "pipe", "pipe"],
});
process.stdout.write(result.stdout ?? "");
process.stderr.write(result.stderr ?? "");
if (result.error) {
	process.stderr.write(`${result.error.message}\n`);
	process.exit(2);
}
process.exit(result.status ?? 2);
