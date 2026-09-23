#!/usr/bin/env python3

import json
import unittest
from unittest import mock

import minicpm_list_integrated as integrated


class IntegratedListTests(unittest.TestCase):
    @staticmethod
    def call_row(name, arguments, call_id):
        return {
            "finish_reason": "tool_calls",
            "elapsed_s": 0.1,
            "completion_tokens": 4,
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }],
        }

    def test_request_shape_router_matches_every_preregistered_task(self):
        for task in integrated.tasks():
            self.assertEqual(
                integrated.route_instruction(task["instruction"]),
                integrated.EXPECTED_ROUTE[task["id"]],
                task["id"],
            )

    def test_each_route_publishes_only_its_required_content(self):
        append = integrated.schema_for("append", ["one", "two"])
        after = integrated.schema_for("after", ["one", "two"])
        between = integrated.schema_for("between", ["one", "two"])
        self.assertEqual(append["parameters"]["required"], ["text"])
        self.assertEqual(after["parameters"]["required"], ["text", "after"])
        self.assertEqual(
            between["parameters"]["required"], ["text", "after", "before"])
        for schema in (append, after, between):
            self.assertFalse(
                {"path", "list", "heading", "ordinal"}
                & set(schema["parameters"]["properties"]))

    def test_integrated_between_trial_validates_and_executes(self):
        task = next(
            task for task in integrated.tasks()
            if task["id"] == "add-item-ordered-renumber")
        fixture = integrated.os.path.join(integrated.ROOT, task["fixture"])
        with open(fixture, newline="") as fh:
            options = integrated.address.handles(fh.read())
        entry = options[task["target_list"]][1]
        selection = self.call_row("list_select", {
            "heading": entry["heading"], "ordinal": entry["ordinal"],
        }, "select-1")
        content = self.call_row("list_insert_between", {
            "text": "two and a half", "after": "second", "before": "third",
        }, "content-1")
        with mock.patch.object(integrated, "sample", side_effect=[
                ({"model": "test-model"}, selection),
                ({"model": "test-model"}, content)]):
            row = integrated.run_trial("unused", task, 0)

        self.assertTrue(row["address_correct"])
        self.assertEqual(row["host_route"], "between")
        self.assertTrue(row["route_correct"])
        self.assertTrue(row["anchor_validation"])
        self.assertTrue(row["structure_validated"])
        self.assertTrue(row["document_changed"])
        self.assertIsNone(row["phase_error"])
        self.assertEqual(len(row["tool_calls"]), 1)


if __name__ == "__main__":
    unittest.main()
