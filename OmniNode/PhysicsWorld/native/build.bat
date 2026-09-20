@echo off
setlocal EnableExtensions

rem ============================================================================
rem HoTools-Omninode-Physics native build helper
rem
rem 本工程自持物理世界的原生模块，产物写入 native\runtime\<abi>\，不写入父仓 _Lib：
rem   hotools_physics   MC2 / Field / XPBD / SpringVRM / RigidWriteback
rem   hotools_jolt      Jolt Physics 刚体/约束后端
rem
rem Usage:
rem   build.bat                  Build both modules for py311 and py313
rem   build.bat all              Build both modules for py311 and py313
rem   build.bat 311              Build both modules for Blender 4.5 / Python 3.11
rem   build.bat 313              Build both modules for Blender 5.x / Python 3.13
rem   build.bat physics          Build only hotools_physics for py311 and py313
rem   build.bat jolt             Build only hotools_jolt for py311 and py313
rem   build.bat 313 physics      Build only hotools_physics for Python 3.13
rem   build.bat 313 jolt         Build only hotools_jolt for Python 3.13
rem
rem Optional overrides:
rem   set CMAKE_EXE=C:\path\to\cmake.exe
rem   set HOTOOLS_FETCH_CACHE=<父仓>\_native\.fetch-cache   (复用 nanobind 源码缓存)
rem ============================================================================

for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"
set "TARGET=%~1"
set "MODULE=%~2"
set "USAGE_EXIT=2"
if not defined TARGET (
    set "TARGET=all"
    set "MODULE=all"
)
if not defined MODULE (
    if /I "%TARGET%"=="all" (
        set "MODULE=all"
    ) else if /I "%TARGET%"=="311" (
        set "MODULE=all"
    ) else if /I "%TARGET%"=="313" (
        set "MODULE=all"
    ) else (
        set "MODULE=all"
    )
)
if /I "%TARGET%"=="physics" (
    set "TARGET=all"
    set "MODULE=physics"
)
if /I "%TARGET%"=="jolt" (
    set "TARGET=all"
    set "MODULE=jolt"
)
if /I "%TARGET%"=="py311" set "TARGET=311"
if /I "%TARGET%"=="py313" set "TARGET=313"
if /I "%MODULE%"=="hotools_physics" set "MODULE=physics"
if /I "%MODULE%"=="hotools_jolt" set "MODULE=jolt"
if /I "%MODULE%"=="native" set "MODULE=physics"

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
if /I "%MODULE%"=="physics" set "CMAKE_TARGET=hotools_physics"
if /I "%MODULE%"=="jolt" set "CMAKE_TARGET=hotools_jolt"
if not defined CMAKE_TARGET if /I not "%MODULE%"=="all" goto usage

