@echo off
::
:: HoTools Blender 插件 —— 构建/安装/重载/打包工具
::
:: 用法:
::   hotools <command> [blender_version] [--auto]
::
:: 命令:
::   package      打包 src/ 到 dist/
::   install      打包并安装到 Blender 扩展目录
::   uninstall    从 Blender 移除扩展
::   reload       卸载后重新安装
::   reload --auto 文件变动时自动重载
::   test         运行 flake8 检查
::   clean        清理构建产物
::   dev          install 的别名
::
:: Author: Lvoxx
::

setlocal enabledelayedexpansion

:: User Configurable Variables
set ADDON_NAME=HoTools
set SOURCE_DIR=./
set DIST_DIR=dist
set DEFAULT_BLENDER_VERSION=5.1

:: Initialize paths
set ROOT_DIR=%~dp0
set BLENDER_BASE=%APPDATA%\Blender Foundation\Blender
set OPERATION=help

:: Get current Git branch
set GIT_BRANCH=unknown
git rev-parse --abbrev-ref HEAD 2>nul >nul && (
    for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "GIT_BRANCH=%%b"
)

:: Parse command-line arguments
set AUTO_RELOAD=0
if not "%~1"=="" set OPERATION=%~1
:: Parse arg2/arg3 — accept --auto and blender version in either order
if not "%~2"=="" (
    if /i "%~2"=="--auto" (
        set AUTO_RELOAD=1
        if not "%~3"=="" set BLENDER_VERSION=%~3
    ) else (
        set BLENDER_VERSION=%~2
        if /i "%~3"=="--auto" set AUTO_RELOAD=1
    )
)
if not defined BLENDER_VERSION set BLENDER_VERSION=%DEFAULT_BLENDER_VERSION%

:: Calculate full paths
set FULL_SOURCE=%ROOT_DIR%%SOURCE_DIR%
set FULL_DIST=%ROOT_DIR%%DIST_DIR%
set ADDON_INSTALL_DIR=%BLENDER_BASE%\%BLENDER_VERSION%\extensions\user_default

:: Verify source directory exists
if not exist "%FULL_SOURCE%\" (
    echo [ERROR]: Source directory not found at %FULL_SOURCE%
    exit /b 1
)

:: Main command router
if /i "%OPERATION%"=="reload" (
    if "%AUTO_RELOAD%"=="1" goto reload_auto
    goto reload
)
goto %OPERATION% 2>nul || goto help

:: Help documentation
:help
echo.
echo ================================================
echo   HoTools Blender Addon - Build Script
echo ================================================
echo   Location : %ROOT_DIR%
echo   Branch   : !GIT_BRANCH!
echo ================================================
echo.
echo USAGE:
echo   hotools ^<command^> [blender_version] [--auto]
echo.
echo COMMANDS:
echo.
echo   package                Build zip into dist\HoTools_^<branch^>.zip
echo                          Runs cleanup + clean first, then zips src\
echo.
echo   install [version]      Package then copy src\ into Blender extensions dir
echo                          (extensions\user_default\HoTools). Verifies the
echo                          target Blender version is installed first
echo.
echo   uninstall [version]    Remove the extension folder from Blender extensions dir
echo.
echo   clean                  Delete dist\ and all *.pyc + __pycache__ artifacts
echo.
echo   test                   Run flake8 lint checks on src\ (requires flake8)
echo                          Exit code 1 on any lint error
echo.
echo   dev                    Package and install (alias for: hotools install)
echo.
echo   reload [version]       Uninstall then re-install
echo                          Faster re-deploy when Blender is already closed
echo.
echo   reload [version] --auto
echo                          Reload once, then watch src\ for file changes and
echo                          reload automatically on every save
echo                          Press Ctrl+C to stop watching
echo.
echo ARGUMENTS:
echo.
echo   [version]              Target Blender version (default: %DEFAULT_BLENDER_VERSION%)
echo                          Must match an installed Blender data folder
echo.
echo   --auto                 Enable file-watch auto-reload (only valid with reload)
echo                          Can appear before or after [version]:
echo                            hotools reload --auto
echo                            hotools reload --auto 5.1
echo                            hotools reload 5.1 --auto
echo.
echo BLENDER PATH:
echo   Base  : %BLENDER_BASE%
echo   Target: %ADDON_INSTALL_DIR%\%ADDON_NAME%
echo.
echo EXAMPLES:
echo   hotools package
echo   hotools install
echo   hotools install 4.2
echo   hotools uninstall 5.1
echo   hotools reload
echo   hotools reload --auto
echo   hotools reload --auto 4.2
echo   hotools test
echo   hotools clean
echo ================================================
goto :eof

:: Clean build artifacts
:clean
echo.
echo [INFO] Cleaning build artifacts...
if exist "%FULL_DIST%" rmdir /s /q "%FULL_DIST%"
if exist "%FULL_SOURCE%\*.pyc" del /s /q "%FULL_SOURCE%\*.pyc"
for /d /r "%FULL_SOURCE%" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
echo [SUCCESS] Clean done.
goto :eof

