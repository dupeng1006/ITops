@echo off
chcp 936 >NUL
rem ============================================================
rem  test
rem ============================================================
echo hello >NUL
taskkill /IM notepad.exe /F >NUL
if %ERRORLEVEL% EQU 0 (
    echo stopped
) else (
    echo not running
)
