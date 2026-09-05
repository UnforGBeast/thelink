# Copyright 2024 The Link Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
GrapeRoot semantic graph wrapper for The Link.

    build_graph(project_path, out_path) -> dict
        Builds / refreshes info_graph.json via graperoot.graph_builder.
        Raises ImportError with install instructions if graperoot is absent.
        Suppresses chat_action_graph.json and context-store.json side-effects.

    extract_relevant_files(graph, query, history, top_n=10) -> list[dict]
        Normalises the graph into scoring documents, ranks them with the
        composable scorer in ``thelink.scoring``, and returns the top-N files
        with their literal code content read from disk.

The graph schema this consumes is documented in docs/info_graph-schema.md.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from thelink.scoring import (
    DEFAULT_SIGNALS, FileDoc, ScoreContext, score_documents, tokenize,
)
from thelink.gitsignals import collect_git_context  # registers the "git" signal

logger = logging.getLogger("link.graph")

_SUPPRESS = ("chat_action_graph.json", "context-store.json")
_MAX_FILE_CHARS = 3_000


def _check_graperoot() -> None:
    """Raise ImportError with actionable message if graperoot is not installed."""
    try:
        import graperoot.graph_builder  # noqa: F401
    except ImportError:
        raise ImportError(
            "graperoot is not installed.\n"
            "Run:  pip install the-link   (or pipx install the-link)\n"
            "Both commands install graperoot automatically."
        )


def _suppress_graperoot_state(data_dir: Path) -> None:
    for name in _SUPPRESS:
        target = data_dir / name
        if target.exists():
            try:
                target.unlink()
                logger.debug("suppressed %s", target)
            except OSError as exc:
                logger.debug("could not suppress %s: %s", target, exc)


