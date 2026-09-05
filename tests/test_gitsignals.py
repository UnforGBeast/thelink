# Copyright 2024 The Link Authors — Apache 2.0
"""
Tests for thelink.gitsignals — the local-git relevance signal.

Uses a throwaway git repo built with `git init`. If git is not on PATH the
whole module is skipped.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.gitsignals import collect_git_context, _signal_git
from thelink.scoring import FileDoc, ScoreContext, score_documents, tokenize


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


SKIP_NO_GIT = unittest.skipUnless(_git_available(), "git not on PATH")


def _doc(path: str) -> FileDoc:
    return FileDoc(path=path, fields={"path": tokenize(path), "symbols": [],
                                      "keywords": [], "summary": []})


def _ctx(git_ctx=None) -> ScoreContext:
    c = ScoreContext(query="", history="", project_path=Path("."))
    if git_ctx is not None:
        c.extras["git"] = git_ctx
    return c


class TestOutsideRepo(unittest.TestCase):

    def test_non_repo_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(collect_git_context(Path(td)))

    def test_signal_is_zero_without_context(self):
        self.assertEqual(_signal_git(_doc("a.py"), _ctx(None)), 0.0)


@SKIP_NO_GIT
class TestInsideRepo(unittest.TestCase):

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        self._git("config", "commit.gpgsign", "false")
        (self.repo / "core.py").write_text("def core(): return 1\n", encoding="utf-8")
        (self.repo / "helper.py").write_text("def helper(): return 2\n", encoding="utf-8")
        (self.repo / "untouched.py").write_text("x = 0\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "initial")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args],
                       capture_output=True, text=True, check=True)

    def test_collects_recent_history(self):
        ctx = collect_git_context(self.repo)
        self.assertIsNotNone(ctx)
        recent_keys = set(ctx["recent"])
        self.assertIn("core.py", recent_keys)
        self.assertIn("helper.py", recent_keys)

    def test_uncommitted_change_scores_highest(self):
        (self.repo / "core.py").write_text("def core(): return 99\n", encoding="utf-8")
        ctx = collect_git_context(self.repo)
        self.assertIn("core.py", ctx["changed"])

        score_dirty = _signal_git(_doc("core.py"), _ctx(ctx))
        score_clean = _signal_git(_doc("untouched.py"), _ctx(ctx))
        self.assertGreater(score_dirty, score_clean)

    def test_ranking_uses_git_when_available(self):
        # Make helper.py dirty; a query that matches neither file should still
        # float helper.py up via the git signal.
        (self.repo / "helper.py").write_text("def helper(): return 3\n", encoding="utf-8")
        docs = [_doc("core.py"), _doc("helper.py"), _doc("untouched.py")]
        ctx = _ctx(collect_git_context(self.repo))
        ranked = score_documents(docs, ctx, signals=("bm25", "path_hit", "git"))
        self.assertEqual(ranked[0].path, "helper.py")

    def test_cochange_with_dirty_file(self):
        # Commit core.py + helper.py together twice so they co-change, then
        # dirty only core.py. helper.py should pick up a co-change boost.
        for i in range(2):
            (self.repo / "core.py").write_text(f"def core(): return {i}\n", encoding="utf-8")
            (self.repo / "helper.py").write_text(f"def helper(): return {i}\n", encoding="utf-8")
            self._git("commit", "-aqm", f"pair {i}")
        (self.repo / "core.py").write_text("def core(): return 'dirty'\n", encoding="utf-8")
        ctx = collect_git_context(self.repo)
        self.assertIn("helper.py", ctx["cochange"])
        boost = _signal_git(_doc("helper.py"), _ctx(ctx))
        self.assertGreater(boost, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
