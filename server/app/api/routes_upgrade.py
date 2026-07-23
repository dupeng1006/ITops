# -*- coding: utf-8 -*-
r"""
安联资管运维管理平台 —— 在线升级接口（v0.6.9 起）

设计理念（数据连续性根治）：
    平台数据（账号/规则/配置/历史任务/归档）全部落在后台数据库与固定数据目录，
    与程序目录物理分离。升级 = 仅替换 app\ 程序目录，数据原地不动。
    本接口把升级动作收进系统内部：管理员在页面上传新版部署包 zip 后，
    服务端自动完成【校验 → 备份数据 → 替换程序 → 自重启 → 启动确认留痕】，
    全程无需人工执行任何脚本。

流程：
    1. POST /api/admin/system/upgrade 上传 zip（admin，冻结态才可用）；
    2. 服务端校验包结构（必须含 app/o32-server.exe），解出 app/ 与 *.bat 到
       临时目录 <安装根>/upgrade/staging-<时间戳>；
    3. 生成独立 updater 批处理（脱离服务进程运行）：等待本进程退出 →
       备份 data 到 backups/data-<时间戳> → robocopy 覆盖 app →
       更新 *.bat → 更新字典库 dictionary.db（如有）→ 以原参数重启服务；
    4. 写入 pending 标记并审计"发起升级"，2.5 秒后本进程自杀，
       由 updater 完成替换并拉起新进程；
    5. 新进程启动时（main.lifespan）核对版本号，审计"升级完成/失败"。

作者：技术部
版本：1.0.0
日期：2026-07-23
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_roles
from app.core.version import get_install_info, get_version
from app.models.entities import SysUser
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

MENU_UPGRADE = "系统管理 · 版本升级"

router = APIRouter(prefix="/api/admin/system", tags=["版本升级"])

_MAX_PKG_SIZE = 500 * 1024 * 1024  # 上传包上限 500MB
_CHUNK = 4 * 1024 * 1024


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _upgrade_dir() -> Path:
    """升级工作目录：<安装根>/upgrade（仅冻结态有意义）"""
    info = get_install_info()
    d = Path(info["install_root"]) / "upgrade"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/version", summary="当前版本与部署信息")
def current_version(
    user: SysUser = Depends(require_roles("admin", "operator")),
):
    info = get_install_info()
    return {
        "version": get_version(),
        "frozen": info["frozen"],
        "install_root": info["install_root"],
        "data_dir": info["data_dir"],
        "archive_dir": info["archive_dir"],
        "upgrade_supported": info["frozen"],
        "pending_upgrade": (_upgrade_dir() / "pending.json").exists() if info["frozen"] else False,
    }


def _parse_pkg_version(zf: zipfile.ZipFile, exe_member: str) -> str:
    """从包内路径推断版本号：o32-ops-platform-v0.6.9/app/o32-server.exe → 0.6.9"""
    m = re.match(r"^o32-ops-platform-v([0-9][0-9A-Za-z.\-]*)/", exe_member.replace("\\", "/"))
    return m.group(1) if m else "未知版本"


def _extract_staging(pkg_path: Path, staging: Path) -> tuple[str, str]:
    """
    校验并解出升级所需内容到 staging 目录。
    返回 (新版本号, 新 app 目录路径)。不合法抛 HTTPException。
    只解 app/**、根级 *.bat、data/dictionary.db —— 绝不触碰 data 库与密钥。
    """
    try:
        zf = zipfile.ZipFile(pkg_path)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="上传文件不是合法的 zip 压缩包")

    with zf:
        names = zf.namelist()
        exe_members = [n for n in names if n.replace("\\", "/").endswith("app/o32-server.exe")]
        if not exe_members:
            raise HTTPException(
                status_code=400,
                detail="部署包结构不完整：未找到 app/o32-server.exe，请确认上传的是平台官方部署包 zip",
            )
        exe_member = exe_members[0].replace("\\", "/")
        prefix = exe_member[: -len("app/o32-server.exe")]  # 如 "o32-ops-platform-v0.6.9/"
        to_version = _parse_pkg_version(zf, exe_member)

        app_dir = staging / "app"
        extracted_bats = 0
        has_dict = False
        for n in names:
            p = n.replace("\\", "/")
            if not p.startswith(prefix):
                continue
            rel = p[len(prefix):]
            if not rel or rel.endswith("/"):
                continue
            if rel.startswith("app/"):
                target = staging / rel
            elif rel.startswith("data/"):
                # 仅字典库允许随升级更新（纯参考数据，不含任何用户数据）
                if rel == "data/dictionary.db":
                    target = staging / rel
                    has_dict = True
                else:
                    continue
            elif "/" not in rel and rel.lower().endswith(".bat"):
                target = staging / rel
                extracted_bats += 1
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(n) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(_CHUNK)
                    if not chunk:
                        break
                    dst.write(chunk)

        if not (app_dir / "o32-server.exe").exists():
            raise HTTPException(status_code=400, detail="部署包解出失败：缺少 app/o32-server.exe")
        logger.info("升级包解出完成: 版本=%s, bat脚本=%d个, 含字典库=%s", to_version, extracted_bats, has_dict)
        return to_version, str(app_dir)


def _build_updater_bat(staging: Path, to_version: str, restart_args: list[str]) -> Path:
    """生成独立 updater 批处理（GBK 编码，脱离服务进程执行）"""
    info = get_install_info()
    root = Path(info["install_root"])
    up_dir = _upgrade_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    args = " ".join(restart_args)

    lines = [
        "@echo off",
        "chcp 936 >nul",
        "setlocal enabledelayedexpansion",
        f'set "ROOT={root}"',
        f'set "STAGE={staging}"',
        f'set "LOG={up_dir / ("updater-" + ts + ".log")}"',
        'set "SVC=O32OpsPlatform"',
        f'echo [%date% %time%] updater 启动，目标版本 {to_version} > "%LOG%"',
        "",
        "rem ---------- 0. 判断运行方式：Windows 服务 / 计划任务 / 前台 ----------",
        "set \"SVC_OK=0\"",
        "sc query %SVC% >nul 2>&1 && set \"SVC_OK=1\"",
        "set \"TASK_OK=0\"",
        'if "!SVC_OK!"=="0" schtasks /query /tn %SVC% >nul 2>&1 && set "TASK_OK=1"',
        'echo [%date% %time%] 服务模式=!SVC_OK! 计划任务=!TASK_OK! >> "%LOG%"',
        "",
        "rem ---------- 1. 停止服务（先按服务/任务方式停，防止自动拉起旧程序） ----------",
        'if "!SVC_OK!"=="1" net stop %SVC% >nul 2>&1',
        'if "!TASK_OK!"=="1" schtasks /end /tn %SVC% >nul 2>&1',
        "ping -n 3 127.0.0.1 >nul",
        "taskkill /F /IM o32-server.exe >nul 2>&1",
        "ping -n 3 127.0.0.1 >nul",
        'echo [%date% %time%] 旧进程已停止 >> "%LOG%"',
        "",
        "rem ---------- 2. 备份数据（安全垫，数据本身不动） ----------",
        'set "BTS=%RANDOM%%RANDOM%"',
        "where powershell >nul 2>&1",
        'if !ERRORLEVEL! EQU 0 for /f %%I in (\'powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"\') do set "BTS=%%I"',
        'if not exist "%ROOT%\\backups" mkdir "%ROOT%\\backups"',
        'robocopy "%ROOT%\\data" "%ROOT%\\backups\\data-!BTS!" /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NJH >nul',
        'echo [%date% %time%] 数据已备份到 backups\\data-!BTS! >> "%LOG%"',
        "",
        "rem ---------- 3. 覆盖程序目录（数据目录不动） ----------",
        'robocopy "%STAGE%\\app" "%ROOT%\\app" /E /COPY:DAT /MIR /R:2 /W:2 /NFL /NDL /NJH >> "%LOG%"',
        "set \"RC=!ERRORLEVEL!\"",
        'echo [%date% %time%] 程序覆盖 robocopy 返回码 !RC! >> "%LOG%"',
        "if !RC! GEQ 8 (",
        '    echo [%date% %time%] 程序覆盖失败 >> "%LOG%"',
        '    echo FAIL> "' + str(up_dir / "last-result.txt") + '"',
        "    exit /b 1",
        ")",
        "",
        "rem ---------- 4. 更新根目录 *.bat 与字典库（如有） ----------",
        'for %%F in ("%STAGE%\\*.bat") do copy /Y "%%F" "%ROOT%\\" >nul',
        'if exist "%STAGE%\\data\\dictionary.db" copy /Y "%STAGE%\\data\\dictionary.db" "%ROOT%\\data\\dictionary.db" >nul',
        "",
        "rem ---------- 5. 重启服务（服务/计划任务/静默启动器/前台 四种方式自适应） ----------",
        'if "!SVC_OK!"=="1" (',
        "    net start %SVC% >> \"%LOG%\" 2>&1",
        ') else if "!TASK_OK!"=="1" (',
        "    schtasks /run /tn %SVC% >> \"%LOG%\" 2>&1",
        ') else if exist "%ROOT%\\start-hidden.vbs" (',
        "    wscript.exe \"%ROOT%\\start-hidden.vbs\"",
        ') else (',
        '    cd /d "%ROOT%\\app"',
        f'    start "" /min "%ROOT%\\app\\o32-server.exe" {args}',
        ')',
        'echo [%date% %time%] 新进程已拉起 >> "%LOG%"',
        'echo OK ' + to_version + '> "' + str(up_dir / "last-result.txt") + '"',
        "",
        "rem ---------- 6. 清理临时文件 ----------",
        'cd /d "%ROOT%"',
        'rmdir /s /q "%STAGE%" >nul 2>&1',
        'del /f /q "%~f0" >nul 2>&1',
        "exit /b 0",
        "",
    ]
    bat_path = up_dir / f"updater-{ts}.bat"
    bat_path.write_bytes("\r\n".join(lines).encode("gbk", errors="replace"))
    return bat_path


def _self_exit() -> None:
    """延迟自杀：给响应返回留出时间，updater 已独立运行"""
    time.sleep(2.5)
    logger.info("在线升级：服务进程退出，由 updater 完成程序替换并重启")
    os._exit(0)


@router.post("/upgrade", summary="上传部署包在线升级（admin，数据自动保留）")
async def online_upgrade(
    request: Request,
    file: UploadFile = File(...),
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    info = get_install_info()
    if not info["frozen"]:
        raise HTTPException(status_code=400, detail="当前为源码运行环境，在线升级仅对部署版（exe）开放")

    up_dir = _upgrade_dir()
    if (up_dir / "pending.json").exists():
        raise HTTPException(status_code=409, detail="已有升级任务进行中，请等待服务重启完成后再试")

    filename = file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail=f"请上传平台部署包 zip 文件（当前文件：{filename}）")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    pkg_path = up_dir / f"pkg-{ts}.zip"
    staging = up_dir / f"staging-{ts}"

    # 1. 流式落盘（限 500MB）
    total = 0
    try:
        with open(pkg_path, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_PKG_SIZE:
                    out.close()
                    pkg_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="部署包超过 500MB 上限，已拒绝")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        pkg_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"部署包接收失败: {e}")

    # 2. 校验 + 解出
    from_version = get_version()
    try:
        to_version, _ = _extract_staging(pkg_path, staging)
    except HTTPException:
        pkg_path.unlink(missing_ok=True)
        raise
    # 解出完成后 zip 不再有用（updater 只用 staging），及时清理避免堆积占盘
    pkg_path.unlink(missing_ok=True)

    # 3. 生成 updater 并写入 pending 标记
    restart_args = [a for a in sys.argv[1:]]
    bat_path = _build_updater_bat(staging, to_version, restart_args)
    pending = {
        "from_version": from_version,
        "to_version": to_version,
        "by": user.username,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pkg": filename,
    }
    (up_dir / "pending.json").write_text(
        json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 4. 审计（发起）
    record_audit(
        db, user.username, "system_upgrade_start", "system", None,
        f"发起在线升级：{from_version} → {to_version}（包：{filename}）。"
        f"数据目录不动，updater 已接管：备份→覆盖程序→自动重启",
        _client_ip(request), menu=MENU_UPGRADE,
    )
    db.commit()

    # 5. 拉起独立 updater（脱离本进程），随后自杀
    log_file = open(up_dir / f"upgrade-{ts}.out", "ab")
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        cwd=str(Path(info["install_root"])),
        stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    logger.info("在线升级：updater 已启动（%s），本进程 2.5 秒后退出", bat_path)
    threading.Thread(target=_self_exit, daemon=True).start()

    return {
        "message": f"升级已开始：{from_version} → {to_version}。服务将在数秒内自动重启，请稍候刷新页面",
        "from_version": from_version,
        "to_version": to_version,
    }


def confirm_pending_upgrade() -> None:
    """
    启动期调用（main.lifespan）：若存在升级 pending 标记，核对版本并审计留痕。
    版本一致 → system_upgrade_success；不一致 → system_upgrade_failed。
    """
    try:
        info = get_install_info()
        if not info["frozen"]:
            return
        marker = Path(info["install_root"]) / "upgrade" / "pending.json"
        if not marker.exists():
            return
        try:
            pending = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pending = {}
        current = get_version()
        expected = str(pending.get("to_version", ""))
        by = str(pending.get("by", "unknown"))
        from_v = str(pending.get("from_version", "unknown"))

        from app.models.database import get_session_factory

        db = get_session_factory()()
        try:
            if expected not in ("未知版本", "") and current == expected:
                record_audit(
                    db, by, "system_upgrade_success", "system", None,
                    f"在线升级完成：{from_v} → {current}，服务已自动重启，数据完整保留",
                    "127.0.0.1", menu=MENU_UPGRADE,
                )
                logger.info("在线升级确认成功：%s → %s", from_v, current)
            else:
                record_audit(
                    db, by, "system_upgrade_failed", "system", None,
                    f"在线升级版本核对异常：期望 {expected}，当前 {current}。"
                    f"请检查 upgrade 目录日志，必要时从 backups 还原数据后用旧包恢复",
                    "127.0.0.1", menu=MENU_UPGRADE,
                )
                logger.warning("在线升级版本核对异常：期望 %s，当前 %s", expected, current)
            db.commit()
        finally:
            db.close()
        marker.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        logger.exception("升级 pending 标记处理失败（不影响启动）")
