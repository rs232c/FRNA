@echo off
echo ==================================================
echo FRNA Process Killer (Windows Batch)
echo ==================================================
echo This will kill ALL Python processes!
echo Make sure to save any important work first.
echo.
echo Press any key to continue, or Ctrl+C to cancel...
#pause > nul

echo.
echo [PYTHON] Killing Python processes...
taskkill /F /IM python.exe /T 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Killed python.exe processes
) else (
    echo [WARNING] No python.exe processes found
)

taskkill /F /IM python3.exe /T 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Killed python3.exe processes
) else (
    echo [WARNING] No python3.exe processes found
)

taskkill /F /IM pythonw.exe /T 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Killed pythonw.exe processes
) else (
    echo [WARNING] No pythonw.exe processes found
)

taskkill /F /IM py.exe /T 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Killed py.exe processes
) else (
    echo [WARNING] No py.exe processes found
)

echo.
echo ==================================================
echo [SUCCESS] All Python processes killed!
echo You can now restart the FRNA server safely.
echo ==================================================
echo.
#pause