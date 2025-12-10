@echo off
echo Starting Fall River News Admin Panel...
echo.
echo Admin Panel: http://localhost:8000/admin
echo Login: admin / admin
echo.
python admin.py
pause
py .\quick_regenerate.py
