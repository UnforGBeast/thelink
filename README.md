# The Link — Unified Context Engine

> Zero-shot context injection for AI coding assistants.  
> Fuses **EGC session memory** (what you decided) with **GrapeRoot's semantic graph** (where the code lives) into a single, token-optimised payload — ready for any AI coding assistant.

---

## Install in one command

No manual setup. No separate EGC or GrapeRoot installs. Everything is fetched automatically.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/UnforGBeast/thelink/main/thelink/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/UnforGBeast/thelink/install.ps1 | iex
```

> **Note:** the Windows command uses `install.ps1` — a native PowerShell script. Do **not** pipe the `.sh` file into `iex`; PowerShell cannot execute bash syntax.

That's it. A global `link` command is now available in every terminal.

---

## Usage

```bash
link "<your query>"
```

```bash
# Minimal — runs against your current directory
link "Update the authentication middleware"

# Target a specific project
link "Refactor the payment module" --project /path/to/project

# Increase context size (default: 10 files)
link "Fix the login bug" --top-n 20 --verbose

# Pipe directly into Bob's rules file for the current session
link "Update the auth middleware" > .bob/rules/00-context.md

# Pipe into clipboard (macOS)
link "Fix the login bug" | pbcopy

# Pipe into clipboard (Windows)
link "Fix the login bug" | Set-Clipboard
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--project`, `-p` | current directory | Path to the target repository |
| `--top-n`, `-n` | `10` | Number of relevant files to include |
| `--graph-out` | `<project>/.dual-graph/info_graph.json` | Where to write the semantic graph |
| `--verbose`, `-v` | off | Show pipeline steps on stderr |
| `--version` | — | Print version and exit |

---

## Output format

The Link writes a structured payload to **stdout**:

```
[PROJECT HISTORY]
<compressed EGC session history — what was decided in past sessions>

[RELEVANT CODEBASE CONTEXT]
--- src/auth/middleware.py ---
<content of the most relevant file>

--- src/auth/token.py ---
<content of the second most relevant file>

[USER REQUEST]
<your query>
```

This can be piped directly into any AI coding assistant as the opening context.

---

## Integration with IBM Bob

### One-shot context injection (recommended)

Run The Link before opening Bob, writing its output into a Bob rules file:

```bash
link "your task description" --project . > .bob/rules/00-context.md
```

Bob automatically reads every file in `.bob/rules/` at the start of every conversation. The spatial + temporal context is pre-loaded before you type anything.

### Pipe to clipboard, paste into Bob

```powershell
link "Update the auth middleware" | Set-Clipboard
```

Then paste as your opening message in Bob's chat.

---

## How it works

```
link "your query"
       │
       ├─ Recall   ─── reads ~/.gemini/session-data/*.jsonl (EGC memory)
       │               Token Crusher compresses history → compressed_history
       │
       ├─ Map      ─── graperoot.graph_builder.scan(project)
       │               Scores file nodes by keyword overlap with query + history
       │               Reads top-N files from disk
       │
       └─ Compile  ─── [PROJECT HISTORY] + [RELEVANT CODEBASE CONTEXT] + [USER REQUEST]
                        → stdout
```

**Temporal memory** comes from EGC's JSONL session store (`~/.gemini/session-data/`). If you use EGC-based tools (Gemini CLI with EGC installed), The Link will find and compress that history automatically. If no history exists, the section is clearly marked as empty.

**Spatial memory** comes from GrapeRoot's semantic graph — a dependency graph of your entire codebase with file nodes, symbol exports, and import edges. The graph is built once per project and refreshed when source files change.

---

## Manual install (alternative)

If you prefer not to use the install scripts:

### pipx (isolated — recommended)

```bash
pipx install the-link
```

### pip (system Python)

```bash
pip install the-link
```

### From source

```bash
git clone https://github.com/UnforGBeast/thelink
cd thelink
pipx install .
```

---

## Uninstall

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/UnforGBeast/thelink/uninstall.sh | bash
```

### Windows

```powershell
irm https://raw.githubusercontent.com/UnforGBeast/thelink/uninstall.ps1 | iex
```

Or manually:

```bash
pipx uninstall the-link
```

---

## Requirements

- Python 3.10 or later
- Internet access for first install (fetches `graperoot` from PyPI)
- Works on Windows, macOS, and Linux

---

## License

Apache License 2.0. See source files for individual headers.

`graperoot` and `EGC` components retain their original Apache 2.0 licenses.
