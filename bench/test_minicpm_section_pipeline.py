#!/usr/bin/env python3

import json
import os
import unittest
from unittest.mock import patch

import minicpm_section_pipeline as pipeline


class SectionPipelineTests(unittest.TestCase):
    def task(self, task_id):
        return next(task for task in pipeline.slots.tasks() if task["id"] == task_id)

    def content(self, task):
        with open(os.path.join(pipeline.ROOT, task["fixture"]), newline="") as fh:
            return fh.read()

    def test_dynamic_anchor_enum_contains_only_unique_outline_addresses(self):
        task = self.task("insert-nested-ratelimits")
        content = self.content(task)
        schema = pipeline.plan_schema(content)
        anchors = schema["parameters"]["properties"]["anchor"]["enum"]
        self.assertEqual(anchors, pipeline.anchor_options(content))
        self.assertIn("API", anchors)
        self.assertNotIn("macOS", anchors)
        self.assertNotIn(task["fixture"], anchors)

    def test_expected_plans_are_fixed_before_sampling(self):
        expected = {
            "insert-release-at-top": {
                "anchor": "[1.4.2] - 2026-08-14",
                "position": "before", "child_count": 1,
            },
            "insert-subsection-last": {
                "anchor": "Install", "position": "last-child", "child_count": 0,
            },
            "insert-nested-ratelimits": {
                "anchor": "API", "position": "last-child",
                "child_count": 1,
            },
            "insert-troubleshooting": {
                "anchor": "Deep heading nesting", "position": "last-child",
                "child_count": 2,
            },
        }
        self.assertEqual({
            task_id: pipeline.expected_plan(self.task(task_id))
            for task_id in expected
        }, expected)

    def test_planning_schema_exposes_no_file_or_content_fields(self):
        schema = pipeline.plan_schema(self.content(self.task("insert-subsection-last")))
        props = schema["parameters"]["properties"]
        self.assertEqual(set(props), {"anchor", "position", "child_count"})
        self.assertFalse({"path", "new_heading", "body"} & set(props))

    def test_received_count_selects_content_schema_and_structure(self):
        task = self.task("insert-subsection-last")
        plan_call = {
            "id": "plan-1", "type": "function", "function": {
                "name": "section_insert_plan",
                "arguments": json.dumps({
                    "anchor": "API",
                    "position": "after",
                    "child_count": 1,
                }),
            },
        }
        content_call = {
            "id": "content-1", "type": "function", "function": {
                "name": "section_insert_one_child",
                "arguments": json.dumps({
                    "new_heading": "New",
                    "child_1_heading": "Child",
                    "child_1_body": "Text.",
                }),
            },
        }
        responses = [
            ({"model": "test"}, {
                "tool_calls": [plan_call], "completion_tokens": 3,
                "elapsed_s": 0.1, "finish_reason": "tool_calls", "content": None,
            }),
            ({"model": "test"}, {
                "tool_calls": [content_call], "completion_tokens": 4,
                "elapsed_s": 0.2, "finish_reason": "tool_calls", "content": None,
            }),
        ]
        with patch.object(pipeline, "sample", side_effect=responses):
            row = pipeline.run_trial("unused", task, 0)
        self.assertEqual(row["content_schema_sha256"], pipeline.canonical_hash(
            pipeline.slots.schema_for_child_count(1)))
        args = json.loads(row["composed_operation"]["function"]["arguments"])
        self.assertEqual(args["path"], task["fixture"])
        self.assertEqual(args["parent"], "API")
        self.assertEqual(args["position"], "after")
        self.assertEqual(args["children"][0]["heading"], "Child")

    def test_invalid_plan_stops_before_content_sampling(self):
        task = self.task("insert-subsection-last")
        plan_call = {
            "id": "plan-1", "type": "function", "function": {
                "name": "section_insert_plan",
                "arguments": json.dumps({
                    "anchor": "Invented", "position": "last-child", "child_count": 0,
                }),
            },
        }
        response = ({"model": "test"}, {
            "tool_calls": [plan_call], "completion_tokens": 3,
            "elapsed_s": 0.1, "finish_reason": "tool_calls", "content": None,
        })
        with patch.object(pipeline, "sample", return_value=response) as sampled:
            row = pipeline.run_trial("unused", task, 0)
        self.assertEqual(sampled.call_count, 1)
        self.assertFalse(row["document_changed"])
        self.assertIn("not an existing section path", row["phase_error"])


if __name__ == "__main__":
    unittest.main()
