@echo off
rem ============================================================
rem  O32 日常运维平台 - 注册为开机自启服务（需管理员权限）
rem  优先使用 nssm\nssm.exe（如存在且可用），
rem  否则回退为系统内置"计划任务"（schtasks，SYSTEM 账户，开机自启）。
rem ============================================================
cd /d %~dp0
set NAME=O32OpsPlatform

net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 请以管理员身份运行本脚本（右键 -^> 以管理员身份运行）
    pause
    exit /b 1
)

if exist "%~dp0nssm\nssm.exe" (
    echo 检测到 NSSM，正在以 Windows 服务方式注册 %NAME% ...
    "%~dp0nssm\nssm.exe" install %NAME% "%~dp0app\o32-server.exe"
    if %ERRORLEVEL% EQU 0 (
        "%~dp0nssm\nssm.exe" set %NAME% AppDirectory "%~dp0"
        "%~dp0nssm\nssm.exe" set %NAME% AppStdout "%~dp0logs\service-out.log"
        "%~dp0nssm\nssm.exe" set %NAME% AppStderr "%~dp0logs\service-err.log"
        "%~dp0nssm\nssm.exe" set %NAME% Start SERVICE_AUTO_START
        "%~dp0nssm\nssm.exe" start %NAME%
        echo 完成：服务 %NAME% 已注册并启动（NSSM 方式，开机自启）
        echo 访问 http://127.0.0.1:8000/docs 验证
        pause
        exit /b 0
    ) else (
        echo [警告] NSSM 注册失败，回退为计划任务方式...
    )
)

echo 正在以计划任务方式注册 %NAME%（SYSTEM 账户，开机自启）...
schtasks /create /tn "%NAME%" /tr "\"%~dp0app\o32-server.exe\"" /sc onstart /ru SYSTEM /rl HIGHEST /f
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 计划任务注册失败
    pause
    exit /b 1
)
schtasks /run /tn "%NAME%"
echo 完成：计划任务 %NAME% 已创建并启动（开机自启）
echo 访问 http://127.0.0.1:8000/docs 验证
pause
