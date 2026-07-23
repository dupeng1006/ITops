@echo off
chcp 936 >nul
rem ============================================================
rem  安联资管运维管理平台 - 卸载开机自启
rem  同时清理 NSSM 服务 / 计划任务 / 启动文件夹快捷方式（存在哪个清哪个）；
rem  无管理员权限时仅可清理当前用户的计划任务与启动文件夹快捷方式。
rem ============================================================
cd /d %~dp0
set NAME=O32OpsPlatform

net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [提示] 当前无管理员权限：仅清理当前用户的计划任务与启动文件夹快捷方式
)

echo 正在停止 o32-server.exe ...
taskkill /IM o32-server.exe /F >nul 2>&1

if exist "%~dp0nssm\nssm.exe" (
    "%~dp0nssm\nssm.exe" stop %NAME% >nul 2>&1
    "%~dp0nssm\nssm.exe" remove %NAME% confirm >nul 2>&1
    echo 已尝试移除 NSSM 服务 %NAME%（如存在）
)

schtasks /end /tn "%NAME%" >nul 2>&1
schtasks /delete /tn "%NAME%" /f >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo 已删除计划任务 %NAME%
) else (
    echo 未发现计划任务 %NAME%（或已删除）
)

del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\O32OpsPlatform.lnk" >nul 2>&1
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\O32OpsPlatform.lnk" (
    echo [提示] 启动文件夹快捷方式删除失败，可手动删除
) else (
    echo 已清理启动文件夹快捷方式（如存在）
)

echo 卸载完成。data\ 与 archive\ 目录保留未动，如需彻底清理请手动删除。
pause
