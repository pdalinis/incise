#!/usr/bin/env python3

import json
import unittest
from unittest.mock import patch

import minicpm_list_required_after as treatment


class RequiredAfterTests(unittest.TestCase):
    def task(self, task_id="add-item-nested-asterisk"):
        return next(task for task in treatment.tasks() if task["id"] == task_id)

    def test_schema_requires_only_content_and_exact_anchor(self):
        schema = treatment.edit_schema(["alpha", "beta-two"])
        self.assertEqual(
            set(schema["parameters"]["properties"]), {"text", "after"})
        self.assertEqual(
            schema["parameters"]["required"], ["text", "after"])
        self.assertEqual(
            schema["parameters"]["properties"]["after"]["enum"],
            ["alpha", "beta-two"])

    def test_exact_item_texts_preserve_order_and_dedupe(self):
        report = {"items": [
            {"text": "one"}, {"text": "two"}, {"text": "one"},
        ]}
        self.assertEqual(treatment.exact_item_texts(report), ["one", "two"])

    def test_compose_injects_read_address(self):
        task = self.task()
        call, error = treatment.compose(task, {
            "path": task["fixture"],
            "list": {"heading": "Asterisk markers, four-space indent"},
        }, {"text": "beta-three", "after": "beta-two"}, ["beta-two"])
        self.assertIsNone(error)
        args = json.loads(call["function"]["arguments"])
        self.assertEqual(args["path"], task["fixture"])
        self.assertEqual(args["list"]["heading"],
                         "Asterisk markers, four-space indent")
        self.assertEqual(args["after"], "beta-two")

    def test_compose_refuses_index_or_wrong_file(self):
        task = self.task()
        call, error = treatment.compose(task, {
            "path": task["fixture"], "list": {"heading": "x"},
        }, {"text": "beta-three", "after": "[3]"}, ["beta-two"])
        self.assertIsNone(call)
        self.assertIn("exact item", error)
        call, error = treatment.compose(task, {
            "path": "other.md", "list": {"heading": "x"},
        }, {"text": "beta-three", "after": "beta-two"}, ["beta-two"])
        self.assertIsNone(call)
        self.assertIn("not", error)

    def test_two_phase_trial_builds_dynamic_enum_and_executes(self):
        task = self.task()
        read_call = {
            "id": "read-1", "type": "function", "function": {
                "name": "list_get", "arguments": json.dumps({
                    "path": task["fixture"],
                    "list": {"heading": "Asterisk markers, four-space indent"},
                }),
            },
        }
        edit_call = {
            "id": "edit-1", "type": "function", "function": {
                "name": "list_insert_after", "arguments": json.dumps({
                    "text": "beta-three", "after": "beta-two",
                }),
            },
        }
        responses = [
            ({"model": "test"}, {
                "tool_calls": [read_call], "completion_tokens": 3,
                "elapsed_s": 0.1, "finish_reason": "tool_calls", "content": None,
            }),
            ({"model": "test"}, {
                "tool_calls": [edit_call], "completion_tokens": 4,
                "elapsed_s": 0.2, "finish_reason": "tool_calls", "content": None,
            }),
        ]
        read_schema = {"name": "list_get", "parameters": {"type": "object"}}
        with patch.object(treatment, "sample", side_effect=responses):
            row = treatment.run_trial("unused", task, 0, read_schema)
        self.assertTrue(row["document_changed"])
        self.assertIn("beta-two", row["allowed_after"])
        self.assertTrue(row["after_from_read"])
        args = json.loads(row["composed_operation"]["function"]["arguments"])
        self.assertEqual(args["after"], "beta-two")


if __name__ == "__main__":
    unittest.main()
