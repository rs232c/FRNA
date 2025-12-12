@echo off
py .\quick_regenerate.py
echo Starting Fall River News Admin Panel...
echo.
echo Admin Panel: http://localhost:8000/admin
echo Login: admin / admin
echo.
python admin.py
pause
