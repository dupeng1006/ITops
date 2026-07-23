@echo off
rem ============================================================
rem  O32 日常运维平台 - 一键构建部署包（前端 + 后端 + 组装 + 压缩）
rem  用法（Windows，双击或命令行）：server\packaging\build.bat
rem  产物：package\o32-ops-platform-v%VERSION%\ 与同名 .zip
rem  前置：构建机需具备 Node 运行时（便携版即可），
rem        通过 set NODE_HOME=... 指定，默认取本机已知便携路径。
rem ============================================================
setlocal
cd /d %~dp0\..
set PY=.venv\Scripts\python.exe
set VERSION=0.6.6
set PKGROOT=..\package
set PKGDIR=%PKGROOT%\o32-ops-platform-v%VERSION%
rem 便携 Node 路径（可用 set NODE_HOME=... 覆盖；默认为本机 kimi-desktop 内置运行时）
if not defined NODE_HOME set "NODE_HOME=C:\Users\peng.du\AppData\Local\Programs\kimi-desktop\resources\resources\runtime"

echo [1/6] 构建前端（client）...
if not exist "%NODE_HOME%\node.exe" (
    echo [错误] 未找到 Node 运行时: %NODE_HOME%
    echo 请安装 Node 或用 set NODE_HOME=便携Node目录 指定后重试
    exit /b 1
)
pushd ..\client
set "PATH=%NODE_HOME%;%PATH%"
if not exist node_modules (
    call npm.cmd ci --registry=https://registry.npmmirror.com
    if %ERRORLEVEL% NEQ 0 ( popd & goto :error )
)
call npm.cmd run build
if %ERRORLEVEL% NEQ 0 ( popd & goto :error )
popd

echo [2/6] 清理旧构建产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/6] PyInstaller 打包（onedir, console）...
%PY% -m PyInstaller --noconfirm --clean packaging\build.spec
if %ERRORLEVEL% NEQ 0 goto :error

echo [4/6] 组装部署目录 %PKGDIR% ...
if exist "%PKGDIR%" rmdir /s /q "%PKGDIR%"
mkdir "%PKGDIR%\app" "%PKGDIR%\data" "%PKGDIR%\archive" "%PKGDIR%\logs" "%PKGDIR%\nssm"
xcopy /E /I /Q "dist\o32-server" "%PKGDIR%\app" >nul
xcopy /E /I /Q "..\client\dist" "%PKGDIR%\app\web" >nul
copy /Y packaging\deploy\start.bat "%PKGDIR%\" >nul
copy /Y packaging\deploy\stop.bat "%PKGDIR%\" >nul
copy /Y packaging\deploy\install.bat "%PKGDIR%\" >nul
copy /Y packaging\deploy\uninstall.bat "%PKGDIR%\" >nul
copy /Y packaging\deploy\upgrade.bat "%PKGDIR%\" >nul
if exist packaging\nssm\nssm.exe copy /Y packaging\nssm\nssm.exe "%PKGDIR%\nssm\" >nul
if exist packaging\nssm\README.txt copy /Y packaging\nssm\README.txt "%PKGDIR%\nssm\" >nul
rem 数据字典库随包预置（PDM 已导入成果，目标机开箱即可查询；亦可在平台上重新导入覆盖）
if exist data\dictionary.db copy /Y data\dictionary.db "%PKGDIR%\data\" >nul

echo [5/6] 生成 版本.txt 与 依赖清单.txt ...
%PY% packaging\gen_pkg_info.py "%PKGDIR%" "%VERSION%"
if %ERRORLEVEL% NEQ 0 goto :error

echo [6/6] 压缩 zip ...
rem 清除可能因测试启动产生的运行时文件（o32ops.db/secret.key/server.log 等）
rem 确保交付包不含测试数据，用户首启时自动生成干净库
if exist "%PKGDIR%\data\o32ops.db" del /f /q "%PKGDIR%\data\o32ops.db" >nul 2>&1
if exist "%PKGDIR%\data\o32ops.db-shm" del /f /q "%PKGDIR%\data\o32ops.db-shm" >nul 2>&1
if exist "%PKGDIR%\data\o32ops.db-wal" del /f /q "%PKGDIR%\data\o32ops.db-wal" >nul 2>&1
if exist "%PKGDIR%\data\secret.key" del /f /q "%PKGDIR%\data\secret.key" >nul 2>&1
if exist "%PKGDIR%\logs\server.log" del /f /q "%PKGDIR%\logs\server.log" >nul 2>&1
rem PowerShell 兜底：PATH 中无 powershell 时使用系统全路径
set "PSHELL=powershell"
where powershell >nul 2>nul || set "PSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PSHELL%" -NoProfile -Command "if (Test-Path '%PKGROOT%\o32-ops-platform-v%VERSION%.zip') { Remove-Item '%PKGROOT%\o32-ops-platform-v%VERSION%.zip' -Force }; Compress-Archive -Path '%PKGDIR%' -DestinationPath '%PKGROOT%\o32-ops-platform-v%VERSION%.zip'"
if %ERRORLEVEL% NEQ 0 goto :error

echo.
echo [OK] Build finished.
echo [OK] package dir: %PKGDIR%
echo [OK] package zip: %PKGROOT%\o32-ops-platform-v%VERSION%.zip
exit /b 0

:error
echo.
echo [错误] 构建失败，请检查上方输出
exit /b 1
