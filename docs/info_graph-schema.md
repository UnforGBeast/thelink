# `info_graph.json` schema (as produced by graperoot)

Reference for the graph structure `thelink.graph` consumes. Captured from a live
`graperoot.graph_builder.scan()` run so downstream work (Phase 1 retrieval) has a
confirmed target instead of guessing.

- **graperoot version observed:** 3.10.10 (compiled extension,
  `graph_builder.cp314-win_amd64.pyd`)
- **API:** `graperoot.graph_builder.scan(root: Path, existing_nodes: dict | None = None) -> dict`
- **Committed sample:** [`tests/fixtures/info_graph.sample.json`](../tests/fixtures/info_graph.sample.json)
  (paths normalised to `/`, `root` replaced with `<FIXTURE_ROOT>`)
- **Conformance test:** `tests/test_graph.py::TestInfoGraphSchema` — fails if the
  fixture stops matching the shape documented here.

## Top level

```jsonc
{
  "root": "<absolute path that was scanned>",
  "node_count": 6,     // len(nodes)
  "edge_count": 5,     // len(edges)
  "file_count": 3,     // nodes where kind == "file"
  "symbol_count": 3,   // nodes where kind == "symbol"
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

There is **one** node list. File nodes and symbol nodes are mixed in it and
distinguished only by the `kind` field. There is no top-level `files`,
`file_nodes`, or `symbols` key.

## Node — `kind: "file"`

| field       | type        | notes |
|-------------|-------------|-------|
| `id`        | str         | equals `path` for file nodes |
| `kind`      | `"file"`    | |
| `path`      | str         | **relative to `root`**, native separator (`\` on Windows) |
| `ext`       | str         | e.g. `.py`, `.md` |
| `size`      | int         | bytes |
| `keywords`  | list[str]   | lowercased identifier fragments mined from the file; empty for non-symbol files (e.g. `.md`) |
| `content`   | str         | full file text, capped at `MAX_CONTENT_CHARS` (24000); files over `MAX_FILE_BYTES` (300000) are not parsed for symbols |
| `summary`   | str         | one-line synopsis graperoot generates (first statement + symbol roll-up) |
| `file_hash` | str         | short hex digest |

No `symbols` / `exports` / `imports` field on file nodes. A file's symbols and
imports are only discoverable via `edges` (see below).

## Node — `kind: "symbol"`

| field         | type          | notes |
|---------------|---------------|-------|
| `id`          | str           | `"<file path>::<name>"` |
| `kind`        | `"symbol"`    | |
| `path`        | str           | the **parent file's** path (not unique per symbol) |
| `ext`         | str           | parent file ext |
| `size`        | int           | line span (`line_end - line_start + 1`-ish) |
| `keywords`    | list[str]     | identifier fragments for this symbol |
| `symbol_type` | str           | graperoot's role guess: `model`, `use_case`, `controller`, `util`, … |
| `name`        | str           | symbol identifier |
| `line_start`  | int           | 1-based |
| `line_end`    | int           | 1-based |
| `body_hash`   | str           | short hex digest of the body |
| `confidence`  | str           | `high` / `medium` / `low` |
| `exported`    | bool          | module-visible vs local |

Symbol nodes have **no** `content`. Their `path` points at the parent file, so
naïvely reading `path` from disk for a symbol node yields the whole parent file.

## Edges

```jsonc
{ "from": "<node id>", "to": "<node id or bare module name>", "rel": "imports" }
```

| `rel`      | `from`        | `to`                                    |
|------------|---------------|-----------------------------------------|
| `contains` | file id       | symbol id (`"file::name"`)              |
| `imports`  | file id       | imported module — **may be a bare name** (`hashlib`) or a dotted path (`src.db`), not necessarily a node id in this graph |

`imports` targets are raw import tokens: external packages, stdlib modules, and
first-party modules all appear the same way and are **not** resolved to file
node ids. Resolving them to in-repo files (for Phase 1.4 graph expansion) is work
The Link has to do itself — e.g. map `src.db` → `src/db.py`.

## Constants exported by `graperoot.graph_builder`

| name                | value  |
|---------------------|--------|
| `MAX_CONTENT_CHARS` | 24000  |
| `MAX_FILE_BYTES`    | 300000 |
| `SQLITE_THRESHOLD`  | 30000  (node count above which graperoot switches to an on-disk sqlite graph) |
| `SYMBOL_EXTS`       | `.py .js .jsx .ts .tsx .java .c .h .cpp .hpp .cs .rb .rs .go(?) .php .kt .kts .scala` (langs with symbol extraction) |
| `SKIP_DIRS`         | `.git .venv venv node_modules dist .next .idea .vscode __pycache__ vendor .dual-graph .beads .beads-hooks Saved Binaries Intermediate DerivedDataCache` |

## How `thelink.graph` consumes this (post Phase 1.1)

`_build_file_docs` splits on `_is_real_schema` — true when `graph["nodes"]` is a
list and any entry carries a `kind`:

- **Real schema** (`_docs_from_real_schema`): iterate `nodes`, keep
  `kind == "file"`, and for each build a `scoring.FileDoc` from four tokenised
  fields — `path`, the file's own `keywords`, its `summary`, and `symbols`
  (every child symbol's `name` + mined `keywords`, grouped back onto the parent
  by shared `path`). `graph["edges"]` is passed straight through to the
  import-graph expansion pass (Phase 1.4).
- **Legacy / synthetic** (`_docs_from_legacy_schema`): a bare list under
  `files` / `nodes` / `file_nodes` whose entries lack `kind`; reads
  `path`/`file`/`name` and `symbols`/`exports`. Kept only for unit-test
  fixtures and non-graperoot graph sources — covered by
  `TestLegacyGraphAdapter`. The pre-1.1 flat-dict fallback
  (`for v in graph.values()`) was unreachable for real graperoot output and has
  been removed.

The pre-1.1 defects this capture surfaced are now closed: symbol nodes can no
longer occupy `top_n` slots (kind filter), and the real `keywords` / `summary`
fields are scored instead of a non-existent `symbols` key on file nodes.
