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
Read-only EGC session event reader.

Scans JSONL session files from the EGC canonical session store
(~/.gemini/session-data/) and the project-local .sessions/ directory.
Returns a flat list of raw event dicts, bounded to MAX_EVENTS, sorted
newest-first by file mtime.

No session writing occurs here.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from memory.paths import egc_canonical_sessions_dir, egc_session_dir, project_root

logger = logging.getLogger("link.memory.reader")

MAX_EVENTS = 500


def read_session_events(project_path: Path | None = None) -> list[dict[str, Any]]:
    """Return up to MAX_EVENTS session events from EGC JSONL stores.

    Resolves session directories in this order:
      1. Project-local ``.sessions/`` inside *project_path* (if it exists)
      2. EGC canonical home store  ``~/.gemini/session-data/``

    Files within each directory are processed newest-first (by mtime).
    Events are appended in that order until MAX_EVENTS is reached.

    Args:
        project_path: Root of the target repository. Defaults to cwd.

    Returns:
        List of raw event dicts (may be empty if no session files exist).
    """
    if project_path is None:
        project_path = project_root()

    dirs: list[Path] = []

    # 1. Project-local .sessions/ if it already exists
    local_sessions = project_path / ".sessions"
    if local_sessions.is_dir():
        dirs.append(local_sessions)

    # 2. EGC canonical home store
    canonical = egc_canonical_sessions_dir()
    if canonical.is_dir() and canonical.resolve() not in {d.resolve() for d in dirs}:
        dirs.append(canonical)

    events: list[dict[str, Any]] = []
    for session_dir in dirs:
        jsonl_files = sorted(
            session_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for jf in jsonl_files:
            if len(events) >= MAX_EVENTS:
                break
            try:
                for line in jf.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                    if len(events) >= MAX_EVENTS:
                        break
            except OSError as exc:
                logger.debug("skipping %s: %s", jf, exc)

    logger.debug("read %d session events from %d director(y/ies)", len(events), len(dirs))
    return events
