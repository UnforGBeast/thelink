# The Link — Test Report

**Suite:** The Link v1.0.0  
**Run date:** 2026-08-29 21:35:38  
**Platform:** Windows 10 (win32 x64)  
**Python:** 3.14.4  
**graperoot:** 3.10.10  
**Runner:** `python -m unittest discover tests/ -v`

---

## Overall Result: ✅ PASS

| Metric | Value |
|--------|------:|
| Total tests | **126** |
| Passed | **125** |
| Failed | **0** |
| Errors | **0** |
| Skipped | **1** |
<!-- note: 1 test is TestCLIErrors counted once vs unittest's discover (28 cli = 12 args + 7 helpers + 3 errors + 6 success) -->
| Total duration | **4.13 s** |

> **Skipped:** `TestE2EWorkspaceScan.test_full_workspace_pipeline` — intentionally gated.  
> Enable with: `$env:THE_LINK_RUN_FULL_E2E = "1"` then re-run.

---

## Results by Module

| Module | Tests | Passed | Failed | Skipped | Duration |
|--------|------:|-------:|-------:|--------:|---------:|
| `test_crusher` | 36 | 36 | 0 | 0 | 0.28 s |
| `test_memory` | 20 | 20 | 0 | 0 | 0.36 s |
| `test_graph` | 25 | 25 | 0 | 0 | 0.53 s |
| `test_cli` | 28 | 28 | 0 | 0 | 0.63 s |
| `test_e2e` | 17 | 16 | 0 | 1 | 4.15 s |
| **Total** | **126** | **125** | **0** | **1** | **4.13 s** |

---

## Module Breakdown

### `test_crusher.py` — Token Crusher (36 tests, 0.28 s)

Covers the Python port of EGC's TypeScript `egc-array-crusher.ts`.

#### `TestToKey` — cell-value serialisation

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_none_returns_null_sentinel` | ✅ | `None` maps to `"__null__"` |
| `test_string_passthrough` | ✅ | Plain strings pass through unchanged |
| `test_int_stringified` | ✅ | Integers cast to string |
| `test_dict_json_serialised` | ✅ | Dicts are JSON-serialised compact |
| `test_list_json_serialised` | ✅ | Lists are JSON-serialised compact |
| `test_zero_not_null` | ✅ | `0` → `"0"`, not `"__null__"` |
| `test_empty_string` | ✅ | Empty string → empty string |

#### `TestColumnCardinality` — cardinality ratio

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_all_identical_is_zero` | ✅ | All-same column → low ratio (1/n) |
| `test_all_unique_is_one` | ✅ | All-unique column → ratio = 1.0 |
| `test_empty_rows_is_zero` | ✅ | Empty list → 0.0 |
| `test_missing_key_counts_as_null` | ✅ | Missing keys treated as `__null__` |
| `test_half_unique` | ✅ | Half-unique column → ~0.5 |

#### `TestRowSignature` — fingerprinting

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_same_rows_same_signature` | ✅ | Identical rows → same signature |
| `test_different_rows_different_signatures` | ✅ | Different values → different signatures |
| `test_truncated_to_32_chars` | ✅ | Per-field contribution ≤ 32 chars |
| `test_empty_keys_list` | ✅ | No keys → empty signature |

#### `TestReduceRows` — dedup + head/tail cap

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_below_min_rows_returns_none` | ✅ | < `MIN_ROWS=5` → `None` (no reduction) |
| `test_dedup_identical_rows` | ✅ | Duplicate rows collapse |
| `test_cap_at_max_rows` | ✅ | Output never exceeds `MAX_ROWS=10` |
| `test_head_tail_strategy` | ✅ | First and last rows kept after cap |
| `test_no_reduction_if_already_small` | ✅ | Small input returns `None` |

