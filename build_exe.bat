@echo off
title Nelumbo - build exe
REM ==================================================================
REM  Nelumbo Connectivity Utility Suite - build the exe with ONE double-click
REM  Keep this file next to app.py and ConnectivityUtility.spec.
REM  Result: dist\Nelumbo Connectivity Utility Suite.exe  (the folder opens at the end)
REM ==================================================================
cd /d "%~dp0"
set "EXE=Nelumbo Connectivity Utility Suite.exe"

echo [1/5] Python ...
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
"%PY%" --version || (echo Python not found & pause & exit /b 1)

echo [2/5] PyInstaller / Pillow ...
"%PY%" -m PyInstaller --version >nul 2>&1 || "%PY%" -m pip install pyinstaller
"%PY%" -c "import PIL" >nul 2>&1 || "%PY%" -m pip install pillow

echo [3/5] Closing a running copy and removing the old build ...
taskkill /f /im "%EXE%" >nul 2>&1
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
for %%f in (views database) do @if exist "%%f\__pycache__" rmdir /s /q "%%f\__pycache__"

echo [4/5] Building (1-3 minutes) ...
"%PY%" -m PyInstaller --noconfirm ConnectivityUtility.spec
if errorlevel 1 (echo. & echo ***** BUILD FAILED - see the messages above ***** & pause & exit /b 1)

echo [5/5] Refreshing the Windows icon cache (the taskbar briefly disappears and comes back) ...
REM Windows keeps the icon of an exe path in a cache: after a rebuild it would keep showing the old /
REM default icon. Clearing the cache and restarting Explorer makes it read the new exe icon.
ie4uinit.exe -show >nul 2>&1
taskkill /f /im explorer.exe >nul 2>&1
del /a /q "%LOCALAPPDATA%\IconCache.db" >nul 2>&1
del /a /q "%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db" >nul 2>&1
start explorer.exe
timeout /t 3 /nobreak >nul

echo.
echo DONE:  %~dp0dist\%EXE%
explorer "%~dp0dist"
pause