# Copyright 2024 The Link Authors — Apache 2.0
"""
Unit tests for thelink.graph — graph wrapper (graperoot-free).

These tests do NOT require graperoot to be installed. They cover:
  - _check_graperoot ImportError guard
  - _suppress_graperoot_state file deletion
  - extract_relevant_files scoring + ranking + disk reads

The build_graph() function requires a live graperoot install and is
covered in test_e2e.py instead.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.graph import (
    _check_graperoot,
    _suppress_graperoot_state,
    _tokenise,
    extract_relevant_files,
)


# ── _check_graperoot ──────────────────────────────────────────────────────────

class TestCheckGraperoot(unittest.TestCase):

    def test_raises_import_error_when_absent(self):
        with patch.dict("sys.modules", {"graperoot": None, "graperoot.graph_builder": None}):
            with self.assertRaises(ImportError) as ctx:
                _check_graperoot()
            self.assertIn("graperoot", str(ctx.exception).lower())
            self.assertIn("pip install", str(ctx.exception))

    def test_no_error_when_present(self):
        mock_module = MagicMock()
        with patch.dict("sys.modules", {"graperoot": mock_module, "graperoot.graph_builder": mock_module}):
            # Should not raise
            _check_graperoot()


# ── _suppress_graperoot_state ────────────────────────────────────────────────

class TestSuppressGraperoot(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deletes_chat_action_graph(self):
        f = self.tmpdir / "chat_action_graph.json"
        f.write_text("{}", encoding="utf-8")
        self.assertTrue(f.exists())
        _suppress_graperoot_state(self.tmpdir)
        self.assertFalse(f.exists())

    def test_deletes_context_store(self):
        f = self.tmpdir / "context-store.json"
        f.write_text("[]", encoding="utf-8")
        _suppress_graperoot_state(self.tmpdir)
        self.assertFalse(f.exists())

    def test_both_deleted_together(self):
        (self.tmpdir / "chat_action_graph.json").write_text("{}", encoding="utf-8")
        (self.tmpdir / "context-store.json").write_text("[]", encoding="utf-8")
        _suppress_graperoot_state(self.tmpdir)
        self.assertFalse((self.tmpdir / "chat_action_graph.json").exists())
        self.assertFalse((self.tmpdir / "context-store.json").exists())

    def test_no_error_when_files_absent(self):
        # Should not raise even if files don't exist
        _suppress_graperoot_state(self.tmpdir)

    def test_other_files_not_deleted(self):
        keeper = self.tmpdir / "info_graph.json"
        keeper.write_text("{}", encoding="utf-8")
        _suppress_graperoot_state(self.tmpdir)
        self.assertTrue(keeper.exists())


# ── _tokenise ────────────────────────────────────────────────────────────────

class TestTokenise(unittest.TestCase):

    def test_basic_split(self):
        tokens = _tokenise("hello world")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)

    def test_lowercased(self):
        tokens = _tokenise("AuthMiddleware")
        self.assertIn("authmiddleware", tokens)

    def test_punctuation_split(self):
        tokens = _tokenise("src/auth/middleware.py")
        self.assertIn("src", tokens)
        self.assertIn("auth", tokens)
        self.assertIn("middleware", tokens)
        self.assertIn("py", tokens)

    def test_empty_string(self):
        self.assertEqual(_tokenise(""), set())


# ── extract_relevant_files ────────────────────────────────────────────────────

class TestExtractRelevantFiles(unittest.TestCase):

    def _make_graph(self, files: list[dict]) -> dict:
        return {
            "file_count": len(files),
            "symbol_count": 0,
            "files": files,
        }

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── Scoring ───────────────────────────────────────────────────────────────

    def test_auth_file_ranks_first_for_auth_query(self):
        graph = self._make_graph([
            {"path": "src/auth/middleware.py", "symbols": ["authenticate", "AuthMiddleware"]},
            {"path": "src/db/models.py",       "symbols": ["User", "Session"]},
            {"path": "README.md",              "symbols": []},
        ])
        results = extract_relevant_files(graph, "Update the authentication middleware", "")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["path"], "src/auth/middleware.py")

    def test_score_is_non_negative(self):
        graph = self._make_graph([
            {"path": "src/foo.py", "symbols": ["bar"]},
        ])
        results = extract_relevant_files(graph, "something", "")
        for r in results:
            self.assertGreaterEqual(r["score"], 0)

    def test_higher_overlap_higher_score(self):
        graph = self._make_graph([
            {"path": "auth/login.py",   "symbols": ["login", "auth", "token"]},
            {"path": "utils/helper.py", "symbols": ["helper"]},
        ])
        results = extract_relevant_files(graph, "login auth token", "")
        scores = {r["path"]: r["score"] for r in results}
        self.assertGreater(scores["auth/login.py"], scores["utils/helper.py"])

    def test_history_contributes_to_scoring(self):
        graph = self._make_graph([
            {"path": "payment/stripe.py", "symbols": ["charge", "refund"]},
            {"path": "auth/login.py",     "symbols": ["login"]},
        ])
        # History mentions payment — should boost payment file
        results = extract_relevant_files(
            graph, "fix the bug",
            history="[2024-01-01] tool_result: stripe — payment charge refund"
        )
        scores = {r["path"]: r["score"] for r in results}
        self.assertGreaterEqual(scores["payment/stripe.py"], scores["auth/login.py"])

    def test_top_n_respected(self):
        files = [{"path": f"file_{i}.py", "symbols": [f"sym_{i}"]} for i in range(20)]
        graph = self._make_graph(files)
        results = extract_relevant_files(graph, "query", "", top_n=5)
        self.assertLessEqual(len(results), 5)

    def test_zero_top_n_returns_empty(self):
        graph = self._make_graph([{"path": "x.py", "symbols": []}])
        results = extract_relevant_files(graph, "query", "", top_n=0)
        self.assertEqual(results, [])

    def test_empty_graph_files_returns_empty(self):
        graph = {"file_count": 0, "files": []}
        results = extract_relevant_files(graph, "anything", "")
        self.assertEqual(results, [])

    # ── Result structure ──────────────────────────────────────────────────────

    def test_result_has_required_keys(self):
        graph = self._make_graph([{"path": "x.py", "symbols": []}])
        results = extract_relevant_files(graph, "test", "")
        for r in results:
            self.assertIn("path", r)
            self.assertIn("score", r)
            self.assertIn("content", r)

    def test_content_read_from_disk(self):
        source = self.tmpdir / "mymodule.py"
        source.write_text("def hello(): pass\n", encoding="utf-8")
        graph = self._make_graph([{"path": "mymodule.py", "symbols": ["hello"]}])
        results = extract_relevant_files(graph, "hello", "", project_path=self.tmpdir)
        self.assertEqual(len(results), 1)
        self.assertIn("def hello", results[0]["content"])

    def test_missing_file_content_is_empty_or_error_string(self):
        graph = self._make_graph([{"path": "does_not_exist.py", "symbols": []}])
        results = extract_relevant_files(graph, "test", "", project_path=self.tmpdir)
        # Content should be empty string or a readable error message — not a crash
        self.assertIsInstance(results[0]["content"], str)

    def test_content_truncated_at_3000_chars(self):
        big_file = self.tmpdir / "big.py"
        big_file.write_text("x" * 10_000, encoding="utf-8")
        graph = self._make_graph([{"path": "big.py", "symbols": []}])
        results = extract_relevant_files(graph, "x", "", project_path=self.tmpdir)
        self.assertLessEqual(len(results[0]["content"]), 3_100)  # slight buffer for truncation note

    def test_truncation_note_appended(self):
        big_file = self.tmpdir / "truncated.py"
        big_file.write_text("y" * 10_000, encoding="utf-8")
        graph = self._make_graph([{"path": "truncated.py", "symbols": []}])
        results = extract_relevant_files(graph, "y", "", project_path=self.tmpdir)
        self.assertIn("truncated", results[0]["content"])

    # ── Alternate graph schemas ───────────────────────────────────────────────

    def test_nodes_key_fallback(self):
        graph = {
            "nodes": [{"path": "src/api.py", "symbols": ["get_user"]}]
        }
        results = extract_relevant_files(graph, "get_user", "")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "src/api.py")

    def test_file_key_in_node(self):
        # Some graperoot versions use "file" instead of "path"
        graph = {
            "files": [{"file": "src/router.py", "symbols": ["route"]}]
        }
        results = extract_relevant_files(graph, "route", "")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "src/router.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
