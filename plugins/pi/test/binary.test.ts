import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { developmentCandidates, nativePackageFor, parseBinaryVersion, resolveBinary } from "../extension/binary.ts";

test("maps only the four supported native targets", () => {
	assert.equal(nativePackageFor({ platform: "darwin", arch: "arm64", glibc: false }), "@pdalinis/pi-incise-darwin-arm64");
	assert.equal(nativePackageFor({ platform: "darwin", arch: "x64", glibc: false }), "@pdalinis/pi-incise-darwin-x64");
	assert.equal(nativePackageFor({ platform: "linux", arch: "arm64", glibc: true }), "@pdalinis/pi-incise-linux-arm64-gnu");
	assert.equal(nativePackageFor({ platform: "linux", arch: "x64", glibc: true }), "@pdalinis/pi-incise-linux-x64-gnu");
	assert.equal(nativePackageFor({ platform: "linux", arch: "x64", glibc: false }), undefined);
	assert.equal(nativePackageFor({ platform: "win32", arch: "x64", glibc: false }), undefined);
});

test("parses only incise version output", () => {
	assert.equal(parseBinaryVersion("incise 0.1.1\n"), "0.1.1");
	assert.equal(parseBinaryVersion("other 0.1.1\n"), undefined);
});

test("resolves the explicit override before PATH", () => {
	const directory = mkdtempSync(join(tmpdir(), "pi-incise-binary-"));
	const override = join(directory, "override");
	const pathBinary = join(directory, "incise");
	for (const path of [override, pathBinary]) {
		writeFileSync(path, "#!/bin/sh\n", { mode: 0o755 });
		chmodSync(path, 0o755);
	}
	const resolved = resolveBinary({
		env: { INCISE_BIN: override, PATH: directory },
		runtime: { platform: "linux", arch: "riscv64", glibc: true },
		startDirectory: directory,
	});
	assert.deepEqual(resolved, { path: override, source: "environment" });
});

test("finds release then debug binaries in a development checkout", () => {
	const directory = mkdtempSync(join(tmpdir(), "pi-incise-checkout-"));
	mkdirSync(join(directory, "crates"));
	mkdirSync(join(directory, "plugins", "pi", "extension"), { recursive: true });
	writeFileSync(join(directory, "Cargo.toml"), "[workspace]\n");
	assert.deepEqual(developmentCandidates(join(directory, "plugins", "pi", "extension")), [
		join(directory, "target", "release", "incise"),
		join(directory, "target", "debug", "incise"),
	]);
});
