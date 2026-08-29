#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# The Link — one-command global installer (macOS / Linux)
#
# What this script does:
#   1. Checks for Python 3.10+
#   2. Installs pipx if not present  (isolated app manager)
#   3. Installs "the-link" via pipx  (graperoot and all deps auto-bundled)
#   4. Verifies the `link` command is on PATH
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/your-org/the-link/main/install.sh | bash
#   — or —
#   bash install.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="https://github.com/your-org/the-link"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

# ── Colours (suppressed in non-interactive shells) ────────────────────────────
if [ -t 1 ]; then
  BOLD="\033[1m"; RESET="\033[0m"; GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"
else
  BOLD=""; RESET=""; GREEN=""; RED=""; YELLOW=""
fi

info()    { echo -e "${BOLD}[link]${RESET} $*"; }
success() { echo -e "${GREEN}[link]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[link]${RESET} $*"; }
error()   { echo -e "${RED}[link] error:${RESET} $*" >&2; exit 1; }

# ── Step 1: Locate Python 3.10+ ───────────────────────────────────────────────
info "Checking Python version..."

PYTHON=""
for candidate in python3 python python3.14 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" &>/dev/null; then
    ver=$("$candidate" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null || true)
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    if [ "${major:-0}" -ge "$MIN_PYTHON_MAJOR" ] && [ "${minor:-0}" -ge "$MIN_PYTHON_MINOR" ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

[ -n "$PYTHON" ] || error "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required but not found.
Install it from https://www.python.org/downloads/ and re-run this script."

info "Using $($PYTHON --version)"

# ── Step 2: Install / upgrade pipx ───────────────────────────────────────────
info "Checking pipx..."

if ! command -v pipx &>/dev/null; then
  info "pipx not found — installing via pip..."
  "$PYTHON" -m pip install --user pipx --quiet
  "$PYTHON" -m pipx ensurepath --quiet 2>/dev/null || true

  # Refresh PATH for the current shell session
  export PATH="$PATH:$HOME/.local/bin"

  if ! command -v pipx &>/dev/null; then
    warn "pipx installed but not yet on PATH."
    warn "Please open a new terminal after installation, or add ~/.local/bin to PATH."
    PIPX="$PYTHON -m pipx"
  else
    PIPX="pipx"
  fi
else
  PIPX="pipx"
fi

info "pipx ready."

# ── Step 3: Install the-link ──────────────────────────────────────────────────
info "Installing The Link (this fetches graperoot and all dependencies)..."

# If already installed, upgrade instead of error
if $PIPX list 2>/dev/null | grep -q "the-link"; then
  info "Existing installation found — upgrading..."
  $PIPX upgrade the-link --quiet 2>/dev/null || $PIPX install "$REPO_URL" --force --quiet
else
  # Try PyPI first, fall back to direct GitHub install
  if ! $PIPX install the-link --quiet 2>/dev/null; then
    info "PyPI package not available — installing from source..."
    $PIPX install "git+${REPO_URL}.git" --quiet
  fi
fi

# ── Step 4: Verify ────────────────────────────────────────────────────────────
info "Verifying installation..."

# Re-source the pipx path in case this is a fresh install
export PATH="$PATH:$HOME/.local/bin"

if command -v link &>/dev/null; then
  VER=$(link --version 2>/dev/null || echo "unknown")
  success "The Link installed successfully!"
  echo ""
  echo -e "  ${BOLD}Command:${RESET} link"
  echo -e "  ${BOLD}Version:${RESET} $VER"
  echo ""
  echo -e "  ${BOLD}Quick start:${RESET}"
  echo -e "    link \"Update the authentication middleware\""
  echo -e "    link \"Refactor the payment module\" --project /path/to/repo --verbose"
  echo -e "    link \"Fix the login bug\" > .bob/rules/00-context.md"
  echo ""
  echo -e "  ${BOLD}Docs:${RESET} ${REPO_URL}#readme"
  echo ""
else
  warn "Installation succeeded but 'link' is not on PATH yet."
  warn "Open a new terminal session and run: link --version"
  warn "Or add pipx's bin directory to PATH manually:"
  warn "  export PATH=\"\$PATH:\$HOME/.local/bin\""
fi
