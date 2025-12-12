@echo off
echo ==================================================
echo Starting FRNA Admin Server
echo ==================================================
echo.
echo This will start the admin panel on:
echo http://localhost:8000/admin
echo.
echo Login: admin / admin
echo.
echo Press any key to continue, or Ctrl+C to cancel...
pause > nul

echo.
echo [STARTING] Fall River News Admin Panel...
echo.
python server.py
echo.
echo ==================================================
echo Admin server stopped.
echo ==================================================
pause