@echo off
rem ============================================================
rem  O32 日常运维平台 - 版本升级数据迁移工具
rem
rem  标准升级流程：
rem    1. 停止旧版本服务（关闭旧窗口或运行旧目录 stop.bat）
rem    2. 把新版本压缩包解压到旧版本【同级】目录
rem    3. 进入新版本目录，运行本脚本：upgrade.bat [旧版本目录]
rem       （不带参数时会自动列出同级旧版本供选择）
rem    4. 运行 start.bat 启动新版本
rem
rem  迁移内容：data（平台库/密钥/规则/模板/字典库）、
rem            archive（核对归档）、logs（运行日志）
rem  安全保障：旧目录原样保留作为回滚备份，
rem            确认新版本运行正常后可手动删除旧目录。
rem ============================================================
setlocal enabledelayedexpansion
cd /d %~dp0

echo ============================================================
echo  O32 日常运维平台 - 升级数据迁移
echo  新版本目录: %CD%
echo ============================================================
echo.

if not "%~1"=="" (
    set "OLD_DIR=%~f1"
    goto :check_old
)

rem 自动探测同级旧版本目录
set N=0
for /d %%D in ("%~dp0..\o32-ops-platform-v*") do (
    if /i not "%%~fD"=="%CD%" (
        set /a N+=1
        set "OLD!N!=%%~fD"
        echo   [!N!] %%~nxD
    )
)
if %N% EQU 0 (
    echo [错误] 未在同级目录找到旧版本（o32-ops-platform-v*）
    echo 请将新版本解压到旧版本同级目录，或用 upgrade.bat 旧目录路径 指定
    pause
    exit /b 1
)
echo.
set /p PICK=请输入旧版本序号、目录名或完整路径（1-%N%）：
if "%PICK%"=="" goto :bad_pick
set "PICK=%PICK:"=%"
rem 方式 1：序号（仅纯数字按序号解析，防止路径盘符冒号被 !var! 展开截断）
set "NONNUM="
for /f "delims=0123456789" %%X in ("%PICK%") do set "NONNUM=%%X"
if not defined NONNUM (
    set "OLD_DIR=!OLD%PICK%!"
)
if defined OLD_DIR goto :check_old
rem 方式 2：完整路径
if exist "%PICK%\data" (
    set "OLD_DIR=%PICK%"
    goto :check_old
)
rem 方式 3：目录名（与列表项匹配）
for /d %%D in ("%~dp0..\o32-ops-platform-v*") do (
    if /i "%%~nxD"=="%PICK%" (
        set "OLD_DIR=%%~fD"
        goto :check_old
    )
)
goto :bad_pick

:bad_pick
echo [错误] 无效输入，请输入列表中的序号、目录名或完整路径
pause
exit /b 1

:check_old
echo 旧版本目录: %OLD_DIR%
if not exist "%OLD_DIR%\data" (
    echo [错误] 旧目录下没有 data 文件夹，请确认路径是否正确
    pause
    exit /b 1
)
if not exist "%OLD_DIR%\data\o32ops.db" (
    echo [警告] 旧目录 data 下没有平台库 o32ops.db（旧版可能从未运行过）
    set /p NOGO=仍要继续迁移吗？（Y/N）:
    if /i not "!NOGO!"=="Y" exit /b 1
)
echo.
echo 请确认：旧版本服务已停止（旧窗口已关闭 / 已运行旧目录 stop.bat / 服务已停用）
set /p OK=确认已停止？（Y/N）:
if /i not "%OK%"=="Y" (
    echo 已取消。请先停止旧版本服务后重新运行本脚本
    pause
    exit /b 1
)
echo.

rem 字典库策略：旧目录已有 dictionary.db（可能含后续导入成果）优先保留；
rem 新包预置版重命名为 dictionary.db.pkg 备份，不强制覆盖
if exist "%OLD_DIR%\data\dictionary.db" (
    if exist "data\dictionary.db" (
        ren "data\dictionary.db" "dictionary.db.pkg"
        echo 已保留旧版字典库；新包预置字典备份为 data\dictionary.db.pkg
    )
)

echo [1/3] 迁移数据目录 data（平台库/密钥/规则/模板/字典库）...
robocopy "%OLD_DIR%\data" "data" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH
if %ERRORLEVEL% GEQ 8 goto :error

echo [2/3] 迁移归档目录 archive（核对原件与结果）...
if exist "%OLD_DIR%\archive" (
    robocopy "%OLD_DIR%\archive" "archive" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH
    if !ERRORLEVEL! GEQ 8 goto :error
) else (
    echo   旧目录无 archive，跳过
)

echo [3/3] 迁移日志目录 logs...
if exist "%OLD_DIR%\logs" (
    robocopy "%OLD_DIR%\logs" "logs" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH
    if !ERRORLEVEL! GEQ 8 goto :error
) else (
    echo   旧目录无 logs，跳过
)

echo.
echo ============================================================
echo  升级数据迁移完成！
echo ============================================================
echo  - 用户、规则、模板、数据源、历史任务、归档文件已全部迁移
echo  - 首次启动时服务端会自动完成数据库结构升级（启动日志可见）
echo  - 旧目录已原样保留作为回滚备份：
echo      %OLD_DIR%
echo    确认新版本运行正常后，可手动删除旧目录释放空间
echo.
echo  现在请运行 start.bat 启动新版本
echo ============================================================
pause
exit /b 0

:error
echo.
echo [错误] 迁移过程中断（robocopy 错误码 %ERRORLEVEL%）
echo 新旧目录数据未被破坏，请检查磁盘空间与文件占用后重试
pause
exit /b 1
