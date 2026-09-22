#!/usr/bin/env python3

import json
import unittest
from unittest.mock import patch

import minicpm_list_relation_router as router


class ListRelationRouterTests(unittest.TestCase):
    def test_schemas_publish_distinct_required_shapes(self):
        after, between = router.relation_schemas(["second", "third"])
        self.assertEqual(after["name"], "list_insert_after")
        self.assertEqual(after["parameters"]["required"], ["text", "after"])
        self.assertEqual(between["name"], "list_insert_between")
        self.assertEqual(
            between["parameters"]["required"], ["text", "after", "before"])
        self.assertIn("only when", after["description"])
        self.assertIn("only when", between["description"])

    def test_relation_parser_requires_exactly_one_known_call(self):
        parsed, error = router.parse_relation_call({"tool_calls": []})
        self.assertIsNone(parsed)
        self.assertIn("exactly one", error)
        parsed, error = router.parse_relation_call({"tool_calls": [{
            "function": {"name": "unknown", "arguments": "{}"},
        }]})
        self.assertIsNone(parsed)
        self.assertIn("unknown tool", error)

    def test_trial_routes_between_and_preserves_validation(self):
        task = next(
            task for task in router.base.tasks()
            if task["id"] == "add-item-ordered-renumber")
        read_call = {
            "id": "read-1", "type": "function", "function": {
                "name": "list_get", "arguments": json.dumps({
                    "path": task["fixture"], "list": {"heading": "Sequential"},
                }),
            },
        }
        relation_call = {
            "id": "route-1", "type": "function", "function": {
                "name": "list_insert_between", "arguments": json.dumps({
                    "text": "two and a half", "after": "second", "before": "third",
                }),
            },
        }
        responses = [
            ({"model": "test"}, {
                "tool_calls": [read_call], "completion_tokens": 3,
                "elapsed_s": 0.1, "finish_reason": "tool_calls", "content": None,
            }),
            ({"model": "test"}, {
                "tool_calls": [relation_call], "completion_tokens": 4,
                "elapsed_s": 0.2, "finish_reason": "tool_calls", "content": None,
            }),
        ]
        schema = {"name": "list_get", "parameters": {"type": "object"}}
        with patch.object(router, "sample", side_effect=responses):
            row = router.run_trial("unused", task, 0, schema)
        self.assertEqual(row["selected_relation"], "between")
        self.assertTrue(row["relation_correct"])
        self.assertTrue(row["validation_passed"])
        self.assertTrue(row["document_changed"])


if __name__ == "__main__":
    unittest.main()
