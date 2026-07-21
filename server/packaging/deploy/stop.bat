@echo off
chcp 936 >/dev/null
rem ============================================================
rem  安联资管运维管理平台 - 停止前台服务
rem ============================================================
cd /d %~dp0
taskkill /IM o32-server.exe /F >/dev/null 2>&1
if %ERRORLEVEL% EQU 0 (
    echo 已停止 o32-server.exe
) else (
    echo 未找到运行中的 o32-server.exe，或已停止
)
pause
