#!/usr/bin/env python3

import unittest

import minicpm_section_slots as slots


class SectionSlotsTests(unittest.TestCase):
    def task(self, task_id):
        return next(task for task in slots.tasks() if task["id"] == task_id)

    def test_schema_exposes_content_but_no_structure(self):
        props = slots.SCHEMA["parameters"]["properties"]
        self.assertEqual(set(props), {
            "new_heading", "body", "child_1_heading", "child_1_body",
            "child_2_heading", "child_2_body",
        })
        self.assertFalse({"path", "parent", "position"} & set(props))

    def test_structure_is_injected_from_the_ideal_first_operation(self):
        task = self.task("insert-nested-ratelimits")
        self.assertEqual(slots.structural_args(task), {
            "path": "corpus/sections/deep-nesting.md",
            "parent": "Reference > API",
            "position": "last-child",
        })

    def test_flat_children_compose_to_one_atomic_insert(self):
        task = self.task("insert-troubleshooting")
        call, error = slots.compose(task, {
            "new_heading": "Troubleshooting",
            "child_1_heading": "Logs",
            "child_1_body": "Written to `~/.incise/log`.",
            "child_2_heading": "Common errors",
            "child_2_body": "See the FAQ.",
        })
        self.assertIsNone(error)
        self.assertEqual(call["function"]["name"], "section_insert")
        self.assertIn('"children":[', call["function"]["arguments"])

    def test_orphan_child_body_refuses_before_execution(self):
        call, error = slots.compose(self.task("insert-release-at-top"), {
            "new_heading": "[1.5.0] - 2026-09-06",
            "child_1_body": "- `plan --explain` flag.",
        })
        self.assertIsNone(call)
        self.assertIn("without `child_1_heading`", error)

    def test_required_schemas_publish_only_the_routed_cardinality(self):
        zero = slots.required_schema(self.task("insert-subsection-last"))
        self.assertEqual(zero["parameters"]["required"], ["new_heading", "body"])
        self.assertEqual(
            set(zero["parameters"]["properties"]), {"new_heading", "body"})

        two = slots.required_schema(self.task("insert-troubleshooting"))
        self.assertEqual(two["name"], "section_insert_two_children")
        self.assertEqual(set(two["parameters"]["required"]), {
            "new_heading", "child_1_heading", "child_1_body",
            "child_2_heading", "child_2_body",
        })
        self.assertNotIn("body", two["parameters"]["properties"])

    def test_required_schema_can_be_selected_without_task_oracle(self):
        one = slots.schema_for_child_count(1)
        self.assertEqual(one["name"], "section_insert_one_child")
        self.assertEqual(set(one["parameters"]["properties"]), {
            "new_heading", "child_1_heading", "child_1_body",
        })
        with self.assertRaises(ValueError):
            slots.schema_for_child_count(3)

    def test_explicit_structure_reaches_composed_operation(self):
        call, error = slots.compose_with_structure({
            "new_heading": "New",
            "body": "Text.",
        }, {
            "path": "document.md",
            "parent": "Chosen > Anchor",
            "position": "after",
        })
        self.assertIsNone(error)
        args = __import__("json").loads(call["function"]["arguments"])
        self.assertEqual(args["parent"], "Chosen > Anchor")
        self.assertEqual(args["position"], "after")


if __name__ == "__main__":
    unittest.main()
