# Copyright 2024 The Link Authors - Apache 2.0
"""
Unit tests for thelink.memory.egc_bridge and its wiring into the CLI.

Tests:
  TestFormatHistory   - rendering of the memory document for [PROJECT HISTORY]
  TestPackageDir      - locating the EGC package (env pin, missing, disabled)
  TestReadState       - the Node reader against a fake EGC package (needs node)
  TestCLIRecall       - the CLI merges EGC memory and session events
"""
import io
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.memory import egc_bridge
from thelink.memory.egc_bridge import (
    DISABLE_ENV, PACKAGE_ENV, egc_package_dir, read_egc_state, format_egc_history,
)
from thelink.cli import main, _build_parser, _merge_history


MEMORY_DOC = textwrap.dedent("""\
    # Project State
    project: /home/dev/projects/orbit-tracker
    updated: 2026-01-15T12:00:00.000Z

    ## Context
    Satellite tracking dashboard in beta.

    ## Active Decisions
    - Use SQLite for the event store: zero-ops requirement on user machines

    ## Do Not Repeat
    - WebSocket reconnect without backoff: melted the server during the outage

    ## Preferences
    - Tests colocated with modules

    ## Next Session
    - Wire the alert webhook to the notification service
    """)

GLOBAL_APPENDIX = "## Global Memory (all projects)\n\n### Preferences\n- Conventional commits"

NODE = shutil.which("node")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fake_egc_package(root: Path, state_dir: Path, with_global: bool = True) -> Path:
    """A stand-in for the EGC npm package: the three libraries the reader loads."""
    pkg = root / "egc"
    lib = pkg / "scripts" / "lib"
    _write(lib / "branch-state.js", textwrap.dedent(f"""\
        'use strict';
        const fs = require('fs');
        const path = require('path');
        const STATE_DIR = {json.dumps(str(state_dir))};
        function getStateDir() {{ return STATE_DIR; }}
        function detectBranch() {{ return 'main'; }}
        function resolveStateRead(stateDir, projectPath, branch) {{
          const file = path.join(stateDir, 'state.md');
          if (fs.existsSync(file)) return {{ filePath: file, source: 'branch', branch }};
          return {{ filePath: file, source: 'none', branch }};
        }}
        module.exports = {{ getStateDir, detectBranch, resolveStateRead }};
        """))
    _write(lib / "state-crypto.js", textwrap.dedent("""\
        'use strict';
        const fs = require('fs');
        function readStateFileDecrypted(filePath) { return fs.readFileSync(filePath, 'utf8'); }
        module.exports = { readStateFileDecrypted };
        """))
    if with_global:
        _write(lib / "global-state.js", textwrap.dedent(f"""\
            'use strict';
            function readGlobalAppendix() {{ return {json.dumps(GLOBAL_APPENDIX)}; }}
            module.exports = {{ readGlobalAppendix }};
            """))
    return pkg


# ── format_egc_history ────────────────────────────────────────────────────────

class TestFormatHistory(unittest.TestCase):

    def test_none_and_empty_state_render_nothing(self):
        self.assertEqual(format_egc_history(None), "")
        self.assertEqual(format_egc_history({}), "")
        self.assertEqual(format_egc_history({"memory": None, "global": None}), "")
        self.assertEqual(format_egc_history({"memory": "   "}), "")

    def test_memory_only(self):
        out = format_egc_history({"memory": MEMORY_DOC})
        self.assertTrue(out.startswith("# Project State"))
        self.assertIn("- Use SQLite for the event store", out)
        self.assertFalse(out.endswith("\n"))

    def test_memory_then_global_appendix(self):
        out = format_egc_history({"memory": MEMORY_DOC, "global": GLOBAL_APPENDIX})
        self.assertLess(out.index("## Next Session"), out.index("## Global Memory"))
        self.assertIn("- Conventional commits", out)

    def test_cap_cuts_on_a_line_boundary(self):
        long_doc = "\n".join(f"- decision number {i}" for i in range(500))
        out = format_egc_history({"memory": long_doc}, max_chars=200)
        self.assertLessEqual(len(out), 200)
        self.assertTrue(out.endswith(tuple("0123456789")), out[-20:])


# ── egc_package_dir / read_egc_state guards ───────────────────────────────────

