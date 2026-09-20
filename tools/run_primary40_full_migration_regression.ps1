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
$Runner = Join-Path $RepoPath "tools\primary40_full_migration_regression.py"

if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Primary 40 regression runner is missing: $Runner"
}

$PythonExe = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python executable not found."
    }
    $PythonExe = $PythonCommand.Source
}

Push-Location $RepoPath
$OldPythonPath = $env:PYTHONPATH
$OldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH = $RepoPath
    $env:PYTHONDONTWRITEBYTECODE = "1"

    & $PythonExe $Runner
    if ($LASTEXITCODE -ne 0) {
        throw "Primary 40 consolidated regression failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PYTHONPATH = $OldPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $OldNoBytecode
    Pop-Location
}

Write-Host "PRIMARY40 RUNNER: PASS"
