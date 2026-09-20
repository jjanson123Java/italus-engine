param(
    [string]$RepoPath = "C:\PyCharm\PyCharm_Projects\PythonProject\Italus novel"
)
$ErrorActionPreference = "Stop"
$Py = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py -PathType Leaf)) {
    $Py = (Get-Command python -ErrorAction Stop).Source
}
Push-Location $RepoPath
$OldPP=$env:PYTHONPATH
$OldBC=$env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH=$RepoPath
    $env:PYTHONDONTWRITEBYTECODE="1"
    & $Py "tools\primary44_rejection_aware_replacement_generation_regression.py"
    if ($LASTEXITCODE -ne 0) { throw "Primary 44 regression failed with exit code $LASTEXITCODE." }
}
finally {
    $env:PYTHONPATH=$OldPP
    $env:PYTHONDONTWRITEBYTECODE=$OldBC
    Pop-Location
}