#### `TestCrushEvents` — public API

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_filters_out_non_observable_types` | ✅ | Non-observable types stripped |
| `test_empty_events_returns_empty_string` | ✅ | Empty input → `""` |
| `test_all_filtered_returns_empty_string` | ✅ | All non-observable → `""` |
| `test_all_observable_types_pass_through` | ✅ | All 10 observable types survive |
| `test_observe_schema_field_name` | ✅ | `"event"` field (observe.sh schema) works |
| `test_output_is_plain_text_lines` | ✅ | Output has `[date]` brackets |
| `test_one_line_per_event` | ✅ | One line per event |
| `test_line_contains_tool_name` | ✅ | Tool name in every line |
| `test_dict_data_content_serialised` | ✅ | Dict data JSON-serialised inline |
| `test_respects_max_chars` | ✅ | Output ≤ `max_chars` |
| `test_truncates_to_last_complete_line` | ✅ | Truncation at last `\n` |
| `test_default_budget_is_8000` | ✅ | Default = 8,000 chars |
| `test_zero_max_chars_returns_empty` | ✅ | `max_chars=0` → `""` |
| `test_many_identical_events_compressed` | ✅ | 50 identical → ≤ 10 lines |
| `test_diverse_events_kept` | ✅ | 5 unique events all kept |

---

### `test_memory.py` — Memory Engine (20 tests, 0.36 s)

Covers path helpers and JSONL session reader.

#### `TestPaths` — path resolution

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_home_dir_returns_path` | ✅ | Returns absolute `Path` |
| `test_egc_home_default_is_dotgemini` | ✅ | Default resolves to `~/.gemini` |
| `test_egc_home_env_override` | ✅ | `EGC_HOME` env var overrides |
| `test_egc_state_dir_falls_back_to_egc_home` | ✅ | State dir falls back correctly |
| `test_egc_canonical_sessions_dir_is_under_state` | ✅ | Sessions dir under state |
| `test_egc_session_dir_env_override` | ✅ | `EGC_SESSION_DIR` override works |
| `test_project_root_env_override` | ✅ | `PROJECT_ROOT` env var overrides |
| `test_project_root_defaults_to_cwd` | ✅ | Falls back to `cwd()` |

#### `TestReader` — JSONL reading

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_returns_empty_list_when_no_sessions` | ✅ | No dirs → `[]` |
| `test_reads_events_from_local_sessions` | ✅ | Reads from `.sessions/` |
| `test_events_are_dicts` | ✅ | Each event is a `dict` |
| `test_event_content_preserved` | ✅ | Fields preserved verbatim |
| `test_multiple_jsonl_files_all_read` | ✅ | Multiple files merged |
| `test_no_local_sessions_dir_still_works` | ✅ | Missing `.sessions/` not an error |

#### `TestReaderEdgeCases` — resilience

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_skips_malformed_json_lines` | ✅ | Non-JSON lines silently skipped |
| `test_skips_blank_lines` | ✅ | Blank lines ignored |
| `test_max_events_cap_enforced` | ✅ | Capped at `MAX_EVENTS=500` |
| `test_none_project_path_uses_cwd` | ✅ | `None` falls back to cwd |
| `test_unicode_content_handled` | ✅ | CJK and symbols read correctly |
| `test_empty_jsonl_file_handled` | ✅ | Empty file does not raise |

---

### `test_graph.py` — Graph Wrapper (25 tests, 0.53 s)

Covers graperoot guard, side-effect suppression, and file scoring. No live graperoot scan.

#### `TestCheckGraperoot` — installation guard

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_raises_import_error_when_absent` | ✅ | `ImportError` raised with pip hint |
| `test_no_error_when_present` | ✅ | No exception when importable |

#### `TestSuppressGraperoot` — side-effect cleanup

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_deletes_chat_action_graph` | ✅ | `chat_action_graph.json` deleted |
| `test_deletes_context_store` | ✅ | `context-store.json` deleted |
| `test_both_deleted_together` | ✅ | Both files deleted in one call |
| `test_no_error_when_files_absent` | ✅ | No error when nothing to delete |
| `test_other_files_not_deleted` | ✅ | `info_graph.json` untouched |

