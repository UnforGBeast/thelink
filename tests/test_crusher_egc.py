# Copyright 2024 The Link Authors - Apache 2.0
"""
Tests for the EGC passthrough in thelink.crusher: when `egc` is on PATH the
row reduction goes through EGC's own Token Crusher (`egc run`); otherwise,
or on any failure, the Python port takes over.

Tests:
  TestParseReduced   - reading the rows back out of `egc run` output
  TestPassthrough    - a fake `egc` on PATH, and every fallback path
"""
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.crusher import (
    DISABLE_ENV, _MAX_ROWS, _parse_reduced, _reduce_rows_via_egc, crush_events,
)


def _events(n: int) -> list[dict]:
    return [
        {"event_type": "tool_use", "timestamp": f"2026-02-{i + 1:02d}T10:00:00Z",
         "data": {"tool": f"tool_{i}", "input": f"payload {i}"}}
        for i in range(n)
    ]


FAKE_EGC = textwrap.dedent("""\
    import json, os, sys
    # Emulates `egc run <python> -c <code> <file>`: crush the JSON array in
    # <file> the way EGC prints it, or misbehave according to FAKE_EGC_MODE.
    mode = os.environ.get("FAKE_EGC_MODE", "reduce")
    marker = os.environ.get("FAKE_EGC_MARKER")
    if marker:
        open(marker, "w").write("called")
    if mode == "fail":
        sys.stderr.write("boom\\n")
        sys.exit(1)
    rows = json.load(open(sys.argv[-1], encoding="utf-8"))
    if mode == "passthrough":
        sys.stdout.write(json.dumps(rows))
        sys.exit(0)
    if mode == "garbage":
        sys.stdout.write("not json at all")
        sys.exit(0)
    kept = rows[:3]
    sys.stdout.write(json.dumps(kept, indent=2))
    sys.stdout.write(f"\\n({len(rows)} rows reduced to {len(kept)})\\n")
    sys.stdout.write("[egc crushed] saved ~42 tokens (full output: rerun with --raw)\\n")
    """)


class _FakeEgc:
    """A fake `egc` executable at the front of PATH, cross-platform."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.script = self.dir / "fake_egc.py"
        self.script.write_text(FAKE_EGC, encoding="utf-8")
        self.marker = self.dir / "called.txt"
        if os.name == "nt":
            (self.dir / "egc.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "{self.script}" %*\r\n', encoding="utf-8")
        else:
            launcher = self.dir / "egc"
            launcher.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "{self.script}" "$@"\n', encoding="utf-8")
            launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def env(self, mode: str = "reduce") -> dict:
        return {
            "PATH": str(self.dir) + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_EGC_MODE": mode,
            "FAKE_EGC_MARKER": str(self.marker),
        }

    @property
    def called(self) -> bool:
        return self.marker.exists()

    def cleanup(self) -> None:
        self._tmp.cleanup()


class TestParseReduced(unittest.TestCase):

    def test_reads_the_leading_json_and_ignores_the_trailer(self):
        out = json.dumps([{"a": 1}, {"a": 2}], indent=2) + "\n(12 rows reduced to 2)\n[egc crushed] saved ~10 tokens\n"
        self.assertEqual(_parse_reduced(out, 12), [{"a": 1}, {"a": 2}])

    def test_untouched_payload_is_none(self):
        rows = [{"a": i} for i in range(6)]
        self.assertIsNone(_parse_reduced(json.dumps(rows), 6))

    def test_non_list_or_non_dict_rows_are_none(self):
        self.assertIsNone(_parse_reduced('{"a": 1}', 6))
        self.assertIsNone(_parse_reduced("[1, 2, 3]", 6))
        self.assertIsNone(_parse_reduced("[]", 6))

    def test_garbage_is_none(self):
        self.assertIsNone(_parse_reduced("not json", 6))
        self.assertIsNone(_parse_reduced("", 6))


class TestPassthrough(unittest.TestCase):

    def setUp(self):
        self.fake = _FakeEgc()
        self.addCleanup(self.fake.cleanup)
        # Never let the real environment decide these tests.
        os.environ.pop(DISABLE_ENV, None)

    def test_rows_come_from_egc_when_it_is_on_path(self):
        with patch.dict(os.environ, self.fake.env("reduce")):
            reduced = _reduce_rows_via_egc(_events(12))
        self.assertTrue(self.fake.called)
        self.assertEqual(len(reduced), 3)
        self.assertEqual(reduced[0]["data"]["tool"], "tool_0")

    def test_crush_events_uses_egc_reduction(self):
        with patch.dict(os.environ, self.fake.env("reduce")):
            out = crush_events(_events(12))
        self.assertEqual(len(out.splitlines()), 3)
        self.assertIn("tool_2", out)
        self.assertNotIn("tool_11", out)

    def test_egc_failure_falls_back_to_the_port(self):
        with patch.dict(os.environ, self.fake.env("fail")):
            out = crush_events(_events(12))
        self.assertTrue(self.fake.called)
        self.assertEqual(len(out.splitlines()), _MAX_ROWS)

    def test_untouched_payload_falls_back_to_the_port(self):
        with patch.dict(os.environ, self.fake.env("passthrough")):
            out = crush_events(_events(12))
        self.assertEqual(len(out.splitlines()), _MAX_ROWS)

    def test_garbage_output_falls_back_to_the_port(self):
        with patch.dict(os.environ, self.fake.env("garbage")):
            out = crush_events(_events(12))
        self.assertEqual(len(out.splitlines()), _MAX_ROWS)

    def test_disable_env_skips_egc_entirely(self):
        with patch.dict(os.environ, {**self.fake.env("reduce"), DISABLE_ENV: "1"}):
            out = crush_events(_events(12))
        self.assertFalse(self.fake.called)
        self.assertEqual(len(out.splitlines()), _MAX_ROWS)

    def test_use_egc_false_skips_egc_entirely(self):
        with patch.dict(os.environ, self.fake.env("reduce")):
            out = crush_events(_events(12), use_egc=False)
        self.assertFalse(self.fake.called)
        self.assertEqual(len(out.splitlines()), _MAX_ROWS)

    def test_too_few_rows_never_call_egc(self):
        with patch.dict(os.environ, self.fake.env("reduce")):
            out = crush_events(_events(3))
        self.assertFalse(self.fake.called)
        self.assertEqual(len(out.splitlines()), 3)

    def test_no_egc_on_path_uses_the_port(self):
        with patch.dict(os.environ, {"PATH": str(self.fake.dir / "nowhere")}):
            out = crush_events(_events(12))
        self.assertFalse(self.fake.called)
        self.assertEqual(len(out.splitlines()), _MAX_ROWS)

    def test_temporary_payload_file_is_removed(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.dict(os.environ, {**self.fake.env("reduce"), "TMPDIR": td, "TMP": td, "TEMP": td}):
            tempfile.tempdir = None
            try:
                _reduce_rows_via_egc(_events(12))
                leftovers = [p for p in Path(td).iterdir() if p.suffix == ".json"]
            finally:
                tempfile.tempdir = None
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
