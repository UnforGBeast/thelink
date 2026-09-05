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

def _real_graph(files: list[dict]) -> dict:
    """Build a graph in the real graperoot shape from a compact spec.

    Each entry: ``{"path": str, "symbols": [str], "keywords": [str],
    "summary": str}`` (only ``path`` required).
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    for f in files:
        p = f["path"]
        ext = Path(p).suffix
        nodes.append({
            "id": p, "kind": "file", "path": p, "ext": ext, "size": 1,
            "keywords": list(f.get("keywords", [])),
            "content": f.get("content", ""), "summary": f.get("summary", ""),
            "file_hash": "deadbeef",
        })
        for s in f.get("symbols", []):
            sid = f"{p}::{s}"
            nodes.append({
                "id": sid, "kind": "symbol", "path": p, "ext": ext, "size": 1,
                "keywords": [], "symbol_type": "util", "name": s,
                "line_start": 1, "line_end": 1, "body_hash": "cafe",
                "confidence": "high", "exported": True,
            })
            edges.append({"from": p, "to": sid, "rel": "contains"})
    return {
        "root": "<test>",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "file_count": sum(1 for n in nodes if n["kind"] == "file"),
        "symbol_count": sum(1 for n in nodes if n["kind"] == "symbol"),
        "nodes": nodes,
        "edges": edges,
    }


class _GitDisabledMixin:
    """Neutralise the git signal so ranking assertions are independent of the
    repository the tests happen to run inside.
    """

    def setUp(self):
        super().setUp()
        self._git_patch = patch("thelink.graph.collect_git_context", return_value=None)
        self._git_patch.start()

    def tearDown(self):
        self._git_patch.stop()
        super().tearDown()


class TestExtractRelevantFiles(_GitDisabledMixin, unittest.TestCase):

    def _make_graph(self, files: list[dict]) -> dict:
        return _real_graph(files)

    def setUp(self):
        super().setUp()
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

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
        graph = _real_graph([])
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

    def test_with_signals_breakdown(self):
        graph = self._make_graph([{"path": "auth/login.py", "symbols": ["login"]}])
        results = extract_relevant_files(
            graph, "login", "", with_signals=True
        )
        self.assertIn("signals", results[0])
        self.assertEqual(
            set(results[0]["signals"]), {"bm25", "path_hit", "import_graph"}
        )
        # total score is the sum of the weighted signal contributions
        self.assertAlmostEqual(
            results[0]["score"], sum(results[0]["signals"].values())
        )

    def test_graph_hops_expands_via_import_edges(self):
        # handler imports helper; query hits only handler's symbol.
        graph = {
            "root": "<t>", "node_count": 4, "edge_count": 3,
            "file_count": 2, "symbol_count": 2,
            "nodes": [
                {"id": "handler.py", "kind": "file", "path": "handler.py", "ext": ".py",
                 "size": 1, "keywords": ["dispatch"], "content": "", "summary": "",
                 "file_hash": "a"},
                {"id": "handler.py::dispatch", "kind": "symbol", "path": "handler.py",
                 "ext": ".py", "size": 1, "keywords": [], "symbol_type": "util",
                 "name": "dispatch", "line_start": 1, "line_end": 1, "body_hash": "b",
                 "confidence": "high", "exported": True},
                {"id": "helper.py", "kind": "file", "path": "helper.py", "ext": ".py",
                 "size": 1, "keywords": ["slugify"], "content": "", "summary": "",
                 "file_hash": "c"},
                {"id": "helper.py::slugify", "kind": "symbol", "path": "helper.py",
                 "ext": ".py", "size": 1, "keywords": [], "symbol_type": "util",
                 "name": "slugify", "line_start": 1, "line_end": 1, "body_hash": "d",
                 "confidence": "high", "exported": True},
            ],
            "edges": [
                {"from": "handler.py", "to": "handler.py::dispatch", "rel": "contains"},
                {"from": "helper.py", "to": "helper.py::slugify", "rel": "contains"},
                {"from": "handler.py", "to": "helper.py", "rel": "imports"},
            ],
        }
        with_hops = extract_relevant_files(graph, "dispatch", "", graph_hops=2, with_signals=True)
        without = extract_relevant_files(graph, "dispatch", "", graph_hops=0, with_signals=True)
        helper_with = next(r for r in with_hops if r["path"] == "helper.py")
        helper_without = next(r for r in without if r["path"] == "helper.py")
        self.assertGreater(helper_with["signals"]["import_graph"], 0.0)
        self.assertEqual(helper_without["signals"]["import_graph"], 0.0)
        self.assertGreater(helper_with["score"], helper_without["score"])


# ── Legacy / non-graperoot graph shapes ─────────────────────────────────────

class TestLegacyGraphAdapter(_GitDisabledMixin, unittest.TestCase):
    """Bare {"files"/"nodes": [{"path"/"file": ..., "symbols": [...]}]} graphs —
    no "kind" field. Accepted for synthetic fixtures and non-graperoot sources.
    """

    def test_nodes_key_without_kind(self):
        graph = {"nodes": [{"path": "src/api.py", "symbols": ["get_user"]}]}
        results = extract_relevant_files(graph, "get_user", "")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "src/api.py")

    def test_file_key_in_node(self):
        graph = {"files": [{"file": "src/router.py", "symbols": ["route"]}]}
        results = extract_relevant_files(graph, "route", "")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "src/router.py")

    def test_files_key_with_symbols(self):
        graph = {"files": [
            {"path": "a/auth.py", "symbols": ["authenticate"]},
            {"path": "b/util.py", "symbols": ["noop"]},
        ]}
        results = extract_relevant_files(graph, "authenticate", "")
        self.assertEqual(results[0]["path"], "a/auth.py")


# ── info_graph.json schema conformance ───────────────────────────────────────

class TestInfoGraphSchema(unittest.TestCase):
    """Pin the committed fixture to the schema documented in
    docs/info_graph-schema.md. If graperoot's output shape changes, this
    breaks here rather than silently in retrieval.
    """

    FIXTURE = Path(__file__).parent / "fixtures" / "info_graph.sample.json"

    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(cls.FIXTURE.read_text(encoding="utf-8"))

    def test_top_level_keys(self):
        self.assertEqual(
            set(self.graph),
            {"root", "node_count", "edge_count", "file_count", "symbol_count",
             "nodes", "edges"},
        )

    def test_counts_match_lists(self):
        g = self.graph
        self.assertEqual(g["node_count"], len(g["nodes"]))
        self.assertEqual(g["edge_count"], len(g["edges"]))
        kinds = [n["kind"] for n in g["nodes"]]
        self.assertEqual(g["file_count"], kinds.count("file"))
        self.assertEqual(g["symbol_count"], kinds.count("symbol"))

    def test_single_node_list_no_files_key(self):
        # The real schema has one mixed "nodes" list, not "files"/"file_nodes".
        self.assertNotIn("files", self.graph)
        self.assertNotIn("file_nodes", self.graph)

    def test_only_file_and_symbol_kinds(self):
        self.assertEqual(
            {n["kind"] for n in self.graph["nodes"]}, {"file", "symbol"}
        )

    def test_file_node_fields(self):
        f = next(n for n in self.graph["nodes"] if n["kind"] == "file")
        self.assertEqual(
            set(f),
            {"id", "kind", "path", "ext", "size", "keywords", "content",
             "summary", "file_hash"},
        )
        self.assertIsInstance(f["keywords"], list)
        self.assertNotIn("symbols", f)
        self.assertNotIn("exports", f)

    def test_symbol_node_fields(self):
        s = next(n for n in self.graph["nodes"] if n["kind"] == "symbol")
        self.assertEqual(
            set(s),
            {"id", "kind", "path", "ext", "size", "keywords", "symbol_type",
             "name", "line_start", "line_end", "body_hash", "confidence",
             "exported"},
        )
        self.assertNotIn("content", s)
        # A symbol's path points at its parent file, not a unique location.
        self.assertTrue(any(
            n["kind"] == "file" and n["path"] == s["path"]
            for n in self.graph["nodes"]
        ))

    def test_edge_shape_and_rels(self):
        for e in self.graph["edges"]:
            self.assertEqual(set(e), {"from", "to", "rel"})
        rels = {e["rel"] for e in self.graph["edges"]}
        self.assertLessEqual(rels, {"imports", "contains"})

    def test_contains_edges_link_file_to_symbol(self):
        ids = {n["id"] for n in self.graph["nodes"]}
        for e in self.graph["edges"]:
            if e["rel"] == "contains":
                self.assertIn(e["from"], ids)
                self.assertIn(e["to"], ids)
                self.assertIn("::", e["to"])

    def test_import_targets_are_not_resolved_to_node_ids(self):
        # Documented behaviour: import targets are raw tokens (e.g. "hashlib",
        # "src.db"), not in-graph node ids. The Link must resolve them itself.
        import_targets = [e["to"] for e in self.graph["edges"] if e["rel"] == "imports"]
        self.assertIn("hashlib", import_targets)


if __name__ == "__main__":
    unittest.main(verbosity=2)
