#!/usr/bin/env python3

import os
import unittest

import minicpm_section_semantic_plan as semantic


class SemanticPlanTests(unittest.TestCase):
    def task(self, task_id):
        return next(task for task in semantic.prior.slots.tasks() if task["id"] == task_id)

    def content(self, task):
        with open(os.path.join(semantic.ROOT, task["fixture"]), newline="") as fh:
            return fh.read()

    def test_schema_hides_executor_jargon_and_numeric_count(self):
        schema = semantic.semantic_schema(self.content(self.task("insert-troubleshooting")))
        props = schema["parameters"]["properties"]
        self.assertEqual(set(props), {
            "anchor", "relationship", "order", "content_shape",
        })
        rendered = str(schema)
        self.assertNotIn("last-child", rendered)
        self.assertNotIn("child_count", rendered)

    def test_expected_semantic_plans(self):
        self.assertEqual(semantic.expected_plan(self.task("insert-release-at-top")), {
            "anchor": "[1.4.2] - 2026-08-14",
            "relationship": "sibling",
            "order": "before-existing",
            "content_shape": "one-subsection",
        })
        self.assertEqual(semantic.expected_plan(self.task("insert-troubleshooting")), {
            "anchor": "Deep heading nesting",
            "relationship": "subsection",
            "order": "after-existing",
            "content_shape": "two-subsections",
        })

    def test_longer_unique_anchor_is_canonicalized(self):
        task = self.task("insert-nested-ratelimits")
        content = self.content(task)
        self.assertEqual(
            semantic.canonical_anchor(content, "Reference > API"), "API")

    def test_ambiguous_anchor_is_refused(self):
        task = self.task("insert-nested-ratelimits")
        plan = {
            "anchor": "macOS", "relationship": "subsection",
            "order": "after-existing", "content_shape": "body-only",
        }
        canonical, error = semantic.canonical_plan(self.content(task), plan)
        self.assertIsNone(canonical)
        self.assertIn("ambiguous", error)

    def test_field_matches_survive_an_invalid_sibling_field(self):
        task = self.task("insert-troubleshooting")
        content = self.content(task)
        expected = semantic.expected_plan(task)
        matches = semantic.independent_field_matches(content, {
            "anchor": "Deep heading nesting",
            "relationship": "after-existing",
            "order": "after-existing",
            "content_shape": "two-subsections",
        }, expected)
        self.assertEqual(matches, {
            "anchor": True, "relationship": False,
            "order": True, "content_shape": True,
        })


if __name__ == "__main__":
    unittest.main()
