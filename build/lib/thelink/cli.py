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
The Link CLI — global entry point.

Installed as the ``link`` console script by pip / pipx.

Usage:
    link "<query>" [--project /path/to/repo] [--graph-out /path/to/info_graph.json]
                   [--top-n N] [--verbose]

Pipeline:
    Ingest  → accept query + resolve project path
    Recall  → read EGC session events → Token Crusher → compressed history
    Map     → build GrapeRoot graph → score + extract relevant files
    Compile → assemble and print structured payload to stdout

Exit codes:
    0  success
    1  fatal error (graperoot not installed, invalid project path, etc.)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


# ── Logging (Calm-Tech: stderr only, no colour, no decoration) ───────────────
_LOG_FORMAT = "[link] %(message)s"
logging.basicConfig(stream=sys.stderr, format=_LOG_FORMAT, level=logging.WARNING)
logger = logging.getLogger("link")


# ── Payload assembly ─────────────────────────────────────────────────────────

def _format_code_chunks(files: list[dict]) -> str:
    if not files:
        return "(no relevant files found)"
    parts = [f"--- {f.get('path', 'unknown')} ---\n{f.get('content', '')}" for f in files]
    return "\n\n".join(parts)


def _build_payload(query: str, history: str, code_chunks: str) -> str:
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


# ── Argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="link",
        description=(
            "The Link — unified context engine.\n"
            "Fuses EGC session memory with GrapeRoot's semantic graph\n"
            "to produce a token-optimised AI context payload on stdout."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  link \"Update the auth middleware\"\n"
            "  link \"Refactor payment module\" --project /my/project --verbose\n"
            "  link \"Fix the login bug\" --project . > .bob/rules/00-context.md\n"
        ),
    )
    p.add_argument("query", help="Task or question to pass to the AI assistant.")
    p.add_argument(
        "--project", "-p", default=None,
        help="Path to the target repository (default: current working directory).",
    )
    p.add_argument(
        "--graph-out", default=None, dest="graph_out",
        help="Path for info_graph.json output (default: <project>/.dual-graph/info_graph.json).",
    )
    p.add_argument(
        "--top-n", "-n", type=int, default=10, dest="top_n",
        help="Number of relevant files to include in context (default: 10).",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Emit detailed operational logs to stderr.",
    )
    p.add_argument(
        "--version", action="version",
        version="%(prog)s 1.0.0",
    )
    return p


# ── Main pipeline ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``link`` console script."""
    args = _build_parser().parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Resolve project path
    project_path = Path(args.project).resolve() if args.project else Path.cwd().resolve()
    if not project_path.is_dir():
        print(f"[link] error: project path does not exist: {project_path}", file=sys.stderr)
        return 1

    graph_out = (
        Path(args.graph_out).resolve()
        if args.graph_out
        else project_path / ".dual-graph" / "info_graph.json"
    )

    # ── Step 2: Recall ────────────────────────────────────────────────────────
    logger.info("recall: reading session events from %s", project_path)
    try:
        from thelink.memory.reader import read_session_events
        events = read_session_events(project_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("recall failed: %s", exc)
        events = []

    logger.info("recall: %d events read, crushing...", len(events))
    from thelink.crusher import crush_events
    compressed_history = crush_events(events)
    logger.info("recall: compressed to %d chars", len(compressed_history))

    # ── Step 3: Map ───────────────────────────────────────────────────────────
    logger.info("map: building semantic graph for %s", project_path)
    try:
        from thelink.graph import build_graph, extract_relevant_files
        graph_data = build_graph(project_path, graph_out)
    except ImportError as exc:
        print(f"[link] error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"[link] error: graph build failed: {exc}", file=sys.stderr)
        return 1

    logger.info("map: extracting relevant files (top %d)...", args.top_n)
    from thelink.graph import extract_relevant_files
    relevant_files = extract_relevant_files(
        graph_data,
        query=args.query,
        history=compressed_history,
        top_n=args.top_n,
        project_path=project_path,
    )
    logger.info("map: %d file(s) extracted", len(relevant_files))

    # ── Step 4: Compile ───────────────────────────────────────────────────────
    logger.info("compile: assembling payload")
    payload = _build_payload(
        args.query,
        compressed_history,
        _format_code_chunks(relevant_files),
    )

    # UTF-8 safe output (Windows cp1252 workaround)
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
