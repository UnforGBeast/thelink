#!/usr/bin/env bash
# The Link — uninstaller (macOS / Linux)
set -euo pipefail

info()    { echo "[link] $*"; }
success() { echo "[link] $*"; }
error()   { echo "[link] error: $*" >&2; exit 1; }

info "Uninstalling The Link..."

if command -v pipx &>/dev/null; then
    if pipx list 2>/dev/null | grep -q "the-link"; then
        pipx uninstall the-link
        success "The Link uninstalled."
    else
        info "The Link is not installed via pipx."
    fi
elif python3 -m pipx list 2>/dev/null | grep -q "the-link"; then
    python3 -m pipx uninstall the-link
    success "The Link uninstalled."
else
    info "pipx not found. If you installed manually, remove it with: pip uninstall the-link"
fi
