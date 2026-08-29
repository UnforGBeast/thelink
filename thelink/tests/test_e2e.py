# Copyright 2024 The Link Authors — Apache 2.0
"""
End-to-end tests for The Link — requires graperoot to be installed.

These tests run the full pipeline against the workspace (d:/VS/BOB)
and validate the real output format, token budget, and side-effect
suppression.

Skip gracefully when graperoot is not installed.

Run:
    python -m unittest tests.test_e2e -v
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Graperoot availability guard ──────────────────────────────────────────────

def _graperoot_available() -> bool:
    try:
        import graperoot.graph_builder  # noqa: F401
        return True
    except ImportError:
        return False

SKIP_IF_NO_GRAPEROOT = unittest.skipUnless(
    _graperoot_available(),
    "graperoot not installed — install with: pip install the-link"
)

# The workspace root (one level above thelink/)
WORKSPACE = Path(__file__).parent.parent.parent.resolve()
LINK_CMD = [sys.executable, "-m", "thelink"]


def _run_link(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run `python -m thelink <args>` and return (exit_code, stdout, stderr)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        LINK_CMD + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=cwd or str(Path(__file__).parent.parent),
    )
    return result.returncode, result.stdout, result.stderr


# ── Basic invocation ──────────────────────────────────────────────────────────

class TestE2EBasic(unittest.TestCase):

    def test_help_exits_0(self):
        code, out, _ = _run_link(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("query", out)

    def test_version_exits_0(self):
        code, out, _ = _run_link(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("1.0.0", out)

    def test_missing_query_exits_nonzero(self):
        code, _, _ = _run_link([])
        self.assertNotEqual(code, 0)

    def test_invalid_project_exits_1(self):
        code, _, err = _run_link(["test", "--project", "/no/such/path/ever"])
        self.assertEqual(code, 1)
        self.assertIn("error", err.lower())

    def test_no_traceback_on_bad_project(self):
        _, _, err = _run_link(["test", "--project", "/no/such/path/ever"])
        self.assertNotIn("Traceback", err)


# ── Full pipeline (requires graperoot) ────────────────────────────────────────

@SKIP_IF_NO_GRAPEROOT
class TestE2EPipeline(unittest.TestCase):

    def setUp(self):
        # Use a temp dir as a minimal project to keep scan fast
        self.tmpdir = tempfile.mkdtemp()
        # Write a small Python file so graperoot has something to scan
        (Path(self.tmpdir) / "main.py").write_text(
            "def authenticate(user, password):\n    return True\n",
            encoding="utf-8",
        )
        (Path(self.tmpdir) / "db.py").write_text(
            "def query(sql):\n    pass\n",
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exit_code_0(self):
        code, _, _ = _run_link([
            "Update the authentication middleware",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "graph.json"),
        ])
        self.assertEqual(code, 0)

    def test_three_section_headers_present(self):
        _, out, _ = _run_link([
            "Update the authentication middleware",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "graph.json"),
        ])
        self.assertIn("[PROJECT HISTORY]",          out)
        self.assertIn("[RELEVANT CODEBASE CONTEXT]", out)
        self.assertIn("[USER REQUEST]",              out)

    def test_query_in_user_request_section(self):
        query = "Fix the login authentication bug"
        _, out, _ = _run_link([
            query,
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "graph.json"),
        ])
        self.assertIn(query, out)

    def test_payload_within_token_budget(self):
        _, out, _ = _run_link([
            "anything",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "graph.json"),
        ])
        # PRD requirement: < 20k tokens ≈ 80,000 chars
        self.assertLessEqual(len(out), 80_000,
            f"Payload too large: {len(out)} chars (limit 80,000)")

    def test_no_traceback_on_success(self):
        _, _, err = _run_link([
            "test query",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "graph.json"),
        ])
        self.assertNotIn("Traceback", err)

    def test_stderr_lines_are_link_prefixed(self):
        _, _, err = _run_link([
            "test query",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "graph.json"),
            "--verbose",
        ])
        for line in err.splitlines():
            if line.strip():
                self.assertTrue(
                    line.startswith("[link]"),
                    f"Unexpected stderr line: {line!r}"
                )

    def test_chat_action_graph_suppressed(self):
        graph_dir = Path(self.tmpdir) / "graph_out"
        graph_dir.mkdir()
        _run_link([
            "test",
            "--project", self.tmpdir,
            "--graph-out", str(graph_dir / "info_graph.json"),
        ])
        self.assertFalse((graph_dir / "chat_action_graph.json").exists())
        self.assertFalse((graph_dir / "context-store.json").exists())

    def test_graph_file_created(self):
        graph_out = Path(self.tmpdir) / "out" / "info_graph.json"
        _run_link([
            "test",
            "--project", self.tmpdir,
            "--graph-out", str(graph_out),
        ])
        self.assertTrue(graph_out.exists(), f"info_graph.json not created at {graph_out}")

    def test_graph_file_valid_json(self):
        import json
        graph_out = Path(self.tmpdir) / "out2" / "info_graph.json"
        _run_link([
            "test",
            "--project", self.tmpdir,
            "--graph-out", str(graph_out),
        ])
        if graph_out.exists():
            data = json.loads(graph_out.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)

    def test_relevant_auth_file_in_context(self):
        _, out, _ = _run_link([
            "authenticate user password",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "g.json"),
        ])
        # The auth file we created should appear in the context section
        context_start = out.find("[RELEVANT CODEBASE CONTEXT]")
        user_request_start = out.find("[USER REQUEST]")
        context_section = out[context_start:user_request_start]
        self.assertIn("main.py", context_section)

    def test_top_n_flag_limits_files(self):
        _, out1, _ = _run_link([
            "test", "--top-n", "1",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "g1.json"),
        ])
        _, out5, _ = _run_link([
            "test", "--top-n", "5",
            "--project", self.tmpdir,
            "--graph-out", str(Path(self.tmpdir) / "g5.json"),
        ])
        # top-n=1 should have fewer file separators than top-n=5
        self.assertLessEqual(out1.count("--- "), out5.count("--- "))


# ── Workspace scan (slowest — skipped in CI unless explicitly requested) ───────

@SKIP_IF_NO_GRAPEROOT
@unittest.skipUnless(
    os.environ.get("THE_LINK_RUN_FULL_E2E") == "1",
    "Set THE_LINK_RUN_FULL_E2E=1 to run the full workspace scan test"
)
class TestE2EWorkspaceScan(unittest.TestCase):
    """Runs the full pipeline against the actual workspace (d:/VS/BOB).
    This builds a real info_graph.json across ~1800 files — takes ~10s.
    """

    def test_full_workspace_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            code, out, err = _run_link([
                "Update the authentication middleware",
                "--project", str(WORKSPACE),
                "--graph-out", str(Path(td) / "info_graph.json"),
                "--verbose",
            ])
            self.assertEqual(code, 0)
            self.assertIn("[PROJECT HISTORY]",          out)
            self.assertIn("[RELEVANT CODEBASE CONTEXT]", out)
            self.assertIn("[USER REQUEST]",              out)
            self.assertNotIn("Traceback", err)
            self.assertLessEqual(len(out), 80_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