def build_graph(project_path: Path, out_path: Path) -> dict[str, Any]:
    """Build or refresh info_graph.json for *project_path*.

    Tries graperoot.graph_builder.scan() first (native Python API), then
    falls back to subprocess python -m graperoot.graph_builder.

    Raises:
        ImportError: if graperoot is not installed.
        RuntimeError: if the graph build process fails.
    """
    _check_graperoot()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    graph: dict[str, Any] | None = None

    try:
        import graperoot.graph_builder as _gb  # type: ignore[import]
        if callable(getattr(_gb, "scan", None)):
            graph = _gb.scan(root=project_path)
            out_path.write_text(
                json.dumps(graph, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("graph built via graperoot.graph_builder.scan()")
    except Exception as exc:  # noqa: BLE001
        logger.debug("scan() failed (%s), falling back to subprocess", exc)
        graph = None

    if graph is None:
        cmd = [
            sys.executable, "-m", "graperoot.graph_builder",
            "--root", str(project_path),
            "--out", str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"graperoot.graph_builder failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
        logger.debug("graph built via subprocess python -m graperoot.graph_builder")
        if not out_path.exists():
            raise RuntimeError(
                f"graperoot.graph_builder completed but {out_path} was not created."
            )
        try:
            graph = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not parse {out_path}: {exc}") from exc

    _suppress_graperoot_state(out_path.parent)

    logger.debug(
        "graph: %s files, %s symbols, %s nodes, %s edges",
        graph.get("file_count", "?"), graph.get("symbol_count", "?"),
        graph.get("node_count", "?"),  graph.get("edge_count", "?"),
    )
    return graph


# ── Legacy tokeniser ────────────────────────────────────────────────────────
# Retained for callers/tests that want the pre-1.1 set-of-tokens behaviour.
# Scoring itself uses thelink.scoring.tokenize (camelCase-aware, stemmed).

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def _tokenise(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


# ── Graph → scoring documents ───────────────────────────────────────────────
# Two input shapes are accepted:
#   * real graperoot output — one "nodes" list whose entries carry a "kind"
#     ("file" | "symbol") plus an "edges" list. This is the only shape a live
#     graperoot install produces (see docs/info_graph-schema.md).
#   * legacy/synthetic — a bare list under "files" / "nodes" / "file_nodes"
#     whose entries have "path"/"file"/"name" and optional "symbols"/"exports".
#     Used by unit-test fixtures and any non-graperoot graph source.

def _is_real_schema(graph: dict) -> bool:
    nodes = graph.get("nodes")
    return isinstance(nodes, list) and any(
        isinstance(n, dict) and "kind" in n for n in nodes
    )


def _docs_from_real_schema(graph: dict) -> list[FileDoc]:
    nodes = graph["nodes"]

    # Fold each file's child symbols (names + mined keywords) back onto the file.
    sym_by_path: dict[str, list[str]] = {}
    for n in nodes:
        if not isinstance(n, dict) or n.get("kind") != "symbol":
            continue
        bucket = sym_by_path.setdefault(str(n.get("path", "")), [])
        if n.get("name"):
            bucket.append(str(n["name"]))
        bucket.extend(str(k) for k in (n.get("keywords") or []))

    docs: list[FileDoc] = []
    for n in nodes:
        if not isinstance(n, dict) or n.get("kind") != "file":
            continue
        path = str(n.get("path", ""))
        docs.append(FileDoc(
            path=path,
            fields={
                "path": tokenize(path),
                "symbols": tokenize(" ".join(sym_by_path.get(path, ()))),
                "keywords": tokenize(" ".join(str(k) for k in (n.get("keywords") or []))),
                "summary": tokenize(str(n.get("summary", "") or "")),
            },
            raw=n,
        ))
    return docs


def _docs_from_legacy_schema(graph: dict) -> list[FileDoc]:
    nodes = None
    for key in ("files", "nodes", "file_nodes"):
        value = graph.get(key)
        if isinstance(value, list):
            nodes = value
            break
    if nodes is None:
        return []

    docs: list[FileDoc] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        path = str(n.get("path") or n.get("file") or n.get("name") or "")
        symbols = n.get("symbols") or n.get("exports") or []
        if not isinstance(symbols, list):
            symbols = [symbols]
        docs.append(FileDoc(
            path=path,
            fields={
                "path": tokenize(path),
                "symbols": tokenize(" ".join(str(s) for s in symbols)),
                "keywords": tokenize(" ".join(str(k) for k in (n.get("keywords") or []))),
                "summary": tokenize(str(n.get("summary", "") or "")),
            },
            raw=n,
        ))
    return docs


def _build_file_docs(graph: dict[str, Any]) -> list[FileDoc]:
    if not isinstance(graph, dict):
        return []
    if _is_real_schema(graph):
        return _docs_from_real_schema(graph)
    return _docs_from_legacy_schema(graph)


def _read_capped(project_path: Path, rel_path: str) -> str:
    """Read *rel_path* under *project_path*, capped at _MAX_FILE_CHARS."""
    if not rel_path:
        return ""
    abs_path = (project_path / rel_path).resolve()
    if not abs_path.is_file():
        return ""
    try:
        raw = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[unreadable: {exc}]"
    if len(raw) <= _MAX_FILE_CHARS:
        return raw
    return raw[:_MAX_FILE_CHARS] + f"\n... [{len(raw) - _MAX_FILE_CHARS} chars truncated]"


def extract_relevant_files(
    graph: dict[str, Any],
    query: str,
    history: str,
    top_n: int = 10,
    project_path: Path | None = None,
    *,
    graph_hops: int = 2,
    use_git: bool = True,
    signals: "list[str] | None" = None,
    weights: "dict[str, float] | None" = None,
    with_signals: bool = False,
) -> list[dict[str, Any]]:
    """Return the top-N most relevant files, ranked by ``thelink.scoring``.

    Args:
        graph:        Parsed info_graph.json (real graperoot or legacy shape).
        query:        The user's raw query string.
        history:      Compressed session history from crusher.crush_events().
        top_n:        Maximum number of files to return.
        project_path: Root for resolving relative file paths. Defaults to cwd.
        graph_hops:   Import-edge hops the graph-expansion pass may walk from a
                      seed file (0 disables it). Default 2.
        use_git:      If True (default), fold in local-git relevance signals
                      when *project_path* is a git repo. Never hits the network.
        signals:      Explicit signal names to run. Overrides the default set
                      (bm25, path_hit, + git when available).
        weights:      Per-signal / per-propagator weight overrides.
        with_signals: If True, each result carries a ``signals`` breakdown dict.

    Returns:
        List of dicts: ``{"path": str, "score": float, "content": str}`` — plus
        ``"signals": {name: weighted_contribution}`` when *with_signals*.
        Sorted by score descending, ties broken by path.
    """
    if project_path is None:
        project_path = Path.cwd()
    project_path = Path(project_path)

    docs = _build_file_docs(graph)
    edges = graph.get("edges") if isinstance(graph, dict) else None
    ctx = ScoreContext(
        query=query or "",
        history=history or "",
        project_path=project_path,
        edges=edges if isinstance(edges, list) else [],
    )
    ctx.extras["graph_hops"] = int(graph_hops)

    active_signals = list(signals) if signals is not None else list(DEFAULT_SIGNALS)
    if signals is None and use_git:
        git_ctx = collect_git_context(project_path)
        if git_ctx:
            ctx.extras["git"] = git_ctx
            active_signals.append("git")
            logger.debug(
                "git: %d changed, %d on branch, %d recent",
                len(git_ctx["changed"]), len(git_ctx["branch"]), len(git_ctx["recent"]),
            )

    ranked = score_documents(docs, ctx, signals=active_signals, weights=weights)

    limit = max(int(top_n), 0)
    results: list[dict[str, Any]] = []
    for sd in ranked[:limit]:
        row: dict[str, Any] = {
            "path": sd.doc.path,
            "score": sd.total,
            "content": _read_capped(project_path, sd.doc.path),
        }
        if with_signals:
            row["signals"] = sd.breakdown()
        results.append(row)
    return results
