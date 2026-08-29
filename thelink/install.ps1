#Requires -Version 5.1
<#
.SYNOPSIS
    The Link — one-command global installer for Windows (PowerShell)

.DESCRIPTION
    What this script does:
      1. Checks for Python 3.10+
      2. Installs pipx if not present  (isolated app manager)
      3. Installs "the-link" via pipx  (graperoot and all deps auto-bundled)
      4. Adds pipx's Scripts dir to the user PATH if needed
      5. Verifies the `link` command works

.EXAMPLE
    # Run directly from PowerShell (as normal user, no admin required):
    irm https://raw.githubusercontent.com/your-org/the-link/main/install.ps1 | iex

    # Or run the local script:
    .\install.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/your-org/the-link"
$MinMajor = 3
$MinMinor = 10

function Write-Info    { Write-Host "[link] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[link] $args" -ForegroundColor Green }
function Write-Warn    { Write-Host "[link] warning: $args" -ForegroundColor Yellow }
function Write-Err     { Write-Host "[link] error: $args" -ForegroundColor Red; exit 1 }

# ── Step 1: Locate Python 3.10+ ───────────────────────────────────────────────
Write-Info "Checking Python version..."

$Python = $null
$candidates = @("python", "python3", "py")

foreach ($candidate in $candidates) {
    try {
        $ver = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            $major = [int]$parts[0]
            $minor = [int]$parts[1]
            if ($major -ge $MinMajor -and $minor -ge $MinMinor) {
                $Python = $candidate
                break
            }
        }
    } catch { }
}

if (-not $Python) {
    # Try Python Launcher for Windows (py -3.x)
    foreach ($minor in @(14, 13, 12, 11, 10)) {
        try {
            $ver = & py "-3.$minor" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver) { $Python = "py -3.$minor"; break }
        } catch { }
    }
}

if (-not $Python) {
    Write-Err "Python $MinMajor.$MinMinor+ is required but not found.`nInstall from https://www.python.org/downloads/ and re-run."
}

$PyVersion = & Invoke-Expression "$Python --version" 2>&1
Write-Info "Using $PyVersion"

# ── Step 2: Install / upgrade pipx ───────────────────────────────────────────
Write-Info "Checking pipx..."

$pipxCmd = Get-Command pipx -ErrorAction SilentlyContinue

if (-not $pipxCmd) {
    Write-Info "pipx not found — installing via pip..."
    Invoke-Expression "$Python -m pip install --user pipx --quiet"
    Invoke-Expression "$Python -m pipx ensurepath" 2>$null

    # Add pipx Scripts to the current session's PATH
    $pipxBin = Join-Path $env:USERPROFILE "AppData\Roaming\Python\Scripts"
    $pipxBin2 = Join-Path $env:USERPROFILE ".local\bin"
    foreach ($p in @($pipxBin, $pipxBin2)) {
        if (Test-Path $p) {
            $env:PATH = "$p;$env:PATH"
        }
    }

    $pipxCmd = Get-Command pipx -ErrorAction SilentlyContinue
    if (-not $pipxCmd) {
        Write-Warn "pipx installed but not yet on PATH in this session."
        Write-Warn "After this script finishes, open a NEW PowerShell window and run: link --version"
        # Use python -m pipx as fallback for the rest of this session
        function Invoke-Pipx { Invoke-Expression "$Python -m pipx $args" }
        $UsePipxModule = $true
    }
}

Write-Info "pipx ready."

# ── Step 3: Install the-link ──────────────────────────────────────────────────
Write-Info "Installing The Link (this fetches graperoot and all dependencies)..."

function Invoke-PipxCommand {
    param([string]$Command)
    if ($UsePipxModule -eq $true) {
        Invoke-Expression "$Python -m pipx $Command"
    } else {
        Invoke-Expression "pipx $Command"
    }
}

$UsePipxModule = $false

# Check if already installed
$installed = $false
try {
    $listOutput = Invoke-PipxCommand "list" 2>&1
    if ($listOutput -match "the-link") { $installed = $true }
} catch { }

if ($installed) {
    Write-Info "Existing installation found — upgrading..."
    try {
        Invoke-PipxCommand "upgrade the-link" | Out-Null
    } catch {
        Invoke-PipxCommand "install the-link --force" | Out-Null
    }
} else {
    # Try PyPI first, then GitHub source
    try {
        Invoke-PipxCommand "install the-link" | Out-Null
    } catch {
        Write-Info "PyPI package not yet available — installing from source..."
        Invoke-PipxCommand "install `"git+${RepoUrl}.git`"" | Out-Null
    }
}

# ── Step 4: Add pipx Scripts to permanent user PATH ───────────────────────────
Write-Info "Ensuring 'link' is available on PATH..."

$pipxScripts = Join-Path $env:USERPROFILE ".local\bin"
$pipxScripts2 = Join-Path $env:USERPROFILE "AppData\Roaming\Python\Scripts"

$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
foreach ($p in @($pipxScripts, $pipxScripts2)) {
    if ((Test-Path $p) -and $userPath -notlike "*$p*") {
        [System.Environment]::SetEnvironmentVariable(
            "PATH",
            "$userPath;$p",
            "User"
        )
        $env:PATH = "$env:PATH;$p"
        Write-Info "Added $p to user PATH."
    }
}

# ── Step 5: Verify ────────────────────────────────────────────────────────────
$linkCmd = Get-Command link -ErrorAction SilentlyContinue

if ($linkCmd) {
    $Ver = & link --version 2>&1
    Write-Success "The Link installed successfully!"
    Write-Host ""
    Write-Host "  Command : link" -ForegroundColor White
    Write-Host "  Version : $Ver" -ForegroundColor White
    Write-Host ""
    Write-Host "  Quick start:" -ForegroundColor White
    Write-Host '    link "Update the authentication middleware"'
    Write-Host '    link "Refactor the payment module" --project C:\my\project --verbose'
    Write-Host '    link "Fix the login bug" | Set-Content .bob\rules\00-context.md'
    Write-Host ""
    Write-Host "  Docs: $RepoUrl#readme" -ForegroundColor DarkCyan
    Write-Host ""
} else {
    Write-Warn "Installation succeeded but 'link' is not on PATH in this session."
    Write-Warn "Open a NEW PowerShell window and run: link --version"
    Write-Warn "If it still fails, run: pipx ensurepath"
}
