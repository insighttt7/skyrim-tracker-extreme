@echo off
setlocal
cd /d "%~dp0"
title Skyrim Tracker Extreme - build

echo === Skyrim Tracker Extreme: building the exe ===
echo.

set "PY="
rem On GitHub Actions use the Python that setup-python installed
if defined CI set "PY=python"
if not defined PY py --version >nul 2>&1 && set "PY=py"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (echo Python was not found: neither "py" nor "python" works in this console. & goto fail)
echo Using: & %PY% --version
echo.
if not exist "assets\SkyrimTrackerExtreme.ico" (echo assets\SkyrimTrackerExtreme.ico is missing. & goto fail)

echo [1/4] Packing the page and CSVs...
%PY% tools\pack.py || goto fail
echo.

echo [2/4] Building with PyInstaller (1-3 minutes)...
%PY% -m PyInstaller --noconfirm --clean --windowed --log-level WARN ^
  --name "Skyrim Tracker Extreme" ^
  --contents-directory libs ^
  --icon "%~dp0assets\SkyrimTrackerExtreme.ico" ^
  --version-file "%~dp0_gen\version_info.txt" ^
  --paths "%~dp0_gen" ^
  --hidden-import bundle_data ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import webview.platforms.winforms ^
  --collect-data webview ^
  --distpath "%~dp0dist" ^
  --workpath "%~dp0_gen\work" ^
  --specpath "%~dp0_gen" ^
  "%~dp0_gen\app.py" || goto fail
echo.

echo [3/4] Release zip and SHA-256...
%PY% tools\pack.py --release || goto fail
echo.

echo [4/4] Cleaning up...
rmdir /s /q "_gen"
echo.
echo Done: dist\Skyrim Tracker Extreme\Skyrim Tracker Extreme.exe
echo       dist\SHA256.txt and the release zip are next to it
echo.
if not defined CI pause
exit /b 0

:fail
echo.
echo BUILD FAILED - send a screenshot of this window.
if not defined CI pause
exit /b 1
