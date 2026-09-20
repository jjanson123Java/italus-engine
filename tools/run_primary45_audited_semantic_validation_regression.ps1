param(
    [string]$RepoPath = "C:\PyCharm\PyCharm_Projects\PythonProject\Italus novel"
)
$ErrorActionPreference = "Stop"
$PythonExe = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}
Push-Location $RepoPath
$OldPythonPath = $env:PYTHONPATH
$OldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH = $RepoPath
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $PythonExe "tools\primary45_audited_semantic_validation_regression.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Primary 45 regression failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PYTHONPATH = $OldPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $OldNoBytecode
    Pop-Location
}
