cd "C:\PyCharm\PyCharm_Projects\PythonProject\Italus novel"

.\.venv\Scripts\Activate.ps1

Write-Host ""
Write-Host "==========================================="
Write-Host " Narrative Studio Development Server"
Write-Host "==========================================="
Write-Host ""

$ExistingListener = Get-NetTCPConnection `
    -LocalPort 8010 `
    -State Listen `
    -ErrorAction SilentlyContinue |
    Select-Object -First 1

if ($null -ne $ExistingListener) {
    Write-Error "Port 8010 is already in use. Stop the existing Italus backend before starting a new one."
    exit 1
}

python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8010

Start-Process "http://127.0.0.1:8010"