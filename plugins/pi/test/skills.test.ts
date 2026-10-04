import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { formatSkillsForPrompt, loadSkillsFromDir } from "@earendil-works/pi-coding-agent";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(packageRoot, "../..");
const packagedSkill = join(packageRoot, "skills", "incise-check", "SKILL.md");
const canonicalSkill = join(repositoryRoot, "skills", "incise-check", "SKILL.md");
const launcher = join(packageRoot, "skills", "incise-check", "scripts", "check.mjs");

test("the Pi skill is the canonical explicit-only skill", () => {
	assert.equal(readFileSync(packagedSkill, "utf8"), readFileSync(canonicalSkill, "utf8"));
	assert.match(readFileSync(packagedSkill, "utf8"), /disable-model-invocation: true/);
	const manifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8")) as {
		pi?: { skills?: string[] };
	};
	assert.deepEqual(manifest.pi?.skills, ["./skills/incise-check"]);
});

test("Pi discovers the packaged skill but omits it from automatic selection", () => {
	const loaded = loadSkillsFromDir({ dir: join(packageRoot, "skills"), source: "pi-incise-test" });
	assert.deepEqual(loaded.diagnostics, []);
	assert.equal(loaded.skills.length, 1);
	assert.equal(loaded.skills[0]?.name, "incise-check");
	assert.equal(loaded.skills[0]?.disableModelInvocation, true);
	assert.equal(formatSkillsForPrompt(loaded.skills), "");
});

test("the skill launcher uses the integration-selected binary", () => {
	const directory = mkdtempSync(join(tmpdir(), "pi-incise-skill-"));
	const fake = join(directory, "incise-fake.mjs");
	writeFileSync(fake, "#!/usr/bin/env node\nprocess.stdout.write(JSON.stringify(process.argv.slice(2)));\n");
	chmodSync(fake, 0o755);
	const result = spawnSync(process.execPath, ["--experimental-strip-types", launcher, "note.md"], {
		encoding: "utf8",
		env: { ...process.env, INCISE_BIN: fake },
	});
	assert.equal(result.status, 0, result.stderr);
	assert.deepEqual(JSON.parse(result.stdout), ["check", "note.md", "--json"]);
});
