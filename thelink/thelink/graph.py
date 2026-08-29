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

Provides two public functions:

    build_graph(project_path, out_path) -> dict
        Builds / refreshes info_graph.json via graperoot.graph_builder.
        Raises ImportError with install instructions if graperoot is absent.
        Suppresses chat_action_graph.json and context-store.json side-effects.

    extract_relevant_files(graph, query, history, top_n=10) -> list[dict]
        Scores graph file nodes by keyword overlap and returns the top-N
        files with their literal code content read from disk.

graperoot is invoked via its Python module — no shell-outs to .sh launchers.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("link.graph")

_SUPPRESS = ("chat_action_graph.json", "context-store.json")


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


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_MAX_FILE_CHARS = 3_000


def _tokenise(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def extract_relevant_files(
    graph: dict[str, Any],
    query: str,
    history: str,
    top_n: int = 10,
    project_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return the top-N most relevant files scored against the query + history.

    Args:
        graph:        Parsed info_graph.json dict from build_graph().
        query:        The user's raw query string.
        history:      Compressed session history from crusher.crush_events().
        top_n:        Maximum number of files to return.
        project_path: Root path to resolve relative file paths. Defaults to cwd.

    Returns:
        List of dicts: ``{"path": str, "score": int, "content": str}``.
    """
    if project_path is None:
        project_path = Path.cwd()

    keywords = _tokenise(query + " " + history)

    file_nodes: list[dict] = []
    for key in ("files", "nodes", "file_nodes"):
        value = graph.get(key)
        if isinstance(value, list):
            file_nodes = value
            break
    if not file_nodes and isinstance(graph, dict):
        for v in graph.values():
            if isinstance(v, dict) and ("path" in v or "file" in v):
                file_nodes.append(v)

    scored: list[tuple[int, dict]] = []
    for node in file_nodes:
        file_path = node.get("path") or node.get("file") or node.get("name") or ""
        symbols: list[str] = node.get("symbols") or node.get("exports") or []
        symbol_text = " ".join(str(s) for s in symbols) if isinstance(symbols, list) else str(symbols)
        node_tokens = _tokenise(file_path + " " + symbol_text)
        scored.append((len(keywords & node_tokens), node))

    scored.sort(key=lambda t: (-t[0], str(t[1].get("path") or "")))

    results: list[dict[str, Any]] = []
    for score, node in scored[:top_n]:
        rel_path = node.get("path") or node.get("file") or node.get("name") or ""
        abs_path = (project_path / rel_path).resolve()
        content = ""
        if abs_path.is_file():
            try:
                raw = abs_path.read_text(encoding="utf-8", errors="replace")
                content = raw[:_MAX_FILE_CHARS]
                if len(raw) > _MAX_FILE_CHARS:
                    content += f"\n... [{len(raw) - _MAX_FILE_CHARS} chars truncated]"
            except OSError as exc:
                content = f"[unreadable: {exc}]"
        results.append({"path": rel_path, "score": score, "content": content})

    return results
