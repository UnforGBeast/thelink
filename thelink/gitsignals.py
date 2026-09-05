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
Git-derived relevance signals for The Link.

``collect_git_context(project_path)`` shells out to a **local** ``git`` (no
network) and summarises what the working tree and recent history say about
which files matter right now:

    changed   — paths with uncommitted modifications  (strongest)
    branch    — paths changed on this branch vs its merge-base with the
                default branch
    recent    — {path: 0..1} recency score from the last N commits
    cochange  — {path: {path: count}} co-commit counts, last N commits

Registers one composite signal, ``git``, with :func:`thelink.scoring.signal`.
Everything degrades to "no signal" (returns ``None`` / contributes ``0.0``)
when git is missing, the directory is not a repo, or a command fails.
"""
from __future__ import annotations

import logging
import subprocess
from collections import Counter
from pathlib import Path

from thelink.scoring import FileDoc, ScoreContext, signal

logger = logging.getLogger("link.git")

_LOG_LIMIT = 50           # commits to walk for recency / co-change
_MAX_FILES_PER_COMMIT = 100   # skip sprawling merge commits
_DEFAULT_BRANCHES = ("origin/HEAD", "origin/main", "origin/master", "main", "master")

# Internal sub-weights folded into the single "git" signal.
_W_CHANGED = 1.0
_W_BRANCH = 0.7
_W_RECENT = 0.6
_W_COCHANGE = 0.5


def _run_git(project_path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_path), *args],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git %s failed: %s", " ".join(args), exc)
        return None
    if result.returncode != 0:
        logger.debug("git %s exited %d: %s", " ".join(args), result.returncode,
                     result.stderr.strip())
        return None
    return result.stdout


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip().lstrip("./")


def _changed_paths(project_path: Path) -> set[str]:
    out = _run_git(project_path, "status", "--porcelain", "-z")
    if not out:
        return set()
    paths: set[str] = set()
    for entry in out.split("\0"):
        if len(entry) > 3:
            paths.add(_norm(entry[3:]))
    return paths


def _branch_paths(project_path: Path) -> set[str]:
    base = None
    for ref in _DEFAULT_BRANCHES:
        mb = _run_git(project_path, "merge-base", "HEAD", ref)
        if mb and mb.strip():
            base = mb.strip()
            break
    if not base:
        return set()
    head = _run_git(project_path, "rev-parse", "HEAD")
    if head and head.strip() == base:
        return set()  # we are on the default branch
    diff = _run_git(project_path, "diff", "--name-only", f"{base}...HEAD")
    return {_norm(l) for l in diff.splitlines() if l.strip()} if diff else set()


def _recent_and_cochange(project_path: Path) -> tuple[dict[str, float], dict[str, Counter]]:
    raw = _run_git(
        project_path, "log", f"-{_LOG_LIMIT}", "--name-only",
        "--pretty=format:%x01%H", "--no-merges",
    )
    recent: dict[str, float] = {}
    cochange: dict[str, Counter] = {}
    if not raw:
        return recent, cochange

    commits: list[list[str]] = []
    current: list[str] = []
    for line in raw.splitlines():
        if line.startswith("\x01"):
            if current:
                commits.append(current)
            current = []
        elif line.strip():
            current.append(_norm(line))
    if current:
        commits.append(current)

    n = max(len(commits), 1)
    for i, files in enumerate(commits):
        if len(files) > _MAX_FILES_PER_COMMIT:
            continue
        weight = (n - i) / n  # newest commit → ~1.0
        for f in files:
            if weight > recent.get(f, 0.0):
                recent[f] = weight
        for a in files:
            bucket = cochange.setdefault(a, Counter())
            for b in files:
                if a != b:
                    bucket[b] += 1
    return recent, cochange


def collect_git_context(project_path: Path) -> dict | None:
    """Summarise local git state for *project_path*, or ``None`` if unavailable."""
    if _run_git(project_path, "rev-parse", "--is-inside-work-tree") is None:
        return None
    changed = _changed_paths(project_path)
    branch = _branch_paths(project_path)
    recent, cochange = _recent_and_cochange(project_path)
    if not (changed or branch or recent):
        return None
    return {
        "changed": changed,
        "branch": branch,
        "recent": recent,
        "cochange": cochange,
    }


def _match(doc_path: str, keys: set[str] | dict) -> str | None:
    """Resolve a scoring doc path against git's path set (suffix-tolerant)."""
    d = _norm(doc_path)
    if d in keys:
        return d
    base = d.rsplit("/", 1)[-1]
    for k in keys:
        if k == d or k.endswith("/" + d) or d.endswith("/" + k):
            return k
    for k in keys:
        if k.rsplit("/", 1)[-1] == base:
            return k
    return None


@signal("git", weight=1.0)
def _signal_git(doc: FileDoc, ctx: ScoreContext) -> float:
    git = ctx.extras.get("git")
    if not git:
        return 0.0

    score = 0.0
    if _match(doc.path, git["changed"]):
        score += _W_CHANGED
    if _match(doc.path, git["branch"]):
        score += _W_BRANCH

    rk = _match(doc.path, git["recent"])
    if rk:
        score += _W_RECENT * git["recent"][rk]

    # Co-change with a currently-dirty file.
    ck = _match(doc.path, git["cochange"])
    if ck and git["changed"]:
        bucket = git["cochange"][ck]
        hits = sum(bucket.get(c, 0) for c in git["changed"])
        if hits:
            score += _W_COCHANGE * min(hits / 3.0, 1.0)

    return score
