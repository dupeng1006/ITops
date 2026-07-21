NSSM（the Non-Sucking Service Manager）2.24 win64

来源：官方网站 https://nssm.cc/release/nssm-2.24.zip（2026-07-17 下载）
nssm-2.24.zip SHA-256: 727d1e42275c605e0f04aba98095c38a8e1e46def453cdffce42869428aa6743
nssm.exe     SHA-256: f689ee9af94b00e9e3f0bb072b34caaf207f32dcb4f5782fc9ca351df9a06c97
许可：Public Domain（公有领域，可自由随包分发）

用途：install.bat 检测到本文件存在时，优先以 NSSM 将 o32-server.exe
注册为 Windows 服务（开机自启）。如目标服务器策略拦截 NSSM，
install.bat 会自动回退为系统内置"计划任务"方式（schtasks，无需第三方程序）。

注意：NSSM 在本打包机的非交互构建会话中未能完成运行验证（进程挂起，
疑似终端安全软件沙箱拦截）；目标服务器首次使用前请管理员先执行
nssm\nssm.exe version 自检，若无法运行则删除本目录，install.bat 将
自动使用计划任务方式。
