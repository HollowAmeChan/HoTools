@echo off
setlocal EnableExtensions

rem ============================================================================
rem HoTools native build helper
rem
rem Usage:
rem   build.bat          Build hotools_native for py311 and py313
rem   build.bat all      Build both modules for py311 and py313
rem   build.bat 311      Build hotools_native for Blender 4.5 / Python 3.11
rem   build.bat py311    Build Blender 4.5 / Python 3.11
rem   build.bat 313      Build hotools_native for Blender 5.x / Python 3.13
rem   build.bat py313    Build Blender 5.x / Python 3.13
rem   build.bat native   Build hotools_native for py311 and py313
rem   build.bat 313 native  Build only hotools_native for Python 3.13
rem   build.bat 313 jolt    Build only hotools_jolt for Python 3.13
rem   build.bat 313 all     Build both modules for Python 3.13
rem
rem Optional override:
rem   set CMAKE_EXE=C:\path\to\cmake.exe
rem ============================================================================

for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"
set "TARGET=%~1"
set "MODULE=%~2"
set "USAGE_EXIT=2"
if not defined TARGET (
    set "TARGET=all"
    set "MODULE=native"
)
if not defined MODULE (
    if /I "%TARGET%"=="all" (
        set "MODULE=all"
    ) else (
        set "MODULE=native"
    )
)
if /I "%TARGET%"=="native" (
    set "TARGET=all"
    set "MODULE=native"
)
if /I "%TARGET%"=="jolt" (
    set "TARGET=all"
    set "MODULE=jolt"
)
if /I "%TARGET%"=="py311" set "TARGET=311"
if /I "%TARGET%"=="py313" set "TARGET=313"
if /I "%MODULE%"=="hotools_native" set "MODULE=native"
if /I "%MODULE%"=="hotools_jolt" set "MODULE=jolt"

if not "%~3"=="" goto usage
if /I "%TARGET%"=="help" (
    set "USAGE_EXIT=0"
    goto usage
)
if /I "%TARGET%"=="-h" (
    set "USAGE_EXIT=0"
    goto usage
)
if /I "%TARGET%"=="--help" (
    set "USAGE_EXIT=0"
    goto usage
)
if /I "%TARGET%"=="311" goto main
if /I "%TARGET%"=="313" goto main
if /I "%TARGET%"=="all" goto main
goto usage

:main
if /I "%MODULE%"=="all" set "CMAKE_TARGET="
if /I "%MODULE%"=="native" set "CMAKE_TARGET=hotools_native"
if /I "%MODULE%"=="jolt" set "CMAKE_TARGET=hotools_jolt"
if not defined CMAKE_TARGET if /I not "%MODULE%"=="all" goto usage

set "CONFIG_PRESET_311=vs2022-py311"
set "BUILD_PRESET_311=vs2022-py311-release"
set "BUILD_DIR_311=%SOURCE_DIR%\build\vs2022-py311"
set "CONFIG_PRESET_313=vs2022-py313"
set "BUILD_PRESET_313=vs2022-py313-release"
set "BUILD_DIR_313=%SOURCE_DIR%\build\vs2022-py313"
if /I "%MODULE%"=="native" (
    set "CONFIG_PRESET_311=vs2022-py311-native"
    set "BUILD_PRESET_311=vs2022-py311-native-release"
    set "BUILD_DIR_311=%SOURCE_DIR%\build\vs2022-py311-native"
    set "CONFIG_PRESET_313=vs2022-py313-native"
    set "BUILD_PRESET_313=vs2022-py313-native-release"
    set "BUILD_DIR_313=%SOURCE_DIR%\build\vs2022-py313-native"
)
if /I "%MODULE%"=="jolt" (
    set "CONFIG_PRESET_311=vs2022-py311-jolt"
    set "BUILD_PRESET_311=vs2022-py311-jolt-release"
    set "BUILD_DIR_311=%SOURCE_DIR%\build\vs2022-py311-jolt"
    set "CONFIG_PRESET_313=vs2022-py313-jolt"
    set "BUILD_PRESET_313=vs2022-py313-jolt-release"
    set "BUILD_DIR_313=%SOURCE_DIR%\build\vs2022-py313-jolt"
)

pushd "%SOURCE_DIR%" >nul
if errorlevel 1 (
    echo [ERROR] Failed to enter source directory: %SOURCE_DIR%
    exit /b 1
)

call :find_cmake
if errorlevel 1 goto fail

echo.
echo ========================================
echo  HoTools native build
echo  Python: %TARGET%
echo  Module: %MODULE%
echo  CMake:  %CMAKE_EXE%
echo ========================================
echo.

if /I "%TARGET%"=="311" (
    call :build_one "%CONFIG_PRESET_311%" "%BUILD_PRESET_311%" "py311" "%BUILD_DIR_311%" "%CMAKE_TARGET%"
    if errorlevel 1 goto fail
    goto success
)

if /I "%TARGET%"=="313" (
    call :build_one "%CONFIG_PRESET_313%" "%BUILD_PRESET_313%" "py313" "%BUILD_DIR_313%" "%CMAKE_TARGET%"
    if errorlevel 1 goto fail
    goto success
)

call :build_one "%CONFIG_PRESET_311%" "%BUILD_PRESET_311%" "py311" "%BUILD_DIR_311%" "%CMAKE_TARGET%"
if errorlevel 1 goto fail
call :build_one "%CONFIG_PRESET_313%" "%BUILD_PRESET_313%" "py313" "%BUILD_DIR_313%" "%CMAKE_TARGET%"
if errorlevel 1 goto fail
goto success

