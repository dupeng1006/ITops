@echo off
chcp 936 >/dev/null
setlocal enabledelayedexpansion
cd /d %~dp0
title 安联资管运维管理平台 - 一键升级

rem ============================================================
rem  覆盖式一键升级：只更新程序，数据（账号/规则/模板/数据源/
rem  Trello/历史任务/归档/字典）原地保留，无需手动迁移。
rem  用法：解压新版包到任意位置，双击本脚本即可（自动定位）。
rem  安装目录默认 D:\O32-Ops；若不同，用 install-dir.txt 指定
rem  或作为第一个参数传入：upgrade.bat 安装目录
rem ============================================================

set "NEW_DIR=%CD%"
set "INSTALL_DIR=D:\O32-Ops"
if not "%~1"=="" set "INSTALL_DIR=%~f1"
if exist "%INSTALL_DIR%\install-dir.txt" set /p INSTALL_DIR=<"%INSTALL_DIR%\install-dir.txt"

echo ============================================================
echo  安联资管运维管理平台 - 一键升级（数据自动保留）
echo ============================================================
echo   新版本程序: %NEW_DIR%\app
echo   安装目录  : %INSTALL_DIR%
echo.

if not exist "%NEW_DIR%\app\o32-server.exe" (
    echo [错误] 未找到新程序 %NEW_DIR%\app\o32-server.exe
    echo 请在新版本解压目录内运行本脚本
    pause
    exit /b 1
)

if not exist "%INSTALL_DIR%\app\o32-server.exe" goto :fresh

rem ---------- 覆盖升级（数据保留） ----------
echo 检测到已安装实例，执行【覆盖升级：仅更新程序，数据保留】
echo.
echo [1/4] 停止正在运行的服务 ...
taskkill /F /IM o32-server.exe >/dev/null 2>&1
timeout /t 2 /nobreak >/dev/null

echo [2/4] 备份当前数据到 backups 目录 ...
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TS=%%I"
if not exist "%INSTALL_DIR%\backups" mkdir "%INSTALL_DIR%\backups"
robocopy "%INSTALL_DIR%\data" "%INSTALL_DIR%\backups\data-!TS!" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH >/dev/null
echo   数据已备份到 backups\data-!TS!

echo [3/4] 用新程序覆盖安装目录 app（数据目录不动）...
robocopy "%NEW_DIR%\app" "%INSTALL_DIR%\app" /E /COPY:DAT /MIR /R:2 /W:2 /NFL /NDL /NJH >/dev/null
if !ERRORLEVEL! GEQ 8 goto :error

echo [4/4] 更新启动/停止等脚本 ...
for %%F in (start.bat stop.bat install.bat uninstall.bat upgrade.bat) do (
    if exist "%NEW_DIR%\%%F" copy /Y "%NEW_DIR%\%%F" "%INSTALL_DIR%\%%F" >/dev/null
)

echo.
echo ============================================================
echo  升级完成！数据已自动保留，无需手动迁移：
echo  账号 / 规则 / 模板 / 数据源 / Trello / 历史任务 / 归档均在
echo  旧数据已备份到 %INSTALL_DIR%\backups\
echo  首次启动会自动完成数据库结构升级（启动日志可见）
echo  请运行 %INSTALL_DIR%\start.bat 启动
echo ============================================================
pause
exit /b 0

:fresh
echo 未检测到已安装实例，执行【全新安装】到 %INSTALL_DIR% ...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
for %%D in (app data archive logs nssm) do (
    if exist "%NEW_DIR%\%%D" robocopy "%NEW_DIR%\%%D" "%INSTALL_DIR%\%%D" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH >/dev/null
)
for %%F in (start.bat stop.bat install.bat uninstall.bat upgrade.bat) do (
    if exist "%NEW_DIR%\%%F" copy /Y "%NEW_DIR%\%%F" "%INSTALL_DIR%\%%F" >/dev/null
)
echo %INSTALL_DIR%>"%INSTALL_DIR%\install-dir.txt"
echo.
echo ============================================================
echo  全新安装完成！数据目录已固定在 %INSTALL_DIR%\data
echo  今后升级只更新程序、数据原地保留，不会再丢失
echo  请运行 %INSTALL_DIR%\start.bat 启动
echo ============================================================
pause
exit /b 0

:error
echo.
echo [错误] 升级中断，robocopy 错误码 !ERRORLEVEL!
echo 新旧目录数据均未被破坏，请检查磁盘空间与文件占用后重试
pause
exit /b 1
