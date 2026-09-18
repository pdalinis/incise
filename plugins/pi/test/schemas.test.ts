import assert from "node:assert/strict";
import test from "node:test";

import { STRUCTURAL_READ_SCHEMAS } from "../extension/schemas.ts";

test("publishes the three structural reads in stable order", () => {
	assert.deepEqual(STRUCTURAL_READ_SCHEMAS.map((schema) => schema.name), [
		"md_tables",
		"md_lists",
		"md_outline",
	]);
	for (const schema of STRUCTURAL_READ_SCHEMAS) {
		assert.deepEqual(schema.parameters.required, ["path"]);
	}
});
