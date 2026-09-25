#!/usr/bin/env python3

import json
import os
import tempfile
import unittest
from types import SimpleNamespace

import armc


class ArgvTests(unittest.TestCase):
    def argv(self, subcommand, args):
        with tempfile.TemporaryDirectory() as root:
            sb = SimpleNamespace(root=os.path.realpath(root))
            return armc._argv("/bin/incise", sb, subcommand, args)

    def test_edits_receive_the_complete_argument_object(self):
        args = {
            "path": "example.md",
            "table": {"heading": "Components"},
            "values": [{"Component": "sprocket"}],
        }
        argv, refused = self.argv("table-add-row", args)
        self.assertIsNone(refused)
        self.assertIn("--args", argv)
        self.assertEqual(json.loads(argv[argv.index("--args") + 1]), args)

    def test_addressed_reads_receive_arguments(self):
        args = {"path": "example.md", "list": {"heading": "Work"}}
        argv, refused = self.argv("items", args)
        self.assertIsNone(refused)
        self.assertIn("--args", argv)

    def test_discovery_reads_do_not_invent_an_argument_flag(self):
        for subcommand in ("tables", "lists", "outline"):
            with self.subTest(subcommand=subcommand):
                argv, refused = self.argv(subcommand, {"path": "example.md"})
                self.assertIsNone(refused)
                self.assertNotIn("--args", argv)


if __name__ == "__main__":
    unittest.main()
