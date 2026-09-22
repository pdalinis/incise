#!/usr/bin/env python3

import json
import os
import unittest

import minicpm_list_handle as treatment


class ListHandleTests(unittest.TestCase):
    def task(self, task_id="add-item-loose"):
        return next(task for task in treatment.tasks() if task["id"] == task_id)

    def content(self, task):
        with open(os.path.join(treatment.ROOT, task["fixture"]), newline="") as fh:
            return fh.read()

    def test_handles_are_unique_and_include_all_selection_metadata(self):
        options = treatment.handles(self.content(self.task()))
        values = [value for value, _entry in options]
        self.assertEqual(len(values), len(set(values)))
        loose = values[7]
        self.assertIn('heading="Nested and mixed lists > Loose vs tight"', loose)
        self.assertIn("ordinal=1", loose)
        self.assertIn('marker="-"', loose)
        self.assertIn("spacing=loose", loose)

    def test_schema_requires_only_one_exact_handle(self):
        options = treatment.handles(self.content(self.task()))
        schema = treatment.select_schema(options)
        self.assertEqual(set(schema["parameters"]["properties"]), {"handle"})
        self.assertEqual(schema["parameters"]["required"], ["handle"])
        self.assertEqual(
            schema["parameters"]["properties"]["handle"]["enum"],
            [value for value, _entry in options])

    def test_expected_handle_comes_from_target_list(self):
        for task in treatment.tasks():
            options = treatment.handles(self.content(task))
            value, entry = options[task["target_list"]]
            ideal = task["ideal_call"]["args"]["list"]
            self.assertTrue(entry["heading"].endswith(ideal["heading"]))
            self.assertEqual(entry["ordinal"], ideal.get("ordinal", 0))
            self.assertIn(f'ordinal={entry["ordinal"]}', value)

    def test_compose_injects_selected_address_and_end_position(self):
        task = self.task("add-item-mixed-markers")
        entry = treatment.handles(self.content(task))[task["target_list"]][1]
        call, error = treatment.compose(task, entry, {"text": "second star item"})
        self.assertIsNone(error)
        args = json.loads(call["function"]["arguments"])
        self.assertEqual(args["list"]["ordinal"], 1)
        self.assertEqual(args["position"], "end")


if __name__ == "__main__":
    unittest.main()
