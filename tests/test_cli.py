# Copyright 2024 The Link Authors — Apache 2.0
"""
CLI integration tests for thelink.cli.main().

Tests the CLI via its Python entry point (main(argv=[...])), avoiding
subprocess overhead while still covering argument parsing, error paths,
and output assembly.

Tests:
  TestArgParser      — argument parsing edge cases
  TestCLIRecall      — Recall step (memory mocked)
  TestCLIMap         — Map step (graperoot mocked)
  TestCLIOutput      — Payload format and stdout
  TestCLIErrors      — Error paths and exit codes
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.cli import (
    main, _build_parser, _format_code_chunks, _build_payload, _explain_lines,
)


# ── _build_parser ─────────────────────────────────────────────────────────────

class TestArgParser(unittest.TestCase):

    def _parse(self, args: list[str]):
        return _build_parser().parse_args(args)

    def test_query_required(self):
        with self.assertRaises(SystemExit):
            self._parse([])

    def test_query_positional(self):
        args = self._parse(["my query"])
        self.assertEqual(args.query, "my query")

    def test_project_flag(self):
        args = self._parse(["q", "--project", "/some/path"])
        self.assertEqual(args.project, "/some/path")

    def test_project_short_flag(self):
        args = self._parse(["q", "-p", "/path"])
        self.assertEqual(args.project, "/path")

    def test_top_n_default_is_10(self):
        args = self._parse(["q"])
        self.assertEqual(args.top_n, 10)

    def test_top_n_custom(self):
        args = self._parse(["q", "--top-n", "20"])
        self.assertEqual(args.top_n, 20)

    def test_top_n_short(self):
        args = self._parse(["q", "-n", "5"])
        self.assertEqual(args.top_n, 5)

    def test_verbose_default_false(self):
        args = self._parse(["q"])
        self.assertFalse(args.verbose)

    def test_verbose_flag(self):
        args = self._parse(["q", "--verbose"])
        self.assertTrue(args.verbose)

    def test_verbose_short_flag(self):
        args = self._parse(["q", "-v"])
        self.assertTrue(args.verbose)

    def test_graph_out_flag(self):
        args = self._parse(["q", "--graph-out", "/tmp/graph.json"])
        self.assertEqual(args.graph_out, "/tmp/graph.json")

    def test_version_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            self._parse(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_explain_default_false(self):
        self.assertFalse(self._parse(["q"]).explain)

    def test_explain_flag(self):
        self.assertTrue(self._parse(["q", "--explain"]).explain)

    def test_explain_short_flag(self):
        self.assertTrue(self._parse(["q", "-e"]).explain)


# ── Payload helpers ───────────────────────────────────────────────────────────

class TestPayloadHelpers(unittest.TestCase):

    def test_format_code_chunks_empty(self):
        result = _format_code_chunks([])
        self.assertIn("no relevant files", result)

    def test_format_code_chunks_one_file(self):
        files = [{"path": "src/auth.py", "score": 5, "content": "def login(): pass"}]
        result = _format_code_chunks(files)
        self.assertIn("src/auth.py", result)
        self.assertIn("def login", result)

    def test_format_code_chunks_multiple_files(self):
        files = [
            {"path": "a.py", "score": 5, "content": "# a"},
            {"path": "b.py", "score": 3, "content": "# b"},
        ]
        result = _format_code_chunks(files)
        self.assertIn("a.py", result)
        self.assertIn("b.py", result)

    def test_build_payload_sections_present(self):
        payload = _build_payload("my query", "some history", "some code")
        self.assertIn("[PROJECT HISTORY]", payload)
        self.assertIn("[RELEVANT CODEBASE CONTEXT]", payload)
        self.assertIn("[USER REQUEST]", payload)

    def test_build_payload_query_in_output(self):
        payload = _build_payload("fix the login bug", "", "")
        self.assertIn("fix the login bug", payload)

    def test_build_payload_empty_history_fallback(self):
        payload = _build_payload("q", "", "code")
        self.assertIn("no session history found", payload)

    def test_build_payload_history_in_output(self):
        payload = _build_payload("q", "past decisions here", "code")
        self.assertIn("past decisions here", payload)


# ── --explain rendering ──────────────────────────────────────────────────────

class TestExplainLines(unittest.TestCase):

    def test_empty_files(self):
        lines = _explain_lines([])
        self.assertEqual(len(lines), 1)
        self.assertIn("no files", lines[0])

    def test_header_lists_signal_names(self):
        files = [
            {"path": "a.py", "score": 3.5, "signals": {"bm25": 2.0, "path_hit": 1.5}},
            {"path": "b.py", "score": 0.0, "signals": {"bm25": 0.0, "path_hit": 0.0}},
        ]
        lines = _explain_lines(files)
        self.assertIn("bm25", lines[0])
        self.assertIn("path_hit", lines[0])
        # one summary line + header row + one row per file
        self.assertEqual(len(lines), 1 + 1 + 2)
        self.assertIn("a.py", lines[-2])
        self.assertIn("b.py", lines[-1])

    def test_rows_show_per_signal_values(self):
        files = [{"path": "x.py", "score": 2.0, "signals": {"bm25": 2.0, "path_hit": 0.0}}]
        body = "\n".join(_explain_lines(files))
        self.assertIn("2.00", body)


class TestExplainIntegration(unittest.TestCase):

    MOCK_GRAPH = {
        "file_count": 2,
        "files": [
            {"path": "src/auth.py", "symbols": ["login", "authenticate"]},
            {"path": "src/db.py",   "symbols": ["query"]},
        ],
    }

    def _run(self, argv, project):
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with patch("thelink.cli.build_graph", return_value=self.MOCK_GRAPH), \
             patch("thelink.cli.read_session_events", return_value=[]), \
             patch("sys.stdout", out_buf), patch("sys.stderr", err_buf):
            code = main(argv + ["--project", project])
        return code, out_buf.getvalue(), err_buf.getvalue()

    def test_stdout_byte_identical_with_and_without_explain(self):
        with tempfile.TemporaryDirectory() as td:
            _, out_plain, _ = self._run(["update auth"], td)
            _, out_explain, err_explain = self._run(["update auth", "--explain"], td)
            self.assertEqual(out_plain, out_explain)
            self.assertIn("explain:", err_explain)

    def test_explain_stderr_all_link_prefixed(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, err = self._run(["authenticate login", "--explain"], td)
            for line in err.splitlines():
                if line.strip():
                    self.assertTrue(line.startswith("[link]"), repr(line))

    def test_explain_names_the_top_file(self):
        with tempfile.TemporaryDirectory() as td:
            _, _, err = self._run(["authenticate login token", "--explain"], td)
            # auth.py has the matching symbols, so it should head the table
            first_row = [l for l in err.splitlines() if l.startswith("[link]") and "src/" in l][0]
            self.assertIn("src/auth.py", first_row)


# ── CLI via main() — error paths ──────────────────────────────────────────────

class TestCLIErrors(unittest.TestCase):

    def test_invalid_project_path_exits_1(self):
        code = main(["my query", "--project", "/this/path/does/not/exist/ever"])
        self.assertEqual(code, 1)

    def test_graperoot_missing_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict("sys.modules", {
                "graperoot": None,
                "graperoot.graph_builder": None,
            }):
                # Patch build_graph to raise ImportError (simulating absent graperoot)
                with patch("thelink.cli.build_graph", side_effect=ImportError("graperoot not installed")):
                    with patch("thelink.cli.read_session_events", return_value=[]):
                        code = main(["my query", "--project", td])
                        self.assertEqual(code, 1)

    def test_graph_build_failure_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("thelink.cli.build_graph", side_effect=RuntimeError("scan failed")):
                with patch("thelink.cli.read_session_events", return_value=[]):
                    code = main(["my query", "--project", td])
                    self.assertEqual(code, 1)


# ── CLI via main() — success path ─────────────────────────────────────────────

class TestCLISuccess(unittest.TestCase):

    MOCK_GRAPH = {
        "file_count": 2,
        "files": [
            {"path": "src/auth.py", "symbols": ["login", "authenticate"]},
            {"path": "src/db.py",   "symbols": ["query"]},
        ],
    }

    def _run_with_mocks(self, argv: list[str], project: str) -> tuple[int, str]:
        """Run main() with graperoot mocked, capture stdout."""
        buf = io.StringIO()
        with patch("thelink.cli.build_graph", return_value=self.MOCK_GRAPH), \
             patch("thelink.cli.read_session_events", return_value=[]), \
             patch("sys.stdout", buf):
            code = main(argv + ["--project", project])
        return code, buf.getvalue()

    def test_exit_code_0_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            code, _ = self._run_with_mocks(["update auth"], td)
            self.assertEqual(code, 0)

    def test_stdout_contains_all_three_sections(self):
        with tempfile.TemporaryDirectory() as td:
            _, output = self._run_with_mocks(["update auth middleware"], td)
            self.assertIn("[PROJECT HISTORY]", output)
            self.assertIn("[RELEVANT CODEBASE CONTEXT]", output)
            self.assertIn("[USER REQUEST]", output)

    def test_query_appears_in_user_request_section(self):
        with tempfile.TemporaryDirectory() as td:
            _, output = self._run_with_mocks(["fix the payment bug"], td)
            self.assertIn("fix the payment bug", output)

    def test_no_session_history_shows_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            _, output = self._run_with_mocks(["test query"], td)
            self.assertIn("no session history found", output)

    def test_top_n_limits_files_in_output(self):
        with tempfile.TemporaryDirectory() as td:
            _, output = self._run_with_mocks(["query", "--top-n", "1"], td)
            # Only 1 file separator should appear
            separator_count = output.count("--- ")
            self.assertLessEqual(separator_count, 1)

    def test_default_graph_out_under_dual_graph(self):
        with tempfile.TemporaryDirectory() as td:
            captured_out_path = []

            def mock_build(project_path, out_path):
                captured_out_path.append(out_path)
                return self.MOCK_GRAPH

            with patch("thelink.cli.build_graph", side_effect=mock_build), \
                 patch("thelink.cli.read_session_events", return_value=[]):
                main(["query", "--project", td])

            self.assertTrue(
                str(captured_out_path[0]).endswith("info_graph.json"),
                f"Expected .../info_graph.json, got {captured_out_path[0]}"
            )
            self.assertIn(".dual-graph", str(captured_out_path[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
