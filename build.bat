@echo off
setlocal
cd /d "%~dp0"
title Skyrim Tracker Extreme - build

echo === Skyrim Tracker Extreme: building the exe ===
echo.
where cargo >nul 2>&1 || (echo Rust ^(cargo^) was not found. Install Rust first - see BUILD.md. & goto fail)
cargo --version
echo.

echo [1/2] Compiling...
cargo build --release || goto fail
echo.

echo [2/2] Collecting dist\...
set "OUT=dist\Skyrim Tracker Extreme"
if not exist "%OUT%" mkdir "%OUT%"
copy /y "target\release\skyrim-tracker-extreme.exe" "%OUT%\Skyrim Tracker Extreme.exe" >nul || goto fail
copy /y "LICENSE.txt" "%OUT%\" >nul
copy /y "docs\README.txt" "%OUT%\" >nul
copy /y "docs\THIRD_PARTY_NOTICES.txt" "%OUT%\" >nul
echo.
echo Done: %OUT%\Skyrim Tracker Extreme.exe
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1
