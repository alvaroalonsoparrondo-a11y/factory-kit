"""Tests of the lap's signal helper. Human-owned.

Run: python3 -m unittest discover -s harness/board -v
"""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import lap_signal as ls

WHEN = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


class Record(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def lines(self, ref="1.2"):
        return [json.loads(l) for l in (self.root / ".lap" / f"{ref}.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_waiting_then_working(self):
        ls.record(self.root, "1.2", "waiting", "approval", "Approve\n  the plan", now=WHEN)
        ls.record(self.root, "1.2", "working", now=WHEN)
        self.assertEqual(self.lines(), [
            {"at": "2026-11-18T10:00:00+00:00", "state": "waiting", "kind": "approval", "text": "Approve the plan"},
            {"at": "2026-11-18T10:00:00+00:00", "state": "working"},
        ])

    def test_bad_input_writes_nothing(self):
        for args in (("1.2", "waiting", "nap", "x"), ("1.2", "waiting", "approval", " "), ("1.2", "done"),
                     ("1.2", "working", "approval"), ("../x", "working"), ("", "working"), ("a/b", "working")):
            with self.assertRaises(ValueError, msg=args):
                ls.record(self.root, *args)
        self.assertFalse((self.root / ".lap").exists())

    def test_main_rejects_an_unknown_kind(self):
        with self.assertRaises(SystemExit):
            ls.main(["1.2", "paused"])
        self.assertEqual(ls.main(["1.2", "waiting", "nap", "x"]), 2)


if __name__ == "__main__":
    unittest.main()
