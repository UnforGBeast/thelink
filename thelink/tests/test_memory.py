# Copyright 2024 The Link Authors — Apache 2.0
"""
Unit tests for thelink.memory — paths + reader.

Tests:
  TestPaths          — path helper functions (env overrides, defaults)
  TestReader         — read_session_events with fixture JSONL files
  TestReaderEdgeCases — malformed input, empty dirs, max-event cap
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.memory.paths import (
    home_dir,
    project_root,
    egc_home,
    egc_state_dir,
    egc_canonical_sessions_dir,
    egc_session_dir,
)
from thelink.memory.reader import read_session_events, MAX_EVENTS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _make_event(event_type: str, tool: str = "read_file") -> dict:
    return {
        "event_type": event_type,
        "timestamp": "2024-01-15T10:00:00Z",
        "data": {"tool": tool, "result": "ok"},
    }


# ── Paths ─────────────────────────────────────────────────────────────────────

class TestPaths(unittest.TestCase):

    def setUp(self):
        # Save env state
        self._saved = {k: os.environ.get(k) for k in (
            "EGC_HOME", "ECC_HOME", "EGC_STATE_ROOT",
            "EGC_STATE_DIR", "ECC_STATE_DIR",
            "EGC_SESSION_DIR", "ECC_SESSION_DIR",
            "PROJECT_ROOT", "EGC_PROJECT_ROOT",
            "HOME", "USERPROFILE",
        )}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_home_dir_returns_path(self):
        result = home_dir()
        self.assertIsInstance(result, Path)
        self.assertTrue(result.is_absolute())

    def test_egc_home_default_is_dotgemini(self):
        # Remove overrides so we get the default
        for k in ("EGC_HOME", "ECC_HOME", "EGC_STATE_ROOT"):
            os.environ.pop(k, None)
        result = egc_home()
        self.assertTrue(str(result).endswith(".gemini") or
                        str(result).endswith(".gemini/") or
                        str(result).endswith(".gemini\\"))

    def test_egc_home_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["EGC_HOME"] = td
            result = egc_home()
            self.assertEqual(result, Path(td).resolve())

    def test_egc_state_dir_falls_back_to_egc_home(self):
        os.environ.pop("EGC_STATE_DIR", None)
        os.environ.pop("ECC_STATE_DIR", None)
        self.assertEqual(egc_state_dir(), egc_home())

    def test_egc_canonical_sessions_dir_is_under_state(self):
        result = egc_canonical_sessions_dir()
        self.assertTrue(str(result).endswith("session-data") or
                        str(result).endswith("session-data\\"))

    def test_egc_session_dir_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["EGC_SESSION_DIR"] = td
            result = egc_session_dir()
            self.assertEqual(result, Path(td).resolve())

    def test_project_root_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["PROJECT_ROOT"] = td
            result = project_root()
            self.assertEqual(result, Path(td).resolve())

    def test_project_root_defaults_to_cwd(self):
        for k in ("PROJECT_ROOT", "EGC_PROJECT_ROOT", "EGC_PLUGIN_ROOT"):
            os.environ.pop(k, None)
        result = project_root()
        self.assertEqual(result, Path.cwd().resolve())


# ── Reader — basic reading ────────────────────────────────────────────────────

class TestReader(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project = Path(self.tmpdir) / "project"
        self.project.mkdir()
        # Redirect EGC canonical dir to a controlled location
        self._sessions_dir = Path(self.tmpdir) / "sessions"
        self._sessions_dir.mkdir()
        self._saved_env = os.environ.get("EGC_SESSION_DIR")
        os.environ["EGC_SESSION_DIR"] = str(self._sessions_dir)
        # Also override EGC_STATE_DIR so egc_canonical_sessions_dir points elsewhere
        self._saved_state = os.environ.get("EGC_STATE_DIR")
        os.environ["EGC_STATE_DIR"] = str(Path(self.tmpdir) / "egcstate")

    def tearDown(self):
        if self._saved_env is None:
            os.environ.pop("EGC_SESSION_DIR", None)
        else:
            os.environ["EGC_SESSION_DIR"] = self._saved_env
        if self._saved_state is None:
            os.environ.pop("EGC_STATE_DIR", None)
        else:
            os.environ["EGC_STATE_DIR"] = self._saved_state
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_empty_list_when_no_sessions(self):
        result = read_session_events(self.project)
        self.assertEqual(result, [])

    def test_reads_events_from_local_sessions(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        events = [_make_event("tool_result"), _make_event("error")]
        _write_jsonl(sessions / "test.jsonl", events)

        result = read_session_events(self.project)
        self.assertEqual(len(result), 2)

    def test_events_are_dicts(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        _write_jsonl(sessions / "x.jsonl", [_make_event("error")])
        result = read_session_events(self.project)
        for e in result:
            self.assertIsInstance(e, dict)

    def test_event_content_preserved(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        event = {"event_type": "error", "timestamp": "2024-01-01", "data": {"tool": "my_tool"}}
        _write_jsonl(sessions / "s.jsonl", [event])
        result = read_session_events(self.project)
        self.assertEqual(result[0]["event_type"], "error")
        self.assertEqual(result[0]["data"]["tool"], "my_tool")

    def test_multiple_jsonl_files_all_read(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        _write_jsonl(sessions / "a.jsonl", [_make_event("error")])
        _write_jsonl(sessions / "b.jsonl", [_make_event("tool_result")])
        result = read_session_events(self.project)
        self.assertEqual(len(result), 2)

    def test_no_local_sessions_dir_still_works(self):
        # No .sessions/ under project — should just return []
        result = read_session_events(self.project)
        self.assertIsInstance(result, list)


# ── Reader — edge cases ───────────────────────────────────────────────────────

class TestReaderEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project = Path(self.tmpdir) / "project"
        self.project.mkdir()
        self._saved_state = os.environ.get("EGC_STATE_DIR")
        os.environ["EGC_STATE_DIR"] = str(Path(self.tmpdir) / "no_such_state")

    def tearDown(self):
        if self._saved_state is None:
            os.environ.pop("EGC_STATE_DIR", None)
        else:
            os.environ["EGC_STATE_DIR"] = self._saved_state
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_skips_malformed_json_lines(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        path = sessions / "bad.jsonl"
        path.write_text('{"ok": true}\nnot json at all\n{"also": "ok"}\n', encoding="utf-8")
        result = read_session_events(self.project)
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].get("ok") or result[1].get("also"))

    def test_skips_blank_lines(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        path = sessions / "blanks.jsonl"
        path.write_text('\n\n{"event_type": "error"}\n\n', encoding="utf-8")
        result = read_session_events(self.project)
        self.assertEqual(len(result), 1)

    def test_max_events_cap_enforced(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        # Write MAX_EVENTS + 50 events across two files
        events = [_make_event("error")] * (MAX_EVENTS + 50)
        half = len(events) // 2
        _write_jsonl(sessions / "a.jsonl", events[:half])
        _write_jsonl(sessions / "b.jsonl", events[half:])
        result = read_session_events(self.project)
        self.assertLessEqual(len(result), MAX_EVENTS)

    def test_none_project_path_uses_cwd(self):
        # Should not raise
        result = read_session_events(None)
        self.assertIsInstance(result, list)

    def test_unicode_content_handled(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        event = {"event_type": "error", "data": {"result": "日本語テスト → ✓"}}
        _write_jsonl(sessions / "unicode.jsonl", [event])
        result = read_session_events(self.project)
        self.assertEqual(len(result), 1)
        self.assertIn("→", result[0]["data"]["result"])

    def test_empty_jsonl_file_handled(self):
        sessions = self.project / ".sessions"
        sessions.mkdir()
        (sessions / "empty.jsonl").write_text("", encoding="utf-8")
        result = read_session_events(self.project)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