set "CONFIG_PRESET_311=vs2022-py311"
set "BUILD_PRESET_311=vs2022-py311-release"
set "BUILD_DIR_311=%SOURCE_DIR%\build\vs2022-py311"
set "CONFIG_PRESET_313=vs2022-py313"
set "BUILD_PRESET_313=vs2022-py313-release"
set "BUILD_DIR_313=%SOURCE_DIR%\build\vs2022-py313"
if /I "%MODULE%"=="physics" (
    set "CONFIG_PRESET_311=vs2022-py311-physics"
    set "BUILD_PRESET_311=vs2022-py311-physics-release"
    set "BUILD_DIR_311=%SOURCE_DIR%\build\vs2022-py311-physics"
    set "CONFIG_PRESET_313=vs2022-py313-physics"
    set "BUILD_PRESET_313=vs2022-py313-physics-release"
    set "BUILD_DIR_313=%SOURCE_DIR%\build\vs2022-py313-physics"
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
echo  HoTools Physics native build
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
set "FRAME_LAYOUT_HEADER=%SOURCE_DIR%\src\mc2\mc2_frame_orientations.hpp"
set "DOMAIN_LAYOUT_HEADER=%SOURCE_DIR%\src\mc2\mc2_domain_cpu.hpp"
set "FIELD_LAYOUT_HEADER=%SOURCE_DIR%\src\field\field_runtime.hpp"
set "NATIVE_LAYOUT_STAMP=%BUILD_DIR%\.mc2_native_layout.stamp"
set "REBUILD_NATIVE_LAYOUT=0"
set "CHECK_NATIVE_LAYOUT=0"

echo [%LABEL%] Configure preset: %CONFIG_PRESET%
echo [%LABEL%] Build preset:     %BUILD_PRESET%
echo [%LABEL%] Build dir:        %BUILD_DIR%
if defined HOTOOLS_FETCH_CACHE echo [%LABEL%] Fetch cache:      %HOTOOLS_FETCH_CACHE%

echo [%LABEL%] Refreshing preset cache and runtime output path...
if defined HOTOOLS_FETCH_CACHE (
    "%CMAKE_EXE%" --preset "%CONFIG_PRESET%" -S "%SOURCE_DIR%" -DHOTOOLS_PHYSICS_FETCH_CACHE="%HOTOOLS_FETCH_CACHE%"
) else (
    "%CMAKE_EXE%" --preset "%CONFIG_PRESET%" -S "%SOURCE_DIR%"
)
if errorlevel 1 (
    echo [ERROR] %LABEL% configure failed.
    exit /b 1
)

rem MC2 / Field 的共享视图结构体布局由这三个头文件定义。任一变更都必须整体重建
rem hotools_physics，否则会出现“陈旧生产者 + 新消费者”的 ABI 错配
rem （对应 CMakeLists 里的 OBJECT_DEPENDS / set_source_files_properties 段）。
if /I "%BUILD_TARGET%"=="hotools_physics" set "CHECK_NATIVE_LAYOUT=1"
if /I "%MODULE%"=="all" set "CHECK_NATIVE_LAYOUT=1"
if "%CHECK_NATIVE_LAYOUT%"=="1" (
    for /f %%I in ('powershell.exe -NoProfile -Command "$h1=Get-Item -LiteralPath '%FRAME_LAYOUT_HEADER%'; $h2=Get-Item -LiteralPath '%DOMAIN_LAYOUT_HEADER%'; $h3=Get-Item -LiteralPath '%FIELD_LAYOUT_HEADER%'; $s=Get-Item -LiteralPath '%NATIVE_LAYOUT_STAMP%' -ErrorAction SilentlyContinue; if ($null -eq $s -or $h1.LastWriteTimeUtc -gt $s.LastWriteTimeUtc -or $h2.LastWriteTimeUtc -gt $s.LastWriteTimeUtc -or $h3.LastWriteTimeUtc -gt $s.LastWriteTimeUtc) { '1' } else { '0' }"') do set "REBUILD_NATIVE_LAYOUT=%%I"
)

if defined BUILD_TARGET (
    if "%REBUILD_NATIVE_LAYOUT%"=="1" (
        echo [%LABEL%] Shared Field/MC2 native layout changed; rebuilding hotools_physics only.
        "%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --target "%BUILD_TARGET%" --clean-first --parallel
    ) else (
        "%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --target "%BUILD_TARGET%" --parallel
    )
) else (
    if "%REBUILD_NATIVE_LAYOUT%"=="1" (
        echo [%LABEL%] Shared Field/MC2 native layout changed; clean rebuilding all modules.
        "%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --clean-first --parallel
    ) else (
        "%CMAKE_EXE%" --build --preset "%BUILD_PRESET%" --parallel
    )
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
if /I "%MODULE%"=="all" echo   native\runtime\%~1\hotools_physics.%~2-win_amd64.pyd
if /I "%MODULE%"=="physics" echo   native\runtime\%~1\hotools_physics.%~2-win_amd64.pyd
if /I "%MODULE%"=="all" echo   native\runtime\%~1\hotools_jolt.%~2-win_amd64.pyd
if /I "%MODULE%"=="jolt" echo   native\runtime\%~1\hotools_jolt.%~2-win_amd64.pyd
exit /b 0

:fail
popd >nul
endlocal
exit /b 1

:usage
echo Usage:
echo   build.bat                Build hotools_physics + hotools_jolt for py311 and py313
echo   build.bat all            Same as no argument
echo   build.bat 311            Build both modules for Blender 4.5 / Python 3.11
echo   build.bat 313            Build both modules for Blender 5.x / Python 3.13
echo   build.bat physics        Build only hotools_physics for py311 and py313
echo   build.bat jolt           Build only hotools_jolt for py311 and py313
echo   build.bat 313 physics    Build only hotools_physics for Python 3.13
echo   build.bat 313 jolt       Build only hotools_jolt for Python 3.13
echo.
echo Optional: set HOTOOLS_FETCH_CACHE to a directory to reuse FetchContent sources
echo           (e.g. the parent repo's _native\.fetch-cache).
exit /b %USAGE_EXIT%
