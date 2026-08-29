#Requires -Version 5.1
# The Link — uninstaller for Windows (PowerShell)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info { Write-Host "[link] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[link] $args" -ForegroundColor Green }

Write-Info "Uninstalling The Link..."

$pipxCmd = Get-Command pipx -ErrorAction SilentlyContinue

if ($pipxCmd) {
    $list = & pipx list 2>&1
    if ($list -match "the-link") {
        & pipx uninstall the-link
        Write-Success "The Link uninstalled."
    } else {
        Write-Info "The Link is not installed via pipx."
    }
} else {
    Write-Info "pipx not found. If you installed manually, run: pip uninstall the-link"
}
