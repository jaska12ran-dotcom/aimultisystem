# PowerShell Development Runner for CodeTwin
Write-Host "Starting CodeTwin Backend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; .\venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8000"

Write-Host "Starting CodeTwin Frontend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"

Write-Host "CodeTwin services launched! Frontend: http://localhost:3000 | Backend: http://localhost:8000" -ForegroundColor Green
