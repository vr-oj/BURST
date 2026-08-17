[CmdletBinding()]
param(
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string]$InnoCompiler = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    $python = (Resolve-Path -LiteralPath $PythonPath).Path
    $version = (Get-Content -LiteralPath "buti_app\VERSION" -Raw).Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?$') {
        throw "Invalid version in buti_app\VERSION: $version"
    }

    & $python -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "The Python environment contains broken requirements."
    }

    if (-not $SkipTests) {
        & $python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "The BURST test suite failed."
        }
    }

    & $python -m PyInstaller --noconfirm --clean BURST.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    if ($InnoCompiler) {
        $iscc = (Resolve-Path -LiteralPath $InnoCompiler).Path
    }
    else {
        $innoCandidates = @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $iscc = $innoCandidates |
            Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
            Select-Object -First 1
    }

    if (-not $iscc) {
        throw "Inno Setup 6 was not found. Install it or pass -InnoCompiler."
    }

    & $iscc installer.iss
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed."
    }

    $installer = Join-Path $repoRoot "installer_output\BURST_Setup_$version.exe"
    if (-not (Test-Path -LiteralPath $installer)) {
        throw "Expected installer was not created: $installer"
    }

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLower()
    $filename = Split-Path -Leaf $installer
    $checksum = "$installer.sha256"
    $checksumLine = "$hash  $filename`r`n"
    [System.IO.File]::WriteAllText(
        $checksum,
        $checksumLine,
        [System.Text.Encoding]::ASCII
    )

    Write-Host ""
    Write-Host "BURST v$version release package is ready:" -ForegroundColor Green
    Write-Host "  Installer: $installer"
    Write-Host "  Checksum:  $checksum"
    Write-Host "  SHA-256:   $hash"
}
finally {
    Pop-Location
}
