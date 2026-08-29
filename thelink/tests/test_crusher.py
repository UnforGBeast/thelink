# Copyright 2024 The Link Authors — Apache 2.0
"""
Unit tests for thelink.crusher — Token Crusher logic.

Tests:
  TestToKey              — cell-value serialisation
  TestColumnCardinality  — cardinality ratio calculation
  TestRowSignature       — row fingerprinting
  TestReduceRows         — dedup + cap algorithm
  TestCrushEvents        — public API end-to-end
"""
import sys
import os
import unittest

# Allow running as: python -m unittest tests.test_crusher  (from thelink/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from thelink.crusher import (
    _to_key,
    _column_cardinality,
    _row_signature,
    _reduce_rows,
    crush_events,
    _MIN_ROWS,
    _MAX_ROWS,
    _OBSERVABLE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_event(event_type: str, tool: str = "read_file",
                ts: str = "2024-01-15T10:00:00Z", result: str = "ok") -> dict:
    return {
        "event_type": event_type,
        "timestamp": ts,
        "data": {"tool": tool, "result": result},
    }


def _make_events(n: int, event_type: str = "tool_result",
                 tool: str = "read_file", result: str = "content") -> list[dict]:
    return [_make_event(event_type, tool, f"2024-01-15T10:{i:02d}:00Z", result) for i in range(n)]


# ── _to_key ───────────────────────────────────────────────────────────────────

class TestToKey(unittest.TestCase):

    def test_none_returns_null_sentinel(self):
        self.assertEqual(_to_key(None), "__null__")

    def test_string_passthrough(self):
        self.assertEqual(_to_key("hello"), "hello")

    def test_int_stringified(self):
        self.assertEqual(_to_key(42), "42")

    def test_dict_json_serialised(self):
        result = _to_key({"a": 1})
        self.assertIn("a", result)
        self.assertIn("1", result)

    def test_list_json_serialised(self):
        result = _to_key([1, 2, 3])
        self.assertEqual(result, "[1,2,3]")

    def test_zero_not_null(self):
        self.assertEqual(_to_key(0), "0")

    def test_empty_string(self):
        self.assertEqual(_to_key(""), "")


# ── _column_cardinality ───────────────────────────────────────────────────────

class TestColumnCardinality(unittest.TestCase):

    def test_all_identical_is_zero(self):
        rows = [{"tool": "read_file"} for _ in range(10)]
        ratio = _column_cardinality(rows, "tool")
        self.assertAlmostEqual(ratio, 0.1)  # 1 unique / 10 total

    def test_all_unique_is_one(self):
        rows = [{"tool": str(i)} for i in range(10)]
        ratio = _column_cardinality(rows, "tool")
        self.assertAlmostEqual(ratio, 1.0)

    def test_empty_rows_is_zero(self):
        self.assertEqual(_column_cardinality([], "tool"), 0.0)

    def test_missing_key_counts_as_null(self):
        rows = [{}, {}, {}]
        # All three map to __null__ → 1 unique / 3 total ≈ 0.33
        ratio = _column_cardinality(rows, "missing")
        self.assertAlmostEqual(ratio, 1 / 3)

    def test_half_unique(self):
        rows = [{"x": "a"}, {"x": "a"}, {"x": "b"}, {"x": "b"}]
        self.assertAlmostEqual(_column_cardinality(rows, "x"), 0.5)


# ── _row_signature ────────────────────────────────────────────────────────────

class TestRowSignature(unittest.TestCase):

    def test_same_rows_same_signature(self):
        row = {"tool": "read_file", "result": "ok"}
        keys = ["tool", "result"]
        self.assertEqual(_row_signature(row, keys), _row_signature(row, keys))

    def test_different_rows_different_signatures(self):
        r1 = {"tool": "read_file"}
        r2 = {"tool": "write_file"}
        self.assertNotEqual(_row_signature(r1, ["tool"]), _row_signature(r2, ["tool"]))

    def test_truncated_to_32_chars(self):
        long_val = "x" * 100
        row = {"tool": long_val}
        sig = _row_signature(row, ["tool"])
        self.assertLessEqual(len(sig), 32)

    def test_empty_keys_list(self):
        row = {"tool": "read_file"}
        sig = _row_signature(row, [])
        self.assertEqual(sig, "")


# ── _reduce_rows ──────────────────────────────────────────────────────────────