class TestPackageDir(unittest.TestCase):

    def test_env_pin_finds_the_package(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = _fake_egc_package(Path(td), Path(td) / "state")
            with patch.dict(os.environ, {PACKAGE_ENV: str(pkg)}):
                self.assertEqual(egc_package_dir(), pkg)

    def test_env_pin_without_libraries_is_not_a_package(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {PACKAGE_ENV: td}):
                self.assertIsNone(egc_package_dir())

    def test_no_egc_anywhere_returns_none(self):
        with patch.dict(os.environ, {PACKAGE_ENV: ""}, clear=False), \
             patch.object(egc_bridge.shutil, "which", return_value=None):
            os.environ.pop(PACKAGE_ENV, None)
            self.assertIsNone(egc_package_dir())

    def test_disable_env_short_circuits_before_any_lookup(self):
        with patch.dict(os.environ, {DISABLE_ENV: "1"}), \
             patch.object(egc_bridge.shutil, "which") as which:
            self.assertIsNone(read_egc_state(Path(".")))
            which.assert_not_called()

    def test_missing_node_returns_none(self):
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(egc_bridge.shutil, "which", return_value=None):
            os.environ.pop(DISABLE_ENV, None)
            self.assertIsNone(read_egc_state(Path(".")))


# ── The Node reader against a fake EGC package ───────────────────────────────

@unittest.skipUnless(NODE, "node is required to run the EGC reader")
class TestReadState(unittest.TestCase):

    def _read(self, pkg: Path, project: Path):
        with patch.dict(os.environ, {PACKAGE_ENV: str(pkg)}):
            os.environ.pop(DISABLE_ENV, None)
            return read_egc_state(project)

    def test_memory_and_global_appendix_are_returned(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            _write(state_dir / "state.md", MEMORY_DOC)
            pkg = _fake_egc_package(Path(td), state_dir)
            state = self._read(pkg, Path(td))
            self.assertIsNotNone(state)
            self.assertEqual(state["source"], "branch")
            self.assertEqual(state["branch"], "main")
            self.assertEqual(state["memory"], MEMORY_DOC)
            self.assertEqual(state["global"], GLOBAL_APPENDIX)

    def test_project_without_memory_reports_none_source(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = _fake_egc_package(Path(td), Path(td) / "state")
            state = self._read(pkg, Path(td))
            self.assertIsNotNone(state)
            self.assertEqual(state["source"], "none")
            self.assertIsNone(state["memory"])
            self.assertEqual(format_egc_history({"memory": None, "global": state["global"]}),
                             GLOBAL_APPENDIX)

    def test_package_without_global_state_library_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            _write(state_dir / "state.md", MEMORY_DOC)
            pkg = _fake_egc_package(Path(td), state_dir, with_global=False)
            state = self._read(pkg, Path(td))
            self.assertEqual(state["memory"], MEMORY_DOC)
            self.assertIsNone(state["global"])

    def test_reader_failure_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = _fake_egc_package(Path(td), Path(td) / "state")
            _write(pkg / "scripts" / "lib" / "state-crypto.js", "throw new Error('boom');")
            self.assertIsNone(self._read(pkg, Path(td)))

    def test_reader_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            _write(state_dir / "state.md", MEMORY_DOC)
            pkg = _fake_egc_package(Path(td), state_dir)
            before = sorted(p.relative_to(td) for p in Path(td).rglob("*"))
            self._read(pkg, Path(td))
            after = sorted(p.relative_to(td) for p in Path(td).rglob("*"))
            self.assertEqual(before, after)


# ── CLI wiring ────────────────────────────────────────────────────────────────

class TestCLIRecall(unittest.TestCase):

    MOCK_GRAPH = {
        "file_count": 1,
        "files": [{"path": "src/auth.py", "symbols": ["login"]}],
    }

    def _run(self, argv, project, egc_state, events):
        buf = io.StringIO()
        reader = MagicMock(return_value=egc_state)
        with patch("thelink.cli.build_graph", return_value=self.MOCK_GRAPH), \
             patch("thelink.cli.read_egc_state", reader), \
             patch("thelink.cli.read_session_events", return_value=events), \
             patch("sys.stdout", buf):
            code = main(argv + ["--project", project])
        return code, buf.getvalue(), reader

    def test_parser_accepts_no_egc(self):
        self.assertTrue(_build_parser().parse_args(["q", "--no-egc"]).no_egc)
        self.assertFalse(_build_parser().parse_args(["q"]).no_egc)

    def test_merge_history_orders_memory_before_events(self):
        merged = _merge_history("memory", "events")
        self.assertEqual(merged, "memory\n\n[RECENT SESSION EVENTS]\nevents")
        self.assertEqual(_merge_history("memory", ""), "memory")
        self.assertEqual(_merge_history("", "events"), "events")
        self.assertEqual(_merge_history("", ""), "")

    def test_memory_document_lands_in_project_history(self):
        with tempfile.TemporaryDirectory() as td:
            code, out, _ = self._run(["fix login"], td, {"memory": MEMORY_DOC}, [])
            self.assertEqual(code, 0)
            history = out.split("[RELEVANT CODEBASE CONTEXT]")[0]
            self.assertIn("## Active Decisions", history)
            self.assertIn("- Use SQLite for the event store", history)
            self.assertNotIn("no session history found", out)
            self.assertNotIn("[RECENT SESSION EVENTS]", out)

    def test_memory_and_events_both_present(self):
        events = [
            {"event_type": "tool_use", "timestamp": "2026-02-01T10:00:00Z",
             "data": {"tool": "shell", "input": "pytest"}},
        ]
        with tempfile.TemporaryDirectory() as td:
            _, out, _ = self._run(["fix login"], td, {"memory": MEMORY_DOC}, events)
            history = out.split("[RELEVANT CODEBASE CONTEXT]")[0]
            self.assertLess(history.index("## Next Session"), history.index("[RECENT SESSION EVENTS]"))
            self.assertIn("tool_use: shell", history)

    def test_no_egc_flag_skips_the_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            _, out, reader = self._run(["fix login", "--no-egc"], td, {"memory": MEMORY_DOC}, [])
            reader.assert_not_called()
            self.assertIn("no session history found", out)

    def test_bridge_absent_keeps_the_old_behavior(self):
        with tempfile.TemporaryDirectory() as td:
            _, out, reader = self._run(["fix login"], td, None, [])
            reader.assert_called_once()
            self.assertIn("no session history found", out)


if __name__ == "__main__":
    unittest.main()
