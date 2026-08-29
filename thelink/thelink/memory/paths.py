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
#
# Derived from EGC (Extended Global Context) — original Apache 2.0 license retained.
"""
Portable path resolution for The Link runtime.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _first_env(*names: str) -> Optional[str]:
    for n in names:
        v = os.environ.get(n)
        if v and v.strip():
            return v.strip()
    return None


def home_dir() -> Path:
    """User home directory (cross-platform, honours HOME / USERPROFILE)."""
    explicit = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    return Path.home()


def project_root() -> Path:
    """The project root — resolves to cwd (no git subprocess)."""
    p = _first_env("PROJECT_ROOT", "EGC_PROJECT_ROOT", "EGC_PLUGIN_ROOT")
    if p:
        return Path(p).expanduser().resolve()
    return Path.cwd().resolve()


def egc_home() -> Path:
    """EGC home / state root. Default: ``~/.gemini`` (matches the Node runtime)."""
    v = _first_env("EGC_HOME", "ECC_HOME", "EGC_STATE_ROOT")
    if v:
        return Path(v).expanduser().resolve()
    return (home_dir() / ".gemini").resolve()


def egc_state_dir() -> Path:
    """Mutable runtime state root. Default: egc_home()."""
    v = _first_env("EGC_STATE_DIR", "ECC_STATE_DIR")
    return Path(v).expanduser().resolve() if v else egc_home()


def egc_canonical_sessions_dir() -> Path:
    """Canonical home-rooted session store: ``<state>/session-data``."""
    return egc_state_dir() / "session-data"


def egc_session_dir() -> Path:
    """Session-transcript recording directory (env-overridable)."""
    v = _first_env(
        "EGC_SESSION_RECORDING_DIR", "ECC_SESSION_RECORDING_DIR",
        "EGC_SESSION_DIR", "ECC_SESSION_DIR",
    )
    if v:
        return Path(v).expanduser().resolve()
    return Path(".sessions")


__all__ = [
    "home_dir", "project_root", "egc_home",
    "egc_state_dir", "egc_canonical_sessions_dir", "egc_session_dir",
]
