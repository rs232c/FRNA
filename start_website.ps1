# PowerShell script to start FRNA Admin Panel
Write-Host "Starting Fall River News Admin Panel..." -ForegroundColor Green
Write-Host ""
Write-Host "Admin Panel: http://localhost:8000/admin" -ForegroundColor Cyan
Write-Host "Login: admin / admin" -ForegroundColor Yellow
Write-Host ""

# Run the unified server
python server.py

Write-Host ""
Write-Host "FRNA server stopped." -ForegroundColor Red
Read-Host "Press Enter to exit"
