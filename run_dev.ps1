cd "C:\PyCharm\PyCharm_Projects\PythonProject\Italus novel"

.\.venv\Scripts\Activate.ps1

Write-Host ""
Write-Host "==========================================="
Write-Host " Narrative Studio Development Server"
Write-Host "==========================================="
Write-Host ""

python -m uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8010

Start-Process "http://127.0.0.1:8010"