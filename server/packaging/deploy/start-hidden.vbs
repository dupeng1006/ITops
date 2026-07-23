' 安联资管运维管理平台 - 静默启动器（无窗口）
' 由 install.bat（非管理员回退）写入启动文件夹调用，也可手动执行：
'   wscript.exe "D:\O32-Ops\start-hidden.vbs"
Dim shell, fso, exe, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
exe = fso.GetParentFolderName(WScript.ScriptFullName) & "\app\o32-server.exe"
' 已在运行则不重复启动
Dim svc, running
running = False
For Each svc In GetObject("winmgmts:").ExecQuery("Select ProcessId from Win32_Process Where Name='o32-server.exe'")
    running = True
Next
If Not running Then
    shell.CurrentDirectory = fso.GetParentFolderName(exe)
    shell.Run """" & exe & """", 0, False
End If
