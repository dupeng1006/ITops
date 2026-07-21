@echo off
rem ============================================================
rem  O32 日常运维平台 - 卸载自启服务（需管理员权限）
rem  同时清理 NSSM 服务与计划任务两种注册方式（存在哪个清哪个）
rem ============================================================
cd /d %~dp0
set NAME=O32OpsPlatform

net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 请以管理员身份运行本脚本（右键 -^> 以管理员身份运行）
    pause
    exit /b 1
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

echo 卸载完成。data\ 与 archive\ 目录保留未动，如需彻底清理请手动删除。
pause
