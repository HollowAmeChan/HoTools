@echo off
setlocal

:: ===========================================================================
:: HoTools native 快速编译脚本
:: 路径说明：
::   MSBUILD_EXE   —— VS 2022 Community MSBuild 可执行文件
::   BUILD_DIR_311 —— Blender 4.5 / Python 3.11 的 cmake 构建目录
::   BUILD_DIR_313 —— Blender 5.x  / Python 3.13 的 cmake 构建目录
:: ===========================================================================
set MSBUILD_EXE=D:\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe
set BUILD_DIR_311=%~dp0build\vs2022-py311
set BUILD_DIR_313=%~dp0build\vs2022-py313

:: 默认编译两个版本；传入参数 311 则只编译 py311；传入 313 则只编译 py313
set TARGET=all
if "%1"=="311" set TARGET=311
if "%1"=="313" set TARGET=313

echo.
echo ========================================
echo  HoTools native 编译
echo  目标: %TARGET%
echo ========================================
echo.

if "%TARGET%"=="311" goto build311
if "%TARGET%"=="313" goto build313
if "%TARGET%"=="all" goto buildall
goto build311

:build311
echo [py311]  构建目录: %BUILD_DIR_311%
"%MSBUILD_EXE%" "%BUILD_DIR_311%\hotools_native.sln" /p:Configuration=Release /p:Platform=x64 /v:minimal /m
if %errorlevel% neq 0 ( echo [ERROR] py311 编译失败 & exit /b 1 )
echo [OK] py311 编译完成
goto end

:build313
echo [py313]  构建目录: %BUILD_DIR_313%
"%MSBUILD_EXE%" "%BUILD_DIR_313%\hotools_native.sln" /p:Configuration=Release /p:Platform=x64 /v:minimal /m
if %errorlevel% neq 0 ( echo [ERROR] py313 编译失败 & exit /b 1 )
echo [OK] py313 编译完成
goto end

:buildall
call :do_build "%BUILD_DIR_311%" py311
if %errorlevel% neq 0 exit /b 1
call :do_build "%BUILD_DIR_313%" py313
if %errorlevel% neq 0 exit /b 1
goto end

:do_build
echo [%~2]  构建目录: %~1
"%MSBUILD_EXE%" "%~1\hotools_native.sln" /p:Configuration=Release /p:Platform=x64 /v:minimal /m
if %errorlevel% neq 0 ( echo [ERROR] %~2 编译失败 & exit /b 1 )
echo [OK] %~2 编译完成
exit /b 0

:end
echo.
echo 产物路径:
if "%TARGET%"=="311" echo   _Lib\py311\HotoolsPackage\hotools_native.cp311-win_amd64.pyd
if "%TARGET%"=="313" echo   _Lib\py313\HotoolsPackage\hotools_native.cp313-win_amd64.pyd
if "%TARGET%"=="all" (
    echo   _Lib\py311\HotoolsPackage\hotools_native.cp311-win_amd64.pyd
    echo   _Lib\py313\HotoolsPackage\hotools_native.cp313-win_amd64.pyd
)
echo.
endlocal
