param(
    [string]$RepoPath = "C:\PyCharm\PyCharm_Projects\PythonProject\Italus novel"
)
$ErrorActionPreference = "Stop"
$RepoPath = [IO.Path]::GetFullPath($RepoPath)
$Python = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project Python not found: $Python"
}
Push-Location $RepoPath
$OldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $RepoPath
    & $Python "tools\primary42_bounded_generation_prompt_authority_regression.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Primary 42 regression failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PYTHONPATH = $OldPythonPath
    Pop-Location
}