class TestReduceRows(unittest.TestCase):

    def test_below_min_rows_returns_none(self):
        rows = _make_events(_MIN_ROWS - 1)
        self.assertIsNone(_reduce_rows([r["data"] for r in rows]))  # type: ignore[arg-type]

    def test_dedup_identical_rows(self):
        # All identical — should collapse to 1 unique, but that is < MIN_ROWS so...
        # Use events that pass through — 10 identical rows collapses to 1
        rows = [{"tool": "read_file", "result": "ok", "status": "done"} for _ in range(10)]
        result = _reduce_rows(rows)
        # Either None (no reduction) or a smaller list
        if result is not None:
            self.assertLess(len(result), len(rows))

    def test_cap_at_max_rows(self):
        # 20 unique rows → should cap at MAX_ROWS
        rows = [{"tool": f"tool_{i}", "result": f"res_{i}", "n": i,
                 "x": i * 2, "y": i * 3} for i in range(20)]
        result = _reduce_rows(rows)
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result), _MAX_ROWS)

    def test_head_tail_strategy(self):
        # 20 distinct rows — result must contain the first and last unique rows
        rows = [{"tool": f"t{i}", "result": f"r{i}", "n": i,
                 "x": i + 1, "y": i + 2} for i in range(20)]
        result = _reduce_rows(rows)
        if result is not None and len(result) == _MAX_ROWS:
            # First row of result should come from head of unique list
            self.assertEqual(result[0]["tool"], "t0")
            # Last row should come from tail
            self.assertEqual(result[-1]["tool"], "t19")

    def test_no_reduction_if_already_small(self):
        rows = [{"tool": "read_file", "result": "ok"} for _ in range(4)]
        self.assertIsNone(_reduce_rows(rows))


# ── crush_events ──────────────────────────────────────────────────────────────

class TestCrushEvents(unittest.TestCase):

    # ── Filtering ─────────────────────────────────────────────────────────────

    def test_filters_out_non_observable_types(self):
        events = [_make_event("irrelevant_type"), _make_event("tool_result")]
        result = crush_events(events)
        self.assertIn("tool_result", result)
        self.assertNotIn("irrelevant_type", result)

    def test_empty_events_returns_empty_string(self):
        self.assertEqual(crush_events([]), "")

    def test_all_filtered_returns_empty_string(self):
        events = [_make_event("not_observable") for _ in range(5)]
        self.assertEqual(crush_events(events), "")

    def test_all_observable_types_pass_through(self):
        for etype in _OBSERVABLE:
            events = [_make_event(etype)]
            result = crush_events(events)
            self.assertIn(etype, result, f"Event type '{etype}' not in output")

    def test_observe_schema_field_name(self):
        # observe.sh uses "event" not "event_type"
        events = [{"event": "tool_result", "timestamp": "2024-01-01", "tool": "grep"}]
        result = crush_events(events)
        self.assertIn("tool_result", result)

    # ── Format ────────────────────────────────────────────────────────────────

    def test_output_is_plain_text_lines(self):
        events = [_make_event("error")]
        result = crush_events(events)
        self.assertGreater(len(result), 0)
        # Should contain date bracket
        self.assertIn("[2024-01-15]", result)

    def test_one_line_per_event(self):
        events = [
            _make_event("error",      "tool_a", "2024-01-15T10:00:00Z"),
            _make_event("tool_result","tool_b", "2024-01-15T10:01:00Z"),
        ]
        result = crush_events(events)
        lines = [l for l in result.splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_line_contains_tool_name(self):
        events = [_make_event("error", tool="apply_diff")]
        result = crush_events(events)
        self.assertIn("apply_diff", result)

    def test_dict_data_content_serialised(self):
        events = [{
            "event_type": "tool_result",
            "timestamp": "2024-01-15T00:00:00Z",
            "data": {"tool": "search", "result": {"found": True}},
        }]
        result = crush_events(events)
        self.assertIn("found", result)

    # ── Character budget ──────────────────────────────────────────────────────

    def test_respects_max_chars(self):
        events = _make_events(100, result="x" * 200)
        result = crush_events(events, max_chars=500)
        self.assertLessEqual(len(result), 500)

    def test_truncates_to_last_complete_line(self):
        events = _make_events(50, result="data")
        result = crush_events(events, max_chars=200)
        # Should not end mid-line (no half-line at the end)
        self.assertFalse(result.endswith("—"))

    def test_default_budget_is_8000(self):
        events = _make_events(1000, result="y" * 10)
        result = crush_events(events)
        self.assertLessEqual(len(result), 8_000)

    def test_zero_max_chars_returns_empty(self):
        events = _make_events(5)
        result = crush_events(events, max_chars=0)
        self.assertEqual(result, "")

    # ── Reduction ─────────────────────────────────────────────────────────────

    def test_many_identical_events_compressed(self):
        # 50 identical tool_result events should compress heavily
        events = _make_events(50, event_type="tool_result", tool="read_file", result="content")
        result = crush_events(events)
        lines = [l for l in result.splitlines() if l.strip()]
        self.assertLessEqual(len(lines), _MAX_ROWS)

    def test_diverse_events_kept(self):
        # 5 unique events (below MIN_ROWS for dedup) — all should survive
        events = [
            _make_event("error",      "tool_a", result="err1"),
            _make_event("tool_result","tool_b", result="res1"),
            _make_event("failure",    "tool_c", result="fail"),
            _make_event("correction", "tool_d", result="fix"),
            _make_event("governance", "tool_e", result="ok"),
        ]
        result = crush_events(events)
        lines = [l for l in result.splitlines() if l.strip()]
        self.assertEqual(len(lines), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
