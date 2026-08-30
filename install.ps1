#Requires -Version 5.1
<#
.SYNOPSIS
    The Link -- one-command local installer for Windows (PowerShell)

.DESCRIPTION
    What this script does:
      1. Checks for Python 3.10+
      2. Installs pipx if not present  (isolated app manager)
      3. Installs "the-link" from this local directory via pipx
      4. Adds pipx Scripts dir to the user PATH if needed
      5. Verifies the link command works

.EXAMPLE
    Run from the repository root (the directory that contains pyproject.toml):
    .\install.ps1
#>

$ErrorActionPreference = "Stop"

# Resolve repo root:
# $MyInvocation.MyCommand.Path is populated when the script is run from a file.
# Fall back to $PWD when invoked via iex/pipe.
if ($MyInvocation.MyCommand.Path) {
    $RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    $RepoRoot = $PWD.Path
}

$MinMajor = 3
$MinMinor = 10
$PythonArgs = @()

function Write-Info    { param([string]$Msg); Write-Host "[link] $Msg" -ForegroundColor Cyan }
function Write-Success { param([string]$Msg); Write-Host "[link] $Msg" -ForegroundColor Green }
function Write-Warn    { param([string]$Msg); Write-Host "[link] warning: $Msg" -ForegroundColor Yellow }
function Write-Err     { param([string]$Msg); Write-Host "[link] error: $Msg" -ForegroundColor Red; exit 1 }

# --- Step 1: Locate Python 3.10+ ---
Write-Info "Checking Python version..."

$Python = $null
foreach ($candidate in @("python", "python3")) {
    try {
        $ver = & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($ver) {
            $parts = $ver.Trim().Split(".")
            if (([int]$parts[0] -ge $MinMajor) -and ([int]$parts[1] -ge $MinMinor)) {
                $Python = $candidate
                break
            }
        }
    } catch { }
}

# Try Python Launcher (py -3.x) if plain python didn't work
if (-not $Python) {
    foreach ($minor in @(14, 13, 12, 11, 10)) {
        try {
            $ver = & py "-3.$minor" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver) {
                $Python = "py"
                $PythonArgs = @("-3.$minor")
                break
            }
        } catch { }
    }
}

if (-not $Python) {
    Write-Err "Python $MinMajor.$MinMinor+ not found. Install from https://www.python.org/downloads/ and re-run."
}

$PyVersion = (& $Python $PythonArgs --version 2>&1) -join ""
Write-Info "Using $PyVersion"

# --- Step 2: Install / upgrade pipx ---
Write-Info "Checking pipx..."

$UsePipxModule = $false
$pipxCmd = Get-Command pipx -ErrorAction SilentlyContinue

if (-not $pipxCmd) {
    Write-Info "pipx not found -- installing via pip..."
    & $Python $PythonArgs -m pip install --user pipx --quiet
    & $Python $PythonArgs -m pipx ensurepath 2>$null

    # Surface the newly-installed pipx bin to this session
    $extraPaths = @(
        (Join-Path $env:USERPROFILE "AppData\Roaming\Python\Scripts"),
        (Join-Path $env:USERPROFILE ".local\bin")
    )
    foreach ($p in $extraPaths) {
        if ((Test-Path $p) -and ($env:PATH -notlike "*$p*")) {
            $env:PATH = $p + ";" + $env:PATH
        }
    }

    $pipxCmd = Get-Command pipx -ErrorAction SilentlyContinue
    if (-not $pipxCmd) {
        Write-Warn "pipx not on PATH yet -- using python -m pipx fallback for this session."
        $UsePipxModule = $true
    }
}

Write-Info "pipx ready."

# --- Helper: run a pipx subcommand ---
function Invoke-Pipx {
    param([string[]]$PipxArgs)
    if ($UsePipxModule) {
        & $Python $PythonArgs -m pipx @PipxArgs
    } else {
        & pipx @PipxArgs
    }
}

# --- Step 3: Install the-link from local source ---
Write-Info "Installing The Link from: $RepoRoot"

if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    Write-Err "pyproject.toml not found in '$RepoRoot'. Run install.ps1 from the repository root."
}

# Uninstall any prior version so pipx does not attempt an upgrade from PyPI
try {
    $listOut = (Invoke-Pipx @("list")) 2>&1
    if ("$listOut" -match "the-link") {
        Write-Info "Existing installation found -- removing before reinstall..."
        Invoke-Pipx @("uninstall", "the-link") 2>&1 | Out-Null
    }
} catch { }

# Install directly from the local directory (no network required)
Invoke-Pipx @("install", $RepoRoot)

# --- Step 4: Ensure pipx Scripts directory is on user PATH ---
Write-Info "Ensuring 'link' is available on PATH..."

$pipxBinDirs = @(
    (Join-Path $env:USERPROFILE ".local\bin"),
    (Join-Path $env:USERPROFILE "AppData\Roaming\Python\Scripts")
)

$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
foreach ($p in $pipxBinDirs) {
    if ((Test-Path $p) -and ($userPath -notlike "*$p*")) {
        $newPath = $userPath + ";" + $p
        [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        $env:PATH = $env:PATH + ";" + $p
        Write-Info "Added $p to user PATH."
    }
}

# Also call pipx ensurepath to register its own bin dir
try { Invoke-Pipx @("ensurepath") 2>&1 | Out-Null } catch { }

# --- Step 5: Verify ---
# Add pipx venv Scripts to current session so link is findable immediately
$pipxVenvScripts = Join-Path $env:USERPROFILE "AppData\Local\pipx\venvs\the-link\Scripts"
if ((Test-Path $pipxVenvScripts) -and ($env:PATH -notlike "*$pipxVenvScripts*")) {
    $env:PATH = $pipxVenvScripts + ";" + $env:PATH
}

$linkCmd = Get-Command link -ErrorAction SilentlyContinue

if ($linkCmd) {
    $Ver = (& link --version 2>&1) -join ""
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
} else {
    Write-Warn "Installation succeeded but 'link' is not on PATH in this session."
    Write-Warn "Open a NEW PowerShell window and run: link --version"
    Write-Warn "If it still fails, run: pipx ensurepath"
}
