#!/usr/bin/env python3
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
link_cli.py — The Link Orchestrator

Single entry point for the unified context engine. Executes the four-step
pipeline and writes a structured context payload to stdout.

Pipeline:
    Ingest  → accept query + resolve project path
    Recall  → read EGC session events → Token Crusher → compressed history
    Map     → build GrapeRoot graph → score + extract relevant files
    Compile → assemble and print payload

Usage:
    python link_cli.py "<query>" [--project /path/to/repo]
                                 [--graph-out /path/to/info_graph.json]
                                 [--verbose]

Exit codes:
    0  success
    1  fatal error (graperoot not installed, invalid project path, etc.)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure src/ is on the import path when running from the thelink/ directory
_HERE = Path(__file__).parent.resolve()
_SRC = _HERE / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memory.reader import read_session_events  # noqa: E402
from crusher import crush_events               # noqa: E402
from graph import build_graph, extract_relevant_files  # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────────────
# Calm-Tech: stderr only, no colour, no emojis, no decoration.
_LOG_FORMAT = "[link] %(message)s"
logging.basicConfig(stream=sys.stderr, format=_LOG_FORMAT, level=logging.WARNING)
logger = logging.getLogger("link")


# ── Output assembly ───────────────────────────────────────────────────────────

def _format_code_chunks(files: list[dict]) -> str:
    """Format extracted file entries as labelled code blocks."""
    if not files:
        return "(no relevant files found)"
    parts: list[str] = []
    for f in files:
        path = f.get("path", "unknown")
        content = f.get("content", "")
        parts.append(f"--- {path} ---\n{content}")
    return "\n\n".join(parts)


def _build_payload(query: str, history: str, code_chunks: str) -> str:
    """Assemble the final structured payload (appflow.md Step 4 format)."""
    history_section = history.strip() or "(no session history found)"
    return (
        "[PROJECT HISTORY]\n"
        f"{history_section}\n"
        "\n"
        "[RELEVANT CODEBASE CONTEXT]\n"
        f"{code_chunks}\n"
        "\n"
        "[USER REQUEST]\n"
        f"{query}"
    )


# ── CLI entry ─────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="link_cli",
        description="The Link — unified context engine for AI coding assistants.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "query",
        help="The user's task or question to pass to the AI assistant.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Path to the target repository (default: current working directory).",
    )
    parser.add_argument(
        "--graph-out",
        default=None,
        dest="graph_out",
        help="Output path for info_graph.json (default: <project>/.dual-graph/info_graph.json).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Emit detailed operational logs to stderr.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # ── Resolve paths ─────────────────────────────────────────────────────────
    project_path = Path(args.project).resolve() if args.project else Path.cwd().resolve()
    if not project_path.is_dir():
        print(f"[link] error: project path does not exist: {project_path}", file=sys.stderr)
        return 1

    if args.graph_out:
        graph_out = Path(args.graph_out).resolve()
    else:
        graph_out = project_path / ".dual-graph" / "info_graph.json"

    # ── Step 2: Recall ────────────────────────────────────────────────────────
    logger.info("recall: reading session events from %s", project_path)
    try:
        events = read_session_events(project_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall failed: %s", exc)
        events = []

    logger.info("recall: %d events read, crushing...", len(events))
    compressed_history = crush_events(events)
    logger.info("recall: compressed to %d chars", len(compressed_history))

    # ── Step 3: Map ───────────────────────────────────────────────────────────
    logger.info("map: building semantic graph for %s", project_path)
    try:
        graph_data = build_graph(project_path, graph_out)
    except ImportError as exc:
        print(f"[link] error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"[link] error: graph build failed: {exc}", file=sys.stderr)
        return 1

    logger.info("map: extracting relevant files...")
    relevant_files = extract_relevant_files(
        graph_data,
        query=args.query,
        history=compressed_history,
        project_path=project_path,
    )
    logger.info("map: %d relevant file(s) extracted", len(relevant_files))

    # ── Step 4: Compile ───────────────────────────────────────────────────────
    logger.info("compile: assembling payload")
    code_chunks = _format_code_chunks(relevant_files)
    payload = _build_payload(args.query, compressed_history, code_chunks)

    # ── Output ────────────────────────────────────────────────────────────────
    # On Windows the default console codec (cp1252) cannot encode all Unicode
    # characters that may appear in source files. Reconfigure stdout to UTF-8
    # with replacement so the payload always writes cleanly.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print(payload)
    logger.info("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
