@echo off
chcp 936 >NUL
rem ============================================================
rem  安联资管运维管理平台 - 前台启动脚本
rem  用法：双击本文件，窗口停留显示日志
rem  停止：直接关闭本窗口，或运行 stop.bat
rem ============================================================
cd /d %~dp0
title 安联资管运维管理平台

rem 检查 8000 端口是否已被占用
netstat -ano | findstr ":8000" | findstr "LISTENING" >NUL
if %errorlevel% equ 0 (
    echo 端口 8000 已被占用，服务可能已在运行。
    echo 请直接访问 http://127.0.0.1:8000
    echo 如需重启，请先运行 stop.bat 关闭现有服务。
    pause
    exit /b 1
)

echo 正在启动 安联资管运维管理平台 ...
echo 服务地址：http://127.0.0.1:8000
echo 接口文档：http://127.0.0.1:8000/docs
echo 日志文件：%~dp0logs\server.log
echo.

"%~dp0app\o32-server.exe" --host 127.0.0.1 --port 8000

if %errorlevel% neq 0 (
    echo.
    echo 服务启动失败，请查看日志：%~dp0logs\server.log
    echo 错误码：%errorlevel%
    pause
)