:find_cmake
if defined CMAKE_EXE (
    if exist "%CMAKE_EXE%" exit /b 0
    echo [ERROR] CMAKE_EXE is set but does not exist: %CMAKE_EXE%
    exit /b 1
)

set "CMAKE_EXE=D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
if exist "%CMAKE_EXE%" exit /b 0

set "CMAKE_EXE="
for %%I in (cmake.exe) do set "CMAKE_EXE=%%~$PATH:I"
if defined CMAKE_EXE exit /b 0

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
    for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.Component.MSBuild -find Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe`) do (
        if not defined CMAKE_EXE set "CMAKE_EXE=%%I"
    )
)
if defined CMAKE_EXE if exist "%CMAKE_EXE%" exit /b 0

echo [ERROR] Could not find cmake.exe.
echo         Install Visual Studio 2022 with C++ tools, or set CMAKE_EXE before running this script.
exit /b 1

:build_one
set "CONFIG_PRESET=%~1"
set "BUILD_PRESET=%~2"
set "LABEL=%~3"
set "BUILD_DIR=%~4"
set "BUILD_TARGET=%~5"
set "NATIVE_LAYOUT_HEADER=%SOURCE_DIR%\src\mc2_context_internal.hpp"
set "DOMAIN_LAYOUT_HEADER=%SOURCE_DIR%\src\mc2_domain_cpu.hpp"
set "NATIVE_LAYOUT_STAMP=%BUILD_DIR%\.mc2_context_layout.stamp"
set "REBUILD_NATIVE_LAYOUT=0"

echo [%LABEL%] Configure preset: %CONFIG_PRESET%
echo [%LABEL%] Build preset:     %BUILD_PRESET%
echo [%LABEL%] Build dir:        %BUILD_DIR%

if not exist "%BUILD_DIR%\CMakeCache.txt" (
    echo [%LABEL%] CMakeCache.txt not found; configuring first...
    "%CMAKE_EXE%" --preset "%CONFIG_PRESET%" -S "%SOURCE_DIR%"
    if errorlevel 1 (
        echo [ERROR] %LABEL% configure failed.
        exit /b 1
    )
)

if /I "%BUILD_TARGET%"=="hotools_native" (
    for /f %%I in ('powershell.exe -NoProfile -Command "$h1=Get-Item -LiteralPath '%NATIVE_LAYOUT_HEADER%'; $h2=Get-Item -LiteralPath '%DOMAIN_LAYOUT_HEADER%'; $s=Get-Item -LiteralPath '%NATIVE_LAYOUT_STAMP%' -ErrorAction SilentlyContinue; if ($null -eq $s -or $h1.LastWriteTimeUtc -gt $s.LastWriteTimeUtc -or $h2.LastWriteTimeUtc -gt $s.LastWriteTimeUtc) { '1' } else { '0' }"') do set "REBUILD_NATIVE_LAYOUT=%%I"
)

if defined BUILD_TARGET (
    if "%REBUILD_NATIVE_LAYOUT%"=="1" (
        echo [%LABEL%] Shared MC2 context layout changed; rebuilding hotools_native only.
        "%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --target "%BUILD_TARGET%" --clean-first --parallel
    ) else (
        "%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --target "%BUILD_TARGET%" --parallel
    )
) else (
    "%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --parallel
)
if errorlevel 1 (
    echo [ERROR] %LABEL% build failed.
    exit /b 1
)

echo [OK] %LABEL% build completed.
if "%REBUILD_NATIVE_LAYOUT%"=="1" type nul > "%NATIVE_LAYOUT_STAMP%"
echo.
exit /b 0

:success
echo.
echo Output modules:
if /I "%TARGET%"=="311" (
    call :print_outputs "py311" "cp311"
) else if /I "%TARGET%"=="313" (
    call :print_outputs "py313" "cp313"
) else (
    call :print_outputs "py311" "cp311"
    call :print_outputs "py313" "cp313"
)
echo.
popd >nul
endlocal
exit /b 0

:print_outputs
if /I "%MODULE%"=="all" echo   _Lib\%~1\HotoolsPackage\hotools_native.%~2-win_amd64.pyd
if /I "%MODULE%"=="native" echo   _Lib\%~1\HotoolsPackage\hotools_native.%~2-win_amd64.pyd
if /I "%MODULE%"=="all" echo   _Lib\%~1\HotoolsPackage\hotools_jolt.%~2-win_amd64.pyd
if /I "%MODULE%"=="jolt" echo   _Lib\%~1\HotoolsPackage\hotools_jolt.%~2-win_amd64.pyd
exit /b 0

:fail
popd >nul
endlocal
exit /b 1

:usage
echo Usage:
echo   build.bat          Build hotools_native for py311 and py313
echo   build.bat all      Build both modules for py311 and py313
echo   build.bat 311      Build hotools_native for Blender 4.5 / Python 3.11
echo   build.bat py311    Build Blender 4.5 / Python 3.11
echo   build.bat 313      Build hotools_native for Blender 5.x / Python 3.13
echo   build.bat py313    Build Blender 5.x / Python 3.13
echo   build.bat native       Build only hotools_native for py311 and py313
echo   build.bat jolt         Build only hotools_jolt for py311 and py313
echo   build.bat 313 native   Build only hotools_native for Python 3.13
echo   build.bat 313 jolt     Build only hotools_jolt for Python 3.13
echo   build.bat 313 all      Build both modules for Python 3.13
exit /b %USAGE_EXIT%
