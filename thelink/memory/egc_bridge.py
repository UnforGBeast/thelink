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
Bridge to the memory EGC actually keeps.

EGC (Extended Global Context) stores one memory document per project, the
Agent Memory Interchange document: Context, Active Decisions, Do Not Repeat,
Preferences and Next Session. It lives encrypted under the user's home and is
read through EGC's own libraries. Rather than re-implementing that layout and
its encryption here, this module finds the EGC package installed on the
machine and runs ``egc_state_reader.js`` against it with Node.

Everything degrades to ``None``: no Node, no EGC, no memory for the project,
or any failure along the way. ``THE_LINK_NO_EGC=1`` disables the bridge and
``THE_LINK_EGC_PACKAGE=<dir>`` pins the EGC package directory.

Public API:
    read_egc_state(project_path) -> dict | None
    format_egc_history(state, max_chars=12000) -> str
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("link.memory.egc")

DISABLE_ENV = "THE_LINK_NO_EGC"
PACKAGE_ENV = "THE_LINK_EGC_PACKAGE"

_READER = Path(__file__).with_name("egc_state_reader.js")
_LIB_MARKER = Path("scripts") / "lib" / "branch-state.js"
_TIMEOUT_SECONDS = 15
_DEFAULT_MAX_CHARS = 12_000


def _candidate_package_dirs() -> list[Path]:
    """Where the EGC npm package may live, most specific first."""
    explicit = os.environ.get(PACKAGE_ENV)
    if explicit:
        return [Path(explicit).expanduser()]

    candidates: list[Path] = []
    exe = shutil.which("egc")
    if exe:
        real = Path(exe).resolve()
        # POSIX: <prefix>/bin/egc is a symlink to <pkg>/scripts/egc.js.
        candidates.append(real.parent.parent)
        # Windows: <prefix>/egc.cmd is a shim next to <prefix>/node_modules.
        candidates.append(real.parent / "node_modules" / "@egchq" / "egc")

    npm = shutil.which("npm")
    if npm:
        try:
            proc = subprocess.run(
                [npm, "root", "-g"], capture_output=True, text=True,
                timeout=_TIMEOUT_SECONDS,
            )
            root = proc.stdout.strip() if proc.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("npm root -g failed: %s", exc)
            root = ""
        if root:
            candidates.append(Path(root) / "@egchq" / "egc")
    return candidates


def egc_package_dir() -> Path | None:
    """Directory of the installed EGC package, or ``None`` when not found."""
    for candidate in _candidate_package_dirs():
        if (candidate / _LIB_MARKER).is_file():
            return candidate
    return None


def read_egc_state(project_path: Path) -> dict[str, Any] | None:
    """Return EGC's memory for *project_path*, or ``None``.

    The dict carries ``source`` (``branch``, ``default-branch``, ``flat`` or
    ``none``), ``branch``, ``memory`` (the AMI document, plain text) and
    ``global`` (the user-wide appendix). ``memory`` is ``None`` when the
    project has no memory yet.
    """
    if os.environ.get(DISABLE_ENV):
        logger.debug("egc bridge disabled by %s", DISABLE_ENV)
        return None

    node = shutil.which("node")
    if not node:
        logger.debug("egc bridge: node not on PATH")
        return None

    package_dir = egc_package_dir()
    if package_dir is None:
        logger.debug("egc bridge: EGC package not found")
        return None

    try:
        proc = subprocess.run(
            [node, str(_READER), str(package_dir), str(Path(project_path))],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("egc bridge: reader failed to run: %s", exc)
        return None
    if proc.returncode != 0:
        logger.debug("egc bridge: reader exited %d: %s", proc.returncode, proc.stderr.strip())
        return None

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.debug("egc bridge: reader printed something that is not JSON")
        return None
    return data if isinstance(data, dict) else None


def format_egc_history(state: dict[str, Any] | None, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """Render the memory document and its global appendix for [PROJECT HISTORY]."""
    if not state:
        return ""
    parts: list[str] = []
    for key in ("memory", "global"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        cut = text[:max_chars]
        last_nl = cut.rfind("\n")
        text = cut[:last_nl] if last_nl > 0 else cut
    return text


__all__ = ["DISABLE_ENV", "PACKAGE_ENV", "egc_package_dir", "read_egc_state", "format_egc_history"]
