# Copyright 2024 The Link Authors — Apache 2.0
"""
Unit tests for thelink.scoring — tokenisation, BM25 index, signal registry,
and the score_documents ranking entry point.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.scoring import (
    FileDoc,
    ScoreContext,
    _Bm25Index,
    _stem,
    score_documents,
    signal,
    tokenize,
    registered_signals,
    DEFAULT_SIGNALS,
    DEFAULT_PROPAGATORS,
)


def _doc(path, *, symbols="", keywords="", summary="") -> FileDoc:
    return FileDoc(
        path=path,
        fields={
            "path": tokenize(path),
            "symbols": tokenize(symbols),
            "keywords": tokenize(keywords),
            "summary": tokenize(summary),
        },
    )


def _ctx(query, history="") -> ScoreContext:
    return ScoreContext(query=query, history=history, project_path=Path("."))


# ── tokenise ─────────────────────────────────────────────────────────────────

class TestTokenize(unittest.TestCase):

    def test_camel_case_split(self):
        self.assertEqual(tokenize("AuthMiddleware", stem=False), ["auth", "middleware"])

    def test_snake_and_path_split(self):
        toks = tokenize("src/auth/get_user.py", stem=False)
        self.assertIn("auth", toks)
        self.assertIn("get", toks)
        self.assertIn("user", toks)

    def test_stopwords_and_extensions_dropped(self):
        self.assertEqual(tokenize("the a of py js", stem=False), [])

    def test_preserves_term_frequency(self):
        self.assertEqual(tokenize("auth auth auth", stem=False), ["auth", "auth", "auth"])

    def test_stem_collapses_inflections(self):
        self.assertEqual(_stem("authenticated"), _stem("authenticating"))
        self.assertEqual(tokenize("charges")[0], tokenize("charge")[0])

    def test_short_tokens_not_stemmed(self):
        self.assertEqual(_stem("api"), "api")


# ── BM25 ─────────────────────────────────────────────────────────────────────

class TestBm25Index(unittest.TestCase):

    def test_rarer_term_scores_higher(self):
        docs = [
            _doc("common.py", symbols="widget"),
            _doc("common2.py", symbols="widget"),
            _doc("rare.py", symbols="widget flux"),
        ]
        idx = _Bm25Index.build(docs)
        # "flux" appears in 1/3 docs, "widget" in all 3 → flux has higher idf
        self.assertGreater(idx.idf["flux"], idx.idf["widget"])

    def test_prefix_expansion_matches_longer_term(self):
        docs = [_doc("a.py", symbols="authentication authorize")]
        idx = _Bm25Index.build(docs)
        expanded = dict(idx.expand(["auth"]))
        # "auth" is not literally in vocab but prefixes two vocab terms
        self.assertIn("authentication", expanded)
        self.assertEqual(expanded["authentication"], 0.5)

    def test_exact_hit_beats_prefix_hit(self):
        docs = [_doc("a.py", symbols="auth authentication")]
        idx = _Bm25Index.build(docs)
        expanded = dict(idx.expand(["auth"]))
        self.assertEqual(expanded["auth"], 1.0)

    def test_unknown_terms_dropped(self):
        docs = [_doc("a.py", symbols="alpha")]
        idx = _Bm25Index.build(docs)
        self.assertEqual(idx.expand(["zzzznope"]), [])


# ── score_documents / signals ───────────────────────────────────────────────

class TestScoreDocuments(unittest.TestCase):

    def test_ranks_relevant_doc_first(self):
        docs = [
            _doc("billing/payments.py", symbols="charge refund invoice"),
            _doc("core/utils.py", symbols="clamp debounce"),
        ]
        ranked = score_documents(docs, _ctx("refund a payment charge"))
        self.assertEqual(ranked[0].path, "billing/payments.py")

    def test_semantic_hit_beats_lexical_prefix_decoy(self):
        # 1.3 "Done when": a query term that semantically matches one file must
        # outrank a file that merely shares a leading substring.
        docs = [
            _doc("auth/session.py", symbols="authenticate authorize login logout"),
            _doc("author/bio.py",   symbols="author authorship byline"),
        ]
        ranked = score_documents(docs, _ctx("user authentication"))
        self.assertEqual(ranked[0].path, "auth/session.py")

    def test_history_weighted_below_query(self):
        docs = [
            _doc("a.py", symbols="alpha"),
            _doc("b.py", symbols="beta"),
        ]
        q_rank = score_documents(docs, _ctx("alpha"))
        h_rank = score_documents(docs, _ctx("unrelated", history="alpha"))
        a_from_query = next(s for s in q_rank if s.path == "a.py").total
        a_from_history = next(s for s in h_rank if s.path == "a.py").total
        self.assertGreater(a_from_query, a_from_history)
        self.assertGreater(a_from_history, 0.0)

    def test_total_is_sum_of_weighted_signals(self):
        docs = [_doc("auth.py", symbols="login")]
        ranked = score_documents(docs, _ctx("login"))
        sd = ranked[0]
        self.assertAlmostEqual(sd.total, sum(s.weighted for s in sd.signals))

    def test_zero_weight_skips_signal(self):
        docs = [_doc("auth.py", symbols="login")]
        ranked = score_documents(
            docs, _ctx("login"), weights={"path_hit": 0, "import_graph": 0}
        )
        self.assertEqual({s.name for s in ranked[0].signals}, {"bm25"})

    def test_deterministic_tie_break_on_path(self):
        docs = [_doc("z.py"), _doc("a.py"), _doc("m.py")]
        ranked = score_documents(docs, _ctx("nomatch"))
        self.assertEqual([s.path for s in ranked], ["a.py", "m.py", "z.py"])

    def test_new_signal_via_registry_only(self):
        # 1.1 "Done when": a new signal can be added without touching
        # score_documents or extract_relevant_files.
        @signal("only_dunder_main", weight=10.0)
        def _s(doc, ctx):
            return 1.0 if doc.path.endswith("__main__.py") else 0.0

        try:
            docs = [_doc("pkg/__main__.py"), _doc("pkg/helpers.py")]
            ranked = score_documents(
                docs, _ctx("nomatch"),
                signals=("bm25", "path_hit", "only_dunder_main"),
            )
            self.assertEqual(ranked[0].path, "pkg/__main__.py")
            self.assertIn("only_dunder_main", ranked[0].breakdown())
            self.assertEqual(ranked[0].total, 10.0)
        finally:
            from thelink import scoring
            scoring._REGISTRY.pop("only_dunder_main", None)

    def test_default_signals_registered(self):
        reg = registered_signals()
        for name in DEFAULT_SIGNALS:
            self.assertIn(name, reg)


# ── import-graph expansion (propagator) ─────────────────────────────────────

class TestImportGraphExpansion(unittest.TestCase):

    def _ctx_with_edges(self, query, edges, hops=2):
        c = ScoreContext(query=query, history="", project_path=Path("."), edges=edges)
        c.extras["graph_hops"] = hops
        return c

    def test_callee_surfaces_from_caller_only_query(self):
        # Query names a symbol that lives only in the CALLER. The callee shares
        # no query terms but is one import hop away — it must gain a score.
        docs = [
            _doc("app/handler.py", symbols="handle_request dispatch"),
            _doc("app/tokenizer.py", symbols="tokenize normalize"),
        ]
        edges = [{"from": "app/handler.py", "to": "app/tokenizer.py", "rel": "imports"}]
        ranked = score_documents(docs, self._ctx_with_edges("handle_request dispatch", edges))
        by_path = {sd.path: sd for sd in ranked}
        callee = by_path["app/tokenizer.py"]
        ig = next(s for s in callee.signals if s.name == "import_graph")
        self.assertGreater(ig.weighted, 0.0)
        self.assertGreater(callee.total, 0.0)

    def test_hop_count_is_configurable(self):
        # a -> b -> c ; query only hits a. c is 2 hops out.
        docs = [_doc("a.py", symbols="alpha"), _doc("b.py", symbols="beta"), _doc("c.py", symbols="gamma")]
        edges = [
            {"from": "a.py", "to": "b.py", "rel": "imports"},
            {"from": "b.py", "to": "c.py", "rel": "imports"},
        ]
        r1 = {sd.path: sd for sd in score_documents(docs, self._ctx_with_edges("alpha", edges, hops=1))}
        r2 = {sd.path: sd for sd in score_documents(docs, self._ctx_with_edges("alpha", edges, hops=2))}

        def ig(sd):
            return next(s.weighted for s in sd.signals if s.name == "import_graph")

        self.assertEqual(ig(r1["c.py"]), 0.0)      # out of reach at hops=1
        self.assertGreater(ig(r2["c.py"]), 0.0)    # reachable at hops=2
        self.assertGreater(ig(r2["b.py"]), ig(r2["c.py"]))  # nearer hop scores higher

    def test_hops_zero_disables_expansion(self):
        docs = [_doc("a.py", symbols="alpha"), _doc("b.py", symbols="beta")]
        edges = [{"from": "a.py", "to": "b.py", "rel": "imports"}]
        ranked = {sd.path: sd for sd in score_documents(docs, self._ctx_with_edges("alpha", edges, hops=0))}
        ig_b = next(s.weighted for s in ranked["b.py"].signals if s.name == "import_graph")
        self.assertEqual(ig_b, 0.0)

    def test_no_edges_no_boost(self):
        docs = [_doc("a.py", symbols="alpha"), _doc("b.py", symbols="beta")]
        ranked = score_documents(docs, self._ctx_with_edges("alpha", []))
        for sd in ranked:
            ig = next(s.weighted for s in sd.signals if s.name == "import_graph")
            self.assertEqual(ig, 0.0)

    def test_dotted_module_target_resolves(self):
        docs = [_doc("pkg/api.py", symbols="serve"), _doc("pkg/db.py", symbols="connect")]
        edges = [{"from": "pkg/api.py", "to": "pkg.db", "rel": "imports"}]
        ranked = {sd.path: sd for sd in score_documents(docs, self._ctx_with_edges("serve", edges))}
        ig_db = next(s.weighted for s in ranked["pkg/db.py"].signals if s.name == "import_graph")
        self.assertGreater(ig_db, 0.0)

    def test_import_graph_is_default_propagator(self):
        self.assertIn("import_graph", DEFAULT_PROPAGATORS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