:: Remove stale generated node files from source
:cleanup_stale_nodes
set "RAMP_FILE=%FULL_SOURCE%\nodes\shader\lscherry\build_face_ramp.py"
set "INIT_FILE=%FULL_SOURCE%\nodes\shader\lscherry\__init__.py"
if exist "%RAMP_FILE%" (
    del /q "%RAMP_FILE%"
    echo [INFO] Removed stale: nodes\shader\lscherry\build_face_ramp.py
)
if exist "%INIT_FILE%" (
    powershell -NoProfile -Command "$f='%INIT_FILE%'; $lines=(Get-Content $f) | Where-Object { $_ -notmatch 'from \.build_face_ramp import' }; $lines | Set-Content $f -Encoding utf8"
)
goto :eof

:: Build addon zip package
:package
call :cleanup_stale_nodes
call :clean
echo.
echo [INFO] Packaging addon [!GIT_BRANCH!]...
if not exist "%FULL_DIST%" mkdir "%FULL_DIST%"

:: Create zip file at: dist\LSPotato_1.0.0.zip
set "ZIP_PATH=%FULL_DIST%\%ADDON_NAME%_!GIT_BRANCH!.zip"

python package.py "%FULL_SOURCE%" "%ZIP_PATH%"

if not exist "%ZIP_PATH%" (
    echo [ERROR] Failed to create zip package
    exit /b 1
)
echo [INFO] Created: %ZIP_PATH%
goto :eof

:: Install to Blender
:install
call :package
echo.
echo [INFO] Installing [!GIT_BRANCH!] as a Blender %BLENDER_VERSION% extension...

:: Verify the target Blender version is installed
if not exist "%BLENDER_BASE%\%BLENDER_VERSION%" (
    echo [ERROR] Blender %BLENDER_VERSION% not found at: "%BLENDER_BASE%\%BLENDER_VERSION%"
    echo [ERROR] Please verify Blender version and installation
    exit /b 1
)

:: Install as a local extension under the "user_default" repository.
:: (cmd's mkdir creates intermediate directories.)
if not exist "%ADDON_INSTALL_DIR%\%ADDON_NAME%" mkdir "%ADDON_INSTALL_DIR%\%ADDON_NAME%"
xcopy /Y /E /Q "%FULL_SOURCE%\*" "%ADDON_INSTALL_DIR%\%ADDON_NAME%\"

echo [INFO] Installed to: "%ADDON_INSTALL_DIR%\%ADDON_NAME%"
echo [INFO] Branch: !GIT_BRANCH!
echo [INFO] Restart Blender, then enable "HoTools" in Preferences ^> Add-ons.
echo [INFO] For a fully faithful test use Blender's "Install from Disk" on the
echo [INFO] dist zip, or run: blender --command extension validate
goto :eof

:: Remove from Blender
:uninstall
echo.
echo [INFO] Uninstalling from Blender %BLENDER_VERSION%...
set ADDON_PATH="%ADDON_INSTALL_DIR%\%ADDON_NAME%"

if exist %ADDON_PATH% (
    rmdir /s /q %ADDON_PATH%
    echo [INFO] Removed: %ADDON_PATH%
) else (
    echo [ERROR] Addon not found: %ADDON_PATH%
)
goto :eof

:: Run code checks
:test
echo.
echo [INFO] Running code checks (flake8)...
flake8 "%FULL_SOURCE%"
if errorlevel 1 (
    echo [ERROR] Code checks failed
    exit /b 1
) else (
    echo [SUCCESS] All tests passed!
)
goto :eof

:: Development shortcut (alias for install — package already runs clean)
:dev
call :install
echo.
echo [SUCCESS] Install complete for [!GIT_BRANCH!]!
goto :eof

:: Uninstall then re-install
:reload
call :uninstall
call :install
echo.
echo [SUCCESS] Reload complete for [!GIT_BRANCH!]!
echo !! Happy Cherrying !!
echo.
goto :eof

:: Auto-reload: watch src/ and reload on every change
:reload_auto
echo.
echo [INFO] Auto-reload mode [!GIT_BRANCH!] ^| Blender %BLENDER_VERSION%
echo [INFO] Watching: %FULL_SOURCE%
echo [INFO] Press Ctrl+C to stop.
echo.
call :reload
echo.
echo [INFO] Watching for changes...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object IO.FileSystemWatcher '%FULL_SOURCE%';$w.IncludeSubdirectories=$true;$w.EnableRaisingEvents=$true;$global:c=$false;$a={$n=$Event.SourceEventArgs.Name;if(-not($n.EndsWith('.pyc')-or$n-like'*__pycache__*')){$global:c=$true}};Register-ObjectEvent $w Changed -Action $a|Out-Null;Register-ObjectEvent $w Created -Action $a|Out-Null;Register-ObjectEvent $w Deleted -Action $a|Out-Null;Register-ObjectEvent $w Renamed -Action $a|Out-Null;while($true){Start-Sleep -Milliseconds 500;if($global:c){$global:c=$false;Write-Host '[WATCH] Change detected, waiting for writes to settle...';Start-Sleep -Seconds 1;exit 2}}"
if errorlevel 2 goto reload_auto
goto :eof

:: End of script
:eof
endlocal