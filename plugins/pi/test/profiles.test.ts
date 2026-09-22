import assert from "node:assert/strict";
import test from "node:test";

import { modelFamily, requestedProfile, selectProfile } from "../extension/profiles.ts";

test("profile names preserve the measured alias and reject typos", () => {
	assert.equal(requestedProfile(undefined), "standard");
	assert.equal(requestedProfile("measured"), "standard");
	assert.equal(requestedProfile("safe-routed"), "safe-routed");
	assert.throws(() => requestedProfile("gemma"), /Unknown INCISE_PROFILE/);
});

test("model families are inferred from model identity or an explicit override", () => {
	assert.equal(modelFamily({ id: "google/gemma-4-26b" }), "gemma");
	assert.equal(modelFamily({ name: "OpenBMB MiniCPM5-2B" }), "minicpm");
	assert.equal(modelFamily({ id: "local" }), "unknown");
	assert.equal(modelFamily({ id: "local" }, "gemma"), "gemma");
	assert.throws(() => modelFamily(undefined, "other"), /Unknown INCISE_MODEL_FAMILY/);
});

test("auto enables only capabilities backed by a passing model-family evaluation", () => {
	assert.equal(selectProfile("auto", { id: "gemma4-direct-q8" }).effective, "safe-routed");
	const minicpm = selectProfile("auto", { id: "openbmb/MiniCPM5-2B" });
	assert.equal(minicpm.effective, "standard");
	assert.match(minicpm.reason, /no general MiniCPM profile has passed/);
	assert.equal(selectProfile("auto", { id: "some-future-model" }).effective, "standard");
	assert.equal(selectProfile("safe-routed", { id: "some-future-model" }).effective, "safe-routed");
});
