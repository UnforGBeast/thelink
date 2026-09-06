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
# Token Crusher — Python port of EGC's egc-array-crusher.ts (Apache 2.0).
"""
Token Crusher — compresses EGC session events into a compact history string.

When the ``egc`` CLI is on PATH, the row reduction is delegated to EGC's own
Token Crusher through ``egc run``, so the events go through the original
implementation and the savings land in the user's ``egc gain`` ledger. The
Python port below is the fallback: no ``egc``, ``THE_LINK_NO_EGC=1``, a
timeout, or a payload EGC leaves untouched all end up here.

The port mirrors EGC's TypeScript egc-array-crusher.ts:
  - Column-cardinality analysis (VARIANCE_THRESHOLD = 0.15)
  - Row deduplication by signature
  - Head + tail cap at MAX_ROWS_AFTER_CRUSH = 10
  - Observable event-type filter
  - Character budget enforcement

Public API:
    crush_events(events, max_chars=8000, use_egc=True) -> str
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any

logger = logging.getLogger("link.crusher")

DISABLE_ENV = "THE_LINK_NO_EGC"

_MIN_ROWS = 5
_MAX_ROWS = 10
_VARIANCE_THRESHOLD = 0.15

_EGC_TIMEOUT_SECONDS = 20
# `egc run` executes a command and crushes its stdout; this one-liner just
# emits the JSON payload written to a temporary file, portably, without a
# shell. EGC detects the JSON array by shape and applies its array crusher.
_EMIT_FILE = "import sys; sys.stdout.write(open(sys.argv[1], encoding='utf-8').read())"

_OBSERVABLE = frozenset({
    "veto", "mutation", "post_tool", "tool_result", "tool_use",
    "error", "failure", "retry", "correction", "governance",
})


def _to_key(v: Any) -> str:
    if v is None:
        return "__null__"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    return str(v)


def _column_cardinality(rows: list[dict], key: str) -> float:
    if not rows:
        return 0.0
    return len({_to_key(row.get(key)) for row in rows}) / len(rows)


def _row_signature(row: dict, keys: list[str]) -> str:
    return "|".join(_to_key(row.get(k))[:32] for k in keys)


def _reduce_rows(rows: list[dict]) -> list[dict] | None:
    if len(rows) < _MIN_ROWS:
        return None
    all_keys = list(dict.fromkeys(k for row in rows for k in row))
    important_keys = [k for k in all_keys if _column_cardinality(rows, k) >= _VARIANCE_THRESHOLD]
    score_keys = important_keys if important_keys else all_keys
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        sig = _row_signature(row, score_keys)
        if sig not in seen:
            seen.add(sig)
            unique.append(row)
    if len(unique) > _MAX_ROWS:
        head_size = _MAX_ROWS // 2
        unique = unique[:head_size] + unique[-(  _MAX_ROWS - head_size):]
    return unique if len(unique) < len(rows) else None


def _parse_reduced(stdout: str, original_count: int) -> list[dict] | None:
    """Rows EGC printed, or None when it left the payload alone.

    ``egc run`` prints the reduced JSON array followed by its own trailer lines
    (row counts, savings marker); only the leading JSON value is read. A
    payload below EGC's size threshold comes back unchanged, which also means
    "nothing to use here".
    """
    try:
        value, _ = json.JSONDecoder().raw_decode(stdout.lstrip())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(row, dict) for row in value):
        return None
    if len(value) >= original_count:
        return None
    return value


def _reduce_rows_via_egc(rows: list[dict]) -> list[dict] | None:
    """Run EGC's original Token Crusher over *rows* through ``egc run``.

    Returns the reduced rows, or None whenever the port should take over:
    EGC absent or disabled, too few rows, a failure or timeout, or a payload
    EGC did not reduce.
    """
    if os.environ.get(DISABLE_ENV) or len(rows) < _MIN_ROWS:
        return None
    egc = shutil.which("egc")
    python = sys.executable
    if not egc or not python:
        return None

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", encoding="utf-8", delete=False,
    ) as handle:
        json.dump(rows, handle, ensure_ascii=False)
        payload_path = handle.name
    try:
        proc = subprocess.run(
            [egc, "run", python, "-c", _EMIT_FILE, payload_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_EGC_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("egc run failed: %s", exc)
        return None
    finally:
        try:
            os.unlink(payload_path)
        except OSError:
            pass

    if proc.returncode != 0:
        logger.debug("egc run exited %d: %s", proc.returncode, proc.stderr.strip()[:200])
        return None
    reduced = _parse_reduced(proc.stdout, len(rows))
    if reduced is not None:
        logger.debug("rows reduced by EGC's Token Crusher: %d -> %d", len(rows), len(reduced))
    return reduced


def crush_events(
    events: list[dict[str, Any]], max_chars: int = 8_000, *, use_egc: bool = True,
) -> str:
    """Compress EGC session events into a token-efficient history string.

    Steps:
      1. Filter to observable event types only.
      2. Reduce rows: EGC's own Token Crusher when ``egc`` is available and
         *use_egc* is true, the Python port otherwise.
      3. Format each event as one plain-text line.
      4. Enforce the character budget.

    Args:
        events:    Raw event dicts from memory.reader.read_session_events().
        max_chars: Hard character limit on the returned string.
        use_egc:   Try the installed EGC first (default). ``THE_LINK_NO_EGC=1``
                   has the same effect from the environment.

    Returns:
        Plain-text history, one line per event, within max_chars.
    """
    filtered = [
        e for e in events
        if e.get("event_type") in _OBSERVABLE or e.get("event") in _OBSERVABLE
    ]
    reduced = _reduce_rows_via_egc(filtered) if use_egc else None
    if reduced is None:
        reduced = _reduce_rows(filtered)
    working = reduced if reduced is not None else filtered

    lines: list[str] = []
    for event in working:
        etype = event.get("event_type") or event.get("event") or "unknown"
        tool = (
            event.get("tool")
            or (event.get("data") or {}).get("tool")
            or (event.get("data") or {}).get("tool_name")
            or "—"
        )
        ts = event.get("timestamp", "")
        date_part = ts[:10] if ts else "?"
        data = event.get("data") or {}
        content = (
            data.get("input") or data.get("output")
            or data.get("result") or data.get("params") or ""
        )
        if isinstance(content, (dict, list)):
            content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)
        content = str(content)[:120]
        lines.append(f"[{date_part}] {etype}: {tool} — {content}")

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars]
        last_nl = result.rfind("\n")
        if last_nl > 0:
            result = result[:last_nl]
    return result


if __name__ == "__main__":
    import io
    raw_events: list[dict] = []
    for line in io.StringIO(sys.stdin.read()):
        line = line.strip()
        if not line:
            continue
        try:
            raw_events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    print(crush_events(raw_events))
