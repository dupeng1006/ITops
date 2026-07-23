@echo off
chcp 936 >nul
rem ============================================================
rem  安联资管运维管理平台 - 注册开机自启
rem  有管理员权限：优先 NSSM 服务，失败回退 SYSTEM 计划任务（开机自启）；
rem  无管理员权限：自动回退为"登录自动启动"（启动文件夹 + 静默启动器，
rem  当前用户登录时后台启动，无窗口，无需管理员）。
rem ============================================================
cd /d %~dp0
set NAME=O32OpsPlatform

net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto :userlogon
goto :admin

:userlogon
echo 检测到当前账号无管理员权限，改用"登录自动启动（启动文件夹）"方式注册 %NAME% ...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "PSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PSHELL%" -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%STARTUP%\O32OpsPlatform.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%~dp0start-hidden.vbs\"'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Description='安联资管运维管理平台 静默自启'; $s.Save()"
if errorlevel 1 (
    echo [错误] 启动文件夹快捷方式创建失败
    pause
    exit /b 1
)
echo 完成：已创建登录自动启动（当前用户登录时后台静默启动，无窗口）
echo 如需立即启动：wscript.exe "%~dp0start-hidden.vbs"
echo 访问 http://127.0.0.1:8000/docs 验证
pause
exit /b 0

:admin
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