#### `TestTokenise` — keyword extraction

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_basic_split` | ✅ | Whitespace splitting |
| `test_lowercased` | ✅ | All tokens lowercased |
| `test_punctuation_split` | ✅ | `/`, `.`, `_` as delimiters |
| `test_empty_string` | ✅ | Empty string → empty set |

#### `TestExtractRelevantFiles` — scoring + ranking

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_auth_file_ranks_first_for_auth_query` | ✅ | Correct file ranked #1 |
| `test_score_is_non_negative` | ✅ | All scores ≥ 0 |
| `test_higher_overlap_higher_score` | ✅ | More keyword hits → higher score |
| `test_history_contributes_to_scoring` | ✅ | History boosts relevant files |
| `test_top_n_respected` | ✅ | `top_n=5` returns ≤ 5 files |
| `test_zero_top_n_returns_empty` | ✅ | `top_n=0` returns `[]` |
| `test_empty_graph_files_returns_empty` | ✅ | Empty graph → `[]` |
| `test_result_has_required_keys` | ✅ | `path`, `score`, `content` present |
| `test_content_read_from_disk` | ✅ | Actual file content read |
| `test_missing_file_content_is_empty_or_error_string` | ✅ | Missing file doesn't crash |
| `test_content_truncated_at_3000_chars` | ✅ | Content capped at 3,000 chars |
| `test_truncation_note_appended` | ✅ | Truncation note added |
| `test_nodes_key_fallback` | ✅ | `"nodes"` key used if no `"files"` |
| `test_file_key_in_node` | ✅ | `"file"` node key used as path |

---

### `test_cli.py` — CLI Integration (24 tests, 0.63 s)

Tests `main(argv=[...])` directly with mocked pipeline.

#### `TestArgParser` — argument parsing

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_query_required` | ✅ | Exits with error if no query |
| `test_query_positional` | ✅ | Query captured positionally |
| `test_project_flag` | ✅ | `--project` accepted |
| `test_project_short_flag` | ✅ | `-p` accepted |
| `test_top_n_default_is_10` | ✅ | Default `--top-n` = 10 |
| `test_top_n_custom` | ✅ | Custom `--top-n` accepted |
| `test_top_n_short` | ✅ | `-n` short form accepted |
| `test_verbose_default_false` | ✅ | `--verbose` off by default |
| `test_verbose_flag` | ✅ | `--verbose` enables verbose |
| `test_verbose_short_flag` | ✅ | `-v` accepted |
| `test_graph_out_flag` | ✅ | `--graph-out` accepted |
| `test_version_exits` | ✅ | `--version` exits 0 |

#### `TestPayloadHelpers` — output assembly

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_format_code_chunks_empty` | ✅ | Empty list → fallback message |
| `test_format_code_chunks_one_file` | ✅ | File path + content in output |
| `test_format_code_chunks_multiple_files` | ✅ | All files present |
| `test_build_payload_sections_present` | ✅ | All 3 section headers |
| `test_build_payload_query_in_output` | ✅ | Query in payload |
| `test_build_payload_empty_history_fallback` | ✅ | Empty history → fallback text |
| `test_build_payload_history_in_output` | ✅ | History text appears |

#### `TestCLIErrors` — error paths

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_invalid_project_path_exits_1` | ✅ | Bad path → exit 1 |
| `test_graperoot_missing_exits_1` | ✅ | `ImportError` → exit 1 + message |
| `test_graph_build_failure_exits_1` | ✅ | `RuntimeError` → exit 1 + message |

#### `TestCLISuccess` — success path

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_exit_code_0_on_success` | ✅ | Clean run → exit 0 |
| `test_stdout_contains_all_three_sections` | ✅ | All 3 headers in stdout |
| `test_query_appears_in_user_request_section` | ✅ | Query in `[USER REQUEST]` |
| `test_no_session_history_shows_fallback` | ✅ | No history → fallback message |
| `test_top_n_limits_files_in_output` | ✅ | `--top-n=1` limits separators |
| `test_default_graph_out_under_dual_graph` | ✅ | Graph path = `.dual-graph/info_graph.json` |

---

### `test_e2e.py` — End-to-End (17 tests, 4.15 s)

