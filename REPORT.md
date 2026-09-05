# The Link — Test Report

**Suite:** The Link v1.0.0 (Phase 1 — retrieval quality)
**Run date:** 2026-09-06
**Platform:** Windows 10 (10.0.19045, win32 AMD64)
**Python:** 3.14.4
**graperoot:** 3.10.10
**Runner:** `python -m unittest discover tests/ -v`

---

## Overall Result: PASS

| Metric | Value |
|--------|------:|
| Total tests | **177** |
| Passed | **176** |
| Failed | **0** |
| Errors | **0** |
| Skipped | **1** |
| Total duration | **~15 s** |

Total = sum of the per-module counts below (36 + 20 + 37 + 24 + 6 + 37 + 17).
The runtime is dominated by `test_gitsignals` (real `git init` repos) and
`test_e2e` (real graperoot scans); the pure-logic modules run in <1 s combined.

> **Skipped:** `TestE2EWorkspaceScan.test_full_workspace_pipeline` — gated;
> enable with `$env:THE_LINK_RUN_FULL_E2E = "1"`.

### Changes since the Phase 0 run (135 tests)

Phase 1 replaced the keyword-overlap scorer with a composable, signal-based one:

- **New `thelink/scoring.py`** — `@signal` / `@propagator` registries, a
  field-weighted BM25 index, camelCase tokeniser + light stemmer, and
  `score_documents()`. Covered by **`test_scoring.py` (24)**.
- **New `thelink/gitsignals.py`** — the composite `git` signal (working-tree
  changes, branch diff, commit recency, co-change) built from local `git` only.
  Covered by **`test_gitsignals.py` (6)**.
- **`test_graph.py` 34 → 37** — `TestExtractRelevantFiles` now feeds the real
  graperoot schema via a `_real_graph()` helper; the legacy bare-list shapes
  moved to `TestLegacyGraphAdapter`; added graph-expansion and `with_signals`
  cases. A `_GitDisabledMixin` neutralises git so ranking assertions don't
  depend on the checkout the suite runs in.
- **`test_cli.py` 28 → 37** — `--explain` / `--graph-hops` / `--no-git` parsing,
  `_explain_lines` rendering, and an integration check that `--explain` leaves
  stdout byte-for-byte unchanged.

---

## Results by Module

| Module | Tests | Passed | Failed | Skipped |
|--------|------:|-------:|-------:|--------:|
| `test_crusher` | 36 | 36 | 0 | 0 |
| `test_memory` | 20 | 20 | 0 | 0 |
| `test_graph` | 37 | 37 | 0 | 0 |
| `test_scoring` | 24 | 24 | 0 | 0 |
| `test_gitsignals` | 6 | 6 | 0 | 0 |
| `test_cli` | 37 | 37 | 0 | 0 |
| `test_e2e` | 17 | 16 | 0 | 1 |
| **Total** | **177** | **176** | **0** | **1** |

---

## Module Breakdown

### `test_crusher.py` — Token Crusher (36)

Unchanged. Python port of EGC's `egc-array-crusher.ts`: `_to_key`,
`_column_cardinality`, `_row_signature`, `_reduce_rows`, and `crush_events`
(observable-type filter, one-line formatting, `max_chars` budget, repeat
compression).

### `test_memory.py` — Memory Engine (20)

Unchanged. `paths.*` env-override resolution, and `read_session_events` against
fixture JSONL (merge, field preservation, malformed/blank lines, `MAX_EVENTS`,
Unicode, empty file).

### `test_graph.py` — Graph wrapper + schema (37)

- **`TestCheckGraperoot`** (2), **`TestSuppressGraperoot`** (5),
  **`TestTokenise`** (4) — unchanged (`_tokenise` is the retained legacy helper).
- **`TestExtractRelevantFiles`** (16) — ranking, `top_n`, disk reads, 3000-char
  truncation + note, `with_signals` breakdown, and `--graph-hops` expansion via
  a real-schema `imports` edge. Runs with the git signal patched off.
- **`TestLegacyGraphAdapter`** (3) — bare `{"files"/"nodes": [...]}` graphs with
  no `kind` field still resolve (synthetic-fixture / non-graperoot support).
- **`TestInfoGraphSchema`** (9) — unchanged; pins
  `tests/fixtures/info_graph.sample.json` to `docs/info_graph-schema.md`.

### `test_scoring.py` — Composable scorer (24)

- **`TestTokenize`** (6) — camelCase / snake / path splitting, stop-word and
  extension drops, term-frequency preservation, stemmer collapse
  (`authenticating`≡`authenticated`), short-token guard.
- **`TestBm25Index`** (4) — rarer term → higher IDF, prefix expansion
  (`auth`→`authentication`), exact hit beats prefix hit, unknown terms dropped.
- **`TestScoreDocuments`** (8) — relevant doc ranks first; **semantic hit beats a
  lexical-prefix decoy** (1.3 gate); history weighted below query; total = Σ
  weighted signals; zero weight skips a signal; deterministic path tie-break;
  **new signal added via registry only** (1.1 gate); default signals registered.
- **`TestImportGraphExpansion`** (6) — callee surfaces from a caller-only query;
  **hop depth configurable** (1 vs 2, 1.4 gate); `--graph-hops 0` disables; no
  edges → no boost; dotted-module target resolves; `import_graph` is a default
  propagator.

### `test_gitsignals.py` — Local-git signal (6)

- **`TestOutsideRepo`** (2) — non-repo dir → `collect_git_context` returns
  `None`; signal is `0.0` with no context.
- **`TestInsideRepo`** (4, real `git init`) — recent history collected;
  uncommitted change outscores a clean file; a dirty file floats to rank 1 for a
  non-matching query; co-change with a dirty file adds a boost.

### `test_cli.py` — CLI integration (37)

- **`TestArgParser`** (15) — all flags incl. `--explain`/`-e`,
  `--graph-hops`, `--no-git`.
- **`TestPayloadHelpers`** (7) — unchanged.
- **`TestExplainLines`** (3) — empty case, header lists signal names, per-signal
  values rendered.
- **`TestExplainIntegration`** (3) — stdout byte-identical with/without
  `--explain`; every `--explain` stderr line `[link]`-prefixed; top file named in
  the table.
- **`TestCLIErrors`** (3), **`TestCLISuccess`** (6) — unchanged.

### `test_e2e.py` — End-to-end (17, 1 skipped)

Unchanged. Real `python -m thelink` subprocess against a temp project with a
live graperoot scan: exit codes, three headers, query echo, 80k-char budget, no
`Traceback`, `[link]`-prefixed stderr, side-effect suppression, `info_graph.json`
creation, auth file surfaced, `--top-n` bound.

---

## How to Re-run

```powershell
python -m unittest discover tests/ -v            # everything
python -m unittest tests.test_scoring -v         # one module
python -m unittest tests.test_scoring.TestImportGraphExpansion -v
$env:THE_LINK_RUN_FULL_E2E = "1"; python -m unittest tests.test_e2e.TestE2EWorkspaceScan -v
```

---

*Machine-readable companion: [`tests/test_results.json`](tests/test_results.json).*
