@echo off
setlocal
cd /d "%~dp0"
title Skyrim Tracker Extreme - build

echo Skyrim Tracker Extreme: building the exe
echo.
where cargo >nul 2>&1 || (echo Rust ^(cargo^) was not found. Install Rust first - see BUILD.md. & goto fail)
cargo --version
echo.

rem no local folder names in the exe (user folder, Desktop): source paths are remapped,
rem and the debug-file path keeps only its file name
set "RUSTFLAGS=-C link-arg=/PDBALTPATH:%%_PDB%%"
call :remap "%USERPROFILE%" "~"
if defined CARGO_HOME call :remap "%CARGO_HOME%" "cargo"

echo [1/3] Compiling...
cargo build --release || goto fail
echo.

echo [2/3] Collecting dist\...
set "OUT=dist\Skyrim Tracker Extreme"
if not exist "%OUT%" mkdir "%OUT%"
copy /y "target\release\skyrim-tracker-extreme.exe" "%OUT%\Skyrim Tracker Extreme.exe" >nul || goto fail
copy /y "LICENSE.txt" "%OUT%\" >nul
copy /y "docs\README.txt" "%OUT%\" >nul
copy /y "docs\THIRD_PARTY_NOTICES.txt" "%OUT%\" >nul
if not exist "%OUT%\lang" mkdir "%OUT%\lang"
copy /y "docs\README_lang.txt" "%OUT%\lang\" >nul
echo.

rem the archive for Nexus: a clean copy of the release files (no data\ or language files from test runs)
echo [3/3] Packing the archive...
set "VER="
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "(ConvertFrom-Json (Get-Content -Raw 'src-tauri\tauri.conf.json')).version"`) do set "VER=%%v"
if not defined VER (echo Cannot read the version from src-tauri\tauri.conf.json. & goto fail)
set "PACK=%TEMP%\ste-pack"
set "ZIP=dist\Skyrim Tracker Extreme v%VER%.zip"
if exist "%PACK%" rmdir /s /q "%PACK%"
mkdir "%PACK%\Skyrim Tracker Extreme\lang" || goto fail
copy /y "%OUT%\Skyrim Tracker Extreme.exe" "%PACK%\Skyrim Tracker Extreme\" >nul || goto fail
copy /y "LICENSE.txt" "%PACK%\Skyrim Tracker Extreme\" >nul || goto fail
copy /y "docs\README.txt" "%PACK%\Skyrim Tracker Extreme\" >nul || goto fail
copy /y "docs\THIRD_PARTY_NOTICES.txt" "%PACK%\Skyrim Tracker Extreme\" >nul || goto fail
copy /y "docs\README_lang.txt" "%PACK%\Skyrim Tracker Extreme\lang\" >nul || goto fail
if exist "%ZIP%" del /q "%ZIP%"
tar -a -c -f "%ZIP%" -C "%PACK%" "Skyrim Tracker Extreme" || goto fail
rmdir /s /q "%PACK%"
echo.
echo Done: %OUT%\Skyrim Tracker Extreme.exe
echo Archive: %ZIP%
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1

rem adds --remap-path-prefix for a folder (skipped if its path has spaces: RUSTFLAGS splits on them)
:remap
set "P=%~1"
if not "%P: =%"=="%P%" exit /b 0
set "RUSTFLAGS=%RUSTFLAGS% --remap-path-prefix=%P%=%~2"
exit /b 0
