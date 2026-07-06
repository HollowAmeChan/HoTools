@echo off
setlocal EnableExtensions

rem ============================================================================
rem HoTools native build helper
rem
rem Usage:
rem   build.bat          Build py311 and py313
rem   build.bat all      Build py311 and py313
rem   build.bat 311      Build Blender 4.5 / Python 3.11
rem   build.bat py311    Build Blender 4.5 / Python 3.11
rem   build.bat 313      Build Blender 5.x / Python 3.13
rem   build.bat py313    Build Blender 5.x / Python 3.13
rem
rem Optional override:
rem   set CMAKE_EXE=C:\path\to\cmake.exe
rem ============================================================================

for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"
set "BUILD_DIR_311=%SOURCE_DIR%\build\vs2022-py311"
set "BUILD_DIR_313=%SOURCE_DIR%\build\vs2022-py313"

set "TARGET=%~1"
set "USAGE_EXIT=2"
if not defined TARGET set "TARGET=all"
if /I "%TARGET%"=="py311" set "TARGET=311"
if /I "%TARGET%"=="py313" set "TARGET=313"

if not "%~2"=="" goto usage
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
echo  Target: %TARGET%
echo  CMake:  %CMAKE_EXE%
echo ========================================
echo.

if /I "%TARGET%"=="311" (
    call :build_one "vs2022-py311" "vs2022-py311-release" "py311" "%BUILD_DIR_311%"
    if errorlevel 1 goto fail
    goto success
)

if /I "%TARGET%"=="313" (
    call :build_one "vs2022-py313" "vs2022-py313-release" "py313" "%BUILD_DIR_313%"
    if errorlevel 1 goto fail
    goto success
)

call :build_one "vs2022-py311" "vs2022-py311-release" "py311" "%BUILD_DIR_311%"
if errorlevel 1 goto fail
call :build_one "vs2022-py313" "vs2022-py313-release" "py313" "%BUILD_DIR_313%"
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

"%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --parallel
if errorlevel 1 (
    echo [ERROR] %LABEL% build failed.
    exit /b 1
)

echo [OK] %LABEL% build completed.
echo.
exit /b 0

:success
echo.
echo Output modules:
if /I "%TARGET%"=="311" (
    echo   _Lib\py311\HotoolsPackage\hotools_native.cp311-win_amd64.pyd
    echo   _Lib\py311\HotoolsPackage\hotools_jolt.cp311-win_amd64.pyd
) else if /I "%TARGET%"=="313" (
    echo   _Lib\py313\HotoolsPackage\hotools_native.cp313-win_amd64.pyd
    echo   _Lib\py313\HotoolsPackage\hotools_jolt.cp313-win_amd64.pyd
) else (
    echo   _Lib\py311\HotoolsPackage\hotools_native.cp311-win_amd64.pyd
    echo   _Lib\py311\HotoolsPackage\hotools_jolt.cp311-win_amd64.pyd
    echo   _Lib\py313\HotoolsPackage\hotools_native.cp313-win_amd64.pyd
    echo   _Lib\py313\HotoolsPackage\hotools_jolt.cp313-win_amd64.pyd
)
echo.
popd >nul
endlocal
exit /b 0

:fail
popd >nul
endlocal
exit /b 1

:usage
echo Usage:
echo   build.bat          Build py311 and py313
echo   build.bat all      Build py311 and py313
echo   build.bat 311      Build Blender 4.5 / Python 3.11
echo   build.bat py311    Build Blender 4.5 / Python 3.11
echo   build.bat 313      Build Blender 5.x / Python 3.13
echo   build.bat py313    Build Blender 5.x / Python 3.13
exit /b %USAGE_EXIT%