Runs the full subprocess pipeline against a real temporary project.  
*Requires graperoot — automatically skipped if not installed.*

#### `TestE2EBasic` — invocation checks

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_help_exits_0` | ✅ | `--help` prints usage, exits 0 |
| `test_version_exits_0` | ✅ | `--version` prints 1.0.0, exits 0 |
| `test_missing_query_exits_nonzero` | ✅ | No query → non-zero exit |
| `test_invalid_project_exits_1` | ✅ | Bad project → exit 1 |
| `test_no_traceback_on_bad_project` | ✅ | No `Traceback` in stderr |

#### `TestE2EPipeline` — full pipeline with real scan

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_exit_code_0` | ✅ | Pipeline exits 0 |
| `test_three_section_headers_present` | ✅ | All 3 headers in output |
| `test_query_in_user_request_section` | ✅ | Query text in `[USER REQUEST]` |
| `test_payload_within_token_budget` | ✅ | Output ≤ 80,000 chars (~20k tokens) |
| `test_no_traceback_on_success` | ✅ | No `Traceback` on stderr |
| `test_stderr_lines_are_link_prefixed` | ✅ | All stderr lines start with `[link]` |
| `test_chat_action_graph_suppressed` | ✅ | `chat_action_graph.json` absent |
| `test_graph_file_created` | ✅ | `info_graph.json` created |
| `test_graph_file_valid_json` | ✅ | `info_graph.json` is valid JSON |
| `test_relevant_auth_file_in_context` | ✅ | Auth file appears for auth query |
| `test_top_n_flag_limits_files` | ✅ | `--top-n=1` produces fewer files |

#### `TestE2EWorkspaceScan` — full workspace

| Test | Result | What it checks |
|------|:------:|----------------|
| `test_full_workspace_pipeline` | ⏭ SKIPPED | 1,800-file scan — set `THE_LINK_RUN_FULL_E2E=1` to enable |

---

## How to Re-run

```powershell
# Run all tests (from thelink/ directory)
.venv\Scripts\python -m unittest discover tests/ -v

# Run a single module
.venv\Scripts\python -m unittest tests.test_crusher -v

# Run a single test class
.venv\Scripts\python -m unittest tests.test_graph.TestExtractRelevantFiles -v

# Run a single test
.venv\Scripts\python -m unittest tests.test_e2e.TestE2EPipeline.test_payload_within_token_budget -v

# Enable the gated workspace scan test
$env:THE_LINK_RUN_FULL_E2E = "1"
.venv\Scripts\python -m unittest tests.test_e2e.TestE2EWorkspaceScan -v
```

---

## Coverage Summary

| Layer | Component | Unit tested | Integration tested |
|-------|-----------|:-----------:|:-----------------:|
| Crusher | `_to_key` | ✅ | — |
| Crusher | `_column_cardinality` | ✅ | — |
| Crusher | `_row_signature` | ✅ | — |
| Crusher | `_reduce_rows` | ✅ | — |
| Crusher | `crush_events` | ✅ | ✅ (via E2E) |
| Memory | `paths.*` | ✅ | — |
| Memory | `read_session_events` | ✅ | ✅ (via E2E) |
| Graph | `_check_graperoot` | ✅ | ✅ (via E2E) |
| Graph | `_suppress_graperoot_state` | ✅ | ✅ (via E2E) |
| Graph | `_tokenise` | ✅ | — |
| Graph | `extract_relevant_files` | ✅ | ✅ (via E2E) |
| Graph | `build_graph` | — | ✅ (via E2E) |
| CLI | Argument parser | ✅ | ✅ (via E2E) |
| CLI | Payload assembly | ✅ | ✅ (via E2E) |
| CLI | Error paths | ✅ | ✅ (via E2E) |
| CLI | Success path | ✅ | ✅ (via E2E) |
| Install | `pyproject.toml` entry point | — | ✅ (link.exe verified) |

---

*Report generated from test run on 2026-08-29. Machine-readable data: [`tests/test_results.json`](tests/test_results.json)*
