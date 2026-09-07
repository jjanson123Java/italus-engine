param(
    [string]$RepoPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = Split-Path -Parent $PSScriptRoot
}

if (-not (Test-Path -LiteralPath $RepoPath -PathType Container)) {
    throw "Repository path does not exist: $RepoPath"
}

$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
$Runner = Join-Path $RepoPath "tools\primary39_full_migration_regression.py"

if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Primary 39 regression runner is missing: $Runner"
}

Push-Location $RepoPath
$OldPythonPath = $env:PYTHONPATH
$OldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH = $RepoPath
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & python $Runner
    if ($LASTEXITCODE -ne 0) {
        throw "Primary 39 regression suite failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PYTHONPATH = $OldPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $OldNoBytecode
    Pop-Location
}

Write-Host "PRIMARY39 RUNNER: PASS"
