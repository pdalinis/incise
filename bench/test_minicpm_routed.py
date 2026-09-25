#!/usr/bin/env python3

import json
import os
import unittest

import armb
import minicpm_routed as routed


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(ROOT, "target", "debug", "incise")


class RoutedTreatmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = routed.load_schemas(BINARY)

    def task(self, family, task_id):
        _path, tasks = routed.load_tasks(family)
        return next(task for task in tasks if task["id"] == task_id)

    def test_primary_population_is_the_preregistered_ninety_pairs(self):
        self.assertEqual(sum(len(ids) for ids in routed.PRIMARY.values()) * 3, 90)

    def test_table_and_section_routes_publish_one_forced_write(self):
        for family, task_id, expected in (
            ("tables", "add-row-aligned-short", "table_add_row"),
            ("sections", "append-hotfix-note", "section_append"),
        ):
            with self.subTest(task_id=task_id):
                payload, read_name, edit_name = routed.treatment_payload(
                    self.task(family, task_id), 0, self.schemas)
                self.assertIsNone(read_name)
                self.assertEqual(edit_name, expected)
                self.assertEqual(payload["tools"][0]["function"]["name"], expected)
                self.assertEqual(payload["tool_choice"]["function"]["name"], expected)

    def test_list_route_forces_read_then_write(self):
        payload, read_name, edit_name = routed.treatment_payload(
            self.task("lists", "add-item-nested-asterisk"), 0, self.schemas)
        self.assertEqual((read_name, edit_name), ("list_get", "list_add_item"))
        self.assertEqual(payload["tools"][0]["function"]["name"], "list_get")
        self.assertEqual(payload["tool_choice"]["function"]["name"], "list_get")

    def test_frontmatter_route_uses_the_requested_scalar_type(self):
        expected = {
            "set-build-jobs": "integer",
            "set-draft-true": "boolean",
            "clear-title": "null",
            "release-bump": "string",
        }
        for task_id, suffix in expected.items():
            with self.subTest(task_id=task_id):
                task = self.task("frontmatter", task_id)
                _read, edit = routed.route(task)
                self.assertEqual(edit, f"frontmatter_set_{suffix}")
                self.assertEqual(
                    self.schemas[edit]["parameters"]["properties"]["value"],
                    {"type": suffix},
                )
                op, _args = armb.normalize(edit, {"key": "x", "value": None})
                self.assertEqual(op, "frontmatter-set")

    def test_frontmatter_precondition_is_owned_by_the_router(self):
        create = self.task("frontmatter", "add-build-cache")
        update = self.task("frontmatter", "set-build-target")
        self.assertEqual(
            routed.frontmatter_precondition(create), {"must_absent": True})
        self.assertEqual(
            routed.frontmatter_precondition(update), {"must_exist": True})
        self.assertIsNone(routed.frontmatter_precondition(
            self.task("tables", "add-row-aligned-short")))

    def test_forced_call_parser_uses_only_the_first_call(self):
        row = {"tool_calls": [
            {"function": {"name": "list_get", "arguments": '{"path":"x"}'}},
            {"function": {"name": "list_get", "arguments": '{"path":"y"}'}},
        ]}
        parsed, error = routed._parse_call(row, "list_get")
        self.assertIsNone(error)
        self.assertEqual(parsed[1], {"path": "x"})

    def test_section_children_schema_is_opt_in_and_structured(self):
        self.assertNotIn(
            "children",
            self.schemas["section_insert"]["parameters"]["properties"],
        )
        schemas = routed.load_schemas(BINARY, section_children=True)
        children = schemas["section_insert"]["parameters"]["properties"]["children"]
        self.assertEqual(children["type"], "array")
        self.assertEqual(children["items"]["required"], ["heading"])
        self.assertIn("never", schemas["section_insert"]["description"])


if __name__ == "__main__":
    unittest.main()
