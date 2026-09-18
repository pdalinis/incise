import { accessSync, constants, existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { delimiter, dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type BinarySource = "environment" | "package" | "path" | "development";

export interface ResolvedBinary {
	path: string;
	source: BinarySource;
	packageName?: string;
}

export interface RuntimePlatform {
	platform: NodeJS.Platform;
	arch: string;
	glibc: boolean;
}

const extensionDirectory = dirname(fileURLToPath(import.meta.url));
export const packageRoot = resolve(extensionDirectory, "..");

export function packageVersion(root = packageRoot): string {
	const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as { version?: unknown };
	if (typeof manifest.version !== "string" || !manifest.version) {
		throw new Error("pi-incise package.json has no version");
	}
	return manifest.version;
}

export function currentRuntime(): RuntimePlatform {
	let glibc = false;
	if (process.platform === "linux") {
		const report = process.report?.getReport() as { header?: { glibcVersionRuntime?: unknown } } | undefined;
		glibc = typeof report?.header?.glibcVersionRuntime === "string";
	}
	return { platform: process.platform, arch: process.arch, glibc };
}

export function nativePackageFor(runtime: RuntimePlatform): string | undefined {
	if (runtime.platform === "darwin" && runtime.arch === "arm64") {
		return "@pdalinis/pi-incise-darwin-arm64";
	}
	if (runtime.platform === "darwin" && runtime.arch === "x64") {
		return "@pdalinis/pi-incise-darwin-x64";
	}
	if (runtime.platform === "linux" && runtime.glibc && runtime.arch === "arm64") {
		return "@pdalinis/pi-incise-linux-arm64-gnu";
	}
	if (runtime.platform === "linux" && runtime.glibc && runtime.arch === "x64") {
		return "@pdalinis/pi-incise-linux-x64-gnu";
	}
	return undefined;
}

function executable(path: string): boolean {
	try {
		accessSync(path, constants.X_OK);
		return true;
	} catch {
		return false;
	}
}

function pathExecutable(name: string, pathValue: string | undefined): string | undefined {
	for (const directory of (pathValue ?? "").split(delimiter)) {
		if (!directory) continue;
		const candidate = join(directory, name);
		if (executable(candidate)) return candidate;
	}
	return undefined;
}

export function developmentCandidates(start = extensionDirectory): string[] {
	let directory = resolve(start);
	for (;;) {
		if (existsSync(join(directory, "Cargo.toml")) && existsSync(join(directory, "crates"))) {
			return [join(directory, "target", "release", "incise"), join(directory, "target", "debug", "incise")];
		}
		const parent = dirname(directory);
		if (parent === directory) return [];
		directory = parent;
	}
}

export interface ResolveBinaryOptions {
	env?: NodeJS.ProcessEnv;
	runtime?: RuntimePlatform;
	startDirectory?: string;
	requireFrom?: string;
}

export function resolveBinary(options: ResolveBinaryOptions = {}): ResolvedBinary | undefined {
	const env = options.env ?? process.env;
	const explicit = env.INCISE_BIN;
	if (explicit) {
		const candidate = isAbsolute(explicit) ? explicit : resolve(explicit);
		if (executable(candidate)) return { path: candidate, source: "environment" };
	}

	const packageName = nativePackageFor(options.runtime ?? currentRuntime());
	if (packageName) {
		try {
			const require = createRequire(options.requireFrom ?? import.meta.url);
			const manifest = require.resolve(`${packageName}/package.json`);
			const candidate = join(dirname(manifest), "bin", "incise");
			if (executable(candidate)) return { path: candidate, source: "package", packageName };
		} catch {
			// An optional dependency is absent on unsupported systems and in development checkouts.
		}
	}

	const onPath = pathExecutable("incise", env.PATH);
	if (onPath) return { path: onPath, source: "path" };

	for (const candidate of developmentCandidates(options.startDirectory)) {
		if (executable(candidate)) return { path: candidate, source: "development" };
	}
	return undefined;
}

export function parseBinaryVersion(stdout: string): string | undefined {
	return stdout.trim().match(/^incise\s+(\S+)$/)?.[1];
}
