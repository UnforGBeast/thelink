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
Token Crusher — compresses a list of EGC session events into a compact,
low-noise history string suitable for LLM context injection.

Algorithm mirrors the TypeScript egc-array-crusher.ts from EGC:
  - Column-cardinality analysis (VARIANCE_THRESHOLD = 0.15)
  - Row deduplication by signature
  - Head + tail cap at MAX_ROWS_AFTER_CRUSH = 10
  - Observable event-type filter
  - Character budget enforcement

Public API:
    crush_events(events, max_chars=8000) -> str
"""
from __future__ import annotations

import json
import sys
from typing import Any

# ── Constants (mirrors egc-array-crusher.ts) ─────────────────────────────────
_MIN_ROWS = 5
_MAX_ROWS = 10
_VARIANCE_THRESHOLD = 0.15

# Mirror of SessionRecorder._OBSERVABLE_EVENT_TYPES
_OBSERVABLE = frozenset({
    "veto", "mutation", "post_tool", "tool_result", "tool_use",
    "error", "failure", "retry", "correction", "governance",
})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_key(v: Any) -> str:
    """Stable string key for a cell value (mirrors TS toKey())."""
    if v is None:
        return "__null__"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    return str(v)


def _column_cardinality(rows: list[dict], key: str) -> float:
    """Ratio of unique values to total rows for a single column."""
    if not rows:
        return 0.0
    values = {_to_key(row.get(key)) for row in rows}
    return len(values) / len(rows)


def _row_signature(row: dict, keys: list[str]) -> str:
    """Fingerprint for a row using the first 32 chars of each scored key."""
    return "|".join(_to_key(row.get(k))[:32] for k in keys)


def _reduce_rows(rows: list[dict]) -> list[dict] | None:
    """Deduplicate and cap rows.

    Returns None if no reduction is possible (too few rows, or result would
    not be smaller than the input).
    """
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
        tail_size = _MAX_ROWS - head_size
        unique = unique[:head_size] + unique[-tail_size:]

    return unique if len(unique) < len(rows) else None


# ── Public API ────────────────────────────────────────────────────────────────

def crush_events(events: list[dict[str, Any]], max_chars: int = 8_000) -> str:
    """Compress a list of EGC session event dicts into a history string.

    Steps:
      1. Filter to observable event types only.
      2. Apply row deduplication / cardinality reduction.
      3. Format each event as a single text line.
      4. Enforce the character budget (truncate tail).

    Args:
        events:    Raw event dicts from memory.reader.read_session_events().
        max_chars: Hard character limit on the returned string.

    Returns:
        Plain-text history string, one line per event, within max_chars.
        Returns an empty string if no relevant events are found.
    """
    # Step 1: filter to observable types
    filtered = [e for e in events if e.get("event_type") in _OBSERVABLE or e.get("event") in _OBSERVABLE]

    # Step 2: deduplicate / reduce
    reduced = _reduce_rows(filtered)
    working = reduced if reduced is not None else filtered

    # Step 3: format lines
    lines: list[str] = []
    for event in working:
        # Support both EGC Python schema (event_type/data) and observe.sh schema (event/tool)
        etype = event.get("event_type") or event.get("event") or "unknown"
        tool = (
            event.get("tool")
            or (event.get("data") or {}).get("tool")
            or (event.get("data") or {}).get("tool_name")
            or "—"
        )
        # Timestamp: use date portion only (keeps lines short)
        ts = event.get("timestamp", "")
        date_part = ts[:10] if ts else "?"

        # Content: prefer tool input/output summary, fall back to raw data
        data = event.get("data") or {}
        content = (
            data.get("input")
            or data.get("output")
            or data.get("result")
            or data.get("params")
            or ""
        )
        if isinstance(content, (dict, list)):
            content = json.dumps(content, separators=(",", ":"), ensure_ascii=False)
        content = str(content)[:120]  # cap per-line content

        lines.append(f"[{date_part}] {etype}: {tool} — {content}")

    result = "\n".join(lines)

    # Step 4: enforce character budget
    if len(result) > max_chars:
        result = result[:max_chars]
        # Trim to last complete line so we don't end mid-sentence
        last_nl = result.rfind("\n")
        if last_nl > 0:
            result = result[:last_nl]

    return result


# ── CLI helper (manual testing) ───────────────────────────────────────────────

if __name__ == "__main__":
    import io
    raw = sys.stdin.read()
    raw_events: list[dict] = []
    for line in io.StringIO(raw):
        line = line.strip()
        if not line:
            continue
        try:
            raw_events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    print(crush_events(raw_events))
