@echo off
rem ============================================================
rem  O32 日常运维平台 - 停止服务（免服务方式启动的实例）
rem ============================================================
cd /d %~dp0
taskkill /IM o32-server.exe /F >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo 已停止 o32-server.exe
) else (
    echo 未发现运行中的 o32-server.exe（或已停止）
)
pause
