@echo off
:: HoTools native 依赖初始化脚本
:: 在 _native/ 目录下执行：setup_extern.bat

setlocal
set SCRIPT_DIR=%~dp0

echo.
echo ========================================
echo  HoTools native extern 依赖初始化
echo ========================================
echo.
echo 此脚本将 nanobind 和 JoltPhysics 作为 git submodule 克隆到 extern/ 目录。
echo 克隆完成后 IDE 可直接解析头文件引用，无需网络也能构建。
echo.

:: 检查是否在 git 仓库内
git rev-parse --git-dir >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 当前目录不在 git 仓库中，请从仓库根目录执行此脚本。
    exit /b 1
)

:: 进入 _native 目录（脚本所在目录）
pushd "%SCRIPT_DIR%"

echo [1/2] 添加 nanobind submodule...
if exist "extern\nanobind\CMakeLists.txt" (
    echo       已存在，跳过。
) else (
    git submodule add --depth 1 https://github.com/wjakob/nanobind.git extern/nanobind
    if %errorlevel% neq 0 ( echo [ERROR] nanobind 添加失败 & exit /b 1 )
)

echo [2/2] 添加 JoltPhysics submodule...
if exist "extern\JoltPhysics\Build\CMakeLists.txt" (
    echo       已存在，跳过。
) else (
    git submodule add --depth 1 https://github.com/jrouwe/JoltPhysics.git extern/JoltPhysics
    if %errorlevel% neq 0 ( echo [ERROR] JoltPhysics 添加失败 & exit /b 1 )
)

echo.
echo [OK] submodule 初始化完成。
echo.
echo 头文件路径（添加到 IDE include 路径）：
echo   extern\nanobind\include\
echo   extern\JoltPhysics\
echo.
echo 后续其他人克隆仓库后，运行：
echo   git submodule update --init --recursive --depth 1
echo.

popd
endlocal
